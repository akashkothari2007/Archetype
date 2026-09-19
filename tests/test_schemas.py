from pathlib import Path

import pytest

from plancheck.core.schemas import (
    CheckResult,
    Model,
    Project,
    ProposedEdits,
    Ruleset,
    Sheet,
    SheetGeometry,
)
from plancheck.engines.base import FIXTURE_DIR, load_fixture


FIXTURES = {
    "project.json": Project,
    "sheet_geometry.json": SheetGeometry,
    "model.json": Model,
    "rules.json": Ruleset,
    "mismatches.json": CheckResult,
    "proposed_edits.json": ProposedEdits,
}


@pytest.mark.parametrize("name, cls", FIXTURES.items())
def test_fixture_round_trip(name, cls):
    original = load_fixture(name, cls)
    dumped = original.model_dump_json()
    restored = cls.model_validate_json(dumped)
    assert restored.model_dump() == original.model_dump()


def test_use_false_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        Sheet(
            sheet_id="x",
            doc_id="d",
            page=1,
            role="elevation",
            use=False,
            reason="",
        )


def test_fixtures_are_hand_written():
    for name in FIXTURES:
        assert (Path(FIXTURE_DIR) / name).is_file()
