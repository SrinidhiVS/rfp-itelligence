from src.search.embedding_models import VectorRecord
from src.search.embeddings import DeterministicEmbeddingProvider
from src.search.keyword import keyword_candidates
from src.search.models import IndexRecord, RankedEvidence, SearchQuery
from src.search.query import expand
from src.search.ranking import CrossEncoderReranker, deduplicate, fuse
from src.search.search import SearchService
from src.search.semantic import SemanticProvider
from src.search.vector_search import VectorSearch
from src.search.vector_store import VectorStore


def record(record_id, text, bid_id="BID-123", page=1):
    return IndexRecord(record_id, record_id, bid_id, record_id, text, bid_id, f"{record_id}.pdf", page, None, "rfp", None, None, {"page_number": page})


def test_keyword_prefers_exact_identifiers_and_bid_metadata():
    records = [record("partial", "Model ZX-2100 is excluded"), record("exact", "Model ZX-210 is required")]
    assert keyword_candidates(records, "ZX-210")[0].record_id == "exact"
    assert [item.record_id for item in keyword_candidates([record("other", "warranty", "BID-999"), record("bid", "warranty")], "BID-123")] == ["bid"]


def test_complete_procurement_identifiers_lead_in_keyword_and_hybrid():
    for identifier in ("168884", "ZX-210", "PA-1209"):
        records = [record("prefix", f"model {identifier}9 extra terms"), record("exact", f"model {identifier}")]
        for configuration in ("keyword-only", "hybrid"):
            results = SearchService(records).search(SearchQuery(f"model {identifier}"), configuration)["results"]
            assert results[0].record_id == "exact"
        assert keyword_candidates(records, identifier)[0].record_id == "exact"
    bids = [record("wrong", "equipment", "1688849"), record("correct", "equipment", "168884")]
    assert keyword_candidates(bids, "168884")[0].record_id == "correct"


def test_partial_only_identifier_is_not_keyword_evidence():
    for exact, longer in (("ZX-210", "ZX-2100"), ("168884", "1688849"), ("PA-1209", "PA-12099")):
        response = SearchService([record("longer", f"Model {longer}")]).search(SearchQuery(exact), "keyword-only")
        assert not response["found"] and response["results"] == []
        assert response["diagnostics"] == ["no_supporting_evidence"]


def test_bm25_prefers_distinctive_terms_without_long_document_padding():
    records = [record("long", "coupler " * 60), record("short", "coupler specialized"), record("common", "coupler included")]
    ranked = keyword_candidates(records, "specialized coupler")
    assert ranked[0].record_id == "short"
    assert ranked[0].method_score > ranked[-1].method_score


def test_fusion_does_not_count_repeated_variants_twice():
    candidates = keyword_candidates([record("a", "warranty"), record("b", "warranty")], "warranty")
    fused = fuse(candidates + candidates, 5)
    assert len(fused) == 2
    assert fused[0].score == 1 / 61


def test_near_duplicate_excerpt_keeps_all_retrieval_methods():
    first = record("first", "warranty includes on-site support")
    second = record("second", first.text)
    first.source_file = second.source_file = "same.pdf"
    results = deduplicate([RankedEvidence("first", 1, 0.2, first, ["keyword"], "complete"),
                           RankedEvidence("second", 2, 0.1, second, ["semantic"], "complete")])
    assert len(results) == 1
    assert results[0].retrieval_methods == ["keyword", "semantic"]


def test_same_location_and_text_in_different_bids_remain_distinct():
    first = record("first", "warranty includes on-site support", "Bid1", page=3)
    second = record("second", first.text, "Bid2", page=3)
    first.source_file = second.source_file = "rfp.pdf"
    results = SearchService([first, second]).search(SearchQuery("warranty", top_k=2))["results"]
    assert {(item.record_id, item.record.bid_id) for item in results} == {("first", "Bid1"), ("second", "Bid2")}
    assert all(item.retrieval_methods == ["keyword", "semantic"] for item in results)


def test_duplicate_saturation_does_not_hide_distinct_51st_excerpt():
    duplicates = [record(f"chunk{index:03d}", "warranty warranty", page=1) for index in range(50)]
    for item in duplicates:
        item.source_file = "shared.pdf"
    distinct = record("unique", "warranty", page=2)
    response = SearchService([*duplicates, distinct]).search(SearchQuery("warranty", top_k=2), "keyword-only")
    assert len(response["results"]) == 2
    assert {item.record_id for item in response["results"]} & {item.record_id for item in duplicates}
    assert any(item.record_id == "unique" for item in response["results"])


def test_procurement_expansion_preserves_identifier_and_intent():
    variants = expand(SearchQuery("latest warranty for ZX-210", filters={"bid_id": "BID-123"})).variants
    assert any("support" in variant and "latest" in variant and "ZX-210" in variant for variant in variants)
    assert all("ZX-210" in variant for variant in variants)


def test_hybrid_retrieval_fuses_vectors_filters_and_citations(tmp_path):
    records = [record("exact", "Latest warranty for ZX-210 is two years", page=4), record("semantic", "Support coverage includes repairs", page=7), record("outside", "Latest warranty ZX-210", "BID-999")]
    provider = DeterministicEmbeddingProvider(8)
    vectors = provider.embed([item.text for item in records])
    store = VectorStore(tmp_path / "vectors.json")
    store.save([VectorRecord(item.record_id, vector, item.scope_id, item.content_fingerprint, item.bid_id, item.source_file, item.page_number, item.source_locator, item.text) for item, vector in zip(records, vectors)], provider.config, {item.scope_id: item.content_fingerprint for item in records})
    service = SearchService(records, vector_search=VectorSearch(store, provider))
    response = service.search(SearchQuery("latest warranty for ZX-210", {"bid_id": "BID-123"}))
    results = response["results"]
    assert {item.record_id for item in results} == {"exact", "semantic"}
    assert results[0].record_id == "exact"
    assert set(results[0].retrieval_methods) == {"keyword", "semantic"}
    assert all(item.record.bid_id == "BID-123" and item.record.source_file and item.record.page_number and item.record.text for item in results)
    assert any("support" in variant for variant in response["query_variants"].variants)


def test_model_reranks_combined_candidates_and_falls_back():
    records = [record("first", "warranty ZX-210"), record("second", "warranty and support")]

    class Model:
        def predict(self, pairs):
            return [10 if "support" in text else 0 for _, text in pairs]

    query = SearchQuery("warranty ZX-210")
    result = SearchService(records, reranker=Model()).search(query)["results"]
    assert result[0].record_id == "second"
    assert [item.rank for item in result] == [1, 2]

    class UnavailableModel:
        def predict(self, pairs):
            raise RuntimeError("model unavailable")

    fallback = SearchService(records, reranker=UnavailableModel()).search(query)["results"]
    assert fallback[0].record_id == "first"
    assert fallback[0].score >= fallback[1].score


def test_invalid_model_predictions_preserve_heuristic_citations_and_empty_filters():
    records = [record("first", "warranty ZX-210", page=2), record("second", "support ZX-210", page=3)]

    class InvalidModel:
        def __init__(self, scores):
            self.scores = scores

        def predict(self, pairs):
            return self.scores

    query = SearchQuery("warranty ZX-210", {"bid_id": "BID-123"})
    baseline = SearchService(records).search(query)["results"]
    for scores in ([0.5], [float("nan"), 1.0], [float("inf"), 1.0]):
        result = SearchService(records, reranker=InvalidModel(scores)).search(query)["results"]
        assert [item.record_id for item in result] == [item.record_id for item in baseline]
        assert all(item.record.source_file and item.record.page_number and item.record.text and item.retrieval_methods for item in result)
    absent = SearchService(records).search(SearchQuery("warranty", {"bid_id": "absent"}))
    assert absent["results"] == [] and absent["diagnostics"] == ["no_filter_match"]


def test_configured_cross_encoder_is_lazy_and_uses_original_query(monkeypatch):
    monkeypatch.setenv("RFP_RERANK_MODEL", "local-test-model")
    service = SearchService([record("first", "warranty requirement")])
    assert isinstance(service.reranker, CrossEncoderReranker)
    assert service.reranker.model is None
    pairs_seen = []

    def predict(model, pairs):
        pairs_seen.extend(pairs)
        return [1.0] * len(pairs)

    monkeypatch.setattr(CrossEncoderReranker, "predict", predict)
    service.search(SearchQuery("warranty"))
    assert pairs_seen and all(query == "warranty" for query, _ in pairs_seen)


def test_model_reranks_bounded_larger_candidate_set_without_dropping_evidence():
    records = [record(f"r{number}", "warranty " + "detail " * number) for number in range(20)]

    class Model:
        def __init__(self):
            self.pairs = []

        def predict(self, pairs):
            self.pairs = pairs
            return [-10.0 if index == 0 else 10.0 if index == 1 else 0.0 for index in range(len(pairs))]

    model = Model()
    response = SearchService(records, reranker=model).search(SearchQuery("warranty", top_k=20))
    assert 0 < len(model.pairs) <= 10
    assert response["results"][0].record_id != SearchService(records).search(SearchQuery("warranty"))["results"][0].record_id
    assert len({item.record_id for item in response["results"]}) == len(response["results"])
    assert all(response["results"][index].score >= response["results"][index + 1].score for index in range(len(response["results"]) - 1))


def test_vector_scores_are_not_compared_directly_and_incomplete_records_stay_excluded():
    records = [record("keyword", "warranty ZX-210"), record("vector", "unrelated")]
    records[1].diagnostic_ids = ["missing_source"]

    class VectorBackend:
        def search(self, query):
            return {"results": [type("Hit", (), {"record_id": "vector", "score": 9999, "rank": 1, "record": records[1]})()], "diagnostics": [], "found": True}

    service = SearchService(records, vector_search=VectorBackend())
    assert [item.record_id for item in service.search(SearchQuery("warranty ZX-210"))["results"]] == ["keyword"]
    assert [item.record_id for item in service.search(SearchQuery("warranty ZX-210"), configuration="semantic-only")["results"]] == ["keyword"]


def test_vector_eligibility_precedes_result_limit_in_both_modes():
    excluded = [record(f"excluded{index}", "opaque text") for index in range(51)]
    for item in excluded:
        item.diagnostic_ids = ["missing_source"]
    valid = record("valid", "opaque text from a complete source")
    hits = [RankedEvidence(item.record_id, rank, 1 / rank, item, ["semantic"], "complete")
            for rank, item in enumerate([*excluded, valid], 1)]

    class VectorBackend:
        def search(self, query):
            return {"results": hits[:query.top_k], "diagnostics": [], "found": True}

    service = SearchService([*excluded, valid], semantic_provider=SemanticProvider(lambda query, text: 0), vector_search=VectorBackend())
    for configuration in ("semantic-only", "hybrid"):
        response = service.search(SearchQuery("unrelated", top_k=1), configuration)
        assert [item.record_id for item in response["results"]] == ["valid"]
        assert response["results"][0].record.bid_id == "BID-123"


def test_unknown_exact_identifier_does_not_return_unrelated_vector_hit():
    records = [record("known", "existing model ZX-210")]

    class VectorBackend:
        def search(self, query):
            return {"results": [RankedEvidence("known", 1, 0.95, records[0], ["semantic"], "complete")], "diagnostics": [], "found": True}

    service = SearchService(records, vector_search=VectorBackend())
    for configuration in ("hybrid", "semantic-only"):
        response = service.search(SearchQuery("ZXQ-UNAVAILABLE-9981"), configuration)
        assert not response["found"] and response["results"] == []


def test_hybrid_keeps_distinct_producers_and_does_not_sort_raw_scores():
    records = [record("shared", "delivery requirement"), record("keyword", "delivery schedule"), record("vector", "opaque excerpt")]

    class VectorBackend:
        def search(self, query):
            hits = [type("Hit", (), {"record_id": item.record_id, "score": score, "rank": rank, "record": item})()
                    for rank, (item, score) in enumerate(((records[2], 9999), (records[0], 0.01)), 1)]
            return {"results": hits, "diagnostics": [], "found": True}

    semantic = SemanticProvider(lambda query, text: 1 if text == "delivery requirement" else 0)
    response = SearchService(records, semantic_provider=semantic, vector_search=VectorBackend()).search(SearchQuery("delivery", top_k=3))
    results = {item.record_id: item for item in response["results"]}
    assert set(results) == {"shared", "keyword", "vector"}
    assert results["shared"].retrieval_methods == ["keyword", "semantic"]
    assert results["keyword"].retrieval_methods == ["keyword"]
    assert results["vector"].retrieval_methods == ["semantic"]
    assert results["vector"].score < 9999
    assert results["shared"].rank < results["vector"].rank
    assert len({item.record_id for item in response["results"]}) == len(response["results"])