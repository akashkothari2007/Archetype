"""The one prompt the generation job sends. Intent only, never coordinates."""

from __future__ import annotations

import json
from typing import Any

from plancheck.core.building import DesignBrief
from plancheck.generation import defaults

SYSTEM = """You are the Archetype generation planner. An architect describes ANY kind of building — house, hospital, school, hotel, warehouse, mosque, office, shop, mixed-use, or something unnamed — and you return a SPACE PROGRAM the packer can build.

CRITICAL OUTPUT RULE: Reply with ONE JSON object only. No markdown fences. No prose. No chain-of-thought. No explanations before or after the JSON.

You do not draw. You never return walls, vertices, polygons, or coordinates. A deterministic packer places rectangles, a compiler builds the wall graph, doors, windows and stairs, and a checker measures compliance. Your only job is to decide which spaces exist, which storey each sits on, how large it should be, and what it should sit next to.

Exact shape:
{
  "program": {
    "building_use": "home" | "office" | "retail" | "mixed",
    "storeys": [{"id": "ground", "name": "Ground floor", "height_ft": 10}],
    "spaces": [
      {"id": "lobby", "name": "Lobby", "floor_id": "ground", "category": "circulation",
       "target_area_sqft": 400, "min_side_ft": 12, "adjacent_to": ["stair_g"],
       "needs_plumbing": false, "circulation": true, "stair": false, "entry": true}
    ],
    "notes": "one or two sentences on the parti"
  }
}

building_use is the PACKER FAMILY, not the building's name:
- home: houses, apartments, villas
- office: workplaces, clinics, hospitals, schools (corridor + core)
- retail: shops, restaurants, warehouses (one big floor plate)
- mixed: hotels, civic buildings, public ground floor with something else above

Invent categories that fit the brief (ward, classroom, sanctuary, guest_room, warehouse). Do not rewrite a hospital as a shop or a house as an office just because those words appear in the room list.

Hard rules:
- Storey ids and space ids are lowercase, no spaces, unique (bed_1, ward_2, wc_l2).
- Every space.floor_id must match a storey id, and every storey must have at least one space.
- Give each storey exactly ONE space with "circulation": true (corridor, hall, lobby or landing) unless the storey is a single room. Size it generously — every other room on that storey opens onto it.
- If there is more than one storey, give EVERY storey a space with "stair": true, roughly the same area, so the stair stacks.
- Repeat shared service space per storey (washrooms, stores) rather than assuming one serves all floors.
- Keep the JSON small enough to finish: at most 8 spaces per storey and 40 spaces total. Group repeats (one "20-bed ward", three "guest_room" types, four "classroom"s) instead of listing every bed, desk or key. Honour explicit small counts ("four meeting rooms" means four spaces).
- target_area_sqft is usable floor area. min_side_ft is the narrowest the room may become; at least 4 and realistic for the use.
- Areas should add up to roughly the gross area. If that would blow the room cap, keep the room cap and scale the spaces so each storey still totals about gross_area / storeys.
- Every storey shares ONE footprint, so give each storey roughly the SAME total area.
- The architect's brief always wins over the typical-area list.

Do not claim the design is compliant. Output JSON only."""

RETRY_NOTE = """Your previous program could not be built. Fix it and return ONLY the JSON object — no prose, no thinking.

If the error said the JSON was cut off or could not be read, write a SMALLER program: fewer rooms, shorter names, no extra keys.

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
    kind: str = "",
) -> list[dict[str, str]]:
    """System policy plus one compact user payload. No chat history is kept."""
    kind = kind or use
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
            "kind": kind,
            "packer_family": use,
            "storeys": floors,
            "gross_area_sqft": round(area_sqft),
            "max_spaces_per_storey": 8,
            "max_spaces_total": 40,
        },
        "reference": defaults.defaults_digest(use, kind),
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
