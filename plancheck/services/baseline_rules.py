"""Hardcoded baseline requirements. No file loading; edit the list in this module."""
from __future__ import annotations

from typing import Any


def _rule(
    rule_id: str,
    applies_to: str,
    metric: str,
    value: float,
    unit: str,
    source_section: str,
    source_text: str,
    *,
    operator: str = ">=",
    scope: str = "room",
    excludes: list[str] | None = None,
    applies_to_filter: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "applies_to": applies_to,
        "metric": metric,
        "operator": operator,
        "value": value,
        "unit": unit,
        "source_doc": "Archetype Baseline",
        "source_page": None,
        "source_label": "",
        "source_section": source_section,
        "source_text": source_text,
        "extraction": "baseline",
        "origin": "baseline",
        "status": "approved",
        "supported": True,
        "editable": True,
        "scope": scope,
        "target_ids": [],
        "qualifiers": [],
        "excludes": excludes or [],
        "applies_to_filter": applies_to_filter or {},
        "superseded_by": "",
    }


ADA = "ADA / ABA 2010 — 32 in (81 cm) clear door width. Public figure; confirm the edition your jurisdiction adopts."
IBC_CORRIDOR = "IBC corridor egress width — 44 in (1.12 m). Public figure; confirm the edition your jurisdiction adopts."
ADA_TURN = "ADA / ABA 2010 — 60 in (1.52 m) turning space. Public figure; confirm the edition your jurisdiction adopts."
DEFAULT = "Archetype default — edit to match your jurisdiction"


BASELINE_RULES: list[dict[str, Any]] = [
    _rule(
        "base-guestroom-area",
        "guestroom*",
        "area",
        16.0,
        "m2",
        DEFAULT,
        "Guestrooms should provide at least 16 m² of interior floor area.",
        excludes=["*Bath*", "*Closet*"],
    ),
    _rule(
        "base-guestroom-min-side",
        "guestroom*",
        "min_side",
        3.0,
        "m",
        DEFAULT,
        "Guestrooms should be at least 3.0 m across their narrowest clear dimension.",
        excludes=["*Bath*", "*Closet*"],
    ),
    _rule(
        "base-bath-area",
        "*Bath*",
        "area",
        4.2,
        "m2",
        DEFAULT,
        "Bathrooms should provide at least 4.2 m² of interior floor area.",
    ),
    _rule(
        "base-bath-min-side",
        "*Bath*",
        "min_side",
        1.5,
        "m",
        DEFAULT,
        "Bathrooms should be at least 1.5 m across their narrowest clear dimension.",
    ),
    _rule(
        "base-closet-min-side",
        "*Closet*",
        "min_side",
        0.6,
        "m",
        DEFAULT,
        "Closets should be at least 0.6 m across their narrowest clear dimension.",
    ),
    _rule(
        "base-corridor-min-side",
        "CORRIDOR*",
        "min_side",
        1.12,
        "m",
        IBC_CORRIDOR,
        "Corridors used for egress should be at least 1.12 m wide at every point along the path.",
    ),
    _rule(
        "base-stair-min-side",
        "STAIR*",
        "min_side",
        1.12,
        "m",
        IBC_CORRIDOR,
        "Stair runs should keep at least 1.12 m of clear width.",
    ),
    _rule(
        "base-acc-min-side",
        "ACC.*",
        "min_side",
        1.52,
        "m",
        ADA_TURN,
        "Accessible units should keep at least 1.52 m on the narrowest clear dimension so a 60 in turning space can fit.",
        excludes=["*Bath*", "*Closet*"],
    ),
    _rule(
        "base-guestroom-entry-clear",
        "door",
        "clear_width",
        0.81,
        "m",
        ADA,
        "Guestroom entry doors should provide at least 0.81 m of clear opening width.",
        scope="opening",
        excludes=["*Bath*", "*Closet*"],
        applies_to_filter={"door_to": "guestroom*"},
    ),
    _rule(
        "base-bedroom-area",
        "bedroom*",
        "area",
        10.0,
        "m2",
        DEFAULT,
        "Bedrooms should provide at least 10 m² of interior floor area.",
    ),
    _rule(
        "base-bedroom-min-side",
        "bedroom*",
        "min_side",
        2.4,
        "m",
        DEFAULT,
        "Bedrooms should be at least 2.4 m across their narrowest clear dimension.",
    ),
    _rule(
        "base-circulation-min-side",
        "circulation",
        "min_side",
        1.12,
        "m",
        IBC_CORRIDOR,
        "Circulation spaces should keep at least 1.12 m of clear width.",
    ),
    _rule(
        "base-door-aperture",
        "door",
        "aperture_width",
        0.76,
        "m",
        DEFAULT,
        "Doors should have a leaf at least 0.76 m wide before stop and hinge deductions.",
        scope="opening",
    ),
]


def _as_dict(rule: Any) -> dict[str, Any]:
    if hasattr(rule, "model_dump"):
        return rule.model_dump()
    return dict(rule)


def _metric(rule: dict[str, Any]) -> str:
    name = str(rule.get("metric", ""))
    aliases = {
        "room.area": "area",
        "room.min_side": "min_side",
        "width": "min_side",
        "door.aperture_width": "aperture_width",
        "door.clear_width": "clear_width",
        "opening.separation": "opening_distance",
    }
    return aliases.get(name, name)


def layer_rules(imported: list[Any] | None = None, baseline: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """BASELINE_RULES first, then imported rules. Matching (applies_to, metric) lets the import win."""
    incoming = [_as_dict(rule) for rule in (imported or [])]
    winners: dict[tuple[str, str], str] = {}
    for rule in incoming:
        key = (str(rule.get("applies_to", "")).lower(), _metric(rule))
        rule_id = str(rule.get("rule_id") or "")
        if rule_id:
            winners[key] = rule_id
    layered: list[dict[str, Any]] = []
    for raw in list(baseline if baseline is not None else BASELINE_RULES):
        rule = dict(raw)
        key = (str(rule.get("applies_to", "")).lower(), _metric(rule))
        if key in winners:
            rule["superseded_by"] = winners[key]
        layered.append(rule)
    layered.extend(incoming)
    return layered
