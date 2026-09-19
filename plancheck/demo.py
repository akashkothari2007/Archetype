"""End-to-end demo: classify for real, remaining engines as stubs."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from plancheck.api import storage
from plancheck.core.settings import reset_settings
from plancheck.engines import (
    agent as agent_engine,
    build_model as model_engine,
    check as check_engine,
    classify as classify_engine,
    extract_rules as rules_engine,
    extract_sheet as extract_engine,
)


def write_sample_drawings(dest: Path) -> Path:
    """Tiny architectural PDF with title-block text classify.py can parse."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    pages = [
        [
            "Drawing No: A.001",
            '1/16" = 1\'-0"',
            "SITE PLAN",
        ],
        [
            "Drawing No: A.202",
            '1/16" = 1\'-0"',
            "TYPICAL FLOOR PLAN (2ND & 3RD)",
            "LEVEL 2",
        ],
        [
            "Drawing No: A.502a",
            '3/16" = 1\'-0"',
            "TYPICAL FLOOR PLAN",
            "LEVEL 2",
        ],
        [
            "Drawing No: A.801",
            '1/4" = 1\'-0"',
            "ENLARGED UNIT PLAN — STUDIO KING",
        ],
        [
            "Drawing No: A.301",
            '1/8" = 1\'-0"',
            "SOUTH ELEVATION",
        ],
        [
            "Drawing No: A.701",
            "GUESTROOM DOOR SCHEDULE",
        ],
        [
            "Drawing No: S.201",
            '1/8" = 1\'-0"',
            "EDGE OF SLAB — LEVEL 2",
        ],
    ]
    for lines in pages:
        page = doc.new_page(width=2384, height=1684)
        y = 80
        for line in lines:
            page.insert_text((72, y), line, fontsize=18)
            y += 28
    dest.write_bytes(doc.tobytes())
    doc.close()
    return dest


def write_sample_standards(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "TownePlace Suites Brand Standards", fontsize=16)
    page.insert_text((72, 110), "Area: 16 m² (175 sq. ft.) minimum", fontsize=12)
    page.insert_text((72, 130), "Corridor Width: minimum 1.5 m (5 ft.)", fontsize=12)
    dest.write_bytes(doc.tobytes())
    doc.close()
    return dest


def run_pipeline(drawings: Path, standards: Path) -> str:
    project = storage.create_project(drawings.stem)
    drawings_path = storage.copy_file(project.project_id, "drawings", drawings)
    standards_path = storage.copy_file(project.project_id, "standards", standards)
    project = storage.add_document(
        project,
        classify_engine.peek_document(drawings_path, "drw-01", "drawings"),
    )
    project = storage.add_document(
        project,
        classify_engine.peek_document(standards_path, "std-01", "standards"),
    )

    project = classify_engine.run(project, storage.drawing_files(project.project_id))
    storage.save_project(project)

    for sheet in project.sheets:
        if not sheet.use:
            continue
        pdf = storage.document_file(project.project_id, sheet.doc_id)
        raster = storage.sheet_raster_path(project.project_id, sheet.sheet_id)
        geom = extract_engine.run(sheet, pdf, raster)
        storage.save_sheet_geometry(project.project_id, geom)
        sheet.geometry_file = f"sheets/{sheet.sheet_id}.json"
    storage.save_project(project)

    geoms = storage.load_all_geometries(project.project_id)
    model = model_engine.run(project, geoms)
    storage.save_model(project.project_id, model)
    project.model_file = "model.json"
    storage.save_project(project)

    rules = rules_engine.run(project, storage.standard_files(project.project_id))
    storage.save_rules(project.project_id, rules)

    mismatches = check_engine.run(model, rules)
    storage.save_mismatches(project.project_id, mismatches)

    edits = agent_engine.run(mismatches, model)
    storage.save_proposed_edits(project.project_id, edits)
    return project.project_id


def main() -> None:
    import os
    import tempfile

    os.environ.setdefault("PLANCHECK_STUB_DELAY_MS", "0")
    reset_settings()

    with tempfile.TemporaryDirectory(prefix="plancheck-demo-") as tmp:
        root = Path(tmp)
        drawings = write_sample_drawings(root / "Sidney_TPS_Arch_sample.pdf")
        standards = write_sample_standards(root / "TownePlace_Standards_sample.pdf")
        project_id = run_pipeline(drawings, standards)
    folder = storage.project_dir(project_id)
    project = storage.load_project(project_id)
    used = [s for s in project.sheets if s.use]
    print(f"project_id: {project_id}")
    print(f"path:       {folder}")
    print(f"sheets:     {len(project.sheets)} classified, {len(used)} use=true")
    for sheet in project.sheets:
        flag = "USE" if sheet.use else "skip"
        print(
            f"  [{flag:4}] p{sheet.page:<3} {sheet.sheet_no or '-':<8} "
            f"{sheet.role:<15} {sheet.scale_text or '-'}"
        )
    print("artifacts:")
    for name in (
        "project.json",
        "model.json",
        "rules.json",
        "mismatches.json",
        "proposed_edits.json",
    ):
        print(f"  {folder / name}")
    print(f"  {folder / 'sheets'} ({len(list((folder / 'sheets').glob('*.json')))} geometry files)")
    print("Serve with: make serve   then open http://127.0.0.1:8000")


if __name__ == "__main__":
    main()
