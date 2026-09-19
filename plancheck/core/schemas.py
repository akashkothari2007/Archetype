"""Pydantic v2 contracts for every JSON artifact that crosses a boundary.

These shapes are the team contract. Engines return validated instances, not
loose dicts. Swapping a stub for a real implementation must not change them.

See README.md for which sheet fills which model.json field.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator
from plancheck.core.building import Building

Point2 = Annotated[list[float], Field(min_length=2, max_length=2)]
BBox4 = Annotated[list[float], Field(min_length=4, max_length=4)]
Poly2 = list[Point2]
SizePx = Annotated[list[int], Field(min_length=2, max_length=2)]

SheetRole = Literal[
    "unit_plan",
    "enlarged_plan",
    "floor_plan",
    "slab_edge",
    "schedule",
    "elevation",
    "section",
    "detail",
    "roof",
    "site",
    "unknown",
]
DocumentSlot = Literal["drawings", "standards"]
WallClass = Literal["loadbearing", "interior", "stud", "concrete", "unknown"]
FixtureKind = Literal["wc", "lav", "shower", "tub", "sink", "unknown"]
AxisDir = Literal["x", "y"]
DimensionSource = Literal["metric_bracket", "imperial"]
MismatchSeverity = Literal["fail", "warn", "cannot_verify"]
ScaleSource = Literal["title_block", "none", "user"]
JobState = Literal["queued", "running", "done", "error", "cancelled"]
SpaceCategory = Literal[
    "guestroom",
    "circulation",
    "public",
    "service",
    "back_of_house",
    "bathroom",
    "storage",
    "other",
]


class SheetStats(BaseModel):
    paths: int | None = None
    words: int = 0
    layers: int = 0
    dim_tokens: int = 0


class Sheet(BaseModel):
    """One row of project.json — classification of a single PDF page."""

    sheet_id: str
    doc_id: str
    page: int
    sheet_no: str | None = None
    title: str | None = None
    discipline: str = "unknown"
    role: SheetRole = "unknown"
    scale_text: str | None = None
    scale_pts_per_ft: float | None = None
    scale_source: ScaleSource = "none"
    levels: list[str] = Field(default_factory=list)
    use: bool = False
    reason: str = ""
    stats: SheetStats = Field(default_factory=SheetStats)
    geometry_file: str | None = None

    @model_validator(mode="after")
    def unused_needs_reason(self) -> Sheet:
        if not self.use and not self.reason:
            raise ValueError("use=false sheets must carry a human-readable reason")
        return self


class Document(BaseModel):
    doc_id: str
    filename: str
    slot: DocumentSlot
    discipline: str = "unknown"
    pages: int
    page_size_pt: Point2
    text_extractable: bool
    layered: bool
    layer_count: int = 0


class Project(BaseModel):
    project_id: str
    name: str
    created_at: str
    units: Literal["ft"] = "ft"
    documents: list[Document] = Field(default_factory=list)
    sheets: list[Sheet] = Field(default_factory=list)
    model_file: str | None = None


class DoorSwing(BaseModel):
    center: Point2
    r: float
    a0: float
    a1: float


class Wall(BaseModel):
    """Sheet-space wall. ``cls`` comes from the CAD layer, not geometry.

    ``thickness_pt`` is stroke width on the sheet when extractable.
    Do not invent 3D wall thickness; ``ASSUMED_WALL_THICKNESS_FT`` is a
    rendering convention only.
    """

    id: str
    a: Point2
    b: Point2
    cls: WallClass = "unknown"
    layer: str
    thickness_pt: float | None = None
    len_ft: float


class Door(BaseModel):
    id: str
    xy: Point2
    bbox: BBox4
    width_pt: float
    width_ft: float
    swing: DoorSwing | None = None


class Window(BaseModel):
    id: str
    a: Point2
    b: Point2
    width_ft: float


class Fixture(BaseModel):
    """Sheet-space fixture. ``kind`` starts as unknown — do not guess."""

    id: str
    xy: Point2
    bbox: BBox4
    kind: FixtureKind = "unknown"
    layer: str


class SheetGridAxis(BaseModel):
    label: str
    pos_pt: float
    axis: AxisDir | None = None


class GridBubble(BaseModel):
    label: str
    xy: Point2


class SheetGrid(BaseModel):
    x_axes: list[SheetGridAxis] = Field(default_factory=list)
    y_axes: list[SheetGridAxis] = Field(default_factory=list)
    bubbles: list[GridBubble] = Field(default_factory=list)


class RoomTag(BaseModel):
    text: str
    xy: Point2
    lines: list[str] = Field(default_factory=list)
    number: str | None = None


class Dimension(BaseModel):
    """Prefer the metric bracket; imperial fractions extract mangled."""

    text: str
    feet: float | None = None
    metres: float | None = None
    xy: Point2
    a: Point2
    b: Point2
    source: DimensionSource


class ClearSpace(BaseModel):
    id: str
    polygon: Poly2
    layer: str | None = None


class CoordinateSystem(BaseModel):
    units: Literal["pt"] = "pt"
    origin: Literal["bottom-left"] = "bottom-left"
    y: Literal["up"] = "up"


class RasterRef(BaseModel):
    dpi: float = 150.0
    file: str = ""
    size_px: SizePx = Field(default_factory=lambda: [0, 0])


class ExcludedSummary(BaseModel):
    """Dropped-path counts so excluded data stays auditable."""

    furniture: int = 0
    wall_hatch: int = 0
    unmapped: int = 0


class SheetGeometry(BaseModel):
    """sheets/<id>.json — raw extracted geometry in sheet space (pt, y-up)."""

    sheet_id: str
    page: int
    size_pt: Point2
    scale_pts_per_ft: float
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    doc_id: str = ""
    source_rotation: int = 0
    regions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extraction_stats: dict[str, int] = Field(default_factory=dict)
    layer_map: dict[str, str] = Field(default_factory=dict)
    walls: list[Wall] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    fixtures: list[Fixture] = Field(default_factory=list)
    grid: SheetGrid = Field(default_factory=SheetGrid)
    room_tags: list[RoomTag] = Field(default_factory=list)
    dimensions: list[Dimension] = Field(default_factory=list)
    clear_spaces: list[ClearSpace] = Field(default_factory=list)
    excluded: ExcludedSummary = Field(default_factory=ExcludedSummary)
    raster: RasterRef = Field(default_factory=RasterRef)
    doc_id: str = ""
    source_rotation: int = 0
    regions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extraction_stats: dict[str, int] = Field(default_factory=dict)


class BBoxFt(BaseModel):
    w: float
    d: float


class TypeDoor(BaseModel):
    width_ft: float
    accessible: bool = False
    to: str | None = None


class TypeWindow(BaseModel):
    width_ft: float


class TypeFixture(BaseModel):
    kind: FixtureKind = "unknown"


class SpaceType(BaseModel):
    """Canonical room type. Geometry lives here; instances live in ``spaces``."""

    type_id: str
    name: str
    category: str
    accessible: bool = False
    source_sheet: str = ""
    source_region_pt: BBox4 | None = None
    boundary_ft: Poly2 = Field(default_factory=list)
    area_sqft: float = 0.0
    area_m2: float = 0.0
    bbox_ft: BBoxFt | None = None
    children: list[SpaceType] = Field(default_factory=list)
    doors: list[TypeDoor] = Field(default_factory=list)
    windows: list[TypeWindow] = Field(default_factory=list)
    fixtures: list[TypeFixture] = Field(default_factory=list)
    confidence: float = 1.0
    method: str = "stub"
    instance_count: int = 0

    @model_validator(mode="after")
    def fill_bbox(self) -> SpaceType:
        if self.bbox_ft is None and self.boundary_ft:
            xs = [p[0] for p in self.boundary_ft]
            ys = [p[1] for p in self.boundary_ft]
            self.bbox_ft = BBoxFt(w=max(xs) - min(xs), d=max(ys) - min(ys))
        return self


class Space(BaseModel):
    """One placed instance of a space type. Position only, no geometry."""

    space_id: str
    type_ref: str
    level: int
    number: str | None = None
    origin_ft: Point2
    rotation_deg: float = 0.0
    mirrored: bool = False
    source_sheet: str
    confidence: float = 1.0


class ModelOrigin(BaseModel):
    grid_x: str
    grid_y: str


class ModelXAxis(BaseModel):
    label: str
    x_ft: float


class ModelYAxis(BaseModel):
    label: str
    y_ft: float


class BuildingGrid(BaseModel):
    x_axes: list[ModelXAxis] = Field(default_factory=list)
    y_axes: list[ModelYAxis] = Field(default_factory=list)


class Level(BaseModel):
    index: int
    name: str
    sheets: list[str] = Field(default_factory=list)
    repeats_as: list[int] | None = None


class Model(BaseModel):
    """model.json — central artifact. Feet, y-up, origin at a named grid."""

    units: Literal["feet"] = "feet"
    origin: ModelOrigin
    grid: BuildingGrid = Field(default_factory=BuildingGrid)
    levels: list[Level] = Field(default_factory=list)
    space_types: list[SpaceType] = Field(default_factory=list)
    spaces: list[Space] = Field(default_factory=list)
    building: Building | None = None


class Rule(BaseModel):
    rule_id: str
    applies_to: str
    metric: str
    operator: str
    value: float
    unit: str
    source_doc: str = ""
    source_page: int | None = None
    source_text: str = ""
    extraction: str = "stub"
    status: Literal["pending", "approved", "rejected"] = "pending"
    scope: Literal["room", "opening", "opening_pair"] = "room"
    target_ids: list[str] = Field(default_factory=list)
    source_label: str = ""
    source_section: str = ""
    qualifiers: list[str] = Field(default_factory=list)
    supported: bool = True
    origin: str = "imported"
    superseded_by: str = ""
    excludes: list[str] = Field(default_factory=list)
    applies_to_filter: dict[str, Any] = Field(default_factory=dict)
    editable: bool = True


class Ruleset(BaseModel):
    rules: list[Rule] = Field(default_factory=list)


class Mismatch(BaseModel):
    """A violation attached to a TYPE, not a room. Blast radius is a count."""

    id: str
    type_ref: str
    rule_id: str
    severity: MismatchSeverity
    metric: str
    actual: float | None = None
    required: float | None = None
    unit: str
    delta: float | None = None
    instances_affected: int = 0
    affected_space_ids: list[str] = Field(default_factory=list)
    message: str
    source_page: int | None = None
    source_text: str = ""
    model_confidence: float = 1.0
    entity_id: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    source_doc: str = ""
    source_label: str = ""
    assumption: str = ""
    pinch_polygon: list[list[float]] | None = None
    superseded_by: str = ""


class CheckResult(BaseModel):
    mismatches: list[Mismatch] = Field(default_factory=list)
    coverage: dict[str, Any] | None = None


class ProposedEdit(BaseModel):
    """Agent output. Never mutates model.json. Refuse loadbearing walls."""

    edit_id: str
    mismatch_id: str
    action: str
    target: str
    change: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] = Field(default_factory=dict)
    blocked_by: list[str] = Field(default_factory=list)
    note: str = ""
    affects_instances: int = 0


class ProposedEdits(BaseModel):
    proposed_edits: list[ProposedEdit] = Field(default_factory=list)


class JobStatus(BaseModel):
    phase: str = "queued"
    result: dict[str, Any] | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    job_id: str
    state: JobState
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    sheets_done: list[dict[str, Any]] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)


class SheetPatch(BaseModel):
    use: bool | None = None
    role: SheetRole | None = None


class ExtractRequest(BaseModel):
    pages: list[int] | Literal["auto"] = "auto"


class CreateProjectResponse(BaseModel):
    project_id: str
    documents: list[Document]
    job_id: str


class ProjectListItem(BaseModel):
    project_id: str
    name: str
    created_at: str
    sheet_count: int
    document_count: int
