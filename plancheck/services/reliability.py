"""Flag measurements that are statistical outliers before they are checked.

Rationale: 46 rooms named STUDIO KING should be within a few percent of each
other. One at 63 sqft is a bad polygon, not a small room. Doors are
manufactured in standard sizes, so a 0.16 m door is an extraction failure,
not a narrow door.

Rooms are grouped by type_ref. Openings are grouped by kind (all doors
together, all windows together) so a standard door is not judged against
window sash fragments.
"""
from __future__ import annotations

from collections import defaultdict

from shapely.geometry import Polygon

from plancheck.core.building import Building, Opening, Room

MAD_K = 3.0
_AREA_EPS = 1e-6


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    return ordered[n // 2]


def _mad(values: list[float], med: float) -> float:
    return _median([abs(value - med) for value in values])


def _room_area(room: Room) -> float:
    if not room.polygon or len(room.polygon) < 3:
        return 0.0
    try:
        area = float(Polygon(room.polygon).area)
    except Exception:
        return 0.0
    return area if area > _AREA_EPS else 0.0


def _flag(entities, values: list[float], label: str) -> None:
    if len(values) < 3:
        return
    med = _median(values)
    mad = _mad(values, med)
    # CAD and manufactured sizes quantize; a raw MAD of 0 must not flag
    # every 3.21 ft door next to a 3.20 ft sibling.
    floor = 0.02 * max(abs(med), 1.0)
    limit = max(MAD_K * mad, floor)
    for entity, value in zip(entities, values):
        if entity.reliability == "suspect":
            continue
        if abs(value - med) <= limit:
            continue
        entity.reliability = "suspect"
        entity.reliability_reason = (
            f"{label} {value:.3f} is more than {MAD_K:g} MAD from the group median {med:.3f}"
        )


def _min_side_ft(room: Room) -> float:
    if not room.polygon or len(room.polygon) < 3:
        return 0.0
    try:
        from plancheck.services.compliance import min_clear_width_ft
        width, _unused = min_clear_width_ft(room)
        return float(width)
    except Exception:
        return 0.0


def apply_reliability(building: Building) -> Building:
    for room in building.rooms:
        room.reliability = "ok"
        room.reliability_reason = ""
    for opening in building.openings:
        opening.reliability = "ok"
        opening.reliability_reason = ""

    grouped: dict[str, list[Room]] = defaultdict(list)
    for room in building.rooms:
        key = (room.type_ref or "").strip()
        if not key:
            continue
        grouped[key].append(room)
    for type_ref, rooms in grouped.items():
        _flag(rooms, [_room_area(room) for room in rooms], f"{type_ref} area_sqft")
        _flag(rooms, [_min_side_ft(room) for room in rooms], f"{type_ref} min_side_ft")

    if building.openings:
        # Doors and windows are separate manufactured populations. Mixing them
        # would treat a 3 ft door as an outlier against 6-inch window marks.
        by_kind: dict[str, list[Opening]] = defaultdict(list)
        for opening in building.openings:
            by_kind[opening.kind].append(opening)
        for kind, group in by_kind.items():
            _flag(group, [float(item.width_ft) for item in group], f"{kind} width_ft")
    return building
