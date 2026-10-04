import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.api import app as app_module
from src.agents.state import ExtractionField, WorkflowState
from src.extraction.fields import CANONICAL_FIELDS
from tests.fixtures.supp_tasks_corpus import build_supp_tasks_corpus


def test_extract_endpoint_returns_canonical_fields_without_removing_legacy_output(monkeypatch, tmp_path):
    fixture = json.loads(Path("tests/fixtures/supp_tasks_coverage.json").read_text(encoding="utf-8"))
    evidence_by_key, _ = build_supp_tasks_corpus(tmp_path / "search-index.json")
    bid1_evidence = [
        evidence_by_key[item["evidence_key"]]
        for item in fixture["records"]
        if item["source"]["bid_id"] == "Bid1"
    ]
    state = WorkflowState(
        mode="extraction",
        goal="extract complete bid record",
        bid_ids=["Bid1"],
        status="completed",
        retrieved_evidence=bid1_evidence,
        draft_fields={
            "submission_deadline": ExtractionField(
                name="submission_deadline",
                value="July 9, 2024",
                confidence=0.9,
                citations=[{"file": "Addendum 2.pdf", "page": 1, "bid_id": "Bid1"}],
                status="supported",
            )
        },
        trace_reference="trace-test",
    )

    class StubWorkflow:
        def invoke(self, request_state):
            return state

    monkeypatch.setattr(app_module, "workflow", StubWorkflow())
    response = TestClient(app_module.app).post(
        "/v1/analysis/extract",
        json={"mode": "extraction", "bid_id": "Bid1", "trace": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"run_id", "status", "output", "diagnostics", "trace_reference", "evaluation"}
    fields = payload["output"]["fields"]
    assert set(CANONICAL_FIELDS).issubset(fields)
    assert "submission_deadline" in fields

    supported = fields["Due Date"]
    assert supported["value"] is not None
    assert supported["status"] == "supported"
    assert supported["citations"]
    assert all(citation["bid_id"] == "Bid1" for citation in supported["citations"])

    missing = fields["Contract or Cooperative to Use"]
    assert missing["value"] is None
    assert missing["citations"] == []
    assert missing["confidence"] == 0.0
    assert missing["status"] == "not_found"
    assert "Not found in documents" in missing["notes"]

    assert {"addendum_changes", "validation", "summary", "unsupported_work"}.issubset(payload["output"])