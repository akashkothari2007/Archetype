"""Coordinate transform and segment geometry.

THE Y FLIP HAPPENS EXACTLY ONCE, HERE, AT THE READ BOUNDARY.
PyMuPDF is y-down from the top-left. Our output is y-up from the bottom-left.
Never flip again downstream.

Rotation matters and is easy to miss. The reference sheets carry /Rotate 270,
which means:

    page.rect      = 2384 x 1684   (what a viewer displays)
    page.mediabox  = 1684 x 2384   (what get_drawings() actually returns)

So raw PyMuPDF coordinates must be pushed through `page.rotation_matrix`
BEFORE the flip, or the result lands outside the page — a raw y of 2162 would
become 1684 - 2162 = -478. pdfplumber already reports display-space
coordinates, so it only needs the flip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pymupdf

#: Segments shorter than this are drafting noise, not geometry.
MIN_SEGMENT_PT = 2.0

#: A segment within this of axis-aligned is snapped to the axis.
AXIS_SNAP_PT = 0.6

#: Endpoints closer than this are treated as the same point when merging.
JOIN_TOLERANCE_PT = 0.35

#: Collinear pieces whose offsets agree this closely belong to the same line.
#: Must stay well below a wall's thickness so opposite faces never collapse.
OFFSET_GROUP_PT = 0.3

Point = tuple[float, float]


@dataclass(frozen=True)
class PageTransform:
    """Maps raw PyMuPDF coordinates into the output space (y-up, bottom-left)."""

    matrix: pymupdf.Matrix
    height: float
    width: float

    @classmethod
    def for_page(cls, page: pymupdf.Page) -> PageTransform:
        return cls(
            matrix=page.rotation_matrix,
            height=page.rect.height,
            width=page.rect.width,
        )

    def point(self, p: Any) -> Point:
        """Raw PyMuPDF point -> output point."""
        q = pymupdf.Point(p) * self.matrix
        return (round(q.x, 3), round(self.height - q.y, 3))

    def bbox(self, rect: Any) -> list[float]:
        """Raw PyMuPDF rect -> [min_x, min_y, max_x, max_y] in output space."""
        r = pymupdf.Rect(rect) * self.matrix
        return [
            round(min(r.x0, r.x1), 3),
            round(self.height - max(r.y0, r.y1), 3),
            round(max(r.x0, r.x1), 3),
            round(self.height - min(r.y0, r.y1), 3),
        ]

    def flip_top(self, top: float) -> float:
        """pdfplumber `top` (already display space) -> output y."""
        return round(self.height - top, 3)


# ---------------------------------------------------------------------------
# Path flattening
# ---------------------------------------------------------------------------


def path_segments(items: list[Any], tf: PageTransform) -> list[tuple[Point, Point]]:
    """Flatten one PyMuPDF path's items into straight segments.

    Curves are reduced to their chord. We are recovering wall centrelines and
    outlines, not reproducing the drawing, so a Bezier's control points add
    nothing a downstream consumer would use.
    """
    out: list[tuple[Point, Point]] = []
    for item in items:
        op = item[0]
        if op == "l":
            out.append((tf.point(item[1]), tf.point(item[2])))
        elif op == "c":
            out.append((tf.point(item[1]), tf.point(item[4])))
        elif op == "re":
            x0, y0, x1, y1 = tf.bbox(item[1])
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            out.extend((corners[i], corners[(i + 1) % 4]) for i in range(4))
        elif op == "qu":
            quad = item[1]
            pts = [tf.point(p) for p in (quad.ul, quad.ur, quad.lr, quad.ll)]
            out.extend((pts[i], pts[(i + 1) % 4]) for i in range(4))
    return out


def has_curve(items: list[Any]) -> bool:
    return any(item[0] == "c" for item in items)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def snap_to_axis(seg: tuple[Point, Point], tolerance: float = AXIS_SNAP_PT) -> tuple[Point, Point]:
    """Square up a nearly-axis-aligned segment.

    CAD output is nominally orthogonal but arrives with sub-point drift. Left
    alone, that drift stops collinear runs from merging.
    """
    (x1, y1), (x2, y2) = seg
    if abs(y2 - y1) <= tolerance and abs(x2 - x1) > tolerance:
        y = round((y1 + y2) / 2, 3)
        return ((x1, y), (x2, y))
    if abs(x2 - x1) <= tolerance and abs(y2 - y1) > tolerance:
        x = round((x1 + x2) / 2, 3)
        return ((x, y1), (x, y2))
    return seg


def length(seg: tuple[Point, Point]) -> float:
    (x1, y1), (x2, y2) = seg
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def is_axis_aligned(seg: tuple[Point, Point]) -> bool:
    (x1, y1), (x2, y2) = seg
    return x1 == x2 or y1 == y2


def merge_collinear(
    segments: list[tuple[Point, Point]], gap: float = JOIN_TOLERANCE_PT
) -> list[tuple[Point, Point]]:
    """Merge axis-aligned segments that lie on the same line and nearly touch.

    A wall arrives as dozens of short collinear pieces because CAD breaks it at
    every intersection. Merging is an interval union per (orientation, offset)
    group. Diagonal segments are passed through untouched — merging those
    reliably needs an angular tolerance that risks welding real corners shut.

    `gap` is how far apart two pieces may be and still join. The default only
    closes rounding drift. A dashed line needs a gap wider than its dashes.
    """
    horizontal: list[tuple[float, list[float]]] = []
    vertical: list[tuple[float, list[float]]] = []
    passthrough: list[tuple[Point, Point]] = []

    for seg in segments:
        (x1, y1), (x2, y2) = seg
        if y1 == y2 and x1 != x2:
            horizontal.append((y1, sorted((x1, x2))))
        elif x1 == x2 and y1 != y2:
            vertical.append((x1, sorted((y1, y2))))
        else:
            passthrough.append(seg)

    merged: list[tuple[Point, Point]] = []
    for y, spans in _by_offset(horizontal):
        for lo, hi in _union(spans, gap):
            merged.append(((lo, y), (hi, y)))
    for x, spans in _by_offset(vertical):
        for lo, hi in _union(spans, gap):
            merged.append(((x, lo), (x, hi)))

    return merged + passthrough


def _by_offset(
    entries: list[tuple[float, list[float]]], tolerance: float = OFFSET_GROUP_PT
) -> list[tuple[float, list[list[float]]]]:
    """Group segments whose perpendicular offsets agree to within `tolerance`.

    Snapping squares a segment up against its own endpoints, so two pieces of
    one wall can still land a few hundredths apart. Grouping on the exact value
    would leave them unmerged, so nearby offsets are clustered and represented
    by their mean. The tolerance stays well under a wall's thickness, so the
    two faces of a wall are never collapsed into one line.
    """
    if not entries:
        return []

    entries.sort(key=lambda item: item[0])
    groups: list[tuple[float, list[list[float]]]] = []
    offsets: list[float] = [entries[0][0]]
    spans: list[list[float]] = [entries[0][1]]

    def flush() -> None:
        groups.append((round(sum(offsets) / len(offsets), 3), spans.copy()))

    for offset, span in entries[1:]:
        if offset - offsets[-1] <= tolerance:
            offsets.append(offset)
            spans.append(span)
        else:
            flush()
            offsets = [offset]
            spans = [span]
    flush()
    return groups


def _union(spans: list[list[float]], gap: float = JOIN_TOLERANCE_PT) -> list[tuple[float, float]]:
    """Union of 1-D intervals, joining any that touch within `gap`."""
    spans.sort()
    out: list[tuple[float, float]] = []
    lo, hi = spans[0]
    for start, end in spans[1:]:
        if start <= hi + gap:
            hi = max(hi, end)
        else:
            out.append((round(lo, 3), round(hi, 3)))
            lo, hi = start, end
    out.append((round(lo, 3), round(hi, 3)))
    return out


def clean_segments(
    segments: list[tuple[Point, Point]],
    min_length: float = MIN_SEGMENT_PT,
    gap: float = JOIN_TOLERANCE_PT,
) -> list[tuple[Point, Point]]:
    """Snap to axis, drop noise, merge collinear runs. Order matters."""
    snapped = [snap_to_axis(s) for s in segments]
    kept = [s for s in snapped if length(s) >= min_length]
    if not kept:
        return []
    return merge_collinear(kept, gap=gap)


def cluster_boxes(boxes: list[list[float]], pad: float) -> list[list[float]]:
    """Group boxes that overlap once grown by `pad`, returning each union.

    Used to reassemble text that was converted to vector outlines: one glyph
    stroke per path, dozens of paths per label. Connected components are found
    through a coarse spatial hash so this stays linear on sheets carrying
    thousands of tag paths.
    """
    if not boxes:
        return []

    cell = max(pad * 4, 8.0)
    grid: dict[tuple[int, int], list[int]] = {}
    for i, box in enumerate(boxes):
        for cx in range(int((box[0] - pad) // cell), int((box[2] + pad) // cell) + 1):
            for cy in range(int((box[1] - pad) // cell), int((box[3] + pad) // cell) + 1):
                grid.setdefault((cx, cy), []).append(i)

    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for members in grid.values():
        for idx, i in enumerate(members):
            for j in members[idx + 1 :]:
                if _overlaps(boxes[i], boxes[j], pad):
                    union(i, j)

    groups: dict[int, list[list[float]]] = {}
    for i, box in enumerate(boxes):
        groups.setdefault(find(i), []).append(box)
    return [union_bbox(group) for group in groups.values()]


def _overlaps(a: list[float], b: list[float], pad: float) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def bbox_of_points(points: list[Point]) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def centre_of(bbox: list[float]) -> Point:
    return (round((bbox[0] + bbox[2]) / 2, 3), round((bbox[1] + bbox[3]) / 2, 3))


def point_in_bbox(p: Point, bbox: list[float], pad: float = 0.0) -> bool:
    return bbox[0] - pad <= p[0] <= bbox[2] + pad and bbox[1] - pad <= p[1] <= bbox[3] + pad


def union_bbox(boxes: list[list[float]]) -> list[float]:
    return [
        round(min(b[0] for b in boxes), 3),
        round(min(b[1] for b in boxes), 3),
        round(max(b[2] for b in boxes), 3),
        round(max(b[3] for b in boxes), 3),
    ]
