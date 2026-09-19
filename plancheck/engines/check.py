"""Verify approved rules using deterministic canonical geometry measurements."""

from __future__ import annotations

import argparse
import math

from plancheck.core.schemas import CheckResult, Mismatch, Model, Ruleset
from plancheck.core.building import Building, Floor, Room
from plancheck.engines.base import invoke, load_fixture
from plancheck.services.compliance import check_building


def run_real(model: Model, rules: Ruleset) -> CheckResult:
    building = model.building
    if building is None:
        # Backwards-compatible read projection; the v2 editor always supplies
        # its canonical building. Never trust cached legacy area/bbox numbers.
        building = Building(floors=[Floor(id=f"level-{l.index}",name=l.name) for l in model.levels])
        types = {t.type_id:t for t in model.space_types}
        for space in model.spaces:
            template = types.get(space.type_ref)
            if template is None: continue
            angle = math.radians(space.rotation_deg)
            def point(p):
                x,y = p
                if space.mirrored: x=-x
                return (space.origin_ft[0]+x*math.cos(angle)-y*math.sin(angle),
                        space.origin_ft[1]+x*math.sin(angle)+y*math.cos(angle))
            for room_type in [template,*template.children]:
                building.rooms.append(Room(id=space.space_id+("/"+room_type.type_id if room_type is not template else ""),
                    floor_id=f"level-{space.level}",name=room_type.name,category=room_type.category,
                    type_ref=room_type.type_id,polygon=[point(p) for p in room_type.boundary_ft],
                    confidence=min(room_type.confidence,space.confidence)))
    checks = check_building(building,[r.model_dump() for r in rules.rules])
    return CheckResult(mismatches=[Mismatch.model_validate(c) for c in checks if c["status"] != "pass"])


def run_stub(model: Model, rules: Ruleset) -> CheckResult:
    result = load_fixture("mismatches.json", CheckResult)
    type_ids = {st.type_id for st in model.space_types}
    space_ids = [sp.space_id for sp in model.spaces]
    rule_ids = {r.rule_id for r in rules.rules}
    for mismatch in result.mismatches:
        if mismatch.type_ref not in type_ids and type_ids:
            mismatch.type_ref = next(iter(type_ids))
        if mismatch.rule_id not in rule_ids and rule_ids:
            mismatch.rule_id = next(iter(rule_ids))
        if space_ids and not mismatch.affected_space_ids:
            mismatch.affected_space_ids = space_ids[: mismatch.instances_affected]
    return result


def run(model: Model, rules: Ruleset) -> CheckResult:
    return invoke("check", model, rules)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check model.json against rules.json."
    )
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    from plancheck.api import storage

    model = storage.load_model(args.project)
    rules = storage.load_rules(args.project)
    result = run(model, rules)
    storage.save_mismatches(args.project, result)
    print(f"wrote mismatches.json ({len(result.mismatches)} mismatches)")


if __name__ == "__main__":
    main()
