import time

from fastapi.testclient import TestClient

from src.agents.state import AnalysisResponse
from src.api import app as app_module
from src.api.jobs import ExtractionJobManager


def test_extraction_job_api_returns_result_and_keeps_sync_route(monkeypatch):
    manager = ExtractionJobManager(max_workers=1, max_jobs=4)
    monkeypatch.setattr(app_module, "extraction_jobs", manager)
    monkeypatch.setattr(
        app_module,
        "_run",
        lambda *args, **kwargs: AnalysisResponse(
            run_id="job-run",
            status="completed",
            output={"fields": {"Bid Number": {"value": "B-1"}}},
        ),
    )
    client = TestClient(app_module.app)
    try:
        started = client.post(
            "/v1/analysis/extraction-jobs",
            json={"mode": "extraction", "bid_id": "Bid1"},
        )
        assert started.status_code == 202
        job_id = started.json()["job_id"]
        assert started.json()["status"] in {"queued", "running"}

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            polled = client.get(f"/v1/analysis/extraction-jobs/{job_id}")
            assert polled.status_code == 200
            if polled.json()["status"] == "completed":
                break
            time.sleep(0.005)
        assert polled.json()["status"] == "completed"
        assert polled.json()["result"]["run_id"] == "job-run"

        synchronous = client.post(
            "/v1/analysis/extract",
            json={"mode": "extraction", "bid_id": "Bid1"},
        )
        assert synchronous.status_code == 200
        assert synchronous.json()["run_id"] == "job-run"
    finally:
        client.close()
        manager.shutdown()


def test_unknown_extraction_job_returns_not_found():
    client = TestClient(app_module.app)
    try:
        response = client.get("/v1/analysis/extraction-jobs/unknown-job")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "job_not_found"
    finally:
        client.close()


def test_extraction_job_forwards_filters_and_preserves_unfiltered_request(monkeypatch):
    manager = ExtractionJobManager(max_workers=1, max_jobs=4)

    class CapturingWorkflow:
        def __init__(self):
            self.states = []

        def invoke(self, state):
            self.states.append(state)
            state.status = "completed"
            state.final_output = {
                "run_id": state.run_id,
                "status": "completed",
                "output": {"fields": {}},
                "diagnostics": [],
                "trace_reference": None,
                "evaluation": {},
            }
            return state

    workflow = CapturingWorkflow()
    monkeypatch.setattr(app_module, "extraction_jobs", manager)
    monkeypatch.setattr(app_module, "workflow", workflow)
    client = TestClient(app_module.app)

    def submit_and_wait(payload):
        started = client.post("/v1/analysis/extraction-jobs", json=payload)
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            response = client.get(f"/v1/analysis/extraction-jobs/{job_id}")
            assert response.status_code == 200
            if response.json()["status"] == "completed":
                return response.json()
            time.sleep(0.005)
        raise AssertionError("extraction job did not complete")

    try:
        filters = {"doc_type": "addendum", "addendum_number": 2}
        filtered = submit_and_wait({"mode": "extraction", "bid_id": "Bid1", "filters": filters})
        unfiltered = submit_and_wait({"mode": "extraction", "bid_id": "Bid2"})

        assert filtered["result"]["status"] == "completed"
        assert unfiltered["result"]["status"] == "completed"
        assert workflow.states[0].bid_ids == ["Bid1"]
        assert workflow.states[0].search_filters == filters
        assert workflow.states[1].bid_ids == ["Bid2"]
        assert workflow.states[1].search_filters is None
    finally:
        client.close()
        manager.shutdown()
