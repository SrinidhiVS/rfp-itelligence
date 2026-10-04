from src.agents.retrieval_agent import RetrievalAgent


class Search:
    def search(self, query, configuration="hybrid"):
        return {"results": [], "diagnostics": [], "query_variants": {"variants": [query.text]}}


def test_retrieval_adapter_preserves_bid_filter_and_query_variants():
    result = RetrievalAgent(Search()).search("deadline", ["Bid1"], top_k=5)
    assert result["query_variants"]["variants"] == ["deadline"]
    assert result["results"] == []
