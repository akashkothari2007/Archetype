"""Flag measurements that are statistical outliers before they are checked.

Rationale: 46 rooms named STUDIO KING should be within a few percent of each
other; one at 63 sqft is a bad polygon, not a small room. Doors come in
standard sizes; a 0.5 ft door is an extraction failure, not a narrow door.

Rooms are grouped by type_ref. All openings are one group. Per group, anything
more than 3 MAD from the median is reliability="suspect" with a reason naming
the group median. Everything else is reliability="ok".

Absolute floors run first. A whole type that is equally impossible (every
closet 5 inches wide) looks consistent to MAD; physics still rejects it.

Quarantined items are never dropped: they are returned separately from
violations so the count stays visible.
"""
from __future__ import annotations

from collections import defaultdict

from shapely.geometry import Polygon

from plancheck.core.building import Building, Opening, Room

MAD_K = 3.0
_AREA_EPS = 1e-6
_MAD_EPS = 1e-9
# 1 m² and 0.45 m expressed in stored feet. A space a person cannot stand in
# is an extraction error, not a small room — even if every peer is the same.
ROOM_AREA_FLOOR_FT2 = 1.0 / 0.09290304
ROOM_MIN_SIDE_FLOOR_FT = 0.45 / 0.3048
OPENING_WIDTH_MIN_FT = 1.5
OPENING_WIDTH_MAX_FT = 8.0
FT_TO_M = 0.3048
FT2_TO_M2 = 0.09290304


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


def _flag(entities, values: list[float], unit: str) -> None:
    if len(values) < 3:
        return
    med = _median(values)
    mad = _mad(values, med)
    scale = max(abs(med) * 1e-4, 1e-6)
    for entity, value in zip(entities, values):
        if entity.reliability == "suspect":
            continue
        if mad <= _MAD_EPS:
            if abs(value - med) <= scale:
                continue
            entity.reliability = "suspect"
            entity.reliability_reason = f"off group median {med:.1f} {unit}"
            continue
        if abs(value - med) <= MAD_K * mad:
            continue
        k = abs(value - med) / mad
        entity.reliability = "suspect"
        entity.reliability_reason = f"{k:.1f} MAD from group median {med:.1f} {unit}"


def _physical_floors(building: Building) -> None:
    for room in building.rooms:
        area = _room_area(room)
        if area > _AREA_EPS and area < ROOM_AREA_FLOOR_FT2:
            room.reliability = "suspect"
            room.reliability_reason = f"implausibly small area ({area * FT2_TO_M2:.2f} m2)"
            continue
        width = _min_side_ft(room)
        if width > _AREA_EPS and width < ROOM_MIN_SIDE_FLOOR_FT:
            room.reliability = "suspect"
            room.reliability_reason = f"implausibly narrow ({width * FT_TO_M:.2f} m)"
    for opening in building.openings:
        width = float(opening.width_ft)
        if width < OPENING_WIDTH_MIN_FT:
            opening.reliability = "suspect"
            opening.reliability_reason = f"implausibly narrow ({width:.2f} ft)"
        elif width > OPENING_WIDTH_MAX_FT:
            opening.reliability = "suspect"
            opening.reliability_reason = f"implausibly wide ({width:.2f} ft)"


def apply_reliability(building: Building) -> Building:
    for room in building.rooms:
        room.reliability = "ok"
        room.reliability_reason = ""
    for opening in building.openings:
        opening.reliability = "ok"
        opening.reliability_reason = ""

    _physical_floors(building)

    grouped: dict[str, list[Room]] = defaultdict(list)
    for room in building.rooms:
        key = (room.type_ref or "").strip()
        if not key:
            continue
        grouped[key].append(room)
    for rooms in grouped.values():
        _flag(rooms, [_room_area(room) for room in rooms], "sq ft")
        _flag(rooms, [_min_side_ft(room) for room in rooms], "ft")

    if building.openings:
        _flag(building.openings, [float(item.width_ft) for item in building.openings], "ft")
    return building
