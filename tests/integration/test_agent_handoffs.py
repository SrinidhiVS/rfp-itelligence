import pytest

from src.agents import graph as graph_module
from src.agents import messages as messages_module
from src.agents.graph import AnalysisWorkflow
from src.agents.messages import make_message
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.agents.state import ValidationResult, WorkflowState
from src.agents.tracing import TraceRecorder


class Search:
    def search(self, query, configuration="hybrid"):
        record = {
            "record_id": "r1",
            "source_file": "rfp.html",
            "page_number": 1,
            "bid_id": "Bid1",
            "source_locator": {},
            "text": "Submission deadline: 2026-12-01.",
        }
        result = {"record_id": "r1", "record": record, "authority_status": "current"}
        return {"results": [result], "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_workflow_validates_forward_retry_and_report_handoffs(tmp_path, monkeypatch):
    actual_validate_message = messages_module.validate_message
    validated_edges = []

    def record_validation(value, **expected):
        message = actual_validate_message(value, **expected)
        validated_edges.append((message.sender, message.recipient))
        return message

    monkeypatch.setattr(graph_module, "validate_message", record_validation)

    actual_validate_fields = graph_module.validate_fields
    validation_calls = 0

    def reject_first_attempt(fields, evidence=None):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            return [
                ValidationResult(
                    scope="field",
                    field="submission_deadline",
                    status="rejected",
                    retry_eligible=True,
                    rejection_reason="retry once",
                )
            ], []
        return actual_validate_fields(fields, evidence)

    monkeypatch.setattr(graph_module, "validate_fields", reject_first_attempt)
    workflow = AnalysisWorkflow(
        RetrievalAgent(Search()),
        max_retries=1,
        settings=Settings(
            index_path=str(tmp_path / "index.json"),
            trace_path=str(tmp_path / "trace.json"),
            langsmith_api_key=None,
        ),
    )
    result = workflow.invoke(
        WorkflowState(
            mode="extraction",
            goal="submission deadline",
            bid_ids=["Bid1"],
            max_retries=1,
        )
    )

    assert result.status != "failed", result.final_output
    assert result.retry_count == 1
    assert validated_edges == [
        ("planner", "ingestion"),
        ("ingestion", "retrieval"),
        ("retrieval", "extraction"),
        ("extraction", "reconciliation"),
        ("reconciliation", "validation"),
        ("validation", "retrieval"),
        ("retrieval", "extraction"),
        ("extraction", "reconciliation"),
        ("reconciliation", "validation"),
        ("validation", "report"),
    ]


def test_invalid_recipient_is_rejected_before_node_executes():
    workflow = object.__new__(AnalysisWorkflow)
    executed = []
    node = workflow._agent_boundary("ingestion", lambda data: executed.append(True) or data)
    payload = {
        "state": WorkflowState(mode="extraction", goal="deadline").model_dump(mode="python"),
        "runtime": {"retry_evidence": [], "extraction_usage": []},
    }
    message = make_message(
        "run-1",
        "planner:0",
        "planner",
        "workflow_handoff",
        payload,
        recipient="retrieval",
    )

    with pytest.raises(ValueError, match="recipient"):
        node({"run_id": "run-1", "_trace": TraceRecorder("trace"), "_handoff": message.model_dump()})
    assert executed == []