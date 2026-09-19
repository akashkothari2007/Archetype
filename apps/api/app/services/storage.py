"""Project storage.

One directory per project on local disk. Uploaded PDFs are licensed client
material, so the directory is gitignored and nothing here ever leaves the box.

Deliberately not a database. The unit of work is "a folder with two PDFs and
some JSON in it", which is also exactly what the CLI operates on, so the
server and the scripts can share inputs without a migration.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings
from app.models.building import Building
from app.models.project import Project, UploadedDocument

_CHUNK = 1024 * 1024


class ProjectNotFound(Exception):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"No project with id {project_id!r}")
        self.project_id = project_id


class UploadTooLarge(Exception):
    def __init__(self, limit_bytes: int) -> None:
        super().__init__(f"Upload exceeds the {limit_bytes} byte limit")
        self.limit_bytes = limit_bytes


def new_project_id() -> str:
    return uuid.uuid4().hex[:12]


def project_dir(project_id: str) -> Path:
    return get_settings().data_dir / project_id


def _manifest_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def _building_path(project_id: str) -> Path:
    return project_dir(project_id) / "building.json"


def create_project_dir(project_id: str) -> Path:
    path = project_dir(project_id)
    (path / "uploads").mkdir(parents=True, exist_ok=True)
    return path


def save_upload(project_id: str, kind: str, filename: str, stream: BinaryIO) -> UploadedDocument:
    """Stream an upload to disk, hashing as it goes.

    Streamed rather than read into memory because the real drawing sets are
    tens to hundreds of megabytes and pdfplumber already gets OOM-killed on
    the full file later in the pipeline.
    """
    settings = get_settings()
    dest = project_dir(project_id) / "uploads" / f"{kind}{Path(filename).suffix or '.pdf'}"
    digest = hashlib.sha256()
    size = 0

    with dest.open("wb") as out:
        while chunk := stream.read(_CHUNK):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise UploadTooLarge(settings.max_upload_bytes)
            digest.update(chunk)
            out.write(chunk)

    return UploadedDocument(
        kind=kind,  # type: ignore[arg-type]
        filename=filename,
        bytes=size,
        page_count=None,
        sha256=digest.hexdigest(),
    )


def upload_path(project_id: str, kind: str) -> Path | None:
    uploads = project_dir(project_id) / "uploads"
    if not uploads.is_dir():
        return None
    return next((p for p in sorted(uploads.iterdir()) if p.stem == kind), None)


def save_project(project: Project) -> None:
    _write_json(_manifest_path(project.project_id), project.model_dump(mode="json"))


def load_project(project_id: str) -> Project:
    path = _manifest_path(project_id)
    if not path.is_file():
        raise ProjectNotFound(project_id)
    return Project.model_validate_json(path.read_text())


def save_building(project_id: str, building: Building) -> None:
    _write_json(_building_path(project_id), building.model_dump(mode="json"))


def load_building(project_id: str) -> Building | None:
    path = _building_path(project_id)
    if not path.is_file():
        return None
    return Building.model_validate_json(path.read_text())


def delete_project(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)


def list_projects() -> list[str]:
    data_dir = get_settings().data_dir
    if not data_dir.is_dir():
        return []
    return sorted(p.name for p in data_dir.iterdir() if (p / "project.json").is_file())


def _write_json(path: Path, payload: object) -> None:
    """Write atomically so a crashed run never leaves a half-written artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)


def utcnow() -> datetime:
    return datetime.now(UTC)
