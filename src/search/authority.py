"""Determine current, superseded, and supporting evidence authority."""

from __future__ import annotations

import re

from .models import RankedEvidence


MODIFICATION_TERMS = ("new due date", "extended", "revised", "changed", "amend", "replacement", "supersedes", "updated")
DEADLINE_TERMS = ("deadline", "due date", "submission", "closing date", "solicitation due")


def _is_deadline_query(query: str) -> bool:
    """Return whether query text signals a deadline-related request.

    Args:
        query: User query string.

    Returns:
        ``True`` when any configured deadline term occurs case-insensitively.
    """
    lowered = query.lower()
    return any(term in lowered for term in DEADLINE_TERMS)


def _is_relevant_amendment(result: RankedEvidence, query: str) -> bool:
    """Check whether an addendum result plausibly modifies the query topic.

    Args:
        result: Ranked evidence item being considered as an amendment.
        query: User query used to match deadline or general topic terms.

    Returns:
        ``True`` when amendment and query content overlap under the module's
        deadline-specific or general modification rules.
    """
    text = result.record.text.lower()
    if _is_deadline_query(query):
        return any(term in text for term in MODIFICATION_TERMS) and any(term in text for term in DEADLINE_TERMS)
    query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    return bool(query_terms.intersection(re.findall(r"[a-z0-9]+", text))) and any(term in text for term in MODIFICATION_TERMS)


def _deadline_value(result: RankedEvidence) -> str | None:
    """Extract the last recognized date string from an evidence passage.

    Args:
        result: Evidence whose source text may contain a deadline.

    Returns:
        Last matched month-name, ISO, or numeric date, lowercased, or ``None``
        when no supported date format is found.
    """
    text = result.record.text
    matches = re.findall(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+20\d{2}\b|\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}[-/]\d{1,2}[-/]20\d{2}\b",
        text,
        re.IGNORECASE,
    )
    return matches[-1].casefold() if matches else None


def apply_requirement_authority(results: list[RankedEvidence], query: str) -> list[RankedEvidence]:
    """Annotate evidence authority using relevant, non-superseded addenda.

    Args:
        results: Ranked evidence to annotate. Each item's authority status and
            superseding record ID are updated in place.
        query: User query used to locate relevant amendments and detect
            deadline intent.

    Returns:
        The same list of evidence objects. The latest matching addendum is
        marked current; older or replaced content is marked superseded or
        supporting. Tied addenda with different extracted deadline values are
        marked ``review_required`` for manual resolution.
    """
    relevant_amendments = [
        item
        for item in results
        if item.record.doc_type == "addendum"
        and item.authority_status != "superseded"
        and item.record.status != "superseded"
        and _is_relevant_amendment(item, query)
    ]
    controlling = max(
        relevant_amendments,
        key=lambda item: (
            item.record.addendum_number if item.record.addendum_number is not None else -1,
            item.record.document_date or "",
            item.record.page_number or -1,
        ),
        default=None,
    )
    if _is_deadline_query(query) and controlling is not None:
        controlling_order = (
            controlling.record.addendum_number,
            controlling.record.document_date,
            controlling.record.page_number,
        )
        tied = [
            item
            for item in relevant_amendments
            if (
                item.record.addendum_number,
                item.record.document_date,
                item.record.page_number,
            )
            == controlling_order
        ]
        tied_values = {_deadline_value(item) for item in tied}
        if len(tied) > 1 and len(tied_values - {None}) > 1:
            for result in results:
                result.authority_status = "review_required"
                result.superseded_by = None
            return results
    for result in results:
        result.authority_status = "unknown"
        result.superseded_by = None
        if controlling and result.record.record_id == controlling.record.record_id:
            result.authority_status = "current"
        elif controlling and (result.record.status == "superseded" or result.authority_status == "superseded"):
            result.authority_status = "superseded"
            result.superseded_by = controlling.record.record_id
        elif controlling and result.record.doc_type != "addendum" and _is_deadline_query(query):
            text = result.record.text.lower()
            if any(term in text for term in ("due", "deadline", "solicitation due", "submission")) and re.search(r"\b20\d{2}\b|\b\d{1,2}[-/]\w+[-/]?20\d{2}\b", text):
                result.authority_status = "superseded"
                result.superseded_by = controlling.record.record_id
            else:
                result.authority_status = "supporting"
        elif result.record.doc_type == "addendum":
            result.authority_status = "supporting"
        else:
            result.authority_status = "supporting"
    return results
