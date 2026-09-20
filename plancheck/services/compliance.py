"""Deterministic measurements over the same building the editors display.

Only explicitly approved, supported rules emit result rows. Missing data is
never treated as compliance. All stored geometry is in feet; each result uses
the rule's original unit.
"""
from __future__ import annotations

import fnmatch
import hashlib
import math
from collections import defaultdict
from itertools import combinations
from statistics import median
from typing import Any

from shapely.geometry import Polygon, JOIN_STYLE

from plancheck.core.building import Building, Opening, Room

EPS = 1e-7
CLEAR_HINGE_STOP_FT = 2.0 / 12.0
CLEAR_WIDTH_ASSUMPTION = (
    "clear width = leaf width − 2 in (stop and hinge projection)"
)
METRIC_ALIASES = {
    "room.area": "area",
    "room.min_side": "min_side",
    "width": "min_side",
    "door.aperture_width": "aperture_width",
    "door.clear_width": "clear_width",
    "opening.separation": "opening_distance",
}
SUPPORTED_METRICS = {"area", "min_side", "aperture_width", "clear_width", "opening_distance"}
AREA_UNITS = {"ft2", "sqft", "feet2", "m2", "sqm"}
LENGTH_UNITS = {"ft", "feet", "foot", "m", "cm", "mm", "in", "inch", "inches"}


def metric_name(rule: dict) -> str:
    name = rule.get("metric", "")
    return METRIC_ALIASES.get(name, name)


def canonical_unit(unit: str) -> str:
    return str(unit).lower().replace("²", "2").replace(" ", "").replace("sq.", "sq").replace("square", "sq")


def _unit_family(unit: str) -> str | None:
    unit = canonical_unit(unit)
    if unit in AREA_UNITS:
        return "area"
    if unit in LENGTH_UNITS:
        return "length"
    return None


def to_rule_units(value: float, unit: str, area: bool = False) -> float:
    unit = canonical_unit(unit)
    family = _unit_family(unit)
    if family is None:
        raise ValueError(f"Unsupported {'area' if area else 'length'} unit: {unit}")
    if area and family != "area":
        raise ValueError("Cannot convert between area and length units.")
    if not area and family != "length":
        raise ValueError("Cannot convert between area and length units.")
    factors = (
        {"ft2": 1, "sqft": 1, "feet2": 1, "m2": 0.09290304, "sqm": 0.09290304}
        if area
        else {"ft": 1, "feet": 1, "foot": 1, "m": 0.3048, "cm": 30.48, "mm": 304.8, "in": 12, "inch": 12, "inches": 12}
    )
    return value * factors[unit]


def from_rule_units(value: float, unit: str, area: bool = False) -> float:
    return value / to_rule_units(1, unit, area)


def polygon_points(room: Room) -> list[tuple[float, float]]:
    points = list(room.polygon or [])
    if points and points[0] == points[-1]:
        points.pop()
    changed = True
    while changed and len(points) > 3:
        changed = False
        for i, p in enumerate(points):
            a, b = points[i - 1], points[(i + 1) % len(points)]
            cross = (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])
            dot = (p[0] - a[0]) * (b[0] - p[0]) + (p[1] - a[1]) * (b[1] - p[1])
            if abs(cross) < EPS and dot >= 0:
                points.pop(i)
                changed = True
                break
    return points


def _room_polygon(room: Room) -> Polygon:
    points = polygon_points(room)
    if len(points) < 4 and len(points) < 3:
        raise ValueError("Room boundary is missing or degenerate.")
    if len(points) < 3:
        raise ValueError("A closed room boundary is required.")
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.area <= EPS:
        raise ValueError("Room boundary is invalid or has no measurable area.")
    return polygon


def room_area(room: Room) -> float:
    return float(_room_polygon(room).area)


def _safe_area(room: Room) -> float:
    try:
        return room_area(room)
    except ValueError:
        return 0.0


def _centroid(room: Room) -> tuple[float, float]:
    points = polygon_points(room)
    if not points:
        return 0.0, 0.0
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def _part_role(room: Room, parent: Room) -> str:
    if room.id == parent.id:
        return "bedroom" if parent.category == "guestroom" else (parent.category or "room")
    name = room.name or ""
    suffix = name[len(parent.name) :].strip().lower() if parent.name and name.startswith(parent.name) else ""
    if suffix in {"bath", "bathroom"} or room.category == "bathroom":
        return "bath"
    if suffix in {"closet", "storage"} or room.category == "storage":
        return "closet"
    return suffix or room.category or "room"


def index_unit_children(building: Building) -> dict[str, list[Room]]:
    """Map guestroom id → child rooms via parent_room_id, else name prefix + nearest parent."""
    by_id = {room.id: room for room in building.rooms}
    index: dict[str, list[Room]] = defaultdict(list)
    claimed: set[str] = set()
    for room in building.rooms:
        parent = by_id.get(room.parent_room_id)
        if parent is None or parent.category != "guestroom":
            continue
        index[parent.id].append(room)
        claimed.add(room.id)
    parents = [room for room in building.rooms if room.category == "guestroom"]
    for child in building.rooms:
        if child.id in claimed:
            continue
        candidates = [
            parent
            for parent in parents
            if parent.id != child.id
            and parent.floor_id == child.floor_id
            and parent.name
            and child.name.startswith(parent.name + " ")
        ]
        if not candidates:
            continue
        longest = max(len(parent.name) for parent in candidates)
        candidates = [parent for parent in candidates if len(parent.name) == longest]
        cx, cy = _centroid(child)
        best = min(candidates, key=lambda parent: math.hypot(_centroid(parent)[0] - cx, _centroid(parent)[1] - cy))
        index[best.id].append(child)
        claimed.add(child.id)
    return index


def guestroom_unit_area(room: Room, building: Building, children_by_parent: dict[str, list[Room]] | None = None) -> tuple[float, list[dict[str, Any]]]:
    """Whole-key area for a guestroom: parent polygon plus named children."""
    kids = (children_by_parent or {}).get(room.id, []) if room.category == "guestroom" else []
    if children_by_parent is None and room.category == "guestroom":
        kids = index_unit_children(building).get(room.id, [])
    parts = []
    total = 0.0
    for item in [room, *kids]:
        area = _safe_area(item)
        total += area
        parts.append({"id": item.id, "role": _part_role(item, room), "area_ft2": area})
    return total, parts


def _composite_area_message(room: Room, actual: float, unit: str, expected: float, operator: str, parts: list[dict[str, Any]]) -> str:
    total_ft = sum(float(part["area_ft2"]) for part in parts)
    bits = " + ".join(f"{float(part['area_ft2']):.0f} {part['role']}" for part in parts)
    return (
        f"{room.name}: area {actual:.3f} {unit} "
        f"({total_ft:.0f} sq ft = {bits}); "
        f"required {operator} {expected:g} {unit}."
    )


def rectangle_sides(room: Room) -> tuple[float, float]:
    points = polygon_points(room)
    room_area(room)
    if len(points) != 4:
        raise ValueError("Minimum-side verification currently requires a rectangular room.")
    vectors = [(points[(i + 1) % 4][0] - p[0], points[(i + 1) % 4][1] - p[1]) for i, p in enumerate(points)]
    lengths = [math.hypot(*v) for v in vectors]
    for i, v in enumerate(vectors):
        other = vectors[(i + 1) % 4]
        if lengths[i] <= EPS or abs(v[0] * other[0] + v[1] * other[1]) > EPS * max(1, lengths[i] * lengths[(i + 1) % 4]):
            raise ValueError("Minimum-side verification currently requires a rectangular room.")
    return lengths[0], lengths[1]


def _wide_enough(polygon: Polygon, width_ft: float) -> tuple[bool, Polygon | None]:
    if width_ft <= EPS:
        return True, None
    radius = width_ft / 2.0
    eroded = polygon.buffer(-radius, join_style=JOIN_STYLE.mitre, mitre_limit=5)
    if eroded.is_empty:
        return False, polygon
    opened = eroded.buffer(radius, join_style=JOIN_STYLE.mitre, mitre_limit=5)
    pinch = polygon.difference(opened)
    if pinch.is_empty or pinch.area < 1e-3:
        return True, None
    return False, pinch


def min_clear_width_ft(room: Room) -> tuple[float, Polygon | None]:
    """Narrowest clear width via morphological opening. Returns (width_ft, unused)."""
    points = polygon_points(room)
    if len(points) < 4:
        raise ValueError("Minimum-side verification needs at least four boundary vertices.")
    polygon = Polygon(points)
    if not polygon.is_valid:
        raise ValueError("Room boundary is self-intersecting or otherwise invalid.")
    if polygon.area <= EPS:
        raise ValueError("Room boundary has no measurable area.")
    minx, miny, maxx, maxy = polygon.bounds
    hi = max(maxx - minx, maxy - miny)
    if hi <= EPS:
        raise ValueError("Room boundary is degenerate.")
    lo = 0.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        ok, _pinch = _wide_enough(polygon, mid)
        if ok:
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.005:
            break
    return lo, None


def pinch_at_width(room: Room, width_ft: float) -> Polygon | None:
    points = polygon_points(room)
    if len(points) < 4:
        raise ValueError("Minimum-side verification needs at least four boundary vertices.")
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.area <= EPS:
        raise ValueError("Room boundary is invalid or has no measurable area.")
    ok, pinch = _wide_enough(polygon, width_ft)
    return None if ok else pinch


def _pattern_values(room: Room) -> list[str]:
    return [
        room.id,
        room.category,
        room.type_ref,
        room.type_ref.split(".", 1)[0] if room.type_ref else "",
        room.name,
        room.name.replace(" ", "_"),
    ]


def _glob(value: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(str(value).lower(), str(pattern).lower())


def _room_hits_pattern(room: Room, pattern: str) -> bool:
    return any(_glob(value, pattern) for value in _pattern_values(room) if value)


def matches_room(room: Room, rule: dict) -> bool:
    ids = rule.get("target_ids") or []
    if ids:
        return room.id in ids
    pattern = str(rule.get("applies_to", "*"))
    if not _room_hits_pattern(room, pattern):
        return False
    for exclude in rule.get("excludes") or []:
        if _room_hits_pattern(room, exclude):
            return False
    return True


def connected_rooms(opening: Opening, building: Building) -> list[Room]:
    return [room for room in building.rooms if opening.wall_id in room.wall_ids]


def matches_opening(opening: Opening, building: Building, rule: dict) -> bool:
    if rule.get("target_ids"):
        return opening.id in rule["target_ids"]
    rooms = connected_rooms(opening, building)
    for exclude in rule.get("excludes") or []:
        if any(_room_hits_pattern(room, exclude) for room in rooms):
            return False
    door_to = (rule.get("applies_to_filter") or {}).get("door_to")
    if door_to and not any(_room_hits_pattern(room, door_to) for room in rooms):
        return False
    pattern = str(rule.get("applies_to", "*"))
    if any(_glob(value, pattern) for value in [opening.id, opening.kind] if value):
        return True
    return any(matches_room(room, rule) for room in rooms)


def opening_gap(a: Opening, b: Opening) -> float:
    if a.wall_id != b.wall_id:
        raise ValueError("Opening separation is supported only on the same straight host wall.")
    return max(0, max(a.offset_ft, b.offset_ft) - min(a.offset_ft + a.width_ft, b.offset_ft + b.width_ft))


def derived_clear_width_ft(opening: Opening) -> tuple[float, str]:
    if opening.clear_width_ft is not None:
        return float(opening.clear_width_ft), ""
    return max(0.0, float(opening.width_ft) - CLEAR_HINGE_STOP_FT), CLEAR_WIDTH_ASSUMPTION


def _compare(actual: float, expected: float, operator: str) -> bool:
    if operator == ">=":
        return actual >= expected - EPS
    if operator == "<=":
        return actual <= expected + EPS
    if operator in {"=", "=="}:
        return abs(actual - expected) <= EPS
    if operator == ">":
        return actual > expected + EPS
    if operator == "<":
        return actual < expected - EPS
    raise ValueError(f"Unsupported rule operator: {operator}")


def _as_dict(rule: Any) -> dict[str, Any]:
    if hasattr(rule, "model_dump"):
        return rule.model_dump()
    return dict(rule)


def _literal_chars(pattern: str) -> int:
    return sum(1 for char in pattern if char not in "*?[]")


def _specificity(rule: dict, entity: Room | Opening) -> tuple[float, float]:
    pattern = str(rule.get("applies_to", "*"))
    score = float(_literal_chars(pattern))
    filt = rule.get("applies_to_filter") or {}
    score += 10 * len(filt)
    if rule.get("excludes"):
        score += 5
    name = getattr(entity, "name", "") or ""
    if name and _glob(name, pattern):
        score += 25
    if getattr(entity, "kind", "") and _glob(entity.kind, pattern):
        score += 10
    try:
        canonical = from_rule_units(float(rule.get("value") or 0), str(rule.get("unit") or ""), metric_name(rule) == "area")
    except (ValueError, TypeError, ZeroDivisionError):
        canonical = 0.0
    operator = rule.get("operator", ">=")
    stringency = canonical if operator in {">=", ">"} else -canonical
    return score, stringency


def _blast(building: Building, room: Room | None) -> tuple[int, list[str]]:
    if room is None:
        return 0, []
    if not room.type_ref:
        return 1, [room.id]
    ids = [item.id for item in building.rooms if item.type_ref == room.type_ref]
    return len(ids), ids


def _geom_coords(geom: Polygon | None) -> list[list[float]] | None:
    if geom is None or geom.is_empty:
        return None
    polygon = geom
    if geom.geom_type == "MultiPolygon":
        polygon = max(geom.geoms, key=lambda item: item.area)
    if polygon.geom_type != "Polygon":
        return None
    return [[float(x), float(y)] for x, y in polygon.exterior.coords]


def _unverified_reason(room: Room, metric: str) -> str:
    label = (room.name or room.id).strip() or room.id
    metric_label = metric.replace("_", " ")
    reasons = []
    if not room.polygon or len(room.polygon) < 3:
        reasons.append("closed polygon is missing")
    name = (room.name or "").strip()
    if name in {"", "Unnamed"} or name.startswith("Space "):
        reasons.append("the room is unnamed")
    if room.confidence < 0.6:
        reasons.append(f"confidence is {room.confidence:.2f} (need at least 0.6)")
    if room.needs_review and not reasons:
        reasons.append("needs_review is set because the boundary was not tagged with a plausible area")
    detail = "; ".join(reasons) or "geometry is marked uncertain"
    return f"Cannot verify {metric_label} for '{label}': {detail}."


def _is_suspect(entity: Any) -> tuple[bool, str]:
    if isinstance(entity, tuple):
        for item in entity:
            if getattr(item, "reliability", "ok") == "suspect":
                return True, getattr(item, "reliability_reason", "") or "measurement is a statistical outlier"
        return False, ""
    if getattr(entity, "reliability", "ok") == "suspect":
        return True, getattr(entity, "reliability_reason", "") or "measurement is a statistical outlier"
    return False, ""


def _result(
    rule: dict,
    ids: list[str],
    actual: float | None,
    error: str = "",
    room: Room | None = None,
    building: Building | None = None,
    assumption: str = "",
    pinch: Polygon | None = None,
    superseded_by: str = "",
) -> dict:
    rule_id = str(rule.get("rule_id", "rule"))
    key = hashlib.sha256((rule_id + "|" + "|".join(ids)).encode()).hexdigest()[:14]
    expected = rule.get("value")
    unit = str(rule.get("unit", ""))
    metric = metric_name(rule)
    passed = False
    try:
        if not isinstance(expected, (float, int)) or not math.isfinite(expected):
            raise ValueError("The reviewed rule needs a finite numeric threshold.")
        if not error and actual is not None:
            passed = _compare(actual, expected, rule.get("operator", ">="))
    except ValueError as exc:
        error = str(exc)
    status = "cannot_verify" if error or actual is None else ("pass" if passed else "fail")
    label = room.name if room else ", ".join(ids)
    message = error or (
        f"{label}: {metric.replace('_', ' ')} {actual:.3f} {unit}; "
        f"required {rule.get('operator', '>=')} {expected:g} {unit}."
    )
    count, space_ids = _blast(building, room) if building else (1 if room else len(ids), [room.id] if room else list(ids))
    payload = {
        "id": f"check-{key}",
        "rule_id": rule_id,
        "entity_id": ids[0] if ids else "",
        "entity_ids": ids,
        "type_ref": (room.type_ref or room.category) if room else "",
        "metric": metric,
        "status": status,
        "severity": status,
        "actual": actual,
        "required": expected,
        "unit": unit,
        "operator": rule.get("operator", ">="),
        "delta": actual - expected if actual is not None and isinstance(expected, (float, int)) else None,
        "message": message,
        "instances_affected": count if count else (1 if room else len(ids)),
        "affected_space_ids": space_ids or ([room.id] if room else list(ids)),
        "source_doc": rule.get("source_doc", ""),
        "source_page": rule.get("source_page"),
        "source_label": rule.get("source_label", ""),
        "source_section": rule.get("source_section", ""),
        "source_text": rule.get("source_text", ""),
        "model_confidence": room.confidence if room else 1,
        "assumption": assumption,
        "pinch_polygon": _geom_coords(pinch),
        "superseded_by": superseded_by,
        "origin": rule.get("origin", ""),
        "contributing_room_ids": list(ids),
        "area_parts": [],
        "reason": "",
        "reliability_reason": "",
    }
    return payload


def _opening_room(opening: Opening, building: Building, rule: dict) -> Room | None:
    rooms = connected_rooms(opening, building)
    door_to = (rule.get("applies_to_filter") or {}).get("door_to")
    if door_to:
        hit = next((room for room in rooms if _room_hits_pattern(room, door_to)), None)
        if hit:
            return hit
    for room in rooms:
        if matches_room(room, {**rule, "excludes": rule.get("excludes") or []}):
            return room
    return rooms[0] if rooms else None


def _candidates(building: Building, rule: dict, metric: str, children_by_parent: dict[str, list[Room]] | None = None) -> list[Any]:
    if metric in {"area", "min_side"}:
        rooms = [room for room in building.rooms if matches_room(room, rule)]
        if metric == "area" and children_by_parent:
            child_to_parent = {child.id: parent_id for parent_id, kids in children_by_parent.items() for child in kids}
            by_id = {room.id: room for room in building.rooms}
            rooms = [
                room
                for room in rooms
                if room.id not in child_to_parent
                or not matches_room(by_id[child_to_parent[room.id]], rule)
            ]
        return rooms
    if metric in {"aperture_width", "clear_width"}:
        return [opening for opening in building.openings if opening.kind == "door" and matches_opening(opening, building, rule)]
    selected = [opening for opening in building.openings if matches_opening(opening, building, rule)]
    pairs = []
    for a, b in combinations(selected, 2):
        if a.kind != b.kind and (a.wall_id == b.wall_id or rule.get("target_ids")):
            pairs.append((a, b))
    return pairs


def _measure(building: Building, rule: dict, entity: Any, children_by_parent: dict[str, list[Room]] | None = None) -> dict:
    metric = metric_name(rule)
    assumption = ""
    pinch = None
    room = entity if isinstance(entity, Room) else None
    area_parts: list[dict[str, Any]] = []
    if isinstance(entity, tuple):
        ids = [item.id for item in entity]
    elif isinstance(entity, Opening):
        ids = [entity.id]
        room = _opening_room(entity, building, rule)
    else:
        ids = [entity.id]
    try:
        if isinstance(entity, Room) and (entity.needs_review or entity.confidence < 0.6):
            raise ValueError(_unverified_reason(entity, metric))
        if isinstance(entity, Room) and (not entity.polygon or len(entity.polygon) < 3):
            raise ValueError(_unverified_reason(entity, metric))
        if room and metric == "area":
            if room.category == "guestroom":
                value, area_parts = guestroom_unit_area(room, building, children_by_parent)
                ids = [part["id"] for part in area_parts] or ids
            else:
                value = room_area(room)
        elif room and metric == "min_side":
            required_ft = from_rule_units(float(rule.get("value") or 0), str(rule.get("unit") or ""), False)
            value, _unused = min_clear_width_ft(room)
            pinch = pinch_at_width(room, required_ft)
        elif metric == "opening_distance":
            value = opening_gap(*entity)
        elif metric == "clear_width":
            value, assumption = derived_clear_width_ft(entity)
        else:
            value = entity.width_ft
        actual = to_rule_units(value, rule.get("unit", ""), metric == "area")
        result = _result(rule, ids, actual, room=room, building=building, assumption=assumption, pinch=pinch)
        if area_parts:
            result["contributing_room_ids"] = [part["id"] for part in area_parts]
            result["area_parts"] = area_parts
            if len(area_parts) > 1 and result["status"] in {"pass", "fail"}:
                result["message"] = _composite_area_message(
                    room,
                    actual,
                    str(rule.get("unit") or ""),
                    float(rule.get("value") or 0),
                    str(rule.get("operator") or ">="),
                    area_parts,
                )
        if metric == "min_side" and room:
            # Morphological opening at the rule threshold is the pass/fail source of truth.
            required_ft = from_rule_units(float(rule.get("value") or 0), str(rule.get("unit") or ""), False)
            ok = pinch is None
            if not ok:
                result["status"] = "fail"
                result["severity"] = "fail"
                result["pinch_polygon"] = _geom_coords(pinch)
                if not result["message"].startswith("Review"):
                    result["message"] = (
                        f"{room.name}: min side {actual:.3f} {rule.get('unit')}; "
                        f"required {rule.get('operator', '>=')} {rule.get('value'):g} {rule.get('unit')}."
                    )
            elif result["status"] != "cannot_verify":
                result["status"] = "pass" if ok else "fail"
                result["severity"] = result["status"]
        suspect, reason = _is_suspect(entity)
        if suspect and result["status"] != "cannot_verify":
            result["status"] = "quarantined"
            result["severity"] = "quarantined"
            result["reliability"] = "suspect"
            result["reason"] = reason
            result["reliability_reason"] = reason
            measured = f"{result['actual']:.3f} {result['unit']}" if result.get("actual") is not None else "unmeasured"
            result["message"] = (
                f"Quarantined — {reason}. Measured {metric.replace('_', ' ')} {measured}; "
                "not reported as a violation."
            )
        return result
    except (ValueError, TypeError) as exc:
        return _result(rule, ids, None, str(exc), room=room, building=building, assumption=assumption)


def _coverage(rules: list[dict], unmatched: list[dict[str, str]]) -> dict[str, Any]:
    missing: dict[str, list[str]] = {}
    supported = unsupported = superseded = 0
    for rule in rules:
        metric = metric_name(rule)
        if rule.get("superseded_by"):
            superseded += 1
        if not rule.get("supported", True) or metric not in SUPPORTED_METRICS:
            unsupported += 1
            missing.setdefault(metric or "unclassified", []).append(str(rule.get("rule_id") or ""))
        else:
            supported += 1
    by_missing = [
        {"metric": metric, "count": len(ids), "example_rule_ids": ids[:5]}
        for metric, ids in sorted(missing.items(), key=lambda item: -len(item[1]))
    ]
    return {
        "rules_total": len(rules),
        "rules_supported": supported,
        "rules_unsupported": unsupported,
        "rules_superseded": superseded,
        "by_missing_metric": by_missing,
        "unmatched_rules": unmatched,
    }


def _split_checks(checks: list[dict]) -> dict[str, list[dict]]:
    groups = {"violations": [], "passes": [], "quarantined": [], "cannot_verify": []}
    for check in checks:
        status = check.get("status")
        if status == "fail":
            groups["violations"].append(check)
        elif status == "pass":
            groups["passes"].append(check)
        elif status == "quarantined":
            groups["quarantined"].append(check)
        elif status == "cannot_verify":
            groups["cannot_verify"].append(check)
    return groups


SCOPE_REVIEW_REASON = "threshold is more than 10× the median area of matched rooms."


def _area_scope_reason(rule: dict, building: Building) -> str:
    if metric_name(rule) != "area":
        return ""
    if str(rule.get("operator") or ">=") not in {">=", ">"}:
        return ""
    rooms = [room for room in building.rooms if matches_room(room, rule)]
    areas = [area for area in (_safe_area(room) for room in rooms) if area > EPS]
    if not areas:
        return ""
    try:
        threshold = from_rule_units(float(rule.get("value") or 0), str(rule.get("unit") or ""), True)
    except (ValueError, TypeError, ZeroDivisionError):
        return ""
    med = float(median(areas))
    if med <= EPS or threshold <= 10 * med:
        return ""
    unit = str(rule.get("unit") or "")
    return (
        f"{SCOPE_REVIEW_REASON} "
        f"Required {rule.get('value'):g} {unit}; median matched area {to_rule_units(med, unit, True):.3f} {unit}."
    )


def _set_rule_status(rule: dict, original: Any, status: str, reason: str = "") -> None:
    rule["status"] = status
    if reason:
        rule["scope_review_reason"] = reason
    elif "scope_review_reason" in rule:
        del rule["scope_review_reason"]
    if isinstance(original, dict):
        original["status"] = status
        if reason:
            original["scope_review_reason"] = reason
        else:
            original.pop("scope_review_reason", None)
    elif original is not None and hasattr(original, "status"):
        original.status = status


def evaluate_building(building: Building, rules: list[Any]) -> dict[str, Any]:
    originals = list(rules)
    parsed = [_as_dict(rule) for rule in originals]
    originals_by_id = {
        str(parsed_rule.get("rule_id") or ""): raw
        for raw, parsed_rule in zip(originals, parsed)
        if parsed_rule.get("rule_id")
    }
    children_by_parent = index_unit_children(building)
    runnable: list[dict] = []
    unmatched: list[dict[str, str]] = []
    for rule in parsed:
        status = str(rule.get("status") or "pending")
        if status not in {"approved", "needs_scope_review"}:
            continue
        if rule.get("superseded_by"):
            continue
        metric = metric_name(rule)
        if not rule.get("supported", True) or metric not in SUPPORTED_METRICS:
            continue
        reason = _area_scope_reason(rule, building)
        original = originals_by_id.get(str(rule.get("rule_id") or ""))
        if reason:
            _set_rule_status(rule, original, "needs_scope_review", reason)
            unmatched.append(
                {
                    "rule_id": str(rule.get("rule_id") or ""),
                    "applies_to": str(rule.get("applies_to") or ""),
                    "reason": reason,
                    "status": "needs_scope_review",
                }
            )
            continue
        if status == "needs_scope_review":
            _set_rule_status(rule, original, "approved")
        runnable.append(rule)

    groups: dict[tuple[str, str], list[tuple[dict, Any]]] = {}
    matched: set[str] = set()
    for rule in runnable:
        metric = metric_name(rule)
        for entity in _candidates(building, rule, metric, children_by_parent):
            entity_id = entity[0].id + "|" + entity[1].id if isinstance(entity, tuple) else entity.id
            groups.setdefault((entity_id, metric), []).append((rule, entity))
            matched.add(str(rule.get("rule_id")))

    unmatched.extend(
        {
            "rule_id": str(rule.get("rule_id") or ""),
            "applies_to": str(rule.get("applies_to") or ""),
            "reason": "applies_to matched no rooms or openings in the current model.",
        }
        for rule in runnable
        if str(rule.get("rule_id")) not in matched
    )

    checks = []
    for items in groups.values():
        ranked = sorted(
            items,
            key=lambda item: _specificity(item[0], item[1][0] if isinstance(item[1], tuple) else item[1]),
            reverse=True,
        )
        winner, entity = ranked[0]
        loser = str(ranked[1][0].get("rule_id") or "") if len(ranked) > 1 else ""
        check = _measure(building, winner, entity, children_by_parent)
        if loser:
            check["superseded_by"] = loser
        checks.append(check)
    split = _split_checks(checks)
    coverage = _coverage(parsed, unmatched)
    coverage["violations"] = len(split["violations"])
    coverage["quarantined"] = len(split["quarantined"])
    coverage["extraction_warnings"] = sum(1 for item in building.review if item.kind == "extraction")
    return {
        "checks": checks,
        "coverage": coverage,
        "violations": split["violations"],
        "passes": split["passes"],
        "quarantined": split["quarantined"],
    }


def check_building(building: Building, rules: list[dict]) -> list[dict[str, Any]]:
    """Run checks. The split lives on evaluate_building: violations / passes / quarantined."""
    return evaluate_building(building, rules)["checks"]
