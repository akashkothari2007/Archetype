"""Geometry helpers for sheet space.

Coordinate conventions
----------------------
Sheet space: PDF points, origin bottom-left, y UP.
PyMuPDF returns y DOWN from top-left. Flip **exactly once** at the read
boundary with :func:`flip_y` and never again.

Building space: feet, y up, origin at a named grid intersection.
    ft = (pt - sheet_origin_pt) / scale_pts_per_ft
World space (3D): plan (x, y) -> world (x, z), extrude along world y.

``ASSUMED_WALL_HEIGHT_FT`` and ``ASSUMED_WALL_THICKNESS_FT`` are rendering
conventions, not extracted data. 2D plans carry no elevation. Label them
assumed anywhere they are shown. Never call this clash detection.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

Point = Sequence[float]
Segment = tuple[tuple[float, float], tuple[float, float]]

ASSUMED_WALL_HEIGHT_FT = 9.0
ASSUMED_WALL_THICKNESS_FT = 0.5


def flip_y(y_pymupdf: float, page_height: float) -> float:
    """Convert a PyMuPDF y (down from top-left) to sheet-space y (up from bottom-left).

    This is the only place in PlanCheck that inverts a y coordinate.
    """
    return page_height - y_pymupdf


def flip_point(
    x: float, y_pymupdf: float, page_height: float
) -> tuple[float, float]:
    """Flip a PyMuPDF point into sheet space. Uses :func:`flip_y` once."""
    return (x, flip_y(y_pymupdf, page_height))


def plan_to_world(
    x: float, y: float, elevation: float = 0.0
) -> tuple[float, float, float]:
    """Building plan (x, y) -> world (x, z) with extrusion along world y."""
    return (x, elevation, y)


def pt_to_ft(pt: float, origin_pt: float, scale_pts_per_ft: float) -> float:
    """Building feet from sheet points: ``(pt - origin) / scale``."""
    if scale_pts_per_ft == 0:
        raise ValueError("scale_pts_per_ft must be non-zero")
    return (pt - origin_pt) / scale_pts_per_ft


def bbox(points: Iterable[Point]) -> tuple[float, float, float, float]:
    """Axis-aligned bounding box ``(min_x, min_y, max_x, max_y)``."""
    xs: list[float] = []
    ys: list[float] = []
    for p in points:
        xs.append(float(p[0]))
        ys.append(float(p[1]))
    if not xs:
        raise ValueError("bbox() requires at least one point")
    return (min(xs), min(ys), max(xs), max(ys))


def polygon_area(points: Sequence[Point]) -> float:
    """Absolute shoelace area. ``points`` may be open or closed."""
    if len(points) < 3:
        return 0.0
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = float(points[i][0]), float(points[i][1])
        x2, y2 = float(points[(i + 1) % n][0]), float(points[(i + 1) % n][1])
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def snap_to_axis(
    a: Point,
    b: Point,
    angle_tol_deg: float = 5.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Snap a near-horizontal or near-vertical segment onto the axis."""
    x0, y0 = float(a[0]), float(a[1])
    x1, y1 = float(b[0]), float(b[1])
    dx, dy = x1 - x0, y1 - y0
    if dx == 0.0 and dy == 0.0:
        return (x0, y0), (x1, y1)
    ang = abs(math.degrees(math.atan2(dy, dx))) % 180.0
    if min(ang, 180.0 - ang) <= angle_tol_deg:
        y = (y0 + y1) / 2.0
        return (x0, y), (x1, y)
    if abs(ang - 90.0) <= angle_tol_deg:
        x = (x0 + x1) / 2.0
        return (x, y0), (x, y1)
    return (x0, y0), (x1, y1)


def _dist(p: tuple[float, float], q: tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _colinear(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    tol: float,
) -> bool:
    area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    ab = _dist(a, b)
    if ab == 0:
        return _dist(a, c) <= tol
    return (area2 / ab) <= tol


def merge_segments(
    segments: Sequence[Segment],
    tolerance: float = 1.0,
) -> list[Segment]:
    """Merge colinear segments that share an endpoint within ``tolerance``."""
    remaining: list[Segment] = [
        ((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
        for a, b in segments
    ]
    merged: list[Segment] = []
    while remaining:
        (a, b) = remaining.pop()
        changed = True
        while changed:
            changed = False
            keep: list[Segment] = []
            for c, d in remaining:
                candidate = _try_merge((a, b), (c, d), tolerance)
                if candidate is None:
                    keep.append((c, d))
                else:
                    a, b = candidate
                    changed = True
            remaining = keep
        merged.append((a, b))
    return merged


def _try_merge(
    s1: Segment, s2: Segment, tol: float
) -> Segment | None:
    pairs = (
        (s1[0], s1[1], s2[0], s2[1]),
        (s1[0], s1[1], s2[1], s2[0]),
        (s1[1], s1[0], s2[0], s2[1]),
        (s1[1], s1[0], s2[1], s2[0]),
    )
    for p, q, r, s in pairs:
        if _dist(q, r) > tol:
            continue
        if not (_colinear(p, q, s, tol) and _colinear(p, s, q, tol)):
            continue
        # q≈r; extend p--q with r--s => p--s
        return (p, s)
    return None
