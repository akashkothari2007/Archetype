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
    reset_settings()
    yield
    reset_settings()
