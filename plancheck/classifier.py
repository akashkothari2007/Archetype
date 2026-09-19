"""Sheet classification.

Reads every page's title block, assigns a role, and states a reason for every
page it excludes. Nothing here guesses: a page with no readable title block is
reported as unknown rather than assumed.
"""

from __future__ import annotations

import collections
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf

from plancheck import layers as layer_map
from plancheck import pdfio, titleblock

#: Roles whose sheets are worth extracting geometry from.
USABLE_ROLES = frozenset({"unit_plan", "enlarged_plan", "floor_plan", "schedule"})

#: Scale boundary between a whole-floor plan and an enlarged one.
ENLARGED_MIN_PTS_PER_FT = 13.0

#: A sheet claiming to be a plan should have at least this many wall paths.
PLAN_MIN_WALL_PATHS = 100

#: Keyword -> role, for sheets that are not plans or schedules.
KEYWORD_ROLES: dict[str, str] = {
    "EDGE OF SLAB": "slab_edge",
    "ELEVATION": "elevation",
    "SECTION": "section",
    "DETAIL": "detail",
    "ROOF": "roof",
    "SITE": "site",
}

REASONS: dict[str, str] = {
    "unit_plan": "Unit plans, highest precision geometry in the set.",
    "enlarged_plan": "Enlarged plan, heavily dimensioned. Accurate geometry.",
    "floor_plan": "Whole floor at small scale. Room inventory and repeat counts.",
    "schedule": "Tabular sheet. Validates room names and carries door widths.",
    "slab_edge": "Structural slab outline. Looks like a plan but contains no rooms.",
    "elevation": "Exterior elevation. No plan geometry.",
    "section": "Vertical cut. Heights are not tied to a locatable room.",
    "detail": "Construction detail. No room data.",
    "roof": "Roof plan. No rooms.",
    "site": "Site plan. Property lines and grading, nothing interior.",
    "unknown": "Title block did not parse, so the sheet role is undetermined.",
}


@dataclass
class SheetRow:
    source: str
    page: int
    sheet_no: str | None
    title: str | None
    role: str
    scale: str | None
    scale_pts_per_ft: float | None
    use: bool
    reason: str
    path_count: int
    word_count: int
    layer_count: int
    wall_paths: int
    review: bool = False
    review_reason: str | None = None


@dataclass
class DocumentInfo:
    path: str
    filename: str
    page_count: int
    page_width: float
    page_height: float
    rotation: int
    text_extracts: bool
    has_ocgs: bool
    ocg_count: int
    layer_count: int
    sheets: list[SheetRow] = field(default_factory=list)


def assign_role(tb: titleblock.TitleBlock) -> str:
    """Role from the title block alone. Geometry is only a sanity check later."""
    keyword = tb.title_keyword()
    sheet_no = tb.sheet_no or ""

    if keyword == "EDGE OF SLAB":
        return "slab_edge"
    if sheet_no.startswith("A.8") or keyword == "UNIT PLAN":
        return "unit_plan"
    if keyword == "FLOOR PLAN":
        if tb.scale_pts_per_ft is None:
            return "floor_plan"
        return "enlarged_plan" if tb.scale_pts_per_ft >= ENLARGED_MIN_PTS_PER_FT else "floor_plan"
    if keyword == "SCHEDULE":
        return "schedule"
    if keyword in KEYWORD_ROLES:
        return KEYWORD_ROLES[keyword]
    return "unknown"


def classify_page(doc: pymupdf.Document, page_index: int, source: Path) -> SheetRow:
    page = doc[page_index]
    words = pdfio.pymupdf_words_display(page)
    tb = titleblock.read(words, page.rect.width, page.get_text())

    drawings = page.get_drawings()
    counts = collections.Counter(layer_map.normalise(p.get("layer")) for p in drawings)
    wall_paths = sum(n for name, n in counts.items() if name in layer_map.WALL_LAYERS)

    role = assign_role(tb)
    use = role in USABLE_ROLES
    if role == "unknown" and tb.title:
        reason = f"Sheet title {tb.title!r} matches no known drawing keyword."
    else:
        reason = REASONS.get(role, REASONS["unknown"])

    row = SheetRow(
        source=source.name,
        page=page_index + 1,
        sheet_no=tb.sheet_no,
        title=tb.title,
        role=role,
        scale=tb.scale_text,
        scale_pts_per_ft=tb.scale_pts_per_ft,
        use=use,
        reason=reason,
        path_count=len(drawings),
        word_count=len(words),
        layer_count=len(counts),
        wall_paths=wall_paths,
    )
    _flag_for_review(row)
    return row


def _flag_for_review(row: SheetRow) -> None:
    """Cross-check the declared role against what is actually drawn.

    A plan sheet is mostly walls. A non-plan sheet with thousands of wall paths
    means the title block was misread. Either way the row is flagged rather
    than silently corrected, because the fix depends on which one is wrong.
    """
    is_plan = row.role in {"unit_plan", "enlarged_plan", "floor_plan"}
    if is_plan and row.wall_paths < PLAN_MIN_WALL_PATHS:
        row.review = True
        row.review_reason = (
            f"Classified {row.role} but only {row.wall_paths} wall-layer paths "
            f"(expected at least {PLAN_MIN_WALL_PATHS})."
        )
    elif not is_plan and row.wall_paths >= PLAN_MIN_WALL_PATHS:
        row.review = True
        row.review_reason = (
            f"Classified {row.role} but carries {row.wall_paths} wall-layer paths, "
            "which looks like a plan."
        )
    elif is_plan and row.scale_pts_per_ft is None:
        row.review = True
        row.review_reason = "Plan sheet with no readable scale in the title block."


def classify_document(src: Path) -> DocumentInfo:
    with pymupdf.open(src) as doc:
        first = doc[0]
        ocgs = doc.get_ocgs()
        rows = [classify_page(doc, index, src) for index in range(doc.page_count)]

        all_layers = {layer_map.normalise(v.get("name")) for v in ocgs.values()}

        return DocumentInfo(
            path=str(src),
            filename=src.name,
            page_count=doc.page_count,
            page_width=round(first.rect.width, 2),
            page_height=round(first.rect.height, 2),
            rotation=first.rotation,
            text_extracts=len(first.get_text("words")) > 0,
            has_ocgs=bool(ocgs),
            ocg_count=len(ocgs),
            layer_count=len(all_layers),
            sheets=rows,
        )


def to_dict(info: DocumentInfo) -> dict:
    return asdict(info)
