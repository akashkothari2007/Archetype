"""Baseten Model APIs client. Orchestrator and subagent share one key, different slugs."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from plancheck.core.logutil import get_logger
from plancheck.core.settings import get_settings

ORCHESTRATOR = "orchestrator"
SUBAGENT = "subagent"
GENERATION = "generation"

# A whole space program is a larger reply than a chat turn or a bounded edit.
_MAX_TOKENS = {ORCHESTRATOR: 1800, SUBAGENT: 900, GENERATION: 4000}

log = get_logger("plancheck.llm")


class LLMError(RuntimeError):
    pass


def _extract_parts(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (content, reasoning). Reasoning is empty when the model omits it."""
    choices = payload.get("choices") or []
    if not choices:
        raise LLMError("Baseten returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    reasoning = message.get("reasoning_content") or payload.get("reasoning") or ""
    if isinstance(reasoning, list):
        reasoning = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in reasoning
        )
    if not content:
        content = reasoning
    if not isinstance(content, str) or not content.strip():
        raise LLMError("Baseten returned an empty reply")
    return content.strip(), str(reasoning).strip() if reasoning else ""


def _extract_text(payload: dict[str, Any]) -> str:
    return _extract_parts(payload)[0]


def _balanced_object(text: str) -> str | None:
    """Pull the first top-level `{...}` even when the model wrapped it in prose."""
    start = text.find("{")
    if start < 0:
        return None
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


def parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    # Prefer a brace-balanced object over naive first/last brace slicing, which
    # breaks when the model dumps chain-of-thought around the JSON.
    candidates = []
    balanced = _balanced_object(cleaned)
    if balanced:
        candidates.append(balanced)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    candidates.append(cleaned)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise LLMError("Model reply was not JSON")


def complete(
    role: str,
    messages: list[dict[str, str]],
    *,
    json_mode: bool = True,
    timeout: float = 60,
) -> str:
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
        "max_tokens": _MAX_TOKENS.get(role, 900),
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    log.info(
        "llm.request agent=%s model=%s timeout=%.1fs json_mode=%s messages=%d max_tokens=%d",
        role,
        model,
        timeout,
        json_mode,
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
            "llm.http_error agent=%s status=%s after=%.1fs",
            role,
            exc.code,
            time.monotonic() - started,
        )
        if json_mode and exc.code == 400:
            log.info("llm.retry agent=%s without json_mode", role)
            return complete(role, messages, json_mode=False, timeout=timeout)
        raise LLMError(f"Baseten request failed (HTTP {exc.code})") from None
    except urllib.error.URLError as exc:
        log.error("llm.unreachable agent=%s error=%s", role, exc)
        raise LLMError("Could not reach Baseten") from None

    elapsed = time.monotonic() - started
    content, reasoning = _extract_parts(payload)
    usage = payload.get("usage") or {}
    log.info(
        "llm.response agent=%s model=%s elapsed=%.1fs chars=%d tokens=%s",
        role,
        model,
        elapsed,
        len(content),
        usage or "n/a",
    )
    if reasoning and reasoning != content:
        # Cap reasoning noise in compose logs — the reply is what we parse.
        preview = reasoning if len(reasoning) <= 2000 else reasoning[:2000] + "\n…(truncated)"
        log.info("llm.reasoning agent=%s\n%s", role, preview)
    log.info("llm.reply agent=%s\n%s", role, content)
    return content


def complete_json(
    role: str, messages: list[dict[str, str]], *, timeout: float = 60
) -> dict[str, Any]:
    text = complete(role, messages, timeout=timeout)
    try:
        return parse_json(text)
    except LLMError:
        # Some reasoning models put the JSON only in the trailing slice; one more
        # pass over the raw text is enough when the first extract was prose-heavy.
        log.warning("llm.json_parse_failed agent=%s chars=%d; retrying extract", role, len(text))
        raise
