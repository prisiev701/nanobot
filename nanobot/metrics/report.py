"""Aggregation and reporting helpers for collected metrics.

All functions operate on plain dicts read from JSONL — no pandas needed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from nanobot.metrics.collector import MetricsCollector


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------


def _since(events: list[dict], hours: float) -> list[dict]:
    """Return events from the last *hours* hours."""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    return [e for e in events if e.get("ts", "") >= cutoff]


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------


def summary_report(collector: MetricsCollector, hours: float = 24) -> dict[str, Any]:
    """High-level summary over the last *hours* hours.

    Returns a dict with sections: overview, tokens, tools, model.
    """
    sessions = _since(collector.read_sessions(), hours)
    llm_events = _since(collector.read_llm_events(), hours)
    tool_events = _since(collector.read_tool_events(), hours)

    total_sessions = len(sessions)
    success_count = sum(1 for s in sessions if s.get("success"))
    success_rate = (success_count / total_sessions * 100) if total_sessions else 0.0

    total_prompt = sum(e.get("total_prompt_tokens", 0) for e in sessions)
    total_completion = sum(e.get("total_completion_tokens", 0) for e in sessions)
    total_tokens = sum(e.get("total_tokens", 0) for e in sessions)
    avg_tokens = (total_tokens // total_sessions) if total_sessions else 0
    tokens_per_success = (total_tokens // success_count) if success_count else 0

    total_tool_calls = len(tool_events)
    tool_success_count = sum(1 for t in tool_events if t.get("tool_success"))
    tool_success_rate = (tool_success_count / total_tool_calls * 100) if total_tool_calls else 0.0

    avg_iterations = 0.0
    if total_sessions:
        avg_iterations = sum(s.get("total_iterations", 0) for s in sessions) / total_sessions

    return {
        "period_hours": hours,
        "overview": {
            "total_sessions": total_sessions,
            "success_rate": round(success_rate, 1),
            "avg_iterations_per_session": round(avg_iterations, 1),
        },
        "tokens": {
            "total_prompt": total_prompt,
            "total_completion": total_completion,
            "total": total_tokens,
            "avg_per_session": avg_tokens,
            "per_success": tokens_per_success,
        },
        "tools": {
            "total_calls": total_tool_calls,
            "success_rate": round(tool_success_rate, 1),
        },
        "llm_calls": len(llm_events),
    }


# ---------------------------------------------------------------------------
# Per-tool breakdown
# ---------------------------------------------------------------------------


def tool_report(collector: MetricsCollector, hours: float = 24) -> list[dict[str, Any]]:
    """Per-tool success rate, avg latency, and call count."""
    events = _since(collector.read_tool_events(), hours)
    by_tool: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_tool[e.get("tool_name", "?")].append(e)

    rows: list[dict[str, Any]] = []
    for name, evts in sorted(by_tool.items(), key=lambda kv: -len(kv[1])):
        total = len(evts)
        ok = sum(1 for e in evts if e.get("tool_success"))
        avg_lat = sum(e.get("latency_ms", 0) for e in evts) // max(total, 1)
        avg_in = sum(e.get("input_size", 0) for e in evts) // max(total, 1)
        avg_out = sum(e.get("output_size", 0) for e in evts) // max(total, 1)

        # Collect unique errors
        errors = Counter(e.get("error", "")[:120] for e in evts if e.get("error"))

        rows.append(
            {
                "tool": name,
                "calls": total,
                "success_rate": round(ok / total * 100, 1) if total else 0.0,
                "avg_latency_ms": avg_lat,
                "avg_input_size": avg_in,
                "avg_output_size": avg_out,
                "top_errors": dict(errors.most_common(3)),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Per-session breakdown
# ---------------------------------------------------------------------------


def session_report(collector: MetricsCollector, last_n: int = 20) -> list[dict[str, Any]]:
    """Recent session summaries, newest first."""
    sessions = collector.read_sessions(limit=last_n)
    rows: list[dict[str, Any]] = []
    for s in reversed(sessions):  # newest first
        rows.append(
            {
                "session_id": s.get("session_id", "?"),
                "started_at": s.get("started_at", "?"),
                "success": s.get("success", False),
                "iterations": s.get("total_iterations", 0),
                "tool_calls": s.get("total_tool_calls", 0),
                "total_tokens": s.get("total_tokens", 0),
                "duration_ms": s.get("duration_ms", 0),
                "model": s.get("model", "?"),
                "tools_used": s.get("tools_used", []),
                "failure_reason": s.get("failure_reason"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Model comparison (useful when experimenting with different models)
# ---------------------------------------------------------------------------


def model_report(collector: MetricsCollector, hours: float = 168) -> list[dict[str, Any]]:
    """Per-model token efficiency and success rate (default: last 7 days)."""
    sessions = _since(collector.read_sessions(), hours)
    by_model: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        by_model[s.get("model", "?")].append(s)

    rows: list[dict[str, Any]] = []
    for model, ss in sorted(by_model.items()):
        total = len(ss)
        ok = sum(1 for s in ss if s.get("success"))
        tokens = sum(s.get("total_tokens", 0) for s in ss)
        rows.append(
            {
                "model": model,
                "sessions": total,
                "success_rate": round(ok / total * 100, 1) if total else 0.0,
                "total_tokens": tokens,
                "tokens_per_session": tokens // max(total, 1),
                "tokens_per_success": tokens // max(ok, 1),
            }
        )
    return rows
