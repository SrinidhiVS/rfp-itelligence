from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.state import WorkflowState


class Search:
    def search(self, query, configuration="hybrid"):
        return {"results": [], "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_trace_reference_matches_persisted_run_trace():
    result = AnalysisWorkflow(RetrievalAgent(Search())).invoke(WorkflowState(mode="qa", goal="unknown", bid_ids=["Bid1"]))
    assert result.trace_reference == result.trace.trace_id
    assert result.final_output["answer"] == "Not found in documents"
