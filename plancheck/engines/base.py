"""Engine protocol, fixture loading, and stub/real dispatch.

Each engine exposes ``run_stub`` and ``run_real`` with the same signature.
``PLANCHECK_ENGINES`` selects which one ``run()`` / ``invoke()`` calls.
Swapping a stub for a real engine is an env-var change, nothing else.
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from plancheck.core.settings import get_settings

T = TypeVar("T", bound=BaseModel)

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"

ENGINE_MODULES: dict[str, str] = {
    "classify": "plancheck.engines.classify",
    "extract": "plancheck.engines.extract_sheet",
    "model": "plancheck.engines.build_model",
    "rules": "plancheck.engines.extract_rules",
    "check": "plancheck.engines.check",
    "agent": "plancheck.engines.agent",
}


def load_fixture(name: str, cls: type[T]) -> T:
    """Load a hand-written fixture and validate it against the contract."""
    path = FIXTURE_DIR / name
    return cls.model_validate_json(path.read_text(encoding="utf-8"))


def invoke(engine_name: str, *args: Any, **kwargs: Any) -> Any:
    settings = get_settings()
    mode = settings.engine_mode(engine_name)
    module = importlib.import_module(ENGINE_MODULES[engine_name])
    fn = getattr(module, f"run_{mode}")
    if mode == "stub":
        delay = settings.stub_delay_ms
        if delay > 0:
            time.sleep(delay / 1000.0)
    return fn(*args, **kwargs)


def not_implemented(engine_name: str) -> None:
    raise NotImplementedError(
        f"{engine_name} real engine is not implemented in this scaffold. "
        f"Keep PLANCHECK_ENGINES {engine_name}:stub, or replace "
        f"run_real in {ENGINE_MODULES[engine_name]}."
    )
