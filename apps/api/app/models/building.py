"""building.json — the central artifact of PlanCheck.

Mirror of packages/schemas/src/building.ts. Edit both in the same commit.

CONVENTIONS
    Coordinates are FEET, origin at sheet bottom-left, y increasing upward.
    The extractor performs the y-flip so nothing downstream has to.
    Areas are carried in both sqft and m2 because the drawings are imperial
    and the brand standards are metric. Never convert at read time.

ASSEMBLY
    One building is assembled from MANY sheets at three different scales
    (whole floor for counts, enlarged segments and unit plans for geometry).
    Every room therefore carries its own `source`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.1.0"

PointFt = tuple[float, float]
"""(x, y) in feet."""

BBoxFt = tuple[float, float, float, float]
"""(min_x, min_y, max_x, max_y) in feet."""

SheetTier = Literal["floor_plan", "enlarged_plan", "unit_plan", "schedule"]
"""Which tier of drawing a value came from. Precision increases down the list."""

ExtractionMethod = Literal[
    "floodfill",
    "dimension_string",
    "schedule_text",
    "inferred",
    "assumed",
    "stub",
]

MetricUnit = Literal["m2", "sqft", "m", "ft", "mm", "in"]

Discipline = Literal["hvac", "plumbing", "electrical"]


class Provenance(BaseModel):
    page: int
    sheet_no: str | None = None
    tier: SheetTier | None = None
    method: ExtractionMethod


class Metric(BaseModel):
    """One measurable property of a room.

    A metric that could not be measured must be ABSENT from the room's metric
    map, never present as zero. E3 then reports "not measurable" instead of
    inventing a passing or failing comparison.
    """

    value: float
    unit: MetricUnit
    confidence: float = Field(ge=0.0, le=1.0)
    source: Provenance


class Room(BaseModel):
    id: str
    type: str
    """Normalized key that rules match against, e.g. "guestroom.studio_king"."""

    label: str
    """Raw text as it appears on the drawing, e.g. "STUDIO KING". Keep both."""

    number: str | None = None
    level_id: str

    polygon_ft: list[PointFt]
    bbox_ft: BBoxFt

    metrics: dict[str, Metric] = Field(default_factory=dict)
    """Open map keyed by metric name. A rule says metric="clear_width" and E3
    looks it up here, so new rule types need zero schema changes."""

    unit_type_id: str | None = None
    """Blast radius. Points at the repeating type this room is an instance of."""

    confidence: float = Field(ge=0.0, le=1.0)
    confidence_notes: list[str] = Field(default_factory=list)

    source: Provenance

    opening_ids: list[str] = Field(default_factory=list)
    fixture_ids: list[str] = Field(default_factory=list)
    violation_ids: list[str] = Field(default_factory=list)
    """Populated by E3. Always present, empty out of E1."""


class UnitType(BaseModel):
    """A repeating guestroom type.

    Geometry comes from the unit plan sheet, the count comes from the
    whole-floor plan. Each tier does the job it is good at.
    """

    id: str
    type: str
    label: str
    count: int
    count_by_level: dict[str, int] = Field(default_factory=dict)
    representative_room_id: str | None = None
    member_room_ids: list[str] = Field(default_factory=list)
    source: Provenance


class Level(BaseModel):
    id: str
    name: str
    index: int
    """Storey index: 0 = ground."""

    elevation_ft: float
    floor_to_floor_ft: float
    elevation_assumed: bool = True
    source_pages: list[int] = Field(default_factory=list)


class Opening(BaseModel):
    id: str
    kind: Literal["door", "window", "opening"]
    tag: str | None = None
    connects: tuple[str, str | None]
    """Rooms on either side. Second entry is None when it opens to outside."""

    xy_ft: PointFt
    width_ft: float | None = None
    height_ft: float | None = None
    height_assumed: bool = True
    source: Provenance


class Dimension(BaseModel):
    text: str
    """Raw token as extracted, mangling and all. Keep it for debugging."""

    feet: float | None = None
    metres: float | None = None
    xy_ft: PointFt
    near_room_id: str | None = None
    parsed_from: Literal["metric_bracket", "imperial", "computed"]
    """Imperial fractions extract mangled (31'-2 1/2" comes out 31'-212), so
    the metric bracket is the reliable one."""

    source: Provenance


class Fixture(BaseModel):
    id: str
    tag: str
    discipline: Discipline
    xy_ft: PointFt
    assumed_z_ft: float
    """Never extracted. Assigned per discipline for rendering only."""

    in_room_id: str | None = None
    source: Provenance


class SheetSource(BaseModel):
    """One entry per page that contributed to this building."""

    page: int
    sheet_no: str | None = None
    title: str | None = None
    tier: SheetTier
    scale_label: str | None = None
    scale_pts_per_ft: float | None = None
    dpi: int | None = None
    scale_verified: bool = False
    """True when the printed scale was confirmed against repeated dimensions."""


class BuildingMeta(BaseModel):
    schema_version: str = SCHEMA_VERSION
    source_pdf: str
    pages: list[int]
    units: Literal["ft"] = "ft"
    generator: str
    """"stub" until E1 is real. This field must never silently disappear."""

    extracted_at: datetime
    bounds_ft: BBoxFt


class BuildingDefaults(BaseModel):
    """Rendering conventions, not extracted data.

    2D plans carry no elevation information. Anywhere these reach the screen
    they must be labelled assumed.
    """

    wall_height_ft: float = 9.0
    wall_thickness_ft: float = 0.5
    door_height_ft: float = 6.75
    assumed: Literal[True] = True


class Building(BaseModel):
    meta: BuildingMeta
    defaults: BuildingDefaults = Field(default_factory=BuildingDefaults)
    sheets_used: list[SheetSource] = Field(default_factory=list)
    levels: list[Level] = Field(default_factory=list)
    unit_types: list[UnitType] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    dimensions: list[Dimension] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    """What the extractor could not do. Surfaced in the UI, never swallowed."""
