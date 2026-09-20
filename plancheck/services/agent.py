"""Chat agent: a thinking orchestrator delegates bounded tasks to cheaper subagents."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from plancheck.core.building import Building, BuildingWall, Room
from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings
from plancheck.services.commands import CommandError, apply_commands, wall_length, wall_points
from plancheck.services.compliance import check_building, room_area
from plancheck.services.llm import LLMError, ORCHESTRATOR, SUBAGENT, complete, complete_json
from plancheck.services.repairs import propose_repairs

log = get_logger("plancheck.agent")

GEOMETRY_COMMANDS = {
    "offset_partition",
    "update_wall",
    "create_wall",
    "split_wall",
    "place_opening",
    "update_opening",
    "delete",
    "place_object",
    "update_object",
    "duplicate",
}
FINISH_COMMANDS = {
    "set_material",
    "set_environment",
    "rename_room",
    "apply_room_material_to_type",
}
ALLOWED_COMMANDS = GEOMETRY_COMMANDS | FINISH_COMMANDS
ALLOWED_MATERIALS = {"plaster", "oak", "tile", "concrete", "sage", "terracotta", "white"}
GEOMETRY_WORKERS = {"geometry"}
FINISH_WORKERS = {"finish", "material", "environment", "rename"}
APPEAR_WORKERS = {"appear", "look"}
EDIT_INTENTS = {"geometry", "finish", "edit"}
REPAIR_EMPTY_MARKERS = ("no repairs", "0 proposed", "pending repair")

_SPATIAL_RE = re.compile(
    r"\b(widen|enlarge|expand|shrink|narrow|offset|slide|relocate|nudge|"
    r"move\s+(?:the\s+)?(?:wall|partition|door|opening)|"
    r"hallway|corridor|circulation|footprint|"
    r"adjust\s+(?:the\s+)?(?:other\s+)?(?:sizes?|rooms?|walls?|layout)|"
    r"room\s+sizes?|fit\s+in\s+the\s+same|"
    r"add\s+(?:a\s+)?(?:door|window|wall)|place\s+(?:a\s+)?(?:door|window)|"
    r"toward(?:s)?\s+the|partition)\b",
    re.I,
)
_REPAIR_RE = re.compile(
    r"\b(fix|repair|resolve)\b.*\b(issue|failure|fail|compliance|check|requirement|violation)s?\b|"
    r"\b(check\s+and\s+fix|propose\s+repairs?|failed\s+(?:area\s+)?checks?|"
    r"compliance\s+failures?|violations?)\b",
    re.I,
)
_FINISH_RE = re.compile(
    r"\b(oak|tile|plaster|sage|terracotta|concrete|material|finish|rename|"
    r"evening|morning|lighting|sunlight|\bsun\b)\b",
    re.I,
)
_APPEAR_RE = re.compile(
    r"\b(photoreal|photorealistic|victorian|splat|facade|façade|cladding|"
    r"more\s+realistic|exterior\s+look|warm\s+brick)\b",
    re.I,
)
_FLOOR_NUM_RE = re.compile(
    r"(?:floor|level|storey|story)\s*(\d+)|(\d+)\s*(?:st|nd|rd|th)?\s*(?:floor|level)",
    re.I,
)
_ORDINAL_INDEX = {
    "ground": 0,
    "first": 0,
    "1st": 0,
    "second": 1,
    "2nd": 1,
    "third": 2,
    "3rd": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
}

ORCHESTRATOR_SYSTEM = """You are the Archetype orchestrator for a local building-design app.
Plan only. Do not invent measurements or pass/fail verdicts; compliance is computed separately.
Design iteration is the default: the user already has a constructed plan and wants to change it.
Repair is ONLY for explicit compliance work (fix failed checks, resolve requirement violations).
Spatial language — widen, enlarge, move a wall, hallway, adjust room sizes, fit the same footprint — is geometry, never repair.
Never return a "no repairs to review" message for a design-edit request.
Never request changes to loadbearing or locked walls; the host will block those.
Return JSON only:
{"intent":"repair"|"geometry"|"finish"|"appear"|"answer","message":"short user-facing text","tasks":[{"id":"t1","worker":"repair"|"geometry"|"finish"|"material"|"environment"|"rename"|"appear"|"explain","instruction":"...","target_ids":[]}],"appearance_prompt":""}
Use geometry for spatial edits (one serial task). Use finish for catalog materials, rename, or sun/time.
Use appear for photoreal exterior look only (no wall commands). Use answer to explain with no writes.
Keep tasks small. Prefer one geometry task."""

# ═════════════════════════════════════════════════════════════════════════════════
# NEW ORCHESTRATOR: For unified flow with violations context
# ═════════════════════════════════════════════════════════════════════════════════
ORCHESTRATOR_UNIFIED_SYSTEM = """You are the Archetype orchestrator. Determine user intent and which violations (if any) to prioritize.

Return JSON only:
{"intent":"repair"|"geometry"|"finish"|"appear"|"answer","violations_to_repair":[...],"message":"brief explanation"}

If intent is "repair":
  - Return violations_to_repair: list of violation IDs from all_violations that you should focus on
  - If user said "repair ALL", return all of them
  - If user mentioned specific issues, return only those
  - Never include violations the user didn't mention or that seem unrelated

If intent is "geometry", "finish", "appear", or "answer":
  - Return violations_to_repair: empty list or null (we don't repair these)
  - Focus on the spatial/style request only

Intent guide:
- geometry: move walls, widen rooms, resize spaces, add doors/windows
- finish: rename rooms, change materials (plaster/oak/tile/concrete), change time/sun/season
- appear: photoreal exterior appearance prompt only (no wall commands)
- answer: explain something, no changes needed
- repair: fix compliance violations explicitly mentioned by the user

Examples:
User: "repair the kitchen area and daylight" with violations=[kitchen_area, master_daylight, hallway_circulation]
→ {"intent":"repair","violations_to_repair":["kitchen_area","master_daylight"],...}

User: "widen the kitchen" with violations=[kitchen_area, ...]
→ {"intent":"geometry","violations_to_repair":[],...}

User: "fix everything"
→ {"intent":"repair","violations_to_repair":[all violation IDs],...}"""

GEOMETRY_SYSTEM = """You are the Archetype geometry editor. Keep reasoning SHORT. Output JSON quickly.
{"commands":[{"kind":"...","target_id":"","params":{}}],"message":"short explanation","blocked":[{"target_id":"","reason":"..."}]}

Allowed kinds: offset_partition, update_wall, create_wall, split_wall, place_opening, update_opening, delete, place_object, update_object, duplicate.
NEVER use move_wall — it bypasses locked-wall safety and creates broken geometry.

CRITICAL — how offset_partition works:
  It moves BOTH endpoints of the target wall by (dx, dy).
  Vertices are SHARED. Every wall in "shares_vertex_with" shares an endpoint vertex.
  Moving a vertex drags all walls connected to it — their endpoints shift too.
  The command FAILS if any locked/structural wall sharing those vertices changes shape.
  Unlocked nonstructural neighbors may stretch or change angle — that is allowed.
  If you want neighbors to move in parallel (keep layout rectangular), also offset them by the same (dx, dy).
  But only do this if the neighbor's OTHER end is not shared with a locked wall — check its "shares_vertex_with" and "adjacent_locked_ids".

Command guide:
- offset_partition: widen/enlarge/shrink rooms by moving a wall. Check adjacent_locked_ids first — nonempty means that vertex touches a locked wall and the command will FAIL. Pick a different wall.
- place_opening: add a door or window. Params: wall_id, kind (door|window), offset_ft, width_ft, height_ft, sill_ft. Target a wall that is long enough.
- update_opening / delete: modify or remove existing openings/objects.
- place_object / update_object / duplicate: furniture and fixtures.

Rules:
- Never move a wall where locked is true or structural is not nonstructural.
- Unlocked nonstructural neighbors that stretch when a vertex moves — that's fine, no need to offset them too unless you want to keep them parallel.
- Use only entity ids from the brief. Do not invent ids.
- If every possible wall is stuck (locked chain), return blocked with a clear reason.
- If the issue is on a floor not in the brief, return blocked immediately.
- If this is a retry, fix the failed commands using the error text.
- Pick the simplest solution. Output JSON."""

GEOMETRY_RETRY_SYSTEM = """Return only commands JSON, no reasoning.
{"commands":[{"kind":"offset_partition","target_id":"","params":{"dx":0,"dy":0}}],"message":"","blocked":[]}
Use offset_partition. NEVER use move_wall. If the target wall has adjacent_locked_ids, pick a different wall. Unlocked neighbors will stretch — that's fine. Use only ids from the brief. Fix dry_run_error."""

FINISH_SYSTEM = """You are a bounded Archetype finish subagent. Return JSON only:
{"commands":[{"kind":"...","target_id":"","params":{}}],"message":"short user-facing text","blocked":[{"reason":"..."}]}
Allowed kinds: set_material, set_environment, rename_room, apply_room_material_to_type, update_object, place_object, duplicate.
set_material materials: plaster, oak, tile, concrete, sage, terracotta, white.
set_environment params: time (0-24), season (spring|summer|autumn|winter), sun_azimuth.
Do not invent entity ids. Do not describe repairs."""

APPEAR_SYSTEM = """You are the Archetype appearance planner. Return JSON only:
{"commands":[],"appearance_prompt":"...","message":"short user-facing text","blocked":[]}
Write appearance_prompt as extra style instructions for a photoreal exterior edit.
Keep the existing footprint, camera, and black outside. No wall or room commands."""

# ═════════════════════════════════════════════════════════════════════════════════
# NEW: REPAIR SUBAGENT (Unified agent improvement)
# ═════════════════════════════════════════════════════════════════════════════════
REPAIR_SYSTEM = """You are the Archetype repair agent. The user wants to fix compliance failures.
Return JSON only:
{"commands":[{"kind":"...","target_id":"","params":{}}],"message":"short explanation","blocked":[{"target_id":"","reason":"..."}]}

Given a list of compliance failures, generate commands to fix them intelligently.
Prioritize failures that can be fixed (e.g., expand undersized rooms, add missing windows).
Refuse to fix failures that require changing locked/structural walls.

Allowed kinds: offset_partition, move_wall, update_wall, create_wall, split_wall, place_opening, update_opening, delete, place_object, update_object, duplicate.

Strategy:
- Use offset_partition {dx,dy} to expand rooms that are too small
- Use place_opening to add windows for daylight requirements
- Use create_wall to add required separations
- NEVER use move_wall on locked or structural walls
- Return blocked for failures you cannot fix

Do not invent entity ids. Only use ids from the building."""

REPAIR_RETRY_SYSTEM = """Return only commands JSON, no reasoning.
{"commands":[...], "message":"", "blocked":[]}
Fix the dry_run_error. Use offset_partition instead of move_wall when possible.
Prefer simpler solutions."""


def is_spatial_request(message: str) -> bool:
    return bool(_SPATIAL_RE.search(message or ""))


def is_explicit_repair(message: str) -> bool:
    text = message or ""
    if is_spatial_request(text):
        return False
    return bool(_REPAIR_RE.search(text))


def host_intent(message: str) -> str | None:
    text = message or ""
    if is_spatial_request(text):
        return "geometry"
    if is_explicit_repair(text):
        return "repair"
    if _APPEAR_RE.search(text):
        return "appear"
    if _FINISH_RE.search(text):
        return "finish"
    return None


def _ordered_floors(building: Building) -> list:
    return sorted(building.floors, key=lambda floor: (floor.elevation_ft, floor.id))


def mentioned_floor_ids(building: Building, message: str) -> list[str]:
    text = (message or "").lower()
    found: list[str] = []
    for floor in building.floors:
        tokens = {floor.id.lower(), floor.name.lower()}
        if any(token and token in text for token in tokens):
            found.append(floor.id)
    ordered = _ordered_floors(building)
    for match in _FLOOR_NUM_RE.finditer(text):
        number = int(match.group(1) or match.group(2))
        if 1 <= number <= len(ordered):
            found.append(ordered[number - 1].id)
    for word, index in _ORDINAL_INDEX.items():
        if re.search(rf"\b{word}\b", text) and index < len(ordered):
            # Name match already recorded "First floor" as upper; skip extra ordinal.
            if word in {"first", "1st"} and any("first" in (f.name + f.id).lower() for f in building.floors):
                continue
            found.append(ordered[index].id)
    seen: list[str] = []
    for floor_id in found:
        if floor_id not in seen:
            seen.append(floor_id)
    return seen


def resolve_floor_ids(
    building: Building,
    message: str,
    floor_id: str | None,
    selected_ids: list[str],
) -> list[str]:
    mentioned = mentioned_floor_ids(building, message)
    known = {floor.id for floor in building.floors}
    resolved: list[str] = []
    for item in mentioned:
        if item in known and item not in resolved:
            resolved.append(item)
    # A named floor wins. Do not also dump the UI floor — that bloated the brief
    # and let the mock widen the wrong storey.
    if not resolved and floor_id and floor_id in known:
        resolved.append(floor_id)
    for entity_id in selected_ids:
        snap = _entity_snapshot(building, entity_id)
        fid = str((snap or {}).get("floor_id") or "")
        if fid in known and fid not in resolved:
            resolved.append(fid)
    if not resolved and building.floors:
        resolved.append(_ordered_floors(building)[0].id)
    return resolved


def _vertex_ref(building: Building, vertex_id: str) -> dict[str, Any]:
    vertex = next((item for item in building.vertices if item.id == vertex_id), None)
    if vertex is None:
        return {"id": vertex_id}
    return {"id": vertex.id, "x": round(vertex.x, 3), "y": round(vertex.y, 3)}


def _room_metrics(room: Room) -> dict[str, Any]:
    payload: dict[str, Any] = {"area_sqft": 0.0, "centroid": None, "bbox": None}
    if not room.polygon or len(room.polygon) < 3:
        return payload
    xs = [pt[0] for pt in room.polygon]
    ys = [pt[1] for pt in room.polygon]
    payload["bbox"] = {
        "min_x": round(min(xs), 3),
        "min_y": round(min(ys), 3),
        "max_x": round(max(xs), 3),
        "max_y": round(max(ys), 3),
    }
    payload["centroid"] = {"x": round(sum(xs) / len(xs), 3), "y": round(sum(ys) / len(ys), 3)}
    try:
        payload["area_sqft"] = round(room_area(room), 2)
    except ValueError:
        payload["area_sqft"] = 0.0
    return payload


def _wall_snapshot(building: Building, wall: BuildingWall) -> dict[str, Any]:
    start, end = None, None
    length = None
    try:
        a, b = wall_points(building, wall)
        start = {"id": a.id, "x": round(a.x, 3), "y": round(a.y, 3)}
        end = {"id": b.id, "x": round(b.x, 3), "y": round(b.y, 3)}
        length = round(wall_length(building, wall), 3)
    except Exception:
        start = _vertex_ref(building, wall.start_id)
        end = _vertex_ref(building, wall.end_id)
    adjacent = _adjacent_locked_ids(building, wall)
    # All walls sharing any vertex (locked or not) — so the LLM knows what offset_partition will drag
    keys = {wall.start_id, wall.end_id}
    shares_vertex = [
        other.id for other in building.walls
        if other.id != wall.id and (other.start_id in keys or other.end_id in keys)
    ]
    return {
        "id": wall.id,
        "floor_id": wall.floor_id,
        "start": start,
        "end": end,
        "length_ft": length,
        "thickness_ft": wall.thickness_ft,
        "height_ft": wall.height_ft,
        "structural": wall.structural,
        "locked": wall.locked,
        "shared_locked": bool(adjacent),
        "adjacent_locked_ids": adjacent,
        "shares_vertex_with": shares_vertex,
        "material": wall.material,
    }


def _entity_snapshot(building: Building, entity_id: str) -> dict[str, Any] | None:
    for room in building.rooms:
        if room.id == entity_id:
            return {
                "kind": "room",
                "id": room.id,
                "name": room.name,
                "category": room.category,
                "floor_id": room.floor_id,
                "material": room.floor_material,
                "wall_ids": list(room.wall_ids),
                **_room_metrics(room),
            }
    for wall in building.walls:
        if wall.id == entity_id:
            return {"kind": "wall", **_wall_snapshot(building, wall)}
    for obj in building.objects:
        if obj.id == entity_id:
            return {
                "kind": "object",
                "id": obj.id,
                "asset_id": obj.asset_id,
                "floor_id": obj.floor_id,
                "x": obj.x,
                "y": obj.y,
            }
    for opening in building.openings:
        if opening.id == entity_id:
            return {
                "kind": "opening",
                "id": opening.id,
                "kind_name": opening.kind,
                "wall_id": opening.wall_id,
                "width_ft": opening.width_ft,
            }
    return {"kind": "unknown", "id": entity_id}


def _failures(building: Building, rules: list[dict]) -> list[dict[str, Any]]:
    return [
        {
            "id": check.get("id"),
            "metric": check.get("metric"),
            "entity_id": check.get("entity_id"),
            "message": check.get("message"),
            "status": check.get("status"),
        }
        for check in check_building(building, rules)
        if check.get("status") == "fail"
    ][:40]


def _scoped_brief(
    building: Building,
    rules: list[dict],
    selected_ids: list[str],
    message: str = "",
    floor_id: str | None = None,
) -> dict[str, Any]:
    floor_ids = resolve_floor_ids(building, message, floor_id, selected_ids)
    floor_set = set(floor_ids)
    extra_ids = set(selected_ids)
    for entity_id in selected_ids:
        snap = _entity_snapshot(building, entity_id)
        if snap and snap.get("kind") == "room":
            extra_ids.update(snap.get("wall_ids") or [])
        if snap and snap.get("floor_id") and snap["floor_id"] not in floor_set:
            floor_set.add(str(snap["floor_id"]))
            floor_ids.append(str(snap["floor_id"]))

    rooms = [room for room in building.rooms if room.floor_id in floor_set]
    walls = [wall for wall in building.walls if wall.floor_id in floor_set]
    if extra_ids:
        walls.extend(wall for wall in building.walls if wall.id in extra_ids and wall not in walls)
        rooms.extend(room for room in building.rooms if room.id in extra_ids and room not in rooms)

    if len(walls) > 80:
        neighborhood = set()
        for room in rooms:
            if room.id in extra_ids or any(wid in extra_ids for wid in room.wall_ids):
                neighborhood.update(room.wall_ids)
        if neighborhood:
            walls = [wall for wall in walls if wall.id in neighborhood][:80]
        else:
            walls = walls[:80]
    wall_ids = {wall.id for wall in walls}
    openings = [op for op in building.openings if op.wall_id in wall_ids]
    objects = [obj for obj in building.objects if obj.floor_id in floor_set]
    if len(objects) > 60:
        objects = objects[:60]

    return {
        "floors": [
            {
                "id": floor.id,
                "name": floor.name,
                "elevation_ft": floor.elevation_ft,
                "height_ft": floor.height_ft,
            }
            for floor in building.floors
        ],
        "active_floor_ids": floor_ids,
        "rooms": [
            {
                "id": room.id,
                "name": room.name,
                "category": room.category,
                "floor_id": room.floor_id,
                "floor_material": room.floor_material,
                "wall_ids": list(room.wall_ids),
                **_room_metrics(room),
            }
            for room in rooms
        ],
        "walls": [_wall_snapshot(building, wall) for wall in walls],
        "openings": [
            {
                "id": op.id,
                "wall_id": op.wall_id,
                "kind": op.kind,
                "offset_ft": op.offset_ft,
                "width_ft": op.width_ft,
                "height_ft": op.height_ft,
                "sill_ft": op.sill_ft,
            }
            for op in openings
        ],
        "objects": [
            {
                "id": obj.id,
                "asset_id": obj.asset_id,
                "kind": obj.kind,
                "floor_id": obj.floor_id,
                "x": obj.x,
                "y": obj.y,
                "rotation_deg": obj.rotation_deg,
                "width_ft": obj.width_ft,
                "depth_ft": obj.depth_ft,
            }
            for obj in objects
        ],
        "environment": building.environment.model_dump(),
        "site": building.site.model_dump(),
        "selected": [_entity_snapshot(building, eid) for eid in selected_ids],
        "failures": _failures(building, rules),
        "approved_rules": sum(1 for rule in rules if rule.get("status") == "approved"),
    }


def _brief(
    building: Building,
    rules: list[dict],
    selected_ids: list[str],
    message: str = "",
    floor_id: str | None = None,
) -> dict[str, Any]:
    return _scoped_brief(building, rules, selected_ids, message, floor_id)


def _float_params(params: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    cleaned: dict[str, Any] = {}
    for key in keys:
        if key not in params:
            continue
        try:
            cleaned[key] = float(params[key])
        except (TypeError, ValueError):
            return None
    return cleaned


def _clean_commands(raw: Any, selected_ids: list[str]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return commands
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind == "unlock_wall" or kind not in ALLOWED_COMMANDS:
            continue
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        target = str(item.get("target_id") or "")
        if kind == "set_material":
            material = str(params.get("material") or "").lower()
            if material == "white":
                material = "plaster"
            if material not in ALLOWED_MATERIALS or not target:
                continue
            params = {"material": material}
        elif kind == "set_environment":
            target = ""
            cleaned: dict[str, Any] = {}
            if "time" in params:
                try:
                    time = float(params["time"])
                except (TypeError, ValueError):
                    continue
                if not 0 <= time <= 24:
                    continue
                cleaned["time"] = time
            if params.get("season") in {"spring", "summer", "autumn", "winter"}:
                cleaned["season"] = params["season"]
            if "sun_azimuth" in params:
                try:
                    cleaned["sun_azimuth"] = float(params["sun_azimuth"])
                except (TypeError, ValueError):
                    continue
            if not cleaned:
                continue
            params = cleaned
        elif kind == "rename_room":
            name = str(params.get("name") or "").strip()
            if not name or not target:
                continue
            params = {"name": name[:80], **({"category": str(params["category"])} if params.get("category") else {})}
        elif kind in {"offset_partition", "move_wall"}:
            if not target and selected_ids:
                target = selected_ids[0]
            cleaned = _float_params(params, ["dx", "dy"])
            if not target or cleaned is None:
                continue
            params = {"dx": cleaned.get("dx", 0.0), "dy": cleaned.get("dy", 0.0)}
            if params["dx"] == 0 and params["dy"] == 0:
                continue
        elif kind == "update_wall":
            if not target:
                continue
            cleaned = _float_params(params, [key for key in ("thickness_ft", "height_ft") if key in params])
            if not cleaned:
                continue
            params = cleaned
        elif kind == "create_wall":
            cleaned = _float_params(params, ["x1", "y1", "x2", "y2"])
            floor = str(params.get("floor_id") or "")
            if not floor or cleaned is None:
                continue
            params = {"floor_id": floor, **cleaned}
            for key in ("thickness_ft", "height_ft"):
                if key in params:
                    continue
                if key in item.get("params", {}):
                    try:
                        params[key] = float(item["params"][key])
                    except (TypeError, ValueError):
                        pass
            target = str(params.get("id") or target)
        elif kind == "split_wall":
            if not target:
                continue
            cleaned = _float_params(params, ["offset_ft"])
            if cleaned is None or "offset_ft" not in cleaned:
                continue
            params = cleaned
        elif kind == "place_opening":
            wall_id = str(params.get("wall_id") or target or "")
            kind_name = str(params.get("kind") or "door")
            cleaned = _float_params(params, [key for key in ("offset_ft", "width_ft", "height_ft", "sill_ft") if key in params or key in {"offset_ft", "width_ft"}])
            if not wall_id or kind_name not in {"door", "window"} or cleaned is None:
                continue
            if "offset_ft" not in cleaned or "width_ft" not in cleaned:
                continue
            params = {"wall_id": wall_id, "kind": kind_name, **cleaned}
            target = target or wall_id
        elif kind == "update_opening":
            if not target:
                continue
            permitted = {"offset_ft", "width_ft", "height_ft", "sill_ft", "hinge", "swing", "clear_width_ft"}
            cleaned_open: dict[str, Any] = {}
            for key, value in params.items():
                if key not in permitted:
                    continue
                if key in {"hinge", "swing"}:
                    cleaned_open[key] = value
                else:
                    try:
                        cleaned_open[key] = float(value)
                    except (TypeError, ValueError):
                        continue
            if not cleaned_open:
                continue
            params = cleaned_open
        elif kind == "place_object":
            floor = str(params.get("floor_id") or "")
            asset = str(params.get("asset_id") or "")
            cleaned = _float_params(params, [key for key in ("x", "y", "rotation_deg", "width_ft", "depth_ft", "height_ft") if key in params or key in {"x", "y"}])
            if not floor or not asset or cleaned is None or "x" not in cleaned or "y" not in cleaned:
                continue
            params = {"floor_id": floor, "asset_id": asset, "kind": str(params.get("kind") or "furniture"), **cleaned}
        elif kind == "update_object":
            if not target and selected_ids:
                target = selected_ids[0]
            if not target:
                continue
            cleaned = _float_params(params, [key for key in ("x", "y", "rotation_deg", "width_ft", "depth_ft", "height_ft") if key in params])
            if not cleaned:
                continue
            params = cleaned
        elif kind == "duplicate":
            if not target and selected_ids:
                target = selected_ids[0]
            if not target:
                continue
            cleaned = _float_params(params, [key for key in ("dx", "dy") if key in params]) or {}
            params = cleaned
        elif kind == "delete":
            if not target:
                continue
            params = {}
        elif kind == "apply_room_material_to_type":
            if not target:
                continue
            params = {}
        commands.append({"kind": kind, "target_id": target, "params": params})
    return commands[:40]


def _result(
    message: str,
    *,
    intent: str,
    commands: list[dict[str, Any]] | None = None,
    blocked: list[dict[str, Any]] | None = None,
    tasks: list[Any] | None = None,
    appearance_prompt: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    commands = commands or []
    blocked = blocked or []
    payload = {
        "commands": commands,
        "tasks": tasks or [],
        "blocked": blocked,
        "message": message,
        "actor": "agent",
        "intent": intent,
        "summary": {"proposed": len(commands), "blocked": len(blocked)},
    }
    if appearance_prompt:
        payload["appearance_prompt"] = appearance_prompt
    if extra:
        payload.update(extra)
    return payload


def _looks_like_repair_summary(message: str) -> bool:
    text = (message or "").lower()
    return any(marker in text for marker in REPAIR_EMPTY_MARKERS) or (
        "repair" in text and ("0 proposed" in text or "no failures" in text or "no pending" in text)
    )


def _sanitize_edit_message(intent: str, message: str, commands: list[dict[str, Any]], blocked: list[dict[str, Any]]) -> str:
    text = (message or "").strip()
    if intent in {"geometry", "finish"} and _looks_like_repair_summary(text):
        text = ""
    if text:
        return text
    if commands:
        kinds = ", ".join(sorted({cmd["kind"] for cmd in commands}))
        return f"Prepared {len(commands)} design change{'s' if len(commands) != 1 else ''} ({kinds}) to apply."
    if blocked:
        reason = blocked[0].get("reason") or "that change is locked"
        target = blocked[0].get("target_id") or blocked[0].get("entity_id") or ""
        where = f" ({target})" if target else ""
        return f"I could not apply that design edit{where}: {reason}"
    if intent == "geometry":
        return "I could not find a movable nonstructural partition for that design edit."
    return "I can change finishes, lighting, or the constructed plan. Describe one spatial or finish edit."


def _movable_wall(wall: BuildingWall | None) -> bool:
    return bool(wall) and not wall.locked and wall.structural == "nonstructural"


def _adjacent_locked_ids(building: Building, wall: BuildingWall) -> list[str]:
    keys = {wall.start_id, wall.end_id}
    found: list[str] = []
    for other in building.walls:
        if other.id == wall.id:
            continue
        if other.start_id in keys or other.end_id in keys:
            if other.locked or other.structural != "nonstructural":
                found.append(other.id)
    return found


def _shares_locked_vertex(building: Building, wall: BuildingWall) -> bool:
    return bool(_adjacent_locked_ids(building, wall))


def _would_drag_locked_vertex(building: Building, wall: BuildingWall) -> bool:
    return _shares_locked_vertex(building, wall)


def sanitize_geometry_commands(
    building: Building, commands: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rewrite move_wall that would drag a locked vertex into offset_partition."""
    cleaned: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    walls = {wall.id: wall for wall in building.walls}
    for command in commands:
        kind = str(command.get("kind") or "")
        target = str(command.get("target_id") or "")
        wall = walls.get(target)
        # move_wall translates both endpoints, so a shared locked vertex fails apply.
        if kind == "move_wall":
            if wall and _movable_wall(wall):
                rewritten = {**command, "kind": "offset_partition"}
                log.info("chat.sanitize move_wall->offset_partition wall=%s", wall.id)
                cleaned.append(rewritten)
            else:
                reason = _wall_block_reason(wall) if wall else f"Unknown wall {target} cannot be moved."
                blocked.append({"target_id": target, "reason": reason})
            continue
        if kind == "offset_partition" and wall and not _movable_wall(wall):
            blocked.append({"target_id": wall.id, "reason": _wall_block_reason(wall)})
            continue
        cleaned.append(command)
    return cleaned, blocked


def _room_centroid(room: Room) -> tuple[float, float] | None:
    if not room.polygon:
        return None
    return (
        sum(pt[0] for pt in room.polygon) / len(room.polygon),
        sum(pt[1] for pt in room.polygon) / len(room.polygon),
    )


def _named_rooms(building: Building, message: str, floor_ids: list[str]) -> list[Room]:
    text = (message or "").lower()
    matches: list[Room] = []
    for room in building.rooms:
        hay = f"{room.name} {room.category} {room.id}".lower()
        tokens = [room.name.lower(), room.category.lower()]
        tokens.extend(part for part in re.split(r"[\s/_-]+", room.name.lower()) if len(part) > 2)
        if any(token and token in text for token in tokens) or any(word in hay for word in ("kitchen", "living", "hallway") if word in text):
            matches.append(room)
    if floor_ids:
        preferred = [room for room in matches if room.floor_id in floor_ids]
        if preferred:
            return preferred
    return matches


def _circulation_label(room: Room) -> bool:
    hay = f"{room.name} {room.category}".lower()
    return room.category == "circulation" or bool(
        re.search(r"\b(hall|hallway|corridor|landing|foyer)\b", hay)
    )


def _circulation_rooms(building: Building, floor_ids: list[str], message: str) -> list[Room]:
    text = (message or "").lower()
    rooms = [room for room in building.rooms if not floor_ids or room.floor_id in floor_ids]
    mentioned = mentioned_floor_ids(building, message)
    if mentioned:
        scoped = [room for room in rooms if room.floor_id in mentioned]
        if scoped:
            rooms = scoped
    named = [room for room in rooms if _circulation_label(room)]
    if re.search(r"\b(hallway|corridor|hall|landing)\b", text):
        return named or [room for room in rooms if room.category == "circulation"]
    return named


def _shared_walls(building: Building, left: Room, right: Room) -> list[BuildingWall]:
    ids = set(left.wall_ids) & set(right.wall_ids)
    return [wall for wall in building.walls if wall.id in ids]


def _offset_away(building: Building, wall: BuildingWall, room: Room, distance: float) -> dict[str, float] | None:
    centroid = _room_centroid(room)
    if centroid is None:
        return None
    try:
        start, end = wall_points(building, wall)
        length = wall_length(building, wall)
    except Exception:
        return None
    if length < 0.05:
        return None
    nx = -(end.y - start.y) / length
    ny = (end.x - start.x) / length
    if (centroid[0] - start.x) * nx + (centroid[1] - start.y) * ny > 0:
        nx, ny = -nx, -ny
    return {"dx": nx * distance, "dy": ny * distance}


def _offset_toward(building: Building, wall: BuildingWall, toward: Room, distance: float) -> dict[str, float] | None:
    centroid = _room_centroid(toward)
    if centroid is None:
        return None
    try:
        start, end = wall_points(building, wall)
        length = wall_length(building, wall)
    except Exception:
        return None
    if length < 0.05:
        return None
    nx = -(end.y - start.y) / length
    ny = (end.x - start.x) / length
    # Point the normal toward the destination room.
    if (centroid[0] - start.x) * nx + (centroid[1] - start.y) * ny < 0:
        nx, ny = -nx, -ny
    return {"dx": nx * distance, "dy": ny * distance}


def _widen_sort_key(
    building: Building, wall: BuildingWall, room: Room
) -> tuple[int, int, float, float, str]:
    """Prefer movable side walls that increase the room's short dimension (true widen)."""
    metrics = _room_metrics(room)
    bbox = metrics.get("bbox") or {}
    width = float(bbox.get("max_x", 0) or 0) - float(bbox.get("min_x", 0) or 0)
    depth = float(bbox.get("max_y", 0) or 0) - float(bbox.get("min_y", 0) or 0)
    try:
        start, end = wall_points(building, wall)
        length = wall_length(building, wall)
    except Exception:
        return (0 if _movable_wall(wall) else 1, 1, 0.0, 0.0, wall.id)
    vertical = abs(start.x - end.x) < abs(start.y - end.y)
    widen_x = width <= depth or width == 0
    aligns = 0 if vertical == widen_x else 1
    axis_pos = -((start.x + end.x) / 2 if vertical else (start.y + end.y) / 2)
    return (0 if _movable_wall(wall) else 1, aligns, -length, axis_pos, wall.id)


def _wall_block_reason(wall: BuildingWall) -> str:
    if wall.locked and wall.structural != "nonstructural":
        return f"Wall {wall.id} is locked and {wall.structural}, so the agent cannot move it."
    if wall.locked:
        return f"Wall {wall.id} is locked, so the agent cannot move it."
    if wall.structural != "nonstructural":
        return f"Wall {wall.id} is {wall.structural}, so the agent cannot move it."
    return f"Wall {wall.id} cannot be moved."


def _try_apply(
    building: Building, rules: list[dict], commands: list[dict[str, Any]]
) -> tuple[Any | None, str | None, str | None]:
    if not commands:
        return None, "No commands were produced for this design edit.", None
    # Block move_wall — it bypasses locked-wall checks and creates diagonals
    for cmd in commands:
        if cmd.get("kind") == "move_wall":
            return None, "move_wall is not allowed — use offset_partition instead, and also offset all walls sharing the same vertices.", cmd.get("target_id")
    try:
        candidate = apply_commands(building, commands, actor="agent")
    except CommandError as exc:
        target = next((cmd.get("target_id") for cmd in commands if cmd.get("target_id")), None)
        return None, str(exc), target
    except (ValueError, KeyError) as exc:
        return None, str(exc), None

    # Geometric sanity: reject if any room area shrinks drastically (areas in sq ft)
    from plancheck.services.compliance import room_area as _room_area
    for room_before in building.rooms:
        room_after = next((r for r in candidate.rooms if r.id == room_before.id), None)
        if not room_after:
            continue
        try:
            area_before = _room_area(room_before)
            area_after = _room_area(room_after)
        except (ValueError, Exception):
            continue
        if area_before > 20.0 and area_after < 20.0:
            return None, f"The edit would crush {room_before.name} to {area_after:.0f} sq ft — pick a smaller offset or a different wall.", room_before.id
        if area_before > 30.0 and area_after < area_before * 0.5:
            pct = 100 - area_after / area_before * 100
            return None, f"The edit would shrink {room_before.name} by {pct:.0f}% (from {area_before:.0f} to {area_after:.0f} sq ft) — use a smaller offset.", room_before.id

    before = {check["id"]: check for check in check_building(building, rules)}
    after = check_building(candidate, rules)
    new_fails = [
        check
        for check in after
        if check.get("status") == "fail" and (before.get(check["id"]) or {}).get("status") != "fail"
    ]
    if new_fails:
        first = new_fails[0]
        return None, f"The edit would introduce a new requirement failure: {first.get('message') or first.get('id')}", first.get("entity_id")
    return candidate, None, None


def _geometry_candidates(
    building: Building,
    message: str,
    selected_ids: list[str],
    floor_id: str | None,
) -> list[tuple[dict[str, Any], str]]:
    floor_ids = resolve_floor_ids(building, message, floor_id, selected_ids)
    rooms_by_id = {room.id: room for room in building.rooms}
    walls_by_id = {wall.id: wall for wall in building.walls}
    candidates: list[tuple[dict[str, Any], str]] = []
    named = _named_rooms(building, message, floor_ids)
    circulation = _circulation_rooms(building, floor_ids, message)
    toward = None
    source = None
    toward_match = re.search(r"toward(?:s)?\s+the\s+([a-z0-9 \-]+)", (message or "").lower())
    if toward_match and named:
        label = toward_match.group(1).strip()
        toward = next((room for room in named if label.split()[0] in f"{room.name} {room.category}".lower()), None)
        source = next((room for room in named if room is not toward), None)
    if source and toward:
        for wall in _shared_walls(building, source, toward):
            params = _offset_toward(building, wall, toward, 2.0)
            if not params:
                continue
            note = f"Enlarge {source.name} toward {toward.name} by moving partition {wall.id}."
            candidates.append(({"kind": "offset_partition", "target_id": wall.id, "params": params}, note))
    targets = circulation or ([room for room in named if room.category == "circulation"]) or named
    selected_rooms = [rooms_by_id[eid] for eid in selected_ids if eid in rooms_by_id]
    if selected_rooms and not targets:
        targets = selected_rooms
    for room in targets:
        wall_ids = list(room.wall_ids)
        scored: list[tuple[int, int, float, float, str, BuildingWall]] = []
        for wall_id in wall_ids:
            wall = walls_by_id.get(wall_id)
            if not wall:
                continue
            scored.append((*_widen_sort_key(building, wall, room), wall))
        for _locked, _align, _length, _axis, _wid, wall in sorted(scored):
            params = _offset_away(building, wall, room, 2.0)
            if not params:
                continue
            note = f"Widen {room.name} by offsetting partition {wall.id}, keeping the same overall footprint."
            candidates.append(({"kind": "offset_partition", "target_id": wall.id, "params": params}, note))
    # Deduplicate by wall id, first note wins.
    seen: set[str] = set()
    unique: list[tuple[dict[str, Any], str]] = []
    for command, note in candidates:
        if command["target_id"] in seen:
            continue
        seen.add(command["target_id"])
        unique.append((command, note))
    return unique


def fallback_geometry_edit(
    building: Building,
    rules: list[dict],
    message: str,
    selected_ids: list[str] | None = None,
    floor_id: str | None = None,
) -> dict[str, Any]:
    selected_ids = selected_ids or []
    blocked: list[dict[str, Any]] = []
    for command, note in _geometry_candidates(building, message, selected_ids, floor_id):
        wall = next((item for item in building.walls if item.id == command["target_id"]), None)
        if wall and not _movable_wall(wall):
            blocked.append({"target_id": wall.id, "reason": _wall_block_reason(wall)})
            continue
        _candidate, error, target = _try_apply(building, rules, [command])
        if error:
            blocked.append({"target_id": target or command["target_id"], "reason": error})
            continue
        return _result(note, intent="geometry", commands=[command], blocked=[])
    if blocked:
        return _result(
            _sanitize_edit_message("geometry", "", [], blocked),
            intent="geometry",
            blocked=blocked,
        )
    return _result(
        "I could not find a movable nonstructural hallway or room partition for that design edit.",
        intent="geometry",
    )


def local_respond(
    building,
    rules,
    message,
    context="2D",
    selected_ids=None,
    report=None,
    floor_id=None,
    history=None,
    **_kwargs,
):
    text = (message or "").lower().strip()
    selected_ids = selected_ids or []
    if report:
        report(phase="working", progress=0.4, message="Using the local editing assistant")
    if is_explicit_repair(message):
        proposal = propose_repairs(building, rules, report)
        count = proposal["summary"]["proposed"]
        blocked = proposal["summary"]["blocked"]
        return {
            **proposal,
            "intent": "repair",
            "message": (
                f"I checked the approved requirements and prepared {count} verifiable repair"
                f"{'s' if count != 1 else ''}. {blocked} issue"
                f"{'s remain' if blocked != 1 else ' remains'} blocked. Review the changes before applying them."
            ),
            "actor": "agent",
        }
    if is_spatial_request(message) or host_intent(message) == "geometry":
        return fallback_geometry_edit(building, rules, message, selected_ids, floor_id)
    materials = {
        "white": "plaster",
        "oak": "oak",
        "tile": "tile",
        "concrete": "concrete",
        "sage": "sage",
        "terracotta": "terracotta",
    }
    material = next((value for word, value in materials.items() if word in text), None)
    if material and selected_ids:
        commands = [{"kind": "set_material", "target_id": eid, "params": {"material": material}} for eid in selected_ids]
        return _result(
            f"I prepared a {material} finish for your selection.",
            intent="finish",
            commands=commands,
        )
    if "sun" in text or "evening" in text or "morning" in text:
        time = 18 if "evening" in text else 8 if "morning" in text else 14
        return _result(
            f"I prepared lighting for {time:02d}:00.",
            intent="finish",
            commands=[{"kind": "set_environment", "target_id": "", "params": {"time": time}}],
        )
    if host_intent(message) == "appear":
        return _result(
            "I can restyle the photoreal exterior once a 3D capture is available.",
            intent="appear",
            appearance_prompt=_appearance_prompt(message),
        )
    return _result(
        "I can widen rooms or hallways, enlarge a space toward a neighbor, change a selected finish, or set lighting. Describe one of those design edits.",
        intent="answer",
    )


def _appearance_prompt(message: str, planned: str | None = None) -> str:
    from plancheck.services.image_edit import SCENE_PROMPT

    extra = (planned or message or "").strip()
    if not extra or extra == SCENE_PROMPT:
        return SCENE_PROMPT
    if extra.startswith(SCENE_PROMPT):
        return extra
    return f"{SCENE_PROMPT} User request: {extra}"


def _worker_system(worker: str) -> str:
    if worker in GEOMETRY_WORKERS or worker == "edit":
        return GEOMETRY_SYSTEM
    if worker in APPEAR_WORKERS:
        return APPEAR_SYSTEM
    return FINISH_SYSTEM


def _run_subagent(
    task: dict[str, Any],
    brief: dict[str, Any],
    selected_ids: list[str],
    *,
    correction: str | None = None,
    failed: list[dict[str, Any]] | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    worker = str(task.get("worker") or "geometry")
    log.info(
        "chat.agent=subagent worker=%s task=%s targets=%s retry=%s compact=%s",
        worker,
        task.get("id"),
        task.get("target_ids"),
        bool(correction),
        compact,
    )
    payload_body: dict[str, Any] = {
        "task": task,
        "instruction": task.get("instruction"),
        "target_ids": task.get("target_ids") or selected_ids,
        "building": brief,
    }
    if correction:
        payload_body["dry_run_error"] = correction
        payload_body["failed_commands"] = failed or []
        payload_body["retry"] = True
    system = (
        GEOMETRY_RETRY_SYSTEM
        if compact and (worker in GEOMETRY_WORKERS or worker == "edit")
        else _worker_system(worker)
    )
    extra: dict[str, Any] = {}
    if compact:
        extra["max_tokens"] = 4800
        extra["reasoning_effort"] = "low"
    try:
        payload = complete_json(
            SUBAGENT,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload_body)},
            ],
            **extra,
        )
    except LLMError as exc:
        log.warning("chat.subagent_llm_error worker=%s error=%s", worker, exc)
        return {
            "commands": [],
            "blocked": [],
            "message": "",
            "task": task,
            "appearance_prompt": "",
            "llm_error": str(exc),
        }
    commands = _clean_commands(payload.get("commands"), selected_ids)
    blocked = payload.get("blocked") if isinstance(payload.get("blocked"), list) else []
    blocked = [item if isinstance(item, dict) else {"reason": str(item)} for item in blocked]
    message = str(payload.get("message") or "")
    appearance_prompt = str(payload.get("appearance_prompt") or "")
    log.info("chat.agent=subagent done commands=%d blocked=%d", len(commands), len(blocked))
    return {
        "commands": commands,
        "blocked": blocked,
        "message": message,
        "task": task,
        "appearance_prompt": appearance_prompt,
    }


def _normalize_intent(plan: dict[str, Any], message: str) -> str:
    intent = str(plan.get("intent") or "answer").lower()
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    workers = {str(task.get("worker") or "").lower() for task in tasks if isinstance(task, dict)}
    forced = host_intent(message)
    if forced == "geometry" and intent in {"repair", "answer", "edit", ""}:
        log.info("chat.override intent=%s->geometry spatial request", intent or "empty")
        return "geometry"
    if forced == "repair":
        return "repair"
    if forced == "appear" and intent in {"answer", "edit", "repair"}:
        return "appear"
    if intent == "edit":
        if workers & GEOMETRY_WORKERS or forced == "geometry":
            return "geometry"
        if workers & APPEAR_WORKERS:
            return "appear"
        return "finish"
    if intent == "repair" and "repair" not in workers and workers & GEOMETRY_WORKERS:
        return "geometry"
    return intent or "answer"


def _geometry_tasks(plan: dict[str, Any], message: str, selected_ids: list[str], intent: str) -> list[dict[str, Any]]:
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    workers = [
        task
        for task in tasks
        if isinstance(task, dict)
        and str(task.get("worker") or "") in (GEOMETRY_WORKERS | FINISH_WORKERS | APPEAR_WORKERS | {"explain", "edit"})
    ]
    if intent == "geometry":
        geometry = [task for task in workers if str(task.get("worker")) in GEOMETRY_WORKERS | {"edit"}]
        if not geometry:
            geometry = [
                {
                    "id": "geometry-1",
                    "worker": "geometry",
                    "instruction": message,
                    "target_ids": selected_ids,
                }
            ]
        return geometry[:1]
    if intent == "finish":
        finish = [task for task in workers if str(task.get("worker")) in FINISH_WORKERS]
        if not finish:
            finish = [
                {
                    "id": "finish-1",
                    "worker": "material" if selected_ids else "environment",
                    "instruction": message,
                    "target_ids": selected_ids,
                }
            ]
        return finish
    if intent == "appear":
        appear = [task for task in workers if str(task.get("worker")) in APPEAR_WORKERS]
        return appear or [
            {
                "id": "appear-1",
                "worker": "appear",
                "instruction": message,
                "target_ids": [],
            }
        ]
    return workers


def _blocked_from_error(error: str, target: str | None, building: Building) -> dict[str, Any]:
    wall = next((item for item in building.walls if item.id == target), None) if target else None
    if wall:
        return {"target_id": wall.id, "reason": _wall_block_reason(wall) if not _movable_wall(wall) else error}
    return {"target_id": target or "", "reason": error}


def _run_edit_tasks(
    tasks: list[dict[str, Any]],
    brief: dict[str, Any],
    selected_ids: list[str],
    building: Building,
    rules: list[dict],
    message: str,
    intent: str,
    report=None,
) -> dict[str, Any]:
    if report:
        report(phase="working", progress=0.4, message=f"Running {len(tasks)} edit worker{'s' if len(tasks) != 1 else ''}")
    serial = intent == "geometry"
    if serial:
        raw_results = [_run_subagent(task, brief, selected_ids) for task in tasks]
    else:
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(tasks))), thread_name_prefix="subagent") as pool:
            raw_results = list(pool.map(lambda task: _run_subagent(task, brief, selected_ids), tasks))

    commands: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    notes: list[str] = []
    appearance_prompt = ""
    for result in raw_results:
        commands.extend(result["commands"])
        blocked.extend(result["blocked"])
        if result["message"]:
            notes.append(result["message"])
        if result.get("appearance_prompt"):
            appearance_prompt = result["appearance_prompt"]

    if intent == "appear":
        prompt = _appearance_prompt(message, appearance_prompt or None)
        return _result(
            " ".join(notes) or "Prepared a photoreal exterior restyle. The 3D view can capture and paint it.",
            intent="appear",
            appearance_prompt=prompt,
            tasks=raw_results,
        )

    llm_commands = list(commands)
    if intent == "geometry" and commands:
        commands, extra_blocked = sanitize_geometry_commands(building, commands)
        blocked.extend(extra_blocked)

    if intent == "geometry" and not commands and not llm_commands:
        fallback = fallback_geometry_edit(building, rules, message, selected_ids, (brief.get("active_floor_ids") or [None])[0])
        if fallback["commands"]:
            return {**fallback, "tasks": raw_results}
        blocked.extend(fallback.get("blocked") or [])

    candidate, error, target = _try_apply(building, rules, commands) if commands else (None, None, None)
    if commands and error:
        log.info("chat.dry_run failed error=%s; retrying once compact", error)
        if report:
            report(phase="working", progress=0.62, message="Correcting the rejected design edit")
        first_error, first_target = error, target
        retried = [
            _run_subagent(
                result["task"],
                brief,
                selected_ids,
                correction=error,
                failed=commands,
                compact=True,
            )
            for result in raw_results
        ]
        commands = []
        blocked = []
        notes = []
        for result in retried:
            commands.extend(result["commands"])
            blocked.extend(result["blocked"])
            if result["message"]:
                notes.append(result["message"])
            raw_results = retried
        if intent == "geometry" and commands:
            commands, extra_blocked = sanitize_geometry_commands(building, commands)
            blocked.extend(extra_blocked)
        candidate, error, target = _try_apply(building, rules, commands) if commands else (None, first_error, first_target)
        if error:
            blocked.append(_blocked_from_error(error, target, building))
            return _result(
                _sanitize_edit_message(intent, "", [], blocked),
                intent=intent,
                blocked=blocked,
                tasks=raw_results,
            )

    if not commands and intent == "geometry":
        return _result(
            _sanitize_edit_message(intent, " ".join(notes), [], blocked),
            intent=intent,
            blocked=blocked,
            tasks=raw_results,
        )

    return _result(
        _sanitize_edit_message(intent, " ".join(notes), commands, blocked),
        intent=intent,
        commands=commands,
        blocked=blocked,
        tasks=raw_results,
        appearance_prompt=appearance_prompt or None,
    )


def _dispatch(
    plan: dict[str, Any],
    building: Building,
    rules: list[dict],
    selected_ids: list[str],
    brief: dict[str, Any],
    message: str,
    report=None,
) -> dict[str, Any]:
    intent = _normalize_intent(plan, message)
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    log.info("chat.dispatch intent=%s tasks=%d", intent, len(tasks) if isinstance(tasks, list) else 0)

    if intent == "repair" and not is_spatial_request(message):
        log.info("chat.agent=repair running propose_repairs")
        if report:
            report(phase="working", progress=0.35, message="Running geometry repair workers")
        proposal = propose_repairs(building, rules, report)
        if report:
            report(phase="working", progress=0.82, message="Writing the review summary")
        try:
            explanation = complete_json(
                SUBAGENT,
                [
                    {
                        "role": "system",
                        "content": 'Write a brief review of proposed repairs. Return JSON: {"message":"..."}. Do not change commands.',
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "summary": proposal.get("summary"),
                                "blocked": proposal.get("blocked"),
                                "ready": [task for task in proposal.get("tasks", []) if task.get("status") == "ready"][:12],
                            }
                        ),
                    },
                ],
            )
            review = str(explanation.get("message") or "")
        except LLMError:
            review = ""
        if not review:
            count = proposal["summary"]["proposed"]
            blocked = proposal["summary"]["blocked"]
            review = (
                f"I checked the approved requirements and prepared {count} verifiable repair"
                f"{'s' if count != 1 else ''}. {blocked} issue"
                f"{'s remain' if blocked != 1 else ' remains'} blocked. Review the changes before applying them."
            )
        return {**proposal, "message": review, "actor": "agent", "intent": "repair"}

    if intent in {"geometry", "finish", "appear", "edit"}:
        workers = _geometry_tasks(plan, message, selected_ids, "geometry" if intent == "edit" else intent)
        return _run_edit_tasks(workers, brief, selected_ids, building, rules, message, "geometry" if intent == "edit" else intent, report)

    if is_spatial_request(message):
        return fallback_geometry_edit(building, rules, message, selected_ids, (brief.get("active_floor_ids") or [None])[0])

    text = str(plan.get("message") or "").strip()
    if _looks_like_repair_summary(text):
        text = ""
    if not text:
        text = "I can review approved requirements, widen a hallway or room, change a selected finish, or set lighting. Describe one of those."
    return _result(text, intent="answer")


# ═════════════════════════════════════════════════════════════════════════════════
# NEW: UNIFIED EDIT AGENT FUNCTIONS (Hackathon improvements)
# ═════════════════════════════════════════════════════════════════════════════════

def detect_intent(message: str) -> str | None:
    """Detect user intent from message.

    Returns: 'geometry' | 'repair' | 'finish' | 'appear' | None
    """
    text = (message or "").lower()

    # Check in priority order
    # Repair takes priority if explicitly mentioned
    if bool(_REPAIR_RE.search(text)):
        return "repair"

    # Geometry (spatial edits)
    if bool(_SPATIAL_RE.search(text)):
        return "geometry"

    # Appearance (exterior styling)
    if bool(_APPEAR_RE.search(text)):
        return "appear"

    # Finish (materials, lighting, etc)
    if bool(_FINISH_RE.search(text)):
        return "finish"

    return None


def geometry_subagent(
    message: str,
    context: dict[str, Any],
    correction: str | None = None,
    failed_commands: list[dict[str, Any]] | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    """Generate geometry edit commands.

    Args:
        message: User instruction
        context: Building context
        correction: Error message if retrying
        failed_commands: Previous commands that failed
        compact: If True, use fast retry mode

    Returns: {"commands": [...], "blocked": [...], "message": "..."}
    """
    task = {
        "id": "geometry",
        "worker": "geometry",
        "instruction": message,
        "target_ids": [],
    }

    log.info("chat.geometry_subagent message=%r compact=%s retry=%s", message[:60], compact, bool(correction))

    payload_body: dict[str, Any] = {
        "task": task,
        "instruction": message,
        "target_ids": [],
        "building": context,
    }

    if correction:
        payload_body["dry_run_error"] = correction
        payload_body["failed_commands"] = failed_commands or []
        payload_body["retry"] = True

    system = GEOMETRY_RETRY_SYSTEM if compact else GEOMETRY_SYSTEM
    extra = {"max_tokens": 4800, "reasoning_effort": "low"} if compact else {}

    try:
        payload = complete_json(
            SUBAGENT,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload_body)},
            ],
            **extra,
        )
    except LLMError as exc:
        log.warning("chat.geometry_subagent_error error=%s", exc)
        return {"commands": [], "blocked": [], "message": ""}

    commands = _clean_commands(payload.get("commands"), [])
    blocked = payload.get("blocked") if isinstance(payload.get("blocked"), list) else []
    blocked = [item if isinstance(item, dict) else {"reason": str(item)} for item in blocked]

    log.info("chat.geometry_subagent done commands=%d blocked=%d", len(commands), len(blocked))

    return {
        "commands": commands,
        "blocked": blocked,
        "message": str(payload.get("message") or ""),
    }


def finish_subagent(
    message: str,
    context: dict[str, Any],
    correction: str | None = None,
    failed_commands: list[dict[str, Any]] | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    """Generate finish/material edit commands.

    Args:
        message: User instruction
        context: Building context
        correction: Error message if retrying
        failed_commands: Previous commands that failed
        compact: If True, use fast retry mode

    Returns: {"commands": [...], "blocked": [...], "message": "..."}
    """
    task = {
        "id": "finish",
        "worker": "finish",
        "instruction": message,
        "target_ids": [],
    }

    log.info("chat.finish_subagent message=%r compact=%s", message[:60], compact)

    payload_body: dict[str, Any] = {
        "task": task,
        "instruction": message,
        "target_ids": [],
        "building": context,
    }

    if correction:
        payload_body["dry_run_error"] = correction
        payload_body["failed_commands"] = failed_commands or []
        payload_body["retry"] = True

    system = FINISH_SYSTEM
    extra = {"max_tokens": 4800, "reasoning_effort": "low"} if compact else {}

    try:
        payload = complete_json(
            SUBAGENT,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload_body)},
            ],
            **extra,
        )
    except LLMError as exc:
        log.warning("chat.finish_subagent_error error=%s", exc)
        return {"commands": [], "blocked": [], "message": ""}

    commands = _clean_commands(payload.get("commands"), [])
    blocked = payload.get("blocked") if isinstance(payload.get("blocked"), list) else []
    blocked = [item if isinstance(item, dict) else {"reason": str(item)} for item in blocked]

    log.info("chat.finish_subagent done commands=%d blocked=%d", len(commands), len(blocked))

    return {
        "commands": commands,
        "blocked": blocked,
        "message": str(payload.get("message") or ""),
    }


def appear_subagent(
    message: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Generate appearance styling prompt.

    Args:
        message: User instruction
        context: Building context

    Returns: {"appearance_prompt": "...", "message": "..."}
    """
    task = {
        "id": "appear",
        "worker": "appear",
        "instruction": message,
        "target_ids": [],
    }

    log.info("chat.appear_subagent message=%r", message[:60])

    payload_body: dict[str, Any] = {
        "task": task,
        "instruction": message,
        "target_ids": [],
        "building": context,
    }

    try:
        payload = complete_json(
            SUBAGENT,
            [
                {"role": "system", "content": APPEAR_SYSTEM},
                {"role": "user", "content": json.dumps(payload_body)},
            ],
        )
    except LLMError as exc:
        log.warning("chat.appear_subagent_error error=%s", exc)
        return {"appearance_prompt": "", "message": ""}

    log.info("chat.appear_subagent done")

    return {
        "appearance_prompt": str(payload.get("appearance_prompt") or ""),
        "message": str(payload.get("message") or ""),
    }


def repair_subagent(
    failures: list[dict[str, Any]],
    message: str,
    context: dict[str, Any],
    compact: bool = False,
) -> dict[str, Any]:
    """Generate commands to fix compliance failures.

    Args:
        failures: List of failed check results from check_building()
        message: User message/intent
        context: Scoped building context
        compact: If True, use fast retry mode

    Returns: {"commands": [...], "blocked": [...], "message": "...", ...}
    """
    system = REPAIR_RETRY_SYSTEM if compact else REPAIR_SYSTEM

    payload_body = {
        "failures": failures,
        "message": message,
        "building": context,
        "failure_count": len(failures),
    }

    log.info("chat.repair_subagent failures=%d compact=%s", len(failures), compact)

    try:
        payload = complete_json(
            SUBAGENT,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload_body)},
            ],
            **({"max_tokens": 4800, "reasoning_effort": "low"} if compact else {}),
        )
    except LLMError as exc:
        log.warning("chat.repair_subagent_error error=%s", exc)
        return {
            "commands": [],
            "blocked": [],
            "message": "",
            "reasoning": "",
        }

    commands = _clean_commands(payload.get("commands"), [])
    blocked = payload.get("blocked") if isinstance(payload.get("blocked"), list) else []
    blocked = [item if isinstance(item, dict) else {"reason": str(item)} for item in blocked]

    log.info("chat.repair_subagent done commands=%d blocked=%d", len(commands), len(blocked))

    return {
        "commands": commands,
        "blocked": blocked,
        "message": str(payload.get("message") or ""),
        "reasoning": str(payload.get("reasoning") or ""),
    }


def try_apply_with_retry(
    commands: list[dict[str, Any]],
    building: Building,
    rules: list[dict],
    intent: str,
    message: str,
    context: dict[str, Any],
    subagent_fn: callable,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Apply commands with validation and one retry if needed.

    Args:
        commands: Commands to apply
        building: Building to modify
        rules: Compliance rules
        intent: Intent type ("geometry" | "repair" | "finish")
        message: User message
        context: Building context
        subagent_fn: Function to call for retry (should accept correction/failed params)
        max_retries: Max retry attempts

    Returns: {
        "candidate": Building | None,
        "commands": [...],
        "error": str | None,
        "target": str | None,
        "retry": bool,
        "blocked": [...]
    }
    """
    if not commands:
        return {
            "candidate": None,
            "commands": [],
            "error": None,
            "target": None,
            "retry": False,
            "blocked": [],
        }

    # Try 1: Apply commands
    candidate, error, target = _try_apply(building, rules, commands)

    if error and max_retries > 0:
        log.info("chat.validation_failed error=%s; retrying once", error)

        # Call subagent with error context
        if intent == "repair":
            retry_result = subagent_fn(
                failures=[],  # Not used in retry
                message=message,
                context=context,
                compact=True,
            )
        else:
            # Geometry/finish use different signature
            retry_result = subagent_fn(
                message=message,
                context=context,
                correction=error,
                failed_commands=commands,
                compact=True,
            )

        retry_commands = retry_result.get("commands", [])
        candidate, error, target = _try_apply(building, rules, retry_commands)

        return {
            "candidate": candidate,
            "commands": retry_commands if not error else [],
            "error": error,
            "target": target,
            "retry": True,
            "blocked": retry_result.get("blocked", []),
        }

    return {
        "candidate": candidate,
        "commands": commands if not error else [],
        "error": error,
        "target": target,
        "retry": False,
        "blocked": [],
    }


def respond_unified(
    building: Building,
    rules: list[dict],
    message: str,
    context: str = "2D",
    selected_ids: list[str] | None = None,
    report: callable | None = None,
    floor_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """New unified edit agent.

    Single pipeline for all intents: geometry, repair, finish, appear.
    """
    selected_ids = selected_ids or []
    settings = get_settings()

    log.info("chat.unified_agent message=%r context=%s", message[:100], context)

    # Step 1: Detect intent
    intent = detect_intent(message)
    if intent is None:
        log.info("chat.unified_agent intent=none (answer mode)")
        return _result(
            "I can widen rooms, fix compliance failures, paint materials, or restyle the exterior. What would you like?",
            intent="answer",
        )

    log.info("chat.unified_agent intent=%s", intent)

    if report:
        report(phase="planning", progress=0.2, message="Analyzing your request")

    # Step 2: Build context
    scoped = _scoped_brief(building, rules, selected_ids, message, floor_id)

    if report:
        report(phase="working", progress=0.4, message=f"Planning {intent} edits")

    # Step 3: Call appropriate subagent
    if intent == "repair":
        failures = check_building(building, rules)
        if not failures:
            return _result("The building already passes all compliance checks!", intent="answer")

        result = repair_subagent(failures, message, scoped)

        def retry_fn(**kw):
            return repair_subagent(failures, message, scoped, **kw)

    elif intent == "geometry":
        result = geometry_subagent(message, scoped)

        def retry_fn(**kw):
            return geometry_subagent(message, scoped, **kw)

    elif intent == "finish":
        result = finish_subagent(message, scoped)

        def retry_fn(**kw):
            return finish_subagent(message, scoped, **kw)

    elif intent == "appear":
        # Appearance doesn't need validation/retry
        result = appear_subagent(message, scoped)
        if report:
            report(phase="done", progress=1.0, message="Prepared exterior styling")
        return _result(
            result.get("message", "Updated exterior appearance"),
            intent="appear",
            appearance_prompt=result.get("appearance_prompt"),
        )

    # Step 4: Validate + Retry
    if report:
        report(phase="working", progress=0.6, message="Validating design")

    validation = try_apply_with_retry(
        result.get("commands", []),
        building,
        rules,
        intent,
        message,
        scoped,
        retry_fn,
    )

    if validation["error"]:
        log.warning("chat.validation_failed after_retry intent=%s error=%s", intent, validation["error"])
        blocked = validation.get("blocked", [])
        blocked.append({"reason": validation["error"], "target_id": validation["target"]})

        if report:
            report(phase="done", progress=1.0, message="Design validation failed")

        return _result(
            f"I can't apply this {intent} edit: {validation['error']}",
            intent=intent,
            blocked=blocked,
            commands=[],
        )

    # Step 5: Check compliance after edits
    if report:
        report(phase="working", progress=0.85, message="Checking compliance")

    compliance_after = check_building(validation["candidate"], rules) if validation["candidate"] else []
    failures_after = [c for c in compliance_after if c["status"] == "fail"]

    note = ""
    if failures_after:
        count = len(failures_after)
        note = f" ({count} compliance check{'s' if count != 1 else ''} still needs attention)"

    if report:
        report(phase="done", progress=1.0, message="Design updated")

    message_text = result.get("message", "Design updated")
    if note:
        message_text += note

    log.info("chat.unified_agent done intent=%s commands=%d retry=%s",
             intent, len(validation["commands"]), validation["retry"])

    return _result(
        message_text,
        intent=intent,
        commands=validation["commands"],
        blocked=validation.get("blocked", []),
        compliance=failures_after,
    )


# ═════════════════════════════════════════════════════════════════════════════════
# NEW AGENT: Repair + Geometry flows with snapshot comparison
# ═════════════════════════════════════════════════════════════════════════════════

def respond_new(
    building: Building,
    rules: list[dict],
    prompt: str,
    fix_new_issues: bool = False,
    violations: list[dict] | None = None,
    report: callable | None = None,
    context: str = "2D",
    floor_id: str | None = None,
    selected_ids: list[str] | None = None,
    history: list[dict] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """New unified flow: Repair or Geometry with new issue detection."""
    selected_ids = selected_ids or []
    history = history or []
    log.info("agent.start prompt=%r fix_new=%s violations_selected=%d floor=%s",
             prompt[:60], fix_new_issues, len(violations or []), floor_id)

    # ─────────────────────────────────────────────────────────────────────
    # Step 0: Setup - Create context and snapshot
    # ─────────────────────────────────────────────────────────────────────

    # Get current building state
    all_violations = check_building(building, rules)
    log.info("agent.setup all_violations=%d", len(all_violations))

    # If violations selected (from prepare repairs button), those are targets
    # Otherwise empty (from chat)
    violations_to_repair = violations if violations else []

    # Build set of IDs being repaired for reliable comparison
    repair_ids = {v.get("id") or v.get("rule_id") for v in violations_to_repair}

    # Snapshot: violation IDs we're NOT fixing (to detect truly new issues later)
    snapshot_ids = {v.get("id") for v in all_violations if v.get("id") not in repair_ids}
    log.info("agent.snapshot snapshot_count=%d violations_to_repair=%d repair_ids=%s",
             len(snapshot_ids), len(violations_to_repair), repair_ids)

    # ─────────────────────────────────────────────────────────────────────
    # Step 1: Orchestrator - Decide intent and which violations to fix
    # ─────────────────────────────────────────────────────────────────────

    log.info("agent.orchestrator calling llm prompt=%r", prompt[:80])

    # Build history turns for context
    turns = []
    for item in history[-6:]:
        if isinstance(item, dict):
            role = str(item.get("role") or "user")
            text = str(item.get("text") or item.get("content") or "")
            if text:
                turns.append({"role": role, "text": text})

    try:
        plan = complete_json(
            ORCHESTRATOR,
            [
                {"role": "system", "content": ORCHESTRATOR_UNIFIED_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps({
                        "prompt": prompt,
                        "context": context,
                        "floor_id": floor_id,
                        "history": turns[-4:] if turns else [],
                        "all_violations": [
                            {
                                "id": v.get("id") or v.get("rule_id"),
                                "rule": v.get("rule") or v.get("rule_id"),
                                "message": v.get("message", ""),
                                "status": v.get("status", "fail")
                            }
                            for v in all_violations
                        ],
                        "violations_selected_count": len(violations_to_repair),
                    })
                },
            ],
        )
    except LLMError as exc:
        log.warning("agent.orchestrator_error error=%s", exc)
        return _result(f"Error deciding what to do: {exc}", intent="answer")

    intent = plan.get("intent", "answer").lower()
    violations_to_repair = plan.get("violations_to_repair") or violations_to_repair

    log.info("agent.orchestrator_result intent=%s violations_to_repair=%d",
             intent, len(violations_to_repair or []))

    # Override: if repair intent, ALWAYS fix new issues
    if intent == "repair":
        fix_new_issues = True
        log.info("agent.override repair_intent forcing fix_new_issues=true")

    # ─────────────────────────────────────────────────────────────────────
    # Step 2: Execute based on intent
    # ─────────────────────────────────────────────────────────────────────

    if intent == "repair":
        return _execute_repair_flow(
            building, rules, prompt, violations_to_repair,
            snapshot_ids, all_violations, fix_new_issues, report,
            floor_id=floor_id, selected_ids=selected_ids,
        )

    elif intent == "geometry":
        return _execute_geometry_flow(
            building, rules, prompt,
            snapshot_ids, all_violations, fix_new_issues, report,
            floor_id=floor_id, selected_ids=selected_ids,
        )

    elif intent == "finish":
        result = finish_subagent(prompt, _scoped_brief(building, rules, selected_ids, prompt, floor_id))
        if report:
            report(phase="done", progress=1.0, message="Applied finish")

        final_building = apply_commands(building, result.get("commands", []))
        log.info("agent.finish_flow done commands=%d", len(result.get("commands", [])))

        return {
            "intent": "finish",
            "message": result.get("message", "Applied finish"),
            "commands": result.get("commands", []),
            "blocked": result.get("blocked", []),
            "llm_calls_made": 1,
            "new_issues_found": [],
            "fixed_new_issues": [],
            "unfixed_new_issues": [],
        }

    elif intent == "appear":
        result = appear_subagent(prompt, _scoped_brief(building, rules, selected_ids, prompt, floor_id))
        if report:
            report(phase="done", progress=1.0, message="Applied appearance")

        log.info("agent.appear_flow done")

        return {
            "intent": "appear",
            "message": result.get("message", "Applied appearance styling"),
            "commands": [],
            "blocked": [],
            "llm_calls_made": 1,
            "new_issues_found": [],
            "fixed_new_issues": [],
            "unfixed_new_issues": [],
            "appearance_prompt": result.get("appearance_prompt"),
        }

    else:  # answer
        log.info("agent.answer_flow answering question")
        brief = _scoped_brief(building, rules, selected_ids, prompt, floor_id)
        try:
            answer_text = complete(
                SUBAGENT,
                [
                    {"role": "system", "content": "You are a helpful building design assistant. Answer the user's question about their building using the context provided. Be concise and friendly."},
                    {"role": "user", "content": f"Building context:\n{brief}\n\nQuestion: {prompt}"},
                ],
                json_mode=False,
                timeout=15,
            )
        except LLMError:
            answer_text = plan.get("message", "I can help with geometry, repairs, finishes, or styling. What would you like?")
        return {
            "intent": "answer",
            "message": answer_text,
            "commands": [],
            "blocked": [],
            "llm_calls_made": 2,
            "new_issues_found": [],
            "fixed_new_issues": [],
            "unfixed_new_issues": [],
        }


def _execute_repair_flow(
    building: Building,
    rules: list[dict],
    prompt: str,
    violations_to_repair: list[dict],
    snapshot_ids: set[str],
    all_violations: list[dict],
    fix_new_issues: bool,
    report: callable | None,
    floor_id: str | None = None,
    selected_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Execute repair intent: deterministic fixes, then geometry LLM if new issues."""
    selected_ids = selected_ids or []

    log.info("agent.repair_flow starting violations_to_repair=%d", len(violations_to_repair))

    if report:
        report(phase="working", progress=0.2, message="Running deterministic repairs")

    # ─────────────────────────────────────────────────────────────────────
    # 3A-1: Deterministic pass through propose_repairs
    # ─────────────────────────────────────────────────────────────────────

    try:
        proposal = propose_repairs(building, rules, report)
        log.info("agent.repair.deterministic commands=%d blocked=%d",
                 len(proposal.get("commands", [])), len(proposal.get("blocked", [])))
    except Exception as exc:
        log.warning("agent.repair.deterministic_error error=%s", exc)
        return _result(f"Repair failed: {exc}", intent="repair", blocked=[{"reason": str(exc)}])

    building_after_repair = apply_commands(building, proposal.get("commands", []))

    # ─────────────────────────────────────────────────────────────────────
    # 3A-2: Check for new issues
    # ─────────────────────────────────────────────────────────────────────

    if report:
        report(phase="working", progress=0.4, message="Checking for new issues")

    current_violations = check_building(building_after_repair, rules)
    new_violations = [
        v for v in current_violations
        if v.get("id") not in snapshot_ids and v.get("status") == "fail"
    ]

    # Also include violations that deterministic repair blocked (couldn't fix)
    blocked_items = proposal.get("blocked", [])
    blocked_entity_ids = {b.get("entity_id") or b.get("check_id", "") for b in blocked_items}
    still_failing = [
        v for v in current_violations
        if v.get("status") == "fail"
        and (v.get("entity_id") in blocked_entity_ids or v.get("id") in blocked_entity_ids)
        and v.get("id") not in {nv.get("id") for nv in new_violations}
    ]
    issues_for_llm = new_violations + still_failing

    log.info("agent.repair.check_new new_violations=%d blocked_still_failing=%d total_for_llm=%d",
             len(new_violations), len(still_failing), len(issues_for_llm))

    fixed_new_commands = []
    unfixed_new = new_violations.copy()
    llm_calls = 0

    # ─────────────────────────────────────────────────────────────────────
    # 3A-3: If issues remain and fix_new_issues=true, use geometry LLM
    # ─────────────────────────────────────────────────────────────────────

    if issues_for_llm and fix_new_issues:
        # Filter to only violations on floors we have context for
        active_floors = {floor_id} if floor_id else {f.id for f in building.floors}
        reachable = [v for v in issues_for_llm
                     if any(v.get("entity_id", "").startswith(fid + "-") for fid in active_floors)]
        unreachable = [v for v in issues_for_llm if v not in reachable]
        if unreachable:
            log.info("agent.repair.skipping_unreachable count=%d floors=%s",
                     len(unreachable), {v.get("entity_id", "").split("-")[0] for v in unreachable})

        if not reachable:
            log.info("agent.repair.geometry_fallback skipped all_unreachable=%d", len(issues_for_llm))
        else:
            log.info("agent.repair.geometry_fallback calling llm reachable=%d", len(reachable))

        if reachable:
            if report:
                report(phase="working", progress=0.6, message="Fixing issues with geometry LLM")

            context = _scoped_brief(building_after_repair, rules, selected_ids, prompt, floor_id)

            # Format only reachable issues for LLM
            issues_text = "\n".join([
                f"- {v.get('rule_name', v.get('rule_id'))}: {v.get('message', '')}"
                for v in reachable
            ])

            result = geometry_subagent(
                message=f"Fix these issues:\n{issues_text}",
                context=context,
                correction=None,
            )

            fixed_new_commands = result.get("commands", [])
            llm_calls = 1

            log.info("agent.repair.geometry_fallback commands=%d blocked=%d",
                     len(fixed_new_commands), len(result.get("blocked", [])))

            # ─────────────────────────────────────────────────────────────────
            # 3A-3b: Validate and retry if needed
            # ─────────────────────────────────────────────────────────────────

            if fixed_new_commands:
                if report:
                    report(phase="working", progress=0.7, message="Validating new issue fixes")

                candidate, error, target = _try_apply(building_after_repair, rules, fixed_new_commands)

                if error:
                    log.info("agent.repair.geometry_fallback validation_failed retrying compact error=%s", error)

                    if report:
                        report(phase="working", progress=0.75, message="Retrying fix for new issues")

                    result = geometry_subagent(
                        message=f"Fix these issues:\n{issues_text}",
                        context=context,
                        correction=error,
                        failed_commands=fixed_new_commands,
                        compact=True,
                    )

                    fixed_new_commands = result.get("commands", [])
                    llm_calls += 1

                log.info("agent.repair.geometry_fallback retry commands=%d", len(fixed_new_commands))

                if fixed_new_commands:
                    candidate, error, target = _try_apply(building_after_repair, rules, fixed_new_commands)

    # ─────────────────────────────────────────────────────────────────────
    # 3A-4: Final state
    # ─────────────────────────────────────────────────────────────────────

    final_building = apply_commands(building_after_repair, fixed_new_commands)
    final_violations = check_building(final_building, rules)

    # Which new violations did we actually fix?
    final_ids = {v.get("id") for v in final_violations}
    unfixed_new = [v for v in new_violations if v.get("id") in final_ids]
    fixed_new = [v for v in new_violations if v.get("id") not in final_ids]

    all_commands = proposal.get("commands", []) + fixed_new_commands
    log.info("agent.repair_flow.done llm_calls=%d fixed_new=%d unfixed_new=%d total_commands=%d",
             llm_calls, len(fixed_new), len(unfixed_new), len(all_commands))

    if report:
        report(phase="done", progress=1.0, message="Repair complete")

    new_issues_note = ""
    if unfixed_new:
        count = len(unfixed_new)
        new_issues_note = f" ({count} new issue{'s' if count != 1 else ''} still need attention)"

    return {
        "intent": "repair",
        "message": proposal.get("message", "Applied repairs") + new_issues_note,
        "commands": all_commands,
        "blocked": proposal.get("blocked", []),
        "llm_calls_made": llm_calls,
        "new_issues_found": new_violations,
        "fixed_new_issues": fixed_new,
        "unfixed_new_issues": unfixed_new,
    }


def _execute_geometry_flow(
    building: Building,
    rules: list[dict],
    prompt: str,
    snapshot_ids: set[str],
    all_violations: list[dict],
    fix_new_issues: bool,
    report: callable | None,
    floor_id: str | None = None,
    selected_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Execute geometry intent: LLM edits, then geometry LLM again if new issues."""
    selected_ids = selected_ids or []

    log.info("agent.geometry_flow starting prompt=%r", prompt[:80])

    if report:
        report(phase="working", progress=0.2, message="Planning geometry edits")

    # ─────────────────────────────────────────────────────────────────────
    # 3B-1: Geometry LLM
    # ─────────────────────────────────────────────────────────────────────

    context = _scoped_brief(building, rules, selected_ids, prompt, floor_id)

    result = geometry_subagent(prompt, context, correction=None)
    original_commands = result.get("commands", [])
    original_blocked = result.get("blocked", [])
    original_message = result.get("message", "Applied geometry edits")
    llm_calls = 1
    log.info("agent.geometry.llm commands=%d blocked=%d",
             len(original_commands), len(original_blocked))

    if report:
        report(phase="working", progress=0.35, message="Validating geometry edits")

    # Validate initial commands with retry
    building_after_geo = building
    if original_commands:
        candidate, error, target = _try_apply(building, rules, original_commands)
        if error:
            log.info("agent.geometry.initial_validation_failed error=%s retrying", error)
            if report:
                report(phase="working", progress=0.4, message="Retrying geometry edits")
            result = geometry_subagent(
                prompt, context,
                correction=error,
                failed_commands=original_commands,
                compact=True,
            )
            original_commands = result.get("commands", [])
            original_blocked = result.get("blocked", []) + original_blocked
            original_message = result.get("message", original_message)
            llm_calls += 1
            log.info("agent.geometry.retry commands=%d blocked=%d",
                     len(original_commands), len(original_blocked))
            if original_commands:
                candidate, error, target = _try_apply(building, rules, original_commands)
                if error:
                    log.warning("agent.geometry.retry_also_failed error=%s", error)
                    original_commands = []
                    original_blocked = original_blocked + [{"reason": error}]
        if original_commands and candidate is not None:
            building_after_geo = candidate

    if report:
        report(phase="working", progress=0.5, message="Checking for new issues")

    # ─────────────────────────────────────────────────────────────────────
    # 3B-2: Check for new issues
    # ─────────────────────────────────────────────────────────────────────

    current_violations = check_building(building_after_geo, rules)
    new_violations = [
        v for v in current_violations
        if v.get("id") not in snapshot_ids and v.get("status") == "fail"
    ]
    log.info("agent.geometry.check_new new_violations=%d", len(new_violations))

    fixed_new_commands = []
    unfixed_new = new_violations.copy()

    # ─────────────────────────────────────────────────────────────────────
    # 3B-3: If new issues and fix_new_issues=true, geometry LLM again
    # ─────────────────────────────────────────────────────────────────────

    if new_violations and fix_new_issues:
        # Filter to only violations on active floors
        active_floors = {floor_id} if floor_id else {f.id for f in building.floors}
        reachable = [v for v in new_violations
                     if any(v.get("entity_id", "").startswith(fid + "-") for fid in active_floors)]
        if not reachable:
            log.info("agent.geometry.fix_new skipped all_unreachable=%d", len(new_violations))
        else:
            log.info("agent.geometry.fix_new calling llm reachable=%d", len(reachable))

        if reachable:
            if report:
                report(phase="working", progress=0.65, message="Fixing new issues that appeared")

            context = _scoped_brief(building_after_geo, rules, selected_ids, prompt, floor_id)

            issues_text = "\n".join([
                f"- {v.get('rule_name', v.get('rule_id'))}: {v.get('message', '')}"
                for v in reachable
            ])

            result = geometry_subagent(
                message=f"Your edits created new issues. Fix these:\n{issues_text}",
                context=context,
                correction=None,
            )

            fixed_new_commands = result.get("commands", [])
            llm_calls += 1

            log.info("agent.geometry.fix_new commands=%d blocked=%d",
                     len(fixed_new_commands), len(result.get("blocked", [])))

            # Validate and retry if needed
            if fixed_new_commands:
                if report:
                    report(phase="working", progress=0.75, message="Validating new issue fixes")

                candidate, error, target = _try_apply(building_after_geo, rules, fixed_new_commands)

                if error:
                    log.info("agent.geometry.fix_new validation_failed retrying compact error=%s", error)

                    if report:
                        report(phase="working", progress=0.8, message="Retrying fix for new issues")

                    result = geometry_subagent(
                        message=f"Fix these issues:\n{issues_text}",
                        context=context,
                        correction=error,
                        failed_commands=fixed_new_commands,
                        compact=True,
                    )

                    fixed_new_commands = result.get("commands", [])
                    llm_calls += 1

                    log.info("agent.geometry.fix_new retry commands=%d", len(fixed_new_commands))

                    if fixed_new_commands:
                        candidate, error, target = _try_apply(building_after_geo, rules, fixed_new_commands)

    # ─────────────────────────────────────────────────────────────────────
    # 3B-4: Final state
    # ─────────────────────────────────────────────────────────────────────

    final_building = apply_commands(building_after_geo, fixed_new_commands)
    final_violations = check_building(final_building, rules)

    # Which new violations did we actually fix?
    final_ids = {v.get("id") for v in final_violations}
    unfixed_new = [v for v in new_violations if v.get("id") in final_ids]
    fixed_new = [v for v in new_violations if v.get("id") not in final_ids]

    log.info("agent.geometry_flow.done llm_calls=%d fixed_new=%d unfixed_new=%d",
             llm_calls, len(fixed_new), len(unfixed_new))

    if report:
        report(phase="done", progress=1.0, message="Geometry edits complete")

    new_issues_note = ""
    if unfixed_new:
        count = len(unfixed_new)
        new_issues_note = f" ({count} new issue{'s' if count != 1 else ''} appeared)"

    return {
        "intent": "geometry",
        "message": original_message + new_issues_note,
        "commands": original_commands + fixed_new_commands,
        "blocked": original_blocked,
        "llm_calls_made": llm_calls,
        "new_issues_found": new_violations,
        "fixed_new_issues": fixed_new,
        "unfixed_new_issues": unfixed_new,
    }


def respond(
    building,
    rules,
    message,
    context="2D",
    selected_ids=None,
    report=None,
    floor_id=None,
    history=None,
    appearance=None,
    brief=None,
):
    selected_ids = selected_ids or []
    history = history or []
    settings = get_settings()
    log.info(
        "chat.start live=%s context=%s floor=%s selected=%d message=%r",
        settings.agent_live(),
        context,
        floor_id,
        len(selected_ids),
        message[:200],
    )
    if not settings.agent_live():
        log.info("chat.agent=mock path=local-fallback")
        return local_respond(building, rules, message, context, selected_ids, report, floor_id, history)
    try:
        if report:
            report(phase="planning", progress=0.2, message="Orchestrator is assigning work")
        scoped = _scoped_brief(building, rules, selected_ids, message, floor_id)
        if isinstance(brief, dict):
            scoped = {**scoped, **{key: brief[key] for key in brief if key not in scoped or brief[key]}}
        log.info(
            "chat.agent=orchestrator planning failures=%d rooms=%d walls=%d floors=%s",
            len(scoped.get("failures") or []),
            len(scoped.get("rooms") or []),
            len(scoped.get("walls") or []),
            scoped.get("active_floor_ids"),
        )
        turns = []
        for item in history[-6:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user")
            text = str(item.get("text") or item.get("content") or "")
            if text:
                turns.append({"role": role, "text": text})
        plan = complete_json(
            ORCHESTRATOR,
            [
                {"role": "system", "content": ORCHESTRATOR_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": message,
                            "context": context,
                            "floor_id": floor_id,
                            "history": turns,
                            "appearance": appearance,
                            "building": scoped,
                        }
                    ),
                },
            ],
        )
        log.info(
            "chat.agent=orchestrator intent=%s tasks=%d message=%r",
            plan.get("intent"),
            len(plan.get("tasks") or []) if isinstance(plan.get("tasks"), list) else 0,
            str(plan.get("message") or "")[:160],
        )
        return _dispatch(plan, building, rules, selected_ids, scoped, message, report)
    except LLMError as exc:
        log.warning("chat.llm_error falling_back_to_mock error=%s", exc)
        fallback = local_respond(building, rules, message, context, selected_ids, report, floor_id, history)
        fallback["message"] = fallback.get("message") or "The model is unavailable, so I used the local assistant instead."
        return fallback
