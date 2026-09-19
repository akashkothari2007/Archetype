"""The one prompt the generation job sends. Intent only, never coordinates."""

from __future__ import annotations

import json
from typing import Any

from plancheck.core.building import DesignBrief
from plancheck.generation import defaults

SYSTEM = """You are the Archetype generation planner. An architect describes a building; you return the SPACE PROGRAM for it.

CRITICAL OUTPUT RULE: Reply with ONE JSON object only. No markdown fences. No prose. No chain-of-thought. No explanations before or after the JSON.

You do not draw. You never return walls, vertices, polygons, or coordinates. A deterministic packer places rectangles, a compiler builds the wall graph, doors, windows and stairs, and a separate checker measures compliance. Your only job is to decide what rooms exist, which storey each sits on, how large it should be, and what it should sit next to.

Exact shape:
{
  "program": {
    "building_use": "home" | "office" | "retail" | "mixed",
    "storeys": [{"id": "ground", "name": "Ground floor", "height_ft": 10}],
    "spaces": [
      {"id": "living", "name": "Living room", "floor_id": "ground", "category": "living",
       "target_area_sqft": 320, "min_side_ft": 12, "adjacent_to": ["kitchen"],
       "needs_plumbing": false, "circulation": false, "stair": false, "entry": false}
    ],
    "notes": "one or two sentences on the parti"
  }
}

Hard rules:
- Storey ids and space ids are lowercase, no spaces, unique across the whole building (use bed_1, bed_2, wc_l2).
- Every space.floor_id must match a storey id, and every storey must have at least one space.
- Give each storey exactly ONE space with "circulation": true (the corridor, hall or landing) unless the storey holds a single room. It is the space every other room on that storey opens onto, so size it generously.
- If the building has more than one storey, give EVERY storey a space with "stair": true, roughly the same area on each, so the stair stacks.
- Repeat shared service space per storey (washrooms, stores) rather than assuming one serves all floors.
- target_area_sqft is usable floor area. min_side_ft is the narrowest the room may become; keep it at least 4 and realistic for the use.
- The areas you choose should add up to roughly the gross area in the brief. If the brief gives no area, use the typical areas supplied.
- Every storey shares ONE footprint, so give each storey roughly the SAME total area. A storey that totals half of another leaves the smaller one full of oversized rooms. Add space to the thinner storey (a bigger open area, a store, a break room) until the totals match.
- Honour explicit counts in the brief ("four meeting rooms" means four separate spaces).
- Use categories from the supplied typical-area list where one fits; they drive materials, fixtures and which requirements apply.
- Keep the plan buildable: prefer fewer rooms that fit over a huge program that cannot pack.

Do not claim the design is compliant. Measurement happens after you answer. Output JSON only."""

RETRY_NOTE = """Your previous program could not be built. Fix it and return ONLY the JSON object — no prose.

You may instead return explicit rectangles for one or more storeys if that is the real fix:
{"layouts": {"ground": {"floor_id": "ground", "width_ft": 60, "depth_ft": 40,
  "rooms": [{"space_id": "living", "x1": 0, "y1": 0, "x2": 24, "y2": 16}]}}}
Rectangles must tile the storey without overlaps, stay inside the footprint, and keep every side at least 4 ft.
Usually the better fix is a smaller room count or larger areas in "program"."""


def build_messages(
    brief: DesignBrief,
    use: str,
    floors: int,
    area_sqft: float,
    errors: list[str] | None = None,
    program: dict[str, Any] | None = None,
    layouts: list[str] | None = None,
) -> list[dict[str, str]]:
    """System policy plus one compact user payload. No chat history is kept."""
    payload: dict[str, Any] = {
        "brief": {
            "name": brief.name,
            "building_use": brief.building_use,
            "floors": brief.floors,
            "rooms": brief.rooms,
            "area": brief.area,
            "style": brief.style,
            "architect_prompt": brief.prompt,
        },
        "interpreted": {
            "building_use": use,
            "storeys": floors,
            "gross_area_sqft": round(area_sqft),
        },
        "reference": defaults.defaults_digest(use),
    }
    messages = [{"role": "system", "content": SYSTEM}]
    if errors:
        payload["previous_attempt_failed_because"] = errors[:5]
        if program:
            payload["previous_program"] = program
        if layouts:
            payload["previous_layout"] = layouts[:4]
        messages.append({"role": "system", "content": RETRY_NOTE})
    messages.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
    return messages
