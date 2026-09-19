from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLANCHECK_", env_file=".env", extra="ignore")

    #: Uploaded drawings live here. Gitignored — this is licensed client material.
    data_dir: Path = API_ROOT / "var" / "projects"

    #: Reject uploads above this size. The ID drawing sets run to 226MB.
    max_upload_bytes: int = 300 * 1024 * 1024

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
