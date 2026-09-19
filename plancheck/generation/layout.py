"""Deterministic room packing. Every storey tiles its plate exactly.

One scheme covers all four uses: a core strip holding the stair in the same
place on every storey, a corridor band, and two room bands loaded off that
corridor. Rooms are sized by their target areas and never fall below their
minimum side, so a plan that cannot fit is reported instead of drawn badly.
"""

from __future__ import annotations

from plancheck.generation import defaults
from plancheck.generation.program import (
    MIN_ROOM_SIDE_FT,
    BuildingProgram,
    FloorLayout,
    RoomRect,
    SpaceSpec,
    snap,
)

CORE_MIN_WIDTH_FT = 7.0
CORE_MAX_WIDTH_FT = 16.0
# A stair run plus landings is about twelve feet, and the front band inherits
# this depth, so it also has to be deep enough to hold a real room.
STAIR_MIN_DEPTH_FT = 12.0
SLENDER_RATIO = 2.5
MAX_ASPECT = 4.0


class LayoutError(ValueError):
    """The program cannot fit the plate; the caller may ask the model to revise."""


def _distribute(span: float, items: list[SpaceSpec], floors: list[float]) -> list[float]:
    """Split a span by target area, never below each room's minimum side."""
    if not items:
        return []
    floors = [min(f, span / len(items)) for f in floors]
    if sum(floors) > span + 1e-6:
        raise LayoutError(
            f"{len(items)} rooms need at least {sum(floors):.1f} ft but only {span:.1f} ft is available"
        )
    total = sum(max(s.target_area_sqft, 1.0) for s in items)
    sizes = [span * max(s.target_area_sqft, 1.0) / total for s in items]
    # Water-fill: lift anything under its minimum, pay for it from the rooms with slack.
    for _ in range(len(items) + 1):
        deficit = sum(max(0.0, floors[i] - sizes[i]) for i in range(len(items)))
        if deficit <= 1e-9:
            break
        slack = sum(max(0.0, sizes[i] - floors[i]) for i in range(len(items)))
        if slack <= 1e-9:
            raise LayoutError("Rooms cannot all meet their minimum side on this plate")
        for i in range(len(items)):
            if sizes[i] > floors[i]:
                sizes[i] -= deficit * (sizes[i] - floors[i]) / slack
            else:
                sizes[i] = floors[i]
    return sizes


def _cut(start: float, end: float, items: list[SpaceSpec], floors: list[float]) -> list[tuple[float, float]]:
    """Grid-snapped cut positions; both sides of every cut share one coordinate."""
    sizes = _distribute(end - start, items, floors)
    edges = [start]
    position = start
    for size in sizes[:-1]:
        position = snap(position + size)
        edges.append(position)
    edges.append(end)
    bands = list(zip(edges, edges[1:]))
    for (lo, hi), space in zip(bands, items):
        if hi - lo < MIN_ROOM_SIDE_FT - 1e-6:
            raise LayoutError(
                f"{space.name} would be only {hi - lo:.1f} ft across; "
                "reduce the room count or increase the floor area"
            )
    return bands


def _floors_for(items: list[SpaceSpec], span: float, shared: float) -> list[float]:
    """Minimum extent along the split axis.

    ``min_side_ft`` constrains a room's narrow dimension. If the dimension the
    rooms already share is wide enough to satisfy it, only the absolute floor
    applies along the axis being cut -- otherwise a 45 sqft powder room with an
    8 ft minimum would demand 8 ft in both directions.
    """
    return [
        max(
            MIN_ROOM_SIDE_FT,
            min(MIN_ROOM_SIDE_FT if shared >= s.min_side_ft else s.min_side_ft, span / max(1, len(items))),
        )
        for s in items
    ]


def _cluster(items: list[SpaceSpec], depth: float, span: float) -> list[list[SpaceSpec]]:
    """Stack rooms too narrow for a full-depth slot instead of stretching them.

    A 45 sqft powder room in a 20 ft deep band would be drawn 2 ft wide. Pairing
    it with a neighbour lets them share one slot and split it front to back. The
    test uses the width a room will really be given -- the band is shared out in
    proportion, so a plate with slack makes every slot wider than its target.
    """
    depth = max(depth, 1.0)
    total = sum(max(s.target_area_sqft, 1.0) for s in items) or 1.0
    width_of = lambda space: span * max(space.target_area_sqft, 1.0) / total
    # A full-depth slot is only reasonable if the room will not end up a corridor
    # of its own: a 90 sqft washroom must not be drawn 5 ft by 38 ft.
    slot = max(MIN_ROOM_SIDE_FT, depth / MAX_ASPECT)
    # Enough stacked rooms to be worth a slot, but never so many they go slivery.
    limit = max(2, int(depth // (2 * MIN_ROOM_SIDE_FT)))
    groups: list[list[SpaceSpec]] = []
    pending: list[SpaceSpec] = []

    def flush() -> None:
        nonlocal pending
        if pending:
            groups.append(pending)
            pending = []

    for space in items:
        if width_of(space) >= slot:
            flush()
            groups.append([space])
            continue
        pending.append(space)
        if sum(width_of(s) for s in pending) >= depth / SLENDER_RATIO or len(pending) >= limit:
            flush()
    flush()

    # A lone room that still cannot reach a workable width joins its neighbour.
    merged: list[list[SpaceSpec]] = []
    for group in groups:
        if len(group) == 1 and width_of(group[0]) < slot and merged:
            merged[-1] = merged[-1] + group
        else:
            merged.append(group)
    if len(merged) > 1 and len(merged[0]) == 1 and width_of(merged[0][0]) < slot:
        merged[1] = merged[0] + merged[1]
        merged.pop(0)
    return merged


def _row(
    x1: float, y1: float, x2: float, y2: float, items: list[SpaceSpec]
) -> list[RoomRect]:
    """Lay rooms side by side across a horizontal band, stacking the small ones."""
    if not items:
        return []
    depth = y2 - y1
    groups = _cluster(items, depth, x2 - x1)
    slots = [
        SpaceSpec(
            id=group[0].id,
            name=group[0].name,
            floor_id=group[0].floor_id,
            target_area_sqft=sum(s.target_area_sqft for s in group),
            min_side_ft=group[0].min_side_ft if len(group) == 1 else MIN_ROOM_SIDE_FT,
        )
        for group in groups
    ]
    rects: list[RoomRect] = []
    for (lo, hi), group in zip(_cut(x1, x2, slots, _floors_for(slots, x2 - x1, depth)), groups):
        if len(group) == 1:
            rects.append(RoomRect(space_id=group[0].id, x1=lo, y1=y1, x2=hi, y2=y2))
        else:
            rects.extend(_column(lo, y1, hi, y2, group))
    return rects


def _column(
    x1: float, y1: float, x2: float, y2: float, items: list[SpaceSpec]
) -> list[RoomRect]:
    """Stack rooms up a vertical strip."""
    return [
        RoomRect(space_id=space.id, x1=x1, y1=lo, x2=x2, y2=hi)
        for (lo, hi), space in zip(_cut(y1, y2, items, _floors_for(items, y2 - y1, x2 - x1)), items)
    ]


def _ordered(use: str, spaces: list[SpaceSpec]) -> list[SpaceSpec]:
    ranking = defaults.profile(use).ordering
    def rank(space: SpaceSpec) -> tuple[int, float, str]:
        try:
            index = ranking.index(space.category)
        except ValueError:
            index = len(ranking)
        return (index, -space.target_area_sqft, space.id)
    return sorted(spaces, key=rank)


def _split_bands(spaces: list[SpaceSpec]) -> tuple[list[SpaceSpec], list[SpaceSpec]]:
    """Deal rooms into two corridor-facing bands with roughly equal depth."""
    front: list[SpaceSpec] = []
    back: list[SpaceSpec] = []
    front_area = back_area = 0.0
    for space in spaces:
        if front_area <= back_area:
            front.append(space)
            front_area += space.target_area_sqft
        else:
            back.append(space)
            back_area += space.target_area_sqft
    return front, back


def core_dimensions(program: BuildingProgram, width_ft: float, depth_ft: float) -> tuple[float, float]:
    """One stair footprint for the whole building so stairs land on each other.

    Its depth also sets the front band, so the stair opens straight onto the
    corridor on every storey rather than through a bedroom.
    """
    stairs = [s for s in program.spaces if s.stair]
    if not stairs:
        return 0.0, 0.0
    stair_area = max(s.target_area_sqft for s in stairs)
    core_w = snap(max(CORE_MIN_WIDTH_FT, min(CORE_MAX_WIDTH_FT, width_ft / 4)))
    stair_d = snap(max(STAIR_MIN_DEPTH_FT, min(stair_area / core_w, depth_ft / 2)))
    if core_w < MIN_ROOM_SIDE_FT or depth_ft - stair_d < 2 * MIN_ROOM_SIDE_FT:
        raise LayoutError("The plate is too small to hold a stair core")
    return core_w, stair_d


def _assign_bands(
    rooms: list[SpaceSpec], front_capacity: float, back_capacity: float
) -> tuple[list[SpaceSpec], list[SpaceSpec]]:
    """Best fit, largest room first, so a big workspace lands in the deep band."""
    front: list[SpaceSpec] = []
    back: list[SpaceSpec] = []
    remaining_front, remaining_back = front_capacity, back_capacity
    for space in sorted(rooms, key=lambda s: (-s.target_area_sqft, s.id)):
        if remaining_front >= remaining_back and front_capacity > 0:
            front.append(space)
            remaining_front -= space.target_area_sqft
        else:
            back.append(space)
            remaining_back -= space.target_area_sqft
    if front_capacity > 0 and not front and back:
        front.append(back.pop())
    if back_capacity > 0 and not back and len(front) > 1:
        back.append(front.pop())
    order = {space.id: index for index, space in enumerate(rooms)}
    return sorted(front, key=lambda s: order[s.id]), sorted(back, key=lambda s: order[s.id])


def pack_floor(
    program: BuildingProgram,
    floor_id: str,
    width_ft: float,
    depth_ft: float,
    corridor_ft: float,
    core_w: float = 0.0,
    stair_d: float = 0.0,
) -> FloorLayout:
    spaces = program.floor_spaces(floor_id)
    if not spaces:
        raise LayoutError(f"Storey {floor_id!r} has no spaces")

    def done(rects: list[RoomRect]) -> FloorLayout:
        return FloorLayout(floor_id=floor_id, width_ft=width_ft, depth_ft=depth_ft, rooms=rects)

    if len(spaces) == 1:
        return done([RoomRect(space_id=spaces[0].id, x1=0, y1=0, x2=width_ft, y2=depth_ft)])

    stair = next((s for s in spaces if s.stair), None)
    remaining = [s for s in spaces if s is not stair]
    corridor = next((s for s in remaining if s.circulation), None)
    rooms = _ordered(program.building_use, [s for s in remaining if s is not corridor])
    band = max(MIN_ROOM_SIDE_FT, min(corridor_ft, depth_ft / 4))

    if stair is None:
        if corridor is None or not rooms:
            return done(_row(0, 0, width_ft, depth_ft, _ordered(program.building_use, remaining)))
        front, back = _assign_bands(rooms, width_ft * (depth_ft - band) / 2, width_ft * (depth_ft - band) / 2)
        if not back:
            split = snap(depth_ft - band)
            return done(
                _row(0, 0, width_ft, split, front)
                + [RoomRect(space_id=corridor.id, x1=0, y1=split, x2=width_ft, y2=depth_ft)]
            )
        share = sum(s.target_area_sqft for s in front) / max(
            sum(s.target_area_sqft for s in rooms), 1.0
        )
        usable = depth_ft - band
        front_d = snap(min(max(usable * share, MIN_ROOM_SIDE_FT), usable - MIN_ROOM_SIDE_FT))
        top = snap(front_d + band)
        return done(
            _row(0, 0, width_ft, front_d, front)
            + [RoomRect(space_id=corridor.id, x1=0, y1=front_d, x2=width_ft, y2=top)]
            + _row(0, top, width_ft, depth_ft, back)
        )

    if core_w <= 0 or stair_d <= 0:
        core_w, stair_d = core_dimensions(program, width_ft, depth_ft)

    if not rooms:
        # Only a stair and a corridor: nothing to load a corridor with.
        return done(_row(0, 0, width_ft, depth_ft, [stair] + ([corridor] if corridor else [])))

    # Balance the two bands rather than letting the stair depth dictate a shallow
    # front and a 40 ft deep back. Anything the stair does not use in the core
    # column becomes the service room beside it, which is where it belongs.
    usable = depth_ft - (band if corridor is not None else 0)
    front_d = snap(min(max(usable / 2, stair_d), usable - MIN_ROOM_SIDE_FT))
    if front_d < stair_d:
        raise LayoutError("The plate is too shallow for a stair core and rooms")

    rects = [RoomRect(space_id=stair.id, x1=0, y1=0, x2=core_w, y2=stair_d)]
    front_capacity = (width_ft - core_w) * front_d
    back_capacity = width_ft * (depth_ft - front_d - (band if corridor is not None else 0))
    front, back = _assign_bands(rooms, front_capacity, back_capacity)

    # Stair footprint is identical on every storey. Fill the leftover core cell
    # only when another room remains to occupy the front strip beside the stair.
    spare = len(front) + len(back) >= 2
    if front_d - stair_d >= MIN_ROOM_SIDE_FT and spare:
        pool = front if len(front) > 1 or not back else back
        beside = min(
            (s for s in pool if s.needs_plumbing),
            default=min(pool, key=lambda s: (s.target_area_sqft, s.id)),
            key=lambda s: (s.target_area_sqft, s.id),
        )
        pool.remove(beside)
        rects.append(RoomRect(space_id=beside.id, x1=0, y1=stair_d, x2=core_w, y2=front_d))
    else:
        # Keep the stair fixed and pull the front band to stair depth so the
        # plate tiles without stretching the shaft or leaving a void.
        front_d = stair_d

    if not front and back:
        front.append(back.pop())
    rects.extend(_row(core_w, 0, width_ft, front_d, front))

    if corridor is None:
        rects.extend(_row(0, front_d, width_ft, depth_ft, back or [front.pop()]))
        return done(rects)
    if not back:
        rects.append(RoomRect(space_id=corridor.id, x1=0, y1=front_d, x2=width_ft, y2=depth_ft))
        return done(rects)
    if depth_ft - front_d - band < MIN_ROOM_SIDE_FT:
        raise LayoutError("The plate is too shallow for a corridor with rooms on both sides")
    top = snap(front_d + band)
    rects.append(RoomRect(space_id=corridor.id, x1=0, y1=front_d, x2=width_ft, y2=top))
    rects.extend(_row(0, top, width_ft, depth_ft, back))
    return done(rects)


def pack_floors(program: BuildingProgram, area_sqft: float | None = None) -> dict[str, FloorLayout]:
    """Pack every storey on one shared plate so the envelope stacks."""
    active = defaults.profile(program.building_use)
    target = area_sqft or sum(s.target_area_sqft for s in program.spaces)
    width_ft, depth_ft = defaults.footprint_for(target, len(program.storeys), active.aspect)
    # The plate must hold the fullest storey, not the average one.
    busiest = max(
        sum(s.target_area_sqft for s in program.floor_spaces(storey.id)) for storey in program.storeys
    )
    if busiest > width_ft * depth_ft:
        width_ft, depth_ft = defaults.footprint_for(busiest, 1, active.aspect)
    width_ft, depth_ft = snap(width_ft), snap(depth_ft)
    core_w, stair_d = core_dimensions(program, width_ft, depth_ft)

    layouts: dict[str, FloorLayout] = {}
    for storey in program.storeys:
        layouts[storey.id] = pack_floor(
            program, storey.id, width_ft, depth_ft, active.corridor_width_ft, core_w, stair_d
        )
    return layouts
