import pytest

from src.search.contracts import validate_result
from src.search.models import IndexRecord, RankedEvidence
from src.search.query import make_query
from src.search.search import SearchService
from src.search.models import SearchQuery
from src.search.embedding_models import VectorRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.vector_search import VectorSearch
from src.search.vector_store import VectorStore


def test_ranked_evidence_contract_requires_authority_and_source_traceability() -> None:
    record = IndexRecord("r", "c", "Bid1:file", "fp", "text", "Bid1", "file.pdf", 1, None, "rfp", None, None, {"relative_path": "file.pdf"}, [])
    result = RankedEvidence("r", 1, 0.8, record, ["hybrid"], "complete", "current", None)
    validate_result(result)


def test_search_query_contract() -> None:
    query = make_query({"text": " warranty ", "mode": "answer"})
    assert (query.text, query.top_k, query.mode, query.include_incomplete) == ("warranty", 5, "answer", False)
    for request in ({"text": " "}, {"text": "warranty", "top_k": 0}, {"text": "warranty", "mode": "unknown"}):
        with pytest.raises(ValueError):
            make_query(request)


def test_result_contract_accepts_missing_page_but_rejects_invalid_rank_and_authority() -> None:
    record = IndexRecord("r", "c", "scope", "fp", "original text", "Bid1", "source.html", None, None, "rfp", None, None, {"relative_path": "source.html"})
    result = RankedEvidence("r", 1, 0.8, record, ["keyword", "semantic"], "complete", "supporting", None)
    validate_result(result)
    assert result.record.text == "original text" and result.record.page_number is None
    for rank, status in ((0, "supporting"), (1, "invalid")):
        with pytest.raises(ValueError):
            validate_result(RankedEvidence("r", rank, 0.8, record, ["keyword"], "complete", status))
    record.source_file = ""
    with pytest.raises(ValueError):
        validate_result(result)


def test_hybrid_result_envelope_retains_vector_only_citation() -> None:
    shared = IndexRecord("shared", "c1", "scope", "fp", "warranty", "Bid1", "shared.pdf", 3, None, "rfp", None, None, {"page_number": 3})
    vector = IndexRecord("vector", "c2", "scope", "fp", "support coverage", "Bid1", "source.html", None, None, "rfp", None, None, {"relative_path": "source.html"})

    class VectorBackend:
        def search(self, query):
            return {"results": [RankedEvidence(item.record_id, rank, 0.9, item, ["semantic"], "complete") for rank, item in enumerate((shared, vector), 1)], "found": True, "diagnostics": []}

    response = SearchService([shared], vector_search=VectorBackend()).search(SearchQuery("warranty", top_k=2))
    assert response["found"] and response["diagnostics"] == []
    assert response["query_variants"].original == "warranty"
    assert response["total_candidates"] > len(response["results"])
    assert len(response["results"]) == 2
    by_id = {item.record_id: item for item in response["results"]}
    assert by_id["shared"].retrieval_methods == ["keyword", "semantic"]
    assert by_id["vector"].record.source_file == "source.html"
    assert by_id["vector"].record.page_number is None
    assert by_id["vector"].record.text == "support coverage"
    assert by_id["vector"].record.source_locator == {"relative_path": "source.html"}


def test_chroma_search_retains_cited_evidence_contract(tmp_path) -> None:
    provider = DeterministicEmbeddingProvider(8)
    record = VectorRecord(
        "r1", provider.embed(["submission deadline"])[0], "Bid1:rfp.pdf", "fp", "Bid1",
        "rfp.pdf", 3, {"relative_path": "rfp.pdf", "page_number": 3}, "submission deadline",
        "rfp", None, None, "current", section_title="Submission", content_kind="text",
    )
    store = VectorStore(tmp_path / "chroma")
    store.save([record], provider.config, {record.scope_id: "fp"})

    response = VectorSearch(store, provider).search(SearchQuery("submission deadline"))
    evidence = response["results"][0]

    validate_result(evidence)
    assert evidence.record.source_file == "rfp.pdf"
    assert evidence.record.page_number == 3
    assert evidence.record.source_locator["relative_path"] == "rfp.pdf"
    assert evidence.authority_status == "current"
