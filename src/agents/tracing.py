"""Record privacy-filtered workflow, model, and tool execution traces."""

from __future__ import annotations

import re
from threading import Lock
import time
from typing import Any
from uuid import uuid4

from .state import AgentTrace, ExtractionResult, ModelUsage, utc_now

_SECRET = re.compile(r"(api[_-]?key|token|password|secret)\s*[:=]\s*[^,\s}]+", re.I)
_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|access[_-]?token|password|secret|authorization)", re.I)
_CONTENT_KEYS = {"text", "content", "source_content", "document_text", "raw_document"}


def safe_summary(value: Any) -> Any:
    """Redact secrets and omit large document-content fields from trace values.

    Args:
        value: Nested scalar, dictionary, or list to summarize.

    Returns:
        Sanitized structure: strings are redacted/truncated to 500 characters,
        dictionaries omit sensitive/content keys and retain at most 30 items,
        and lists retain at most 20 entries.
    """
    if isinstance(value, str):
        text = _SECRET.sub(r"\\1=[REDACTED]", value)
        return text[:500]
    if isinstance(value, dict):
        return {
            str(key): safe_summary(item)
            for key, item in list(value.items())[:30]
            if key.lower() not in _CONTENT_KEYS and not _SENSITIVE_KEY.search(key)
        }
    if isinstance(value, list):
        return [safe_summary(item) for item in value[:20]]
    return value


class TraceRecorder:
    """Append thread-safe workflow, model, and tool events to an ``AgentTrace``."""

    def __init__(self, trace_id: str | None = None, run_id: str | None = None):
        """Create a trace recorder with supplied or generated trace identity."""
        self.trace = AgentTrace(trace_id=trace_id or str(uuid4()), run_id=run_id)
        self._lock = Lock()

    def event(self, node: str, event: str, *, status: str = "ok", input_value: Any = None, output_value: Any = None, error: str | None = None, latency_ms: float | None = None, token_usage: Any = None, retry_count: int = 0) -> None:
        """Append a node event with sanitized input/output summaries."""
        event_data = {
            "timestamp": utc_now(),
            "node": node,
            "event": event,
            "status": status,
            "input_summary": safe_summary(input_value),
            "output_summary": safe_summary(output_value),
            "error": safe_summary(error),
            "latency_ms": latency_ms,
            "token_usage": token_usage if token_usage is not None else "unavailable",
            "retry_count": retry_count,
        }
        with self._lock:
            self.trace.events.append(event_data)

    def model_call(self, node: str, usage: ModelUsage, *, duration_ms: float, status: str = "succeeded") -> None:
        """Append a model-call event with provider usage and elapsed time."""
        with self._lock:
            self.trace.events.append({
                "timestamp": utc_now(),
                "event_type": "model_call",
                "node": node,
                "run_id": self.trace.run_id,
                "call_id": str(uuid4()),
                "status": status,
                "duration_ms": duration_ms,
                "usage": safe_summary(usage.model_dump(mode="python")),
            })

    def tool_call(
        self,
        tool_name: str,
        *,
        input_value: Any = None,
        output_value: Any = None,
        duration_ms: float,
        status: str = "succeeded",
        error: str | None = None,
    ) -> None:
        """Append a tool-call event with sanitized inputs, outputs, and status."""
        with self._lock:
            self.trace.events.append({
                "timestamp": utc_now(),
                "event_type": "tool_call",
                "node": tool_name,
                "run_id": self.trace.run_id,
                "tool_call_id": str(uuid4()),
                "tool_name": tool_name,
                "status": status,
                "input_summary": safe_summary(input_value),
                "output_summary": safe_summary(output_value),
                "error_summary": error,
                "duration_ms": duration_ms,
            })

    def run_tool(self, tool_name: str, input_value: Any, operation, *, output_summary=None):
        """Run an operation and trace success/failure timing and summaries.

        Args:
            tool_name: Tool identifier included in trace event.
            input_value: Sanitized input summary to record.
            operation: Zero-argument callable to execute.
            output_summary: Optional callable reducing the raw result for trace.

        Returns:
            Raw operation result; exceptions are traced and re-raised.
        """
        started = time.perf_counter()
        try:
            result = operation()
        except Exception as exc:
            self.tool_call(
                tool_name,
                input_value=input_value,
                duration_ms=(time.perf_counter() - started) * 1000,
                status="failed",
                error=type(exc).__name__,
            )
            raise
        summary = output_summary(result) if output_summary else result
        self.tool_call(
            tool_name,
            input_value=input_value,
            output_value=summary,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return result

    def run_model(self, node: str, operation, *, provider: str | None = None, model: str | None = None):
        """Run a model operation and record usage, provider identity, and timing."""
        started = time.perf_counter()
        try:
            result = operation()
        except Exception:
            self.model_call(
                node,
                ModelUsage(provider=provider, model=model),
                duration_ms=(time.perf_counter() - started) * 1000,
                status="failed",
            )
            raise
        usage = result.usage if isinstance(result, ExtractionResult) else ModelUsage()
        self.model_call(node, usage, duration_ms=(time.perf_counter() - started) * 1000)
        return result

    def run(self, node: str, input_value: Any, operation, *, retry_count: int = 0):
        """Run a workflow node operation and append start/end events."""
        started = time.perf_counter()
        self.event(node, "start", input_value=input_value, retry_count=retry_count)
        try:
            result = operation()
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000
            self.event(node, "end", status="failed", error=str(exc), latency_ms=latency, retry_count=retry_count)
            raise
        latency = (time.perf_counter() - started) * 1000
        self.event(node, "end", output_value=result, latency_ms=latency, retry_count=retry_count)
        return result
