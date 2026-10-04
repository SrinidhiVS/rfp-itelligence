from src.agents.graph import AnalysisWorkflow
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.state import WorkflowState


class EmptySearch:
    def search(self, query, configuration="hybrid"):
        return {"results": [], "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_workflow_retry_count_never_exceeds_limit():
    result = AnalysisWorkflow(RetrievalAgent(EmptySearch()), max_retries=2).invoke(WorkflowState(mode="extraction", goal="extract", bid_ids=["Bid1"], max_retries=2))
    assert result.retry_count <= 2
    assert all(attempt <= 2 for attempt in result.retry_attempts.values())
