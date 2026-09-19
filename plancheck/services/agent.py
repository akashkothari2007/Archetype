"""Chat agent: a thinking orchestrator delegates bounded tasks to cheaper subagents."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from plancheck.core.building import Building
from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings
from plancheck.mocks.agent_provider import respond as mock_respond
from plancheck.services.compliance import check_building
from plancheck.services.llm import LLMError, ORCHESTRATOR, SUBAGENT, complete_json
from plancheck.services.repairs import propose_repairs

log = get_logger("plancheck.agent")

ALLOWED_COMMANDS = {
    "set_material",
    "set_environment",
    "rename_room",
    "update_object",
    "place_object",
    "duplicate",
}
ALLOWED_MATERIALS = {"plaster", "oak", "tile", "concrete", "sage", "terracotta", "white"}

ORCHESTRATOR_SYSTEM = """You are the Archetype orchestrator for a local building-design app.
Plan only. Do not invent measurements or pass/fail verdicts; compliance is computed separately.
A human reviews every edit before it is applied. Never request changes to loadbearing or locked walls.
Return JSON only:
{"intent":"repair"|"edit"|"answer","message":"short user-facing text","tasks":[{"id":"t1","worker":"repair"|"material"|"environment"|"rename"|"explain","instruction":"...","target_ids":[]}]}
Use repair when the user wants issues fixed. Keep tasks small. Prefer one repair task."""

SUBAGENT_SYSTEM = """You are a bounded Archetype subagent. Return JSON only:
{"commands":[{"kind":"...","target_id":"","params":{}}],"message":"short user-facing text","blocked":[{"reason":"..."}]}
Allowed command kinds: set_material, set_environment, rename_room, update_object, place_object, duplicate.
set_material materials: plaster, oak, tile, concrete, sage, terracotta, white.
set_environment params: time (0-24), season (spring|summer|autumn|winter), sun_azimuth.
If the request needs a loadbearing or locked wall change, add a blocked reason and return no commands.
Do not invent entity ids."""


def _entity_snapshot(building: Building, entity_id: str) -> dict[str, Any] | None:
    for room in building.rooms:
        if room.id == entity_id:
            return {"kind": "room", "id": room.id, "name": room.name, "category": room.category, "floor_id": room.floor_id, "material": room.floor_material}
    for wall in building.walls:
        if wall.id == entity_id:
            return {"kind": "wall", "id": wall.id, "floor_id": wall.floor_id, "structural": wall.structural, "locked": wall.locked, "material": wall.material}
    for obj in building.objects:
        if obj.id == entity_id:
            return {"kind": "object", "id": obj.id, "asset_id": obj.asset_id, "floor_id": obj.floor_id, "x": obj.x, "y": obj.y}
    for opening in building.openings:
        if opening.id == entity_id:
            return {"kind": "opening", "id": opening.id, "kind_name": opening.kind, "wall_id": opening.wall_id, "width_ft": opening.width_ft}
    return {"kind": "unknown", "id": entity_id}


def _brief(building: Building, rules: list[dict], selected_ids: list[str]) -> dict[str, Any]:
    failures = [
        {
            "id": check.get("id"),
            "metric": check.get("metric"),
            "entity_id": check.get("entity_id"),
            "message": check.get("message"),
            "status": check.get("status"),
        }
        for check in check_building(building, rules)
        if check.get("status") == "fail"
    ]
    return {
        "floors": [{"id": f.id, "name": f.name} for f in building.floors],
        "rooms": [
            {"id": r.id, "name": r.name, "category": r.category, "floor_id": r.floor_id}
            for r in building.rooms
        ],
        "environment": building.environment.model_dump(),
        "selected": [_entity_snapshot(building, eid) for eid in selected_ids],
        "failures": failures[:40],
        "approved_rules": sum(1 for rule in rules if rule.get("status") == "approved"),
    }


def _clean_commands(raw: Any, selected_ids: list[str]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return commands
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind not in ALLOWED_COMMANDS:
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
        elif kind in {"update_object", "place_object", "duplicate"} and not target and selected_ids:
            target = selected_ids[0]
        commands.append({"kind": kind, "target_id": target, "params": params})
    return commands[:40]


def _empty(message: str, **extra: Any) -> dict[str, Any]:
    return {
        "commands": [],
        "tasks": [],
        "blocked": extra.get("blocked", []),
        "message": message,
        "actor": extra.get("actor", "agent"),
        "summary": extra.get("summary", {"proposed": 0, "blocked": extra.get("blocked_count", 0)}),
        **{k: v for k, v in extra.items() if k not in {"blocked", "actor", "summary", "blocked_count"}},
    }


def _run_subagent(task: dict[str, Any], brief: dict[str, Any], selected_ids: list[str]) -> dict[str, Any]:
    log.info(
        "chat.agent=subagent worker=%s task=%s targets=%s",
        task.get("worker"),
        task.get("id"),
        task.get("target_ids"),
    )
    payload = complete_json(
        SUBAGENT,
        [
            {"role": "system", "content": SUBAGENT_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": task,
                        "selected": brief.get("selected"),
                        "rooms": brief.get("rooms"),
                        "environment": brief.get("environment"),
                    }
                ),
            },
        ],
    )
    commands = _clean_commands(payload.get("commands"), selected_ids)
    blocked = payload.get("blocked") if isinstance(payload.get("blocked"), list) else []
    message = str(payload.get("message") or "Prepared a small change for review.")
    log.info("chat.agent=subagent done commands=%d blocked=%d", len(commands), len(blocked))
    return {"commands": commands, "blocked": blocked, "message": message, "task": task}


def _dispatch(plan: dict[str, Any], building: Building, rules: list[dict], selected_ids: list[str], brief: dict[str, Any], report=None) -> dict[str, Any]:
    intent = str(plan.get("intent") or "answer").lower()
    tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    log.info("chat.dispatch intent=%s tasks=%d", intent, len(tasks))
    if intent == "repair" or any(str(task.get("worker")) == "repair" for task in tasks if isinstance(task, dict)):
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
                    {"role": "system", "content": "Write a brief review of proposed repairs. Return JSON: {\"message\":\"...\"}. Do not change commands."},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "summary": proposal.get("summary"),
                                "blocked": proposal.get("blocked"),
                                "ready": [t for t in proposal.get("tasks", []) if t.get("status") == "ready"][:12],
                            }
                        ),
                    },
                ],
            )
            message = str(explanation.get("message") or "")
        except LLMError:
            message = ""
        if not message:
            count = proposal["summary"]["proposed"]
            blocked = proposal["summary"]["blocked"]
            message = (
                f"I checked the approved requirements and prepared {count} verifiable repair"
                f"{'s' if count != 1 else ''}. {blocked} issue"
                f"{'s remain' if blocked != 1 else ' remains'} blocked. Review the changes before applying them."
            )
        return {**proposal, "message": message, "actor": "agent"}

    workers = [task for task in tasks if isinstance(task, dict) and str(task.get("worker")) in {"material", "environment", "rename", "explain"}]
    if intent == "edit" and not workers:
        workers = [{"id": "edit-1", "worker": "material" if selected_ids else "environment", "instruction": plan.get("message") or "", "target_ids": selected_ids}]
    if workers and intent != "answer":
        if report:
            report(phase="working", progress=0.4, message=f"Running {len(workers)} subagent{'s' if len(workers) != 1 else ''}")
        with ThreadPoolExecutor(max_workers=min(4, len(workers)), thread_name_prefix="subagent") as pool:
            results = list(pool.map(lambda task: _run_subagent(task, brief, selected_ids), workers))
        commands: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        notes: list[str] = []
        for result in results:
            commands.extend(result["commands"])
            blocked.extend([item if isinstance(item, dict) else {"reason": str(item)} for item in result["blocked"]])
            if result["message"]:
                notes.append(result["message"])
        message = " ".join(notes) or str(plan.get("message") or "Prepared changes for your review.")
        return {
            "commands": commands,
            "tasks": results,
            "blocked": blocked,
            "message": message,
            "actor": "user",
            "summary": {"proposed": len(commands), "blocked": len(blocked), "workers": len(workers)},
        }

    message = str(plan.get("message") or "").strip()
    if not message:
        message = "I can review approved requirements, prepare repairs, change a selected finish, or set lighting. Describe one of those."
    return _empty(message)


def respond(building, rules, message, context="2D", selected_ids=None, report=None):
    selected_ids = selected_ids or []
    settings = get_settings()
    log.info(
        "chat.start live=%s context=%s selected=%d message=%r",
        settings.agent_live(),
        context,
        len(selected_ids),
        message[:200],
    )
    if not settings.agent_live():
        log.info("chat.agent=mock path=local-fallback")
        return mock_respond(building, rules, message, context, selected_ids, report)
    try:
        if report:
            report(phase="planning", progress=0.2, message="Orchestrator is assigning work")
        brief = _brief(building, rules, selected_ids)
        log.info("chat.agent=orchestrator planning failures=%d rooms=%d", len(brief.get("failures") or []), len(brief.get("rooms") or []))
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
                            "building": brief,
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
        return _dispatch(plan, building, rules, selected_ids, brief, report)
    except LLMError as exc:
        log.warning("chat.llm_error falling_back_to_mock error=%s", exc)
        fallback = mock_respond(building, rules, message, context, selected_ids, report)
        fallback["message"] = (
            fallback.get("message")
            or "The model is unavailable, so I used the local assistant instead."
        )
        return fallback
