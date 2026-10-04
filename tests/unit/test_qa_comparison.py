from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.state import WorkflowState


class Search:
    def search(self, query, configuration="hybrid"):
        results = []
        for index, bid in enumerate(("Bid1", "Bid2")):
            results.append({"record_id": bid, "rank": index + 1, "score": 1.0, "retrieval_methods": ["keyword"], "source_completeness": "complete", "authority_status": "current", "record": {"record_id": bid, "source_file": bid + ".html", "page_number": 1, "bid_id": bid, "source_locator": {}, "text": bid + " warranty requirement"}})
        return {"results": results, "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_comparison_groups_evidence_by_bid():
    state = AnalysisWorkflow(RetrievalAgent(Search())).invoke(WorkflowState(mode="qa", goal="compare warranties", bid_ids=["Bid1", "Bid2"]))
    assert set(state.final_output["evidence_by_bid"]) == {"Bid1", "Bid2"}
