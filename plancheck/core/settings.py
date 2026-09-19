"""Environment configuration and per-engine stub/real selection."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PACKAGE_DIR / "data" / "projects"
DEFAULT_ENGINES = (
    "classify:real,extract:stub,model:stub,rules:stub,check:stub,agent:stub"
)
ENGINE_NAMES = ("classify", "extract", "model", "rules", "check", "agent")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PLANCHECK_",
        extra="ignore",
    )

    data_dir: Path = Field(default=DEFAULT_DATA_DIR)
    stub_delay_ms: int = Field(default=400)
    engines: str = Field(default=DEFAULT_ENGINES)

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
