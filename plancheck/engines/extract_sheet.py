"""Extract geometry from one PDF page. Scaffold ships the stub only."""

from __future__ import annotations

import argparse
from pathlib import Path

import pymupdf

from plancheck.core.schemas import RasterRef, Sheet, SheetGeometry
from plancheck.engines.base import invoke, load_fixture, not_implemented


def write_placeholder_raster(
    dest: Path, width_pt: float, height_pt: float, label: str
) -> RasterRef:
    """Tiny stand-in PNG so the raster endpoint has something to serve."""
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=width_pt, height=height_pt)
        page.draw_rect(
            page.rect,
            color=(0.85, 0.85, 0.82),
            fill=(0.93, 0.93, 0.90),
        )
        page.insert_text((36, 48), f"PlanCheck stub raster  {label}", fontsize=16)
        pix = page.get_pixmap(dpi=36)
        dest.parent.mkdir(parents=True, exist_ok=True)
        pix.save(dest)
        return RasterRef(
            dpi=36.0,
            file=f"sheets/{dest.name}",
            size_px=[pix.width, pix.height],
        )
    finally:
        doc.close()


def run_real(
    sheet: Sheet, pdf_path: Path, raster_path: Path
) -> SheetGeometry:
    from plancheck.services.pdf_extract import extract
    return extract(sheet, pdf_path, raster_path)


def run_stub(
    sheet: Sheet, pdf_path: Path, raster_path: Path
) -> SheetGeometry:
    geom = load_fixture("sheet_geometry.json", SheetGeometry)
    geom.sheet_id = sheet.sheet_id
    geom.page = sheet.page
    if sheet.scale_pts_per_ft:
        geom.scale_pts_per_ft = sheet.scale_pts_per_ft
    geom.raster = write_placeholder_raster(
        raster_path, geom.size_pt[0], geom.size_pt[1], sheet.sheet_id
    )
    return geom


def run(sheet: Sheet, pdf_path: Path, raster_path: Path) -> SheetGeometry:
    return invoke("extract", sheet, pdf_path, raster_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract geometry for one classified sheet."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--sheet", required=True, help="sheet_id")
    args = parser.parse_args()
    from plancheck.api import storage

    project = storage.load_project(args.project)
    sheet = next(
        (s for s in project.sheets if s.sheet_id == args.sheet), None
    )
    if sheet is None:
        raise SystemExit(f"Unknown sheet {args.sheet}")
    pdf = storage.document_file(args.project, sheet.doc_id)
    raster = storage.sheet_raster_path(args.project, sheet.sheet_id)
    geom = run(sheet, pdf, raster)
    storage.save_sheet_geometry(args.project, geom)
    sheet.geometry_file = f"sheets/{sheet.sheet_id}.json"
    storage.save_project(project)
    print(f"wrote {sheet.geometry_file}")


if __name__ == "__main__":
    main()
