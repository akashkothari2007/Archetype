"""Deterministic measurements over the same building the editors display.

Only explicitly approved rules run. Missing data is never treated as compliance.
All stored geometry is in feet; each result uses the rule's original unit.
"""
from __future__ import annotations

import fnmatch
import hashlib
import math
from itertools import combinations
from typing import Any

from plancheck.core.building import Building, Room, Opening

EPS = 1e-7
METRIC_ALIASES = {"room.area": "area", "room.min_side": "min_side", "width": "min_side",
                  "door.aperture_width": "aperture_width", "door.clear_width": "clear_width",
                  "opening.separation": "opening_distance"}


def metric_name(rule: dict) -> str:
    name = rule.get("metric", "")
    return METRIC_ALIASES.get(name, name)


def canonical_unit(unit: str) -> str:
    return str(unit).lower().replace("²", "2").replace(" ", "").replace("sq.", "sq").replace("square", "sq")


def to_rule_units(value: float, unit: str, area: bool = False) -> float:
    unit = canonical_unit(unit)
    factors = ({"ft2": 1, "sqft": 1, "feet2": 1, "m2": 0.09290304, "sqm": 0.09290304}
               if area else {"ft": 1, "feet": 1, "foot": 1, "m": 0.3048, "cm": 30.48,
                             "mm": 304.8, "in": 12, "inch": 12, "inches": 12})
    if unit not in factors:
        raise ValueError(f"Unsupported {'area' if area else 'length'} unit: {unit}")
    return value * factors[unit]


def from_rule_units(value: float, unit: str, area: bool = False) -> float:
    return value / to_rule_units(1, unit, area)


def polygon_points(room: Room) -> list[tuple[float, float]]:
    points = list(room.polygon)
    if points and points[0] == points[-1]:
        points.pop()
    # Remove only collinear intermediate vertices; rotation is preserved.
    changed = True
    while changed and len(points) > 3:
        changed = False
        for i, p in enumerate(points):
            a, b = points[i - 1], points[(i + 1) % len(points)]
            cross = (p[0]-a[0])*(b[1]-p[1])-(p[1]-a[1])*(b[0]-p[0])
            dot = (p[0]-a[0])*(b[0]-p[0])+(p[1]-a[1])*(b[1]-p[1])
            if abs(cross) < EPS and dot >= 0:
                points.pop(i)
                changed = True
                break
    return points


def room_area(room: Room) -> float:
    points = polygon_points(room)
    if len(points) < 3:
        raise ValueError("A closed room boundary is required.")
    from shapely.geometry import Polygon
    polygon = Polygon(points)
    if not polygon.is_valid or polygon.area <= EPS:
        raise ValueError("Room boundary is invalid or has no measurable area.")
    return float(polygon.area)


def rectangle_sides(room: Room) -> tuple[float, float]:
    points = polygon_points(room)
    room_area(room)
    if len(points) != 4:
        raise ValueError("Minimum-side verification currently requires a rectangular room.")
    vectors = [(points[(i+1)%4][0]-p[0], points[(i+1)%4][1]-p[1]) for i,p in enumerate(points)]
    lengths = [math.hypot(*v) for v in vectors]
    for i, v in enumerate(vectors):
        other = vectors[(i+1)%4]
        if lengths[i] <= EPS or abs(v[0]*other[0]+v[1]*other[1]) > EPS*max(1,lengths[i]*lengths[(i+1)%4]):
            raise ValueError("Minimum-side verification currently requires a rectangular room.")
    return lengths[0], lengths[1]


def matches_room(room: Room, rule: dict) -> bool:
    ids = rule.get("target_ids") or []
    if ids:
        return room.id in ids
    pattern = str(rule.get("applies_to", "*")).lower()
    values = [room.id, room.category, room.type_ref, room.name, room.name.replace(" ", "_")]
    return any(fnmatch.fnmatchcase(v.lower(), pattern) for v in values if v)


def matches_opening(opening: Opening, building: Building, rule: dict) -> bool:
    if rule.get("target_ids"):
        return opening.id in rule["target_ids"]
    pattern = str(rule.get("applies_to", "*")).lower()
    if any(fnmatch.fnmatchcase(v.lower(), pattern) for v in [opening.id, opening.kind]):
        return True
    return any(opening.wall_id in room.wall_ids and matches_room(room, rule) for room in building.rooms)


def opening_gap(a: Opening, b: Opening) -> float:
    if a.wall_id != b.wall_id:
        raise ValueError("Opening separation is supported only on the same straight host wall.")
    return max(0, max(a.offset_ft, b.offset_ft)-min(a.offset_ft+a.width_ft, b.offset_ft+b.width_ft))


def _compare(actual: float, expected: float, operator: str) -> bool:
    if operator == ">=": return actual >= expected-EPS
    if operator == "<=": return actual <= expected+EPS
    if operator in {"=", "=="}: return abs(actual-expected) <= EPS
    if operator == ">": return actual > expected+EPS
    if operator == "<": return actual < expected-EPS
    raise ValueError(f"Unsupported rule operator: {operator}")


def _result(rule: dict, ids: list[str], actual: float | None, error: str = "", room: Room | None = None) -> dict:
    rule_id = str(rule.get("rule_id", "rule"))
    key = hashlib.sha256((rule_id+"|"+"|".join(ids)).encode()).hexdigest()[:14]
    expected = rule.get("value")
    unit = str(rule.get("unit", ""))
    metric = metric_name(rule)
    passed = False
    try:
        if not isinstance(expected, (float,int)) or not math.isfinite(expected):
            raise ValueError("The reviewed rule needs a finite numeric threshold.")
        if not error and actual is not None:
            passed = _compare(actual, expected, rule.get("operator", ">="))
    except ValueError as exc:
        error = str(exc)
    status = "cannot_verify" if error or actual is None else ("pass" if passed else "fail")
    label = room.name if room else ", ".join(ids)
    message = error or f"{label}: {metric.replace('_',' ')} {actual:.3f} {unit}; required {rule.get('operator','>=')} {expected:g} {unit}."
    return {"id": f"check-{key}", "rule_id": rule_id, "entity_id": ids[0] if ids else "",
            "entity_ids": ids, "type_ref": room.type_ref or room.category if room else "",
            "metric": metric, "status": status, "severity": status, "actual": actual,
            "required": expected, "unit": unit, "operator": rule.get("operator", ">="),
            "delta": actual-expected if actual is not None and isinstance(expected,(float,int)) else None,
            "message": message, "instances_affected": 1 if room else len(ids),
            "affected_space_ids": [room.id] if room else [], "source_doc": rule.get("source_doc", ""),
            "source_page": rule.get("source_page"), "source_label": rule.get("source_label", ""),
            "source_section": rule.get("source_section", ""), "source_text": rule.get("source_text", ""),
            "model_confidence": room.confidence if room else 1}


def check_building(building: Building, rules: list[dict]) -> list[dict[str, Any]]:
    results = []
    for original in rules:
        rule = original.model_dump() if hasattr(original, "model_dump") else dict(original)
        if rule.get("status", "pending") != "approved":
            continue
        metric = metric_name(rule)
        if not rule.get("supported", True) or metric not in {"area","min_side","aperture_width","clear_width","opening_distance"}:
            results.append(_result(rule, rule.get("target_ids") or [], None, "This rule needs information or a measurement the current model cannot verify."))
            continue
        candidates = []
        if metric in {"area","min_side"}:
            candidates = [(room.id, room) for room in building.rooms if matches_room(room, rule)]
        elif metric in {"aperture_width","clear_width"}:
            candidates = [(o.id,o) for o in building.openings if o.kind == "door" and matches_opening(o,building,rule)]
        else:
            selected = [o for o in building.openings if matches_opening(o,building,rule)]
            candidates = [(a.id+"|"+b.id,(a,b)) for a,b in combinations(selected,2)
                          if a.kind != b.kind and (a.wall_id==b.wall_id or rule.get("target_ids"))]
        if not candidates:
            results.append(_result(rule,rule.get("target_ids") or [],None,"No matching, measurable entities are available for this rule's reviewed scope."))
        for _, entity in candidates:
            ids = [x.id for x in entity] if isinstance(entity,tuple) else [entity.id]
            room = entity if isinstance(entity,Room) else None
            try:
                if room:
                    if room.needs_review or room.confidence < 0.6:
                        raise ValueError("Review the uncertain room geometry before verifying this rule.")
                    value = room_area(room) if metric == "area" else min(rectangle_sides(room))
                elif metric == "opening_distance":
                    value = opening_gap(*entity)
                elif metric == "clear_width":
                    if entity.clear_width_ft is None:
                        raise ValueError("Clear door width is unknown; an aperture or nominal door width cannot substitute for it.")
                    value = entity.clear_width_ft
                else:
                    value = entity.width_ft
                actual = to_rule_units(value,rule.get("unit", ""),metric=="area")
                results.append(_result(rule,ids,actual,room=room))
            except (ValueError, TypeError) as exc:
                results.append(_result(rule,ids,None,str(exc),room=room))
    return results
