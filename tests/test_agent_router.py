import pytest
from fastapi.testclient import TestClient

from plancheck.api.main import app
from plancheck.core.building import Building, BuildingWall, Floor, Room, Vertex
from plancheck.core.settings import (
    DEFAULT_ORCHESTRATOR_MODEL,
    DEFAULT_SUBAGENT_MODEL,
    reset_settings,
)
from plancheck.mocks.generation import demo_home, demo_rules
from plancheck.services.agent import _scoped_brief, host_intent, respond
from plancheck.services.commands import CommandError, apply_commands
from plancheck.services.llm import LLMError

HALLWAY_PROMPT = (
    "can you widen the hallway on floor 2 and adjust other sizes of rooms accordingly to fit in the same size"
)
KITCHEN_PROMPT = "enlarge the kitchen toward the living room"


def _assert_design_edit(result):
    assert result.get("intent") in {"geometry", "finish"}
    assert result["actor"] == "agent"
    assert result["commands"], result
    assert result["commands"][0]["kind"] in {"offset_partition", "move_wall", "update_wall"}
    message = result["message"].lower()
    assert "0 proposed" not in message
    assert "no repairs" not in message


def test_mock_fallback_without_key(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "")
    monkeypatch.setenv("PLANCHECK_AGENT_API_KEY", "")
    monkeypatch.setattr("plancheck.core.settings._env_file_value", lambda name: "")
    reset_settings()
    result = respond(demo_home(), demo_rules(), "Set evening lighting")
    assert result["commands"][0]["kind"] == "set_environment"


def test_orchestrator_delegates_to_subagent(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()
    building = demo_home()
    selected = building.rooms[0].id
    calls = []

    def fake_complete(role, messages):
        calls.append(role)
        if role == "orchestrator":
            return {
                "intent": "edit",
                "message": "Updating the finish",
                "tasks": [{"id": "t1", "worker": "material", "instruction": "oak floor", "target_ids": [selected]}],
            }
        return {
            "commands": [{"kind": "set_material", "target_id": selected, "params": {"material": "oak"}}],
            "message": "Oak for the selected room.",
            "blocked": [],
        }

    monkeypatch.setattr("plancheck.services.agent.complete_json", fake_complete)
    result = respond(building, demo_rules(), "Make this oak", selected_ids=[selected])
    assert calls == ["orchestrator", "subagent"]
    assert result["commands"] == [{"kind": "set_material", "target_id": selected, "params": {"material": "oak"}}]
    assert "Oak" in result["message"]
    assert result["actor"] == "agent"


def test_health_reports_baseten_when_live(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()
    payload = TestClient(app).get("/api/desktop/health").json()
    assert payload["agent_provider"] == "baseten"
    assert payload["orchestrator_model"] == DEFAULT_ORCHESTRATOR_MODEL
    assert payload["subagent_model"] == DEFAULT_SUBAGENT_MODEL


def test_host_routes_hallway_to_geometry():
    assert host_intent(HALLWAY_PROMPT) == "geometry"
    assert host_intent(KITCHEN_PROMPT) == "geometry"
    assert host_intent("fix the failed area checks") == "repair"


def test_widen_hallway_floor_2_mock():
    reset_settings()
    building = demo_home()
    landing = next(room for room in building.rooms if room.floor_id == "upper" and room.category == "circulation")
    result = respond(building, demo_rules(), HALLWAY_PROMPT, floor_id="ground")
    _assert_design_edit(result)
    command = result["commands"][0]
    assert command["kind"] == "offset_partition"
    assert command["target_id"] == "upper-w11"
    assert command["target_id"] in landing.wall_ids
    assert command["params"]["dx"] == 2
    wall = next(item for item in building.walls if item.id == command["target_id"])
    assert wall.floor_id == "upper"
    assert not wall.locked
    assert wall.structural == "nonstructural"
    apply_commands(demo_home(), result["commands"], actor="agent")


def test_move_wall_upper_w11_fails_offset_partition_succeeds():
    building = demo_home()
    with pytest.raises(CommandError, match="locked|not reviewed nonstructural"):
        apply_commands(
            building,
            [{"kind": "move_wall", "target_id": "upper-w11", "params": {"dx": 2, "dy": 0}}],
            actor="agent",
        )
    moved = apply_commands(
        building,
        [{"kind": "offset_partition", "target_id": "upper-w11", "params": {"dx": 2, "dy": 0}}],
        actor="agent",
    )
    assert moved is not building
    landing = next(room for room in moved.rooms if room.floor_id == "upper" and room.category == "circulation")
    xs = [pt[0] for pt in landing.polygon]
    assert max(xs) > 26


def test_enlarge_kitchen_toward_living_mock():
    reset_settings()
    result = respond(demo_home(), demo_rules(), KITCHEN_PROMPT)
    _assert_design_edit(result)
    apply_commands(demo_home(), result["commands"], actor="agent")


def test_brief_includes_mentioned_floor_walls():
    building = demo_home()
    brief = _scoped_brief(building, demo_rules(), [], HALLWAY_PROMPT, floor_id="ground")
    assert "upper" in brief["active_floor_ids"]
    assert "ground" not in brief["active_floor_ids"]
    rooms = brief["rooms"]
    assert any(room["floor_id"] == "upper" for room in rooms)
    assert all(room["floor_id"] == "upper" for room in rooms)
    assert any(room["category"] == "circulation" and room["floor_id"] == "upper" for room in rooms)
    assert any(room.get("area_sqft", 0) > 0 for room in rooms)
    walls = brief["walls"]
    assert walls
    assert all("start" in wall and "end" in wall for wall in walls)
    assert any(wall["floor_id"] == "upper" and wall.get("length_ft") for wall in walls)
    w11 = next(wall for wall in walls if wall["id"] == "upper-w11")
    assert w11["locked"] is False
    assert w11["shared_locked"] is True
    assert "upper-w7" in w11["adjacent_locked_ids"]


def test_orchestrator_repair_override_still_emits_geometry(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()
    building = demo_home()
    landing = next(room for room in building.rooms if room.floor_id == "upper" and room.category == "circulation")
    wall_id = next(
        wall.id
        for wall in building.walls
        if wall.id in landing.wall_ids and not wall.locked and wall.structural == "nonstructural"
    )

    def fake_complete(role, messages):
        if role == "orchestrator":
            return {
                "intent": "repair",
                "message": "No repairs to review: 0 proposed and 0 blocked.",
                "tasks": [{"id": "t1", "worker": "repair", "instruction": "fix", "target_ids": []}],
            }
        return {
            "commands": [{"kind": "offset_partition", "target_id": wall_id, "params": {"dx": 2, "dy": 0}}],
            "message": "Widened the landing.",
            "blocked": [],
        }

    monkeypatch.setattr("plancheck.services.agent.complete_json", fake_complete)
    result = respond(building, demo_rules(), HALLWAY_PROMPT, floor_id="ground")
    _assert_design_edit(result)
    assert result["intent"] == "geometry"


def test_geometry_worker_dry_run_offset(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()
    building = demo_home()

    def fake_complete(role, messages, **_kwargs):
        if role == "orchestrator":
            return {
                "intent": "geometry",
                "message": "Widening the hallway",
                "tasks": [{"id": "g1", "worker": "geometry", "instruction": HALLWAY_PROMPT, "target_ids": []}],
            }
        return {
            "commands": [{"kind": "offset_partition", "target_id": "upper-w11", "params": {"dx": 2, "dy": 0}}],
            "message": "Widened the circulation on floor 2.",
            "blocked": [],
        }

    monkeypatch.setattr("plancheck.services.agent.complete_json", fake_complete)
    result = respond(building, demo_rules(), HALLWAY_PROMPT)
    _assert_design_edit(result)
    assert result["commands"][0]["kind"] == "offset_partition"
    apply_commands(building, result["commands"], actor="agent")


def test_loadbearing_target_is_blocked():
    building = Building(
        floors=[Floor(id="f2", name="Floor 2", elevation_ft=10)],
        vertices=[
            Vertex(id="a", floor_id="f2", x=0, y=0),
            Vertex(id="b", floor_id="f2", x=12, y=0),
            Vertex(id="c", floor_id="f2", x=12, y=4),
            Vertex(id="d", floor_id="f2", x=0, y=4),
        ],
        walls=[
            BuildingWall(id="w1", floor_id="f2", start_id="a", end_id="b", structural="loadbearing", locked=True),
            BuildingWall(id="w2", floor_id="f2", start_id="b", end_id="c", structural="loadbearing", locked=True),
            BuildingWall(id="w3", floor_id="f2", start_id="c", end_id="d", structural="loadbearing", locked=True),
            BuildingWall(id="w4", floor_id="f2", start_id="d", end_id="a", structural="loadbearing", locked=True),
        ],
        rooms=[
            Room(
                id="hall",
                floor_id="f2",
                name="Hallway",
                category="circulation",
                polygon=[(0, 0), (12, 0), (12, 4), (0, 4)],
                wall_ids=["w1", "w2", "w3", "w4"],
            )
        ],
    )
    result = respond(building, [], HALLWAY_PROMPT, floor_id="f2")
    assert result["intent"] == "geometry"
    assert result["commands"] == []
    assert result["blocked"]
    message = result["message"].lower()
    assert "0 proposed" not in message
    assert "no repairs" not in message
    assert "locked" in message or "loadbearing" in message


def test_appear_returns_prompt_without_commands(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()

    def fake_complete(role, messages):
        if role == "orchestrator":
            return {
                "intent": "appear",
                "message": "Restyling the exterior",
                "tasks": [{"id": "a1", "worker": "appear", "instruction": "warm brick", "target_ids": []}],
            }
        return {
            "commands": [],
            "appearance_prompt": "warm victorian brick",
            "message": "Prepared a photoreal exterior restyle.",
            "blocked": [],
        }

    monkeypatch.setattr("plancheck.services.agent.complete_json", fake_complete)
    result = respond(demo_home(), demo_rules(), "Make the exterior warm brick")
    assert result["intent"] == "appear"
    assert result["commands"] == []
    assert result.get("appearance_prompt")
    assert "warm" in result["appearance_prompt"].lower() or "brick" in result["appearance_prompt"].lower()


def test_sanitizer_rewrites_move_wall_shared_locked(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()
    building = demo_home()

    def fake_complete(role, messages, **_kwargs):
        if role == "orchestrator":
            return {
                "intent": "geometry",
                "message": "Widening the hallway",
                "tasks": [{"id": "g1", "worker": "geometry", "instruction": HALLWAY_PROMPT, "target_ids": []}],
            }
        return {
            "commands": [{"kind": "move_wall", "target_id": "upper-w11", "params": {"dx": 2, "dy": 0}}],
            "message": "Moved the landing wall.",
            "blocked": [],
        }

    monkeypatch.setattr("plancheck.services.agent.complete_json", fake_complete)
    result = respond(building, demo_rules(), HALLWAY_PROMPT)
    _assert_design_edit(result)
    assert result["commands"][0]["kind"] == "offset_partition"
    assert result["commands"][0]["target_id"] == "upper-w11"
    apply_commands(demo_home(), result["commands"], actor="agent")


def test_retry_empty_json_does_not_use_keyword_mock(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()
    building = demo_home()
    calls = []

    def fake_complete(role, messages, **_kwargs):
        calls.append(role)
        if role == "orchestrator":
            return {
                "intent": "geometry",
                "message": "Widening the hallway",
                "tasks": [{"id": "g1", "worker": "geometry", "instruction": HALLWAY_PROMPT, "target_ids": []}],
            }
        if calls.count("subagent") == 1:
            return {
                "commands": [{"kind": "offset_partition", "target_id": "upper-w11", "params": {"dx": 0, "dy": 2}}],
                "message": "Tried an envelope-drifting offset.",
                "blocked": [],
            }
        raise LLMError("Model reply was not JSON")

    monkeypatch.setattr("plancheck.services.agent.complete_json", fake_complete)
    result = respond(building, demo_rules(), HALLWAY_PROMPT)
    assert result["intent"] == "geometry"
    assert result["commands"] == []
    assert result["blocked"]
    assert not any(str(item.get("target_id") or "").startswith("ground") for item in result["blocked"])
    reasons = " ".join(str(item.get("reason") or "") for item in result["blocked"]).lower()
    assert "locked" in reasons or "upper-w7" in reasons
    assert calls.count("subagent") >= 2
