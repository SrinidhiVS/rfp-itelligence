from fastapi.testclient import TestClient

from src.api import app as app_module


class CapturingWorkflow:
    def __init__(self):
        self.states = []

    def invoke(self, state):
        self.states.append(state)
        state.status = "completed"
        return state


def test_optional_filters_reach_qa_and_extraction_without_changing_unfiltered_requests(monkeypatch):
    workflow = CapturingWorkflow()
    monkeypatch.setattr(app_module, "workflow", workflow)
    client = TestClient(app_module.app)
    filters = {"doc_type": "addendum", "addendum_number": 2}

    qa_response = client.post(
        "/v1/analysis/qa",
        json={"mode": "qa", "question": "What changed?", "bid_ids": ["Bid1"], "filters": filters},
    )
    assert qa_response.status_code == 200
    assert workflow.states[-1].search_filters == filters
    assert set(qa_response.json()) == {"run_id", "status", "output", "diagnostics", "trace_reference", "evaluation"}

    extraction_response = client.post(
        "/v1/analysis/extract",
        json={"mode": "extraction", "bid_id": "Bid1", "filters": filters, "trace": False},
    )
    assert extraction_response.status_code == 200
    assert workflow.states[-1].search_filters == filters
    assert "fields" in extraction_response.json()["output"]

    unfiltered_response = client.post(
        "/v1/analysis/qa",
        json={"mode": "qa", "question": "unknown", "bid_ids": ["Bid1"]},
    )
    assert unfiltered_response.status_code == 200
    assert workflow.states[-1].search_filters is None


def test_invalid_analysis_filters_return_structured_validation_errors():
    client = TestClient(app_module.app)
    invalid_filters = (
        {"doc_type": "unrecognized"},
        {"addendum_number": 0},
        {"bid_id": ["OtherBid"]},
    )

    for filters in invalid_filters:
        response = client.post(
            "/v1/analysis/qa",
            json={"mode": "qa", "question": "deadline", "bid_ids": ["Bid1"], "filters": filters},
        )
        assert response.status_code == 422
        assert "detail" in response.json()
