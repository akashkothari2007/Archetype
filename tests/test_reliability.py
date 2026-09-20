from plancheck.core.building import Building, Floor, Opening, Room
from plancheck.services.compliance import evaluate_building
from plancheck.services.reliability import apply_reliability


def _room(rid, area_w, area_d, **kw):
    data = dict(
        id=rid,
        floor_id="f1",
        name="STUDIO KING",
        category="guestroom",
        type_ref="guestroom.studio_king",
        polygon=[(0, 0), (area_w, 0), (area_w, area_d), (0, area_d)],
        confidence=0.85,
        needs_review=False,
    )
    data.update(kw)
    return Room(**data)


def _rule(**kw):
    data = dict(
        rule_id="r-area",
        applies_to="guestroom*",
        metric="area",
        operator=">=",
        value=20,
        unit="m2",
        status="approved",
        supported=True,
        source_text="Area: 20 m²",
        source_page=34,
        source_doc="TownePlace Suites Standards.pdf",
        excludes=[],
        applies_to_filter={},
        superseded_by="",
    )
    data.update(kw)
    return data


def test_outlier_studio_is_quarantined_not_a_violation():
    rooms = [_room(f"r{i}", 16, 22) for i in range(5)]
    rooms.append(_room("r-bad", 7, 9))
    building = Building(floors=[Floor(id="f1", name="Ground")], rooms=rooms)
    apply_reliability(building)
    assert building.rooms[-1].reliability == "suspect"
    assert "median" in building.rooms[-1].reliability_reason
    assert all(room.reliability == "ok" for room in building.rooms[:-1])

    result = evaluate_building(building, [_rule()])
    assert result["coverage"]["quarantined"] == 1
    assert len(result["quarantined"]) == 1
    assert result["quarantined"][0]["status"] == "quarantined"
    assert result["quarantined"][0]["reason"]
    assert "median" in result["quarantined"][0]["reason"]
    assert result["quarantined"][0]["reason"] == building.rooms[-1].reliability_reason
    assert result["violations"] == []
    assert all(item["status"] != "fail" for item in result["checks"] if item["entity_id"] == "r-bad")


def test_opening_width_outlier_is_quarantined():
    openings = [
        Opening(id=f"d{i}", wall_id="w1", kind="door", offset_ft=1, width_ft=3.2) for i in range(8)
    ]
    openings.append(Opening(id="d-tiny", wall_id="w1", kind="door", offset_ft=1, width_ft=0.5))
    building = Building(floors=[Floor(id="f1", name="Ground")], openings=openings)
    apply_reliability(building)
    assert building.openings[-1].reliability == "suspect"
    assert building.openings[-1].reliability_reason == "implausibly narrow (0.50 ft)"
    result = evaluate_building(
        building,
        [_rule(rule_id="door", applies_to="door", metric="aperture_width", value=0.8, unit="m", scope="opening")],
    )
    tiny = [item for item in result["checks"] if item["entity_id"] == "d-tiny"]
    assert tiny
    assert tiny[0]["status"] == "quarantined"
    assert tiny[0]["reason"] == "implausibly narrow (0.50 ft)"
    assert "implausibly narrow" in tiny[0]["reliability_reason"]
    assert result["coverage"]["quarantined"] >= 1
    assert all(item["entity_id"] != "d-tiny" for item in result["violations"])


def test_identical_narrow_closets_are_quarantined():
    """MAD cannot catch a group that is uniformly impossible; physics can."""
    closets = [
        _room(
            f"c{i}",
            0.472,
            45,
            name="STUDIO KING Closet",
            category="storage",
            type_ref="storage.studio_king_closet",
        )
        for i in range(5)
    ]
    building = Building(floors=[Floor(id="f1", name="Ground")], rooms=closets)
    apply_reliability(building)
    assert all(room.reliability == "suspect" for room in building.rooms)
    assert all(room.reliability_reason == "implausibly narrow (0.14 m)" for room in building.rooms)
    result = evaluate_building(
        building,
        [_rule(rule_id="closet-side", applies_to="*Closet*", metric="min_side", value=0.6, unit="m")],
    )
    assert result["violations"] == []
    assert result["coverage"]["quarantined"] == 5
    assert all(item["status"] == "quarantined" for item in result["checks"])
    assert all(item["reason"] == "implausibly narrow (0.14 m)" for item in result["checks"])


def test_uniformly_wide_openings_are_quarantined():
    openings = [Opening(id=f"d{i}", wall_id="w1", kind="door", offset_ft=1, width_ft=10.0) for i in range(6)]
    building = Building(floors=[Floor(id="f1", name="Ground")], openings=openings)
    apply_reliability(building)
    assert all(item.reliability == "suspect" for item in building.openings)
    assert all(item.reliability_reason == "implausibly wide (10.00 ft)" for item in building.openings)
