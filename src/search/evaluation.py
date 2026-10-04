"""Validate labeled retrieval cases and report search quality metrics."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from .models import IndexRecord

MAX_EXPECTED_EXCERPT_CHARS = 240


def validate_cases(cases: list[dict], records: list[IndexRecord]) -> None:
    """Validate expected evidence IDs and citations against indexed records.

    Args:
        cases: Evaluation case mappings with unique IDs, query, bid ID,
            expected record IDs, and matching source excerpts.
        records: Indexed corpus records used to validate each expected passage.

    Returns:
        ``None`` when every case and expected citation matches the corpus.

    Raises:
        ValueError: If case identifiers, query, expected IDs, excerpts, bid
            IDs, source files, pages, or source locators are invalid.
    """
    by_id = {record.record_id: record for record in records}
    bid_ids = {record.bid_id for record in records}
    seen_cases: set[str] = set()
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen_cases:
            raise ValueError(f"{case_id or '<missing>'}: case_id must be nonempty and unique")
        seen_cases.add(case_id)
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"{case_id}: query must be nonblank")
        expected_ids = case.get("expected_record_ids")
        passages = case.get("expected_passages")
        if not isinstance(expected_ids, list) or not all(isinstance(item, str) and item for item in expected_ids) or len(expected_ids) != len(set(expected_ids)):
            raise ValueError(f"{case_id}: expected_record_ids must be unique nonempty IDs")
        if not isinstance(passages, list) or any(not isinstance(item, dict) for item in passages):
            raise ValueError(f"{case_id}: expected_passages must be a list")
        if not expected_ids and case.get("category") != "not-found":
            raise ValueError(f"{case_id}: empty expected passages must be labeled not-found")
        if expected_ids and case.get("category") == "not-found":
            raise ValueError(f"{case_id}: not-found cases cannot have expected passages")
        bid_id = case.get("bid_id")
        if not isinstance(bid_id, str) or not bid_id or (expected_ids and bid_id != "both" and bid_id not in bid_ids):
            raise ValueError(f"{case_id}: bid_id does not match the indexed corpus")
        passage_ids = [item.get("record_id") for item in passages]
        if len(passage_ids) != len(expected_ids) or set(passage_ids) != set(expected_ids):
            raise ValueError(f"{case_id}: expected_passages must match expected_record_ids exactly")
        for passage in passages:
            record_id = passage["record_id"]
            record = by_id.get(record_id)
            if record is None:
                raise ValueError(f"{case_id}: missing indexed record {record_id}")
            excerpt = passage.get("excerpt")
            if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in record.text:
                raise ValueError(f"{case_id}: excerpt does not match indexed record {record_id}")
            if len(excerpt) > MAX_EXPECTED_EXCERPT_CHARS:
                raise ValueError(f"{case_id}: excerpt exceeds {MAX_EXPECTED_EXCERPT_CHARS} characters for {record_id}")
            if record.bid_id != passage.get("bid_id") or (bid_id != "both" and record.bid_id != bid_id):
                raise ValueError(f"{case_id}: bid mismatch for {record_id}")
            if not record.source_file or record.source_file != passage.get("source_file"):
                raise ValueError(f"{case_id}: source_file mismatch for {record_id}")
            if "page_number" not in passage or passage["page_number"] != record.page_number:
                raise ValueError(f"{case_id}: page_number mismatch for {record_id}")
            if (record.page_number is None and record.source_locator and passage.get("source_locator") != record.source_locator) or ("source_locator" in passage and passage["source_locator"] != record.source_locator):
                raise ValueError(f"{case_id}: source_locator mismatch for {record_id}")


def reciprocal_rank(expected: set[str], returned: list[str]) -> float:
    """Compute reciprocal rank of the first returned relevant record.

    Args:
        expected: Set of relevant record IDs.
        returned: Record IDs in retrieval order.

    Returns:
        ``1 / rank`` for the first relevant result, or 0. Empty expectations
        score 1 only when no results were returned.
    """
    if not expected:
        return 1.0 if not returned else 0.0
    for index, record_id in enumerate(returned, 1):
        if record_id in expected:
            return 1.0 / index
    return 0.0


def recall_at_k(expected: set[str], returned: list[str], k: int) -> float:
    """Compute the fraction of relevant records present in the first k hits.

    Args:
        expected: Set of relevant record IDs.
        returned: Record IDs in retrieval order.
        k: Number of top results to inspect.

    Returns:
        Recall in the range 0 to 1. Empty expectations score 1 only when no
        results were returned.
    """
    if not expected:
        return 1.0 if not returned else 0.0
    return len(expected.intersection(returned[:k])) / len(expected)


def load_cases(path: Path) -> list[dict]:
    """Read a JSON evaluation case array from disk.

    Args:
        path: UTF-8 JSON file containing the case list.

    Returns:
        Parsed list of case dictionaries.

    Raises:
        OSError: If the file cannot be read.
        json.JSONDecodeError: If the file does not contain valid JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


class _ObservedVectorSearch:
    """Record vector-backend diagnostics while preserving its response."""

    def __init__(self, backend):
        """Wrap a vector search backend for evaluation instrumentation.

        Args:
            backend: Object exposing ``search(query)`` and returning a mapping
                with optional diagnostic strings.
        """
        self.backend = backend
        self.diagnostics: list[str] = []

    def search(self, query):
        """Forward a query and retain non-empty-result diagnostics.

        Args:
            query: Query object accepted by the wrapped backend.

        Returns:
            The backend's response mapping unchanged.
        """
        response = self.backend.search(query)
        self.diagnostics.extend(message for message in response.get("diagnostics", []) if message != "no_supporting_evidence")
        return response


class _ObservedReranker:
    """Track reranker calls and invalid-output or runtime diagnostics."""

    def __init__(self, backend):
        """Wrap a model reranker for evaluation instrumentation.

        Args:
            backend: Object exposing ``predict(pairs)``.
        """
        self.backend = backend
        self.diagnostic: str | None = None
        self.calls = 0

    def predict(self, pairs):
        """Forward query/document pairs and record malformed scores or errors.

        Args:
            pairs: Sequence of string pairs expected by the wrapped model.

        Returns:
            A list of model scores. Invalid scores are returned but recorded as
            a diagnostic; backend exceptions are recorded and re-raised.
        """
        self.calls += 1
        try:
            scores = list(self.backend.predict(pairs))
            if len(scores) != len(pairs) or not all(math.isfinite(float(score)) for score in scores):
                self.diagnostic = "reranker returned invalid scores"
            return scores
        except Exception as exc:
            self.diagnostic = str(exc)
            raise


def evaluate(search_service, cases: list[dict], configurations: list[str], k: int = 5, warm_up: bool = False, run_context: dict | None = None, require_vectors: bool = False, vector_status: dict | None = None) -> dict:
    """Run labeled cases across retrieval configurations and aggregate metrics.

    Args:
        search_service: Mutable service exposing ``search`` and optional
            ``vector_search``/``reranker`` dependencies.
        cases: Validated cases containing query, bid ID, and expected record IDs.
        configurations: Retrieval configuration names passed to ``search``.
        k: Cutoff for recall and returned evidence; defaults to 5.
        warm_up: Whether to time one initial query per configuration.
        run_context: Optional metadata merged into generated run metadata.
        require_vectors: Whether a usable indexed-vector backend is mandatory.
        vector_status: Optional readiness mapping; ``available`` must be true
            when vector search is required.

    Returns:
        Report mapping with ``k``, per-configuration case metrics and
        availability, plus ``run_context`` containing timestamp, case count,
        case-set SHA-256, configurations, and cutoff. Metrics include recall,
        MRR, latency percentages, and optional warm-up time.
    """
    context = dict(run_context or {})
    context.update({
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "case_set_sha256": sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        "configurations": list(configurations),
        "k": k,
    })
    reports = []
    for configuration in configurations:
        backend = getattr(search_service, "vector_search", None) if require_vectors else None
        if require_vectors and (backend is None or not (vector_status or {}).get("available")):
            reports.append({"configuration": configuration, "available": False, "actual_mode": "unavailable" if configuration == "semantic-only" else "lexical-fallback", "reranker_status": "unmeasured", "diagnostics": (vector_status or {}).get("diagnostics") or ["vector search unavailable"], "cases": []})
            continue
        observer = _ObservedVectorSearch(backend) if require_vectors else None
        if observer is not None:
            search_service.vector_search = observer
        reranker = getattr(search_service, "reranker", None)
        reranker_observer = _ObservedReranker(reranker) if reranker is not None else None
        if reranker_observer is not None:
            search_service.reranker = reranker_observer
        case_results = []
        warm_up_seconds = None
        try:
            if warm_up and cases:
                from .query import make_query
                first = cases[0]
                filters = {} if first.get("bid_id") in (None, "both") else {"bid_id": first["bid_id"]}
                query = make_query({"text": first["query"], "filters": filters, "top_k": k})
                start = perf_counter()
                search_service.search(query, configuration=configuration)
                warm_up_seconds = perf_counter() - start
            for case in cases:
                from .query import make_query
                filters = {} if case.get("bid_id") in (None, "both") else {"bid_id": case["bid_id"]}
                query = make_query({"text": case["query"], "filters": filters, "top_k": k})
                start = perf_counter()
                response = search_service.search(query, configuration=configuration)
                elapsed_seconds = perf_counter() - start
                returned = [item.record_id for item in response["results"]]
                expected = set(case["expected_record_ids"])
                case_results.append({"case_id": case["case_id"], "expected_record_ids": list(expected), "returned_record_ids": returned, "recall_at_k": recall_at_k(expected, returned, k), "reciprocal_rank": reciprocal_rank(expected, returned), "elapsed_seconds": elapsed_seconds})
        finally:
            if observer is not None:
                search_service.vector_search = backend
            if reranker_observer is not None:
                search_service.reranker = reranker
        if observer is not None and observer.diagnostics:
            reports.append({"configuration": configuration, "available": False, "actual_mode": "unavailable" if configuration == "semantic-only" else "lexical-fallback", "reranker_status": "unmeasured", "diagnostics": observer.diagnostics, "cases": []})
            continue
        recall = sum(item["recall_at_k"] for item in case_results) / len(case_results) if case_results else 0
        reranker_status = "heuristic-fallback" if reranker_observer is not None and reranker_observer.diagnostic else "model" if reranker_observer is not None and reranker_observer.calls else "not-used" if reranker_observer is not None else "heuristic"
        reports.append({"configuration": configuration, "available": True, "actual_mode": ("indexed-vector" if configuration == "semantic-only" else "indexed-hybrid") if require_vectors else "unspecified", "reranker_status": reranker_status, "diagnostics": [reranker_observer.diagnostic] if reranker_status == "heuristic-fallback" else [], "cases": case_results, "recall_at_k": recall, "mrr": sum(item["reciprocal_rank"] for item in case_results) / len(case_results) if case_results else 0, "relevant_at_k_percent": 100 * recall, "under_5_seconds_percent": 100 * sum(item["elapsed_seconds"] < 5 for item in case_results) / len(case_results) if case_results else 0, "warm_up_seconds": warm_up_seconds})
    return {"k": k, "configurations": reports, "run_context": context}
