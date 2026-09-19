"""CAD layer name -> semantic bucket.

Layer names often carry an xref prefix::

    21-039_XREF Floor Plans - CFS|WALL-STUD-LOADBEARING

Normalise by splitting on ``|`` and taking the last segment. Unknown layers
go to the ``unmapped`` bucket with counts — never crash, never drop.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel, Field

# Normalised layer name (last | segment) -> semantic bucket.
LAYER_TO_BUCKET: dict[str, str] = {
    "WALL": "wall",
    "WALL-INTR": "wall",
    "WALL-STUD": "wall",
    "WALL-STUD-LOADBEARING": "wall",
    "WALL-INSUL": "wall_hatch",
    "WALL-HATCH LIGHT": "wall_hatch",
    "HATCH-CONC. WALL": "wall_hatch",
    "DOOR": "door",
    "DOOR-FINE": "door",
    "DOOR-HIDDEN": "door",
    "WINDOW": "window",
    "PLUMBING FIXTURE": "fixture",
    "P-SANR-FIXT": "fixture",
    "A-PLMG-FIXT": "fixture",
    "NEW-PLUMB": "fixture",
    "NEW-PMB-DRAINS": "fixture",
    "GRID": "grid",
    "ANNO-GRID": "grid",
    "COLUMN": "column",
    "STAIR": "stair",
    "A-STAIRS": "stair",
    "ELEVATOR": "elevator",
    "MECH-SHAFT": "shaft",
    "FLOOR-CLR SPACE": "clear_space",
    "ANNO-CLEAR SPACE": "clear_space",
    "ANNO-ROOM TAG": "room_tag",
    "ANNO-DIMS": "dimension",
    "I-FURN": "furniture",
    "FURNITURE": "furniture",
    "ID FURN": "furniture",
    "FUR": "furniture",
    "MILLWORK": "furniture",
}

EXCLUDED_BUCKETS = frozenset({"wall_hatch", "furniture"})
UNMAPPED = "unmapped"


class LayerSummary(BaseModel):
    """Counts that extract/classify attach to a sheet. Unmapped names are kept."""

    buckets: dict[str, int] = Field(default_factory=dict)
    unmapped: dict[str, int] = Field(default_factory=dict)
    excluded: dict[str, int] = Field(default_factory=dict)

    @property
    def distinct_count(self) -> int:
        return sum(1 for n in self.buckets.values() if n) + len(self.unmapped)


def normalise(raw: str | None) -> str:
    """Strip xref prefix; empty/None becomes ``''``."""
    if not raw:
        return ""
    return raw.split("|")[-1].strip()


def bucket_for(raw: str | None) -> str:
    """Return the semantic bucket, or ``unmapped``."""
    key = normalise(raw)
    if not key:
        return UNMAPPED
    return LAYER_TO_BUCKET.get(key, UNMAPPED)


def is_excluded(raw: str | None) -> bool:
    return bucket_for(raw) in EXCLUDED_BUCKETS


def summarise(layer_names: Iterable[str | None]) -> LayerSummary:
    """Bucket every name. Unknown layers are counted under their normalised name."""
    buckets: Counter[str] = Counter()
    unmapped: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    for raw in layer_names:
        key = normalise(raw)
        bucket = LAYER_TO_BUCKET.get(key, UNMAPPED) if key else UNMAPPED
        buckets[bucket] += 1
        if bucket == UNMAPPED:
            unmapped[key or "(none)"] += 1
        if bucket in EXCLUDED_BUCKETS:
            excluded[bucket] += 1
    return LayerSummary(
        buckets=dict(buckets),
        unmapped=dict(unmapped),
        excluded=dict(excluded),
    )
