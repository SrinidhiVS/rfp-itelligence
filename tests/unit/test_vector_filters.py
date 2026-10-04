from src.search.embedding_models import VectorRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.models import SearchQuery
from src.search.vector_search import VectorSearch
from src.search.vector_store import VectorStore


def test_vector_search_applies_bid_doc_and_addendum_filters(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    vectors = provider.embed(["deadline", "deadline", "deadline", "deadline"])
    records = [
        VectorRecord("current", vectors[0], "s1", "f1", "Bid1", "addendum.pdf", 1, {}, "deadline", "addendum", 2, "2026-10-01", "current"),
        VectorRecord("wrong-bid", vectors[1], "s2", "f2", "Bid2", "addendum.pdf", 1, {}, "deadline", "addendum", 2, "2026-10-01", "current"),
        VectorRecord("wrong-addendum", vectors[2], "s3", "f3", "Bid1", "addendum.pdf", 1, {}, "deadline", "addendum", 3, "2026-10-01", "current"),
        VectorRecord("wrong-document", vectors[3], "s4", "f4", "Bid1", "rfp.pdf", 1, {}, "deadline", "rfp", 2, "2026-10-01", "current"),
    ]
    store = VectorStore(tmp_path / "vectors.json")
    store.save(records, provider.config, {"s1": "f1", "s2": "f2", "s3": "f3", "s4": "f4"})
    search = VectorSearch(store, provider)
    result = search.search(SearchQuery(text="deadline", filters={"bid_id": ["Bid1"], "doc_type": "addendum", "addendum_number": 2}))
    assert result["found"] is True
    assert [item.record_id for item in result["results"]] == ["current"]
    assert result["results"][0].record.doc_type == "addendum"

    no_match = search.search(SearchQuery(text="deadline", filters={"bid_id": ["Bid1"], "doc_type": "addendum", "addendum_number": 9}))
    assert no_match["found"] is False
    assert no_match["results"] == []
