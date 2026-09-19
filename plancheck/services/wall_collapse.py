"""Collapse raw CAD wall strokes into centerline walls with thickness."""
from __future__ import annotations

import math
from dataclasses import dataclass

MIN_WALL_FT = 1.0
VERTEX_SNAP_FT = 0.05
LANE_TOL_FT = 0.08
MERGE_GAP_FT = 0.35
PAIR_OFFSET_MIN_FT = 0.2
PAIR_OFFSET_MAX_FT = 1.2
JAMB_KEEP_FT = 0.1
JAMB_MAX_FT = 0.45
PAIR_OVERLAP = 0.6
DEFAULT_THICKNESS_FT = 0.5
VERTEX_WELD_FT = 0.12
PARALLEL_DOT_TOL = 0.02
DIAGONAL_ANGLE_BIN = 0.05

_STRUCT_RANK = {"loadbearing": 2, "unknown": 1, "nonstructural": 0}


@dataclass(frozen=True)
class CollapsedWall:
    start: tuple[float, float]
    end: tuple[float, float]
    structural: str
    thickness_ft: float
    assumed: bool


def snap_point(p, grid: float = VERTEX_SNAP_FT) -> tuple[float, float]:
    return (round(p[0] / grid) * grid, round(p[1] / grid) * grid)


def segment_length(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def total_run_length(segments) -> float:
    return sum(segment_length(item[0], item[1]) for item in segments)


def merge_structural(a: str, b: str) -> str:
    return a if _STRUCT_RANK.get(a, 1) >= _STRUCT_RANK.get(b, 1) else b


def _as_seg(item) -> tuple[tuple[float, float], tuple[float, float], str]:
    start = (float(item[0][0]), float(item[0][1]))
    end = (float(item[1][0]), float(item[1][1]))
    structural = item[2] if len(item) > 2 else "unknown"
    return start, end, structural


def _is_vertical(a, b, tol: float = LANE_TOL_FT) -> bool:
    return abs(b[0] - a[0]) <= tol


def _is_horizontal(a, b, tol: float = LANE_TOL_FT) -> bool:
    return abs(b[1] - a[1]) <= tol


def _near_endpoint(p, buckets, tol: float = JAMB_KEEP_FT) -> bool:
    gx, gy = round(p[0] / tol), round(p[1] / tol)
    for ix in (gx - 1, gx, gx + 1):
        for iy in (gy - 1, gy, gy + 1):
            for q in buckets.get((ix, iy), ()):
                if math.hypot(p[0] - q[0], p[1] - q[1]) <= tol:
                    return True
    return False


def _direction(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return dx / length, dy / length, length


def _attached_and_collinear(a, b, long_segments, buckets) -> bool:
    """Tessellation sits collinear with a kept run; jambs are returns, not collinear."""
    direction = _direction(a, b)
    if not direction:
        return True
    ux, uy, _ = direction
    for start, end, _ in long_segments:
        if not (
            math.hypot(a[0] - start[0], a[1] - start[1]) <= JAMB_KEEP_FT
            or math.hypot(a[0] - end[0], a[1] - end[1]) <= JAMB_KEEP_FT
            or math.hypot(b[0] - start[0], b[1] - start[1]) <= JAMB_KEEP_FT
            or math.hypot(b[0] - end[0], b[1] - end[1]) <= JAMB_KEEP_FT
        ):
            continue
        other = _direction(start, end)
        if not other:
            continue
        vx, vy, _ = other
        if abs(abs(ux * vx + uy * vy) - 1.0) <= 0.15:
            return True
    return False


def filter_short_segments(segments):
    long, short = [], []
    for item in segments:
        a, b, structural = _as_seg(item)
        if segment_length(a, b) >= MIN_WALL_FT:
            long.append((a, b, structural))
        else:
            short.append((a, b, structural))
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for a, b, _ in long:
        for p in (a, b):
            key = (round(p[0] / JAMB_KEEP_FT), round(p[1] / JAMB_KEEP_FT))
            buckets.setdefault(key, []).append(p)
    kept = list(long)
    for a, b, structural in short:
        if segment_length(a, b) > JAMB_MAX_FT:
            continue
        if not (_near_endpoint(a, buckets) and _near_endpoint(b, buckets)):
            continue
        if _attached_and_collinear(a, b, long, buckets):
            continue
        kept.append((a, b, structural))
    return kept


def _union_intervals(items, gap: float):
    ordered = sorted(items, key=lambda t: (t[0], t[1]))
    out: list[list] = []
    for lo, hi, structural in ordered:
        if hi - lo <= 1e-9:
            continue
        if not out or lo - out[-1][1] > gap:
            out.append([lo, hi, structural])
        else:
            out[-1][1] = max(out[-1][1], hi)
            out[-1][2] = merge_structural(out[-1][2], structural)
    return [(lo, hi, structural) for lo, hi, structural in out]


def _merge_axis(segments, axis: str):
    buckets: dict[int, list] = {}
    for a, b, structural in segments:
        if axis == "v":
            coord = (a[0] + b[0]) / 2
            lo, hi = sorted((a[1], b[1]))
        else:
            coord = (a[1] + b[1]) / 2
            lo, hi = sorted((a[0], b[0]))
        buckets.setdefault(round(coord / LANE_TOL_FT), []).append((lo, hi, structural, coord))
    merged = []
    for items in buckets.values():
        lane = sum(item[3] for item in items) / len(items)
        for lo, hi, structural in _union_intervals([(item[0], item[1], item[2]) for item in items], MERGE_GAP_FT):
            if axis == "v":
                merged.append(((lane, lo), (lane, hi), structural))
            else:
                merged.append(((lo, lane), (hi, lane), structural))
    return merged


def _merge_diagonal(segments):
    buckets: dict[tuple[int, int], list] = {}
    for a, b, structural in segments:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        ux, uy = dx / length, dy / length
        if ux < -1e-12 or (abs(ux) <= 1e-12 and uy < 0):
            ux, uy = -ux, -uy
            a, b = b, a
        angle = math.atan2(uy, ux)
        offset = a[0] * (-uy) + a[1] * ux
        t0 = a[0] * ux + a[1] * uy
        t1 = b[0] * ux + b[1] * uy
        key = (round(angle / DIAGONAL_ANGLE_BIN), round(offset / LANE_TOL_FT))
        buckets.setdefault(key, []).append((min(t0, t1), max(t0, t1), structural, ux, uy, offset))
    merged = []
    for items in buckets.values():
        ux = sum(item[3] for item in items) / len(items)
        uy = sum(item[4] for item in items) / len(items)
        norm = math.hypot(ux, uy) or 1.0
        ux, uy = ux / norm, uy / norm
        offset = sum(item[5] for item in items) / len(items)
        nx, ny = -uy, ux
        for lo, hi, structural in _union_intervals([(item[0], item[1], item[2]) for item in items], MERGE_GAP_FT):
            start = (lo * ux + offset * nx, lo * uy + offset * ny)
            end = (hi * ux + offset * nx, hi * uy + offset * ny)
            merged.append((start, end, structural))
    return merged


def merge_collinear(segments):
    snapped = []
    for item in segments:
        a, b, structural = _as_seg(item)
        a, b = snap_point(a), snap_point(b)
        if segment_length(a, b) < 1e-9:
            continue
        snapped.append((a, b, structural))
    vertical, horizontal, diagonal = [], [], []
    for a, b, structural in snapped:
        vert, horiz = _is_vertical(a, b), _is_horizontal(a, b)
        if vert and not horiz:
            vertical.append((a, b, structural))
        elif horiz and not vert:
            horizontal.append((a, b, structural))
        elif vert and horiz:
            continue
        else:
            diagonal.append((a, b, structural))
    return _merge_axis(vertical, "v") + _merge_axis(horizontal, "h") + _merge_diagonal(diagonal)


def _project(origin, ux, uy, p) -> float:
    return (p[0] - origin[0]) * ux + (p[1] - origin[1]) * uy


def _point(origin, ux, uy, t):
    return (origin[0] + ux * t, origin[1] + uy * t)


def _try_pair(first, second):
    a, b, s1 = first
    c, d, s2 = second
    dir1 = _direction(a, b)
    dir2 = _direction(c, d)
    if not dir1 or not dir2:
        return None
    u1x, u1y, length1 = dir1
    u2x, u2y, length2 = dir2
    if abs(abs(u1x * u2x + u1y * u2y) - 1.0) > PARALLEL_DOT_TOL:
        return None
    nx, ny = -u1y, u1x
    offset = abs((c[0] - a[0]) * nx + (c[1] - a[1]) * ny)
    if not (PAIR_OFFSET_MIN_FT <= offset <= PAIR_OFFSET_MAX_FT):
        return None
    i1 = sorted((_project(a, u1x, u1y, a), _project(a, u1x, u1y, b)))
    i2 = sorted((_project(a, u1x, u1y, c), _project(a, u1x, u1y, d)))
    lo, hi = max(i1[0], i2[0]), min(i1[1], i2[1])
    overlap = hi - lo
    if overlap <= 0 or overlap / min(length1, length2) <= PAIR_OVERLAP:
        return None
    p1a, p1b = _point(a, u1x, u1y, lo), _point(a, u1x, u1y, hi)
    t_c = _project(a, u1x, u1y, c)
    p2a = _point(c, u1x, u1y, lo - t_c)
    p2b = _point(c, u1x, u1y, hi - t_c)
    start = ((p1a[0] + p2a[0]) / 2, (p1a[1] + p2a[1]) / 2)
    end = ((p1b[0] + p2b[0]) / 2, (p1b[1] + p2b[1]) / 2)
    leftovers = []
    if lo - i1[0] >= MIN_WALL_FT:
        leftovers.append((_point(a, u1x, u1y, i1[0]), _point(a, u1x, u1y, lo), s1))
    if i1[1] - hi >= MIN_WALL_FT:
        leftovers.append((_point(a, u1x, u1y, hi), _point(a, u1x, u1y, i1[1]), s1))
    if lo - i2[0] >= MIN_WALL_FT:
        leftovers.append((_point(c, u1x, u1y, i2[0] - t_c), _point(c, u1x, u1y, lo - t_c), s2))
    if i2[1] - hi >= MIN_WALL_FT:
        leftovers.append((_point(c, u1x, u1y, hi - t_c), _point(c, u1x, u1y, i2[1] - t_c), s2))
    wall = CollapsedWall(start, end, merge_structural(s1, s2), offset, False)
    return wall, leftovers


def pair_parallel_faces(segments) -> list[CollapsedWall]:
    pending = [_as_seg(item) for item in segments]
    out: list[CollapsedWall] = []
    while pending:
        pending.sort(key=lambda item: -segment_length(item[0], item[1]))
        current = pending.pop(0)
        best_i = None
        best = None
        for i, other in enumerate(pending):
            hit = _try_pair(current, other)
            if hit and (best is None or hit[0].thickness_ft >= 0) and hit:
                overlap = segment_length(hit[0].start, hit[0].end)
                if best is None or overlap > best[0]:
                    best = (overlap, i, hit)
        if best is None:
            a, b, structural = current
            out.append(CollapsedWall(a, b, structural, DEFAULT_THICKNESS_FT, True))
            continue
        _overlap, index, (wall, leftovers) = best
        pending.pop(index)
        out.append(wall)
        pending.extend(leftovers)
    return out


def merge_collapsed_walls(walls: list[CollapsedWall]) -> list[CollapsedWall]:
    """Union collinear centerlines after pairing, keeping measured thickness."""
    if not walls:
        return []
    merged = merge_collinear([(w.start, w.end, w.structural) for w in walls])
    out = []
    for start, end, structural in merged:
        direction = _direction(start, end)
        if not direction:
            continue
        ux, uy, length = direction
        nx, ny = -uy, ux
        thick = DEFAULT_THICKNESS_FT
        assumed = True
        for wall in walls:
            other = _direction(wall.start, wall.end)
            if not other:
                continue
            vx, vy, _ = other
            if abs(abs(ux * vx + uy * vy) - 1.0) > PARALLEL_DOT_TOL:
                continue
            offset = abs((wall.start[0] - start[0]) * nx + (wall.start[1] - start[1]) * ny)
            if offset > LANE_TOL_FT:
                continue
            t0 = _project(start, ux, uy, wall.start)
            t1 = _project(start, ux, uy, wall.end)
            lo, hi = sorted((t0, t1))
            overlap = min(length, hi) - max(0.0, lo)
            if overlap <= 0:
                continue
            if not wall.assumed and wall.thickness_ft >= thick:
                thick = wall.thickness_ft
                assumed = False
            elif wall.assumed and assumed:
                thick = max(thick, wall.thickness_ft)
            structural = merge_structural(structural, wall.structural)
        out.append(CollapsedWall(start, end, structural, thick, assumed))
    return out


def snap_t_junctions(walls: list[CollapsedWall], dist: float = 0.32) -> list[CollapsedWall]:
    """Snap endpoints onto crossing (not parallel) walls so T-junctions share vertices."""
    if not walls:
        return []
    prepared = []
    for wall in walls:
        direction = _direction(wall.start, wall.end)
        if direction:
            prepared.append((wall, direction))
    def snap_pt(p, self_u):
        best = None
        for wall, (ux, uy, length) in prepared:
            if abs(abs(self_u[0] * ux + self_u[1] * uy) - 1.0) <= 0.2:
                continue
            t = _project(wall.start, ux, uy, p)
            if t < -0.05 or t > length + 0.05:
                continue
            q = _point(wall.start, ux, uy, max(0.0, min(length, t)))
            offset = math.hypot(p[0] - q[0], p[1] - q[1])
            if 1e-6 < offset <= dist and (best is None or offset < best[0]):
                best = (offset, q)
        return snap_point(best[1]) if best else snap_point(p)
    out = []
    for wall, (ux, uy, _) in prepared:
        start, end = snap_pt(wall.start, (ux, uy)), snap_pt(wall.end, (ux, uy))
        if segment_length(start, end) < VERTEX_SNAP_FT:
            continue
        out.append(CollapsedWall(start, end, wall.structural, wall.thickness_ft, wall.assumed))
    return out


def weld_endpoints(walls: list[CollapsedWall], weld: float = VERTEX_WELD_FT) -> list[CollapsedWall]:
    """Reuse nearby endpoints so nearly coincident corners share a vertex."""
    if not walls:
        return []
    points = sorted({snap_point(p) for w in walls for p in (w.start, w.end)})
    clusters: list[tuple[float, float]] = []
    remap: dict[tuple[float, float], tuple[float, float]] = {}
    for point in points:
        hit = None
        for representative in clusters:
            if math.hypot(point[0] - representative[0], point[1] - representative[1]) <= weld:
                hit = representative
                break
        if hit is None:
            clusters.append(point)
            remap[point] = point
        else:
            remap[point] = hit
    out = []
    for wall in walls:
        start, end = remap[snap_point(wall.start)], remap[snap_point(wall.end)]
        if segment_length(start, end) < VERTEX_SNAP_FT:
            continue
        out.append(CollapsedWall(start, end, wall.structural, wall.thickness_ft, wall.assumed))
    return out


def collapse_wall_segments(segments) -> list[CollapsedWall]:
    filtered = filter_short_segments(segments)
    merged = merge_collinear(filtered)
    paired = pair_parallel_faces(merged)
    return weld_endpoints(snap_t_junctions(merge_collapsed_walls(paired)))


def collapse_sheet_walls(walls, scale: float, sheet_id: str):
    """Collapse sheet-space Wall objects (points) using a known pts-per-foot scale."""
    from plancheck.core.schemas import Wall

    if not walls or not scale:
        return walls
    segments = []
    for wall in walls:
        structural = "loadbearing" if wall.cls == "loadbearing" else "nonstructural" if wall.cls == "interior" else "unknown"
        segments.append(((wall.a[0] / scale, wall.a[1] / scale), (wall.b[0] / scale, wall.b[1] / scale), structural))
    collapsed = collapse_wall_segments(segments)
    layer = walls[0].layer if walls else "WALL"
    out = []
    for i, wall in enumerate(collapsed):
        cls = "loadbearing" if wall.structural == "loadbearing" else "interior" if wall.structural == "nonstructural" else "unknown"
        length = segment_length(wall.start, wall.end)
        out.append(
            Wall(
                id=f"{sheet_id}-cw{i}",
                a=[wall.start[0] * scale, wall.start[1] * scale],
                b=[wall.end[0] * scale, wall.end[1] * scale],
                cls=cls,
                layer=layer,
                thickness_pt=None if wall.assumed else wall.thickness_ft * scale,
                len_ft=length,
            )
        )
    return out
