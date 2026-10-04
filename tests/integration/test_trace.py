import json

from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.agents.state import ExtractionResult, ModelUsage, WorkflowState


class Search:
    def search(self, query, configuration="hybrid"):
        return {"results": [], "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_workflow_trace_has_all_nodes():
    result = AnalysisWorkflow(RetrievalAgent(Search())).invoke(WorkflowState(mode="extraction", goal="extract", bid_ids=["Bid1"]))
    nodes = {event["node"] for event in result.trace.events}
    assert {"Planner", "Ingestion", "Retrieval", "Extraction", "Reconciliation", "Validation", "Report"} <= nodes


def test_workflow_records_usage_tools_and_survives_sink_failure(tmp_path):
    class EvidenceSearch:
        def search(self, query, configuration="hybrid"):
            record = {
                "record_id": "r1",
                "source_file": "rfp.html",
                "page_number": 1,
                "bid_id": "Bid1",
                "source_locator": {},
                "text": "Submission deadline: 2026-12-01. api_key=source-secret",
            }
            result = {"record_id": "r1", "record": record, "authority_status": "current"}
            return {"results": [result], "diagnostics": [], "query_variants": {"variants": [query.text]}}

    class Provider:
        def extract_fields(self, evidence, field_names):
            return ExtractionResult(
                values={"submission_deadline": "2026-12-01"},
                usage=ModelUsage(
                    provider="fake",
                    model="offline",
                    input_tokens=10,
                    output_tokens=3,
                    total_tokens=13,
                    availability="reported",
                ),
            )

    workflow = AnalysisWorkflow(
        RetrievalAgent(EvidenceSearch()),
        model_provider=Provider(),
        settings=Settings(
            index_path=str(tmp_path / "index.json"),
            trace_path=str(tmp_path / "trace.json"),
            langsmith_api_key="test-only",
        ),
    )

    class FailingSink:
        def record(self, trace):
            raise RuntimeError("trace transport unavailable")

    workflow.trace_sink = FailingSink()
    result = workflow.invoke(WorkflowState(mode="extraction", goal="submission deadline", bid_ids=["Bid1"]))

    assert result.status == "completed"
    events = result.trace.events
    assert any(event.get("event_type") == "model_call" and event["usage"]["total_tokens"] == 13 for event in events)
    assert any(event.get("event_type") == "tool_call" and event["tool_name"] == "retrieval" for event in events)
    assert any(event.get("event_type") == "tool_call" and event["tool_name"] == "bid_indexing" for event in events)
    serialized = json.dumps(result.trace.model_dump())
    assert "source-secret" not in serialized
    assert "Submission deadline: 2026-12-01" not in serialized
    assert (tmp_path / "trace.json").exists()


def test_disabled_tracing_skips_persistence_and_remote_sink(tmp_path):
    workflow = AnalysisWorkflow(
        RetrievalAgent(Search()),
        settings=Settings(
            trace_enabled=False,
            trace_path=str(tmp_path / "trace.json"),
            langsmith_api_key="test-only",
        ),
    )

    class ForbiddenSink:
        def record(self, trace):
            raise AssertionError("disabled tracing called the remote sink")

    workflow.trace_sink = ForbiddenSink()
    result = workflow.invoke(WorkflowState(mode="qa", goal="unknown", bid_ids=["Bid1"]))

    assert result.status == "partial"
    assert result.trace.delivery_status == "disabled"
    assert not (tmp_path / "trace.json").exists()


def test_missing_langsmith_credentials_marks_trace_unconfigured(tmp_path):
    workflow = AnalysisWorkflow(
        RetrievalAgent(Search()),
        settings=Settings(
            trace_path=str(tmp_path / "trace.json"),
            langsmith_api_key=None,
        ),
    )

    result = workflow.invoke(WorkflowState(mode="qa", goal="unknown", bid_ids=["Bid1"]))

    assert result.trace.delivery_status == "unconfigured"


def test_unwritable_local_trace_does_not_fail_analysis(tmp_path):
    blocked_path = tmp_path / "trace-directory"
    blocked_path.mkdir()
    workflow = AnalysisWorkflow(
        RetrievalAgent(Search()),
        settings=Settings(
            trace_path=str(blocked_path),
            langsmith_api_key=None,
        ),
    )

    result = workflow.invoke(WorkflowState(mode="qa", goal="unknown", bid_ids=["Bid1"]))

    assert result.status == "partial"
    assert result.final_output["answer"] == "Not found in documents"
    assert result.trace.local_persistence_status == "failed"
