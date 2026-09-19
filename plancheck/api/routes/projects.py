"""Create, list, get projects; override sheet classification."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from plancheck.api import jobs, storage
from plancheck.core.schemas import (
    CreateProjectResponse,
    Project,
    ProjectListItem,
    Sheet,
    SheetPatch,
)
from plancheck.engines import classify as classify_engine

router = APIRouter()


def _require_project(project_id: str) -> Project:
    try:
        return storage.load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects", response_model=CreateProjectResponse)
def create_project(
    drawings: list[UploadFile] = File(default=[]),
    standards: list[UploadFile] = File(default=[]),
) -> CreateProjectResponse:
    if not drawings:
        raise HTTPException(
            status_code=400, detail="At least one drawings PDF is required"
        )
    first_name = Path(drawings[0].filename or "project").stem
    project = storage.create_project(first_name)

    for index, upload in enumerate(drawings, start=1):
        doc_id = f"drw-{index:02d}"
        filename = Path(upload.filename or f"{doc_id}.pdf").name
        path = storage.save_upload(
            project.project_id, "drawings", upload, filename=filename
        )
        document = classify_engine.peek_document(path, doc_id, "drawings")
        project = storage.add_document(project, document)

    for index, upload in enumerate(standards, start=1):
        doc_id = f"std-{index:02d}"
        filename = Path(upload.filename or f"{doc_id}.pdf").name
        path = storage.save_upload(
            project.project_id, "standards", upload, filename=filename
        )
        document = classify_engine.peek_document(path, doc_id, "standards")
        project = storage.add_document(project, document)

    project_id = project.project_id

    def work(report: jobs.ProgressFn) -> None:
        current = storage.load_project(project_id)

        def on_progress(frac: float, message: str) -> None:
            report(progress=frac, message=message)

        result = classify_engine.run(
            current,
            storage.drawing_files(project_id),
            on_progress=on_progress,
        )
        storage.save_project(result)
        report(message=f"Classified {len(result.sheets)} sheets")

    job_id = jobs.submit(work, "classifying drawings")
    return CreateProjectResponse(
        project_id=project.project_id,
        documents=project.documents,
        job_id=job_id,
    )


@router.get("/projects", response_model=list[ProjectListItem])
def list_projects() -> list[ProjectListItem]:
    return storage.list_projects()


@router.get("/projects/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    return _require_project(project_id)


@router.patch(
    "/projects/{project_id}/sheets/{sheet_id}",
    response_model=Sheet,
)
def patch_sheet(project_id: str, sheet_id: str, body: SheetPatch) -> Sheet:
    project = _require_project(project_id)
    sheet = next((s for s in project.sheets if s.sheet_id == sheet_id), None)
    if sheet is None:
        raise HTTPException(status_code=404, detail="Unknown sheet")
    if body.role is not None:
        sheet.role = body.role
    if body.use is not None:
        sheet.use = body.use
        if sheet.use:
            sheet.reason = "User included this sheet."
        else:
            sheet.reason = "User excluded this sheet."
    storage.save_project(project)
    return sheet
