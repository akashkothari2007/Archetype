"""Project and API envelope types. Mirror of packages/schemas/src/project.ts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.building import Building
from app.models.sheets import Sheet

DocumentKind = Literal["drawings", "standards"]


class UploadedDocument(BaseModel):
    kind: DocumentKind
    filename: str
    bytes: int
    page_count: int | None = None
    sha256: str


class Project(BaseModel):
    project_id: str
    created_at: datetime
    documents: list[UploadedDocument] = Field(default_factory=list)
    sheets: list[Sheet] = Field(default_factory=list)
    """Classification of every page of the drawings PDF."""

    warnings: list[str] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    pages: list[int] | Literal["auto"] = "auto"
    """Explicit page list, or "auto" to take every sheet marked use: true."""


class ExtractResponse(BaseModel):
    project_id: str
    pages: list[int]
    building: Building
    elapsed_ms: int
    """Wall-clock milliseconds, shown in the UI so slow pages are visible."""
