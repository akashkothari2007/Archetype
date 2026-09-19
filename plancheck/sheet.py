"""Sheet extraction — one drawing page into a structured layer model.

Reads what each path *is* from its CAD layer rather than inferring it from
geometry. Paths on unmapped layers are counted and reported, never silently
dropped; paths on excluded layers (hatching, furniture) are counted and then
discarded so the output stays small and legible.

Produces no rooms, no compliance, no heights. Wall thickness and height are
left null because a 2D plan does not contain them.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from plancheck import geometry as geo
from plancheck import layers as layer_map
from plancheck import pdfio, titleblock
from plancheck.classifier import assign_role
from plancheck.scale import parse_dimension

SCHEMA_VERSION = "0.1.0"

#: A grid line spans the building; anything shorter is a tick or a bubble.
GRID_MIN_LENGTH_PT = 72.0

#: Grid lines are dashed. Segments this far apart still belong to one line.
GRID_DASH_GAP_PT = 24.0

#: Grid bubble labels: a column number or a row letter, nothing else.
GRID_LABEL_RE = re.compile(r"^([1-9][0-9]?[a-z]?|[A-Z])$")

#: How far from a grid line end a bubble label may sit.
GRID_LABEL_RADIUS_PT = 36.0

#: Glyph strokes closer than this belong to the same line of tag text.
TAG_GLYPH_PAD_PT = 2.0

#: Size envelope for one line of room-tag text, used to reject stray marks.
TAG_MIN_HEIGHT_PT = 3.0
TAG_MAX_HEIGHT_PT = 24.0
TAG_MIN_WIDTH_PT = 6.0

#: Room tag words are merged when stacked this closely.
TAG_X_TOLERANCE_PT = 12.0
TAG_Y_GAP_PT = 18.0

#: Words on one baseline are joined when the horizontal gap is under this.
TAG_INLINE_GAP_PT = 14.0

#: A metric bracket pairs with the imperial token directly above it.
DIM_PAIR_Y_PT = 22.0
DIM_PAIR_X_PT = 26.0

#: Cell size for the spatial index used to test words against tag boxes.
INDEX_CELL_PT = 64.0


@dataclass
class SheetExtract:
    payload: dict

    @property
    def sheet_id(self) -> str:
        return self.payload["sheet"]["sheet_no"] or f"page_{self.payload['source']['page']}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def extract_sheet(
    src: Path,
    page_number: int,
    render_dir: Path | None = None,
    dpi: int = 150,
) -> SheetExtract:
    """Extract one page (1-indexed) into the sheet model."""
    with pymupdf.open(src) as doc:
        if not 1 <= page_number <= doc.page_count:
            raise ValueError(
                f"{src.name} has {doc.page_count} pages; asked for page {page_number}."
            )
        page = doc[page_number - 1]
        tf = geo.PageTransform.for_page(page)

        tb = titleblock.read(pdfio.pymupdf_words_display(page), page.rect.width, page.get_text())
        buckets, unmapped, excluded, layer_detail = _bucket_paths(page, tf)

    # pdfplumber needs a single-page file; the full set gets it OOM-killed.
    with pdfio.split_page(src, page_number) as page_pdf:
        words = pdfio.plumber_words(page_pdf, tf)

    walls = _walls(buckets["wall"])
    grid = _grid(buckets["grid"], words)
    room_tags = _room_tags(buckets["room_tag"], words)
    dimensions = _dimensions(words)

    render = None
    if render_dir is not None:
        sheet_id = tb.sheet_no or f"page_{page_number}"
        png = pdfio.render_png(src, page_number, render_dir / f"{sheet_id}.png", dpi=dpi)
        render = {
            "png": str(png),
            "dpi": dpi,
            "width_px": round(tf.width * dpi / 72),
            "height_px": round(tf.height * dpi / 72),
        }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {"pdf": src.name, "path": str(src), "page": page_number},
        "sheet": {
            "sheet_no": tb.sheet_no,
            "title": tb.title,
            "role": assign_role(tb),
            "scale": tb.scale_text,
            "scale_pts_per_ft": tb.scale_pts_per_ft,
            "project_no": tb.project_no,
        },
        "page": {
            "width": round(tf.width, 2),
            "height": round(tf.height, 2),
            "units": "pt",
            "origin": "bottom-left",
            "y_axis": "up",
        },
        # Wall height and thickness are absent by design: a 2D plan carries no
        # elevation data and these sheets do not annotate wall assemblies.
        "assumptions": {"wall_height_ft": None, "wall_thickness_ft": None},
        "render": render,
        "layers": layer_detail,
        "unmapped": dict(sorted(unmapped.items(), key=lambda kv: -kv[1])),
        "excluded": excluded,
        "walls": walls,
        "doors": _openings(buckets["door"], "door"),
        "windows": _openings(buckets["window"], "window"),
        "fixtures": _fixtures(buckets["fixture"]),
        "columns": _simple(buckets["column"], "col"),
        "stairs": _simple(buckets["stair"], "stair"),
        "elevators": _simple(buckets["elevator"], "elev"),
        "shafts": _simple(buckets["shaft"], "shaft"),
        "clear_spaces": _simple(buckets["clear_space"], "clr"),
        "grid": grid,
        "room_tags": room_tags,
        "dimensions": dimensions,
    }
    payload["counts"] = {
        "walls": len(walls),
        "doors": len(payload["doors"]),
        "windows": len(payload["windows"]),
        "fixtures": len(payload["fixtures"]),
        "columns": len(payload["columns"]),
        "stairs": len(payload["stairs"]),
        "elevators": len(payload["elevators"]),
        "shafts": len(payload["shafts"]),
        "clear_spaces": len(payload["clear_spaces"]),
        "grid_lines": len(grid["lines"]),
        "grid_labels": len(grid["labels"]),
        "room_tags": len(room_tags),
        "dimensions": len(dimensions),
        "words": len(words),
        "unmapped_layers": len(unmapped),
    }
    return SheetExtract(payload)


# ---------------------------------------------------------------------------
# Layer bucketing
# ---------------------------------------------------------------------------


def _bucket_paths(
    page: pymupdf.Page, tf: geo.PageTransform
) -> tuple[dict[str, list[dict]], collections.Counter, dict, dict]:
    """Sort every path on the page into its semantic bucket."""
    buckets: dict[str, list[dict]] = {name: [] for name in layer_map.GEOMETRY_BUCKETS}
    unmapped: collections.Counter = collections.Counter()
    excluded: collections.Counter = collections.Counter()
    per_layer: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    for path in page.get_drawings():
        layer = layer_map.normalise(path.get("layer"))
        bucket = layer_map.bucket_for(path.get("layer"))

        if bucket is None:
            unmapped[layer] += 1
            continue

        per_layer[bucket][layer] += 1

        if layer_map.is_excluded(bucket):
            excluded[bucket] += 1
            continue

        items = path.get("items", [])
        record = {"layer": layer, "items": items, "bbox": tf.bbox(path["rect"])}
        # Only walls and grid lines are consumed as segments; flattening the
        # rest would be thousands of paths of wasted work per sheet.
        if bucket in ("wall", "grid"):
            record["segments"] = geo.path_segments(items, tf)
        buckets[bucket].append(record)

    layer_detail = {
        bucket: {
            "paths": sum(counts.values()),
            "layers": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        }
        for bucket, counts in sorted(per_layer.items())
    }
    return buckets, unmapped, dict(excluded), layer_detail


# ---------------------------------------------------------------------------
# Walls
# ---------------------------------------------------------------------------


def _walls(paths: list[dict]) -> list[dict]:
    """Flatten wall paths to cleaned segments, grouped by construction class.

    Merging is done per class so a loadbearing run is never welded onto an
    interior partition that happens to be collinear with it.
    """
    by_class: dict[tuple[str, str], list[tuple[geo.Point, geo.Point]]] = collections.defaultdict(
        list
    )
    for path in paths:
        key = (layer_map.wall_class_for(path["layer"]), path["layer"])
        by_class[key].extend(path["segments"])

    out: list[dict] = []
    for (cls, layer), segments in sorted(by_class.items()):
        for (x1, y1), (x2, y2) in geo.clean_segments(segments):
            out.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "cls": cls, "layer": layer})
    return out


# ---------------------------------------------------------------------------
# Openings, fixtures, simple bboxes
# ---------------------------------------------------------------------------


def _openings(paths: list[dict], prefix: str) -> list[dict]:
    """One record per path group, with the swing arc flag for doors."""
    out: list[dict] = []
    for index, path in enumerate(paths):
        bbox = path["bbox"]
        out.append(
            {
                "id": f"{prefix}-{index:04d}",
                "bbox": bbox,
                "centre": list(geo.centre_of(bbox)),
                "swing": geo.has_curve(path["items"]),
                "layer": path["layer"],
            }
        )
    return out


def _fixtures(paths: list[dict]) -> list[dict]:
    out: list[dict] = []
    for index, path in enumerate(paths):
        bbox = path["bbox"]
        out.append(
            {
                "id": f"fix-{index:04d}",
                "bbox": bbox,
                "centre": list(geo.centre_of(bbox)),
                # Fixture type is not derivable from the layer name alone and
                # is not guessed here.
                "kind": "unknown",
                "layer": path["layer"],
            }
        )
    return out


def _simple(paths: list[dict], prefix: str) -> list[dict]:
    return [
        {
            "id": f"{prefix}-{index:04d}",
            "bbox": path["bbox"],
            "centre": list(geo.centre_of(path["bbox"])),
            "layer": path["layer"],
        }
        for index, path in enumerate(paths)
    ]


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------


def _grid(paths: list[dict], words: list[dict]) -> dict:
    """Long axis-aligned grid lines, plus their bubble labels.

    Grid lines are drawn dashed. On the typical floor plan the longest single
    path segment is about 20pt, so nothing survives a per-path length filter.
    Segments are therefore pooled across the whole layer and merged with a gap
    wide enough to bridge the dashes before the length filter is applied.
    """
    pooled: list[tuple[geo.Point, geo.Point]] = []
    for path in paths:
        pooled.extend(path["segments"])

    lines: list[dict] = []
    for seg in geo.clean_segments(pooled, min_length=1.0, gap=GRID_DASH_GAP_PT):
        if not geo.is_axis_aligned(seg) or geo.length(seg) < GRID_MIN_LENGTH_PT:
            continue
        (x1, y1), (x2, y2) = seg
        lines.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "axis": "v" if x1 == x2 else "h"})

    endpoints = [(line["x1"], line["y1"]) for line in lines]
    endpoints += [(line["x2"], line["y2"]) for line in lines]

    labels: list[dict] = []
    for word in words:
        if not GRID_LABEL_RE.match(word["text"]):
            continue
        cx, cy = pdfio.word_centre(word)
        near = any(
            abs(cx - ex) <= GRID_LABEL_RADIUS_PT and abs(cy - ey) <= GRID_LABEL_RADIUS_PT
            for ex, ey in endpoints
        )
        if near:
            labels.append({"text": word["text"], "x": cx, "y": cy})

    return {"lines": lines, "labels": labels}


# ---------------------------------------------------------------------------
# Room tags
# ---------------------------------------------------------------------------


def _room_tags(paths: list[dict], words: list[dict]) -> list[dict]:
    """Room tags, located from the ANNO-ROOM TAG layer.

    Two cases occur in the same document and both are handled:

    1. The layer carries real text. Words inside a tag box are merged into one
       label — horizontally adjacent words on a baseline first ("STUDIO" beside
       "KING"), then vertically stacked lines ("STUDIO" above "KING").

    2. The layer carries the text as vector outlines, one path per glyph
       stroke. This is what the reference floor plans do: page 30 has 1256 tag
       paths with a median bbox of 1.4 x 1.7pt and no words anywhere near them.
       The string is then genuinely unrecoverable without OCR, which is out of
       scope. The tag's *position* is still recovered by clustering the glyph
       strokes, and the record is emitted with `label: null` and
       `text_outlined: true` rather than being dropped or guessed at.
    """
    if not paths:
        return []

    boxes = [p["bbox"] for p in paths]
    index = _SpatialIndex(boxes)
    inside = [w for w in words if index.contains(pdfio.word_centre(w))]

    tags: list[dict] = []

    if inside:
        for cluster in _stack_lines(_group_baselines(inside)):
            texts = [line["text"] for line in cluster]
            bbox = geo.union_bbox([line["bbox"] for line in cluster])
            tags.append(_tag_record(len(tags), bbox, texts, outlined=False))
        return tags

    # Outlined text: rebuild each label's footprint from its glyph strokes.
    glyph_runs = geo.cluster_boxes(boxes, pad=TAG_GLYPH_PAD_PT)
    lines = [{"text": "", "bbox": box} for box in glyph_runs if _tag_sized(box)]
    for cluster in _stack_lines(lines):
        bbox = geo.union_bbox([line["bbox"] for line in cluster])
        tags.append(_tag_record(len(tags), bbox, [], outlined=True))
    return tags


def _tag_sized(box: list[float]) -> bool:
    """Reject strokes too small or too large to be a line of tag text."""
    width = box[2] - box[0]
    height = box[3] - box[1]
    return TAG_MIN_HEIGHT_PT <= height <= TAG_MAX_HEIGHT_PT and width >= TAG_MIN_WIDTH_PT


def _tag_record(index: int, bbox: list[float], texts: list[str], outlined: bool) -> dict:
    centre = geo.centre_of(bbox)
    return {
        "id": f"tag-{index:04d}",
        "label": " ".join(texts) if texts else None,
        "lines": texts,
        "text_outlined": outlined,
        "bbox": bbox,
        "x": centre[0],
        "y": centre[1],
    }


def _group_baselines(words: list[dict]) -> list[dict]:
    """Join words that share a baseline and sit close horizontally."""
    ordered = sorted(words, key=lambda w: (-round(w["y1"], 1), w["x0"]))
    lines: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        if not current:
            return
        bbox = geo.union_bbox([[w["x0"], w["y0"], w["x1"], w["y1"]] for w in current])
        lines.append({"text": " ".join(w["text"] for w in current), "bbox": bbox})

    for word in ordered:
        if current:
            last = current[-1]
            same_line = abs(last["y1"] - word["y1"]) <= 2.0
            close = word["x0"] - last["x1"] <= TAG_INLINE_GAP_PT
            if not (same_line and close):
                flush()
                current = []
        current.append(word)
    flush()
    return lines


def _stack_lines(lines: list[dict]) -> list[list[dict]]:
    """Merge vertically stacked lines whose x-centres nearly agree."""
    remaining = sorted(lines, key=lambda line: -line["bbox"][3])
    clusters: list[list[dict]] = []

    for line in remaining:
        cx = (line["bbox"][0] + line["bbox"][2]) / 2
        top = line["bbox"][3]
        placed = False
        for cluster in clusters:
            last = cluster[-1]
            last_cx = (last["bbox"][0] + last["bbox"][2]) / 2
            gap = last["bbox"][1] - top
            if abs(last_cx - cx) <= TAG_X_TOLERANCE_PT and 0 <= gap <= TAG_Y_GAP_PT:
                cluster.append(line)
                placed = True
                break
        if not placed:
            clusters.append([line])
    return clusters


class _SpatialIndex:
    """Coarse grid index, so testing words against thousands of boxes is cheap."""

    def __init__(self, boxes: list[list[float]]) -> None:
        self.boxes = boxes
        self.cells: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
        for i, box in enumerate(boxes):
            for cx in range(int(box[0] // INDEX_CELL_PT), int(box[2] // INDEX_CELL_PT) + 1):
                for cy in range(int(box[1] // INDEX_CELL_PT), int(box[3] // INDEX_CELL_PT) + 1):
                    self.cells[(cx, cy)].append(i)

    def contains(self, point: geo.Point) -> bool:
        key = (int(point[0] // INDEX_CELL_PT), int(point[1] // INDEX_CELL_PT))
        return any(geo.point_in_bbox(point, self.boxes[i]) for i in self.cells.get(key, ()))


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


def _dimensions(words: list[dict]) -> list[dict]:
    """Pair each metric bracket with the imperial token drawn above it.

    On these sheets the two halves of a dimension are separate text runs
    stacked vertically, so they are recombined here. The bracket supplies the
    value; the imperial token is kept only as the human-readable original.
    """
    brackets = [w for w in words if "[" in w["text"] and "m]" in w["text"]]
    imperials = [w for w in words if "'" in w["text"] and "-" in w["text"]]
    used: set[int] = set()

    out: list[dict] = []
    for word in brackets:
        cx, cy = pdfio.word_centre(word)
        partner_index = _nearest_above(word, imperials, used)
        text = word["text"]
        if partner_index is not None:
            used.add(partner_index)
            text = f"{imperials[partner_index]['text']} {word['text']}"

        parsed = parse_dimension(text)
        if parsed is None:
            continue
        metres, source = parsed
        out.append({"text": text, "metres": metres, "source": source, "x": cx, "y": cy})

    # Imperial tokens with no bracket of their own still carry a value, but a
    # less trustworthy one. They are kept and labelled, not dropped.
    for i, word in enumerate(imperials):
        if i in used:
            continue
        parsed = parse_dimension(word["text"])
        if parsed is None:
            continue
        metres, source = parsed
        cx, cy = pdfio.word_centre(word)
        out.append({"text": word["text"], "metres": metres, "source": source, "x": cx, "y": cy})

    out.sort(key=lambda d: (-d["y"], d["x"]))
    return out


def _nearest_above(bracket: dict, imperials: list[dict], used: set[int]) -> int | None:
    """Index of the imperial token sitting directly above `bracket`."""
    bx, by = pdfio.word_centre(bracket)
    best: tuple[float, int] | None = None
    for i, word in enumerate(imperials):
        if i in used:
            continue
        wx, wy = pdfio.word_centre(word)
        dy = wy - by
        if not (0 < dy <= DIM_PAIR_Y_PT) or abs(wx - bx) > DIM_PAIR_X_PT:
            continue
        score = dy + abs(wx - bx)
        if best is None or score < best[0]:
            best = (score, i)
    return best[1] if best else None
