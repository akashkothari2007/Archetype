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


def _post(url: str, key: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Key {key}" if "fal.run" in url else f"Bearer {key}"
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
        raise SplatError(f"TripoSplat request failed (HTTP {exc.code})") from None
    except urllib.error.URLError as exc:
        raise SplatError("Could not reach TripoSplat") from exc
    if not isinstance(payload, dict):
        raise SplatError("TripoSplat returned an unexpected payload")
    return payload


def _get(url: str, key: str, timeout: float) -> dict[str, Any]:
    headers = {}
    if key:
        headers["Authorization"] = f"Key {key}" if "fal.run" in url else f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise SplatError("TripoSplat status was not JSON")
    return payload


def _download(url: str, timeout: float = 120) -> bytes:
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _extract_file(payload: dict[str, Any]) -> bytes:
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


def generate_splat(png: bytes, *, timeout: float = 240) -> bytes:
    settings = get_settings()
    key = settings.resolved_splat_api_key()
    if not key and not settings.splat_url.strip():
        raise SplatError("TripoSplat is not configured")
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    body = {
        "image_url": data_url,
        "num_gaussians": 65536,
        "num_inference_steps": 16,
        "output_format": "splat",
    }
    custom = settings.splat_url.strip()
    if custom:
        payload = _post(custom, key, {**body, "image": data_url, "prompt": "building"}, timeout)
        return _extract_file(payload)

    submit = _post(
        f"https://queue.fal.run/{FAL_MODEL}",
        key,
        body,
        min(timeout, 60),
    )
    status_url = submit.get("status_url") or submit.get("response_url")
    request_id = submit.get("request_id")
    if not status_url and request_id:
        status_url = f"https://queue.fal.run/{FAL_MODEL}/requests/{request_id}/status"
    if not status_url:
        return _extract_file(submit)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _get(status_url, key, 30)
        state = str(status.get("status") or status.get("state") or "").upper()
        if state in {"COMPLETED", "OK", "SUCCESS"}:
            response_url = status.get("response_url") or (
                f"https://queue.fal.run/{FAL_MODEL}/requests/{request_id}" if request_id else None
            )
            result = _get(response_url, key, 60) if response_url else status
            return _extract_file(result)
        if state in {"FAILED", "ERROR", "CANCELLED"}:
            raise SplatError("TripoSplat failed to generate a splat")
        time.sleep(2)
    raise SplatError("TripoSplat timed out")
