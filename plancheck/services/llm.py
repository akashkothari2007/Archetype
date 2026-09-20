"""Baseten Model APIs client. Orchestrator and subagent share one key, different slugs."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Literal

from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings

ORCHESTRATOR = "orchestrator"
SUBAGENT = "subagent"
GENERATION = "generation"

# Generation replies are a whole space program. Reasoning tokens count against
# this budget, so it has to be large enough for thinking plus the JSON.
_MAX_TOKENS = {ORCHESTRATOR: 1800, SUBAGENT: 3200, GENERATION: 16000}
_JSON_HINTS = ("program", "layouts", "spaces", "storeys", "intent", "commands")
_THINK_RE = re.compile(
    r"<think(ing)?>.*?</think(ing)?>|```(?:thinking|reason(?:ing)?)(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

log = get_logger("plancheck.llm")

JsonMode = Literal["schema", "object", "off"]


class LLMError(RuntimeError):
    pass


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in value
        )
    return str(value)


def _extract_parts(payload: dict[str, Any]) -> tuple[str, str, str]:
    """Return (content, reasoning, finish_reason). Content is never filled from reasoning."""
    choices = payload.get("choices") or []
    if not choices:
        raise LLMError("Baseten returned no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    content = _as_text(message.get("content")).strip()
    reasoning = _as_text(
        message.get("reasoning_content")
        or message.get("reasoning")
        or payload.get("reasoning")
    ).strip()
    finish_reason = str(choice.get("finish_reason") or payload.get("finish_reason") or "")
    if not content and not reasoning:
        raise LLMError("Baseten returned an empty reply")
    return content, reasoning, finish_reason


def _strip_wrappers(text: str) -> str:
    cleaned = _THINK_RE.sub(" ", text.strip())
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return cleaned


def _balanced_object(text: str, start: int) -> str | None:
    """Pull the `{...}` that starts at `start`, or None if it never closes."""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _iter_objects(text: str) -> list[str]:
    objects: list[str] = []
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            break
        matched = _balanced_object(text, start)
        if matched:
            objects.append(matched)
            index = start + len(matched)
        else:
            objects.append(text[start:])
            break
    return objects


def _repair_truncated(text: str) -> str | None:
    """Close a cut-off object so a nearly-complete program can still be read."""
    start = text.find("{")
    if start < 0:
        return None
    snippet = text[start:]
    if not any(f'"{hint}"' in snippet for hint in _JSON_HINTS):
        return None
    stack: list[str] = []
    in_string = False
    escape = False
    for char in snippet:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            if stack and stack[-1] == char:
                stack.pop()
    if in_string:
        snippet += '"'
    snippet = snippet.rstrip()
    if snippet.endswith(","):
        snippet = snippet[:-1]
    while stack:
        snippet += stack.pop()
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    return snippet if isinstance(data, dict) else None


def _load_dict(candidate: str) -> dict[str, Any] | None:
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _score(data: dict[str, Any]) -> int:
    keys = set(data)
    nested = data.get("program") if isinstance(data.get("program"), dict) else {}
    keys |= set(nested)
    return sum(40 for hint in _JSON_HINTS if hint in keys) + min(len(data), 8)


def parse_json(text: str) -> dict[str, Any]:
    """Read a JSON object out of a model reply, including messy or truncated ones."""
    cleaned = _strip_wrappers(text)
    candidates = _iter_objects(cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    repaired = _repair_truncated(cleaned)
    if repaired:
        candidates.append(repaired)
    candidates.append(cleaned)

    best: dict[str, Any] | None = None
    best_score = -1
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        data = _load_dict(candidate)
        if data is None:
            continue
        score = _score(data)
        if score > best_score:
            best, best_score = data, score
    if best is not None:
        return best
    raise LLMError("Model reply was not JSON")


def _response_format(role: str, mode: JsonMode) -> dict[str, Any] | None:
    if mode == "off":
        return None
    if mode == "schema" and role == GENERATION:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "building_program",
                "strict": False,
                "schema": {
                    "type": "object",
                    "properties": {
                        "program": {"type": "object"},
                        "layouts": {"type": "object"},
                    },
                    "additionalProperties": True,
                },
            },
        }
    return {"type": "json_object"}


def complete(
    role: str,
    messages: list[dict[str, str]],
    *,
    json_mode: bool = True,
    timeout: float = 60,
) -> str:
    content, _, _ = _chat(
        role, messages, mode="object" if json_mode else "off", timeout=timeout
    )
    return content


def _chat(
    role: str,
    messages: list[dict[str, str]],
    *,
    mode: JsonMode,
    timeout: float,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> tuple[str, str, str]:
    settings = get_settings()
    key = settings.resolved_api_key()
    if not key:
        raise LLMError("Baseten API key is missing")
    if role == GENERATION:
        model = settings.generation_slug()
    elif role == ORCHESTRATOR:
        model = settings.orchestrator_slug()
    else:
        model = settings.subagent_slug()

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens or _MAX_TOKENS.get(role, 900),
    }
    fmt = _response_format(role, mode)
    if fmt:
        body["response_format"] = fmt
    # GLM-5.3 defaults to high reasoning, which burns the token budget before JSON.
    effort = reasoning_effort or ("low" if role == GENERATION else None)
    if effort:
        body["reasoning_effort"] = effort

    log.info(
        "llm.request agent=%s model=%s timeout=%.1fs json_mode=%s messages=%d max_tokens=%d",
        role,
        model,
        timeout,
        mode,
        len(messages),
        body["max_tokens"],
    )
    for index, message in enumerate(messages):
        log.info(
            "llm.prompt agent=%s [%d/%d] role=%s\n%s",
            role,
            index + 1,
            len(messages),
            message.get("role"),
            message.get("content", ""),
        )

    request = urllib.request.Request(
        settings.agent_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, timeout)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        log.warning(
            "llm.http_error agent=%s status=%s after=%.1fs mode=%s",
            role,
            exc.code,
            time.monotonic() - started,
            mode,
        )
        if exc.code == 400 and mode == "schema":
            log.info("llm.retry agent=%s with json_object", role)
            return _chat(
                role,
                messages,
                mode="object",
                timeout=timeout,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
        if exc.code == 400 and mode == "object":
            log.info("llm.retry agent=%s without json_mode", role)
            return _chat(
                role,
                messages,
                mode="off",
                timeout=timeout,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
        raise LLMError(f"Baseten request failed (HTTP {exc.code})") from None
    except urllib.error.URLError as exc:
        log.error("llm.unreachable agent=%s error=%s", role, exc)
        raise LLMError("Could not reach Baseten") from None

    elapsed = time.monotonic() - started
    content, reasoning, finish_reason = _extract_parts(payload)
    usage = payload.get("usage") or {}
    log.info(
        "llm.response agent=%s model=%s elapsed=%.1fs chars=%d finish=%s tokens=%s",
        role,
        model,
        elapsed,
        len(content),
        finish_reason or "n/a",
        usage or "n/a",
    )
    if reasoning and reasoning != content:
        preview = reasoning if len(reasoning) <= 2000 else reasoning[:2000] + "\n…(truncated)"
        log.info("llm.reasoning agent=%s\n%s", role, preview)
    log.info("llm.reply agent=%s\n%s", role, content or "(empty content)")
    return content, reasoning, finish_reason


def complete_json(
    role: str,
    messages: list[dict[str, str]],
    *,
    timeout: float = 60,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    mode: JsonMode = "schema" if role == GENERATION else "object"
    content, reasoning, finish_reason = _chat(
        role,
        messages,
        mode=mode,
        timeout=timeout,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
    )
    sources = [content]
    if reasoning and reasoning != content:
        sources.append(reasoning)
        sources.append(f"{content}\n{reasoning}")
    last_exc: LLMError | None = None
    for source in sources:
        if not source or not source.strip():
            continue
        try:
            return parse_json(source)
        except LLMError as exc:
            last_exc = exc
            log.warning(
                "llm.json_parse_failed agent=%s chars=%d finish=%s",
                role,
                len(source),
                finish_reason or "n/a",
            )
    if finish_reason == "length":
        raise LLMError(
            "The JSON was cut off before it was complete. "
            "Return a smaller program: at most 8 spaces per storey, 40 spaces total."
        )
    raise last_exc or LLMError("Model reply was not JSON")
