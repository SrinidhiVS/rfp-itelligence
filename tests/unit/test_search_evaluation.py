from copy import deepcopy
from pathlib import Path
import pytest
from types import SimpleNamespace

from src.search.evaluation import evaluate, load_cases, validate_cases
from src.search.evaluation import recall_at_k, reciprocal_rank
from src.search.models import IndexRecord, RankedEvidence
from src.search.search import SearchService


def test_retrieval_metrics() -> None:
    expected = {"a"}
    assert recall_at_k(expected, ["a", "b"], 5) == 1.0
    assert reciprocal_rank(expected, ["b", "a"]) == 0.5
    assert recall_at_k({"a", "b"}, ["b"], 5) == 0.5
    assert recall_at_k({"a", "b"}, ["b", "b", "a"], 2) == 0.5
    assert recall_at_k({"a", "b"}, ["b", "a"], 2) == 1.0
    assert recall_at_k({"a", "b"}, ["b", "a"], 1) == 0.5
    assert recall_at_k(set(), [], 5) == reciprocal_rank(set(), []) == 1.0


def test_publishable_case_contract_validates_annotations_and_no_match() -> None:
    item = IndexRecord("r1", "c1", "scope", "fp", "quoted source requirement", "Bid1", "rfp.pdf", 2, None, "rfp", None, None, {"relative_path": "rfp.pdf"})
    good = {"case_id": "C1", "query": "requirement", "bid_id": "Bid1", "expected_record_ids": ["r1"], "expected_passages": [{"record_id": "r1", "excerpt": "source requirement", "bid_id": "Bid1", "source_file": "rfp.pdf", "page_number": 2}]}
    no_match = {"case_id": "C2", "query": "unknown", "bid_id": "UnknownBid", "category": "not-found", "expected_record_ids": [], "expected_passages": []}
    validate_cases([good, no_match], [item])
    for invalid in ({**good, "case_id": ""}, {**good, "query": " "}, {**good, "expected_record_ids": ["r1", "r1"]}, {**good, "expected_passages": []}, {**no_match, "expected_passages": good["expected_passages"]}):
        with pytest.raises(ValueError):
            validate_cases([invalid], [item])
    with pytest.raises(ValueError, match="C1"):
        validate_cases([good, good], [item])


def test_case_validation_identifies_stale_quotes_sources_and_page_less_locators() -> None:
    record = IndexRecord("r", "c", "scope", "fp", "Original warranty clause", "Bid1", "page.html", None, None, "rfp", None, None, {"relative_path": "page.html", "section": "Warranty"})
    passage = {"record_id": "r", "excerpt": "warranty clause", "bid_id": "Bid1", "source_file": "page.html", "page_number": None, "source_locator": record.source_locator}
    case = {"case_id": "C12", "query": "warranty", "bid_id": "Bid1", "expected_record_ids": ["r"], "expected_passages": [passage]}
    validate_cases([case], [record])
    for key, value in (("record_id", "stale"), ("excerpt", "invented"), ("bid_id", "Bid2"), ("source_file", "other.html"), ("page_number", 3), ("source_locator", {"section": "Other"})):
        invalid = deepcopy(case)
        invalid["expected_passages"][0][key] = value
        with pytest.raises(ValueError, match="C12"):
            validate_cases([invalid], [record])
    missing_locator = deepcopy(case)
    del missing_locator["expected_passages"][0]["source_locator"]
    with pytest.raises(ValueError, match="C12"):
        validate_cases([missing_locator], [record])


def test_publishable_quotes_must_be_short_verbatim_source_excerpts() -> None:
    item = IndexRecord("r1", "c1", "scope", "fp", "warranty clause " + "additional details " * 60, "Bid1", "rfp.pdf", 1, None, "rfp", None, None, {})
    case = {"case_id": "C3", "query": "warranty", "bid_id": "Bid1", "category": "requirement", "expected_record_ids": ["r1"], "expected_passages": [{"record_id": "r1", "excerpt": "warranty clause", "bid_id": "Bid1", "source_file": "rfp.pdf", "page_number": 1}]}
    validate_cases([case], [item])
    for oversized in (item.text, item.text[:241]):
        invalid = deepcopy(case)
        invalid["expected_passages"][0]["excerpt"] = oversized
        with pytest.raises(ValueError, match="C3"):
            validate_cases([invalid], [item])


def test_no_match_cases_require_explicit_category_without_changing_metrics() -> None:
    cases = load_cases(Path("eval/cases.json"))
    no_match = [case for case in cases if case["case_id"] in {"C015", "C021"}]
    assert len(no_match) == 2
    validate_cases(no_match, [])
    mislabeled = deepcopy(no_match[0])
    mislabeled["category"] = "exact"
    with pytest.raises(ValueError, match="C015"):
        validate_cases([mislabeled], [])
    assert recall_at_k(set(), [], 5) == reciprocal_rank(set(), []) == 1.0


def test_multiple_expected_passages_and_empty_no_match_preserve_relevance() -> None:
    records = [IndexRecord(label, label, "scope", "fp", "warranty " + label, bid, label + ".pdf", 1, None, "rfp", None, None, {}) for label, bid in (("a", "Bid1"), ("b", "Bid2"))]
    case = {"case_id": "C1", "query": "warranty", "bid_id": "both", "expected_record_ids": ["a", "b"], "expected_passages": [{"record_id": item.record_id, "excerpt": "warranty", "bid_id": item.bid_id, "source_file": item.source_file, "page_number": 1} for item in records]}
    validate_cases([case, {"case_id": "C2", "query": "absent", "bid_id": "both", "category": "not-found", "expected_record_ids": [], "expected_passages": []}], records)
    assert recall_at_k(set(case["expected_record_ids"]), ["b"], 5) == 0.5
    assert reciprocal_rank(set(case["expected_record_ids"]), ["unrelated", "b"]) == 0.5


def test_evaluation_aggregates_fractional_recall_without_changing_mrr() -> None:
    class Service:
        def search(self, query, configuration="hybrid"):
            return {"results": [SimpleNamespace(record_id="b")] if query.text == "partial" else []}

    cases = [{"case_id": "C1", "query": "partial", "bid_id": "both", "expected_record_ids": ["a", "b"]},
             {"case_id": "C2", "query": "absent", "bid_id": "both", "expected_record_ids": []}]
    row = evaluate(Service(), cases, ["hybrid"], k=5)["configurations"][0]
    assert [case["recall_at_k"] for case in row["cases"]] == [0.5, 1.0]
    assert row["recall_at_k"] == 0.75
    assert row["relevant_at_k_percent"] == 75.0
    assert row["mrr"] == 1.0


def test_evaluation_reports_warm_query_duration_and_retains_existing_metrics(monkeypatch) -> None:
    ticks = iter([0, 2, 2, 3, 3, 9])
    monkeypatch.setattr("src.search.evaluation.perf_counter", lambda: next(ticks), raising=False)

    class Service:
        def search(self, query, configuration="hybrid"):
            return {"results": [SimpleNamespace(record_id="answer")] if query.text == "found" else []}

    cases = [{"case_id": "C1", "query": "found", "bid_id": "both", "expected_record_ids": ["answer"]},
             {"case_id": "C2", "query": "absent", "bid_id": "both", "expected_record_ids": ["answer"]}]
    report = evaluate(Service(), cases, ["hybrid"], warm_up=True)["configurations"][0]
    assert report["warm_up_seconds"] == 2
    assert [case["elapsed_seconds"] for case in report["cases"]] == [1, 6]
    assert report["under_5_seconds_percent"] == 50
    assert report["relevant_at_k_percent"] == 50
    assert report["recall_at_k"] == 0.5 and report["mrr"] == 0.5


def test_evaluation_empty_cases_has_zero_rates() -> None:
    report = evaluate(None, [], ["hybrid"], warm_up=True)["configurations"][0]
    assert report["cases"] == []
    assert report["recall_at_k"] == report["mrr"] == 0
    assert report["under_5_seconds_percent"] == report["relevant_at_k_percent"] == 0


def test_comparison_run_context_keeps_identical_cases_and_metric_fields() -> None:
    class Service:
        def search(self, query, configuration="hybrid"):
            return {"results": [SimpleNamespace(record_id="r1")]}

    cases = [{"case_id": "C1", "query": "warranty", "bid_id": "both", "expected_record_ids": ["r1"]}]
    context = {"corpus": {"corpus_id": "fixture"}, "vector_index": {"available": True}, "reranker": {"model_name": None, "status": "off"}}
    report = evaluate(Service(), cases, ["semantic-only", "hybrid"], k=5, run_context=context)
    assert report["run_context"]["case_count"] == 1
    assert report["run_context"]["k"] == 5
    assert report["run_context"]["configurations"] == ["semantic-only", "hybrid"]
    assert len(report["run_context"]["case_set_sha256"]) == 64
    assert report["run_context"]["evaluated_at"]
    assert report["run_context"]["corpus"] == context["corpus"]
    assert [row["configuration"] for row in report["configurations"]] == ["semantic-only", "hybrid"]
    assert all([case["case_id"] for case in row["cases"]] == ["C1"] and row["recall_at_k"] == row["mrr"] == 1 for row in report["configurations"])


def test_unavailable_or_failing_vectors_are_not_reported_as_measured() -> None:
    record = IndexRecord("r1", "c1", "scope", "fp", "warranty", "Bid1", "rfp.pdf", 1, None, "rfp", None, None, {})
    cases = [{"case_id": "C1", "query": "warranty", "bid_id": "Bid1", "expected_record_ids": ["r1"]}]
    missing = evaluate(SearchService([record]), cases, ["semantic-only", "hybrid"], require_vectors=True, vector_status={"available": False, "diagnostics": ["index missing"]})
    assert all(row["available"] is False and "recall_at_k" not in row and "mrr" not in row for row in missing["configurations"])
    assert missing["configurations"][0]["actual_mode"] == "unavailable"
    assert missing["configurations"][1]["actual_mode"] == "lexical-fallback"

    class FailingBackend:
        def search(self, query):
            return {"results": [], "found": False, "diagnostics": ["embedding failed during query"]}

    failed = evaluate(SearchService([record], vector_search=FailingBackend()), cases, ["semantic-only", "hybrid"], require_vectors=True, vector_status={"available": True, "diagnostics": []})
    assert all(row["available"] is False and "recall_at_k" not in row and "mrr" not in row for row in failed["configurations"])
    assert all("embedding failed" in row["diagnostics"][0] for row in failed["configurations"])

    class WorkingBackend:
        def search(self, query):
            return {"results": [RankedEvidence("r1", 1, 0.8, record, ["semantic"], "complete")], "found": True, "diagnostics": []}

    measured = evaluate(SearchService([record], vector_search=WorkingBackend()), cases, ["semantic-only", "hybrid"], require_vectors=True, vector_status={"available": True, "diagnostics": []})
    assert [row["actual_mode"] for row in measured["configurations"]] == ["indexed-vector", "indexed-hybrid"]
    assert all(row["available"] and row["recall_at_k"] == row["mrr"] == 1 and row["cases"][0]["case_id"] == "C1" for row in measured["configurations"])


def test_failed_configured_reranker_is_disclosed_as_heuristic_fallback() -> None:
    record = IndexRecord("r1", "c1", "scope", "fp", "warranty", "Bid1", "rfp.pdf", 1, None, "rfp", None, None, {})

    class WorkingBackend:
        def search(self, query):
            return {"results": [RankedEvidence("r1", 1, 0.8, record, ["semantic"], "complete")], "found": True, "diagnostics": []}

    class FailingReranker:
        def predict(self, pairs):
            raise RuntimeError("prediction unavailable")

    cases = [{"case_id": "C1", "query": "warranty", "bid_id": "Bid1", "expected_record_ids": ["r1"]}]
    report = evaluate(SearchService([record], vector_search=WorkingBackend(), reranker=FailingReranker()), cases, ["hybrid"], require_vectors=True, vector_status={"available": True, "diagnostics": []})
    row = report["configurations"][0]
    assert row["available"] and row["mrr"] == 1
    assert row["reranker_status"] == "heuristic-fallback"
    assert "prediction unavailable" in row["diagnostics"]
    semantic = evaluate(SearchService([record], vector_search=WorkingBackend(), reranker=FailingReranker()), cases, ["semantic-only"], require_vectors=True, vector_status={"available": True, "diagnostics": []})
    assert semantic["configurations"][0]["reranker_status"] == "not-used"
