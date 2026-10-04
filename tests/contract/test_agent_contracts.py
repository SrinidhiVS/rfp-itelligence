import pytest
from pydantic import ValidationError

from src.agents.messages import make_message, validate_message
from src.agents.state import AnalysisResponse, ExtractionField, WorkflowState
from fastapi import HTTPException
from src.api.app import ExtractionRequest, QARequest, _resolve_submissions


def test_supported_field_requires_citation():
    field = ExtractionField(name="deadline", value="2026-10-10", status="supported", citations=[{"file": "bid.html", "bid_id": "Bid1"}])
    assert field.citations[0].file == "bid.html"


def test_message_contract_round_trips():
    message = make_message("run-1", "task-1", "Planner", "plan", {"mode": "extraction"}, recipient="Ingestion")
    validated = validate_message(
        message,
        expected_sender="Planner",
        expected_recipient="Ingestion",
        expected_run_id="run-1",
    )
    assert validated.payload_type == "plan"
    assert validated.sender == "Planner"
    assert validated.agent == "Planner"
    assert validated.message_version == 1


def test_message_rejects_missing_identity_unknown_types_and_invalid_payloads():
    message = make_message("run-1", "task-1", "Planner", "plan", {"mode": "extraction"}, recipient="Ingestion")
    missing_version = message.model_dump()
    missing_version.pop("message_version")
    with pytest.raises(ValueError, match="invalid agent message"):
        validate_message(missing_version)

    with pytest.raises(ValueError, match="recipient"):
        validate_message(message, expected_recipient="Retrieval")

    invalid_payload = make_message("run-1", "task-2", "Planner", "plan", {"mode": "unknown"}, recipient="Ingestion")
    with pytest.raises(ValueError, match="invalid agent payload"):
        validate_message(invalid_payload)

    unknown_type = make_message("run-1", "task-3", "Planner", "unknown", {}, recipient="Ingestion")
    with pytest.raises(ValueError, match="unknown agent payload type"):
        validate_message(unknown_type)


def test_response_contains_evaluation():
    response = AnalysisResponse(run_id="run-1", status="completed", output={})
    assert response.evaluation.field_dispositions == {}


def test_workflow_state_accepts_optional_submissions_and_retry_selection():
    old = WorkflowState(mode="extraction", goal="extract complete bid record", bid_ids=["Bid1"])
    assert old.submitted_bid_folders == {} and old.unsupported_work == [] and old.retry_fields == []
    state = WorkflowState(mode="extraction", goal="deadline", bid_ids=["Bid1"], submitted_bid_folders={"Bid1": "Bid1"}, retry_fields=["submission_deadline"])
    assert state.submitted_bid_folders == {"Bid1": "Bid1"}
    assert state.retry_fields == ["submission_deadline"]
    assert {"run_id", "status", "output", "diagnostics", "trace_reference", "evaluation"} <= set(AnalysisResponse(run_id="run-1", status="completed", output={}).model_dump())
    with pytest.raises(ValidationError):
        WorkflowState(mode="extraction", goal="deadline", bid_ids=["Bid1"], max_retries=-1)


def test_api_requests_keep_old_inputs_and_restrict_submission_bid_scope():
    assert ExtractionRequest(bid_id="Bid1").submitted_bid_folders == {}
    assert QARequest(question="deadline?", bid_ids=["Bid1"]).submitted_bid_folders == {}
    assert ExtractionRequest(bid_id="Bid1", submitted_bid_folders={"Bid1": "Bid1"}).submitted_bid_folders == {"Bid1": "Bid1"}
    assert QARequest(question="deadline?", bid_ids=["Bid1"], submitted_bid_folders={"Bid1": "Bid1"}).submitted_bid_folders == {"Bid1": "Bid1"}
    for request in ({"bid_id": "Bid1", "submitted_bid_folders": {"Bid2": "Bid2"}}, {"bid_id": "Bid1", "submitted_bid_folders": {"Bid1": "../Bid2"}}):
        with pytest.raises(ValidationError):
            ExtractionRequest(**request)
    with pytest.raises(ValidationError):
        QARequest(question="deadline?", bid_ids=["Bid1"], submitted_bid_folders={"Bid2": "Bid2"})


def test_staged_bid_folders_must_exist_inside_authorized_root(tmp_path, monkeypatch):
    monkeypatch.setenv("RFP_SUBMISSION_ROOT", str(tmp_path))
    with pytest.raises(HTTPException) as missing:
        _resolve_submissions({"Bid1": "Bid1"})
    assert missing.value.status_code == 422
    folder = tmp_path / "Bid1"
    folder.mkdir()
    assert _resolve_submissions({"Bid1": "Bid1"}) == {"Bid1": str(folder.resolve())}
    with pytest.raises(ValidationError):
        ExtractionRequest(bid_id="Bid1", submitted_bid_folders={"Bid1": str(tmp_path)})
