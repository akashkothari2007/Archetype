from plancheck.core.building import Room
from plancheck.services.compliance import check_building, matches_room


def _room(**kw):
    data = dict(id="r1", floor_id="f1", name="201", category="guestroom", type_ref="", polygon=[(0, 0), (16, 0), (16, 20), (0, 20)])
    data.update(kw)
    return Room(**data)


def test_guestroom_glob_matches_category_when_type_ref_empty():
    room = _room(type_ref="")
    rule = {"applies_to": "guestroom*", "metric": "area"}
    assert matches_room(room, rule)
    assert not matches_room(_room(category="circulation", name="CORRIDOR"), rule)


def test_guestroom_glob_matches_type_ref():
    room = _room(category="other", type_ref="guestroom.studio_king", name="STUDIO KING")
    assert matches_room(room, {"applies_to": "guestroom*"})


def test_pending_rules_do_not_emit_checks():
    room = _room(confidence=0.85, needs_review=False)
    from plancheck.core.building import Building, Floor

    building = Building(floors=[Floor(id="f1", name="Ground")], rooms=[room])
    pending = {
        "rule_id": "r1",
        "applies_to": "guestroom*",
        "metric": "area",
        "operator": ">=",
        "value": 16,
        "unit": "m2",
        "status": "pending",
        "supported": True,
        "source_text": "Area: 16 m²",
        "source_page": 34,
    }
    assert check_building(building, [pending]) == []
    approved = dict(pending, status="approved")
    results = check_building(building, [approved])
    assert results
    assert results[0]["source_text"]
    assert results[0]["source_page"] == 34


def test_auto_approve_writes_source_backed_checks(tmp_path):
    from plancheck.api.routes.desktop import recheck
    from plancheck.core.building import Building, Floor
    from plancheck.core.settings import get_settings
    from plancheck.services.repository import FileProjectRepository

    assert get_settings().auto_approve is True
    room = _room(confidence=0.85, needs_review=False, type_ref="guestroom.studio_king")
    building = Building(floors=[Floor(id="f1", name="Ground")], rooms=[room])
    rules = [
        {
            "rule_id": f"r{i}",
            "applies_to": "guestroom*",
            "metric": "area",
            "operator": ">=",
            "value": value,
            "unit": "m2",
            "status": "pending",
            "supported": True,
            "source_text": f"Area: {value} m² minimum",
            "source_page": 34,
        }
        for i, value in enumerate((16.0, 20.0, 30.0, 40.0, 50.0, 6.0))
    ]
    rules.append(
        {
            "rule_id": "unsupported",
            "applies_to": "guestroom*",
            "metric": "window_area_ratio",
            "operator": ">=",
            "value": 8,
            "unit": "percent",
            "status": "pending",
            "supported": False,
            "source_text": "Window area is a percentage of floor area.",
            "source_page": 40,
        }
    )
    if get_settings().auto_approve:
        for rule in rules:
            if rule.get("supported"):
                rule["status"] = "approved"
    repo = FileProjectRepository(tmp_path)
    project = repo.create("auto", building, rules)
    project = repo.commit(project.project_id, project.revision, recheck)
    checks = project.checks
    assert sum(1 for rule in project.rules if rule.get("status") == "approved") == 6
    assert all(rule.get("status") == "pending" for rule in project.rules if not rule.get("supported"))
    sourced = [check for check in checks if check.get("source_text") and check.get("source_page")]
    assert len(sourced) >= 5
