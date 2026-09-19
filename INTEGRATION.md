# Compliance tap-in points for the agent teammate

This document is the contract between `services/compliance.py` and anything that
proposes edits. Pass/fail is decided only in Python. Do not call a model to
judge geometry.

## `check_building(building, rules) -> list[dict]`

```python
from plancheck.services.compliance import check_building, evaluate_building
from plancheck.core.building import Building

checks: list[dict] = check_building(building, rules)
payload: dict = evaluate_building(building, rules)
# payload == {"checks": [...], "coverage": {...}, "violations": [...], "passes": [...], "quarantined": [...]}
```

`check_building` is a thin wrapper around `evaluate_building(...)["checks"]`.
`apply_reliability(building)` runs after `build_model` and again in desktop
`recheck` before `check_building`. Suspect measurements are returned in
`quarantined` and are never `fail`.

Call sites today:

| Caller | File | What it does with the result |
| --- | --- | --- |
| Desktop recheck | `plancheck/api/routes/desktop.py` `recheck()` | Writes `snapshot["checks"]` and `snapshot["coverage"]`, then the repository persists `mismatches.json` |
| Command apply | `desktop.py` `POST /projects/{pid}/commands` | `apply_commands` then `recheck` |
| Repair apply | `desktop.py` `POST /projects/{pid}/repairs/{run_id}/apply` | Same: mutate building, then `recheck` |
| Rule review | `desktop.py` `PATCH /projects/{pid}/rules/{rule_id}` | Updates the rule, then `recheck` |
| Deterministic repairs | `plancheck/services/repairs.py` | Calls `check_building` before/after candidate `CommandBatch`s |
| Pipeline engine | `plancheck/engines/check.py` `run_real()` | Maps non-`pass` / non-`quarantined` rows into `CheckResult.mismatches` |

Re-run after a `CommandBatch`:

```python
from plancheck.services.commands import apply_commands
from plancheck.services.compliance import evaluate_building

next_building = apply_commands(building, commands, actor="agent")  # copy; failures change nothing
result = evaluate_building(next_building, rules)
```

The desktop already does this inside `recheck` on commit. Prefer that path so
`model.json` / `rules.json` / `mismatches.json` stay in one revision.

## Rule dict

Every rule in `rules.json` is a dict. Baseline rules are the Python list
`plancheck.services.baseline_rules.BASELINE_RULES` (no file I/O). The layered
set is `layer_rules(imported) -> BASELINE_RULES + imported`.

| Field | Type | Notes |
| --- | --- | --- |
| `rule_id` | str | Baseline ids are prefixed `base-` |
| `applies_to` | str | glob, matched against room id / name / category / `type_ref` |
| `metric` | str | Supported: `area`, `min_side`, `aperture_width`, `clear_width` (and `opening_distance` if an imported rule uses it) |
| `operator` | str | `>=`, `<=`, `>`, `<`, `=` |
| `value` | float | Threshold in `unit`. Never substitute a remembered code figure for this number |
| `unit` | str | `m`, `m2`, `ft`, `cm`, … Cross-family conversion raises |
| `source_doc` | str | `"Archetype Baseline"` or the uploaded PDF name |
| `source_page` | int \| null | Baseline has no page |
| `source_section` | str | Public-figure provenance or `"Archetype default — edit to match your jurisdiction"` |
| `source_text` | str | Plain-language sentence shown in Standards |
| `origin` | str | `"baseline"` or `"imported"` |
| `status` | str | `pending` / `approved` / `rejected`. Only `approved` runs |
| `supported` | bool | Unsupported rules never emit result rows |
| `editable` | bool | Baseline is editable |
| `superseded_by` | str | Set on a baseline rule when an imported rule shares `(applies_to, metric)` |
| `excludes` | list[str] | globs; a room matching any exclude is out of scope |
| `applies_to_filter` | dict | `door_to` glob filters openings by a connected room |
| `scope` | str | `room` / `opening` / `opening_pair` |
| `target_ids` | list[str] | If set, only those ids |
| `qualifiers` | list[str] | Human notes, not evaluated |

Layering: imported wins on the same `(applies_to.lower(), metric)`. The baseline
row stays in the list, is greyed in Standards as `overridden by <source_doc>`,
and is skipped in evaluation.

Specificity at check time: among approved supported rules that match the same
`(entity, metric)`, score = literal (non-glob) characters in `applies_to` + 10
per `applies_to_filter` entry + 5 if `excludes` is non-empty + 25 if the glob
matches the entity name. Highest score governs; ties take the more stringent
threshold. The loser id is recorded on the mismatch as `superseded_by`.

## Mismatch / check dict

`check_building` returns one dict per `(entity, metric)` that a supported
approved rule actually matched. Status is `pass`, `fail`, `cannot_verify`, or
`quarantined`.

Unsupported rules (`supported=false` or metric outside the whitelist) produce
**zero** rows. They only appear in `coverage.by_missing_metric`.

`cannot_verify` is reserved for a supported rule that matched a real entity but
could not measure it (degenerate polygon, `needs_review`, confidence < 0.6).
The message names the missing field or failed check.

`quarantined` is a measurement more than 3 MAD from its group median
(`type_ref` for rooms, all openings as one group). It is listed and counted,
never dropped, and never reported as a violation. The Checks tab line reads
`N violations · M measurements quarantined as unreliable`.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | str | `check-` + hash |
| `rule_id` | str | Winning rule |
| `entity_id` | str | Room or opening id |
| `entity_ids` | list[str] | Same, or a pair for opening distance |
| `type_ref` | str | Room type or category |
| `metric` | str | Canonical metric name |
| `status` / `severity` | str | `pass` / `fail` / `cannot_verify` / `quarantined` |
| `actual` | float \| null | In the **rule's** unit |
| `required` | float | Rule threshold |
| `unit` / `operator` | str | Copied from the rule |
| `delta` | float \| null | `actual - required` |
| `message` | str | Includes the reason when unverifiable |
| `instances_affected` | int | Count of rooms sharing this room's `type_ref`, computed at check time, never read off `Room.instance_count` |
| `affected_space_ids` | list[str] | Those room ids |
| `source_doc` / `source_page` / `source_text` / `source_section` |  | Provenance |
| `model_confidence` | float | From the room |
| `assumption` | str | Set when clear width is derived: `clear width = leaf width − 2 in (stop and hinge projection)` |
| `pinch_polygon` | list[[x,y]] \| null | Failed `min_side` morphological pinch, in feet, for highlighting |
| `superseded_by` | str | More general rule that lost specificity |

`min_side` uses morphological opening, not the bounding-box short side:

```text
opened = poly.buffer(-w/2, join_style=mitre).buffer(w/2, join_style=mitre)
pinch  = poly.difference(opened)
```

If opening reconstructs the polygon, the space is at least `w` wide everywhere.
Fewer than four vertices, zero area, or a self-intersection → `cannot_verify`.

Clear width: `clear_ft = width_ft - 2/12` when `opening.clear_width_ft` is null.

## Coverage

`evaluate_building` / `snapshot["coverage"]` / `mismatches.json`:

```json
{
  "rules_total": 283,
  "rules_supported": 28,
  "rules_unsupported": 255,
  "rules_superseded": 1,
  "by_missing_metric": [{"metric": "unclassified_requirement", "count": 255, "example_rule_ids": ["…"]}],
  "unmatched_rules": [{"rule_id": "…", "applies_to": "engineering_office", "reason": "applies_to matched no rooms or openings in the current model."}],
  "violations": 12,
  "quarantined": 31,
  "extraction_warnings": 1
}
```

`unmatched_rules` is the loud channel: a glob that hits zero rooms looks like a
pass unless it is listed here. The Checks tab shows a one-line summary
(`38 of 147 rules checkable`). Do not treat unmatched as `cannot_verify` rows.

## Commands an agent may emit

`plancheck/services/commands.py` `apply_commands(building, commands, actor="user"|"agent")`.

Kinds:

- `move_vertex`, `move_wall`, `offset_partition`
- `update_wall`, `unlock_wall` (user only)
- `create_wall`, `split_wall`, `join_walls`
- `place_opening`, `update_opening`
- `place_object`, `update_object`, `duplicate`
- `set_material`, `apply_room_material_to_type`, `set_environment`
- `rename_room`, `rotate_selection`, `delete`

Unknown kinds raise `CommandError`. The building is copied first; a failed
batch leaves the original untouched.

## Loadbearing guard

In `apply_commands`, `_wall_allowed(wall, actor)`:

```python
if w.locked or (actor == "agent" and w.structural != "nonstructural"):
    raise CommandError(...)
```

Any agent proposal that touches a wall with `structural == "loadbearing"`
(or `unknown`, or `locked=True`) **must be rejected in this function**. Do not
work around it in the provider. `unlock_wall` is user-only.

## The three files

| File | Who writes it | Contents |
| --- | --- | --- |
| `revisions/<n>/model.json` | `FileProjectRepository._write_snapshot` | Full snapshot: `building`, `rules`, `checks`, `coverage` |
| `revisions/<n>/rules.json` | same | `{ "rules": [...] }` — baseline + imported, after `layer_rules` |
| `revisions/<n>/mismatches.json` | same | `{ "checks": [...], "coverage": {...} }` |

Import (`desktop.py` `/import`) auto-approves `supported=true` extracted rules
when `PLANCHECK_AUTO_APPROVE` is true, then `layer_rules(imported)`. Generate
(`/generate`) stores `layer_rules([])` — baseline alone. Both commit through
`recheck`, which is the only place pass/fail is recorded.
