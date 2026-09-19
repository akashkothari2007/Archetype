"""Acceptance checks against the real drawing set.

The drawings are licensed client material and are not in this repository, so
these tests skip unless the file is present. Point at it with:

    export PLANCHECK_TEST_PDF="/path/to/21-039_Sidney TPS_Arch._IFC.pdf"
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from plancheck.classifier import classify_document
from plancheck.sheet import extract_sheet

DEFAULT_PDF = (
    Path.home() / "Downloads/Information for Akash/Drawings/21-039_Sidney TPS_Arch._IFC.pdf"
)
PDF = Path(os.environ.get("PLANCHECK_TEST_PDF", DEFAULT_PDF))

pytestmark = pytest.mark.skipif(not PDF.is_file(), reason=f"Drawing set not available at {PDF}")


@pytest.fixture(scope="module")
def document():
    return classify_document(PDF)


@pytest.fixture(scope="module")
def sheets():
    cache: dict[int, dict] = {}

    def get(page: int) -> dict:
        if page not in cache:
            cache[page] = extract_sheet(PDF, page, render_dir=None).payload
        return cache[page]

    return get


class TestClassify:
    def test_document_shape(self, document) -> None:
        assert document.page_count == 51
        assert (document.page_width, document.page_height) == (2384.0, 1684.0)
        assert document.text_extracts
        assert document.has_ocgs, "the CAD layers are the whole trick; they must survive"

    @pytest.mark.parametrize(
        ("page", "sheet_no", "role", "pts_per_ft", "use"),
        [
            (8, "A.202", "floor_plan", 4.5, True),
            (30, "A.501c", "enlarged_plan", 13.5, True),
            (51, "A.801", "unit_plan", 18.0, True),
            (17, "A.301", "elevation", 4.5, False),
        ],
    )
    def test_key_pages(self, document, page, sheet_no, role, pts_per_ft, use) -> None:
        row = document.sheets[page - 1]
        assert row.page == page
        assert row.sheet_no == sheet_no
        assert row.role == role
        assert row.scale_pts_per_ft == pytest.approx(pts_per_ft)
        assert row.use is use

    @pytest.mark.parametrize("page", range(10, 17))
    def test_slab_edge_pages_are_excluded_with_a_reason(self, document, page) -> None:
        row = document.sheets[page - 1]
        assert row.role == "slab_edge"
        assert row.use is False
        assert row.reason

    def test_every_excluded_page_states_a_reason(self, document) -> None:
        for row in document.sheets:
            if not row.use:
                assert row.reason, f"page {row.page} was excluded with no reason"


class TestExtract:
    #: page -> bucket path counts, from the layer audit of the real set.
    EXPECTED = {
        51: {"wall": 352, "door": 188, "window": 60, "fixture": 2150},
        30: {"wall": 1969, "door": 264, "grid": 432, "room_tag": 1256},
        8: {"wall": 6649, "door": 2053, "grid": 2346, "room_tag": 9308},
    }

    @pytest.mark.parametrize("page", [51, 30, 8])
    def test_bucket_path_counts(self, sheets, page) -> None:
        layers = sheets(page)["layers"]
        for bucket, expected in self.EXPECTED[page].items():
            assert layers[bucket]["paths"] == expected

    @pytest.mark.parametrize("page", [51, 30, 8])
    def test_furniture_is_excluded_at_extract_time(self, sheets, page) -> None:
        """Toggling furniture in the viewer changes nothing because it never ships."""
        payload = sheets(page)
        assert payload["excluded"].get("furniture", 0) > 0
        assert "furniture" not in payload
        for record in payload["walls"]:
            assert "FURN" not in record["layer"]

    @pytest.mark.parametrize("page", [51, 30, 8])
    def test_geometry_stays_inside_the_sheet(self, sheets, page) -> None:
        payload = sheets(page)
        width, height = payload["page"]["width"], payload["page"]["height"]
        for wall in payload["walls"]:
            assert 0 <= wall["x1"] <= width and 0 <= wall["x2"] <= width
            assert 0 <= wall["y1"] <= height and 0 <= wall["y2"] <= height

    @pytest.mark.parametrize("page", [51, 30, 8])
    def test_nothing_is_silently_lost(self, sheets, page) -> None:
        payload = sheets(page)
        assert isinstance(payload["unmapped"], dict)
        assert all(count > 0 for count in payload["unmapped"].values())

    @pytest.mark.parametrize("page", [51, 30, 8])
    def test_heights_and_thicknesses_are_never_invented(self, sheets, page) -> None:
        assumptions = sheets(page)["assumptions"]
        assert assumptions["wall_height_ft"] is None
        assert assumptions["wall_thickness_ft"] is None

    @pytest.mark.parametrize("page", [51, 30, 8])
    def test_output_is_well_under_the_size_budget(self, sheets, page) -> None:
        encoded = json.dumps(sheets(page), separators=(",", ":"))
        assert len(encoded) < 20 * 1_048_576

    def test_walls_carry_their_construction_class(self, sheets) -> None:
        walls = sheets(8)["walls"]
        assert {w["cls"] for w in walls} >= {"loadbearing", "interior", "stud"}

    def test_dashed_grid_lines_are_recovered(self, sheets) -> None:
        """No single grid path on page 8 is longer than about 20pt."""
        assert sheets(8)["counts"]["grid_lines"] > 0

    def test_dimensions_prefer_the_metric_bracket(self, sheets) -> None:
        dimensions = sheets(8)["dimensions"]
        assert dimensions
        bracket = sum(1 for d in dimensions if d["source"] == "metric_bracket")
        assert bracket > len(dimensions) * 0.75

    def test_outlined_room_tags_are_located_but_not_guessed(self, sheets) -> None:
        """Page 30's tag text is vector outlines, so the string is unrecoverable."""
        tags = sheets(30)["room_tags"]
        assert tags
        for tag in tags:
            if tag["text_outlined"]:
                assert tag["label"] is None
                assert tag["bbox"]

    def test_sheet_metadata_survives_extraction(self, sheets) -> None:
        sheet = sheets(51)["sheet"]
        assert sheet["sheet_no"] == "A.801"
        assert sheet["title"] == "ENLARGED UNIT PLANS"
        assert sheet["role"] == "unit_plan"
        assert sheet["scale_pts_per_ft"] == pytest.approx(18.0)
