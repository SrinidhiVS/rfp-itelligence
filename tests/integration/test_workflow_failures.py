import pytest

from src.agents.graph import AnalysisWorkflow
from src.agents import graph as graph_module
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.state import ValidationResult, WorkflowState
from src.agents.messages import validate_message
from src.agents.settings import Settings
from src.agents.tracing import TraceRecorder


class EmptySearch:
    def search(self, query, configuration="hybrid"):
        return {"results": [], "diagnostics": ["no_supporting_evidence"], "query_variants": {"variants": [query.text]}}


def test_empty_retrieval_returns_partial_fields_without_crash():
    result = AnalysisWorkflow(RetrievalAgent(EmptySearch())).invoke(WorkflowState(mode="extraction", goal="extract", bid_ids=["Bid1"]))
    assert result.final_output["fields"]["submission_deadline"]["status"] == "not_found"
    assert result.final_output["fields"]["submission_deadline"]["notes"] == "Not found in documents"

class FailingSearch:
    def search(self, query, configuration="hybrid"):
        raise TimeoutError("search timed out")

def test_search_failure_returns_structured_failed_state():
    result = AnalysisWorkflow(RetrievalAgent(FailingSearch())).invoke(WorkflowState(mode="qa", goal="deadline", bid_ids=["Bid1"]))
    assert result.status == "failed"
    assert result.final_output["error"] == "workflow failed"

def test_malformed_message_is_rejected():
    try:
        validate_message({"payload": {}})
    except ValueError as exc:
        assert "invalid agent message" in str(exc)
    else:
        raise AssertionError("malformed message was accepted")

def test_missing_model_configuration_is_structured():
    settings = Settings(openai_api_key=None)
    try:
        settings.require_model()
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("missing configuration was accepted")

def test_trace_provider_fallback_preserves_local_event():
    recorder = TraceRecorder("fallback")
    recorder.event("Report", "end", status="failed", error="provider unavailable")
    assert recorder.trace.events[0]["error"] == "provider unavailable"


@pytest.mark.parametrize("fail_until,max_retries", [(1, 1), (100, 2)])
def test_retry_reextracts_only_failed_field_and_preserves_accepted_field(tmp_path, monkeypatch, fail_until, max_retries):
    searches = []
    extracted = []

    class Search:
        def search(self, query, configuration="hybrid"):
            searches.append(query.text)
            record = {"record_id": "r1", "source_file": "rfp.html", "page_number": 1, "bid_id": "Bid1", "source_locator": {}, "text": "Submission deadline: 2026-12-01. Bid bond: 5% of bid price"}
            return {"results": [{"record_id": "r1", "record": record, "authority_status": "current"}], "diagnostics": [], "query_variants": {"variants": [query.text]}}

    class Model:
        def extract_fields(self, evidence, field_names):
            extracted.append(tuple(field_names))
            return {}

    actual_validate = graph_module.validate_fields
    attempts = 0

    def validate(fields, evidence=None):
        nonlocal attempts
        attempts += 1
        if attempts <= fail_until:
            return [ValidationResult(scope="field", field="submission_deadline", status="passed"), ValidationResult(scope="field", field="bid_bond", status="rejected", retry_eligible=True, rejection_reason="retry bond")], []
        return actual_validate(fields, evidence)

    monkeypatch.setattr(graph_module, "validate_fields", validate)
    workflow = AnalysisWorkflow(RetrievalAgent(Search()), max_retries=max_retries, model_provider=Model(), settings=Settings(trace_path=str(tmp_path / "trace.json")))
    result = workflow.invoke(WorkflowState(mode="extraction", goal="submission deadline and bid bond", bid_ids=["Bid1"], max_retries=max_retries))
    assert result.status != "failed", result.final_output
    assert result.retry_attempts == {"bid_bond": max_retries}
    assert sorted(extracted[:2]) == sorted([("submission_deadline",), ("bid_bond",)])
    assert extracted[2:] == [("bid_bond",)] * max_retries
    assert sum(query.startswith("submission deadline ") for query in searches) == 1
    assert sum(query.startswith("bid bond ") for query in searches) == max_retries + 1
    assert all("submission deadline and bid bond" in query for query in searches)
    assert result.final_output["fields"]["submission_deadline"]["value"] == "2026-12-01"
    if fail_until > max_retries:
        assert result.status == "partial"
        assert any(item.code == "retry_exhausted" for item in result.diagnostics)


def test_retry_without_new_support_leaves_missing_field_and_accepted_citation(tmp_path, monkeypatch):
    class Search:
        bond_calls = 0

        def search(self, query, configuration="hybrid"):
            if "bid bond" in query.text:
                self.bond_calls += 1
                if self.bond_calls > 1:
                    return {"results": [], "diagnostics": ["no_supporting_evidence"], "query_variants": {"variants": [query.text]}}
            record = {"record_id": "r1", "source_file": "rfp.html", "page_number": 1, "bid_id": "Bid1", "source_locator": {}, "text": "Submission deadline: 2026-12-01. Bid bond: 5% of bid price"}
            return {"results": [{"record_id": "r1", "record": record, "authority_status": "current"}], "diagnostics": [], "query_variants": {"variants": [query.text]}}

    initial_validate = graph_module.validate_fields
    checked = False

    def validate(fields, evidence=None):
        nonlocal checked
        if not checked:
            checked = True
            return [ValidationResult(scope="field", field="submission_deadline", status="passed"), ValidationResult(scope="field", field="bid_bond", status="rejected", retry_eligible=True)], []
        return initial_validate(fields, evidence)

    monkeypatch.setattr(graph_module, "validate_fields", validate)
    workflow = AnalysisWorkflow(RetrievalAgent(Search()), settings=Settings(trace_path=str(tmp_path / "trace.json")))
    result = workflow.invoke(WorkflowState(mode="extraction", goal="submission deadline and bid bond", bid_ids=["Bid1"], max_retries=2))
    assert result.retry_attempts == {"bid_bond": 1}
    assert result.final_output["fields"]["submission_deadline"]["citations"]
    assert result.final_output["fields"]["bid_bond"]["status"] == "not_found"
    assert result.status == "partial"
