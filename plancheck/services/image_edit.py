"""FLUX.2 image edit on a dedicated Baseten deployment."""

from __future__ import annotations

import base64
import io
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from PIL import Image

from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings

log = get_logger("plancheck.image_edit")

SCENE_PROMPT = (
    "Edit this isometric massing into a photograph of the same building, same camera. "
    "Keep the exact footprint, roof outline, window and door openings, and facing. "
    "The building must fill the frame at full architectural scale — a real house, not a toy, "
    "miniature, tabletop model, or diorama. Do not add other buildings, cars, people, or trees. "
    "Do not invent a landscape, lawn, or table around it. Replace placeholder shading with "
    "crisp materials and construction detail: brick, mortar, flashing, eaves, glass, wear. "
    "Pure black (#000000) everywhere outside the building."
)

FURNITURE_PROMPT = (
    "Turn this color sketch into a photoreal studio photograph of one piece of furniture. "
    "Keep the silhouette, proportions, and colors of the drawing. "
    "The furniture is a real, full-scale manufactured piece, not a toy, miniature, illustration, or CAD massing. "
    "Center it, fully visible, three-quarter view, standing upright. "
    "Pure black (#000000) background. No room, walls, floor plane, people, plants, or extra objects. "
    "Tight contact shadow only. Photoreal materials, joinery, fabric, and wear."
)


def guide_prompt(brief: Any = None, extra: str = "") -> str:
    """Flux instruction: measured massing + the project's brief + optional user style."""
    parts = [SCENE_PROMPT]
    use = str(getattr(brief, "building_use", "") or "").strip()
    style = str(getattr(brief, "style", "") or "").strip()
    floors = str(getattr(brief, "floors", "") or "").strip()
    direction = str(getattr(brief, "prompt", "") or "").strip()
    if use:
        parts.append(f"This {use.lower()} should read as a finished building of that type.")
    if floors:
        parts.append(f"Keep {floors} storeys and this silhouette.")
    if style:
        parts.append(f"Finish: {style}.")
    if direction:
        parts.append(f"Architect's direction: {direction}")
    extra = extra.strip()
    if extra and extra not in SCENE_PROMPT:
        parts.append(f"User request: {extra}")
    parts.append("Match the isometric direction of the guide image. Do not spin or orbit the building.")
    return " ".join(parts)


def furniture_prompt(extra: str = "") -> str:
    parts = [FURNITURE_PROMPT]
    extra = extra.strip()
    if extra:
        parts.append(f"The sketch is of: {extra}.")
    parts.append("Match the drawn colors. Do not add a scene around the object.")
    return " ".join(parts)


def prepare_furniture_guide(png: bytes) -> bytes:
    """Square-crop ink onto black so Flux / TripoSplat see one isolated object."""
    try:
        image = Image.open(io.BytesIO(png))
        image.load()
    except Exception as exc:
        raise ImageEditError("The furniture sketch was not a readable image") from exc
    image = image.convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        luma = image.convert("L")
        bbox = luma.point(lambda value: 255 if value > 8 else 0).getbbox()
    if bbox is None:
        raise ImageEditError("Draw some furniture before generating")
    cropped = image.crop(bbox)
    width, height = cropped.size
    pad = max(8, int(max(width, height) * 0.16))
    side = max(width, height) + pad * 2
    square = Image.new("RGB", (side, side), (0, 0, 0))
    square.paste(cropped.convert("RGB"), ((side - width) // 2, (side - height) // 2), cropped)
    square = square.resize((1024, 1024), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    square.save(out, format="PNG")
    return out.getvalue()


class ImageEditError(RuntimeError):
    def __init__(self, message: str, *, deployment_id: str | None = None):
        super().__init__(message)
        self.deployment_id = deployment_id


_DEACTIVATED = re.compile(r"Model version ([A-Za-z0-9_]+) is deactivated", re.I)


def _error_detail(raw: str) -> str:
    text = (raw or "").strip()
    try:
        payload = json.loads(text)
    except Exception:
        return " ".join(text.split())
    if not isinstance(payload, dict):
        return " ".join(text.split())
    err = payload.get("error") or payload.get("message") or payload.get("detail") or text
    if isinstance(err, dict):
        err = err.get("message") or err.get("error") or json.dumps(err)
    return " ".join(str(err).split())


def flux_error_message(status: int, raw: str) -> str:
    detail = _error_detail(raw)
    lower = detail.lower()
    if "payment method" in lower:
        return (
            "Baseten needs a payment method before Flux can start. "
            "Add a card in that workspace, activate Flux.2 [dev], then try again."
        )
    if "deactivated" in lower:
        return (
            "Flux is turned off on Baseten. Activate the Flux.2 [dev] deployment "
            "in that workspace, then try again."
        )
    if status in {401, 403}:
        suffix = f"HTTP {status}"
        if detail:
            suffix += f": {detail[:160]}"
        return (
            f"Flux rejected the API key ({suffix}). "
            "Create a key in the Hack the North workspace and set PLANCHECK_IMAGE_API_KEY."
        )
    if status == 404:
        return "Flux is not reachable at this model id. Check PLANCHECK_IMAGE_MODEL_ID."
    suffix = f": {detail[:220]}" if detail else ""
    return f"Flux request failed (HTTP {status}){suffix}"


def _manage(url: str, key: str, method: str = "GET", body: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:800]
        log.warning("image.manage_error status=%s body=%s", exc.code, raw[:400])
        raise ImageEditError(flux_error_message(exc.code, raw)) from None
    except urllib.error.URLError:
        raise ImageEditError("Could not reach Baseten to start Flux") from None
    return payload if isinstance(payload, dict) else {}


def wake_flux(
    model_id: str,
    deployment_id: str,
    key: str,
    on_status: Callable[[str], None] | None = None,
    timeout: float = 480,
    pause: float = 8,
) -> None:
    log.info("image.wake model=%s deployment=%s", model_id, deployment_id)
    if on_status:
        on_status("Starting Flux on Baseten…")
    _manage(
        f"https://api.baseten.co/v1/models/{model_id}/deployments/{deployment_id}/activate",
        key,
        method="POST",
        body={},
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = _manage(
            f"https://api.baseten.co/v1/models/{model_id}/deployments/{deployment_id}",
            key,
        )
        status = str(payload.get("status") or "").upper()
        log.info("image.wake status=%s", status)
        if status in {"ACTIVE", "SCALED_TO_ZERO"}:
            return
        if on_status:
            on_status("Flux is starting on Baseten…")
        time.sleep(max(pause, 0.01))
    raise ImageEditError("Flux is still starting on Baseten. Wait a minute and try again.")


def _decode_b64(payload: str) -> bytes:
    text = payload.strip()
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    try:
        return base64.b64decode(text, validate=False)
    except Exception as exc:
        raise ImageEditError("Baseten returned an unreadable image") from exc


def to_png(raw: bytes) -> bytes:
    if len(raw) >= 8 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise ImageEditError("Baseten returned an image we could not read") from exc
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def decode_png(data_url: str) -> bytes:
    try:
        raw = _decode_b64(data_url)
    except ImageEditError as exc:
        raise ImageEditError("The snapshot was not a PNG") from exc
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageEditError("The snapshot was not a PNG")
    if len(raw) > 12_000_000:
        raise ImageEditError("The snapshot is too large")
    return raw


def extract_png(payload: Any) -> bytes:
    if isinstance(payload, (bytes, bytearray)):
        return to_png(bytes(payload))
    if isinstance(payload, str):
        return to_png(_decode_b64(payload))
    if not isinstance(payload, dict):
        raise ImageEditError("Baseten returned an unexpected image payload")
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            blob = first.get("b64_json") or first.get("b64") or first.get("image")
            if blob:
                return to_png(_decode_b64(blob) if isinstance(blob, str) else bytes(blob))
            url = first.get("url")
            if isinstance(url, str) and url.startswith("data:"):
                return to_png(_decode_b64(url))
        if isinstance(first, str):
            return to_png(_decode_b64(first))
    for key in ("b64_json", "image", "output", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return to_png(_decode_b64(value))
        if isinstance(value, dict):
            return extract_png(value)
    raise ImageEditError("Baseten returned no image")


def _post(url: str, key: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:800]
        log.warning("image.http_error status=%s body=%s", exc.code, raw[:400])
        match = _DEACTIVATED.search(_error_detail(raw))
        raise ImageEditError(flux_error_message(exc.code, raw), deployment_id=match.group(1) if match else None) from None
    except urllib.error.URLError:
        raise ImageEditError("Could not reach the Flux deployment") from None
    if not isinstance(payload, dict):
        raise ImageEditError("Baseten returned an unexpected image payload")
    return payload


def edit_png(
    png: bytes,
    *,
    prompt: str = SCENE_PROMPT,
    timeout: float = 120,
    on_status: Callable[[str], None] | None = None,
) -> bytes:
    settings = get_settings()
    key = settings.resolved_image_api_key()
    model_id = settings.image_model_id.strip()
    if not key or not model_id:
        raise ImageEditError(
            "Flux is not configured. Set PLANCHECK_IMAGE_MODEL_ID and a Hack the North API key."
        )
    encoded = base64.b64encode(png).decode("ascii")
    data_url = f"data:image/png;base64,{encoded}"
    slug = settings.image_model.strip() or "flux2-dev"
    # OpenAI's Python extra_body is merged at the top level. Nesting it is a 400.
    generate = {
        "model": slug,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
        "num_inference_steps": 28,
        "guidance_scale": 4.0,
        "input_image": data_url,
    }
    attempts = [
        (
            f"https://model-{model_id}.api.baseten.co/environments/production/sync/v1/images/generations",
            generate,
        ),
        (
            f"https://model-{model_id}.api.baseten.co/production/sync/v1/images/generations",
            generate,
        ),
    ]

    last: ImageEditError | None = None
    woken = False
    for url, body in attempts:
        log.info("image.request url=%s bytes=%d", url.split(".co", 1)[-1], len(png))
        try:
            payload = _post(url, key, body, timeout)
            result = extract_png(payload)
            log.info("image.ok url=%s out_bytes=%d", url.split(".co", 1)[-1], len(result))
            return result
        except ImageEditError as exc:
            last = exc
            if not woken and exc.deployment_id:
                woken = True
                wake_flux(model_id, exc.deployment_id, key, on_status=on_status)
                continue
            # Billing / a confirmed inactive deployment cannot be saved by another URL.
            if "payment method" in str(exc).lower() or "turned off" in str(exc):
                raise
            continue
    raise last or ImageEditError("Flux did not return an edited image")
