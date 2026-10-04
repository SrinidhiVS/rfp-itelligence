from src.agents.graph import AnalysisWorkflow
from src.agents.state import ExtractionResult, ModelUsage
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.report_agent import extraction_response, synthesize_answer
from src.agents.settings import Settings
from src.agents.state import AddendumChange, ExtractionField, WorkflowState
from src.agents.tracing import TraceRecorder


class EmptySearch:
    def search(self, query, configuration="hybrid"):
        return {"results": [], "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_report_agent_uses_not_found_guardrail():
    result = AnalysisWorkflow(RetrievalAgent(EmptySearch())).invoke(WorkflowState(mode="qa", goal="unknown", bid_ids=["Bid1"]))
    assert result.final_output["answer"] == "Not found in documents"


def test_extraction_report_exposes_unresolved_fields_and_cited_conflicts():
    state = WorkflowState(mode="extraction", goal="deadline", bid_ids=["Bid1"], status="partial", retry_attempts={"submission_deadline": 2},
                          draft_fields={"submission_deadline": ExtractionField(name="submission_deadline", status="review_required", notes="conflicting dates")},
                          addendum_changes=[AddendumChange(field="submission_deadline", previous_value="2026-09-01", new_value="2026-10-01", addendum_number=2, citations=[{"file": "addendum.pdf", "bid_id": "Bid1"}], reason="conflicting changes", review_required=True)])
    output = extraction_response(state).output
    assert {"fields", "addendum_changes", "validation", "summary"} <= set(output)
    assert output["unresolved_fields"] == ["submission_deadline"]
    assert output["retry_attempts"] == {"submission_deadline": 2}
    assert output["addendum_conflicts"][0]["citations"][0]["file"] == "addendum.pdf"


def test_qa_synthesis_is_concise_cited_and_bid_scoped():
    text = "Submission deadline: October 10, 2026. " + "Other boilerplate. " * 30
    evidence = [{"record": {"record_id": "one", "source_file": "bid1.pdf", "page_number": 2, "bid_id": "Bid1", "source_locator": {}, "text": text}, "authority_status": "current"},
                {"record": {"record_id": "two", "source_file": "bid2.pdf", "page_number": 4, "bid_id": "Bid2", "source_locator": {}, "text": "Submission deadline: October 15, 2026."}, "authority_status": "current"}]
    answer = synthesize_answer("Compare submission deadlines", evidence)
    assert answer["found"] and not answer["disputed"]
    assert len(answer["answer"]) < len(text)
    assert {claim["bid_id"] for claim in answer["claims"]} == {"Bid1", "Bid2"}
    assert all(claim["citations"][0]["bid_id"] == claim["bid_id"] for claim in answer["claims"])
    assert synthesize_answer("What is the insurance amount?", evidence)["found"] is False
    conflicting = synthesize_answer("When is the deadline?", [evidence[0], {**evidence[1], "record": {**evidence[1]["record"], "bid_id": "Bid1"}}])
    assert conflicting["disputed"] and not conflicting["found"]


def test_qa_workflow_uses_model_to_generate_report_without_replacing_citations():
    class ReportProvider:
        def __init__(self):
            self.called = False

        def extract_fields(self, evidence, field_names):
            return ExtractionResult()

        def generate_report(self, question, claims, fallback_answer):
            self.called = True
            assert question == "When is the deadline?"
            assert claims[0]["text"] == "Bid1: submission deadline is October 10, 2026."
            return ExtractionResult(
                values={"answer": "The deadline is October 10, 2026."},
                usage=ModelUsage(provider="ollama", model="qwen2.5:3b"),
            )

    provider = ReportProvider()
    workflow = AnalysisWorkflow(
        retrieval_agent=EmptySearch(),
        model_provider=provider,
        settings=Settings(trace_enabled=False),
    )
    evidence = [{
        "record": {
            "record_id": "deadline",
            "source_file": "bid1.pdf",
            "page_number": 2,
            "bid_id": "Bid1",
            "source_locator": {},
            "text": "Submission deadline: October 10, 2026.",
        },
        "authority_status": "current",
    }]
    data = {
        "mode": "qa",
        "goal": "When is the deadline?",
        "retrieved_evidence": evidence,
        "diagnostics": [],
        "_trace": TraceRecorder("qa-report"),
    }

    workflow._extraction(data)

    assert provider.called
    assert data["final_output"]["answer"] == "The deadline is October 10, 2026."
    assert data["final_output"]["citations"][0]["file"] == "bid1.pdf"
    assert data["final_output"]["report_generation"]["provider"] == "ollama"


def test_qa_synthesizes_model_number_from_source_with_claim_citation():
    text = "SI# CC7802 Dell\nLatitude 5550\nDescription\nDell Latitude 5550 XCTO Base"
    evidence = [{"record": {"record_id": "model", "source_file": "Dell_Laptop_Specs.pdf", "page_number": 1, "bid_id": "Bid2", "source_locator": {}, "text": text}, "authority_status": "current"}]
    answer = synthesize_answer("What is the model number?", evidence)
    assert answer["found"]
    assert "Dell Latitude 5550" in answer["claims"][0]["text"]
    citation = answer["claims"][0]["citations"][0]
    assert citation["file"] == "Dell_Laptop_Specs.pdf" and citation["page"] == 1 and citation["bid_id"] == "Bid2"


def test_qa_synthesizes_mandatory_requirement_from_source():
    text = "The Master Contractor must be an authorized reseller for Dell."
    evidence = [{"record": {"record_id": "requirement", "source_file": "PORFP_-_Dell_Laptop_Final.pdf", "page_number": 2, "bid_id": "Bid2", "source_locator": {}, "text": text}, "authority_status": "current"}]
    answer = synthesize_answer("What mandatory requirement applies to Dell reseller authorization?", evidence)
    assert answer["found"] and "authorized reseller for Dell" in answer["answer"]
    assert answer["claims"][0]["citations"][0]["page"] == 2


def test_qa_uses_question_relevance_to_choose_mandatory_requirement():
    evidence = [
        {"record": {"record_id": "forms", "source_file": "rfp.pdf", "page_number": 11, "bid_id": "Bid1", "source_locator": {}, "text": "One (1) form must be provided for each, and every subcontractor employed."}, "authority_status": "current"},
        {"record": {"record_id": "joint-venture", "source_file": "rfp.pdf", "page_number": 43, "bid_id": "Bid1", "source_locator": {}, "text": "Each JV partner (excluding your company) must complete Sections A through D on Page 4."}, "authority_status": "current"},
    ]
    answer = synthesize_answer("What mandatory requirement applies to forms for subcontractors?", evidence)
    assert answer["found"] and not answer["disputed"]
    assert len(answer["claims"]) == 1
    assert "form must be provided" in answer["claims"][0]["text"]
    assert answer["claims"][0]["citations"][0]["page"] == 11
