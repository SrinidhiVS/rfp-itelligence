"""Tokenize text and retrieve records with BM25-style keyword scoring."""

from __future__ import annotations

from collections import Counter
import math
import re

from .models import CandidateResult, IndexRecord


def tokens(text: str) -> list[str]:
    """Extract lowercase alphanumeric tokens, retaining internal separators.

    Args:
        text: Input query or document text.

    Returns:
        Tokens matching letters/digits with optional internal hyphen or
        underscore groups, in source order.
    """
    return re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.lower())


def keyword_candidates(records: list[IndexRecord], query: str, limit: int = 50) -> list[CandidateResult]:
    """Rank records using BM25-style lexical relevance and identifier matches.

    Args:
        records: Index records to search.
        query: Text whose tokens are matched against passage text and bid ID.
        limit: Maximum candidates to return; defaults to 50.

    Returns:
        Positive-scoring ``CandidateResult`` objects ordered by descending
        score and stable record ID, with one-based ranks. Numeric identifiers
        of at least three characters must all occur in a candidate record.
    """
    query_tokens = set(tokens(query))
    if not query_tokens or not records:
        return []
    documents = [Counter(tokens(record.text + " " + record.bid_id)) for record in records]
    lengths = [sum(document.values()) for document in documents]
    average_length = sum(lengths) / len(lengths) or 1
    frequencies = Counter(token for document in documents for token in query_tokens if document[token])
    scored: list[tuple[float, IndexRecord]] = []
    identifiers = [token for token in query_tokens if any(char.isdigit() for char in token) and len(token) >= 3]
    for record, document, length in zip(records, documents, lengths):
        if any(identifier not in document for identifier in identifiers):
            continue
        score = 0.0
        for token in query_tokens:
            frequency = document[token]
            if frequency:
                idf = math.log(1 + (len(records) - frequencies[token] + 0.5) / (frequencies[token] + 0.5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average_length))
        score += 3.0 * sum(identifier in document for identifier in identifiers)
        if query.lower().strip() in record.text.lower():
            score += 1.0
        if score:
            scored.append((score, record))
    scored.sort(key=lambda item: (-item[0], item[1].record_id))
    return [CandidateResult(record.record_id, "keyword", score, rank, record) for rank, (score, record) in enumerate(scored[:limit], 1)]
