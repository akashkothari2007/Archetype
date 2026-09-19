from fastapi.testclient import TestClient

from plancheck.api.main import app
from plancheck.core.settings import reset_settings
from plancheck.mocks.generation import demo_home, demo_rules
from plancheck.services.agent import respond


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


def test_health_reports_baseten_when_live(monkeypatch):
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "baseten")
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    reset_settings()
    payload = TestClient(app).get("/api/desktop/health").json()
    assert payload["agent_provider"] == "baseten"
    assert payload["orchestrator_model"] == "deepseek-ai/DeepSeek-V4-Pro"
    assert payload["subagent_model"] == "zai-org/GLM-5.3-Flash"
