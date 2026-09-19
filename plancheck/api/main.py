"""FastAPI app. CORS is open for local development."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from plancheck.api.routes.desktop import router as desktop_router
from plancheck.services.repository import RevisionConflict
from plancheck.core.settings import get_settings
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from plancheck.api import jobs
from plancheck.api.routes.pipeline import router as pipeline_router
from plancheck.api.routes.projects import router as projects_router
from plancheck.core.schemas import JobStatus

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="PlanCheck", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins.split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(desktop_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job


@app.exception_handler(RevisionConflict)
async def revision_error(request: Request,exc: RevisionConflict):
    return JSONResponse(status_code=409,content={"detail":str(exc)})

@app.exception_handler(ValueError)
async def value_error(request: Request,exc: ValueError):
    return JSONResponse(status_code=422,content={"detail":str(exc)})

@app.exception_handler(FileNotFoundError)
async def file_error(request: Request,exc: FileNotFoundError):
    return JSONResponse(status_code=404,content={"detail":str(exc)})

app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
