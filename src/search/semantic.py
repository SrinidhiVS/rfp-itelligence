"""Provide lightweight semantic-style scoring and candidate retrieval."""

from __future__ import annotations

from collections import Counter
import math
from typing import Callable

from .keyword import tokens
from .models import CandidateResult, IndexRecord


ScoreFunction = Callable[[str, str], float]


class SemanticProvider:
    """Provide finite semantic-candidate scores without requiring a model.

    Args:
        scorer: Optional callable receiving query and document strings and
            returning a numeric similarity score. Defaults to token cosine
            similarity.
    """

    def __init__(self, scorer: ScoreFunction | None = None):
        """Use the supplied scoring callable or default token cosine scoring."""
        self._scorer = scorer or self._token_cosine

    def score(self, query: str, text: str) -> float:
        """Return a finite similarity score for a query and document string.

        Args:
            query: User query text.
            text: Candidate document text.

        Returns:
            The scorer's finite value as a float, or ``0.0`` for non-finite
            results.
        """
        score = float(self._scorer(query, text))
        if not math.isfinite(score):
            return 0.0
        return score

    @staticmethod
    def _token_cosine(query: str, text: str) -> float:
        """Compute cosine similarity over token-frequency vectors.

        Args:
            query: Text supplying the first token-frequency vector.
            text: Text supplying the second token-frequency vector.

        Returns:
            Cosine similarity in the range 0 to 1, or 0 when either text has
            no tokens.
        """
        query_counts = Counter(tokens(query))
        text_counts = Counter(tokens(text))
        if not query_counts or not text_counts:
            return 0.0

        shared = query_counts.keys() & text_counts.keys()
        dot_product = sum(query_counts[token] * text_counts[token] for token in shared)
        query_norm = math.sqrt(sum(count * count for count in query_counts.values()))
        text_norm = math.sqrt(sum(count * count for count in text_counts.values()))
        return dot_product / (query_norm * text_norm) if query_norm and text_norm else 0.0


def semantic_candidates(
    records: list[IndexRecord],
    query: str,
    limit: int = 50,
    provider: SemanticProvider | None = None,
) -> list[CandidateResult]:
    """Score indexed records and return the best positive semantic matches.

    Args:
        records: Candidate index records.
        query: Query variant used for similarity scoring.
        limit: Maximum number of results; non-positive values return no results.
        provider: Optional semantic scorer; a default token scorer is created
            when omitted.

    Returns:
        Positive-scoring ``CandidateResult`` objects, ordered by descending
        score and then record ID, with one-based ranks.
    """
    if limit <= 0 or not records:
        return []

    scorer = provider or SemanticProvider()
    scored = [
        (scorer.score(query, record.text), record)
        for record in records
    ]
    scored = [(score, record) for score, record in scored if score > 0]
    scored.sort(key=lambda item: (-item[0], item[1].record_id))
    return [
        CandidateResult(record.record_id, "semantic", score, rank, record)
        for rank, (score, record) in enumerate(scored[:limit], 1)
    ]