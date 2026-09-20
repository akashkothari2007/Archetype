import base64
import io
import json

import pytest

from plancheck.core.settings import reset_settings
from plancheck.services import splat as splat_service

SPLAT_BYTES = b"\x00\x01splat-payload"


def test_auth_header_per_provider():
    assert splat_service._auth("https://model-1.api.baseten.co/environments/production/predict", "k") == "Api-Key k"
    assert splat_service._auth("https://splat.internal/predict", "k") == "Bearer k"


def test_reason_surfaces_api_error():
    body = json.dumps({"error": "Internal Server Error (in model/chainlet)."})
    message = splat_service._reason(500, body)
    assert "Internal Server Error" in message
    assert splat_service._reason(401, json.dumps({"detail": "unauthorized"})).startswith("TripoSplat rejected")


def test_generate_splat_uses_self_hosted_endpoint(monkeypatch):
    monkeypatch.setenv("PLANCHECK_SPLAT_URL", "https://model-abc.api.baseten.co/environments/production/predict")
    monkeypatch.setenv("PLANCHECK_SPLAT_API_KEY", "baseten-key")
    reset_settings()
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["body"] = json.loads(request.data.decode("utf-8"))
        payload = {
            "model_mesh": {
                "content": base64.b64encode(SPLAT_BYTES).decode("ascii"),
                "file_name": "output.splat",
            }
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        response.__enter__ = lambda: response
        response.__exit__ = lambda *args: False
        return response

    monkeypatch.setattr(splat_service.urllib.request, "urlopen", fake_urlopen)
    assert splat_service.generate_splat(b"\x89PNG fake") == SPLAT_BYTES
    assert seen["url"].endswith("/environments/production/predict")
    assert seen["auth"] == "Api-Key baseten-key"
    assert seen["body"]["output_format"] == "splat"
    assert seen["body"]["image"].startswith("data:image/png;base64,")


def test_generate_splat_without_any_endpoint(monkeypatch):
    monkeypatch.setenv("PLANCHECK_SPLAT_URL", "")
    monkeypatch.setenv("PLANCHECK_SPLAT_API_KEY", "")
    reset_settings()
    with pytest.raises(splat_service.SplatError, match="not configured"):
        splat_service.generate_splat(b"\x89PNG fake")


def test_splat_filename_tracks_format():
    assert splat_service.splat_filename(b"ply\nformat ascii 1.0\n") == "appearance.ply"
    assert splat_service.splat_filename(SPLAT_BYTES) == "appearance.splat"
