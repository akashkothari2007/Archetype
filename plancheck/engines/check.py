"""Check model.json against rules.json. Stub only."""

from __future__ import annotations

import argparse

from plancheck.core.schemas import CheckResult, Model, Ruleset
from plancheck.engines.base import invoke, load_fixture, not_implemented


def run_real(model: Model, rules: Ruleset) -> CheckResult:
    not_implemented("check")
    raise AssertionError("unreachable")


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
