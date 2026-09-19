"""Project routes.

Two calls, because classification and extraction are genuinely different steps:

    POST /api/projects              upload the whole set, get a per-page verdict
    POST /api/projects/{id}/extract run only the pages that matter

The first call returning "here is what we found and here is what we are
ignoring and why" is worth building even though it is cheap. It is what makes
the tool feel like it read the drawings rather than guessed.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.models.building import Building
from app.models.project import ExtractRequest, ExtractResponse, Project
from app.services import classifier, extractor, storage

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    drawings: UploadFile = File(..., description="Architectural drawing set, PDF."),
    standards: UploadFile | None = File(None, description="Brand standards manual, PDF."),
) -> Project:
    """Upload a drawing set and classify every page of it."""
    project_id = storage.new_project_id()
    storage.create_project_dir(project_id)

    try:
        documents = [_store(project_id, "drawings", drawings)]
        if standards is not None and standards.filename:
            documents.append(_store(project_id, "standards", standards))
    except storage.UploadTooLarge as exc:
        storage.delete_project(project_id)
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    except Exception:
        storage.delete_project(project_id)
        raise

    drawings_path = storage.upload_path(project_id, "drawings")
    assert drawings_path is not None

    documents[0].page_count = classifier.page_count(drawings_path)
    sheets, warnings = classifier.classify(drawings_path, pages=documents[0].page_count)

    project = Project(
        project_id=project_id,
        created_at=storage.utcnow(),
        documents=documents,
        sheets=sheets,
        warnings=warnings,
    )
    storage.save_project(project)
    return project


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    return _load(project_id)


@router.post("/{project_id}/extract", response_model=ExtractResponse)
def extract_building(project_id: str, request: ExtractRequest) -> ExtractResponse:
    """Run E1 over the selected pages and return building.json."""
    project = _load(project_id)

    pages = (
        classifier.default_pages(project.sheets) if request.pages == "auto" else request.pages
    )
    if not pages:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No pages to extract. The classifier marked no sheet as usable.",
        )

    known = {s.page for s in project.sheets}
    if known and (unknown := sorted(set(pages) - known)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Pages not present in the uploaded drawing set: {unknown}",
        )

    drawings_path = storage.upload_path(project_id, "drawings")
    if drawings_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project has no drawings PDF.")

    started = time.perf_counter()
    building = extractor.extract(Path(drawings_path), sorted(pages), sheets=project.sheets)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    storage.save_building(project_id, building)
    return ExtractResponse(
        project_id=project_id,
        pages=sorted(pages),
        building=building,
        elapsed_ms=elapsed_ms,
    )


@router.get("/{project_id}/building", response_model=Building)
def get_building(project_id: str) -> Building:
    """The most recent extraction. 404 until /extract has been called."""
    _load(project_id)
    building = storage.load_building(project_id)
    if building is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No extraction has been run for this project yet."
        )
    return building


def _store(project_id: str, kind: str, upload: UploadFile):
    if not (upload.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"{kind} must be a PDF, got {upload.filename!r}.",
        )
    return storage.save_upload(project_id, kind, upload.filename or f"{kind}.pdf", upload.file)


def _load(project_id: str) -> Project:
    try:
        return storage.load_project(project_id)
    except storage.ProjectNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
