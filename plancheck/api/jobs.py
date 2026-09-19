"""In-process background job runner. Frontend polls GET /api/jobs/{id}."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from plancheck.core.schemas import JobStatus

ProgressFn = Callable[..., None]

_lock = threading.Lock()
_jobs: dict[str, JobStatus] = {}


def get_job(job_id: str) -> JobStatus | None:
    with _lock:
        job = _jobs.get(job_id)
        return job.model_copy() if job else None


def _update(job_id: str, **kwargs: Any) -> None:
    with _lock:
        current = _jobs[job_id]
        _jobs[job_id] = current.model_copy(update=kwargs)


def submit(
    fn: Callable[[ProgressFn], Any],
    message: str = "queued",
) -> str:
    job_id = uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = JobStatus(
            job_id=job_id,
            state="queued",
            progress=0.0,
            message=message,
            error=None,
        )

    def report(**kwargs: Any) -> None:
        _update(job_id, **kwargs)

    def runner() -> None:
        try:
            report(state="running", message=message)
            fn(report)
            latest = get_job(job_id)
            if latest is not None and latest.state != "error":
                report(
                    state="done",
                    progress=1.0,
                    message=latest.message or "done",
                )
        except Exception as exc:  # noqa: BLE001 — surface any engine failure
            report(state="error", error=str(exc), message="failed")

    threading.Thread(target=runner, daemon=True).start()
    return job_id
