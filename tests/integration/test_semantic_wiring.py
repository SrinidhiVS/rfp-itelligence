from src.agents.retrieval_agent import RetrievalAgent


def test_retrieval_agent_exposes_semantic_readiness_status():
    agent = RetrievalAgent(search_service=object())
    status = agent.status()
    assert "semantic_enabled" in status
    assert "semantic_diagnostic" in status