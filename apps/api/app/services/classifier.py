"""Sheet classifier — STUB.

WHAT THE REAL ONE WILL DO
    Every page of an architectural set carries a structured title block. Read
    it with pdfplumber and three regexes sort a 51-page PDF into roles:

        sheet_no = /Drawing No:\\s*([A-Z0-9.\\-]+)/
        scale    = /(\\d+(?:\\/\\d+)?"\\s*=\\s*\\d+'-\\d+")/
        title    = FLOOR PLAN | UNIT PLAN | ELEVATION | SECTION | DETAIL
                 | SCHEDULE | ROOF | EDGE OF SLAB

        unit_plan      sheet starts A.8  OR title contains UNIT PLAN
        enlarged_plan  title has FLOOR PLAN and scale is 3/16" or 1/4"
        floor_plan     title has FLOOR PLAN and scale is 1/16"
        schedule       title contains SCHEDULE
        ignore         everything else

    Cross-check the role against dimension density as a sanity signal: a real
    plan sheet has 60+ dimension tokens, a details sheet has under 20.

WHAT THIS STUB DOES
    Reads the page count with pypdf, then returns the hand-verified sheet map
    for the TownePlace Sidney set when the page count matches, and honest
    `role: unknown, use: false` rows otherwise. No title block is read.

    The sheet map below is the domain knowledge, written down in exactly one
    place. When the real classifier lands it replaces this function and the
    map becomes the regression fixture that proves the parser agrees with the
    drawing index.
"""

from __future__ import annotations

from pathlib import Path

from app.models.sheets import Sheet, SheetRole
from app.services.scale import parse_scale_label

GENERATOR = "stub"

#: Page count of the reference set, used to decide whether the map applies.
TOWNEPLACE_PAGE_COUNT = 51

#: (first_page, last_page, sheet_no, title, role, scale, reason)
#: Derived from the drawing index on page 1 of 21-039_Sidney TPS_Arch._IFC.pdf.
_SHEET_MAP: list[tuple[int, int, str | None, str, SheetRole, str | None, str]] = [
    (1, 1, "A.000", "COVER SHEET & DRAWING INDEX", "index", None,
     "Drawing index. Useful to confirm the sheet list, carries no geometry."),
    (2, 4, "ASP-1", "SITE PLAN", "site", None,
     "Property lines and grading. Nothing about the building interior."),
    (5, 5, "A.002", "WALL SCHEDULE", "schedule", None,
     "Real wall assemblies and thicknesses. Enrichment once the core works — "
     "it is how we stop assuming 0.5 ft."),
    (6, 6, "A.100", "BCBC MATRIX & FIRE SEPARATION PLANS", "code_matrix", None,
     "Building code compliance table the architect filled in by hand. "
     "Hook for the city-codes rule source later."),
    (7, 7, "A.201", "GROUND FLOOR PLAN", "floor_plan", '1/16"=1\'-0"',
     "Whole ground floor. Lobby and public areas have their own brand rules."),
    (8, 8, "A.202", "TYPICAL FLOOR PLAN (2ND & 3RD)", "floor_plan", '1/16"=1\'-0"',
     "Whole repeating floor. This is where unit repeat counts come from."),
    (9, 9, "A.203", "ROOF PLAN", "roof", None, "No rooms."),
    (10, 16, "A.206", "EDGE OF SLAB", "edge_of_slab", None,
     "Structural slab outline. Looks like a floor plan, contains no rooms."),
    (17, 18, "A.301", "EXTERIOR ELEVATIONS", "elevation", None,
     "What the outside looks like. No plan geometry."),
    (19, 22, "A.400", "BUILDING SECTIONS", "section", None,
     "Vertical cuts. Heights exist here but are not tied to a locatable room. "
     "Possible source of real ceiling heights later."),
    (23, 27, "A.410", "DETAILS", "detail", None, "Wall assembly construction. No room data."),
    (28, 32, "A.501", "ENLARGED GROUND FLOOR PLAN", "enlarged_plan", '3/16"=1\'-0"',
     "Ground floor segments at 3x, heavily dimensioned. Accurate public-area geometry."),
    (33, 37, "A.502", "ENLARGED TYPICAL FLOOR PLAN", "enlarged_plan", '3/16"=1\'-0"',
     "Typical floor segments at 3x, heavily dimensioned. Accurate guestroom geometry."),
    (38, 38, "A.302", "EXTERIOR ELEVATIONS", "elevation", None, "No plan geometry."),
    (39, 47, "A.411", "DETAILS", "detail", None, "No room data."),
    (48, 48, "A.701", "DOOR SCHEDULE", "schedule", None,
     "Clean tabular room names and door widths. Door width is a real brand and "
     "accessibility rule, and it validates extracted labels for free."),
    (49, 50, "A.520", "DETAILS", "detail", None, "No room data."),
    (51, 51, "A.801", "ENLARGED UNIT PLANS", "unit_plan", '1/4"=1\'-0"',
     "One drawing per unit type including accessible variants. Highest precision "
     "geometry in the set."),
]

#: Roles the pipeline extracts geometry from.
_USE_ROLES: frozenset[SheetRole] = frozenset({"floor_plan", "enlarged_plan", "unit_plan"})


def page_count(pdf_path: Path) -> int | None:
    """Page count only. Deliberately does not touch page content.

    pdfplumber is OOM-killed (exit 137) on the full drawing file, so the real
    pipeline splits pages with qpdf first. pypdf only reads the page tree, so
    it is safe on the whole document.
    """
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf_path), strict=False).pages)
    except Exception:
        return None


def classify(pdf_path: Path, pages: int | None = None) -> tuple[list[Sheet], list[str]]:
    """Classify every page of a drawing set.

    Returns the sheet list and any warnings the UI should surface.
    """
    total = pages if pages is not None else page_count(pdf_path)
    warnings: list[str] = [
        "Sheet roles are stubbed. No title block has been read — the classifier "
        "regexes are not implemented yet."
    ]

    if total is None:
        warnings.append(f"Could not read a page count from {pdf_path.name}.")
        return [], warnings

    if total != TOWNEPLACE_PAGE_COUNT:
        warnings.append(
            f"{pdf_path.name} has {total} pages, and the stub only knows the "
            f"{TOWNEPLACE_PAGE_COUNT}-page TownePlace Sidney set. Every sheet is "
            "reported as unknown until the real classifier lands."
        )
        return [_unknown_sheet(p) for p in range(1, total + 1)], warnings

    sheets = [_sheet_for_page(p) for p in range(1, total + 1)]
    used = sum(1 for s in sheets if s.use)
    warnings.append(
        f"{used} of {total} sheets carry extractable plan geometry. "
        "The rest are classified and skipped with a stated reason."
    )
    return sheets, warnings


def default_pages(sheets: list[Sheet]) -> list[int]:
    """The pages an `auto` extract would run on."""
    return [s.page for s in sheets if s.use]


def _sheet_for_page(page: int) -> Sheet:
    for first, last, sheet_no, title, role, scale, reason in _SHEET_MAP:
        if first <= page <= last:
            return Sheet(
                page=page,
                sheet_no=_sheet_no_for(sheet_no, role, page, first),
                title=title,
                role=role,
                scale=scale,
                scale_pts_per_ft=parse_scale_label(scale) if scale else None,
                dim_tokens=None,
                use=role in _USE_ROLES,
                reason=reason,
            )
    return _unknown_sheet(page)


def _sheet_no_for(base: str | None, role: SheetRole, page: int, first_page: int) -> str | None:
    """Enlarged plans are lettered runs (A.502a .. A.502e), everything else isn't."""
    if base is None:
        return None
    if role == "enlarged_plan":
        return f"{base}{chr(ord('a') + page - first_page)}"
    return base


def _unknown_sheet(page: int) -> Sheet:
    return Sheet(
        page=page,
        sheet_no=None,
        title=None,
        role="unknown",
        scale=None,
        scale_pts_per_ft=None,
        dim_tokens=None,
        use=False,
        reason="Not classified. The title-block parser is not implemented yet.",
    )
