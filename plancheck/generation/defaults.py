"""Per-use heuristics, brief parsing, and the starter requirement packs.

These are design defaults and project requirements, not building code. They are
injected into the prompt so the model does not have to guess, and they seed the
Standards tab so generated geometry is measured the moment it exists.
"""

from __future__ import annotations

import fnmatch
import math
import re
from dataclasses import dataclass, field

from plancheck.generation.program import USES, BuildingUse

SQFT_PER_SQM = 10.763910416709722
DOOR_WIDTH_FT = 3.0
DOOR_HEIGHT_FT = 7.0
WINDOW_WIDTH_FT = 5.0
WINDOW_HEIGHT_FT = 4.0
WINDOW_SILL_FT = 3.0


@dataclass(frozen=True)
class UseProfile:
    key: BuildingUse
    label: str
    floor_height_ft: float
    corridor_width_ft: float
    aspect: float
    default_area_sqft: float
    default_floors: int
    typical_areas: dict[str, float]
    ordering: tuple[str, ...]
    guidance: tuple[str, ...] = field(default_factory=tuple)


PROFILES: dict[str, UseProfile] = {
    "home": UseProfile(
        key="home",
        label="Home",
        floor_height_ft=10,
        corridor_width_ft=4,
        aspect=1.35,
        default_area_sqft=2400,
        default_floors=2,
        typical_areas={
            "living": 320, "kitchen": 200, "dining": 180, "bedroom": 180,
            "primary_bedroom": 260, "bathroom": 60, "office": 130, "storage": 60,
            "utility": 70, "circulation": 140, "stair": 90, "garage": 400,
        },
        ordering=("living", "kitchen", "dining", "circulation", "stair", "office", "bedroom", "bathroom", "utility", "storage"),
        guidance=(
            "Put living, kitchen and dining together on the entry storey.",
            "Bedrooms and bathrooms belong on the upper storey when there is more than one.",
            "Stack bathrooms above each other or beside one another so plumbing shares a wall.",
        ),
    ),
    "office": UseProfile(
        key="office",
        label="Office",
        floor_height_ft=12,
        corridor_width_ft=6,
        aspect=1.5,
        default_area_sqft=8000,
        default_floors=2,
        typical_areas={
            "reception": 300, "open_office": 1600, "office": 140, "meeting": 240,
            "boardroom": 420, "break": 260, "bathroom": 120, "storage": 100,
            "server": 90, "circulation": 320, "stair": 130,
        },
        ordering=("reception", "circulation", "stair", "open_office", "meeting", "boardroom", "office", "break", "bathroom", "server", "storage"),
        guidance=(
            "Reception sits on the entry storey next to the stair core.",
            "A corridor should reach every enclosed room; keep it at least 6 ft wide.",
            "Repeat the stair and washrooms in the same position on every storey.",
        ),
    ),
    "retail": UseProfile(
        key="retail",
        label="Retail",
        floor_height_ft=13,
        corridor_width_ft=6,
        aspect=1.4,
        default_area_sqft=5000,
        default_floors=1,
        typical_areas={
            "sales": 2400, "entry": 200, "fitting": 90, "stock": 500,
            "receiving": 260, "bathroom": 100, "break": 180, "office": 140,
            "circulation": 220, "stair": 120,
        },
        ordering=("entry", "sales", "fitting", "circulation", "stair", "office", "break", "bathroom", "stock", "receiving"),
        guidance=(
            "Give the sales floor the largest single rectangle, facing the street edge.",
            "Stock, receiving and staff rooms line the back of the plan.",
        ),
    ),
    "mixed": UseProfile(
        key="mixed",
        label="Mixed use",
        floor_height_ft=12,
        corridor_width_ft=6,
        aspect=1.45,
        default_area_sqft=9000,
        default_floors=3,
        typical_areas={
            "lobby": 420, "sales": 1400, "retail": 1400, "open_office": 1400,
            "office": 150, "meeting": 240, "apartment": 700, "living": 300,
            "bedroom": 180, "kitchen": 140, "bathroom": 110, "break": 220,
            "storage": 120, "circulation": 320, "stair": 130,
        },
        ordering=("lobby", "entry", "circulation", "stair", "sales", "retail", "open_office", "living", "kitchen", "meeting", "office", "bedroom", "break", "bathroom", "storage"),
        guidance=(
            "Keep the public uses (lobby, retail) on the ground storey.",
            "Put workplace or residential space above, sharing one stair core.",
        ),
    ),
}

_USE_WORDS: tuple[tuple[str, BuildingUse], ...] = (
    ("mixed", "mixed"), ("multi-use", "mixed"), ("multi use", "mixed"),
    ("office", "office"), ("workplace", "office"), ("studio", "office"),
    ("coworking", "office"), ("clinic", "office"), ("school", "office"),
    ("retail", "retail"), ("shop", "retail"), ("store", "retail"),
    ("boutique", "retail"), ("showroom", "retail"), ("restaurant", "retail"),
    ("cafe", "retail"), ("home", "home"), ("house", "home"),
    ("residential", "home"), ("apartment", "home"), ("villa", "home"),
    ("cabin", "home"), ("duplex", "home"),
)


def normalise_use(*texts: str) -> BuildingUse:
    """Pick a packer family from whatever the architect typed."""
    haystack = " ".join(t.lower() for t in texts if t)
    if "mixed" in haystack or ("retail" in haystack and ("office" in haystack or "apartment" in haystack)):
        return "mixed"
    for word, use in _USE_WORDS:
        if word in haystack:
            return use
    return "home"


def profile(use: str) -> UseProfile:
    return PROFILES.get(use if use in USES else normalise_use(use), PROFILES["home"])


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "single": 1, "double": 2,
}


def parse_floor_count(*texts: str, default: int = 2) -> int:
    """Read a storey count from '3', 'three floors', 'G+2', 'two-storey'."""
    for text in texts:
        if not text:
            continue
        lowered = text.lower()
        ground_plus = re.search(r"\bg\s*\+\s*(\d+)\b", lowered)
        if ground_plus:
            return max(1, min(8, int(ground_plus.group(1)) + 1))
        digits = re.search(r"\b(\d{1,2})\b", lowered)
        if digits:
            return max(1, min(8, int(digits.group(1))))
        for word, value in _NUMBER_WORDS.items():
            if re.search(rf"\b{word}\b", lowered):
                return max(1, min(8, value))
    return default


def parse_area_sqft(*texts: str, default: float = 2400) -> float:
    """Read a gross area in square feet from '2,400 sq ft' or '220 m2'."""
    for text in texts:
        if not text:
            continue
        lowered = text.lower().replace(",", "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*(sq\.?\s*m|square\s*met|m2|m²|sqm)", lowered)
        if match:
            return max(200.0, float(match.group(1)) * SQFT_PER_SQM)
        match = re.search(r"(\d+(?:\.\d+)?)\s*(sq\.?\s*f|square\s*f|sf\b|ft2|ft²|sqft)", lowered)
        if match:
            return max(200.0, float(match.group(1)))
        match = re.search(r"\b(\d{3,6}(?:\.\d+)?)\b", lowered)
        if match:
            return max(200.0, float(match.group(1)))
    return default


def footprint_for(area_sqft: float, floors: int, aspect: float) -> tuple[float, float]:
    """Plate proportions for a target gross area spread over N storeys."""
    plate = max(240.0, float(area_sqft) / max(1, floors))
    depth = math.sqrt(plate / aspect)
    return round(depth * aspect, 2), round(depth, 2)


def typical_area(use: str, category: str, fallback: float = 150.0) -> float:
    return profile(use).typical_areas.get(category, fallback)


def _rule(
    rule_id: str,
    applies_to: str,
    metric: str,
    value: float,
    unit: str,
    text: str,
    scope: str = "room",
    operator: str = ">=",
) -> dict:
    return {
        "rule_id": rule_id,
        "applies_to": applies_to,
        "metric": metric,
        "operator": operator,
        "value": value,
        "unit": unit,
        "source_doc": "Archetype starter requirements",
        "source_page": 1,
        "source_text": text,
        "source_section": "Generated project requirements - not building code",
        "source_label": "Starter requirement",
        "extraction": "generated",
        "status": "approved",
        "scope": scope,
        "target_ids": [],
        "qualifiers": [],
        "supported": True,
    }


# Only metrics compliance.py can actually measure: area, min_side, aperture_width.
_PACKS: dict[str, list[dict]] = {
    "home": [
        _rule("GEN-DOOR-001", "door", "aperture_width", 0.9, "m",
              "Modelled door apertures should be at least 0.90 m wide.", scope="opening"),
        _rule("GEN-BED-001", "bedroom", "area", 7.0, "m2",
              "A bedroom should have at least 7.0 m2 of floor area."),
        _rule("GEN-BED-002", "bedroom", "min_side", 2.1, "m",
              "A bedroom should be at least 2.10 m across its narrow dimension."),
        _rule("GEN-BATH-001", "bathroom", "area", 3.3, "m2",
              "A bathroom should have at least 3.30 m2 of floor area."),
    ],
    "office": [
        _rule("GEN-DOOR-001", "door", "aperture_width", 0.9, "m",
              "Modelled door apertures should be at least 0.90 m wide.", scope="opening"),
        _rule("GEN-CORR-001", "circulation", "min_side", 1.5, "m",
              "A corridor should stay at least 1.50 m wide along its length."),
        _rule("GEN-MEET-001", "meeting", "area", 10.0, "m2",
              "A meeting room should have at least 10.0 m2 of floor area."),
        _rule("GEN-WC-001", "bathroom", "area", 2.5, "m2",
              "A washroom should have at least 2.50 m2 of floor area."),
        _rule("GEN-OFF-001", "office", "area", 8.0, "m2",
              "An enclosed office should have at least 8.0 m2 of floor area."),
    ],
    "retail": [
        _rule("GEN-DOOR-001", "door", "aperture_width", 0.9, "m",
              "Modelled door apertures should be at least 0.90 m wide.", scope="opening"),
        _rule("GEN-SALES-001", "sales", "min_side", 4.0, "m",
              "The sales floor should stay at least 4.00 m across its narrow dimension."),
        _rule("GEN-WC-001", "bathroom", "area", 2.5, "m2",
              "A washroom should have at least 2.50 m2 of floor area."),
        _rule("GEN-STOCK-001", "stock", "area", 12.0, "m2",
              "Stock rooms should have at least 12.0 m2 of floor area."),
    ],
}
_PACKS["mixed"] = _PACKS["office"] + [
    _rule("GEN-LIV-001", "living", "area", 12.0, "m2",
          "A living space should have at least 12.0 m2 of floor area."),
    _rule("GEN-BED-001", "bedroom", "area", 7.0, "m2",
          "A bedroom should have at least 7.0 m2 of floor area."),
]


def rule_pack(use: str, categories: set[str] | None = None) -> list[dict]:
    """Starter requirements, filtered to what this building actually contains.

    Shipping a rule with nothing to measure produces a permanent
    ``cannot_verify`` row, which reads as a defect rather than a requirement.
    """
    rules = [dict(rule) for rule in _PACKS.get(profile(use).key, _PACKS["home"])]
    if categories is None:
        return rules
    kept = []
    for rule in rules:
        pattern = rule["applies_to"].lower()
        # Match exactly how compliance.matches_room will, or the rule can never fire.
        if rule["scope"] == "opening" or pattern == "*":
            kept.append(rule)
        elif any(fnmatch.fnmatchcase(category.lower(), pattern) for category in categories):
            kept.append(rule)
    return kept


def defaults_digest(use: str) -> str:
    """Compact reference injected into the prompt instead of a tool round trip."""
    active = profile(use)
    areas = ", ".join(f"{name} ~{area:g} sqft" for name, area in active.typical_areas.items())
    lines = [
        f"Building use: {active.label} ({active.key})",
        f"Typical storey height {active.floor_height_ft:g} ft; corridors {active.corridor_width_ft:g} ft wide.",
        f"Typical areas: {areas}.",
    ]
    lines.extend(f"- {tip}" for tip in active.guidance)
    packs = rule_pack(active.key)
    lines.append("Requirements that will be measured on the result:")
    lines.extend(
        f"- {rule['applies_to']}: {rule['metric']} {rule['operator']} {rule['value']:g} {rule['unit']}"
        for rule in packs
    )
    return "\n".join(lines)
