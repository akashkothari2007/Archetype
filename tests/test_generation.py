"""Generation agent: geometry, packing, and the two-call budget. No network."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from plancheck.api.main import app
from plancheck.core.building import DesignBrief
from plancheck.core.settings import reset_settings
from plancheck.generation import GenerationError, generate_from_brief
from plancheck.generation.compiler import CompileError, compile_building
from plancheck.generation.defaults import (
    normalise_use,
    parse_area_sqft,
    parse_floor_count,
    rule_pack,
)
from plancheck.generation.layout import LayoutError, pack_floors
from plancheck.generation.program import BuildingProgram, FloorLayout
from plancheck.mocks.generation import demo_home, demo_rules
from plancheck.services.commands import CommandError, apply_commands, validate_building
from plancheck.services.compliance import check_building
from plancheck.services.repairs import propose_repairs


def space(sid, floor, category, area, **extra):
    return {
        "id": sid,
        "name": sid.replace("_", " ").title(),
        "floor_id": floor,
        "category": category,
        "target_area_sqft": area,
        **extra,
    }


HOME = {
    "building_use": "home",
    "storeys": [
        {"id": "ground", "name": "Ground floor", "height_ft": 10},
        {"id": "upper", "name": "First floor", "height_ft": 10},
    ],
    "spaces": [
        space("stair_g", "ground", "stair", 90),
        space("hall", "ground", "circulation", 140, entry=True),
        space("living", "ground", "living", 320, min_side_ft=12),
        space("kitchen", "ground", "kitchen", 200),
        space("dining", "ground", "dining", 180),
        space("wc", "ground", "bathroom", 50),
        space("stair_u", "upper", "stair", 90),
        space("landing", "upper", "circulation", 120),
        space("bed_1", "upper", "bedroom", 260, min_side_ft=11),
        space("bed_2", "upper", "bedroom", 180, min_side_ft=10),
        space("bed_3", "upper", "bedroom", 170, min_side_ft=10),
        space("bath", "upper", "bathroom", 70),
    ],
}
OFFICE = {
    "building_use": "office",
    "storeys": [{"id": "l1", "name": "Ground floor"}, {"id": "l2", "name": "Level 2"}],
    "spaces": [
        space("core_1", "l1", "stair", 130),
        space("lobby", "l1", "circulation", 320, entry=True),
        space("reception", "l1", "reception", 300),
        space("work_1", "l1", "open_office", 1400),
        space("wc_1", "l1", "bathroom", 120),
        space("core_2", "l2", "stair", 130),
        space("corridor", "l2", "circulation", 300),
        space("meet_a", "l2", "meeting", 260),
        space("meet_b", "l2", "meeting", 240),
        space("work_2", "l2", "open_office", 1300),
        space("wc_2", "l2", "bathroom", 120),
    ],
}
RETAIL = {
    "building_use": "retail",
    "storeys": [{"id": "ground", "name": "Ground floor", "height_ft": 13}],
    "spaces": [
        space("sales", "ground", "sales", 2400, min_side_ft=20, entry=True),
        space("back", "ground", "circulation", 180),
        space("stock", "ground", "stock", 500),
        space("wc", "ground", "bathroom", 90),
        space("manager", "ground", "office", 140),
    ],
}
MIXED = {
    "building_use": "mixed",
    "storeys": [
        {"id": "ground", "name": "Ground floor", "height_ft": 13},
        {"id": "l2", "name": "Level 2"},
        {"id": "l3", "name": "Level 3"},
    ],
    "spaces": [
        space("core_g", "ground", "stair", 130),
        space("lobby", "ground", "lobby", 420, circulation=True, entry=True),
        space("shop", "ground", "retail", 1400, min_side_ft=18),
        space("core_2", "l2", "stair", 130),
        space("corr_2", "l2", "circulation", 300),
        space("work", "l2", "open_office", 1400),
        space("meet", "l2", "meeting", 240),
        space("core_3", "l3", "stair", 130),
        space("corr_3", "l3", "circulation", 300),
        space("living", "l3", "living", 300),
        space("bed", "l3", "bedroom", 180),
        space("kitchen", "l3", "kitchen", 140),
        space("bath", "l3", "bathroom", 110),
    ],
}
ALL_PROGRAMS = {"home": HOME, "office": OFFICE, "retail": RETAIL, "mixed": MIXED}


def build(raw, area=None):
    program = BuildingProgram.model_validate(raw)
    layouts = pack_floors(program, area)
    return program, layouts, compile_building(program, layouts)


# --- brief parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [("Home", "home"), ("a small dental clinic", "office"), ("corner shop", "retail"),
     ("retail below apartments", "mixed"), ("", "home")],
)
def test_use_is_read_from_free_text(text, expected):
    assert normalise_use(text) == expected


@pytest.mark.parametrize("text,expected", [("2", 2), ("three floors", 3), ("G+2", 3), ("", 2)])
def test_floor_count_parsing(text, expected):
    assert parse_floor_count(text) == expected


def test_area_parsing_handles_both_unit_systems():
    assert parse_area_sqft("2,400 sq ft") == 2400
    assert round(parse_area_sqft("220 m2")) == 2368
    assert parse_area_sqft("no number here", default=1234) == 1234


# --- packer -----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ALL_PROGRAMS))
def test_packer_tiles_every_storey_without_overlap(name):
    program = BuildingProgram.model_validate(ALL_PROGRAMS[name])
    layouts = pack_floors(program)
    for storey in program.storeys:
        layout = layouts[storey.id]
        expected = {s.id for s in program.floor_spaces(storey.id)}
        assert {r.space_id for r in layout.rooms} == expected
        # FloorLayout rejects overlaps, so equal areas means the plate is covered.
        assert sum(r.area_sqft for r in layout.rooms) == pytest.approx(
            layout.width_ft * layout.depth_ft, rel=1e-6
        )


@pytest.mark.parametrize("name", ["home", "office", "mixed"])
def test_stair_stacks_on_the_same_footprint(name):
    program = BuildingProgram.model_validate(ALL_PROGRAMS[name])
    layouts = pack_floors(program)
    stairs = {s.id for s in program.spaces if s.stair}
    placed = [
        (r.x1, r.y1, r.x2, r.y2)
        for layout in layouts.values()
        for r in layout.rooms
        if r.space_id in stairs
    ]
    assert len(placed) == len(program.storeys)
    assert len(set(placed)) == 1


def test_every_floor_shares_one_plate():
    program = BuildingProgram.model_validate(MIXED)
    sizes = {(l.width_ft, l.depth_ft) for l in pack_floors(program).values()}
    assert len(sizes) == 1


def test_plate_follows_the_requested_gross_area():
    program = BuildingProgram.model_validate(HOME)
    layout = pack_floors(program, 2400)["ground"]
    assert layout.width_ft * layout.depth_ft == pytest.approx(1200, rel=0.05)


def test_packer_refuses_an_impossible_plate():
    program = BuildingProgram.model_validate(
        {
            "building_use": "office",
            "storeys": [{"id": "g", "name": "G"}],
            "spaces": [space(f"r{i}", "g", "office", 20) for i in range(40)],
        }
    )
    with pytest.raises(LayoutError):
        pack_floors(program)


# --- compiler ---------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(ALL_PROGRAMS))
def test_compiled_geometry_is_valid_and_uniquely_identified(name):
    program, layouts, building = build(ALL_PROGRAMS[name])
    validate_building(building)
    ids = [e.id for group in
           (building.floors, building.vertices, building.walls, building.rooms,
            building.openings, building.objects)
           for e in group]
    assert len(ids) == len(set(ids))
    assert len(building.floors) == len(program.storeys)
    assert len(building.rooms) == len(program.spaces)


def test_envelope_is_locked_and_partitions_are_not():
    _, _, building = build(HOME)
    envelope = [w for w in building.walls if w.locked]
    partitions = [w for w in building.walls if not w.locked]
    assert envelope and partitions
    assert all(w.structural == "loadbearing" for w in envelope)
    assert all(w.structural == "nonstructural" for w in partitions)
    assert all(w.thickness_ft > partitions[0].thickness_ft for w in envelope)


def test_partitions_stay_editable_by_the_agent_and_the_envelope_does_not():
    _, _, building = build(HOME)
    partition = next(w for w in building.walls if not w.locked)
    moved = apply_commands(
        building,
        [{"kind": "offset_partition", "target_id": partition.id, "params": {"distance_ft": 0.5}}],
        actor="agent",
    )
    assert moved is not building
    locked = next(w for w in building.walls if w.locked)
    with pytest.raises(CommandError):
        apply_commands(
            building,
            [{"kind": "offset_partition", "target_id": locked.id, "params": {"distance_ft": 0.5}}],
            actor="agent",
        )


def test_walls_are_shared_between_neighbouring_rooms():
    _, _, building = build(HOME)
    ground = [r for r in building.rooms if r.floor_id == "ground"]
    shared = [
        wall_id
        for wall_id in {w.id for w in building.walls if w.floor_id == "ground"}
        if sum(wall_id in room.wall_ids for room in ground) == 2
    ]
    assert shared, "adjacent rooms must reference one wall, not two coincident ones"


@pytest.mark.parametrize("name", sorted(ALL_PROGRAMS))
def test_every_room_is_reachable_and_openings_fit_their_walls(name):
    _, _, building = build(ALL_PROGRAMS[name])
    assert not building.review, [r.message for r in building.review]
    walls = {w.id: w for w in building.walls}
    vertices = {v.id: v for v in building.vertices}
    for opening in building.openings:
        wall = walls[opening.wall_id]
        start, end = vertices[wall.start_id], vertices[wall.end_id]
        length = ((end.x - start.x) ** 2 + (end.y - start.y) ** 2) ** 0.5
        assert opening.offset_ft >= 0
        assert opening.offset_ft + opening.width_ft <= length + 1e-6
        assert opening.sill_ft + opening.height_ft <= wall.height_ft + 1e-6
    assert any(o.kind == "door" for o in building.openings)
    assert any(o.kind == "window" for o in building.openings)


def test_ground_floor_gets_an_entry_and_stairs_stack_as_objects():
    _, _, building = build(OFFICE)
    stairs = [o for o in building.objects if o.asset_id == "stairs"]
    assert len(stairs) == 2
    assert len({(o.x, o.y) for o in stairs}) == 1
    assert any(o.asset_id == "toilet" for o in building.objects)


def test_compiler_rejects_a_storey_with_no_layout():
    program = BuildingProgram.model_validate(HOME)
    layouts = pack_floors(program)
    layouts.pop("upper")
    with pytest.raises(CompileError):
        compile_building(program, layouts)


# --- contracts --------------------------------------------------------------


def test_overlapping_rectangles_are_rejected_before_compiling():
    with pytest.raises(ValueError, match="overlap"):
        FloorLayout.model_validate(
            {
                "floor_id": "g",
                "width_ft": 30,
                "depth_ft": 20,
                "rooms": [
                    {"space_id": "a", "x1": 0, "y1": 0, "x2": 20, "y2": 20},
                    {"space_id": "b", "x1": 10, "y1": 0, "x2": 30, "y2": 20},
                ],
            }
        )


def test_program_rejects_a_space_on_an_unknown_storey():
    with pytest.raises(ValueError, match="unknown floor_id"):
        BuildingProgram.model_validate(
            {
                "storeys": [{"id": "g", "name": "G"}],
                "spaces": [space("a", "g", "living", 200), space("b", "nope", "living", 200)],
            }
        )


def test_dangling_adjacency_hints_are_dropped_rather_than_fatal():
    program = BuildingProgram.model_validate(
        {
            "storeys": [{"id": "g", "name": "G"}],
            "spaces": [space("a", "g", "living", 200, adjacent_to=["ghost", "a"])],
        }
    )
    assert program.spaces[0].adjacent_to == []


# --- requirements -----------------------------------------------------------


def test_rule_pack_only_ships_requirements_that_can_be_measured():
    _, program_obj, building = build(OFFICE)
    program = BuildingProgram.model_validate(OFFICE)
    rules = rule_pack("office", {s.category for s in program.spaces})
    assert rules
    results = check_building(building, rules)
    assert results
    assert not [r for r in results if r["status"] == "cannot_verify"]


def test_generated_geometry_is_measured_and_repairable():
    # Eight 70 sqft offices sit under the 8 m2 requirement on purpose.
    spaces = [space("core", "g", "stair", 130), space("corr", "g", "circulation", 200, entry=True)]
    spaces += [space(f"o{i}", "g", "office", 70) for i in range(8)]
    program = BuildingProgram.model_validate(
        {"building_use": "office", "storeys": [{"id": "g", "name": "G"}], "spaces": spaces}
    )
    layouts = pack_floors(program, sum(s["target_area_sqft"] for s in spaces))
    building = compile_building(program, layouts)
    rules = rule_pack("office", {s.category for s in program.spaces})
    failures = [c for c in check_building(building, rules) if c["status"] == "fail"]
    assert failures, "undersized offices should be reported, not silently accepted"
    proposal = propose_repairs(building, rules)
    assert proposal["summary"]["proposed"] or proposal["summary"]["blocked"]


# --- demo provider ----------------------------------------------------------


def test_demo_home_still_compiles_through_the_shared_compiler():
    building = demo_home()
    validate_building(building)
    assert len(building.floors) == 2
    assert building == demo_home()
    assert any(w.locked for w in building.walls)
    assert propose_repairs(building, demo_rules())["commands"]


def test_demo_provider_needs_no_key():
    result = generate_from_brief(DesignBrief(name="Demo"))
    assert result.llm_calls == 0
    assert result.program is None
    assert len(result.building.floors) == 2


# --- the agent loop ---------------------------------------------------------


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("PLANCHECK_GENERATION_PROVIDER", "baseten")
    monkeypatch.setenv("PLANCHECK_AGENT_API_KEY", "test-key")
    reset_settings()


def scripted(monkeypatch, *replies):
    """Replace the model with a fixed script and record how often it is called."""
    calls = []

    def fake(role, messages, **kwargs):
        calls.append((role, messages))
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr("plancheck.generation.agent.complete_json", fake)
    return calls


def test_one_model_call_is_enough_on_the_happy_path(live, monkeypatch):
    calls = scripted(monkeypatch, {"program": HOME})
    result = generate_from_brief(DesignBrief(name="Willow", prompt="A calm family house"))
    assert len(calls) == 1
    assert result.llm_calls == 1
    validate_building(result.building)
    assert len(result.building.floors) == 2
    assert result.program["building_use"] == "home"
    assert result.layouts["ground"]["rooms"]


def test_a_broken_program_gets_exactly_one_corrective_turn(live, monkeypatch):
    broken = {"program": {"storeys": [{"id": "g", "name": "G"}], "spaces": []}}
    calls = scripted(monkeypatch, broken, {"program": RETAIL})
    result = generate_from_brief(DesignBrief(name="Shop"))
    assert len(calls) == 2
    assert result.llm_calls == 2
    validate_building(result.building)
    # The corrective turn is told what actually went wrong.
    assert "previous_attempt_failed_because" in calls[1][1][-1]["content"]


def test_the_same_failing_plan_twice_fails_closed(live, monkeypatch):
    calls = scripted(monkeypatch, {"program": HOME})
    monkeypatch.setattr(
        "plancheck.generation.agent.compile_building",
        lambda *a, **k: (_ for _ in ()).throw(CompileError("walls do not close")),
    )
    with pytest.raises(GenerationError, match="same plan again"):
        generate_from_brief(DesignBrief(name="Loop"))
    # The repeat is rejected before it costs a third call or a second pipeline run.
    assert len(calls) == 2


def test_two_different_failures_end_the_job(live, monkeypatch):
    calls = scripted(monkeypatch, {"program": HOME | {"notes": "a"}}, {"program": HOME | {"notes": "b"}})
    monkeypatch.setattr(
        "plancheck.generation.agent.compile_building",
        lambda *a, **k: (_ for _ in ()).throw(CompileError("walls do not close")),
    )
    with pytest.raises(GenerationError, match="walls do not close"):
        generate_from_brief(DesignBrief(name="Broken"))
    assert len(calls) == 2


def test_prose_instead_of_a_program_is_not_retried_forever(live, monkeypatch):
    calls = scripted(monkeypatch, {"message": "Sure! What style would you like?"})
    with pytest.raises(GenerationError):
        generate_from_brief(DesignBrief(name="Chatty"))
    assert len(calls) == 2


def test_the_model_may_fix_one_storey_with_explicit_rectangles(live, monkeypatch):
    fix = {
        "layouts": {
            "ground": {
                "width_ft": 40,
                "depth_ft": 30,
                "rooms": [
                    {"space_id": "stair_g", "x1": 0, "y1": 0, "x2": 10, "y2": 12},
                    {"space_id": "hall", "x1": 10, "y1": 0, "x2": 40, "y2": 12},
                    {"space_id": "living", "x1": 0, "y1": 12, "x2": 16, "y2": 30},
                    {"space_id": "kitchen", "x1": 16, "y1": 12, "x2": 28, "y2": 30},
                    {"space_id": "dining", "x1": 28, "y1": 12, "x2": 36, "y2": 30},
                    {"space_id": "wc", "x1": 36, "y1": 12, "x2": 40, "y2": 30},
                ],
            }
        }
    }
    calls = scripted(monkeypatch, {"program": HOME}, fix)
    attempts = {"n": 0}
    real = pack_floors

    def once(program, area=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise LayoutError("first pack failed")
        return real(program, area)

    monkeypatch.setattr("plancheck.generation.agent.pack_floors", once)
    result = generate_from_brief(DesignBrief(name="Fixed"))
    assert len(calls) == 2
    ground = {r["space_id"]: r for r in result.layouts["ground"]["rooms"]}
    assert (ground["stair_g"]["x2"], ground["stair_g"]["y2"]) == (10, 12)


def test_a_live_provider_without_a_key_refuses_instead_of_faking_it(monkeypatch):
    monkeypatch.setenv("PLANCHECK_GENERATION_PROVIDER", "baseten")
    monkeypatch.setenv("PLANCHECK_AGENT_API_KEY", "")
    reset_settings()
    with pytest.raises(GenerationError, match="no API key"):
        generate_from_brief(DesignBrief(name="No key"))


def test_a_wall_clock_budget_stops_the_job(live, monkeypatch):
    scripted(monkeypatch, {"program": HOME})
    monkeypatch.setattr("plancheck.generation.agent.DEADLINE_S", -1)
    with pytest.raises(GenerationError):
        generate_from_brief(DesignBrief(name="Slow"))


def test_progress_is_reported_in_order(live, monkeypatch):
    scripted(monkeypatch, {"program": OFFICE})
    seen = []
    generate_from_brief(
        DesignBrief(name="Studio", building_use="Office"),
        lambda **kw: seen.append((kw.get("phase"), kw.get("progress"))),
    )
    phases = [p for p, _ in seen]
    assert phases[0] == "analyzing"
    assert "planning" in phases and "validating" in phases
    assert [p for _, p in seen] == sorted(p for _, p in seen)


# --- API --------------------------------------------------------------------


def run_generate(client, brief):
    response = client.post("/api/desktop/generate", json=brief)
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(200):
        job = client.get("/api/desktop/jobs/" + job_id).json()
        if job["state"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_generate_endpoint_uses_the_agent_and_saves_a_real_plan(live, monkeypatch, tmp_path):
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path))
    reset_settings()
    scripted(monkeypatch, {"program": OFFICE})
    client = TestClient(app)
    job = run_generate(client, {"name": "Studio", "building_use": "Office", "prompt": "Two floors"})
    assert job["state"] == "done", job

    project = client.get("/api/desktop/projects/" + job["result"]["project_id"]).json()
    assert len(project["building"]["floors"]) == 2
    assert project["brief"]["prompt"] == "Two floors"
    assert project["checks"]
    # Not the demo house.
    assert {r["name"] for r in project["building"]["rooms"]} != {
        r.name for r in demo_home().rooms
    }
    audit = json.loads(
        (tmp_path / job["result"]["project_id"] / "program.json").read_text(encoding="utf8")
    )
    assert audit["llm_calls"] == 1
    assert audit["program"]["building_use"] == "office"


def test_generate_endpoint_reports_the_failure_and_writes_nothing(live, monkeypatch, tmp_path):
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path))
    reset_settings()
    scripted(monkeypatch, {"message": "I need more detail"})
    client = TestClient(app)
    job = run_generate(client, {"name": "Doomed"})
    assert job["state"] == "error"
    assert job["result"] is None
    assert client.get("/api/desktop/projects").json() == []


def test_health_reports_the_generation_provider(live):
    payload = TestClient(app).get("/api/desktop/health").json()
    assert payload["generation_provider"] == "baseten"
