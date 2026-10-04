from datetime import datetime, timedelta, timezone
from threading import Event
import time

import pytest

from src.api.jobs import ExtractionJobCapacityError, ExtractionJobManager


def _wait_for_status(manager: ExtractionJobManager, job_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job and job["status"] == expected:
            return job
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def test_job_returns_immediately_and_publishes_result():
    manager = ExtractionJobManager(max_workers=1, max_jobs=2)
    release = Event()
    try:
        job = manager.submit(lambda: (release.wait(2), {"status": "completed", "output": {"fields": {}}})[1])
        assert job["status"] in {"queued", "running"}
        running = _wait_for_status(manager, job["job_id"], "running")
        assert running["result"] is None

        release.set()
        completed = _wait_for_status(manager, job["job_id"], "completed")
        assert completed["result"] == {"status": "completed", "output": {"fields": {}}}
    finally:
        release.set()
        manager.shutdown()


def test_job_errors_are_structured_and_do_not_escape_worker():
    manager = ExtractionJobManager(max_workers=1, max_jobs=2)
    try:
        job = manager.submit(lambda: (_ for _ in ()).throw(RuntimeError("private detail")))
        failed = _wait_for_status(manager, job["job_id"], "failed")
        assert failed["error"] == {
            "code": "extraction_job_failed",
            "message": "Extraction job failed. Retry the request or inspect server diagnostics.",
        }
        assert "private detail" not in str(failed)
    finally:
        manager.shutdown()


def test_job_capacity_is_bounded():
    manager = ExtractionJobManager(max_workers=1, max_jobs=1)
    release = Event()
    try:
        manager.submit(lambda: release.wait(2))
        with pytest.raises(ExtractionJobCapacityError):
            manager.submit(lambda: None)
    finally:
        release.set()
        manager.shutdown()


def test_terminal_job_expires_after_retention():
    manager = ExtractionJobManager(max_workers=1, max_jobs=1, retention=timedelta(seconds=10))
    try:
        job = manager.submit(lambda: {"status": "completed"})
        _wait_for_status(manager, job["job_id"], "completed")
        manager._jobs[job["job_id"]].updated_at = datetime.now(timezone.utc) - timedelta(seconds=11)
        assert manager.get(job["job_id"]) is None
    finally:
        manager.shutdown()
