"""JSONL-based metrics collector.

Writes structured events to append-only JSONL files under ~/.nanobot/metrics/.
Thread-safe for single-process async usage.  No external dependencies.
"""

import json
from pathlib import Path

from loguru import logger

from nanobot.metrics.models import ToolEvent, LLMEvent, SessionSummary
from nanobot.utils.helpers import ensure_dir


class MetricsCollector:
    """Append-only JSONL metrics writer.

    Files:
        tool_events.jsonl   — one line per tool invocation
        llm_events.jsonl    — one line per LLM API call
        sessions.jsonl      — one line per completed session
    """

    def __init__(self, metrics_dir: Path | None = None, *, enabled: bool = True):
        self.enabled = enabled
        if not enabled:
            self._dir = Path("/dev/null")  # never used
            return
        self._dir = ensure_dir(metrics_dir or Path.home() / ".nanobot" / "metrics")
        self._tool_path = self._dir / "tool_events.jsonl"
        self._llm_path = self._dir / "llm_events.jsonl"
        self._session_path = self._dir / "sessions.jsonl"

    # -- public API ----------------------------------------------------------

    def record_tool_event(self, event: ToolEvent) -> None:
        self._append(self._tool_path, event.to_dict())

    def record_llm_event(self, event: LLMEvent) -> None:
        self._append(self._llm_path, event.to_dict())

    def record_session(self, summary: SessionSummary) -> None:
        self._append(self._session_path, summary.to_dict())

    # -- reading (used by report.py) -----------------------------------------

    def read_tool_events(self, limit: int = 0) -> list[dict]:
        return self._read(self._tool_path, limit)

    def read_llm_events(self, limit: int = 0) -> list[dict]:
        return self._read(self._llm_path, limit)

    def read_sessions(self, limit: int = 0) -> list[dict]:
        return self._read(self._session_path, limit)

    @property
    def metrics_dir(self) -> Path:
        return self._dir

    # -- internals -----------------------------------------------------------

    def _append(self, path: Path, data: dict) -> None:
        if not self.enabled:
            return
        try:
            with open(path, "a") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Metrics write failed ({path.name}): {e}")

    @staticmethod
    def _read(path: Path, limit: int = 0) -> list[dict]:
        if not path.exists():
            return []
        lines: list[dict] = []
        try:
            with open(path) as f:
                for raw in f:
                    raw = raw.strip()
                    if raw:
                        lines.append(json.loads(raw))
        except Exception as e:
            logger.warning(f"Metrics read failed ({path.name}): {e}")
        if limit > 0:
            lines = lines[-limit:]
        return lines
