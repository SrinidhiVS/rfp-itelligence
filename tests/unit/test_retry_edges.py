from src.agents.state import WorkflowState


def test_retry_budget_is_bounded():
    state = WorkflowState(mode="extraction", goal="extract", max_retries=0)
    assert state.max_retries == 0
    assert state.retry_count <= state.max_retries
