from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.state import WorkflowState


class Search:
    def search(self, query, configuration="hybrid"):
        return {"results": [{"record_id": "r1", "rank": 1, "score": 1.0, "retrieval_methods": ["keyword"], "source_completeness": "complete", "authority_status": "current", "record": {"record_id": "r1", "source_file": "rfp.html", "page_number": 1, "bid_id": "Bid1", "source_locator": {"secret": "hidden"}, "text": "deadline: October 20"}}], "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_api_facing_output_keeps_citation_metadata_without_raw_evidence_payload():
    result = AnalysisWorkflow(RetrievalAgent(Search())).invoke(WorkflowState(mode="qa", goal="deadline", bid_ids=["Bid1"]))
    assert "retrieved_evidence" not in result.final_output
    assert result.final_output["citations"][0]["file"] == "rfp.html"
    assert "text" not in result.final_output["citations"][0]
