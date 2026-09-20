"""Rectangles to editable geometry. The only place generated coordinates exist.

Room rectangles are turned into a shared-vertex wall graph: every edge is split
at each neighbouring corner, so two rooms that touch reference one wall rather
than two overlapping ones. Edges with a single owner face outside and become the
locked loadbearing envelope; shared edges become unlocked partitions the editor
and the repair agent are allowed to move.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from plancheck.core.building import (
    Building,
    BuildingWall,
    Floor,
    Opening,
    PlacedObject,
    Room,
    ReviewItem,
    Source,
    Vertex,
)
from plancheck.generation import defaults
from plancheck.generation.program import (
    BuildingProgram,
    FloorLayout,
    RoomRect,
    SpaceSpec,
    is_bathroom,
    is_kitchen,
    snap,
)
from plancheck.services.commands import recompute_rooms, validate_building

Point = tuple[float, float]
Segment = tuple[Point, Point]

EXTERIOR_THICKNESS_FT = 0.65
INTERIOR_THICKNESS_FT = 0.4
DOOR_CLEARANCE_FT = 0.8
WINDOW_CLEARANCE_FT = 2.0
MAX_WINDOWS_PER_ROOM = 3

SERVICE_CATEGORIES = {"stair", "storage", "utility", "server", "stock", "receiving", "shaft"}
FLOOR_MATERIALS = {
    "bathroom": "tile", "wc": "tile", "restroom": "tile", "washroom": "tile",
    "kitchen": "tile",
    "utility": "concrete", "stock": "concrete", "receiving": "concrete",
    "sales": "concrete", "garage": "concrete", "circulation": "oak", "stair": "oak",
}


@dataclass(frozen=True)
class CompileOptions:
    """Modelling conventions. Doors and windows are assumptions, not measurements."""

    door_width_ft: float = defaults.DOOR_WIDTH_FT
    door_height_ft: float = defaults.DOOR_HEIGHT_FT
    entry_door_width_ft: float = 3.3
    window_width_ft: float = defaults.WINDOW_WIDTH_FT
    window_height_ft: float = defaults.WINDOW_HEIGHT_FT
    window_sill_ft: float = defaults.WINDOW_SILL_FT
    exterior_thickness_ft: float = EXTERIOR_THICKNESS_FT
    interior_thickness_ft: float = INTERIOR_THICKNESS_FT
    door_every_partition: bool = False
    method: str = "generated"


class CompileError(ValueError):
    """The layout cannot become valid geometry; the caller may ask for a fix."""


@dataclass
class _FloorGraph:
    segments: dict[Segment, list[str]] = field(default_factory=dict)
    points: set[Point] = field(default_factory=set)


def _key(a: Point, b: Point) -> Segment:
    return (a, b) if a <= b else (b, a)


def _length(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _split_edge(a: Point, b: Point, points: set[Point]) -> list[Segment]:
    """Cut one rectangle edge at every corner that lands on it."""
    if a[0] == b[0]:
        between = sorted(p[1] for p in points if p[0] == a[0] and min(a[1], b[1]) < p[1] < max(a[1], b[1]))
        ordered = [min(a[1], b[1]), *between, max(a[1], b[1])]
        return [((a[0], lo), (a[0], hi)) for lo, hi in zip(ordered, ordered[1:])]
    between = sorted(p[0] for p in points if p[1] == a[1] and min(a[0], b[0]) < p[0] < max(a[0], b[0]))
    ordered = [min(a[0], b[0]), *between, max(a[0], b[0])]
    return [((lo, a[1]), (hi, a[1])) for lo, hi in zip(ordered, ordered[1:])]


def _build_graph(rects: list[RoomRect]) -> _FloorGraph:
    graph = _FloorGraph()
    for rect in rects:
        graph.points.update(rect.corners())
    for rect in rects:
        corners = rect.corners()
        for a, b in zip(corners, corners[1:] + corners[:1]):
            for segment in _split_edge(a, b, graph.points):
                graph.segments.setdefault(_key(*segment), []).append(rect.space_id)
    return graph


def _material_for(space: SpaceSpec) -> str:
    return FLOOR_MATERIALS.get(space.category, "oak")


def _door_target(opening_walls: set[str], candidates: list[tuple[float, str]], width: float) -> tuple[float, str] | None:
    """Longest free wall that can host a door with clearance on both sides."""
    for length, wall_id in sorted(candidates, reverse=True):
        if wall_id not in opening_walls and length >= width + DOOR_CLEARANCE_FT:
            return length, wall_id
    return None


def compile_building(
    program: BuildingProgram,
    layouts: dict[str, FloorLayout],
    options: CompileOptions | None = None,
) -> Building:
    """Compile validated intent into a Building the editors can already open."""
    options = options or CompileOptions()
    missing = [s.id for s in program.storeys if s.id not in layouts]
    if missing:
        raise CompileError(f"No layout was produced for storey(s): {', '.join(missing)}")

    building = Building()
    source = Source(method=options.method, assumed=True)
    touched: set[str] = set()

    for storey in program.storeys:
        layout = layouts[storey.id]
        spaces = {s.id: s for s in program.floor_spaces(storey.id)}
        rects = [r for r in layout.rooms if r.space_id in spaces]
        if not rects:
            raise CompileError(f"Storey {storey.id!r} has no rooms that match the program")

        building.floors.append(
            Floor(
                id=storey.id,
                name=storey.name,
                elevation_ft=snap(program.elevation_ft(storey.id)),
                height_ft=storey.height_ft,
            )
        )
        touched.add(storey.id)

        graph = _build_graph(rects)
        vertex_ids = {p: f"{storey.id}-v{i}" for i, p in enumerate(sorted(graph.points))}
        for point, vid in sorted(vertex_ids.items(), key=lambda kv: kv[1]):
            building.vertices.append(Vertex(id=vid, floor_id=storey.id, x=point[0], y=point[1]))

        # Walls: one owner means the segment faces outside, so it carries the envelope.
        wall_of: dict[Segment, str] = {}
        exterior_walls: dict[str, list[tuple[float, str]]] = {}
        shared: dict[tuple[str, str], list[tuple[float, str]]] = {}
        for index, (segment, owners) in enumerate(sorted(graph.segments.items())):
            a, b = segment
            external = len(set(owners)) == 1
            wall = BuildingWall(
                id=f"{storey.id}-w{index}",
                floor_id=storey.id,
                start_id=vertex_ids[a],
                end_id=vertex_ids[b],
                thickness_ft=options.exterior_thickness_ft if external else options.interior_thickness_ft,
                height_ft=storey.height_ft,
                structural="loadbearing" if external else "nonstructural",
                locked=external,
                source=source,
            )
            building.walls.append(wall)
            wall_of[segment] = wall.id
            length = _length(a, b)
            if external:
                exterior_walls.setdefault(owners[0], []).append((length, wall.id))
            else:
                pair = tuple(sorted(set(owners))[:2])
                if len(pair) == 2:
                    shared.setdefault(pair, []).append((length, wall.id))

        for rect in sorted(rects, key=lambda r: r.space_id):
            space = spaces[rect.space_id]
            building.rooms.append(
                Room(
                    id=f"{storey.id}-{space.id}",
                    floor_id=storey.id,
                    name=space.name,
                    category=space.category,
                    type_ref=f"{program.building_use}.{space.category}",
                    polygon=rect.corners(),
                    floor_material=_material_for(space),
                    source=source,
                )
            )

        _add_openings(building, program, storey.id, spaces, rects, exterior_walls, shared, options, source)
        _add_objects(building, spaces, rects, storey.id)

    recompute_rooms(building, touched)
    try:
        validate_building(building)
    except ValueError as exc:
        raise CompileError(str(exc)) from exc
    return building


def _add_openings(
    building: Building,
    program: BuildingProgram,
    floor_id: str,
    spaces: dict[str, SpaceSpec],
    rects: list[RoomRect],
    exterior_walls: dict[str, list[tuple[float, str]]],
    shared: dict[tuple[str, str], list[tuple[float, str]]],
    options: CompileOptions,
    source: Source,
) -> None:
    used: set[str] = set()
    ground = program.storeys[0].id == floor_id

    def place(wall_id: str, length: float, kind: str, width: float, height: float, sill: float) -> None:
        used.add(wall_id)
        building.openings.append(
            Opening(
                id=f"{wall_id}-{kind[0]}",
                wall_id=wall_id,
                kind=kind,
                offset_ft=snap(max(0.0, (length - width) / 2)),
                width_ft=width,
                height_ft=height,
                sill_ft=sill,
                source=source,
            )
        )

    # Every room reachable from the entry: one door per edge of a spanning tree.
    neighbours: dict[str, list[tuple[str, list[tuple[float, str]]]]] = {r.space_id: [] for r in rects}
    for (left, right), walls in shared.items():
        if left in neighbours and right in neighbours:
            neighbours[left].append((right, walls))
            neighbours[right].append((left, walls))

    order = sorted(
        rects,
        key=lambda r: (
            not spaces[r.space_id].entry,
            not spaces[r.space_id].circulation,
            -r.area_sqft,
            r.space_id,
        ),
    )
    root = order[0].space_id
    seen = {root}
    queue: deque[str] = deque([root])
    unreachable_note: list[str] = []
    while queue:
        current = queue.popleft()
        # Circulation first keeps doors on corridors instead of chaining rooms.
        for other, walls in sorted(
            neighbours[current],
            key=lambda item: (not spaces[item[0]].circulation, -max(w[0] for w in item[1]), item[0]),
        ):
            if other in seen:
                continue
            target = _door_target(used, walls, options.door_width_ft)
            if target is None:
                continue
            length, wall_id = target
            place(wall_id, length, "door", options.door_width_ft, options.door_height_ft, 0)
            seen.add(other)
            queue.append(other)

    for rect in rects:
        if rect.space_id not in seen:
            unreachable_note.append(spaces[rect.space_id].name)

    if options.door_every_partition:
        for walls in shared.values():
            for length, wall_id in walls:
                if wall_id not in used and length >= options.door_width_ft + DOOR_CLEARANCE_FT:
                    place(wall_id, length, "door", options.door_width_ft, options.door_height_ft, 0)

    if ground:
        entry_space = next(
            (r.space_id for r in order if r.space_id in exterior_walls),
            None,
        )
        if entry_space is not None:
            target = _door_target(used, exterior_walls[entry_space], options.entry_door_width_ft)
            if target is not None:
                length, wall_id = target
                place(wall_id, length, "door", options.entry_door_width_ft, options.door_height_ft, 0)

    for space_id, walls in sorted(exterior_walls.items()):
        space = spaces.get(space_id)
        if space is None or space.category in SERVICE_CATEGORIES:
            continue
        placed = 0
        for length, wall_id in sorted(walls, reverse=True):
            if placed >= MAX_WINDOWS_PER_ROOM:
                break
            if wall_id in used or length < options.window_width_ft + WINDOW_CLEARANCE_FT:
                continue
            place(
                wall_id,
                length,
                "window",
                options.window_width_ft,
                options.window_height_ft,
                options.window_sill_ft,
            )
            placed += 1

    if unreachable_note:
        building.review.append(
            ReviewItem(
                id=f"{floor_id}-connectivity",
                kind="circulation",
                message=(
                    "No wall was long enough for a door into: "
                    + ", ".join(sorted(unreachable_note))
                    + ". Widen the shared partition or add a door in the editor."
                ),
                entity_ids=[f"{floor_id}-{name}" for name in sorted(unreachable_note)],
            )
        )


def _door_sides(building: Building, floor_id: str, rect: RoomRect) -> set[str]:
    """Which edges of this rectangle already have a door, so fixtures stay off them."""
    verts = {v.id: v for v in building.vertices if v.floor_id == floor_id}
    walls = {w.id: w for w in building.walls if w.floor_id == floor_id}
    sides: set[str] = set()
    for opening in building.openings:
        if opening.kind != "door":
            continue
        wall = walls.get(opening.wall_id)
        if wall is None:
            continue
        start, end = verts.get(wall.start_id), verts.get(wall.end_id)
        if start is None or end is None:
            continue
        xs, ys = sorted((start.x, end.x)), sorted((start.y, end.y))
        if abs(start.y - end.y) < 0.05 and xs[1] - xs[0] > 0.5:
            if abs(start.y - rect.y1) < 0.05 and xs[1] > rect.x1 + 0.2 and xs[0] < rect.x2 - 0.2:
                sides.add("s")
            elif abs(start.y - rect.y2) < 0.05 and xs[1] > rect.x1 + 0.2 and xs[0] < rect.x2 - 0.2:
                sides.add("n")
        elif abs(start.x - end.x) < 0.05 and ys[1] - ys[0] > 0.5:
            if abs(start.x - rect.x1) < 0.05 and ys[1] > rect.y1 + 0.2 and ys[0] < rect.y2 - 0.2:
                sides.add("w")
            elif abs(start.x - rect.x2) < 0.05 and ys[1] > rect.y1 + 0.2 and ys[0] < rect.y2 - 0.2:
                sides.add("e")
    return sides


def _fixture_pose(
    rect: RoomRect, side: str, along: float, width: float, depth: float
) -> tuple[float, float, float, float]:
    """Centre, rotation, and depth used so the back of the fixture sits on the wall."""
    inset = 0.12
    into = min(depth, max(1.0, (_into(rect, side) - 2 * inset)))
    if side == "s":
        return snap(along), snap(rect.y1 + into / 2 + inset), 0.0, into
    if side == "n":
        return snap(along), snap(rect.y2 - into / 2 - inset), 180.0, into
    if side == "w":
        return snap(rect.x1 + into / 2 + inset), snap(along), 90.0, into
    return snap(rect.x2 - into / 2 - inset), snap(along), 270.0, into


def _into(rect: RoomRect, side: str) -> float:
    return rect.depth_ft if side in {"s", "n"} else rect.width_ft


def _along_span(rect: RoomRect, side: str) -> tuple[float, float]:
    if side in {"s", "n"}:
        return rect.x1, rect.x2
    return rect.y1, rect.y2


def _ranked_sides(rect: RoomRect, blocked: set[str]) -> list[str]:
    order = sorted(
        ("s", "n", "w", "e"),
        key=lambda side: (
            side in blocked,
            -(_along_span(rect, side)[1] - _along_span(rect, side)[0]),
            -_into(rect, side),
            side,
        ),
    )
    return [side for side in order if _into(rect, side) >= 1.6]


def _place_on_walls(
    floor_id: str,
    rect: RoomRect,
    blocked: set[str],
    items: list[tuple[str, str, float, float, float]],
) -> list[PlacedObject]:
    """Pack fixtures along room walls. ``items`` are id, asset, width, depth, height."""
    placed: list[PlacedObject] = []
    used: dict[str, float] = {}
    gap = 0.35
    corner = 0.4
    for object_id, asset, width, depth, height in items:
        pose = None
        for side in _ranked_sides(rect, blocked):
            lo, hi = _along_span(rect, side)
            cursor = used.get(side, lo + corner)
            if cursor + width + corner > hi:
                continue
            along = cursor + width / 2
            x, y, rotation, into = _fixture_pose(rect, side, along, width, depth)
            pose = (side, cursor + width + gap, x, y, rotation, into)
            break
        if pose is None:
            continue
        side, next_cursor, x, y, rotation, into = pose
        used[side] = next_cursor
        placed.append(
            PlacedObject(
                id=object_id,
                floor_id=floor_id,
                asset_id=asset,
                kind="fixture",
                x=x,
                y=y,
                rotation_deg=rotation,
                width_ft=width,
                depth_ft=into,
                height_ft=height,
            )
        )
    return placed


def _add_objects(building: Building, spaces: dict[str, SpaceSpec], rects: list[RoomRect], floor_id: str) -> None:
    for rect in sorted(rects, key=lambda r: r.space_id):
        space = spaces[rect.space_id]
        cx, cy = rect.center()
        if space.stair:
            building.objects.append(
                PlacedObject(
                    id=f"{floor_id}-stairs",
                    floor_id=floor_id,
                    asset_id="stairs",
                    kind="reference",
                    x=cx,
                    y=cy,
                    width_ft=min(3.2, max(1.0, rect.width_ft - 1)),
                    depth_ft=min(8.0, max(1.0, rect.depth_ft - 1)),
                    height_ft=8,
                )
            )
            continue
        blocked = _door_sides(building, floor_id, rect)
        items: list[tuple[str, str, float, float, float]] = []
        if is_bathroom(space):
            items = [
                (f"{floor_id}-{space.id}-wc", "toilet", 1.7, 2.5, 2.5),
                (f"{floor_id}-{space.id}-sink", "sink", 2.0, 1.6, 2.8),
            ]
            if rect.area_sqft >= 50:
                items.append((f"{floor_id}-{space.id}-shower", "shower", 3.0, 3.0, 0.3))
        elif is_kitchen(space):
            run = min(5.0, max(2.5, min(rect.width_ft, rect.depth_ft) * 0.45))
            items = [
                (f"{floor_id}-{space.id}-counter", "counter", run, 2.0, 3.0),
                (f"{floor_id}-{space.id}-sink", "sink", 2.0, 1.6, 2.8),
            ]
        for obj in _place_on_walls(floor_id, rect, blocked, items):
            building.objects.append(obj)
