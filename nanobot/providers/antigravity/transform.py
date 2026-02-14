"""OpenAI <-> Gemini format transformation for Antigravity provider."""

from __future__ import annotations

import json
import uuid
from typing import Any

from nanobot.providers.antigravity.constants import (
    COMPOSITION_SCHEMA_KEYS,
    REJECTED_SCHEMA_KEYS,
)
from nanobot.providers.base import ToolCallDelta, ToolCallRequest


def messages_to_gemini(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Convert OpenAI-format messages to Gemini contents + systemInstruction.

    Returns:
        (contents, system_instruction) — system_instruction is None if no
        system messages are present.
    """
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []

    for msg in messages:
        role = msg["role"]
        content = msg.get("content")

        # ── System messages ────────────────────────────────────────────
        if role == "system":
            if content:
                system_parts.append({"text": content})
            continue

        # ── Map role ───────────────────────────────────────────────────
        gemini_role = "model" if role == "assistant" else "user"
        parts: list[dict[str, Any]] = []

        # ── Assistant with tool calls ──────────────────────────────────
        if role == "assistant" and msg.get("tool_calls"):
            if content:
                parts.append({"text": content})
            for tc in msg["tool_calls"]:
                args = tc["function"]["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                tc_id = tc.get("id", f"tc_{uuid.uuid4().hex[:12]}")
                parts.append(
                    {
                        "functionCall": {
                            "id": tc_id,
                            "name": tc["function"]["name"],
                            "args": args,
                        }
                    }
                )

        # ── Tool result ────────────────────────────────────────────────
        elif role == "tool":
            name = msg.get("name", msg.get("tool_call_id", ""))
            tc_id = msg.get("tool_call_id", f"tc_{uuid.uuid4().hex[:12]}")
            parts.append(
                {
                    "functionResponse": {
                        "id": tc_id,
                        "name": name,
                        "response": {"result": content or ""},
                    }
                }
            )

        # ── Regular content (string or multimodal list) ────────────────
        elif content:
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append({"text": item["text"]})
                    elif isinstance(item, str):
                        parts.append({"text": item})
            else:
                parts.append({"text": content})

        if parts:
            contents.append({"role": gemini_role, "parts": parts})

    # ── Merge consecutive same-role messages ───────────────────────────
    # Gemini rejects two consecutive messages with the same role.
    # IMPORTANT: functionResponse parts must NOT be merged with text
    # parts in the same user turn — Claude models reject mixed content.
    merged: list[dict[str, Any]] = []
    for entry in contents:
        if merged and merged[-1]["role"] == entry["role"]:
            prev_has_fr = any("functionResponse" in p for p in merged[-1]["parts"])
            curr_has_fr = any("functionResponse" in p for p in entry["parts"])
            if prev_has_fr != curr_has_fr:
                # Different part types — insert model placeholder to maintain
                # role alternation without mixing function and text parts.
                merged.append({"role": "model", "parts": [{"text": "OK."}]})
                merged.append(entry)
            else:
                merged[-1]["parts"].extend(entry["parts"])
        else:
            merged.append(entry)

    system_instruction = {"role": "user", "parts": system_parts} if system_parts else None
    return merged, system_instruction


def tools_to_gemini(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Convert OpenAI tools format to Gemini functionDeclarations.

    OpenAI:  [{"type": "function", "function": {"name": ..., ...}}]
    Gemini:  [{"functionDeclarations": [{"name": ..., ...}]}]
    """
    if not tools:
        return None

    declarations: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") != "function":
            continue
        func = tool["function"]
        decl: dict[str, Any] = {
            "name": func["name"],
            "description": func.get("description", ""),
        }
        if "parameters" in func:
            decl["parameters"] = sanitize_schema(func["parameters"])
        declarations.append(decl)

    if not declarations:
        return None

    return [{"functionDeclarations": declarations}]


def sanitize_schema(schema: Any) -> Any:
    """Recursively strip JSON Schema keys rejected by Gemini API.

    Handles:
    - Removes: const, $ref, $defs, default, examples, title
    - Converts ``const`` to ``enum: [value]``
    - Flattens single-item ``anyOf`` / ``oneOf`` (unwraps the inner schema)
    - Merges ``allOf`` items into one schema
    - Multi-item ``anyOf`` / ``oneOf``: takes the first branch (lossy but functional)
    """
    if not isinstance(schema, dict):
        return schema

    # ── Handle composition keywords first ──────────────────────────────
    # Process them before the main loop so the result replaces the
    # original schema dict entirely when appropriate.
    schema = _resolve_composition(schema)

    result: dict[str, Any] = {}
    for key, value in schema.items():
        if key in REJECTED_SCHEMA_KEYS:
            if key == "const":
                result["enum"] = [value]
            continue

        # Skip composition keys — already resolved above
        if key in COMPOSITION_SCHEMA_KEYS:
            continue

        if isinstance(value, dict):
            result[key] = sanitize_schema(value)
        elif isinstance(value, list):
            result[key] = [
                sanitize_schema(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            result[key] = value

    return result


def _resolve_composition(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve anyOf/oneOf/allOf into a flat schema Gemini can accept."""

    # ── allOf: merge all sub-schemas ───────────────────────────────────
    if "allOf" in schema:
        items = schema["allOf"]
        if isinstance(items, list) and items:
            merged = {k: v for k, v in schema.items() if k != "allOf"}
            for sub in items:
                if isinstance(sub, dict):
                    for k, v in sub.items():
                        if k == "properties" and k in merged:
                            merged[k] = {**merged[k], **v}
                        elif k == "required" and k in merged:
                            merged[k] = list(dict.fromkeys(merged[k] + v))
                        else:
                            merged[k] = v
            return merged

    # ── anyOf / oneOf: unwrap single-item, else take first branch ──────
    for key in ("anyOf", "oneOf"):
        if key in schema:
            items = schema[key]
            if isinstance(items, list) and items:
                # Filter out null-type entries for "optional" patterns
                non_null = [s for s in items if isinstance(s, dict) and s.get("type") != "null"]
                chosen = non_null[0] if non_null else items[0]
                if isinstance(chosen, dict):
                    # Preserve any sibling keys (description, etc.)
                    base = {k: v for k, v in schema.items() if k not in COMPOSITION_SCHEMA_KEYS}
                    base.update(chosen)
                    return base

    return schema


def _unwrap_response(data: dict[str, Any]) -> dict[str, Any]:
    """Unwrap Antigravity v1internal response envelope.

    The API wraps responses as::

        { "response": { candidates, usageMetadata, ... }, "traceId": "...", "metadata": {} }

    This helper returns the inner ``response`` dict, or the original dict if
    it already contains ``candidates`` directly.
    """
    if "response" in data and isinstance(data["response"], dict):
        return data["response"]
    return data


def parse_gemini_response(
    response_json: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    """Parse Gemini API response into components for LLMResponse.

    Returns dict with: content, tool_calls, finish_reason, usage,
    reasoning_content.
    """
    response_json = _unwrap_response(response_json)
    candidates = response_json.get("candidates", [])
    if not candidates:
        return {
            "content": None,
            "tool_calls": [],
            "finish_reason": "error",
            "usage": {},
            "reasoning_content": None,
        }

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    finish_reason = _map_finish_reason(candidate.get("finishReason", "STOP"))

    content_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    reasoning_content: str | None = None

    for part in parts:
        if "text" in part:
            if part.get("thought"):
                reasoning_content = part["text"]
            else:
                content_parts.append(part["text"])
        elif "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append(
                ToolCallRequest(
                    id=f"ag_{uuid.uuid4().hex[:12]}",
                    name=fc["name"],
                    arguments=fc.get("args", {}),
                )
            )

    content = "\n".join(content_parts) if content_parts else None

    # Parse usage
    usage: dict[str, int] = {}
    usage_meta = response_json.get("usageMetadata", {})
    if usage_meta:
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount", 0),
            "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
            "total_tokens": usage_meta.get("totalTokenCount", 0),
        }

    return {
        "content": content,
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
        "usage": usage,
        "reasoning_content": reasoning_content,
    }


def _map_finish_reason(gemini_reason: str) -> str:
    """Map Gemini finish reason to OpenAI-compatible string."""
    mapping = {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
        "FINISH_REASON_UNSPECIFIED": "stop",
    }
    return mapping.get(gemini_reason, "stop")


def parse_sse_chunk(
    event_data: dict[str, Any],
) -> dict[str, Any]:
    """Parse a single SSE event (Gemini streaming response) into stream chunk components.

    Returns dict with: content_delta, tool_calls_delta, reasoning_delta,
    finish_reason, usage.
    """
    event_data = _unwrap_response(event_data)
    candidates = event_data.get("candidates", [])
    content_delta: str | None = None
    tool_calls_delta: list[ToolCallDelta] = []
    reasoning_delta: str | None = None
    finish_reason: str | None = None

    if candidates:
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])

        for part in parts:
            if "text" in part:
                if part.get("thought"):
                    reasoning_delta = part["text"]
                else:
                    content_delta = part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls_delta.append(
                    ToolCallDelta(
                        id=f"ag_{uuid.uuid4().hex[:12]}",
                        name=fc.get("name"),
                        arguments_json=json.dumps(fc.get("args", {})),
                    )
                )

        raw_reason = candidate.get("finishReason")
        if raw_reason:
            finish_reason = _map_finish_reason(raw_reason)

    # Parse usage from final chunk
    usage: dict[str, int] = {}
    usage_meta = event_data.get("usageMetadata", {})
    if usage_meta:
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount", 0),
            "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
            "total_tokens": usage_meta.get("totalTokenCount", 0),
        }

    return {
        "content_delta": content_delta,
        "tool_calls_delta": tool_calls_delta,
        "reasoning_delta": reasoning_delta,
        "finish_reason": finish_reason,
        "usage": usage,
    }
