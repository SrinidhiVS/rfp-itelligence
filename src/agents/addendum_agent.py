"""Resolve field changes from relevant ordered addendum evidence."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .extraction_agent import _value_for
from .state import AddendumChange, Citation


def _citation(item: dict[str, Any]) -> Citation:
    """Convert an addendum evidence record to the workflow citation schema."""
    record = item["record"]
    return Citation(file=record["source_file"], page=record.get("page_number"), bid_id=record["bid_id"], locator=record.get("source_locator", {}), authority_status=item.get("authority_status"), superseded_by=item.get("superseded_by"))


def _valid_change(field: str, value: str | None) -> bool:
    """Check required presence and supported date format for an amendment."""
    if not value:
        return False
    if field == "submission_deadline":
        for date_format in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%B %d"):
            try:
                datetime.strptime(value, date_format)
                return True
            except ValueError:
                continue
        return False
    return True


def reconcile_changes(fields: dict[str, Any], evidence: list[dict[str, Any]]) -> list[AddendumChange]:
    """Apply the latest comparable field-specific addendum update.

    Args:
        fields: Mutable mapping of extracted workflow fields.
        evidence: Ranked evidence records; addendum type, update language, and
            field-specific terms are required to be considered.

    Returns:
        Addendum change models for resolved and review-required updates. Tied,
        invalid, or incomparable changes mark the affected field for review.
    """
    changes: list[AddendumChange] = []
    for name, field in fields.items():
        candidates = []
        review = []
        terms = ("submission deadline", "deadline", "due date") if name == "submission_deadline" else (name.replace("_", " "),)
        for item in evidence:
            record = item["record"]
            text = record["text"]
            if record.get("doc_type") != "addendum" or field.citations and record["bid_id"] != field.citations[0].bid_id:
                continue
            if not any(re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) for term in terms):
                continue
            if not re.search(r"\b(?:revised|changed|extended|amended|updated|new)\b", text, re.IGNORECASE):
                continue
            value = _value_for(name, text)
            number = record.get("addendum_number")
            document_date = record.get("document_date")
            order = ("number", number) if isinstance(number, int) else ("date", document_date) if document_date else None
            if not _valid_change(name, value) or order is None:
                review.append((item, value, "invalid or unorderable addendum change"))
            else:
                candidates.append((order, item, value))
        if candidates:
            kinds = {order[0] for order, _, _ in candidates}
            if len(kinds) != 1:
                review.extend((item, value, "incomparable addendum ordering") for _, item, value in candidates)
            else:
                latest = max(order for order, _, _ in candidates)
                controlling = [(item, value) for order, item, value in candidates if order == latest]
                if len({value for _, value in controlling}) != 1:
                    review.extend((item, value, "conflicting changes at the same order") for item, value in controlling)
                else:
                    item, value = controlling[0]
                    previous_value = field.value
                    field.value = value
                    partial_date = name == "submission_deadline" and not re.search(r"\b\d{4}\b", value)
                    field.status = "review_required" if partial_date else "supported"
                    field.citations = [_citation(item)]
                    field.notes = "Date year is not stated; review required." if partial_date else "Value controlled by the latest valid relevant addendum."
                    changes.append(AddendumChange(field=name, previous_value=previous_value, new_value=value, addendum_number=item["record"].get("addendum_number"), citations=[_citation(item)], reason="Partial date requires review" if partial_date else "Latest valid field-specific change", review_required=partial_date))
        for item, value, reason in review:
            changes.append(AddendumChange(field=name, previous_value=field.value, new_value=value, addendum_number=item["record"].get("addendum_number"), citations=[_citation(item)], reason=reason, review_required=True))
        if review and not any(change.field == name and not change.review_required for change in changes):
            field.status = "review_required"
            field.notes = "Addendum conflict or invalid change requires review."
    return changes
