"""End-to-end round trip against the stub engines.

These assertions are about the *contract*, not the stub's made-up geometry.
They should keep passing unchanged when the real extractor replaces the stub.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    get_settings.cache_clear()
    monkeypatch.setenv("PLANCHECK_DATA_DIR", str(tmp_path / "projects"))
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def _pdf(pages: int) -> bytes:
    """A minimal valid PDF with the given page count."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=1224, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _upload(client: TestClient, pages: int = 51):
    return client.post(
        "/api/projects",
        files={"drawings": ("set.pdf", _pdf(pages), "application/pdf")},
    )


def test_health_reports_which_engines_are_stubbed(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["engines"]["extractor"] == "stub"


def test_upload_classifies_every_page(client: TestClient) -> None:
    response = _upload(client)
    assert response.status_code == 201

    project = response.json()
    assert project["documents"][0]["page_count"] == 51
    assert len(project["sheets"]) == 51
    # Every sheet states a reason, used or not. That is the whole point of the view.
    assert all(sheet["reason"] for sheet in project["sheets"])

    used = [s["page"] for s in project["sheets"] if s["use"]]
    assert used == [7, 8, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 51]


def test_unknown_page_count_is_reported_not_guessed(client: TestClient) -> None:
    project = _upload(client, pages=12).json()
    assert all(sheet["role"] == "unknown" for sheet in project["sheets"])
    assert not any(sheet["use"] for sheet in project["sheets"])


def test_non_pdf_upload_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/projects",
        files={"drawings": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415


def test_extract_returns_a_well_formed_building(client: TestClient) -> None:
    project_id = _upload(client).json()["project_id"]

    response = client.post(f"/api/projects/{project_id}/extract", json={"pages": [8, 33, 51]})
    assert response.status_code == 200

    building = response.json()["building"]
    assert building["meta"]["pages"] == [8, 33, 51]
    assert building["meta"]["generator"] == "stub"
    assert building["rooms"], "extraction produced no rooms"

    # Geometry invariants the viewer depends on.
    min_x, min_y, max_x, max_y = building["meta"]["bounds_ft"]
    for room in building["rooms"]:
        assert len(room["polygon_ft"]) >= 3
        assert room["source"]["page"], "every room must carry provenance"
        assert 0.0 <= room["confidence"] <= 1.0
        x0, y0, x1, y1 = room["bbox_ft"]
        assert min_x <= x0 < x1 <= max_x
        assert min_y <= y0 < y1 <= max_y

    # Blast radius must resolve: a room's unit type has to exist.
    unit_type_ids = {u["id"] for u in building["unit_types"]}
    for room in building["rooms"]:
        if room["unit_type_id"] is not None:
            assert room["unit_type_id"] in unit_type_ids

    # Openings must reference real rooms.
    room_ids = {room["id"] for room in building["rooms"]}
    for opening in building["openings"]:
        assert opening["connects"][0] in room_ids


def test_extract_auto_uses_the_recommended_sheets(client: TestClient) -> None:
    project_id = _upload(client).json()["project_id"]
    body = client.post(f"/api/projects/{project_id}/extract", json={"pages": "auto"}).json()
    assert body["pages"] == [7, 8, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 51]


def test_extract_rejects_pages_outside_the_document(client: TestClient) -> None:
    project_id = _upload(client).json()["project_id"]
    response = client.post(f"/api/projects/{project_id}/extract", json={"pages": [999]})
    assert response.status_code == 400


def test_building_is_persisted_and_refetchable(client: TestClient) -> None:
    project_id = _upload(client).json()["project_id"]
    assert client.get(f"/api/projects/{project_id}/building").status_code == 404

    client.post(f"/api/projects/{project_id}/extract", json={"pages": [51]})
    refetched = client.get(f"/api/projects/{project_id}/building")
    assert refetched.status_code == 200
    assert refetched.json()["meta"]["pages"] == [51]


def test_missing_project_is_a_404(client: TestClient) -> None:
    assert client.get("/api/projects/does-not-exist").status_code == 404
