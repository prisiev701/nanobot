"""Data models for metrics events."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


@dataclass
class ToolEvent:
    """A single tool invocation record."""

    ts: str
    session_id: str
    tool_name: str
    tool_success: bool
    latency_ms: int
    input_size: int  # len(json.dumps(params))
    output_size: int  # len(result)
    error: str | None = None
    iteration: int = 0  # which loop iteration this tool call belongs to

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMEvent:
    """A single LLM API call record."""

    ts: str
    session_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    has_tool_calls: bool
    num_tool_calls: int
    latency_ms: int
    iteration: int
    finish_reason: str = "stop"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionSummary:
    """End-of-session aggregate record."""

    session_id: str
    started_at: str
    ended_at: str
    duration_ms: int
    success: bool
    total_iterations: int
    total_tool_calls: int
    total_llm_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    tools_used: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    task_type: str | None = None  # future: auto-classify
    channel: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
