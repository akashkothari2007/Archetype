import os

import pytest

from plancheck.core.settings import reset_settings


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("PLANCHECK_STUB_DELAY_MS", "0")
    monkeypatch.setenv(
        "PLANCHECK_ENGINES",
        "classify:real,extract:stub,model:stub,rules:stub,check:stub,agent:stub",
    )
    monkeypatch.setenv("PLANCHECK_AGENT_PROVIDER", "mock")
    monkeypatch.setenv("PLANCHECK_GENERATION_PROVIDER", "demo")
    monkeypatch.setenv("PLANCHECK_AGENT_API_KEY", "")
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    # A developer's real .env must never make the suite call a model.
    monkeypatch.setattr("plancheck.core.settings._env_file_value", lambda name: "")
    reset_settings()
    yield
    reset_settings()
