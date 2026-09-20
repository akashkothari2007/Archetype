"""MEP grid registration and mep.json assembly.

Aligns MEP sheets to architectural sheets by matching grid bubble labels,
solving a 2D similarity transform, and transforming equipment positions
into building feet.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from plancheck.core.schemas import GridBubble, MepSheetData, SheetGeometry


# 2D plans carry no elevation data. These are rendering conventions only.
# Never used for any check.
ASSUMED_Z: dict[str, float] = {
    "plumbing": -1.0,
    "power": 1.5,
    "hvac": 8.5,
    "lighting": 9.0,
}
DEFAULT_Z = 1.5


def match_grid_bubbles(
    arch_bubbles: list[GridBubble],
    mep_bubbles: list[GridBubble],
) -> list[tuple[str, list[float], list[float]]]:
    """Match by label text (case-insensitive), discard duplicates."""
    def label_map(bubbles: list[GridBubble]) -> dict[str, list[float]]:
        counts: dict[str, int] = {}
        pts: dict[str, list[float]] = {}
        for b in bubbles:
            key = b.label.upper()
            counts[key] = counts.get(key, 0) + 1
            pts[key] = b.xy
        return {k: v for k, v in pts.items() if counts[k] == 1}

    arch_map = label_map(arch_bubbles)
    mep_map = label_map(mep_bubbles)
    pairs = []
    for label in arch_map:
        if label in mep_map:
            pairs.append((label, arch_map[label], mep_map[label]))
    return pairs


def solve_transform(
    pairs: list[tuple[str, list[float], list[float]]],
) -> dict:
    """Solve 2D similarity transform from matched grid bubble pairs.

    Returns dict with transform [a,b,c,d,e,f], matched_labels, rms_error_ft, confidence.
    """
    if len(pairs) < 2:
        return {
            "transform": [1, 0, 0, 0, 1, 0],
            "matched_labels": [p[0] for p in pairs],
            "rms_error_ft": 9999.0,
            "confidence": "manual",
        }

    # Collect source (mep) and target (arch) points
    src = [(p[2][0], p[2][1]) for p in pairs]
    dst = [(p[1][0], p[1][1]) for p in pairs]
    n = len(pairs)

    if n == 2:
        # Exact solution: scale + rotation + translation from 2 pairs
        sx0, sy0 = src[0]
        sx1, sy1 = src[1]
        dx0, dy0 = dst[0]
        dx1, dy1 = dst[1]
        src_dx, src_dy = sx1 - sx0, sy1 - sy0
        dst_dx, dst_dy = dx1 - dx0, dy1 - dy0
        src_len = math.hypot(src_dx, src_dy)
        dst_len = math.hypot(dst_dx, dst_dy)
        if src_len < 1e-9:
            return {
                "transform": [1, 0, 0, 0, 1, 0],
                "matched_labels": [p[0] for p in pairs],
                "rms_error_ft": 9999.0,
                "confidence": "manual",
            }
        s = dst_len / src_len
        src_angle = math.atan2(src_dy, src_dx)
        dst_angle = math.atan2(dst_dy, dst_dx)
        theta = dst_angle - src_angle
        a = s * math.cos(theta)
        b = -s * math.sin(theta)
        d = s * math.sin(theta)
        e = s * math.cos(theta)
        c = dx0 - a * sx0 - b * sy0
        f = dy0 - d * sx0 - e * sy0
        rms = 0.0
    else:
        # Least-squares 2D similarity transform (3+ pairs)
        # x' = a*x + b*y + c
        # y' = d*x + e*y + f  where a=s*cos, b=-s*sin, d=s*sin, e=s*cos
        # Build normal equations for [a, b, c] and [d, e, f] simultaneously
        sum_x = sum(p[0] for p in src)
        sum_y = sum(p[1] for p in src)
        sum_xx = sum(p[0] ** 2 for p in src)
        sum_yy = sum(p[1] ** 2 for p in src)
        sum_xy = sum(p[0] * p[1] for p in src)
        sum_xp = sum(s[0] * d[0] + s[1] * d[1] for s, d in zip(src, dst))
        sum_yp = sum(s[1] * d[0] - s[0] * d[1] for s, d in zip(src, dst))
        sum_xdst = sum(d[0] for d in dst)
        sum_ydst = sum(d[1] for d in dst)

        # Similarity constraint: a=e, b=-d
        # Solve: [sum_xx+sum_yy, sum_x, sum_y] [a]   [sum_xp]
        #        [sum_x,         n,     0    ] [c] = [sum_xdst]
        #        [sum_y,         0,     n    ] [tx]  [sum_ydst] (for x-component)
        # Plus same with b=-d for rotation component
        det_main = n * (sum_xx + sum_yy) - sum_x * sum_x - sum_y * sum_y
        if abs(det_main) < 1e-12:
            return {
                "transform": [1, 0, 0, 0, 1, 0],
                "matched_labels": [p[0] for p in pairs],
                "rms_error_ft": 9999.0,
                "confidence": "manual",
            }

        a_val = (n * sum_xp - sum_x * sum_xdst - sum_y * sum_ydst) / det_main
        b_val = (n * sum_yp - sum_y * sum_xdst + sum_x * sum_ydst) / det_main
        c_val = (sum_xdst - a_val * sum_x - b_val * sum_y) / n
        f_val = (sum_ydst - a_val * sum_y + b_val * sum_x) / n

        a = a_val
        b = -b_val
        d = b_val
        e = a_val
        c = c_val
        f = f_val

        # Compute RMS residual
        total = 0.0
        for s, dd in zip(src, dst):
            px = a * s[0] + b * s[1] + c
            py = d * s[0] + e * s[1] + f
            total += (px - dd[0]) ** 2 + (py - dd[1]) ** 2
        rms = math.sqrt(total / n)

    confidence = "high" if rms < 0.5 else "medium" if rms < 2.0 else "low"
    return {
        "transform": [a, b, c, d, e, f],
        "matched_labels": [p[0] for p in pairs],
        "rms_error_ft": round(rms, 4),
        "confidence": confidence,
    }


def register_sheet(
    arch_geom: SheetGeometry,
    mep_data: MepSheetData,
    arch_scale: float,
) -> dict:
    """Register MEP sheet to architectural sheet via grid bubbles.

    Returns dict with transform, registration info, and transformed equipment.
    """
    pairs = match_grid_bubbles(arch_geom.grid.bubbles, mep_data.grid.bubbles)
    if len(pairs) < 2:
        # Identity transform with manual confidence
        result = solve_transform([])
        result["equipment"] = [
            {
                "tag": eq.tag,
                "xy_ft": [eq.xy_pt[0] / arch_scale, eq.xy_pt[1] / arch_scale],
                "in_room": None,
                "kind": eq.kind,
                "assumed_z_ft": ASSUMED_Z.get(eq.kind, DEFAULT_Z),
                "z_assumed": True,
            }
            for eq in mep_data.equipment
        ]
        return result

    result = solve_transform(pairs)
    tf = result["transform"]
    a, b, c, d, e, f = tf

    # Transform equipment: mep sheet pt → arch sheet pt → building feet
    equipment = []
    for eq in mep_data.equipment:
        mx, my = eq.xy_pt
        # Apply similarity transform to get arch sheet pt
        ax = a * mx + b * my + c
        ay = d * mx + e * my + f
        # Convert from arch sheet pt to feet
        fx = ax / arch_scale
        fy = ay / arch_scale
        equipment.append({
            "tag": eq.tag,
            "xy_ft": [round(fx, 3), round(fy, 3)],
            "in_room": None,
            "kind": eq.kind,
            "assumed_z_ft": ASSUMED_Z.get(eq.kind, DEFAULT_Z),
            "z_assumed": True,
        })
    result["equipment"] = equipment
    return result


def assign_rooms(
    equipment: list[dict],
    rooms: list[dict],
) -> list[dict]:
    """Point-in-polygon each equipment point against floor room polygons."""
    try:
        from shapely.geometry import Point, Polygon
    except ImportError:
        return equipment

    polys = []
    for room in rooms:
        poly = room.get("polygon", [])
        if len(poly) >= 3:
            try:
                polys.append((room["id"], Polygon(poly)))
            except Exception:
                continue

    for eq in equipment:
        pt = Point(eq["xy_ft"])
        for room_id, polygon in polys:
            if polygon.contains(pt):
                eq["in_room"] = room_id
                break
    return equipment


def build_mep_json(
    sheets: list[dict],
    registrations: dict[str, dict],
    floor_map: dict[str, str],
) -> dict:
    """Assemble the mep.json handoff file.

    Args:
        sheets: list of MEP sheet dicts with sheet_id, discipline, page, raster_url
        registrations: {sheet_id: registration result from register_sheet}
        floor_map: {sheet_id: floor_id}
    """
    floors: dict[str, dict] = {}
    for sheet in sheets:
        sid = sheet["sheet_id"]
        reg = registrations.get(sid)
        if not reg:
            continue
        floor_id = floor_map.get(sid, "unknown")
        if floor_id not in floors:
            floors[floor_id] = {"floor_id": floor_id, "disciplines": []}
        layer = {
            "discipline": sheet.get("discipline", "unknown"),
            "sheet_id": sid,
            "page": sheet.get("page", 0),
            "raster_url": sheet.get("raster_url", ""),
            "transform": reg["transform"],
            "registration": {
                "rms_error_ft": reg["rms_error_ft"],
                "confidence": reg["confidence"],
                "matched_labels": reg["matched_labels"],
            },
            "equipment": reg.get("equipment", []),
        }
        floors[floor_id]["disciplines"].append(layer)

    return {"floors": list(floors.values())}
