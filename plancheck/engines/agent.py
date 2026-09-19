"""Propose CAD edits from mismatches.json + model.json. Stub only.

The agent may only propose edits that check.py can re-verify. It writes
proposed_edits.json only — never mutates model.json, never touches a PDF.
It must refuse edits whose affected walls have cls loadbearing. MEP is
read-only.
"""

from __future__ import annotations

import argparse

from plancheck.core.schemas import CheckResult, Model, ProposedEdits
from plancheck.engines.base import invoke, load_fixture, not_implemented


def run_real(mismatches: CheckResult, model: Model) -> ProposedEdits:
    not_implemented("agent")
    raise AssertionError("unreachable")


def run_stub(mismatches: CheckResult, model: Model) -> ProposedEdits:
    edits = load_fixture("proposed_edits.json", ProposedEdits)
    ids = [m.id for m in mismatches.mismatches]
    type_ids = [st.type_id for st in model.space_types]
    counts = {st.type_id: st.instance_count for st in model.space_types}
    for i, edit in enumerate(edits.proposed_edits):
        if ids:
            edit.mismatch_id = ids[i % len(ids)]
        if type_ids and edit.target not in type_ids:
            edit.target = type_ids[min(i, len(type_ids) - 1)]
        if edit.target in counts:
            edit.affects_instances = counts[edit.target]
    return edits


def run(mismatches: CheckResult, model: Model) -> ProposedEdits:
    return invoke("agent", mismatches, model)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Propose edits from mismatches.json and model.json."
    )
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    from plancheck.api import storage

    mismatches = storage.load_mismatches(args.project)
    model = storage.load_model(args.project)
    edits = run(mismatches, model)
    storage.save_proposed_edits(args.project, edits)
    print(
        f"wrote proposed_edits.json ({len(edits.proposed_edits)} edits)"
    )


if __name__ == "__main__":
    main()
