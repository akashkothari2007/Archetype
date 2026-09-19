"""Build model.json from extracted sheets. Scaffold ships the stub only."""

from __future__ import annotations

import argparse

from plancheck.core.schemas import Model, Project, SheetGeometry, SpaceType
from plancheck.engines.base import invoke, load_fixture, not_implemented


def _rewrite_source_sheet(types: list[SpaceType], sheet_id: str) -> None:
    for space_type in types:
        space_type.source_sheet = sheet_id
        _rewrite_source_sheet(space_type.children, sheet_id)


def run_real(
    project: Project, geometries: list[SheetGeometry]
) -> Model:
    not_implemented("model")
    raise AssertionError("unreachable")


def run_stub(
    project: Project, geometries: list[SheetGeometry]
) -> Model:
    model = load_fixture("model.json", Model)
    sheet_id = None
    if geometries:
        sheet_id = geometries[0].sheet_id
    elif project.sheets:
        used = next((s for s in project.sheets if s.use), project.sheets[0])
        sheet_id = used.sheet_id
    if sheet_id:
        _rewrite_source_sheet(model.space_types, sheet_id)
        for space in model.spaces:
            space.source_sheet = sheet_id
    return model


def run(project: Project, geometries: list[SheetGeometry]) -> Model:
    return invoke("model", project, geometries)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build building model.json from extracted sheets."
    )
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    from plancheck.api import storage

    project = storage.load_project(args.project)
    geoms = storage.load_all_geometries(args.project)
    model = run(project, geoms)
    storage.save_model(args.project, model)
    project.model_file = "model.json"
    storage.save_project(project)
    print(f"wrote model.json ({len(model.space_types)} space types)")


if __name__ == "__main__":
    main()
