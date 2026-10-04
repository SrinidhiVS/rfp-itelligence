from src.search.cli import _vector_readiness
from src.search.embedding_models import VectorRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.index import IndexService
from src.search.models import IndexRecord, SearchQuery
from src.search.storage import CorpusStore
from src.search.vector_store import VectorStore
from src.search.vector_search import VectorSearch


def test_vector_search_preserves_bid_filter(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    vectors = provider.embed(["deadline Bid1", "warranty Bid2"])
    records = [VectorRecord("r1", vectors[0], "s1", "f1", "Bid1", "one.pdf", 1, {}, "deadline Bid1"), VectorRecord("r2", vectors[1], "s2", "f2", "Bid2", "two.pdf", 1, {}, "warranty Bid2")]
    store = VectorStore(tmp_path / "vectors.json")
    store.save(records, provider.config, {"s1": "f1", "s2": "f2"})
    result = VectorSearch(store, provider).search(SearchQuery(text="deadline Bid1", filters={"bid_id": ["Bid1"]}))
    assert result["found"] is True
    assert result["results"][0].record.bid_id == "Bid1"


def test_vector_readiness_requires_compatible_nonempty_index(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    store = VectorStore(tmp_path / "vectors.json")
    assert _vector_readiness(None)["available"] is False
    missing = _vector_readiness(VectorSearch(store, provider))
    assert missing["available"] is False and missing["actual_mode"] == "unavailable"
    store.save([VectorRecord("r1", provider.embed(["deadline"])[0], "s", "fp", "Bid1", "one.pdf", 1, {}, "deadline")], provider.config, {"s": "fp"})
    available = _vector_readiness(VectorSearch(store, provider))
    assert available["available"] is True and available["record_count"] == 1
    assert available["model_name"] == provider.config.model_name
    assert available["actual_mode"] == "indexed-vector" and available["diagnostics"] == []
    incompatible = _vector_readiness(VectorSearch(store, DeterministicEmbeddingProvider(16)))
    assert incompatible["available"] is False and incompatible["actual_mode"] == "unavailable" and incompatible["diagnostics"]


def test_vector_readiness_requires_active_corpus_identity_and_source_context(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    store = VectorStore(tmp_path / "vectors.json")
    corpus = [IndexRecord("r1", "c1", "s1", "fp1", "deadline Bid1", "Bid1", "one.pdf", 1, None, "rfp", None, None, {}),
              IndexRecord("r2", "c2", "s2", "fp2", "warranty Bid2", "Bid2", "two.pdf", 2, None, "rfp", None, None, {})]
    vectors = provider.embed([item.text for item in corpus])
    stored = [VectorRecord(item.record_id, vector, item.scope_id, item.content_fingerprint, item.bid_id, item.source_file, item.page_number, {}, item.text) for item, vector in zip(corpus, vectors)]
    store.save([stored[0], VectorRecord("foreign", vectors[1], "s2", "fp2", "Bid2", "two.pdf", 2, {}, corpus[1].text)], provider.config, {"s1": "fp1", "s2": "fp2"})
    stale = _vector_readiness(VectorSearch(store, provider), corpus)
    assert stale["available"] is False and stale["actual_mode"] == "unavailable" and stale["diagnostics"]
    store.save([stored[0], VectorRecord("r2", vectors[1], "s2", "fp2", "WrongBid", "wrong.pdf", 2, {}, corpus[1].text)], provider.config, {"s1": "fp1", "s2": "fp2"})
    assert _vector_readiness(VectorSearch(store, provider), corpus)["available"] is False
    store.save(stored, provider.config, {"s1": "fp1", "s2": "fp2"})
    assert _vector_readiness(VectorSearch(store, provider), corpus)["available"] is True


def test_vector_search_returns_section_and_content_kind(tmp_path):
    provider = DeterministicEmbeddingProvider(8)
    indexer = IndexService(CorpusStore(tmp_path / "corpus.json"))
    indexer.update({
        "bid_id": "Bid1",
        "source_manifest": [{"relative_path": "rfp.pdf"}],
        "chunks": [{
            "chunk_id": "chunk-1",
            "text": "submission deadline",
            "bid_id": "Bid1",
            "source_file": "rfp.pdf",
            "page_number": 4,
            "section_title": "Submission",
            "content_kind": "table",
            "source_locator": {"relative_path": "rfp.pdf", "page_number": 4, "table_id": "table-1"},
        }],
    })
    store = VectorStore(tmp_path / "vectors.json")
    store.build_from_records(indexer.records(), provider)

    result = VectorSearch(store, provider).search(SearchQuery(text="submission deadline"))
    evidence = result["results"][0].record

    assert evidence.section_title == "Submission"
    assert evidence.content_kind == "table"
    assert evidence.bid_id == "Bid1"
    assert evidence.source_file == "rfp.pdf"
    assert evidence.page_number == 4
    assert evidence.source_locator["table_id"] == "table-1"
