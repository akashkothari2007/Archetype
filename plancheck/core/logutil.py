"""Stdout logging for local runs and `docker compose logs -f backend`.

Use the standard library logger — not print. Uvicorn and Docker both capture
stdout, so INFO/DEBUG lines from ``plancheck.*`` show up in compose logs.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Idempotent. Safe to call from FastAPI startup and from tests."""
    global _CONFIGURED
    from plancheck.core.settings import get_settings

    resolved = (level or get_settings().log_level or "INFO").strip().upper()
    numeric = getattr(logging, resolved, logging.INFO)

    root = logging.getLogger()
    # force=True wins over uvicorn's earlier basicConfig so our format sticks.
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    root.setLevel(numeric)
    for name in (
        "plancheck",
        "plancheck.generation",
        "plancheck.llm",
        "plancheck.agent",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        logging.getLogger(name).setLevel(numeric)

    # Keep HTTP client chatter quiet unless someone opts into DEBUG.
    if numeric > logging.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger("plancheck").info("logging ready level=%s", resolved)


def get_logger(name: str) -> logging.Logger:
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
