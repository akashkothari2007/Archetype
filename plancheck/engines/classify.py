"""Classify drawing PDF pages from title-block text.

This is the only real engine in the scaffold: it is pure text parsing.
Text is extracted per page so a 51-page CAD PDF is never loaded as one string.
"""

from __future__ import annotations

import argparse
import collections
import re
from collections.abc import Callable
from pathlib import Path

import pymupdf

from plancheck.core.layers import normalise
from plancheck.core.scale import find_scale
from plancheck.core.schemas import Document, Project, Sheet, SheetStats
from plancheck.engines.base import invoke, load_fixture

# Spec regex, plus a-z so A.501c survives. Applied to title-block text first.
SHEET_NO_RE = re.compile(r"Drawing No:\s*([A-Za-z0-9.\-]+)")
SHEET_NO_SHAPE = re.compile(
    r"^(?:[A-Z]{1,3}\.\d{2,4}[a-z]?|[A-Z]{1,3}\d{2,4}[a-z]?|ASP-\d+)$"
)
SHEET_TITLE_RE = re.compile(
    r"Sheet Title:\s*(.+?)(?:Design By:|Drawn By:|Approved By:|$)",
    re.IGNORECASE | re.DOTALL,
)
LEVEL_RE = re.compile(r"\bLEVEL\s+(\d+)\b", re.IGNORECASE)
LEVEL_RANGE_RE = re.compile(
    r"(\d+)\s*(?:st|nd|rd|th)?\s*(?:to|-|–|&)\s*(\d+)\s*(?:st|nd|rd|th)?",
    re.IGNORECASE,
)
DIM_TOKEN_RE = re.compile(r"""\d+'\-\d+"|\[\d{3,5}\]""")

# Phrase patterns so "PROOF" ≠ "ROOF" and "ON SITE" is weaker than "SITE PLAN".
KEYWORD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EDGE OF SLAB", re.compile(r"EDGE\s+OF\s+SLAB")),
    ("UNIT PLAN", re.compile(r"UNIT\s+PLANS?")),
    ("FLOOR PLAN", re.compile(r"FLOOR\s+PLAN")),
    ("ELEVATION", re.compile(r"ELEVATIONS?\b")),
    ("SECTION", re.compile(r"SECTIONS?\b")),
    ("DETAIL", re.compile(r"DETAILS?\b")),
    ("SCHEDULE", re.compile(r"SCHEDULE\b")),
    ("ROOF", re.compile(r"\bROOF\s+PLAN\b|\bROOF\b")),
    ("SITE", re.compile(r"\bSITE\s+PLAN\b|\bSITE\b")),
)
TITLE_KEYWORDS = tuple(name for name, _ in KEYWORD_PATTERNS)

USABLE_ROLES = frozenset(
    {"unit_plan", "enlarged_plan", "floor_plan", "schedule"}
)
DRAWING_STAT_ROLES = frozenset({"floor_plan", "enlarged_plan", "unit_plan"})
ENLARGED_MIN_PTS_PER_FT = 13.0

KEYWORD_ROLES: dict[str, str] = {
    "ELEVATION": "elevation",
    "SECTION": "section",
    "DETAIL": "detail",
    "ROOF": "roof",
    "SITE": "site",
}

REASONS: dict[str, str] = {
    "unit_plan": "Unit plan; highest-precision geometry in the set.",
    "enlarged_plan": "Enlarged floor plan (scale >= 13 pt/ft); accurate geometry.",
    "floor_plan": "Whole-floor plan at small scale. Room inventory and repeat counts.",
    "schedule": "Tabular sheet. Validates room names and carries door widths.",
    "slab_edge": "Structural slab outline. Looks like a plan but contains no rooms.",
    "elevation": "Exterior elevation. No plan geometry.",
    "section": "Vertical cut. Heights are not tied to a locatable room.",
    "detail": "Construction detail. No room data.",
    "roof": "Roof plan. No rooms.",
    "site": "Site plan. Property lines and grading, nothing interior.",
    "unknown": "Title block did not parse, so the sheet role is undetermined.",
}

DISCIPLINE: dict[str, str] = {
    "A": "architectural",
    "S": "structural",
    "M": "mechanical",
    "E": "electrical",
    "P": "plumbing",
    "C": "civil",
}

ProgressFn = Callable[[float, str], None]


def peek_document(path: Path, doc_id: str, slot: str) -> Document:
    """Cheap per-file metadata for the create-project response. One page only."""
    with pymupdf.open(path) as doc:
        first = doc[0]
        ocgs = doc.get_ocgs() or {}
        words = first.get_text("words") or []
        return Document(
            doc_id=doc_id,
            filename=path.name,
            slot=slot,  # type: ignore[arg-type]
            discipline="unknown",
            pages=doc.page_count,
            page_size_pt=[round(first.rect.width, 2), round(first.rect.height, 2)],
            text_extractable=len(words) > 0,
            layered=bool(ocgs),
            layer_count=len(ocgs),
        )


def display_words(page: pymupdf.Page) -> list[tuple[float, float, float, float, str]]:
    """Word boxes in *display* space (page.rect), after applying page rotation.

    This is not the sheet-space y-up flip — that lives only in core.geometry.flip_y.
    CAD sheets are often stored at /Rotate 270; without this, the title block is
    not where page.rect says it is.
    """
    mat = page.rotation_matrix
    out: list[tuple[float, float, float, float, str]] = []
    for rec in page.get_text("words") or []:
        rect = pymupdf.Rect(rec[:4]) * mat
        out.append((rect.x0, rect.y0, rect.x1, rect.y1, rec[4]))
    return out


def title_block_text(page: pymupdf.Page) -> str:
    """Bottom-right title block, reconstructed in reading order."""
    width, height = page.rect.width, page.rect.height
    words = [
        w
        for w in display_words(page)
        if w[0] > width * 0.70 and w[1] > height * 0.62
    ]
    words.sort(key=lambda w: (round(w[1] / 8.0) * 8.0, w[0]))
    return " ".join(w[4] for w in words)


def looks_like_sheet_no(token: str) -> bool:
    return bool(SHEET_NO_SHAPE.match(token))


def normalise_sheet_no(token: str) -> str:
    """A206a → A.206a. Dotted numbers are left alone."""
    if "." in token or token.startswith("ASP-"):
        return token
    match = re.fullmatch(r"([A-Z]+)(\d{2,4}[a-z]?)", token)
    if match:
        return f"{match.group(1)}.{match.group(2)}"
    return token


def parse_sheet_no(text: str) -> str | None:
    """Spec: Drawing No: … — skip garbage captures like 'S' or 'PRIVACY'."""
    for match in SHEET_NO_RE.finditer(text):
        raw = match.group(1)
        if looks_like_sheet_no(raw):
            return normalise_sheet_no(raw)
    return None


def first_title_keyword(text: str) -> str | None:
    """Earliest keyword in the given text, not list order."""
    upper = text.upper()
    best: tuple[int, str] | None = None
    for name, pattern in KEYWORD_PATTERNS:
        match = pattern.search(upper)
        if match is None:
            continue
        if best is None or match.start() < best[0]:
            best = (match.start(), name)
    return None if best is None else best[1]


def sheet_title_field(title_block: str) -> str | None:
    field = SHEET_TITLE_RE.search(title_block)
    return field.group(1).strip() if field else None


def parse_levels(title: str | None) -> list[str]:
    """Storeys named in a sheet title: GROUND → 1, (2nd to 3rd) → 2, 3."""
    if not title:
        return []
    found: list[str] = []

    def add(level: int) -> None:
        if level >= 1 and str(level) not in found:
            found.append(str(level))

    for start, end in LEVEL_RANGE_RE.findall(title):
        lo, hi = int(start), int(end)
        for level in range(min(lo, hi), max(lo, hi) + 1):
            add(level)
    for match in LEVEL_RE.finditer(title):
        add(int(match.group(1)))
    if not found and re.search(r"\bGROUND\b", title, re.I):
        add(1)
    if not found and re.search(r"\bFIRST\s+FLOOR\b", title, re.I):
        add(1)
    return found


def parse_title(title_block: str, full_text: str) -> str | None:
    """Prefer the Sheet Title: field; otherwise first keyword in TB, then page."""
    field = SHEET_TITLE_RE.search(title_block)
    if field:
        titled = first_title_keyword(field.group(1))
        if titled:
            return titled
    return first_title_keyword(title_block) or first_title_keyword(full_text)


def assign_role(
    sheet_no: str | None,
    title: str | None,
    pts_per_ft: float | None,
) -> str:
    no = sheet_no or ""
    t = title or ""
    if no.startswith("A.8") or "UNIT PLAN" in t:
        return "unit_plan"
    if "FLOOR PLAN" in t:
        if pts_per_ft is not None and pts_per_ft >= ENLARGED_MIN_PTS_PER_FT:
            return "enlarged_plan"
        return "floor_plan"
    if "EDGE OF SLAB" in t:
        return "slab_edge"
    if "SCHEDULE" in t:
        return "schedule"
    for keyword, role in KEYWORD_ROLES.items():
        if keyword in t:
            return role
    return "unknown"


def discipline_of(sheet_no: str | None) -> str:
    if not sheet_no:
        return "unknown"
    return DISCIPLINE.get(sheet_no[0].upper(), "unknown")


def reason_for(role: str, use: bool, title: str | None) -> str:
    if use:
        return REASONS.get(role, "")
    if role == "unknown" and title:
        return f"Sheet title {title!r} matches no known drawing keyword."
    return REASONS.get(role, REASONS["unknown"])


def classify_page(
    doc: pymupdf.Document, page_index: int, doc_id: str
) -> Sheet:
    page = doc[page_index]
    text = page.get_text() or ""
    title_block = title_block_text(page)
    words = page.get_text("words") or []
    field_title = sheet_title_field(title_block)
    keyword_title = parse_title(title_block, text)
    title = field_title or keyword_title

    sheet_no = parse_sheet_no(title_block) or parse_sheet_no(text)
    scale_text, pts_per_ft = find_scale(title_block)
    if scale_text is None:
        scale_text, pts_per_ft = find_scale(text)
    role = assign_role(sheet_no, keyword_title or title, pts_per_ft)
    use = role in USABLE_ROLES
    levels = parse_levels(field_title) or parse_levels(title)

    paths = None
    distinct_layers: set[str] = set()
    if role in DRAWING_STAT_ROLES:
        drawings = page.get_drawings()
        paths = len(drawings)
        distinct_layers = {normalise(d.get("layer")) for d in drawings}
        distinct_layers.discard("")

    page_no = page_index + 1
    return Sheet(
        sheet_id=f"{doc_id}-p{page_no:03d}",
        doc_id=doc_id,
        page=page_no,
        sheet_no=sheet_no,
        title=title,
        discipline=discipline_of(sheet_no),
        role=role,  # type: ignore[arg-type]
        scale_text=scale_text,
        scale_pts_per_ft=pts_per_ft,
        scale_source="title_block" if scale_text else "none",
        levels=levels,
        use=use,
        reason=reason_for(role, use, title),
        stats=SheetStats(
            paths=paths,
            words=len(words),
            layers=len(distinct_layers),
            dim_tokens=len(DIM_TOKEN_RE.findall(text)),
        ),
        geometry_file=None,
    )


def classify_document(
    path: Path,
    doc_id: str,
    on_progress: Callable[[int, int, Sheet], None] | None = None,
) -> tuple[Document, list[Sheet]]:
    with pymupdf.open(path) as doc:
        first = doc[0]
        ocgs = doc.get_ocgs() or {}
        page_size = [round(first.rect.width, 2), round(first.rect.height, 2)]
        sheets: list[Sheet] = []
        any_text = False
        total = doc.page_count
        for index in range(total):
            sheet = classify_page(doc, index, doc_id)
            if sheet.stats.words > 0:
                any_text = True
            sheets.append(sheet)
            if on_progress:
                on_progress(index + 1, total, sheet)
        counts = collections.Counter(s.discipline for s in sheets)
        discipline = counts.most_common(1)[0][0] if counts else "unknown"
        document = Document(
            doc_id=doc_id,
            filename=path.name,
            slot="drawings",
            discipline=discipline,
            pages=doc.page_count,
            page_size_pt=page_size,
            text_extractable=any_text,
            layered=bool(ocgs),
            layer_count=len(ocgs),
        )
    return document, sheets


def run_real(
    project: Project,
    drawing_files: dict[str, Path],
    on_progress: ProgressFn | None = None,
) -> Project:
    items = list(drawing_files.items())
    total_pages = 0
    counts: list[int] = []
    for _doc_id, path in items:
        with pymupdf.open(path) as doc:
            counts.append(doc.page_count)
            total_pages += doc.page_count

    drawing_docs: list[Document] = []
    sheets: list[Sheet] = []
    done = 0
    for (doc_id, path), _n in zip(items, counts, strict=True):
        document, doc_sheets = classify_document(path, doc_id)
        drawing_docs.append(document)
        for sheet in doc_sheets:
            sheets.append(sheet)
            done += 1
            if on_progress and total_pages:
                on_progress(
                    done / total_pages,
                    f"Classified {path.name} p.{sheet.page}/{document.pages}",
                )

    standards = [d for d in project.documents if d.slot == "standards"]
    return project.model_copy(
        update={"documents": drawing_docs + standards, "sheets": sheets}
    )


def run_stub(
    project: Project,
    drawing_files: dict[str, Path],
    on_progress: ProgressFn | None = None,
) -> Project:
    fixture = load_fixture("project.json", Project)
    fixture.project_id = project.project_id
    fixture.name = project.name
    fixture.created_at = project.created_at
    standards = [d for d in project.documents if d.slot == "standards"]
    drawings = [d for d in project.documents if d.slot == "drawings"]
    if drawings:
        for sheet in fixture.sheets:
            sheet.doc_id = drawings[0].doc_id
    fixture.documents = drawings + standards
    if on_progress:
        on_progress(1.0, "Stub classify loaded fixture project.json")
    return fixture


def run(
    project: Project,
    drawing_files: dict[str, Path],
    on_progress: ProgressFn | None = None,
) -> Project:
    return invoke(
        "classify", project, drawing_files, on_progress=on_progress
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify uploaded drawings PDFs for a PlanCheck project."
    )
    parser.add_argument("--project", required=True, help="Project id")
    args = parser.parse_args()
    from plancheck.api import storage

    project = storage.load_project(args.project)
    result = run(project, storage.drawing_files(args.project))
    storage.save_project(result)
    used = sum(1 for s in result.sheets if s.use)
    print(
        f"{result.project_id}: {len(result.sheets)} sheets, {used} marked use=true"
    )


if __name__ == "__main__":
    main()
