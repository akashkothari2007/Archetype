"""Flag measurements that are statistical outliers before they are checked.

Rationale: 46 rooms named STUDIO KING should be within a few percent of each
other; one at 63 sqft is a bad polygon, not a small room. Doors come in
standard sizes; a 0.5 ft door is an extraction failure, not a narrow door.

Rooms are grouped by type_ref. All openings are one group. Per group, anything
more than 3 MAD from the median is reliability="suspect" with a reason naming
the group median. Everything else is reliability="ok".

Quarantined items are never dropped: they are returned separately from
violations so the count stays visible.
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
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2


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


def _min_side_ft(room: Room) -> float:
    if not room.polygon or len(room.polygon) < 3:
        return 0.0
    try:
        from plancheck.services.compliance import min_clear_width_ft
        width, _unused = min_clear_width_ft(room)
        return float(width)
    except Exception:
        return 0.0


def _flag(entities, values: list[float], label: str) -> None:
    if len(values) < 3:
        return
    med = _median(values)
    mad = _mad(values, med)
    limit = MAD_K * mad
    for entity, value in zip(entities, values):
        if entity.reliability == "suspect":
            continue
        if abs(value - med) <= limit:
            continue
        entity.reliability = "suspect"
        entity.reliability_reason = (
            f"{label} {value:.3f} is more than {MAD_K:g} MAD from the group median {med:.3f}"
        )


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
        _flag(
            building.openings,
            [float(item.width_ft) for item in building.openings],
            "opening width_ft",
        )
    return building
