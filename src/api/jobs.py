"""Manage bounded asynchronous extraction jobs and polling response states."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable
from uuid import uuid4


TERMINAL_STATUSES = {"completed", "partial", "review_required", "failed"}


class ExtractionJobCapacityError(RuntimeError):
    """Raised when the manager has reached its retained-job capacity."""

    pass


@dataclass
class _ExtractionJob:
    """Hold mutable lifecycle state and serialized result for one job."""

    job_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None


class ExtractionJobManager:
    """Run extraction callables in a bounded thread pool and retain statuses.

    Args:
        max_workers: Concurrent worker count; must be at least one.
        max_jobs: Maximum queued/running/retained jobs; must be at least workers.
        retention: Duration to keep terminal jobs before pruning.
    """

    def __init__(
        self,
        *,
        max_workers: int = 2,
        max_jobs: int = 64,
        retention: timedelta = timedelta(hours=1),
    ) -> None:
        """Initialize worker pool and validate configured capacity limits."""
        if max_workers < 1 or max_jobs < max_workers:
            raise ValueError("job limits must allow at least one worker")
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="extraction-job")
        self._max_jobs = max_jobs
        self._retention = retention
        self._jobs: dict[str, _ExtractionJob] = {}
        self._lock = RLock()

    def submit(self, operation: Callable[[], Any]) -> dict[str, Any]:
        """Queue an operation and return its initial queued job envelope.

        Args:
            operation: Zero-argument callable producing a dictionary or
                Pydantic response with a JSON-mode model dump.

        Returns:
            Job mapping containing ID, status, ISO timestamps, and null result
            and error fields.

        Raises:
            ExtractionJobCapacityError: If retained job capacity is full.
        """
        now = datetime.now(timezone.utc)
        job_id = uuid4().hex
        job = _ExtractionJob(job_id, "queued", now, now)
        with self._lock:
            self._prune(now)
            if len(self._jobs) >= self._max_jobs:
                raise ExtractionJobCapacityError("extraction job capacity is full")
            self._jobs[job_id] = job
            try:
                self._executor.submit(self._run, job_id, operation)
            except Exception:
                self._jobs.pop(job_id, None)
                raise
            return self._serialize(job)

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return a serialized job state, pruning expired terminal jobs first."""
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune(now)
            job = self._jobs.get(job_id)
            return self._serialize(job) if job is not None else None

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop workers and cancel queued futures when possible."""
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _run(self, job_id: str, operation: Callable[[], Any]) -> None:
        """Execute one job and publish completed result or generic failure."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.updated_at = datetime.now(timezone.utc)
        try:
            result = operation()
            serialized = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            if not isinstance(serialized, dict):
                raise TypeError("extraction operation returned a non-object result")
            result_status = serialized.get("status", "completed")
            status = result_status if result_status in TERMINAL_STATUSES else "completed"
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.status = status
                    job.result = serialized
                    job.updated_at = datetime.now(timezone.utc)
        except Exception:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.status = "failed"
                    job.error = {
                        "code": "extraction_job_failed",
                        "message": "Extraction job failed. Retry the request or inspect server diagnostics.",
                    }
                    job.updated_at = datetime.now(timezone.utc)

    def _prune(self, now: datetime) -> None:
        """Remove terminal jobs whose last update exceeds the retention period."""
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in TERMINAL_STATUSES and now - job.updated_at >= self._retention
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)

    @staticmethod
    def _serialize(job: _ExtractionJob) -> dict[str, Any]:
        """Convert job state into the API polling JSON envelope."""
        return {
            "job_id": job.job_id,
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "result": job.result,
            "error": job.error,
        }