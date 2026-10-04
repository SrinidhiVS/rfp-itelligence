"""Deliver local workflow traces to LangSmith on a best-effort basis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class LangSmithTraceSink:
    """Best-effort LangSmith-compatible run sink; local traces remain authoritative.

    Args:
        api_key: Optional LangSmith credential. Without one no remote client is
            initialized.
        project: LangSmith project name used when creating runs.
    """

    def __init__(self, api_key: str | None = None, project: str = "rfp-multi-agent-analysis"):
        """Initialize a remote client if credentials and dependencies are available."""
        self.api_key = api_key
        self.project = project
        self.client = None
        if api_key:
            try:
                from langsmith import Client
                self.client = Client(api_key=api_key)
            except Exception:
                self.client = None

    def record(self, trace: dict[str, Any]) -> str | None:
        """Create/update a LangSmith chain run from a local trace dictionary.

        Args:
            trace: Mapping with trace ID, optional run ID, and event list.

        Returns:
            Remote run ID as a string on success, or ``None`` when unavailable
            or when remote delivery fails.
        """
        if not self.client:
            return None
        try:
            run_id = trace.get("trace_id") or str(uuid4())
            run = self.client.create_run(
                id=run_id,
                name="rfp-analysis",
                run_type="chain",
                inputs={"trace_id": trace.get("trace_id"), "run_id": trace.get("run_id")},
                project_name=self.project,
            )
            self.client.update_run(
                run_id,
                outputs={
                    "trace_id": trace.get("trace_id"),
                    "run_id": trace.get("run_id"),
                    "events": trace.get("events", []),
                },
                end_time=datetime.now(timezone.utc),
            )
            return str(run_id)
        except Exception:
            return None
