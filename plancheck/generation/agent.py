"""The generate job: at most two model calls, then deterministic geometry.

The model is asked once for a space program. Packing, compiling, validating,
checking and repairing all run here, exactly once per attempt. If the geometry
cannot be built the model gets one corrective turn with the real error, and
that is the end of it -- there is no free-running tool loop to spin in.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from plancheck.core.building import Building, DesignBrief
from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings
from plancheck.generation import defaults, prompts
from plancheck.generation.compiler import CompileError, compile_building
from plancheck.generation.layout import LayoutError, pack_floors
from plancheck.generation.program import BuildingProgram, FloorLayout
from plancheck.services.commands import CommandError, apply_commands
from plancheck.services.compliance import check_building
from plancheck.services.llm import GENERATION, LLMError, complete_json
from plancheck.services.repairs import propose_repairs

MAX_LLM_CALLS = 2
# Whole-job wall clock. A reasoning model needs roughly half a minute to write a
# program, so the budget has to cover the one corrective turn the design allows
# and still guarantee the job cannot sit there spinning.
DEADLINE_S = 150.0
DEMO_PROVIDERS = {"", "demo", "mock", "stub", "off", "none"}
LIVE_PROVIDERS = {"baseten", "agent", "real", "live", "model"}

Reporter = Callable[..., Any]
log = get_logger("plancheck.generation")


class GenerationError(RuntimeError):
    """Generation could not produce geometry. The job fails; nothing is written."""


@dataclass
class GenerationResult:
    building: Building
    rules: list[dict]
    program: dict[str, Any] | None = None
    layouts: dict[str, Any] = field(default_factory=dict)
    llm_calls: int = 0
    notes: str = ""
    recovered_from: list[str] = field(default_factory=list)


@dataclass
class GenerationSession:
    """In-memory truth for one job. The model never sees anything below."""

    brief: DesignBrief
    use: str
    floors: int
    area_sqft: float
    kind: str = ""
    program: BuildingProgram | None = None
    layouts: dict[str, FloorLayout] = field(default_factory=dict)
    overrides: dict[str, FloorLayout] = field(default_factory=dict)
    llm_calls: int = 0
    deadline: float = 0.0

    def remaining(self) -> float:
        return self.deadline - time.monotonic()


def _noop(**_: Any) -> None:
    return None


def _provider() -> str:
    return get_settings().generation_provider.strip().lower()


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


DEMO_STEPS = (
    ("analyzing", "Reading your design brief"),
    ("planning", "Arranging the two-storey demo layout"),
    ("working", "Connecting walls and openings"),
    ("working", "Preparing materials and fixtures"),
    ("validating", "Validating editable geometry"),
)


def _demo(report: Reporter) -> GenerationResult:
    from plancheck.mocks.generation import demo_home, demo_rules

    log.info("generation.agent=demo path=fixed-house (no LLM)")
    for index, (phase, message) in enumerate(DEMO_STEPS):
        log.info("generation.demo step=%d/%d phase=%s %s", index + 1, len(DEMO_STEPS), phase, message)
        report(phase=phase, progress=0.1 + index * 0.16, message=message)
        time.sleep(0.32)
    building = demo_home()
    log.info(
        "generation.demo done floors=%d rooms=%d walls=%d openings=%d",
        len(building.floors),
        len(building.rooms),
        len(building.walls),
        len(building.openings),
    )
    return GenerationResult(building=building, rules=demo_rules())


def _parse_payload(payload: dict[str, Any]) -> tuple[BuildingProgram | None, dict[str, FloorLayout]]:
    """Validate whatever the model returned. Raises ValueError with a fixable message."""
    if not isinstance(payload, dict):
        raise ValueError("The model reply was not a JSON object")
    raw_program = payload.get("program")
    if raw_program is None and {"storeys", "spaces"} <= set(payload):
        raw_program = payload  # tolerate a bare program object
    program = BuildingProgram.model_validate(raw_program) if raw_program is not None else None

    layouts: dict[str, FloorLayout] = {}
    raw_layouts = payload.get("layouts")
    if isinstance(raw_layouts, dict):
        for floor_id, raw in raw_layouts.items():
            if not isinstance(raw, dict):
                continue
            layouts[str(floor_id)] = FloorLayout.model_validate({"floor_id": floor_id, **raw})
    elif isinstance(raw_layouts, list):
        for raw in raw_layouts:
            if isinstance(raw, dict) and raw.get("floor_id"):
                layouts[str(raw["floor_id"])] = FloorLayout.model_validate(raw)
    if program is None and not layouts:
        raise ValueError('The reply contained no "program" object. Return JSON of the form {"program": {...}}.')
    return program, layouts


def _readable(exc: Exception) -> list[str]:
    """Turn a validation failure into something the model can act on."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            return [
                f"{'.'.join(str(p) for p in item.get('loc', ()))}: {item.get('msg', '')}".strip(": ")
                for item in errors()[:6]
            ]
        except (TypeError, ValueError):
            pass
    return [str(exc)]


def _run_pipeline(session: GenerationSession, report: Reporter) -> tuple[Building, list[dict]]:
    """Pack, compile, check, repair. Every stage runs once."""
    program = session.program
    if program is None:
        raise LayoutError("No program is available to pack")

    log.info("generation.host stage=pack use=%s\n%s", program.building_use, program.summary())
    report(phase="working", progress=0.55, message="Arranging rooms on every floor")
    layouts = pack_floors(program, session.area_sqft)
    for floor_id, layout in session.overrides.items():
        if floor_id in layouts:
            log.info("generation.host stage=pack override floor=%s", floor_id)
            layouts[floor_id] = layout
    session.layouts = layouts
    for layout in layouts.values():
        log.info("generation.host stage=pack layout %s", layout.summary())

    log.info("generation.host stage=compile")
    report(phase="working", progress=0.7, message="Building walls, doors and windows")
    building = compile_building(program, layouts)
    log.info(
        "generation.host stage=compile done floors=%d rooms=%d walls=%d openings=%d objects=%d review=%d",
        len(building.floors),
        len(building.rooms),
        len(building.walls),
        len(building.openings),
        len(building.objects),
        len(building.review),
    )

    report(phase="validating", progress=0.85, message="Measuring against your requirements")
    categories = {space.category for space in program.spaces}
    rules = defaults.rule_pack(program.building_use, categories)
    log.info("generation.host stage=check rules=%d categories=%s", len(rules), sorted(categories))

    results = check_building(building, rules)
    failures = [c for c in results if c["status"] == "fail"]
    log.info(
        "generation.host stage=check pass=%d fail=%d other=%d",
        sum(1 for c in results if c["status"] == "pass"),
        len(failures),
        sum(1 for c in results if c["status"] not in {"pass", "fail"}),
    )
    for failure in failures[:8]:
        log.info("generation.host check.fail %s", failure.get("message", failure))

    if failures:
        try:
            proposal = propose_repairs(building, rules)
            log.info(
                "generation.host stage=repair proposed=%s blocked=%s",
                proposal.get("summary", {}).get("proposed"),
                proposal.get("summary", {}).get("blocked"),
            )
            if proposal["commands"]:
                building = apply_commands(building, proposal["commands"], actor="agent")
                log.info("generation.host stage=repair applied=%d", len(proposal["commands"]))
        except (CommandError, ValueError, KeyError) as exc:
            log.warning("generation.host stage=repair skipped error=%s", exc)
    return building, rules


def _ask(session: GenerationSession, errors: list[str]) -> dict[str, Any]:
    messages = prompts.build_messages(
        session.brief,
        session.use,
        session.floors,
        session.area_sqft,
        errors=errors,
        program=session.program.model_dump(mode="json") if session.program else None,
        layouts=[layout.summary() for layout in session.layouts.values()],
        kind=session.kind,
    )
    session.llm_calls += 1
    log.info(
        "generation.agent=generation call=%d/%d remaining=%.1fs retry=%s",
        session.llm_calls,
        MAX_LLM_CALLS,
        session.remaining(),
        bool(errors),
    )
    if errors:
        log.info("generation.agent=generation feeding_errors=%s", errors)
    return complete_json(GENERATION, messages, timeout=session.remaining())


def generate_from_brief(brief: DesignBrief, report: Reporter | None = None) -> GenerationResult:
    """Brief in, validated Building out. Raises GenerationError instead of guessing."""
    report = report or _noop
    settings = get_settings()
    provider = _provider()
    started = time.monotonic()

    log.info(
        "generation.start provider=%s name=%r use=%r floors=%r area=%r prompt_chars=%d",
        provider,
        brief.name,
        brief.building_use,
        brief.floors,
        brief.area,
        len(brief.prompt or ""),
    )
    if brief.prompt:
        log.info("generation.brief.prompt\n%s", brief.prompt)

    if provider in DEMO_PROVIDERS:
        result = _demo(report)
        log.info("generation.done path=demo elapsed=%.1fs", time.monotonic() - started)
        return result
    if provider not in LIVE_PROVIDERS:
        raise GenerationError(
            f"Unknown PLANCHECK_GENERATION_PROVIDER {provider!r}. "
            f"Use 'demo' or one of {', '.join(sorted(LIVE_PROVIDERS))}."
        )
    if not settings.resolved_api_key():
        raise GenerationError(
            "Generation is set to the live model but no API key is configured. "
            "Add BASETEN_API_KEY to .env, or set PLANCHECK_GENERATION_PROVIDER=demo."
        )

    use = defaults.normalise_use(brief.building_use, brief.name, brief.prompt, brief.rooms)
    kind = defaults.detect_kind(brief.building_use, brief.name, brief.prompt, brief.rooms)
    active = defaults.profile(use)
    session = GenerationSession(
        brief=brief,
        use=use,
        floors=defaults.parse_floor_count(
            brief.floors, brief.prompt, brief.rooms, brief.name, default=active.default_floors
        ),
        area_sqft=defaults.parse_area_sqft(
            brief.area, brief.prompt, brief.rooms, default=active.default_area_sqft
        ),
        deadline=time.monotonic() + DEADLINE_S,
        kind=kind,
    )
    log.info(
        "generation.interpreted kind=%s packer=%s storeys=%d area_sqft=%.0f model=%s deadline_s=%.0f",
        kind,
        session.use,
        session.floors,
        session.area_sqft,
        settings.generation_slug(),
        DEADLINE_S,
    )

    report(phase="analyzing", progress=0.08, message="Reading your design brief")
    errors: list[str] = []
    history: list[str] = []
    seen: set[str] = set()

    for attempt in range(MAX_LLM_CALLS):
        if session.remaining() <= 0:
            log.warning("generation.deadline exceeded before attempt=%d", attempt + 1)
            break
        report(
            phase="planning",
            progress=0.2 if attempt == 0 else 0.45,
            message="Planning the spaces and how they connect"
            if attempt == 0
            else "Revising the plan after the first attempt",
        )
        log.info("generation.loop attempt=%d/%d", attempt + 1, MAX_LLM_CALLS)
        try:
            payload = _ask(session, errors)
        except LLMError as exc:
            errors = [f"The previous reply could not be read: {exc}"]
            history.extend(errors)
            log.warning("generation.llm_error %s", exc)
            continue

        digest = _digest(payload)
        if digest in seen:
            log.error("generation.duplicate_plan digest=%s", digest[:12])
            raise GenerationError(
                "The model returned the same plan again after it failed to build. "
                "Try a more specific brief."
            )
        seen.add(digest)

        try:
            program, layouts = _parse_payload(payload)
        except ValueError as exc:
            errors = _readable(exc)
            history.extend(errors)
            log.warning("generation.parse_failed %s", errors)
            continue

        if program is not None:
            session.program = program
            session.overrides = {}
            log.info("generation.program accepted\n%s", program.summary())
        if layouts:
            session.overrides.update(layouts)
            log.info("generation.layouts accepted floors=%s", sorted(layouts))
        if session.program is None:
            errors = ['The reply contained no "program" object']
            history.extend(errors)
            log.warning("generation.missing_program")
            continue

        try:
            building, rules = _run_pipeline(session, report)
        except (LayoutError, CompileError, CommandError, ValueError) as exc:
            errors = [str(exc)]
            history.extend(errors)
            log.warning("generation.pipeline_failed %s", exc)
            continue

        log.info(
            "generation.done path=agent llm_calls=%d elapsed=%.1fs recovered=%d notes=%r",
            session.llm_calls,
            time.monotonic() - started,
            len(history),
            session.program.notes,
        )
        return GenerationResult(
            building=building,
            rules=rules,
            program=session.program.model_dump(mode="json"),
            layouts={fid: layout.model_dump(mode="json") for fid, layout in session.layouts.items()},
            llm_calls=session.llm_calls,
            notes=session.program.notes,
            recovered_from=history,
        )

    detail = errors[0] if errors else "the model did not answer in time"
    log.error(
        "generation.failed after=%.1fs detail=%s history=%s",
        time.monotonic() - started,
        detail,
        history,
    )
    raise GenerationError(f"The design could not be generated: {detail}")
