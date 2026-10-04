"""Validate search requests, expand query terms, and filter indexed records."""

from __future__ import annotations

import re

from .contracts import validate_query_request
from .models import IndexRecord, QueryVariant, SearchQuery

TERM_EXPANSIONS = {
    "deadline": ["due date", "submission deadline", "closing date"],
    "due date": ["deadline", "submission deadline", "closing date"],
    "submission deadline": ["deadline", "due date", "closing date"],
    "closing date": ["deadline", "due date", "submission deadline"],
    "delivery": ["shipping", "fulfillment"],
    "shipping": ["delivery", "fulfillment"],
    "warranty": ["support", "coverage"],
    "support": ["warranty", "maintenance"],
    "pricing": ["cost", "price"],
    "price": ["pricing", "cost"],
    "quantity": ["units", "amount"],
    "specifications": ["requirements", "technical requirements"],
    "requirements": ["specifications", "technical requirements"],
    "proposal": ["bid", "submission"],
    "evaluation": ["scoring", "selection"],
}

INTENT_MODIFIERS = ("final", "current", "latest", "revised", "updated", "extended", "new")
IDENTIFIER_PATTERN = re.compile(r"\b[A-Z]{1,8}[-_][A-Z0-9-]*\d[A-Z0-9-]*\b|\b(?:model|part|solicitation|bid|rfp)\s*#?\s*[A-Z0-9][A-Z0-9-]*\b", re.IGNORECASE)
ADDENDUM_PATTERN = re.compile(r"\b(?:addendum|amendment)\s*#?\s*\d+\b", re.IGNORECASE)


def make_query(request: dict) -> SearchQuery:
    """Validate a request mapping and normalize it into a ``SearchQuery``.

    Args:
        request: Mapping containing required ``text`` and optional ``filters``,
            ``top_k``, ``mode``, and ``include_incomplete`` values.

    Returns:
        A ``SearchQuery`` with trimmed text, a default limit of 5, search mode
        by default, and a boolean incomplete-evidence flag.

    Raises:
        ValueError: If request validation rejects the supplied values.
    """
    validate_query_request(request)
    return SearchQuery(str(request["text"]).strip(), request.get("filters", {}), int(request.get("top_k", 5)), request.get("mode", "search"), bool(request.get("include_incomplete", False)))


def expand(query: SearchQuery) -> QueryVariant:
    """Generate vocabulary variants while retaining the original query.

    Args:
        query: Validated search query to expand.

    Returns:
        ``QueryVariant`` containing the original text, unique replacement
        variants, and the generated expansion terms. Identifier and addendum
        tokens are retained when expanding date-related intent.
    """
    variants = [query.text]
    terms: list[str] = []
    lowered = query.text.lower()
    identifiers = list(dict.fromkeys(IDENTIFIER_PATTERN.findall(query.text) + ADDENDUM_PATTERN.findall(query.text)))
    modifiers = [modifier for modifier in INTENT_MODIFIERS if re.search(rf"\b{modifier}\b", lowered)]
    for key, additions in TERM_EXPANSIONS.items():
        match = re.search(rf"\b{re.escape(key)}\b", lowered)
        if match:
            if identifiers and any(modifier in modifiers for modifier in ("final", "current", "latest", "revised", "updated")) and key in {"deadline", "due date", "submission deadline", "closing date"}:
                additions = list(dict.fromkeys(additions + ["final due date", "revised due date", "extended due date", "new due date", "solicitation due date"]))
            for addition in additions:
                candidate = query.text[:match.start()] + addition + query.text[match.end():]
                if candidate.lower() not in {item.lower() for item in variants}:
                    variants.append(candidate)
                    terms.append(candidate)
    return QueryVariant(query.text, variants, terms)


def filter_records(records: list[IndexRecord], query: SearchQuery) -> list[IndexRecord]:
    """Apply bid, document-type, addendum, and completeness filters.

    Args:
        records: Indexed records to inspect.
        query: Query whose ``filters`` and ``include_incomplete`` settings
            control selection.

    Returns:
        Records matching every supplied filter, preserving input order.
        Records with diagnostic IDs are excluded unless incomplete evidence is
        explicitly included.
    """
    result = []
    for record in records:
        bid_filter = query.filters.get("bid_id")
        if bid_filter:
            allowed_bids = set(bid_filter) if isinstance(bid_filter, (list, tuple, set)) else {bid_filter}
            if record.bid_id not in allowed_bids:
                continue
        if query.filters.get("doc_type") and record.doc_type != query.filters["doc_type"]:
            continue
        if query.filters.get("addendum_number") is not None and record.addendum_number != int(query.filters["addendum_number"]):
            continue
        if not query.include_incomplete and record.diagnostic_ids:
            continue
        result.append(record)
    return result
