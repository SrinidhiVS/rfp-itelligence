"""Combine retrieval candidates, remove duplicates, and rerank evidence."""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
import math
import re

from .keyword import tokens
from .models import CandidateResult, RankedEvidence
from .diagnostics import source_completeness


def fuse(candidates: list[CandidateResult], top_k: int) -> list[RankedEvidence]:
    """Fuse method-specific ranked candidates with reciprocal-rank scoring.

    Args:
        candidates: Candidate records with retrieval method, score, and rank.
        top_k: Maximum number of unique record IDs to return.

    Returns:
        ``RankedEvidence`` objects ordered by fused score, with retrieval
        methods and source-completeness status attached.
    """
    scores: dict[str, float] = defaultdict(float)
    methods: dict[str, set[str]] = defaultdict(set)
    records = {}
    best_ranks: dict[tuple[str, str], int] = {}
    for candidate in candidates:
        methods[candidate.record_id].add(candidate.retrieval_method)
        records[candidate.record_id] = candidate.record
        key = (candidate.record_id, candidate.retrieval_method)
        best_ranks[key] = min(best_ranks.get(key, candidate.rank), candidate.rank)
    for (record_id, _), rank in best_ranks.items():
        scores[record_id] += 1.0 / (60 + rank)
    ordered = sorted(scores, key=lambda record_id: (-scores[record_id], record_id))[:top_k]
    return [RankedEvidence(record_id, rank, scores[record_id], records[record_id], sorted(methods[record_id]), source_completeness(records[record_id].diagnostic_ids)) for rank, record_id in enumerate(ordered, 1)]


def deduplicate(results: list[RankedEvidence]) -> list[RankedEvidence]:
    """Remove near-identical results from the same bid, file, and page.

    Args:
        results: Ranked evidence to inspect in existing rank order.

    Returns:
        A list retaining the first representative of each duplicate group.
        Retrieval-method labels from duplicate entries are merged into the
        retained representative.
    """
    selected: list[RankedEvidence] = []
    for result in results:
        duplicate = False
        normalized = " ".join(result.record.text.lower().split())
        for previous in selected:
            same_location = (previous.record.bid_id, previous.record.source_file, previous.record.page_number) == (result.record.bid_id, result.record.source_file, result.record.page_number)
            previous_text = " ".join(previous.record.text.lower().split())
            if same_location and (normalized == previous_text or SequenceMatcher(None, normalized, previous_text).ratio() >= 0.9):
                previous.retrieval_methods = sorted(set(previous.retrieval_methods) | set(result.retrieval_methods))
                duplicate = True
                break
        if not duplicate:
            selected.append(result)
    return selected


def rerank(results: list[RankedEvidence], query: str) -> list[RankedEvidence]:
    """Apply deterministic lexical, numeric, and requirement relevance boosts.

    Args:
        results: Evidence candidates to score; each candidate's score and rank
            are updated in place.
        query: Original user query used to derive relevance signals.

    Returns:
        The same evidence objects ordered by descending heuristic score, with
        ranks reassigned starting at 1.
    """
    query_terms = set(tokens(query))
    scored = []
    for result in results:
        text = result.record.text.lower()
        score = result.score + len(query_terms & set(tokens(text))) * 0.01
        identifiers = re.findall(r"\b[A-Z]{1,8}[-_][A-Z0-9-]*\d[A-Z0-9-]*\b", query, re.IGNORECASE)
        score += sum(0.25 for identifier in identifiers if identifier.lower() in set(tokens(text)))
        numeric_values = re.findall(r"\b\d+(?:\.\d+)?(?:%|gb|ghz|mhz|inch|inches|hours?|days?|mm|w|mp)?\b", text)
        requirement_phrases = ("must", "required", "minimum", "maximum", "at least", "up to", "shall", "include")
        factual_attributes = ("processor", "memory", "ram", "storage", "display", "resolution", "wireless", "ports", "battery", "operating system", "warranty", "delivery", "quantity", "duration", "payment", "model", "part")
        score += min(len(numeric_values), 8) * 0.008
        score += sum(0.012 for phrase in requirement_phrases if phrase in text)
        score += sum(0.018 for attribute in factual_attributes if attribute in text)
        deadline_query = any(term in query.lower() for term in ("deadline", "due date", "submission", "closing date"))
        current_intent = any(term in query.lower() for term in ("final", "current", "latest", "revised", "updated"))
        answer_phrases = ("new due date", "submission deadline", "solicitation due", "extended due date", "revised deadline", "extended to", "changed to", "revised to")
        if deadline_query:
            score += sum(0.12 for phrase in answer_phrases if phrase in text)
            if "following the solicitation due date" in text or "schedules, deadlines" in text:
                score -= 0.08
        if result.record.doc_type == "addendum":
            if any(phrase in text for phrase in ("new due date", "extended", "revised", "changed", "amend")) and deadline_query:
                score += 0.25 + (result.record.addendum_number or 0) * 0.005
        result.score = score
        scored.append((-score, result.record_id, result))
    scored.sort(key=lambda item: (item[0], item[1]))
    for rank, (_, _, result) in enumerate(scored, 1):
        result.rank = rank
    return [item[2] for item in scored]


class CrossEncoderReranker:
    """Lazily load a sentence-transformers cross-encoder for pair scoring.

    Args:
        model_name: Cross-encoder model identifier accepted by
            ``sentence_transformers.CrossEncoder``.
    """

    def __init__(self, model_name: str):
        """Store the model identifier and defer loading until first prediction."""
        self.model_name = model_name
        self.model = None

    def predict(self, pairs: list[tuple[str, str]]):
        """Score query/document text pairs, loading the model on first use.

        Args:
            pairs: Sequence of ``(query, document_text)`` string pairs.

        Returns:
            The score array returned by the loaded cross-encoder, normally one
            numeric score per input pair.
        """
        if self.model is None:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(self.model_name)
        return self.model.predict(pairs)


def model_rerank(results: list[RankedEvidence], query: str, model) -> list[RankedEvidence]:
    """Use model scores when valid, falling back to heuristic ranking.

    Args:
        results: Ranked evidence candidates.
        query: Query text paired with each candidate's document text.
        model: Optional object exposing ``predict(pairs)``; ``None`` disables
            model reranking.

    Returns:
        Ranked evidence ordered using model/heuristic scores. Invalid model
        output or scoring errors return the deterministic heuristic ranking.
    """
    fallback = rerank(results, query)
    if model is None or not fallback:
        return fallback
    shortlist = fallback[:10]
    try:
        scores = list(model.predict([(query, item.record.text) for item in shortlist]))
        if len(scores) != len(shortlist) or not all(math.isfinite(float(score)) for score in scores):
            return fallback
    except Exception:
        return fallback
    model_order = sorted(zip(scores, shortlist), key=lambda pair: (-float(pair[0]), pair[1].rank))
    if len(fallback) <= 2:
        for rank, (score, item) in enumerate(model_order, 1):
            item.rank = rank
            item.score = float(score)
        return [item for _, item in model_order]
    model_ranks = {item.record_id: rank for rank, (_, item) in enumerate(model_order, 1)}
    combined_ranks = {item.record_id: 3 * item.rank + model_ranks.get(item.record_id, item.rank) for item in fallback}
    ordered = sorted(fallback, key=lambda item: (combined_ranks[item.record_id], item.rank))
    for rank, item in enumerate(ordered, 1):
        item.score = 1.0 / (1 + combined_ranks[item.record_id])
        item.rank = rank
    return ordered
