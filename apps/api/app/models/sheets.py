"""Sheet classification. Mirror of packages/schemas/src/sheets.ts.

The classifier reads the title block (structured text on every page) and sorts
the full set into roles, so the user drops in the whole PDF instead of being
asked which pages matter.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SheetRole = Literal[
    "floor_plan",  # whole repeating floor at 1/16". Room inventory and repeat counts.
    "enlarged_plan",  # segment at 3/16" or 1/4". Accurate geometry.
    "unit_plan",  # one drawing per unit type. Highest precision.
    "schedule",  # door / wall / finish schedules. Validates labels.
    "code_matrix",  # building code compliance table. Hook for city codes later.
    "elevation",
    "section",
    "detail",
    "site",
    "roof",
    "edge_of_slab",
    "index",
    "unknown",
]

#: Roles that carry plan geometry worth extracting.
EXTRACTABLE_ROLES: frozenset[str] = frozenset({"floor_plan", "enlarged_plan", "unit_plan"})


class Sheet(BaseModel):
    page: int
    """1-indexed page in the uploaded PDF."""

    sheet_no: str | None = None
    title: str | None = None
    role: SheetRole = "unknown"
    scale: str | None = None
    scale_pts_per_ft: float | None = None

    dim_tokens: int | None = None
    """Dimension-token count. A real plan sheet has 60+; a details sheet under 20."""

    use: bool = False
    reason: str
    """Why it is or isn't used. Shown verbatim in the UI."""
