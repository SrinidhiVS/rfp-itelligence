from __future__ import annotations

from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from src.frontend import app as frontend_app
from src.frontend.config import FrontendConfig


class FakeFrontendClient:
    def __init__(self) -> None:
        self.config = FrontendConfig(bid_ids=("Bid1", "Bid2", "District-RFP-3"))
        self.question_response: dict[str, Any] = analysis_response(
            output={
                "answer": "The due date is October 30.",
                "found": True,
                "citations": [],
                "evidence_by_bid": {},
            }
        )
        self.extraction_response: dict[str, Any] = analysis_response(
            output={"fields": {}, "addendum_changes": [], "validation": []}
        )
        self.import_result: dict[str, Any] = {
            "bid_id": "imported-bid",
            "report": {
                "status": "complete",
                "documents": [],
                "diagnostics": [],
            },
            "index": {"indexed": 1, "skipped": 0, "replaced": 0, "removed": 0, "failed": 0},
        }
        self.question_error: Exception | None = None
        self.questions: list[str] = []
        self.extraction_error: Exception | None = None
        self.extraction_wait_error: Exception | None = None
        self.extraction_job_start_count = 0
        self.extraction_job_polls: list[str] = []
        self.import_error: Exception | None = None
        self.extraction_job_id = "test-extraction-job"

    def health(self) -> dict[str, Any]:
        return {"semantic_search": {"semantic_enabled": True}}

    def ask(self, request: Any) -> dict[str, Any]:
        self.questions.append(request.question)
        if self.question_error:
            raise self.question_error
        return self.question_response

    def extract(self, request: Any) -> dict[str, Any]:
        if self.extraction_error:
            raise self.extraction_error
        return self.extraction_response

    def start_extraction_job(self, request: Any) -> dict[str, Any]:
        if self.extraction_error:
            raise self.extraction_error
        self.extraction_job_start_count += 1
        self.extraction_request = request
        return {"job_id": self.extraction_job_id, "status": "queued"}

    def wait_for_extraction_job(self, job_id: str, on_update=None) -> dict[str, Any]:
        self.extraction_job_polls.append(job_id)
        if self.extraction_wait_error:
            raise self.extraction_wait_error
        for status in ("queued", "running", self.extraction_response.get("status", "completed")):
            if on_update:
                on_update({"job_id": job_id, "status": status})
        return self.extraction_response

    def import_bid_files(self, folder_name: str, uploaded_files: list[Any]) -> dict[str, Any]:
        if self.import_error:
            raise self.import_error
        return self.import_result


def analysis_response(
    status: str = "completed",
    output: dict[str, Any] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": "test-run",
        "status": status,
        "output": output or {},
        "diagnostics": diagnostics or [],
        "trace_reference": None,
        "evaluation": {},
    }


@pytest.fixture
def response_factory():
    return analysis_response


@pytest.fixture
def import_result_factory():
    def build(
        status: str = "complete",
        diagnostics: list[dict[str, Any]] | None = None,
        documents: list[dict[str, Any]] | None = None,
        index: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return {
            "bid_id": "imported-bid",
            "report": {
                "status": status,
                "documents": documents or [],
                "diagnostics": diagnostics or [],
            },
            "index": index or {"indexed": 1, "skipped": 0, "replaced": 0, "removed": 0, "failed": 0},
        }

    return build


@pytest.fixture
def frontend_client(monkeypatch: pytest.MonkeyPatch) -> FakeFrontendClient:
    client = FakeFrontendClient()
    monkeypatch.setattr(frontend_app, "get_client", lambda: client)
    return client


@pytest.fixture
def app_test(frontend_client: FakeFrontendClient) -> AppTest:
    return AppTest.from_function(_run_frontend_app).run()


def _run_frontend_app() -> None:
    from src.frontend.app import main

    main()