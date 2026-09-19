"""Versioned, renderer-independent editable building and desktop contracts."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, FiniteFloat


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str


class Source(BaseModel):
    document_id: str = ""
    sheet_id: str = ""
    page: int | None = None
    method: str = "user"
    assumed: bool = False


class Floor(Entity):
    name: str
    elevation_ft: FiniteFloat = 0
    height_ft: FiniteFloat = Field(default=9, gt=0)


class Vertex(Entity):
    floor_id: str
    x: FiniteFloat
    y: FiniteFloat


class BuildingWall(Entity):
    floor_id: str
    start_id: str
    end_id: str
    thickness_ft: FiniteFloat = Field(default=0.5, gt=0, le=10)
    height_ft: FiniteFloat = Field(default=9, gt=0, le=100)
    structural: Literal["loadbearing", "nonstructural", "unknown"] = "unknown"
    locked: bool = True
    material: str = "plaster"
    confidence: float = Field(default=1, ge=0, le=1)
    source: Source = Field(default_factory=Source)


class Opening(Entity):
    wall_id: str
    kind: Literal["door", "window"]
    offset_ft: FiniteFloat = Field(ge=0)
    width_ft: FiniteFloat = Field(gt=0)
    height_ft: FiniteFloat = Field(default=7, gt=0)
    sill_ft: FiniteFloat = Field(default=0, ge=0)
    hinge: Literal["left", "right"] = "left"
    swing: Literal["in", "out"] = "in"
    clear_width_ft: FiniteFloat | None = None
    source: Source = Field(default_factory=Source)


class Room(Entity):
    floor_id: str
    name: str
    category: str = "other"
    type_ref: str = ""
    polygon: list[tuple[FiniteFloat, FiniteFloat]]
    wall_ids: list[str] = Field(default_factory=list)
    floor_material: str = "oak"
    confidence: float = Field(default=1, ge=0, le=1)
    needs_review: bool = False
    instance_count: int = 0
    source: Source = Field(default_factory=Source)


class PlacedObject(Entity):
    floor_id: str
    asset_id: str
    kind: str = "furniture"
    x: FiniteFloat
    y: FiniteFloat
    rotation_deg: FiniteFloat = 0
    width_ft: FiniteFloat = Field(default=2, gt=0)
    depth_ft: FiniteFloat = Field(default=2, gt=0)
    height_ft: FiniteFloat = Field(default=2, gt=0)


class Environment(BaseModel):
    sun_azimuth: FiniteFloat = 135
    time: FiniteFloat = Field(default=14, ge=0, le=24)
    season: Literal["spring", "summer", "autumn", "winter"] = "summer"


class ReviewItem(Entity):
    kind: str
    message: str
    document_id: str = ""
    sheet_id: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    status: Literal["pending", "resolved"] = "pending"


class CatalogueFixture(BaseModel):
    kind: str = "unknown"
    x: FiniteFloat = 0
    y: FiniteFloat = 0
    asset_id: str = ""


class TypeCatalogueEntry(BaseModel):
    """A unit-plan room type. Not a storey — instances live on floor-plan rooms."""

    type_ref: str
    name: str
    label: str = ""
    category: str = "other"
    polygon: list[tuple[FiniteFloat, FiniteFloat]] = Field(default_factory=list)
    area_sqft: float = 0
    aspect_ratio: float = 0
    fixtures: list[CatalogueFixture] = Field(default_factory=list)
    instance_count: int = 0
    source: Source = Field(default_factory=Source)


class Building(BaseModel):
    schema_version: Literal[2] = 2
    units: Literal["feet"] = "feet"
    floors: list[Floor] = Field(default_factory=list)
    vertices: list[Vertex] = Field(default_factory=list)
    walls: list[BuildingWall] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    objects: list[PlacedObject] = Field(default_factory=list)
    type_catalogue: list[TypeCatalogueEntry] = Field(default_factory=list)
    environment: Environment = Field(default_factory=Environment)
    review: list[ReviewItem] = Field(default_factory=list)


class DesignBrief(BaseModel):
    name: str = Field(default="Untitled project", min_length=1, max_length=160)
    building_use: str = "Home"
    floors: str = "2"
    rooms: str = "3 bedrooms, 2 bathrooms, kitchen, living room"
    area: str = "2,400 sq ft"
    style: str = "Warm minimal"


class ModelCommand(BaseModel):
    kind: str
    target_id: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class CommandBatch(BaseModel):
    expected_revision: int
    commands: list[ModelCommand] = Field(min_length=1, max_length=1000)


class RevisionRequest(BaseModel):
    expected_revision: int


class DesktopProject(BaseModel):
    project_id: str
    name: str
    revision: int
    created_at: str
    updated_at: str
    brief: DesignBrief | None = None
    building: Building
    rules: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    files: list[dict[str, Any]] = Field(default_factory=list)
    sheets: list[dict[str, Any]] = Field(default_factory=list)
    import_meta: dict[str, Any] = Field(default_factory=dict)
    can_undo: bool = False
    can_redo: bool = False


class BuildingPatch(BaseModel):
    """Delta returned by edit commands so the desktop can patch a local Building."""

    revision: int
    can_undo: bool = False
    can_redo: bool = False
    changed: dict[str, list[Any]] = Field(default_factory=dict)
    removed_ids: list[str] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    environment: dict[str, Any] | None = None

