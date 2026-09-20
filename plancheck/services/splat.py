"""TripoSplat image-to-Gaussian overlay (exterior only), hosted on Baseten."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings

log = get_logger("plancheck.splat")


class SplatError(RuntimeError):
    pass


def _reason(status: int, body: str) -> str:
    detail = body
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            detail = str(parsed.get("error") or parsed.get("detail") or parsed.get("message") or body)
    except ValueError:
        pass
    detail = " ".join(detail.split())[:220]
    if "payment method" in detail.lower():
        return "Baseten needs a payment method before TripoSplat can start. Add a card in that workspace, activate TripoSplat, then try again."
    if "deactivated" in detail.lower():
        return "TripoSplat is turned off on Baseten. Activate that deployment in the workspace, then try again."
    if status in {401, 403}:
        return f"TripoSplat rejected the Baseten API key (HTTP {status}). {detail}"
    return f"TripoSplat request failed (HTTP {status}). {detail}".strip()


def _auth(url: str, key: str) -> str:
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


def splat_filename(raw: bytes, stem: str = "appearance") -> str:
    ext = "ply" if raw[:3] == b"ply" or raw[:4].lower() == b"ply\n" else "splat"
    return f"{stem}.{ext}"


def generate_splat(png: bytes, *, timeout: float = 900, num_gaussians: int = 131072) -> bytes:
    """Timeout is generous: a self-hosted endpoint may cold start from zero."""
    settings = get_settings()
    url = settings.splat_url.strip()
    key = settings.resolved_splat_api_key()
    if not url or not key:
        raise SplatError(
            "TripoSplat is not configured. Set PLANCHECK_SPLAT_URL and PLANCHECK_SPLAT_API_KEY "
            "for the Baseten deployment (see deploy/triposplat-baseten)."
        )
    data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    body = {
        "image": data_url,
        "image_url": data_url,
        "num_gaussians": num_gaussians,
        "output_format": "splat",
    }
    log.info("splat.request bytes=%d gaussians=%d", len(png), num_gaussians)
    return _extract_file(_post(url, key, body, timeout))
