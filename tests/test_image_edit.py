import base64
import json
import time
import urllib.error

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


def test_guide_prompt_uses_brief_and_keeps_camera():
    from plancheck.core.building import DesignBrief
    from plancheck.services.image_edit import guide_prompt

    prompt = guide_prompt(
        DesignBrief(name="Willow House", building_use="Home", style="Warm brick", prompt="South-facing porch"),
        extra="evening light",
    )
    assert "Warm brick" in prompt
    assert "South-facing porch" in prompt
    assert "evening light" in prompt
    assert "isometric" in prompt.lower()
    assert "miniature" in prompt.lower()


def test_furniture_prompt_keeps_the_sketch_isolated():
    from plancheck.services.image_edit import FURNITURE_PROMPT, furniture_prompt

    prompt = furniture_prompt("red velvet sofa")
    assert "red velvet sofa" in prompt
    assert "black" in FURNITURE_PROMPT.lower()
    assert "furniture" in prompt.lower()


def test_prepare_furniture_guide_crops_ink_onto_black():
    import io
    from PIL import Image
    from plancheck.services.image_edit import prepare_furniture_guide

    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    for x in range(10, 22):
        for y in range(8, 24):
            image.putpixel((x, y), (200, 40, 40, 255))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    guide = prepare_furniture_guide(buf.getvalue())
    out = Image.open(io.BytesIO(guide))
    assert out.size == (1024, 1024)
    assert out.convert("RGB").getpixel((0, 0)) == (0, 0, 0)
    assert out.convert("RGB").getpixel((512, 512))[0] > 80


def test_prepare_furniture_guide_rejects_blank_canvas():
    import io
    from PIL import Image
    from plancheck.services.image_edit import ImageEditError, prepare_furniture_guide

    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(buf, format="PNG")
    try:
        prepare_furniture_guide(buf.getvalue())
        raise AssertionError("blank sketches should be rejected")
    except ImageEditError as exc:
        assert "Draw some furniture" in str(exc)


def test_appearance_get_is_empty_before_paint(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path / "projects"))
    reset_settings()
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    response = TestClient(app).get(f"/api/desktop/projects/{project.project_id}/appearance")
    assert response.status_code == 200
    assert response.json() == {}


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


def test_appearance_does_not_require_triposplat_key(monkeypatch):
    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q40o4ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("PLANCHECK_SPLAT_API_KEY", "")
    monkeypatch.setenv("PLANCHECK_SPLAT_URL", "")
    reset_settings()
    monkeypatch.setattr("plancheck.api.routes.desktop.jobs.submit", lambda *_args, **_kwargs: "appearance-job")
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    response = TestClient(app).post(
        f"/api/desktop/projects/{project.project_id}/appearance",
        json={"image": "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()},
    )
    assert response.status_code == 200


def test_appearance_job_writes_png(monkeypatch, tmp_path):
    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q4o04ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path / "projects"))
    reset_settings()
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    monkeypatch.setattr("plancheck.services.image_edit.edit_png", lambda png, **kw: TINY_PNG)
    client = TestClient(app)
    started = client.post(
        f"/api/desktop/projects/{project.project_id}/appearance",
        json={
            "image": "data:image/png;base64," + base64.b64encode(TINY_PNG).decode(),
            "projector": [1] * 16,
            "prompt": "warm hand-made brick",
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
    assert meta["prompt"] == "warm hand-made brick"
    assert "primary" in meta["palette"]
    fetched = client.get(f"/api/desktop/projects/{project.project_id}/appearance")
    assert fetched.status_code == 200
    assert "palette" in fetched.json()


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


def test_flux_error_explains_deactivated_and_billing():
    from plancheck.services.image_edit import flux_error_message

    assert "turned off" in flux_error_message(400, '{"error":"Model version qe9xr82 is deactivated. It needs to be activated before running predictions"}').lower()
    assert "payment method" in flux_error_message(400, '{"code":"VALIDATION_ERROR","message":"You must add a payment method to deploy models."}').lower()
    auth = flux_error_message(403, '{"error":"Authentication failed"}')
    assert "HTTP 403" in auth
    assert "Authentication failed" in auth


def test_edit_png_retries_both_flux_urls_on_403(monkeypatch):
    from plancheck.services.image_edit import ImageEditError, edit_png

    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "Forbidden",
            hdrs=None,
            fp=__import__("io").BytesIO(b'{"error":"Authentication failed"}'),
        )

    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q40o4ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    reset_settings()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    try:
        edit_png(TINY_PNG)
        raise AssertionError("rejected Flux keys should fail")
    except ImageEditError as exc:
        assert "HTTP 403" in str(exc)
        assert "Authentication failed" in str(exc)
    assert any("/environments/production/sync/v1/images/generations" in url for url in calls)
    assert any("/production/sync/v1/images/generations" in url and "/environments/" not in url for url in calls)


def test_edit_png_wakes_deactivated_flux_then_surfaces_billing(monkeypatch):
    from plancheck.services.image_edit import ImageEditError, edit_png

    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append(request.full_url)
        if "images/generations" in request.full_url:
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=__import__("io").BytesIO(
                    b'{"error":"Model version qe9xr82 is deactivated. It needs to be activated before running predictions"}'
                ),
            )
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=__import__("io").BytesIO(
                b'{"code":"VALIDATION_ERROR","message":"You must add a payment method to deploy models."}'
            ),
        )

    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q40o4ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    reset_settings()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    try:
        edit_png(TINY_PNG)
        raise AssertionError("deactivated Flux should fail with a billing message")
    except ImageEditError as exc:
        assert "payment method" in str(exc).lower()
    assert any("images/generations" in url for url in calls)
    assert any("/activate" in url for url in calls)


def _sketch_png():
    import io
    from PIL import Image

    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for x in range(8, 24):
        for y in range(10, 22):
            image.putpixel((x, y), (180, 60, 40, 255))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_imagine_furniture_requires_flux_and_splat(monkeypatch):
    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q40o4ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("PLANCHECK_SPLAT_URL", "")
    monkeypatch.setenv("PLANCHECK_SPLAT_API_KEY", "")
    reset_settings()
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    floor_id = project.building.floors[0].id
    response = TestClient(app).post(
        f"/api/desktop/projects/{project.project_id}/imagine-furniture",
        json={
            "image": "data:image/png;base64," + base64.b64encode(_sketch_png()).decode(),
            "floor_id": floor_id,
            "x": 8,
            "y": 6,
        },
    )
    assert response.status_code == 400


def test_imagine_furniture_job_writes_splat(monkeypatch, tmp_path):
    monkeypatch.setenv("PLANCHECK_IMAGE_MODEL_ID", "q40o4ekw")
    monkeypatch.setenv("PLANCHECK_IMAGE_API_KEY", "test-key")
    monkeypatch.setenv("PLANCHECK_SPLAT_URL", "https://model-abc.api.baseten.co/environments/production/predict")
    monkeypatch.setenv("PLANCHECK_SPLAT_API_KEY", "splat-key")
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path / "projects"))
    reset_settings()
    repo = FileProjectRepository()
    project = repo.create("Look", demo_home(), demo_rules())
    monkeypatch.setattr("plancheck.services.image_edit.edit_png", lambda png, **kw: TINY_PNG)
    monkeypatch.setattr("plancheck.services.splat.generate_splat", lambda png, **kw: b"\x00\x01splat-payload")
    client = TestClient(app)
    started = client.post(
        f"/api/desktop/projects/{project.project_id}/imagine-furniture",
        json={
            "image": "data:image/png;base64," + base64.b64encode(_sketch_png()).decode(),
            "floor_id": project.building.floors[0].id,
            "x": 8,
            "y": 6,
            "width_ft": 5,
            "depth_ft": 3,
            "height_ft": 2.5,
            "prompt": "walnut bench",
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
    placed = job["result"]["object"]
    assert placed["asset_id"] == "imagine"
    assert placed["splat"].endswith(".splat")
    assert placed["width_ft"] == 5
    saved = tmp_path / "projects" / project.project_id / placed["splat"]
    assert saved.read_bytes() == b"\x00\x01splat-payload"
