"""Acceptance checks against the real drawing set.

The drawings are licensed client material and are not in this repository, so
these tests skip unless the file is present. Point at it with:

    export PLANCHECK_TEST_PDF="/path/to/21-039_Sidney TPS_Arch._IFC.pdf"

Extract/model tests stay out of this file: those engines are stubs in the
scaffold. Classify is real and must hold on the 51-page set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from plancheck.engines.classify import classify_document

DEFAULT_PDF = (
    Path.home()
    / "Downloads/Information for Akash/Drawings/21-039_Sidney TPS_Arch._IFC.pdf"
)
PDF = Path(os.environ.get("PLANCHECK_TEST_PDF", DEFAULT_PDF))

pytestmark = pytest.mark.skipif(
    not PDF.is_file(), reason=f"Drawing set not available at {PDF}"
)


@pytest.fixture(scope="module")
def classified():
    return classify_document(PDF, "drw-01")


class TestClassify:
    def test_document_shape(self, classified) -> None:
        document, sheets = classified
        assert document.pages == 51
        assert document.page_size_pt == [2384.0, 1684.0]
        assert document.text_extractable
        assert document.layered, "CAD layers (OCGs) must survive the PDF export"
        assert len(sheets) == 51

    @pytest.mark.parametrize(
        ("page", "sheet_no", "role", "pts_per_ft", "use"),
        [
            (8, "A.202", "floor_plan", 4.5, True),
            (30, "A.501c", "enlarged_plan", 13.5, True),
            (51, "A.801", "unit_plan", 18.0, True),
            (17, "A.301", "elevation", 4.5, False),
        ],
    )
    def test_key_pages(
        self, classified, page, sheet_no, role, pts_per_ft, use
    ) -> None:
        _document, sheets = classified
        row = sheets[page - 1]
        assert row.page == page
        assert row.sheet_no == sheet_no
        assert row.role == role
        assert row.scale_pts_per_ft == pytest.approx(pts_per_ft)
        assert row.use is use

    def test_floor_plan_levels(self, classified) -> None:
        _document, sheets = classified
        ground = next(s for s in sheets if s.sheet_no == "A.201")
        typical = next(s for s in sheets if s.sheet_no == "A.202")
        assert ground.levels == ["1"]
        assert typical.levels == ["2", "3"]

    @pytest.mark.parametrize("page", range(10, 17))
    def test_slab_edge_pages_are_excluded_with_a_reason(
        self, classified, page
    ) -> None:
        _document, sheets = classified
        row = sheets[page - 1]
        assert row.role == "slab_edge"
        assert row.use is False
        assert row.reason

    def test_every_excluded_page_states_a_reason(self, classified) -> None:
        _document, sheets = classified
        for row in sheets:
            if not row.use:
                assert row.reason, f"page {row.page} was excluded with no reason"
