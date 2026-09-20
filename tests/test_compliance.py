from shapely.geometry import box
from shapely.ops import unary_union

from plancheck.core.building import Building, Floor, Opening, Room
from plancheck.services.baseline_rules import BASELINE_RULES, layer_rules
from plancheck.services.compliance import (
    check_building,
    evaluate_building,
    matches_room,
    to_rule_units,
)


def _room(**kw):
    data = dict(
        id="r1",
        floor_id="f1",
        name="201",
        category="guestroom",
        type_ref="",
        polygon=[(0, 0), (16, 0), (16, 20), (0, 20)],
        confidence=0.85,
        needs_review=False,
    )
    data.update(kw)
    return Room(**data)


def _building(rooms, openings=None):
    return Building(floors=[Floor(id="f1", name="Ground")], rooms=list(rooms), openings=list(openings or []))


def _rule(**kw):
    data = dict(
        rule_id="r1",
        applies_to="guestroom*",
        metric="area",
        operator=">=",
        value=16,
        unit="m2",
        status="approved",
        supported=True,
        source_text="Area: 16 m²",
        source_page=34,
        source_doc="TownePlace Suites Standards.pdf",
        excludes=[],
        applies_to_filter={},
        superseded_by="",
    )
    data.update(kw)
    return data


def test_guestroom_glob_matches_category_when_type_ref_empty():
    room = _room(type_ref="")
    rule = {"applies_to": "guestroom*", "metric": "area"}
    assert matches_room(room, rule)
    assert not matches_room(_room(category="circulation", name="CORRIDOR"), rule)


def test_guestroom_glob_matches_type_ref():
    room = _room(category="other", type_ref="guestroom.studio_king", name="STUDIO KING")
    assert matches_room(room, {"applies_to": "guestroom*"})


def test_pending_rules_do_not_emit_checks():
    building = _building([_room()])
    pending = _rule(status="pending")
    assert check_building(building, [pending]) == []
    results = check_building(building, [_rule(status="approved")])
    assert results
    assert results[0]["source_text"]
    assert results[0]["source_page"] == 34


def test_accessible_room_uses_acc_rule_not_generic():
    room = _room(id="acc", name="ACC. KING", category="guestroom", type_ref="guestroom.acc_king", polygon=[(0, 0), (5.1, 0), (5.1, 22), (0, 22)])
    generic = _rule(rule_id="base-guestroom-min-side", applies_to="guestroom*", metric="min_side", value=3.0, unit="m", excludes=["*Bath*", "*Closet*"])
    accessible = _rule(rule_id="base-acc-min-side", applies_to="ACC.*", metric="min_side", value=1.52, unit="m", excludes=["*Bath*", "*Closet*"])
    results = check_building(_building([room]), [generic, accessible])
    assert len(results) == 1
    assert results[0]["rule_id"] == "base-acc-min-side"
    assert results[0]["status"] == "pass"


def test_corridor_min_side_converts_metres_to_feet():
    room = _room(id="c1", name="CORRIDOR", category="circulation", type_ref="circulation.corridor", polygon=[(0, 0), (40, 0), (40, 6), (0, 6)])
    rule = _rule(rule_id="corr", applies_to="CORRIDOR*", metric="min_side", value=1.5, unit="m")
    results = check_building(_building([room]), [rule])
    assert results
    assert results[0]["status"] == "pass"
    assert results[0]["actual"] == pytest_approx(6 * 0.3048)


def pytest_approx(value, rel=1e-3):
    class A:
        def __eq__(self, other):
            return other is not None and abs(float(other) - value) <= rel * max(1.0, abs(value))

        def __repr__(self):
            return f"approx({value})"

    return A()


def test_l_shaped_corridor_reports_pinch_geometry():
    polygon = unary_union([box(0, 0, 12, 10), box(12, 3.5, 18, 6.5), box(18, 0, 30, 10)])
    coords = list(polygon.exterior.coords)[:-1]
    room = _room(id="l1", name="CORRIDOR", category="circulation", polygon=coords)
    rule = _rule(rule_id="corr-pinch", applies_to="CORRIDOR*", metric="min_side", value=1.5, unit="m")
    results = check_building(_building([room]), [rule])
    assert results[0]["status"] == "fail"
    assert results[0]["pinch_polygon"]
    assert len(results[0]["pinch_polygon"]) >= 4


def test_bathroom_door_does_not_trip_entry_rule():
    guest = _room(id="g1", name="STUDIO KING", wall_ids=["w-entry", "w-bath"])
    bath = _room(id="b1", name="STUDIO KING Bath", category="bathroom", polygon=[(0, 0), (8, 0), (8, 8), (0, 8)], wall_ids=["w-bath"])
    corridor = _room(id="c1", name="CORRIDOR", category="circulation", polygon=[(0, 0), (20, 0), (20, 6), (0, 6)], wall_ids=["w-entry"])
    entry = Opening(id="d-entry", wall_id="w-entry", kind="door", offset_ft=1, width_ft=3.5)
    bath_door = Opening(id="d-bath", wall_id="w-bath", kind="door", offset_ft=1, width_ft=2.5)
    rule = _rule(
        rule_id="base-guestroom-entry-clear",
        applies_to="door",
        metric="clear_width",
        value=0.81,
        unit="m",
        scope="opening",
        excludes=["*Bath*", "*Closet*"],
        applies_to_filter={"door_to": "guestroom*"},
    )
    results = check_building(_building([guest, bath, corridor], [entry, bath_door]), [rule])
    ids = {item["entity_id"] for item in results}
    assert "d-bath" not in ids
    assert "d-entry" in ids
    assert all(item.get("assumption") for item in results)


def test_null_geometry_is_cannot_verify():
    room = _room(polygon=[], needs_review=False, confidence=0.9)
    results = check_building(_building([room]), [_rule()])
    assert results
    assert results[0]["status"] == "cannot_verify"
    assert results[0]["status"] != "pass"
    assert "polygon" in results[0]["message"].lower()


def test_needs_review_cannot_verify_names_the_field():
    room = _room(needs_review=True, confidence=0.85, name="STUDIO KING")
    results = check_building(_building([room]), [_rule()])
    assert results[0]["status"] == "cannot_verify"
    assert "needs_review" in results[0]["message"]
    assert "STUDIO KING" in results[0]["message"]
    assert results[0]["message"] != "Review the uncertain room geometry before verifying this rule."


def test_unmatched_rule_is_reported_not_emitted():
    room = _room(name="STUDIO KING")
    rule = _rule(rule_id="ghost", applies_to="NO_SUCH_SPACE*")
    result = evaluate_building(_building([room]), [rule])
    assert result["checks"] == []
    assert any(item["rule_id"] == "ghost" for item in result["coverage"]["unmatched_rules"])


def test_instances_affected_counts_shared_type_ref():
    a = _room(id="a", name="STUDIO KING", type_ref="guestroom.studio_king", polygon=[(0, 0), (10, 0), (10, 10), (0, 10)])
    b = _room(id="b", name="STUDIO KING", type_ref="guestroom.studio_king", polygon=[(20, 0), (30, 0), (30, 10), (20, 10)])
    results = check_building(_building([a, b]), [_rule(value=50, unit="m2")])
    assert results
    for item in results:
        assert item["instances_affected"] == 2
        assert set(item["affected_space_ids"]) == {"a", "b"}


def test_cross_family_unit_conversion_raises():
    try:
        to_rule_units(10, "m2", area=False)
    except ValueError as exc:
        assert "area" in str(exc).lower() or "length" in str(exc).lower()
    else:
        raise AssertionError("expected cross-family conversion to raise")


def test_unsupported_rules_produce_zero_result_rows():
    room = _room()
    junk = _rule(rule_id="junk", metric="unclassified_requirement", supported=False, value=1, unit="")
    live = _rule(rule_id="live", value=16, unit="m2")
    results = check_building(_building([room]), [junk, live])
    assert all(item["rule_id"] != "junk" for item in results)
    assert all(item["metric"] != "unclassified_requirement" for item in results)
    assert results


def test_imported_guestroom_area_supersedes_baseline():
    imported = _rule(rule_id="rule-page-34", applies_to="guestroom*", metric="area", value=16.0, unit="m2", source_page=34)
    layered = layer_rules([imported])
    baseline = next(rule for rule in layered if rule["rule_id"] == "base-guestroom-area")
    assert baseline["superseded_by"] == "rule-page-34"
    room = _room()
    results = check_building(_building([room]), layered)
    assert all(item["rule_id"] != "base-guestroom-area" for item in results)
    assert any(item["rule_id"] == "rule-page-34" for item in results)


def test_baseline_alone_is_checkable_on_a_generated_home():
    from plancheck.mocks.generation import demo_home

    rules = layer_rules([])
    assert rules
    assert all(rule["origin"] == "baseline" for rule in rules)
    result = evaluate_building(demo_home(), rules)
    assert result["checks"]
    assert result["coverage"]["rules_total"] == len(BASELINE_RULES)


def test_guestroom_area_sums_named_children():
    parent = _room(
        id="g1",
        name="STUDIO KING",
        type_ref="guestroom.studio_king",
        polygon=[(0, 0), (15, 0), (15, 14), (0, 14)],
    )
    bath = _room(
        id="b1",
        name="STUDIO KING Bath",
        category="bathroom",
        type_ref="bathroom.studio_king_bath",
        polygon=[(15, 0), (25, 0), (25, 8), (15, 8)],
        parent_room_id="g1",
    )
    closet = _room(
        id="c1",
        name="STUDIO KING Closet",
        category="storage",
        type_ref="storage.studio_king_closet",
        polygon=[(15, 8), (20, 8), (20, 12), (15, 12)],
        parent_room_id="g1",
    )
    results = check_building(_building([parent, bath, closet]), [_rule(value=20, unit="m2")])
    guest = next(item for item in results if item["entity_id"] == "g1")
    assert guest["status"] == "pass"
    assert 25 <= guest["actual"] <= 35
    assert set(guest["contributing_room_ids"]) == {"g1", "b1", "c1"}
    assert "bedroom" in guest["message"]
    assert "bath" in guest["message"]
    assert "closet" in guest["message"]
    parent_only = to_rule_units(15 * 14, "m2", True)
    assert parent_only < 20


def test_guestroom_child_prefix_fallback_uses_nearest_parent():
    left = _room(id="g-left", name="STUDIO KING", type_ref="guestroom.studio_king", polygon=[(0, 0), (16, 0), (16, 12), (0, 12)])
    right = _room(id="g-right", name="STUDIO KING", type_ref="guestroom.studio_king", polygon=[(40, 0), (56, 0), (56, 12), (40, 12)])
    left_bath = _room(
        id="b-left",
        name="STUDIO KING Bath",
        category="bathroom",
        polygon=[(16, 0), (24, 0), (24, 8), (16, 8)],
    )
    right_bath = _room(
        id="b-right",
        name="STUDIO KING Bath",
        category="bathroom",
        polygon=[(56, 0), (64, 0), (64, 8), (56, 8)],
    )
    results = check_building(_building([left, right, left_bath, right_bath]), [_rule(value=20, unit="m2")])
    by_id = {item["entity_id"]: item for item in results}
    assert "b-left" in by_id["g-left"]["contributing_room_ids"]
    assert "b-right" not in by_id["g-left"]["contributing_room_ids"]
    assert "b-right" in by_id["g-right"]["contributing_room_ids"]
    assert "b-left" not in by_id["g-right"]["contributing_room_ids"]


def test_guestroom_children_are_not_checked_when_parent_matches_area_rule():
    parent = _room(id="g1", name="STUDIO KING", type_ref="guestroom.studio_king", polygon=[(0, 0), (15, 0), (15, 14), (0, 14)])
    bath = _room(
        id="b1",
        name="STUDIO KING Bath",
        category="bathroom",
        polygon=[(15, 0), (25, 0), (25, 8), (15, 8)],
        parent_room_id="g1",
    )
    closet = _room(
        id="c1",
        name="STUDIO KING Closet",
        category="storage",
        polygon=[(15, 8), (20, 8), (20, 12), (15, 12)],
        parent_room_id="g1",
    )
    results = check_building(_building([parent, bath, closet]), [_rule(applies_to="*", value=20, unit="m2")])
    ids = {item["entity_id"] for item in results}
    assert "g1" in ids
    assert "b1" not in ids
    assert "c1" not in ids
    assert next(item for item in results if item["entity_id"] == "g1")["status"] == "pass"


def test_oversized_area_rule_is_needs_scope_review_not_a_violation():
    corridor = _room(
        id="corr",
        name="CORRIDOR",
        category="circulation",
        type_ref="circulation.corridor",
        polygon=[(0, 0), (40, 0), (40, 3.3567), (0, 3.3567)],
    )
    rule = _rule(rule_id="rule-page-61", applies_to="CORRIDOR*", metric="area", value=127, unit="m2", source_page=61)
    result = evaluate_building(_building([corridor]), [rule])
    assert result["violations"] == []
    assert all(item["rule_id"] != "rule-page-61" for item in result["checks"])
    scoped = [item for item in result["coverage"]["unmatched_rules"] if item["rule_id"] == "rule-page-61"]
    assert scoped
    assert scoped[0]["status"] == "needs_scope_review"
    assert "10" in scoped[0]["reason"]
    assert rule["status"] == "needs_scope_review"


def test_wildcard_ballroom_area_does_not_fail_corridors():
    rooms = [
        _room(id="corr", name="CORRIDOR", category="circulation", polygon=[(0, 0), (40, 0), (40, 3.3567), (0, 3.3567)]),
        *[
            _room(
                id=f"cl{i}",
                name="STUDIO KING Closet",
                category="storage",
                polygon=[(100 + i * 6, 0), (105 + i * 6, 0), (105 + i * 6, 4), (100 + i * 6, 4)],
            )
            for i in range(8)
        ],
    ]
    rule = _rule(rule_id="rule-page-61", applies_to="*", metric="area", value=127, unit="m2", source_page=61)
    result = evaluate_building(_building(rooms), [rule])
    assert all(item["status"] != "fail" or item["rule_id"] != "rule-page-61" for item in result["checks"])
    assert any(item["rule_id"] == "rule-page-61" and item.get("status") == "needs_scope_review" for item in result["coverage"]["unmatched_rules"])


def test_auto_approve_writes_source_backed_checks(tmp_path):
    from plancheck.api.routes.desktop import recheck
    from plancheck.core.settings import get_settings
    from plancheck.services.repository import FileProjectRepository

    assert get_settings().auto_approve is True
    room = _room(type_ref="guestroom.studio_king")
    building = _building([room])
    rules = [
        _rule(rule_id="r-area", status="pending", value=50),
        _rule(rule_id="r-side", status="pending", metric="min_side", value=8, unit="m"),
        _rule(rule_id="unsupported", metric="window_area_ratio", supported=False, status="pending", unit="percent", value=8, source_text="Window area is a percentage of floor area.", source_page=40),
    ]
    if get_settings().auto_approve:
        for rule in rules:
            if rule.get("supported"):
                rule["status"] = "approved"
    repo = FileProjectRepository(tmp_path)
    project = repo.create("auto", building, layer_rules(rules))
    project = repo.commit(project.project_id, project.revision, recheck)
    assert project.coverage
    sourced = [check for check in project.checks if check.get("source_text") and check.get("status") == "fail"]
    assert sourced
    assert all(check["metric"] != "unclassified_requirement" for check in project.checks)
    assert all(check.get("instances_affected", 0) > 0 for check in project.checks if check["status"] == "fail")
