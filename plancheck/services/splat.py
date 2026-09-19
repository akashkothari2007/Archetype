"""TripoSplat image-to-Gaussian overlay (exterior only)."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any

from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings

log = get_logger("plancheck.splat")

FAL_MODEL = "tripo3d/triposplat"


class SplatError(RuntimeError):
    pass


def _reason(status: int, body: str) -> str:
    """fal explains billing and validation failures in the body; show it."""
    detail = body
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            detail = str(parsed.get("detail") or parsed.get("message") or body)
    except ValueError:
        pass
    detail = " ".join(detail.split())[:220]
    if status in {401, 403} and "balance" in detail.lower():
        return f"TripoSplat could not run: {detail}"
    if status in {401, 403}:
        return f"TripoSplat rejected the fal key (HTTP {status}). {detail}"
    return f"TripoSplat request failed (HTTP {status}). {detail}".strip()


def _auth(url: str, key: str) -> str:
    """fal wants `Key`, Baseten wants `Api-Key`, anything else gets a bearer token."""
    if "fal.run" in url:
        return f"Key {key}"
    if "baseten.co" in url:
        return f"Api-Key {key}"
    return f"Bearer {key}"


def _post(url: str, key: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = _auth(url, key)
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        log.warning("splat.http_error status=%s body=%s", exc.code, detail)
        raise SplatError(_reason(exc.code, detail)) from None
    except urllib.error.URLError as exc:
        raise SplatError("Could not reach TripoSplat") from exc
    if not isinstance(payload, dict):
        raise SplatError("TripoSplat returned an unexpected payload")
    return payload


def _get(url: str, key: str, timeout: float) -> dict[str, Any]:
    headers = {}
    if key:
        headers["Authorization"] = _auth(url, key)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        log.warning("splat.status_error status=%s body=%s", exc.code, detail)
        raise SplatError(_reason(exc.code, detail)) from None
    if not isinstance(payload, dict):
        raise SplatError("TripoSplat status was not JSON")
    return payload


def _download(url: str, timeout: float = 120) -> bytes:
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _extract_file(payload: dict[str, Any]) -> bytes:
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    file_info = payload.get("model_mesh") or payload.get("splat") or payload.get("file")
    if isinstance(file_info, dict):
        url = file_info.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return _download(url)
        blob = file_info.get("content") or file_info.get("b64_json") or file_info.get("data")
        if isinstance(blob, str) and blob:
            text = blob.partition(",")[2] if blob.startswith("data:") else blob
            return base64.b64decode(text)
    if isinstance(payload.get("url"), str) and payload["url"].startswith("http"):
        return _download(payload["url"])
    raise SplatError("TripoSplat returned no splat file")


def splat_filename(raw: bytes) -> str:
    if raw[:3] == b"ply" or raw[:4].lower() == b"ply\n":
        return "appearance.ply"
    return "appearance.splat"


def generate_splat(png: bytes, *, timeout: float = 900) -> bytes:
    """Timeout is generous: a self-hosted endpoint may cold start from zero."""
    settings = get_settings()
    key = settings.resolved_splat_api_key()
    if not key and not settings.splat_url.strip():
        raise SplatError(
            "TripoSplat is not configured. Set PLANCHECK_SPLAT_URL for a self-hosted "
            "endpoint, or FAL_KEY to use fal."
        )
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    # Only the documented TripoSplat inputs; fal bills 422s that reach a runner.
    body = {
        "image_url": data_url,
        "num_gaussians": 131072,
        "output_format": "splat",
    }
    custom = settings.splat_url.strip()
    if custom:
        log.info("splat.request custom bytes=%d", len(png))
        return _extract_file(_post(custom, key, {**body, "image": data_url}, timeout))

    log.info("splat.queue bytes=%d", len(png))
    submit = _post(f"https://queue.fal.run/{FAL_MODEL}", key, body, min(timeout, 60))
    try:
        return _extract_file(submit)
    except SplatError:
        pass
    request_id = str(submit.get("request_id") or "")
    status_url = str(submit.get("status_url") or "")
    response_url = str(submit.get("response_url") or "")
    if not status_url and request_id:
        status_url = f"https://queue.fal.run/{FAL_MODEL}/requests/{request_id}/status"
    if not response_url and request_id:
        response_url = f"https://queue.fal.run/{FAL_MODEL}/requests/{request_id}"
    if not status_url:
        raise SplatError("TripoSplat did not return a request id")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _get(status_url, key, 30)
        state = str(status.get("status") or status.get("state") or "").upper()
        log.info("splat.status state=%s", state)
        if state in {"COMPLETED", "OK", "SUCCESS"}:
            result = _get(response_url, key, 60) if response_url else status
            return _extract_file(result)
        if state in {"FAILED", "ERROR", "CANCELLED"}:
            raise SplatError("TripoSplat failed to generate a splat")
        time.sleep(2)
    raise SplatError("TripoSplat timed out")
