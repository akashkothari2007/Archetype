"""Planner prompts: research in, space program JSON out. Never coordinates."""

from __future__ import annotations

import json
from typing import Any

from plancheck.core.building import DesignBrief
from plancheck.generation import defaults

SYSTEM = """You are the Archetype generation planner. Before you write a space program you are given RESEARCH: the building kind, the internal program library that was consulted, and the rooms that kind of building actually needs. Use that research. Do not invent a generic house, office, or shop when the research says hospital, mosque, school, hotel, warehouse, or something else.

CRITICAL OUTPUT RULE: Reply with ONE JSON object only. No markdown fences. No prose. No chain-of-thought. No explanations before or after the JSON.

You do not draw. You never return walls, vertices, polygons, or coordinates. A deterministic packer places rectangles, a compiler builds the wall graph, doors, windows and stairs, and a checker measures compliance. Your job is to decide which spaces exist, which storey each sits on, how large it should be, and what it should sit next to — for THIS building kind.

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
    "notes": "one or two sentences on the parti and why these rooms"
  }
}

How to use the research object you are given:
- research.kind / research.label is the building you are designing. Honour it.
- research.layout_scheme is how rooms will be packed. Size circulation to match it. Do not write a hotel corridor program for a house, shop, sanctuary or warehouse.
- research.packer_family is ONLY the layout engine (corridor width, storey height). It is not the building type. A hospital still uses packer family "office"; a mosque still uses "mixed".
- research.recommended_rooms is the starting set. Keep rooms tagged from_brief. Keep typical rooms that belong to this kind. Drop typical rooms that contradict the brief. Add a specialized room the library missed if the brief names it.
- research.architect_named_rooms must appear in the program.
- research.required_room_counts is a hard count. If it says classroom 8, emit eight separate classroom spaces (classroom_1 … classroom_8). Never collapse them into "Classrooms Group A (2 rooms)" or any other grouped rectangle.
- research.sources and research.planning_notes are the knowledge to follow. External sources with a url are published design guides; honour them, and do not invent citations.
- Invent categories that fit the kind (ward, classroom, sanctuary, guest_room, warehouse). Never rewrite a hospital as a shop or a house as an office just because those words appear in the room list.

building_use in the JSON is the PACKER FAMILY, copied from research.packer_family:
- home: houses, apartments, villas
- office: workplaces, clinics, hospitals, schools
- retail: shops, restaurants, warehouses
- mixed: hotels, civic buildings, worship, public ground floor with something else above

Layout scheme (research.layout_scheme) decides the diagram, not a hallway for every building:
- cluster (houses): living, kitchen and dining share one open public zone. Bedrooms cluster. Circulation is a compact hall, foyer or landing next to the stair — never a corridor down the middle of the house.
- hall (worship, gym, restaurant, warehouse, civic): one dominant room takes most of the plate. A lobby or narthex leads into it. Support rooms line the back edge.
- edge (retail): the sales floor is the largest rectangle, facing the street. Stock and staff line the back. Do not cut a hallway through the shop.
- corridor (office, hospital, hotel, school, clinic, apartments): a real double-loaded corridor is correct. Size it generously so every enclosed room can open onto it.
- mixed: large public rooms on the ground storey; corridor only on workplace or guest-room floors.

Hard rules:
- Storey ids and space ids are lowercase, no spaces, unique (bed_1, ward_2, wc_l2).
- Every space.floor_id must match a storey id, and every storey must have at least one space.
- Give each storey exactly ONE space with "circulation": true (hall, lobby, landing or corridor) unless the storey is a single room. For cluster/hall/edge that space is a compact foyer or lobby, not a building-long hallway.
- If there is more than one storey, give EVERY storey a space with "stair": true, roughly the same area, so the stair stacks.
- Repeat shared service space per storey (washrooms, stores) rather than assuming one serves all floors.
- Keep the JSON small enough to finish: at most 16 spaces per storey and 48 spaces total. Collapse only non-room inventory (beds in a ward, desks in a classroom, pews). If the brief gives a number of rooms, emit that many spaces with unique ids.
- Never name a space "group" or "(N rooms)". That is one rectangle pretending to be several rooms. Split it.
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
Usually the better fix is a smaller room count or larger areas in "program". Keep the researched building kind."""


def build_messages(
    brief: DesignBrief,
    use: str,
    floors: int,
    area_sqft: float,
    errors: list[str] | None = None,
    program: dict[str, Any] | None = None,
    layouts: list[str] | None = None,
    kind: str = "",
    research: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """System policy plus brief + research. No chat history is kept."""
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
        "research": research
        or {
            "kind": kind,
            "packer_family": use,
            "layout_scheme": defaults.layout_scheme(kind, use),
            "storeys": floors,
            "gross_area_sqft": round(area_sqft),
            "reference": defaults.defaults_digest(use, kind),
        },
        "interpreted": {
            "kind": kind,
            "packer_family": use,
            "layout_scheme": defaults.layout_scheme(kind, use),
            "storeys": floors,
            "gross_area_sqft": round(area_sqft),
            "max_spaces_per_storey": 16,
            "max_spaces_total": 48,
        },
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
