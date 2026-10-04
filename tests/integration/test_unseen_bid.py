from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.state import WorkflowState


class EmptySearch:
    def search(self, query, configuration="hybrid"):
        return {"results": [], "diagnostics": ["no_filter_match"], "query_variants": {"variants": [query.text]}}


def test_unseen_bid_returns_structured_unavailable_output():
    result = AnalysisWorkflow(RetrievalAgent(EmptySearch())).invoke(WorkflowState(mode="extraction", goal="extract", bid_ids=["UnseenBid"]))
    field = result.final_output["fields"]["submission_deadline"]
    assert field["value"] is None
    assert field["status"] == "not_found"
    assert field["notes"] == "Not found in documents"
    assert result.diagnostics
