"""Filesystem store: data/projects/<project_id>/ — no database."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from pydantic import BaseModel

from plancheck.core.schemas import (
    CheckResult,
    Document,
    Model,
    Project,
    ProjectListItem,
    ProposedEdits,
    Ruleset,
    SheetGeometry,
)
from plancheck.core.settings import get_settings


def data_dir() -> Path:
    path = get_settings().data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(project_id: str) -> Path:
    return data_dir() / project_id


def project_json_path(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def uploads_dir(project_id: str, slot: str) -> Path:
    return project_dir(project_id) / "uploads" / slot


def sheets_dir(project_id: str) -> Path:
    return project_dir(project_id) / "sheets"


def sheet_json_path(project_id: str, sheet_id: str) -> Path:
    return sheets_dir(project_id) / f"{sheet_id}.json"


def sheet_raster_path(project_id: str, sheet_id: str) -> Path:
    return sheets_dir(project_id) / f"{sheet_id}.raster.png"


def model_path(project_id: str) -> Path:
    return project_dir(project_id) / "model.json"


def rules_path(project_id: str) -> Path:
    return project_dir(project_id) / "rules.json"


def mismatches_path(project_id: str) -> Path:
    return project_dir(project_id) / "mismatches.json"


def proposed_edits_path(project_id: str) -> Path:
    return project_dir(project_id) / "proposed_edits.json"


def write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def new_project_id() -> str:
    return "pc-" + uuid.uuid4().hex[:10]


def create_project(name: str) -> Project:
    project_id = new_project_id()
    project = Project(
        project_id=project_id,
        name=name,
        created_at=datetime.now(timezone.utc).isoformat(),
        units="ft",
        documents=[],
        sheets=[],
        model_file=None,
    )
    uploads_dir(project_id, "drawings").mkdir(parents=True, exist_ok=True)
    uploads_dir(project_id, "standards").mkdir(parents=True, exist_ok=True)
    sheets_dir(project_id).mkdir(parents=True, exist_ok=True)
    save_project(project)
    return project


def save_project(project: Project) -> None:
    write_model(project_json_path(project.project_id), project)


def load_project(project_id: str) -> Project:
    path = project_json_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Unknown project {project_id}")
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def list_projects() -> list[ProjectListItem]:
    items: list[ProjectListItem] = []
    if not data_dir().exists():
        return items
    for child in sorted(data_dir().iterdir()):
        path = child / "project.json"
        if not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        items.append(
            ProjectListItem(
                project_id=raw["project_id"],
                name=raw.get("name", ""),
                created_at=raw.get("created_at", ""),
                sheet_count=len(raw.get("sheets") or []),
                document_count=len(raw.get("documents") or []),
            )
        )
    return items


def save_upload(
    project_id: str, slot: str, upload: UploadFile, filename: str | None = None
) -> Path:
    name = filename or Path(upload.filename or "upload.pdf").name
    dest = uploads_dir(project_id, slot) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        shutil.copyfileobj(upload.file, out)
    return dest


def copy_file(project_id: str, slot: str, src: Path) -> Path:
    dest = uploads_dir(project_id, slot) / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def document_file(project_id: str, doc_id: str) -> Path:
    project = load_project(project_id)
    doc = next((d for d in project.documents if d.doc_id == doc_id), None)
    if doc is None:
        raise FileNotFoundError(f"Unknown document {doc_id}")
    path = uploads_dir(project_id, doc.slot) / doc.filename
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def drawing_files(project_id: str) -> dict[str, Path]:
    project = load_project(project_id)
    return {
        d.doc_id: uploads_dir(project_id, "drawings") / d.filename
        for d in project.documents
        if d.slot == "drawings"
    }


def standard_files(project_id: str) -> list[Path]:
    project = load_project(project_id)
    return [
        uploads_dir(project_id, "standards") / d.filename
        for d in project.documents
        if d.slot == "standards"
    ]


def save_sheet_geometry(project_id: str, geom: SheetGeometry) -> None:
    write_model(sheet_json_path(project_id, geom.sheet_id), geom)


def load_sheet_geometry(project_id: str, sheet_id: str) -> SheetGeometry:
    path = sheet_json_path(project_id, sheet_id)
    if not path.exists():
        raise FileNotFoundError(f"No geometry for sheet {sheet_id}")
    return SheetGeometry.model_validate_json(path.read_text(encoding="utf-8"))


def load_all_geometries(project_id: str) -> list[SheetGeometry]:
    folder = sheets_dir(project_id)
    if not folder.exists():
        return []
    geoms: list[SheetGeometry] = []
    for path in sorted(folder.glob("*.json")):
        geoms.append(
            SheetGeometry.model_validate_json(path.read_text(encoding="utf-8"))
        )
    return geoms


def save_model(project_id: str, model: Model) -> None:
    write_model(model_path(project_id), model)


def load_model(project_id: str) -> Model:
    path = model_path(project_id)
    if not path.exists():
        raise FileNotFoundError("model.json not built yet")
    return Model.model_validate_json(path.read_text(encoding="utf-8"))


def save_rules(project_id: str, rules: Ruleset) -> None:
    write_model(rules_path(project_id), rules)


def load_rules(project_id: str) -> Ruleset:
    path = rules_path(project_id)
    if not path.exists():
        raise FileNotFoundError("rules.json not built yet")
    return Ruleset.model_validate_json(path.read_text(encoding="utf-8"))


def save_mismatches(project_id: str, result: CheckResult) -> None:
    write_model(mismatches_path(project_id), result)


def load_mismatches(project_id: str) -> CheckResult:
    path = mismatches_path(project_id)
    if not path.exists():
        raise FileNotFoundError("mismatches.json not built yet")
    return CheckResult.model_validate_json(path.read_text(encoding="utf-8"))


def save_proposed_edits(project_id: str, edits: ProposedEdits) -> None:
    write_model(proposed_edits_path(project_id), edits)


def load_proposed_edits(project_id: str) -> ProposedEdits:
    path = proposed_edits_path(project_id)
    if not path.exists():
        raise FileNotFoundError("proposed_edits.json not built yet")
    return ProposedEdits.model_validate_json(path.read_text(encoding="utf-8"))


def add_document(project: Project, document: Document) -> Project:
    documents = [d for d in project.documents if d.doc_id != document.doc_id]
    documents.append(document)
    updated = project.model_copy(update={"documents": documents})
    save_project(updated)
    return updated
