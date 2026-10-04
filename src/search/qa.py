"""Construct cited answers and addendum change logs from search evidence."""

from __future__ import annotations

from .models import CitedAnswer, SearchQuery
from .addendum import reconcile
from .keyword import tokens


class QAService:
    """Turn search results into an answer with source-level citations.

    Args:
        search_service: Search adapter exposing ``search(SearchQuery)`` and
            returning ranked results plus diagnostics.
    """

    def __init__(self, search_service):
        """Bind the QA adapter to a search service."""
        self.search_service = search_service

    def answer(self, query: SearchQuery) -> CitedAnswer:
        """Answer a query from retrieved evidence without inventing support.

        Args:
            query: Validated query to send to the configured search service.

        Returns:
            ``CitedAnswer`` containing the query, answer text, found flag,
            evidence, citation dictionaries, diagnostics, per-bid evidence,
            and any addendum change records. With no evidence, the answer is
            ``"Not found in documents"`` and ``found`` is false.
        """
        response = self.search_service.search(query)
        evidence = response["results"]
        if not evidence:
            return CitedAnswer(query, "Not found in documents", False, diagnostics=response["diagnostics"])
        citations = [{
            "file": item.record.source_file,
            "page": item.record.page_number,
            "bid_id": item.record.bid_id,
            "doc_type": item.record.doc_type,
            "addendum_number": item.record.addendum_number,
            "section_title": item.record.section_title,
            "score": item.score,
            "rank": item.rank,
            "authority_status": item.authority_status,
            "superseded_by": item.superseded_by,
            "locator": item.record.source_locator,
        } for item in evidence]
        comparison = any(term in query.text.lower() for term in ("compare", "difference", "both bids"))
        answer_evidence = evidence[:3] if comparison else evidence[:1]
        answer = "\n\n".join(item.record.text for item in answer_evidence)
        change_log = []
        evidence_by_bid: dict[str, list] = {}
        for item in evidence:
            evidence_by_bid.setdefault(item.record.bid_id, []).append(item)
        query_terms = set(tokens(query.text))
        relevant_addenda = [item for item in evidence if item.record.doc_type == "addendum" and (query_terms.intersection(tokens(item.record.text)) or any(term in item.record.text.lower() for term in ("new due date", "extended", "revised", "changed", "amend")))]
        if relevant_addenda:
            values = [(item.record.addendum_number, item.record.page_number or 0, item.record.text, item) for item in relevant_addenda]
            _, change_log = reconcile(values, query.text)
        return CitedAnswer(query, answer, True, evidence=evidence, citations=citations, diagnostics=response["diagnostics"], change_log=change_log, evidence_by_bid=evidence_by_bid)
