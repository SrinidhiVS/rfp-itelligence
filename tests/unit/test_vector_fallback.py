from src.search.vector_store import VectorIndexError, VectorStore


def test_missing_vector_index_has_structured_error(tmp_path):
    store = VectorStore(tmp_path / "missing.json")
    try:
        store.load()
    except VectorIndexError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("missing vector index was accepted")


def test_search_keeps_keyword_results_when_chroma_is_missing(tmp_path):
    from src.search.embeddings import DeterministicEmbeddingProvider
    from src.search.models import IndexRecord, SearchQuery
    from src.search.search import SearchService
    from src.search.vector_search import VectorSearch

    record = IndexRecord(
        "r1", "r1", "Bid1:rfp.pdf", "fp", "submission deadline", "Bid1",
        "rfp.pdf", 1, None, "rfp", None, None, {"relative_path": "rfp.pdf", "page_number": 1},
    )
    vector_search = VectorSearch(VectorStore(tmp_path / "missing-chroma"), DeterministicEmbeddingProvider(8))

    service = SearchService([record], vector_search=vector_search)
    hybrid = service.search(SearchQuery("submission deadline"))
    assert hybrid["found"] is True
    assert any("missing" in diagnostic for diagnostic in hybrid["diagnostics"])

    result = service.search(SearchQuery("submission deadline"), configuration="keyword-only")

    assert result["found"] is True
    assert result["results"][0].record_id == "r1"
    assert result["results"][0].retrieval_methods == ["keyword"]
