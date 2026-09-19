from plancheck.api import storage
from plancheck.core.schemas import (
    CheckResult,
    Model,
    Project,
    ProposedEdits,
    Ruleset,
    SheetGeometry,
)
from plancheck.demo import run_pipeline, write_sample_drawings, write_sample_standards
from plancheck.engines.classify import assign_role, parse_levels


def test_assign_role_rules():
    assert assign_role("A.801", "UNIT PLAN", 18.0) == "unit_plan"
    assert assign_role("A.202", "FLOOR PLAN", 4.5) == "floor_plan"
    assert assign_role("A.502a", "FLOOR PLAN", 13.5) == "enlarged_plan"
    assert assign_role("A.301", "ELEVATION", 9.0) == "elevation"
    assert assign_role("A.701", "SCHEDULE", None) == "schedule"
    assert assign_role("S.201", "EDGE OF SLAB", 9.0) == "slab_edge"


def test_parse_levels_from_sheet_titles():
    assert parse_levels("GROUND FLOOR PLAN") == ["1"]
    assert parse_levels("TYPICAL FLOOR PLAN (2nd to 3rd)") == ["2", "3"]
    assert parse_levels("LEVEL 4 FLOOR PLAN") == ["4"]
    assert parse_levels("FLOOR PLAN") == []


def test_stub_pipeline_end_to_end(tmp_path):
    drawings = write_sample_drawings(tmp_path / "drawings.pdf")
    standards = write_sample_standards(tmp_path / "standards.pdf")
    project_id = run_pipeline(drawings, standards)

    project = storage.load_project(project_id)
    assert isinstance(project, Project)
    assert project.sheets
    roles = {s.role for s in project.sheets if s.use}
    assert "unit_plan" in roles
    assert "floor_plan" in roles
    assert "enlarged_plan" in roles
    assert "schedule" in roles
    skipped = [s for s in project.sheets if not s.use]
    assert skipped
    assert all(s.reason for s in skipped)

    geoms = storage.load_all_geometries(project_id)
    assert geoms
    for geom in geoms:
        assert isinstance(geom, SheetGeometry)
        assert geom.coordinate_system.y == "up"
        assert geom.coordinate_system.origin == "bottom-left"

    model = storage.load_model(project_id)
    assert isinstance(model, Model)
    assert model.units == "feet"
    assert model.space_types
    assert model.spaces

    rules = storage.load_rules(project_id)
    assert isinstance(rules, Ruleset)
    assert rules.rules

    mismatches = storage.load_mismatches(project_id)
    assert isinstance(mismatches, CheckResult)
    assert mismatches.mismatches
    assert any(m.severity == "cannot_verify" for m in mismatches.mismatches)

    edits = storage.load_proposed_edits(project_id)
    assert isinstance(edits, ProposedEdits)
    assert edits.proposed_edits
    assert all(e.blocked_by == [] or isinstance(e.blocked_by, list) for e in edits.proposed_edits)
