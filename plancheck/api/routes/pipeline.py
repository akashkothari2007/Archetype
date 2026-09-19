"""Extract, model, rules, check, agent endpoints. Long work returns a job_id."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from plancheck.api import jobs, storage
from plancheck.core.schemas import (
    CheckResult,
    ExtractRequest,
    Model,
    Project,
    ProposedEdits,
    Ruleset,
    SheetGeometry,
)
from plancheck.engines import agent as agent_engine
from plancheck.engines import build_model as model_engine
from plancheck.engines import check as check_engine
from plancheck.engines import extract_rules as rules_engine
from plancheck.engines import extract_sheet as extract_engine

router = APIRouter()


def _require_project(project_id: str) -> Project:
    try:
        return storage.load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/extract")
def extract(project_id: str, body: ExtractRequest) -> dict[str, str]:
    project = _require_project(project_id)
    if body.pages == "auto":
        page_set = {s.page for s in project.sheets if s.use}
    else:
        page_set = set(body.pages)
    selected_ids = [
        s.sheet_id for s in project.sheets if s.page in page_set
    ]
    if not selected_ids:
        raise HTTPException(status_code=400, detail="No sheets to extract")

    def work(report: jobs.ProgressFn) -> None:
        proj = storage.load_project(project_id)
        wanted = set(selected_ids)
        targets = [s for s in proj.sheets if s.sheet_id in wanted]
        n = len(targets)
        for index, sheet in enumerate(targets, start=1):
            pdf = storage.document_file(project_id, sheet.doc_id)
            raster = storage.sheet_raster_path(project_id, sheet.sheet_id)
            geom = extract_engine.run(sheet, pdf, raster)
            storage.save_sheet_geometry(project_id, geom)
            sheet.geometry_file = f"sheets/{sheet.sheet_id}.json"
            report(
                progress=index / n,
                message=f"Extracted {sheet.sheet_id} ({index}/{n})",
            )
        storage.save_project(proj)

    job_id = jobs.submit(work, "extracting sheets")
    return {"job_id": job_id}


@router.get(
    "/projects/{project_id}/sheets/{sheet_id}",
    response_model=SheetGeometry,
)
def get_sheet(project_id: str, sheet_id: str) -> SheetGeometry:
    _require_project(project_id)
    try:
        return storage.load_sheet_geometry(project_id, sheet_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/sheets/{sheet_id}/raster.png")
def get_raster(project_id: str, sheet_id: str) -> FileResponse:
    _require_project(project_id)
    path = storage.sheet_raster_path(project_id, sheet_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No raster for this sheet")
    return FileResponse(path, media_type="image/png")


@router.post("/projects/{project_id}/model")
def post_model(project_id: str) -> dict[str, str]:
    _require_project(project_id)

    def work(report: jobs.ProgressFn) -> None:
        report(progress=0.1, message="Loading sheet geometry")
        proj = storage.load_project(project_id)
        geoms = storage.load_all_geometries(project_id)
        if not geoms:
            raise RuntimeError("Extract sheets before building the model")
        model = model_engine.run(proj, geoms)
        storage.save_model(project_id, model)
        proj.model_file = "model.json"
        storage.save_project(proj)
        report(progress=1.0, message="Wrote model.json")

    return {"job_id": jobs.submit(work, "building model")}


@router.get("/projects/{project_id}/model", response_model=Model)
def get_model(project_id: str) -> Model:
    _require_project(project_id)
    try:
        return storage.load_model(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/rules")
def post_rules(project_id: str) -> dict[str, str]:
    _require_project(project_id)

    def work(report: jobs.ProgressFn) -> None:
        proj = storage.load_project(project_id)
        report(progress=0.2, message="Reading standards PDFs")
        ruleset = rules_engine.run(proj, storage.standard_files(project_id))
        storage.save_rules(project_id, ruleset)
        report(progress=1.0, message=f"Wrote {len(ruleset.rules)} rules")

    return {"job_id": jobs.submit(work, "extracting rules")}


@router.get("/projects/{project_id}/rules", response_model=Ruleset)
def get_rules(project_id: str) -> Ruleset:
    _require_project(project_id)
    try:
        return storage.load_rules(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/check")
def post_check(project_id: str) -> dict[str, str]:
    _require_project(project_id)

    def work(report: jobs.ProgressFn) -> None:
        report(progress=0.2, message="Loading model and rules")
        model = storage.load_model(project_id)
        rules = storage.load_rules(project_id)
        result = check_engine.run(model, rules)
        storage.save_mismatches(project_id, result)
        report(
            progress=1.0,
            message=f"Wrote {len(result.mismatches)} mismatches",
        )

    return {"job_id": jobs.submit(work, "checking compliance")}


@router.get("/projects/{project_id}/mismatches", response_model=CheckResult)
def get_mismatches(project_id: str) -> CheckResult:
    _require_project(project_id)
    try:
        return storage.load_mismatches(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/agent")
def post_agent(project_id: str) -> dict[str, str]:
    _require_project(project_id)

    def work(report: jobs.ProgressFn) -> None:
        mismatches = storage.load_mismatches(project_id)
        model = storage.load_model(project_id)
        edits = agent_engine.run(mismatches, model)
        storage.save_proposed_edits(project_id, edits)
        report(
            progress=1.0,
            message=f"Wrote {len(edits.proposed_edits)} proposed edits",
        )

    return {"job_id": jobs.submit(work, "proposing edits")}


@router.get(
    "/projects/{project_id}/proposed-edits",
    response_model=ProposedEdits,
)
def get_proposed_edits(project_id: str) -> ProposedEdits:
    _require_project(project_id)
    try:
        return storage.load_proposed_edits(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
