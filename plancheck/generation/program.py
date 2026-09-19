"""Design intent the model is allowed to author. No vertices, no wall topology.

A program says which spaces exist, how big they should be, and what should sit
next to what. A layout says where rectangles go. Everything else — shared
vertices, envelope versus partition, openings — is derived by the compiler.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

USES = ("home", "office", "retail", "mixed")
BuildingUse = Literal["home", "office", "retail", "mixed"]

GRID_FT = 0.5
MIN_ROOM_SIDE_FT = 4.0
_ID_STRIP = re.compile(r"[^a-z0-9]+")
_USE_ALIASES: dict[str, BuildingUse] = {
    "house": "home", "home": "home", "residential": "home", "apartment": "home",
    "villa": "home", "cabin": "home", "duplex": "home", "dwelling": "home",
    "office": "office", "workplace": "office", "studio": "office",
    "coworking": "office", "clinic": "office", "school": "office",
    "hospital": "office", "healthcare": "office", "university": "office",
    "college": "office", "library": "office", "civic": "office",
    "retail": "retail", "shop": "retail", "store": "retail", "boutique": "retail",
    "showroom": "retail", "restaurant": "retail", "cafe": "retail",
    "warehouse": "retail", "industrial": "retail", "factory": "retail",
    "gym": "retail", "supermarket": "retail",
    "mixed": "mixed", "hotel": "mixed", "motel": "mixed", "museum": "mixed",
    "theatre": "mixed", "theater": "mixed", "church": "mixed", "mosque": "mixed",
    "temple": "mixed",
}


def snap(value: float) -> float:
    """Quantise to the layout grid so shared edges stay exactly coincident."""
    return round(round(float(value) / GRID_FT) * GRID_FT, 3)


def slug_id(value: object, fallback: str = "space") -> str:
    """Turn whatever the model labelled a room into a stable lowercase id."""
    text = _ID_STRIP.sub("_", str(value or "").strip().lower()).strip("_")
    if not text or not text[0].isalnum():
        text = f"{fallback}_{text}".strip("_")
    return (text or fallback)[:48]


def coerce_use(value: object) -> BuildingUse:
    """Any building type collapses onto one of the four packer families."""
    key = _ID_STRIP.sub("_", str(value or "").strip().lower()).strip("_")
    if key in USES:
        return key  # type: ignore[return-value]
    return _USE_ALIASES.get(key, "home")


class StoreySpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    height_ft: float = Field(default=10, ge=7, le=24)

    @field_validator("id", mode="before")
    @classmethod
    def _slug(cls, value: object) -> str:
        return slug_id(value, "floor")

    @field_validator("height_ft", mode="before")
    @classmethod
    def _height(cls, value: object) -> float:
        try:
            return min(24.0, max(7.0, float(value)))
        except (TypeError, ValueError):
            return 10.0


class SpaceSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    floor_id: str = Field(min_length=1, max_length=48)
    category: str = Field(default="other", max_length=40)
    target_area_sqft: float = Field(gt=0, le=100_000)
    min_side_ft: float = Field(default=8, ge=MIN_ROOM_SIDE_FT, le=400)
    adjacent_to: list[str] = Field(default_factory=list, max_length=12)
    needs_plumbing: bool = False
    circulation: bool = False
    stair: bool = False
    entry: bool = False

    @field_validator("id", mode="before")
    @classmethod
    def _slug_id(cls, value: object) -> str:
        return slug_id(value, "space")

    @field_validator("floor_id", mode="before")
    @classmethod
    def _slug_floor(cls, value: object) -> str:
        return slug_id(value, "floor")

    @field_validator("adjacent_to", mode="before")
    @classmethod
    def _adj(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [slug_id(item, "space") for item in value if item]

    @field_validator("target_area_sqft", mode="before")
    @classmethod
    def _area(cls, value: object) -> float:
        try:
            return min(100_000.0, max(20.0, float(value)))
        except (TypeError, ValueError):
            return 150.0

    @field_validator("min_side_ft", mode="before")
    @classmethod
    def _side(cls, value: object) -> float:
        try:
            return min(400.0, max(MIN_ROOM_SIDE_FT, float(value)))
        except (TypeError, ValueError):
            return 8.0

    @model_validator(mode="after")
    def _normalise(self) -> SpaceSpec:
        self.category = (self.category or "other").strip().lower().replace(" ", "_")
        if self.stair or self.category in {"stair", "stairs", "core"}:
            self.stair = True
            self.circulation = True
        if self.category in {"circulation", "corridor", "lobby", "landing", "foyer", "hall"}:
            self.circulation = True
        if self.category in {"bathroom", "wc", "restroom", "toilet", "ensuite", "powder"}:
            self.needs_plumbing = True
        return self


class BuildingProgram(BaseModel):
    """The whole design intent for one generated building."""

    model_config = ConfigDict(extra="ignore")

    building_use: BuildingUse = "home"
    storeys: list[StoreySpec] = Field(min_length=1, max_length=8)
    spaces: list[SpaceSpec] = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=1200)

    @field_validator("building_use", mode="before")
    @classmethod
    def _use(cls, value: object) -> BuildingUse:
        return coerce_use(value)

    @model_validator(mode="after")
    def _check(self) -> BuildingProgram:
        seen_storeys: set[str] = set()
        for storey in self.storeys:
            base = storey.id
            n = 2
            while storey.id in seen_storeys:
                storey.id = f"{base}_{n}"[:48]
                n += 1
            seen_storeys.add(storey.id)
        aliases: dict[str, str] = {}
        for storey in self.storeys:
            aliases[storey.id] = storey.id
            aliases[storey.id.replace("_", "")] = storey.id
            head = storey.id.split("_")[0]
            aliases.setdefault(head, storey.id)

        used: set[str] = set()
        for space in self.spaces:
            base = space.id
            n = 2
            while space.id in used:
                space.id = f"{base}_{n}"[:48]
                n += 1
            used.add(space.id)
            if space.floor_id not in seen_storeys:
                space.floor_id = aliases.get(
                    space.floor_id,
                    aliases.get(space.floor_id.replace("_", ""), space.floor_id),
                )
            if space.floor_id not in seen_storeys:
                raise ValueError(
                    f"Space {space.id!r} references unknown floor_id {space.floor_id!r}; "
                    f"use one of {sorted(seen_storeys)}"
                )
        space_ids = [s.id for s in self.spaces]
        for storey in self.storeys:
            if not any(s.floor_id == storey.id for s in self.spaces):
                raise ValueError(f"Storey {storey.id!r} has no spaces")
        # Adjacency is a hint, not a contract: drop dangling references quietly.
        valid = set(space_ids)
        for space in self.spaces:
            space.adjacent_to = [ref for ref in space.adjacent_to if ref in valid and ref != space.id]
        return self

    def floor_spaces(self, floor_id: str) -> list[SpaceSpec]:
        return [s for s in self.spaces if s.floor_id == floor_id]

    def space(self, space_id: str) -> SpaceSpec | None:
        return next((s for s in self.spaces if s.id == space_id), None)

    def elevation_ft(self, floor_id: str) -> float:
        elevation = 0.0
        for storey in self.storeys:
            if storey.id == floor_id:
                return elevation
            elevation += storey.height_ft
        return elevation

    def summary(self) -> str:
        lines = [f"use={self.building_use}, storeys={len(self.storeys)}, spaces={len(self.spaces)}"]
        for storey in self.storeys:
            spaces = self.floor_spaces(storey.id)
            total = sum(s.target_area_sqft for s in spaces)
            names = ", ".join(f"{s.name} {s.target_area_sqft:g}sf" for s in spaces)
            lines.append(f"{storey.id}: {total:g} sqft -- {names}")
        return "\n".join(lines)


class RoomRect(BaseModel):
    """One axis-aligned room footprint in floor coordinates (feet, y-up)."""

    model_config = ConfigDict(extra="ignore")

    space_id: str = Field(min_length=1, max_length=48)
    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def _order(self) -> RoomRect:
        self.x1, self.x2 = snap(min(self.x1, self.x2)), snap(max(self.x1, self.x2))
        self.y1, self.y2 = snap(min(self.y1, self.y2)), snap(max(self.y1, self.y2))
        if self.width_ft < MIN_ROOM_SIDE_FT or self.depth_ft < MIN_ROOM_SIDE_FT:
            raise ValueError(
                f"Room {self.space_id!r} is {self.width_ft:g}x{self.depth_ft:g} ft; "
                f"every side must be at least {MIN_ROOM_SIDE_FT:g} ft"
            )
        return self

    @property
    def width_ft(self) -> float:
        return round(self.x2 - self.x1, 3)

    @property
    def depth_ft(self) -> float:
        return round(self.y2 - self.y1, 3)

    @property
    def area_sqft(self) -> float:
        return round(self.width_ft * self.depth_ft, 2)

    def corners(self) -> list[tuple[float, float]]:
        return [(self.x1, self.y1), (self.x2, self.y1), (self.x2, self.y2), (self.x1, self.y2)]

    def center(self) -> tuple[float, float]:
        return (round((self.x1 + self.x2) / 2, 3), round((self.y1 + self.y2) / 2, 3))


class FloorLayout(BaseModel):
    """Rectangles that tile one storey. Overlaps are rejected before compiling."""

    model_config = ConfigDict(extra="ignore")

    floor_id: str = Field(min_length=1, max_length=48)
    width_ft: float = Field(gt=0, le=2000)
    depth_ft: float = Field(gt=0, le=2000)
    rooms: list[RoomRect] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def _check(self) -> FloorLayout:
        self.width_ft, self.depth_ft = snap(self.width_ft), snap(self.depth_ft)
        seen: set[str] = set()
        for rect in self.rooms:
            if rect.space_id in seen:
                raise ValueError(f"Floor {self.floor_id!r} places {rect.space_id!r} twice")
            seen.add(rect.space_id)
            if rect.x2 > self.width_ft + 1e-6 or rect.y2 > self.depth_ft + 1e-6 or rect.x1 < -1e-6 or rect.y1 < -1e-6:
                raise ValueError(
                    f"Room {rect.space_id!r} falls outside the "
                    f"{self.width_ft:g}x{self.depth_ft:g} ft footprint"
                )
        for i, a in enumerate(self.rooms):
            for b in self.rooms[i + 1 :]:
                if min(a.x2, b.x2) - max(a.x1, b.x1) > 1e-6 and min(a.y2, b.y2) - max(a.y1, b.y1) > 1e-6:
                    raise ValueError(f"Rooms {a.space_id!r} and {b.space_id!r} overlap")
        return self

    def summary(self) -> str:
        parts = [
            f"{r.space_id} {r.width_ft:g}x{r.depth_ft:g} at ({r.x1:g},{r.y1:g})"
            for r in sorted(self.rooms, key=lambda r: (r.y1, r.x1))
        ]
        return f"{self.floor_id} [{self.width_ft:g}x{self.depth_ft:g} ft]: " + "; ".join(parts)
