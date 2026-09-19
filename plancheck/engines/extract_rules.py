"""Extract compliance rules from a brand-standards PDF. Stub only."""

from __future__ import annotations

import argparse
from pathlib import Path

from plancheck.core.schemas import Project, Ruleset
from plancheck.engines.base import invoke, load_fixture, not_implemented


def run_real(project: Project, standards: list[Path]) -> Ruleset:
    not_implemented("rules")
    raise AssertionError("unreachable")


def run_stub(project: Project, standards: list[Path]) -> Ruleset:
    ruleset = load_fixture("rules.json", Ruleset)
    if standards:
        name = standards[0].name
        for rule in ruleset.rules:
            rule.source_doc = name
    elif project.documents:
        std = next(
            (d for d in project.documents if d.slot == "standards"), None
        )
        if std:
            for rule in ruleset.rules:
                rule.source_doc = std.filename
    return ruleset


def run(project: Project, standards: list[Path]) -> Ruleset:
    return invoke("rules", project, standards)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract rules.json from uploaded standards PDFs."
    )
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    from plancheck.api import storage

    project = storage.load_project(args.project)
    ruleset = run(project, storage.standard_files(args.project))
    storage.save_rules(args.project, ruleset)
    print(f"wrote rules.json ({len(ruleset.rules)} rules)")


if __name__ == "__main__":
    main()
