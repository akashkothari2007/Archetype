"""Title block reading.

Every sheet carries a structured title block in a strip down the right-hand
side. Its fields are label/value pairs:

    Sheet Title:            Scale:          Date:       Project No.:
    ENLARGED UNIT PLANS     1/4" = 1'-0"    24/02/16    21-039
    Drawing No:
    A.801

A whole-page regex does not work here. `Drawing No:\\s*([A-Z0-9.\\-]+)` matches
"S" on every page of the reference set, because the label and its value are
separate text runs and the next thing in reading order is "Scale:". Worse, a
keyword scan over full page text finds ELEVATION, SCHEDULE, ROOF and SITE all
on one elevation sheet, since the general notes mention them.

So fields are located by anchoring on their label and reading the cell below
it, bounded on the right by the next label on the same row. The regexes from
the brief are kept as a fallback for sheets whose labels do not parse.
"""

from __future__ import annotations

import re

from plancheck.scale import parse_scale_text

#: Label phrases, as word sequences. Longest match wins.
LABELS: tuple[tuple[str, ...], ...] = (
    ("Drawing", "Issues/Revisions:"),
    ("Drawing", "Series:"),
    ("Drawing", "No:"),
    ("Sheet", "Title:"),
    ("Project", "No.:"),
    ("Design", "By:"),
    ("Drawn", "By:"),
    ("Approved", "By:"),
    ("Key", "Plan:"),
    ("Architect's", "Stamp"),
    ("Issue/Revision",),
    ("Project:",),
    ("Scale:",),
    ("Date:",),
    ("Note:",),
    ("No.",),
    ("By:",),
)

#: Title keywords, checked in this order. First hit wins.
TITLE_KEYWORDS: tuple[str, ...] = (
    "EDGE OF SLAB",
    "UNIT PLAN",
    "FLOOR PLAN",
    "ELEVATION",
    "SECTION",
    "SCHEDULE",
    "DETAIL",
    "ROOF",
    "SITE",
)

#: Fraction of page width at which the title block strip starts.
STRIP_FRACTION = 0.82

#: Rows are grouped by `top` within this many points.
ROW_TOLERANCE = 2.0

SHEET_NO_RE = re.compile(r"Drawing No:\s*([A-Z0-9.\-]+)")
SHEET_NO_SHAPE_RE = re.compile(r"^[A-Z]{1,3}[.\-]?\d{1,3}[a-z]?$")


class TitleBlock:
    """Parsed title block for one page."""

    def __init__(
        self,
        sheet_no: str | None,
        title: str | None,
        scale_text: str | None,
        scale_pts_per_ft: float | None,
        project_no: str | None,
    ) -> None:
        self.sheet_no = sheet_no
        self.title = title
        self.scale_text = scale_text
        self.scale_pts_per_ft = scale_pts_per_ft
        self.project_no = project_no

    def __repr__(self) -> str:
        return (
            f"TitleBlock(sheet_no={self.sheet_no!r}, title={self.title!r}, "
            f"scale_text={self.scale_text!r})"
        )

    def title_keyword(self) -> str | None:
        """First recognised drawing keyword in the sheet title, if any."""
        if not self.title:
            return None
        upper = self.title.upper()
        return next((k for k in TITLE_KEYWORDS if k in upper), None)


def read(words: list[dict], page_width: float, page_text: str = "") -> TitleBlock:
    """Parse the title block from display-space words.

    `words` need `text`, `x0`, `x1`, `top`.
    """
    strip = [w for w in words if w["x0"] >= page_width * STRIP_FRACTION]
    rows = _rows(strip)
    spans = [_label_spans(row) for row in rows]

    sheet_no = _field(rows, spans, ("Drawing", "No:"), max_lines=1)
    title = _field(rows, spans, ("Sheet", "Title:"), max_lines=3)
    scale_text = _field(rows, spans, ("Scale:",), max_lines=1)
    project_no = _field(rows, spans, ("Project", "No.:"), max_lines=1)

    if sheet_no is None and page_text:
        fallback = SHEET_NO_RE.search(page_text)
        # The fallback regex famously matches "S"; only accept a real shape.
        if fallback and SHEET_NO_SHAPE_RE.match(fallback.group(1)):
            sheet_no = fallback.group(1)

    if sheet_no is not None and not SHEET_NO_SHAPE_RE.match(sheet_no):
        sheet_no = None

    parsed = parse_scale_text(scale_text or "") if scale_text else None
    if parsed is None and page_text:
        parsed = parse_scale_text(page_text)

    return TitleBlock(
        sheet_no=sheet_no,
        title=title,
        scale_text=parsed[0] if parsed else (scale_text or None),
        scale_pts_per_ft=round(parsed[1], 4) if parsed else None,
        project_no=project_no,
    )


def _rows(words: list[dict]) -> list[list[dict]]:
    """Group words into visual rows, each sorted left to right."""
    rows: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1][0]["top"] - word["top"]) <= ROW_TOLERANCE:
            rows[-1].append(word)
        else:
            rows.append([word])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    return rows


def _label_spans(row: list[dict]) -> list[tuple[int, tuple[str, ...]]]:
    """Positions in `row` where a known label phrase starts."""
    found: list[tuple[int, tuple[str, ...]]] = []
    i = 0
    while i < len(row):
        for phrase in LABELS:
            if i + len(phrase) <= len(row) and all(
                row[i + k]["text"] == phrase[k] for k in range(len(phrase))
            ):
                found.append((i, phrase))
                i += len(phrase)
                break
        else:
            i += 1
    return found


def _field(
    rows: list[list[dict]],
    spans: list[list[tuple[int, tuple[str, ...]]]],
    label: tuple[str, ...],
    max_lines: int,
) -> str | None:
    """Read the value cell beneath `label`.

    Bounded on the right by the next label on the same row, and below by the
    next row that contains any label at all.
    """
    for index, row_spans in enumerate(spans):
        match = next((s for s in row_spans if s[1] == label), None)
        if match is None:
            continue

        start_word = rows[index][match[0]]
        x_start = start_word["x0"]
        later = [rows[index][pos]["x0"] for pos, _ in row_spans if pos > match[0]]
        x_end = min(later) if later else float("inf")

        collected: list[str] = []
        for row in rows[index + 1 :]:
            if _label_spans(row):
                break
            cell = [w["text"] for w in row if x_start - 3.0 <= w["x0"] < x_end - 3.0]
            if not cell:
                if collected:
                    break
                continue
            collected.append(" ".join(cell))
            if len(collected) >= max_lines:
                break

        if collected:
            return " ".join(collected).strip()
    return None
