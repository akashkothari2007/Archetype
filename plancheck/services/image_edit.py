"""FLUX.2 image edit on a dedicated Baseten deployment."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from typing import Any

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


class ImageEditError(RuntimeError):
    pass


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
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        log.warning("image.http_error status=%s body=%s", exc.code, detail)
        if exc.code in {401, 403}:
            raise ImageEditError(
                "This Baseten API key cannot call the Flux deployment. "
                "Create a key in the Hack the North workspace and set PLANCHECK_IMAGE_API_KEY."
            ) from None
        if exc.code == 404:
            raise ImageEditError(
                "Flux is not reachable at this model id. Check PLANCHECK_IMAGE_MODEL_ID."
            ) from None
        raise ImageEditError(f"Flux request failed (HTTP {exc.code})") from None
    except urllib.error.URLError:
        raise ImageEditError("Could not reach the Flux deployment") from None
    if not isinstance(payload, dict):
        raise ImageEditError("Baseten returned an unexpected image payload")
    return payload


def edit_png(png: bytes, *, prompt: str = SCENE_PROMPT, timeout: float = 120) -> bytes:
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
            f"https://model-{model_id}.api.baseten.co/production/sync/v1/images/generations",
            generate,
        ),
        (
            f"https://model-{model_id}.api.baseten.co/environments/production/sync/v1/images/generations",
            generate,
        ),
    ]

    last: ImageEditError | None = None
    for url, body in attempts:
        log.info("image.request url=%s bytes=%d", url.split(".co", 1)[-1], len(png))
        try:
            payload = _post(url, key, body, timeout)
            result = extract_png(payload)
            log.info("image.ok url=%s out_bytes=%d", url.split(".co", 1)[-1], len(result))
            return result
        except ImageEditError as exc:
            last = exc
            if "Hack the North" in str(exc) or "not reachable" in str(exc):
                raise
            continue
    raise last or ImageEditError("Flux did not return an edited image")
