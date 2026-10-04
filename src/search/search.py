"""Retrieve and rank bid-document evidence for search queries."""

from __future__ import annotations

from dataclasses import replace
import os

from .keyword import keyword_candidates, tokens
from .models import CandidateResult, SearchQuery
from .query import expand, filter_records
from .ranking import CrossEncoderReranker, deduplicate, fuse, model_rerank
from .semantic import semantic_candidates
from .semantic import SemanticProvider
from .contracts import validate_result
from .authority import apply_requirement_authority


class SearchService:
    """Run filtered keyword, semantic, and optional vector retrieval.

    Args:
        records: Candidate ``IndexRecord`` objects available to this service.
        semantic_provider: Optional scorer used for semantic candidate search;
            a deterministic token scorer is created when omitted.
        vector_search: Optional vector index adapter implementing ``search``.
        reranker: Optional model exposing ``predict`` for query/text pairs.
        vector_diagnostic: Optional diagnostic to append to each result when
            vector retrieval is degraded or unavailable.
    """

    def __init__(self, records, semantic_provider: SemanticProvider | None = None, vector_search=None, reranker=None, vector_diagnostic: str | None = None):
        """Store records and initialize supplied/default retrieval components."""
        self.records = records
        self.semantic_provider = semantic_provider or SemanticProvider()
        self.vector_search = vector_search
        self.vector_diagnostic = vector_diagnostic
        model_name = os.getenv("RFP_RERANK_MODEL")
        self.reranker = reranker if reranker is not None else CrossEncoderReranker(model_name) if model_name else None

    def search(self, query: SearchQuery, configuration: str = "hybrid") -> dict:
        """Search the configured corpus and return ranked evidence.

        Args:
            query: Search text, filters, result limit, and query mode.
            configuration: Retrieval strategy: ``"keyword-only"``,
                ``"semantic-only"``, or ``"hybrid"``. Hybrid combines
                available lexical and semantic candidates.

        Returns:
            Mapping with ``query_variants`` (a ``QueryVariant``), ``results``
            (ranked ``RankedEvidence`` objects), ``total_candidates`` (int),
            ``found`` (bool), and ``diagnostics`` (list of diagnostic strings).
        """
        filtered = filter_records(self.records, query)
        excluded_ids = {record.record_id for record in self.records} - {record.record_id for record in filtered}
        identifiers = {term for term in tokens(query.text) if len(term) >= 3 and any(char.isdigit() for char in term)}
        vector_diagnostics = []

        def vector_matches(item):
            """Require every numeric query identifier in candidate text/bid ID."""
            return identifiers.issubset(set(tokens(item.record.text + " " + item.record.bid_id)))

        def eligible_vector_results(limit):
            """Expand vector top-k until enough filter-eligible results are found."""
            requested = limit
            previous_ids = set()
            while True:
                response = self.vector_search.search(replace(query, top_k=requested))
                eligible = [item for item in response["results"] if item.record_id not in excluded_ids and filter_records([item.record], query) and vector_matches(item)]
                seen_ids = {item.record_id for item in response["results"]}
                if len(eligible) >= limit or len(response["results"]) < requested or response["diagnostics"] or seen_ids == previous_ids:
                    return response, eligible[:limit]
                previous_ids = seen_ids
                requested *= 2

        if self.vector_search is not None and configuration == "semantic-only":
            response, response["results"] = eligible_vector_results(query.top_k)
            for rank, item in enumerate(response["results"], 1):
                item.rank = rank
            response["found"] = bool(response["results"])
            if response["results"] or response["diagnostics"]:
                return response
        variants = expand(query)
        internal_limit = 50
        previous_ids = set()
        while True:
            candidates = []
            for variant in variants.variants:
                if configuration in {"keyword-only", "hybrid"}:
                    candidates.extend(keyword_candidates(filtered, variant, internal_limit))
                if configuration in {"semantic-only", "hybrid"}:
                    candidates.extend(semantic_candidates(filtered, variant, internal_limit, self.semantic_provider))
            if self.vector_search is not None and configuration == "hybrid":
                vector_response, vector_results = eligible_vector_results(internal_limit)
                vector_diagnostics.extend(
                    diagnostic
                    for diagnostic in vector_response["diagnostics"]
                    if diagnostic != "no_supporting_evidence" and diagnostic not in vector_diagnostics
                )
                candidates.extend(
                    CandidateResult(item.record_id, "semantic", item.score, item.rank, item.record)
                    for item in vector_results
                )
            unique = deduplicate(fuse(candidates, len(candidates)))
            current_ids = {item.record_id for item in candidates}
            if len(unique) >= query.top_k or not candidates or current_ids == previous_ids:
                break
            if self.vector_search is None and internal_limit >= len(filtered):
                break
            previous_ids = current_ids
            internal_limit *= 2
        ranked = model_rerank(unique, query.text, self.reranker)
        ranked = apply_requirement_authority(ranked, query.text)
        results = ranked[:query.top_k]
        for result in results:
            validate_result(result)
        diagnostics = vector_diagnostics.copy()
        if self.vector_diagnostic and self.vector_diagnostic not in diagnostics:
            diagnostics.append(self.vector_diagnostic)
        if not results:
            diagnostics.append("no_filter_match" if query.filters and filtered == [] else "no_supporting_evidence")
        return {"query_variants": variants, "results": results, "total_candidates": len(candidates), "found": bool(results), "diagnostics": diagnostics}
