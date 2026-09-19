"""Environment configuration and per-engine stub/real selection."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PACKAGE_DIR / "data" / "projects"
DEFAULT_ENGINES = (
    "classify:real,extract:real,model:real,rules:real,check:real,agent:stub"
)
ENGINE_NAMES = ("classify", "extract", "model", "rules", "check", "agent")
DEFAULT_ORCHESTRATOR_MODEL = "zai-org/GLM-5.3-Flash"
DEFAULT_SUBAGENT_MODEL = "zai-org/GLM-5.3-Flash"
DEFAULT_GENERATION_MODEL = "zai-org/GLM-5.3-Flash"
DEFAULT_AGENT_BASE_URL = "https://inference.baseten.co/v1"


def _env_file_value(name: str) -> str:
    path = Path(".env")
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PLANCHECK_",
        extra="ignore",
        env_file=".env",
    )

    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    stub_delay_ms: int = Field(default=400)
    engines: str = Field(default=DEFAULT_ENGINES)
    agent_provider: str = "mock"
    agent_api_key: str = ""
    agent_model: str = ""
    agent_base_url: str = DEFAULT_AGENT_BASE_URL
    orchestrator_model: str = DEFAULT_ORCHESTRATOR_MODEL
    subagent_model: str = DEFAULT_SUBAGENT_MODEL
    generation_provider: str = "demo"
    generation_model: str = ""
    log_level: str = "INFO"
    use_enlarged: bool = False
    auto_approve: bool = True
    session_token: str = ""
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"

    def resolved_api_key(self) -> str:
        return (
            self.agent_api_key.strip()
            or os.environ.get("BASETEN_API_KEY", "").strip()
            or _env_file_value("BASETEN_API_KEY")
        )

    def orchestrator_slug(self) -> str:
        return self.orchestrator_model.strip() or self.agent_model.strip() or DEFAULT_ORCHESTRATOR_MODEL

    def subagent_slug(self) -> str:
        return self.subagent_model.strip() or self.agent_model.strip() or DEFAULT_SUBAGENT_MODEL

    def agent_live(self) -> bool:
        return self.agent_provider.strip().lower() in {"baseten", "real"} and bool(
            self.resolved_api_key()
        )

    def generation_slug(self) -> str:
        return (
            self.generation_model.strip()
            or DEFAULT_GENERATION_MODEL
            or self.orchestrator_slug()
        )

    def generation_live(self) -> bool:
        return self.generation_provider.strip().lower() in {
            "baseten",
            "agent",
            "real",
            "live",
            "model",
        } and bool(self.resolved_api_key())

    def engine_modes(self) -> dict[str, str]:
        modes = {name: "stub" for name in ENGINE_NAMES}
        modes["classify"] = "real"
        for pair in self.engines.split(","):
            pair = pair.strip()
            if not pair:
                continue
            if ":" not in pair:
                raise ValueError(
                    f"Invalid PLANCHECK_ENGINES entry {pair!r}; expected name:stub|real"
                )
            name, mode = pair.split(":", 1)
            name, mode = name.strip(), mode.strip().lower()
            if name not in ENGINE_NAMES:
                raise ValueError(f"Unknown engine {name!r}")
            if mode not in {"stub", "real"}:
                raise ValueError(f"Engine mode must be 'stub' or 'real', got {mode!r}")
            modes[name] = mode
        return modes

    def engine_mode(self, name: str) -> str:
        if name not in ENGINE_NAMES:
            raise ValueError(f"Unknown engine {name!r}")
        return self.engine_modes()[name]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Drop the cached settings object (tests mutate env vars)."""
    get_settings.cache_clear()
