import base64
import json
import time

from fastapi.testclient import TestClient

from plancheck.api.main import app
from plancheck.core.settings import reset_settings
from plancheck.mocks.generation import demo_home, demo_rules
from plancheck.services.image_edit import SCENE_PROMPT, decode_png, edit_png, extract_png, to_png
from plancheck.services.repository import FileProjectRepository

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_decode_png_from_data_url():
    encoded = base64.b64encode(TINY_PNG).decode()
    assert decode_png("data:image/png;base64," + encoded) == TINY_PNG


def test_extract_png_from_openai_shape():
    encoded = base64.b64encode(TINY_PNG).decode()
    assert extract_png({"data": [{"b64_json": encoded}]}) == TINY_PNG


def test_extract_png_converts_jpeg():
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (200, 10, 10)).save(buf, format="JPEG")
    jpeg = buf.getvalue()
    encoded = base64.b64encode(jpeg).decode()
    png = extract_png({"data": [{"b64_json": encoded}]})
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert to_png(jpeg)[:8] == b"\x89PNG\r\n\x1a\n"


def test_sample_palette_skips_black_background():
    import io
    from PIL import Image
    from plancheck.services.appearance_style import sample_palette

    image = Image.new("RGB", (8, 8), (0, 0, 0))
    for x in range(3, 7):
        for y in range(3, 7):
            image.putpixel((x, y), (180, 90, 40))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    palette = sample_palette(buf.getvalue())
    assert palette["primary"].startswith("#")
    assert palette["primary"] != "#000000"


def test_extract_cladding_writes_wall_and_roof_maps():
    import io
    from PIL import Image
    from plancheck.services.appearance_style import extract_cladding

    image = Image.new("RGB", (64, 64), (0, 0, 0))
    for x in range(12, 52):
        for y in range(18, 58):
            image.putpixel((x, y), (160, 70, 40) if y > 28 else (90, 90, 95))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    wall, roof = extract_cladding(buf.getvalue())
    assert wall[:8] == b"\x89PNG\r\n\x1a\n"
    assert roof[:8] == b"\x89PNG\r\n\x1a\n"


def test_scene_prompt_forbids_toys():
    assert "diorama" in SCENE_PROMPT.lower()
    assert "black" in SCENE_PROMPT.lower()


def test_appearance_requires_flux_config(monkeypatch):
    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "")
    reset_settings()
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    response = TestClient(app).post(
        f"/api/desktop/projects/{project.project_id}/appearance",
        json={"image": "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()},
    )
    assert response.status_code == 400


def test_appearance_requires_triposplat_key(monkeypatch):
    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q40o4ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("PLANCHECK_SPLAT_API_KEY", "")
    monkeypatch.setenv("PLANCHECK_SPLAT_URL", "")
    monkeypatch.delenv("FAL_KEY", raising=False)
    reset_settings()
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    response = TestClient(app).post(
        f"/api/desktop/projects/{project.project_id}/appearance",
        json={"image": "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()},
    )
    assert response.status_code == 400
    assert "FAL_KEY" in response.json()["detail"]


def test_appearance_job_writes_png(monkeypatch, tmp_path):
    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q4o04ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("FAL_KEY", "test-fal")
    reset_settings()
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    monkeypatch.setattr("plancheck.services.image_edit.edit_png", lambda png, **kw: TINY_PNG)
    monkeypatch.setattr("plancheck.services.splat.generate_splat", lambda png, **kw: b"ply\nformat ascii 1.0\nend_header\n")
    client = TestClient(app)
    started = client.post(
        f"/api/desktop/projects/{project.project_id}/appearance",
        json={
            "image": "data:image/png;base64," + base64.b64encode(TINY_PNG).decode(),
            "projector": [1] * 16,
        },
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    for _ in range(50):
        job = client.get(f"/api/desktop/jobs/{job_id}").json()
        if job["state"] in {"done", "error"}:
            break
        time.sleep(0.05)
    assert job["state"] == "done", job
    saved = tmp_path / "projects" / project.project_id / "appearance.png"
    assert saved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    meta = json.loads((tmp_path / "projects" / project.project_id / "appearance.json").read_text(encoding="utf-8"))
    assert meta["scope"] == "exterior"
    assert "primary" in meta["palette"]
    assert meta["splat"] == "appearance.ply"
    assert (tmp_path / "projects" / project.project_id / "appearance.ply").is_file()


def test_edit_png_sends_input_image_not_nested_extra_body(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            encoded = base64.b64encode(TINY_PNG).decode()
            return json.dumps({"data": [{"b64_json": encoded}]}).encode()

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q40o4ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    reset_settings()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert edit_png(TINY_PNG) == TINY_PNG
    assert captured["url"].endswith("/images/generations")
    assert "extra_body" not in captured["body"]
    assert captured["body"]["input_image"].startswith("data:image/png;base64,")
    assert captured["body"]["response_format"] == "b64_json"
