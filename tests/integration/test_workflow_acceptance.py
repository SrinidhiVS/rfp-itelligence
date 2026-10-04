from src.agents.report_agent import citation_coverage
from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.settings import Settings
from src.agents.state import ExtractionField, WorkflowState


def test_citation_acceptance_threshold_is_defined_for_non_null_fields():
    fields = {"a": ExtractionField(name="a"), "b": ExtractionField(name="b")}
    assert citation_coverage(fields) == 1.0


def test_qa_workflow_returns_direct_claim_cited_answer_and_no_answer(tmp_path):
    class Search:
        def search(self, query, configuration="hybrid"):
            record = {"record_id": "r1", "source_file": "bid.pdf", "page_number": 2, "bid_id": "Bid1", "source_locator": {}, "text": "Submission deadline: October 10, 2026. Additional purchasing boilerplate."}
            return {"results": [{"record_id": "r1", "record": record, "authority_status": "current"}], "diagnostics": [], "query_variants": {"variants": [query.text]}}

    workflow = AnalysisWorkflow(RetrievalAgent(Search()), settings=Settings(trace_path=str(tmp_path / "trace.json")))
    result = workflow.invoke(WorkflowState(mode="qa", goal="When is the submission deadline?", bid_ids=["Bid1"]))
    output = result.final_output
    assert output["found"] and "October 10, 2026" in output["answer"]
    assert "Additional purchasing boilerplate" not in output["answer"]
    assert output["claims"][0]["citations"][0]["file"] == "bid.pdf"
    unknown = workflow.invoke(WorkflowState(mode="qa", goal="What is the insurance amount?", bid_ids=["Bid1"]))
    assert not unknown.final_output["found"] and unknown.final_output["citations"] == []


def test_qa_workflow_keeps_bid_claims_separate_and_flags_conflict(tmp_path):
    class Search:
        def __init__(self):
            self.conflict = False

        def search(self, query, configuration="hybrid"):
            second_bid = "Bid1" if self.conflict else "Bid2"
            results = []
            for record_id, bid_id, due_date in (("one", "Bid1", "2026-10-10"), ("two", second_bid, "2026-10-15")):
                record = {"record_id": record_id, "source_file": f"{record_id}.pdf", "page_number": 1, "bid_id": bid_id, "source_locator": {}, "text": f"Submission deadline: {due_date}"}
                results.append({"record_id": record_id, "record": record, "authority_status": "current"})
            return {"results": results, "diagnostics": [], "query_variants": {"variants": [query.text]}}

    search = Search()
    workflow = AnalysisWorkflow(RetrievalAgent(search), settings=Settings(trace_path=str(tmp_path / "trace.json")))
    compared = workflow.invoke(WorkflowState(mode="qa", goal="Compare submission deadlines", bid_ids=["Bid1", "Bid2"]))
    assert compared.status == "completed" and compared.final_output["found"]
    assert {claim["bid_id"] for claim in compared.final_output["claims"]} == {"Bid1", "Bid2"}
    assert all(claim["citations"][0]["bid_id"] == claim["bid_id"] for claim in compared.final_output["claims"])
    search.conflict = True
    conflicted = workflow.invoke(WorkflowState(mode="qa", goal="When is the submission deadline?", bid_ids=["Bid1"]))
    assert conflicted.status == "review_required" and conflicted.final_output["disputed"]
    assert not conflicted.final_output["found"] and len(conflicted.final_output["citations"]) == 2


def test_extraction_retrieval_includes_goal_specific_terms(tmp_path):
    class Search:
        queries = []

        def search(self, query, configuration="hybrid"):
            self.queries.append(query.text)
            record = {"record_id": "forms", "source_file": "rfp.pdf", "page_number": 11, "bid_id": "Bid1", "source_locator": {}, "text": "One (1) form must be provided for each, and every subcontractor employed."}
            return {"results": [{"record_id": "forms", "record": record, "authority_status": "current"}], "diagnostics": [], "query_variants": {"variants": [query.text]}}

    search = Search()
    workflow = AnalysisWorkflow(RetrievalAgent(search), settings=Settings(trace_path=str(tmp_path / "trace.json")))
    result = workflow.invoke(WorkflowState(mode="extraction", goal="Extract mandatory requirement for subcontractor forms", bid_ids=["Bid1"], max_retries=0))
    assert result.final_output["fields"]["mandatory_requirements"]["value"] == "One (1) form must be provided for each, and every subcontractor employed."
    assert any("subcontractor forms" in query.lower() for query in search.queries)
