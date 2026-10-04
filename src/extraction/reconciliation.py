"""Apply addendum values and collection operations to extracted fields."""

from __future__ import annotations

import re
from typing import Any

from .citations import citation_from_evidence
from .fields import COLLECTION_FIELDS
from .models import AddendumChange, ExtractedField, FieldValueItem
from .normalization import normalize_collection_items, normalize_value
from src.field_registry import FIELD_DEFINITIONS_BY_CANONICAL_NAME


def is_addendum_evidence(item: dict[str, Any]) -> bool:
    """Return whether a record is identified as addendum evidence.

    Args:
        item: Evidence mapping with optional nested record metadata.

    Returns:
        ``True`` for addendum document type, explicit addendum number, or an
        addendum-marked source filename.
    """
    record = item.get("record", item)
    return (
        record.get("doc_type") == "addendum"
        or record.get("addendum_number") is not None
        or "addendum" in record.get("source_file", "").casefold()
    )


def _is_field_update_candidate(field: str, text: str) -> bool:
    """Detect update wording associated with a supported scalar field."""
    if field == "Due Date":
        return bool(re.search(r"\bnew\s+(?:submission\s+)?due\s+date\b|\bsubmission\s+deadline\b", text, re.IGNORECASE))
    if field == "Payment Terms":
        return bool(re.search(r"\bpayment\s+terms?\s*[:\-]", text, re.IGNORECASE))
    if field == "Delivery Date":
        return bool(re.search(r"\bdelivery\s+(?:date|within)\s*[:\-]", text, re.IGNORECASE))
    if field == "Installation":
        return bool(re.search(r"\binstallation\b.{0,60}\b(?:revised|updated|changed|replaced|no longer required)\b", text, re.IGNORECASE))
    if field == "Title":
        return bool(re.search(r"\b(?:new|revised|updated|changed)\s+(?:solicitation\s+)?title\b", text, re.IGNORECASE))
    if field == "Bid Number":
        return bool(re.search(r"\b(?:new|revised|updated|changed)\s+(?:bid|rfp|solicitation)\s+(?:number|no\.)\b", text, re.IGNORECASE))
    if field == "Pre Bid Meeting":
        return bool(re.search(r"\bpre[- ]?(?:bid|proposal)\s+(?:meeting|conference).{0,60}\b(?:new|rescheduled|changed|updated)\b", text, re.IGNORECASE))
    if field == "Bid Submission Type":
        return bool(re.search(r"\bsubmission\s+(?:method|instructions?)\b.{0,60}\b(?:new|revised|updated|changed)\b", text, re.IGNORECASE))
    if field == "Term of Bid":
        return bool(re.search(r"\b(?:initial\s+term|renewal|contract\s+term)\b.{0,80}\b(?:new|revised|updated|changed|extended)\b", text, re.IGNORECASE))
    return False


def reconcile(fields: dict[str, ExtractedField], evidence: list[dict[str, Any]], bid_id: str) -> list[AddendumChange]:
    """Reconcile scalar and collection fields against ordered addendum evidence.

    Args:
        fields: Canonical extracted fields; values/status/citations may be
            mutated to reflect controlling addenda or unresolved conflicts.
        evidence: Base and addendum evidence mappings containing text, source,
            addendum number/date, and optional authority status.
        bid_id: Bid identifier inserted into citations.

    Returns:
        Ordered ``AddendumChange`` records with previous/current values,
        citations, controlling addendum metadata, and review flags.
    """
    changes: list[AddendumChange] = []
    for name, field in fields.items():
        if name in COLLECTION_FIELDS:
            changes.extend(_reconcile_collection_field(name, field, evidence, bid_id))
            continue
        candidates = []
        for item in evidence:
            record = item.get("record", item)
            if not is_addendum_evidence(item):
                continue
            text = record.get("text", "")
            if not _is_field_update_candidate(name, text):
                continue
            value = _parse_field_value(name, text, item, bid_id)
            if value is not None:
                candidates.append((item, value))
        candidates.sort(key=lambda pair: (
            pair[0].get("record", pair[0]).get("addendum_number") or -1,
            pair[0].get("record", pair[0]).get("document_date") or "",
        ))
        if not candidates:
            continue
        controlling, revised_value = candidates[-1]
        record = controlling.get("record", controlling)
        previous = field.value
        previous_citations = list(field.citations)
        citation = citation_from_evidence(controlling, bid_id)
        top_key = (record.get("addendum_number") or -1, record.get("document_date") or "")
        tied = [pair for pair in candidates if (
            (pair[0].get("record", pair[0]).get("addendum_number") or -1),
            pair[0].get("record", pair[0]).get("document_date") or "",
        ) == top_key]
        tied_authorities = {item.get("authority_status") or item.get("record", item).get("status") for item, _ in tied}
        tied_values = {_value_signature(value) for _, value in tied}
        if len(tied) > 1 and (len(tied_authorities) > 1 or len(tied_values) > 1):
            tied_citations = [citation_from_evidence(item, bid_id) for item, _ in tied]
            field.value = None
            field.citations = tied_citations
            field.status = "review_required"
            field.confidence = 0.0
            field.notes = "Conflicting authoritative addendum values require review."
            changes.append(AddendumChange(
                field=name,
                previous_value=previous,
                current_value=None,
                previous_citations=previous_citations,
                current_citations=tied_citations,
                addendum_number=record.get("addendum_number"),
                effective_date=record.get("document_date"),
                controlling_citation=citation,
                notes="Top-ranked addendum values or authority conflict; precedence could not be resolved.",
                review_required=True,
            ))
            continue
        if name in COLLECTION_FIELDS and isinstance(previous, list) and isinstance(revised_value, list):
            merged = {item.value.casefold(): item for item in previous}
            for item in revised_value:
                existing = merged.get(item.value.casefold())
                if existing:
                    existing.attributes.update(item.attributes)
                    for item_citation in item.citations:
                        if item_citation.model_dump_json() not in {entry.model_dump_json() for entry in existing.citations}:
                            existing.citations.append(item_citation)
                else:
                    merged[item.value.casefold()] = item
            revised_value = list(merged.values())
        if _value_signature(previous) == _value_signature(revised_value):
            continue
        field.value = revised_value
        if name in COLLECTION_FIELDS:
            field.citations = list({
                citation.model_dump_json(): citation
                for item_value in field.value
                for citation in item_value.citations
            }.values())
        else:
            field.citations = [citation]
        field.status = "supported"
        field.notes = "Value controlled by the latest valid addendum."
        changes.append(AddendumChange(
            field=name,
            previous_value=previous,
            current_value=field.value,
            previous_citations=previous_citations,
            current_citations=field.citations if name in COLLECTION_FIELDS else [citation],
            addendum_number=record.get("addendum_number"),
            effective_date=record.get("document_date"),
            controlling_citation=citation,
            notes="Selected by addendum number/effective date and source authority.",
        ))
    return changes


def _reconcile_collection_field(
    name: str,
    field: ExtractedField,
    evidence: list[dict[str, Any]],
    bid_id: str,
) -> list[AddendumChange]:
    """Apply add/add, replacement, and removal operations to a collection field."""
    current = _collection_items_from_evidence(name, evidence, bid_id, addenda=False)
    candidates = []
    if name in {"company_name", "contact_info"}:
        return []
    for item in evidence:
        record = item.get("record", item)
        if not is_addendum_evidence(item):
            continue
        text = record.get("text", "")
        if name == "Product Specification" and record.get("content_kind") != "table":
            definition = FIELD_DEFINITIONS_BY_CANONICAL_NAME[name]
            aliases = [
                re.escape(alias).replace(r"\ ", r"\s+")
                for alias in definition.label_aliases
                if alias.casefold() not in {"wifi", "wireless", "bluetooth", "copilot ready"}
            ]
            explicit_label = bool(aliases and re.search(
                rf"(?im)^\s*(?:{'|'.join(aliases)})s?\s*[:|]",
                text,
            ))
            if not explicit_label:
                continue
        items = normalize_collection_items(name, text)
        if name == "Any Additional Documentation Required" and record.get("addendum_number"):
            if re.search(r"sign\s+this\s+addendum|acknowledge.{0,50}return/submit", record.get("text", ""), re.IGNORECASE):
                acknowledgment = (f"Addendum {record['addendum_number']}", {})
                if acknowledgment not in items:
                    items.append(acknowledgment)
        if not items:
            continue
        candidates.append((item, _collection_operation(record.get("text", "")), items))
    if not candidates:
        return []
    candidates.sort(key=lambda candidate: (
        candidate[0].get("record", candidate[0]).get("addendum_number") or -1,
        candidate[0].get("record", candidate[0]).get("document_date") or "",
    ))

    grouped: list[list[tuple[dict[str, Any], str, list[tuple[str, dict[str, Any]]]]]] = []
    group_key = None
    for candidate in candidates:
        record = candidate[0].get("record", candidate[0])
        key = (record.get("addendum_number") or -1, record.get("document_date") or "")
        if key != group_key:
            grouped.append([])
            group_key = key
        grouped[-1].append(candidate)

    changes: list[AddendumChange] = []
    for group in grouped:
        group_record = group[-1][0].get("record", group[-1][0])
        replacements = [candidate for candidate in group if candidate[1] == "replace"]
        replacement_values = {
            tuple(value.casefold() for value, _ in candidate[2])
            for candidate in replacements
        }
        replacement_authorities = {
            candidate[0].get("authority_status") or candidate[0].get("record", candidate[0]).get("status")
            for candidate in replacements
        }
        if len(replacements) > 1 and (len(replacement_values) > 1 or len(replacement_authorities) > 1):
            previous = list(current)
            previous_citations = _item_citations(previous)
            current_citations = [citation_from_evidence(candidate[0], bid_id) for candidate in replacements]
            field.value = None
            field.citations = current_citations
            field.status = "review_required"
            field.confidence = 0.0
            field.notes = "Conflicting collection replacement addenda require review."
            changes.append(AddendumChange(
                field=name,
                previous_value=previous,
                current_value=None,
                previous_citations=previous_citations,
                current_citations=current_citations,
                addendum_number=group_record.get("addendum_number"),
                effective_date=group_record.get("document_date"),
                controlling_citation=current_citations[-1],
                notes="Same-order collection replacements conflict and require review.",
                review_required=True,
            ))
            return changes

        previous = list(current)
        previous_signature = _value_signature(previous)
        if replacements:
            current = _items_with_citations(replacements[-1][0], replacements[-1][2], bid_id)
        for candidate in group:
            operation = candidate[1]
            candidate_items = _items_with_citations(candidate[0], candidate[2], bid_id)
            if operation == "replace":
                continue
            if operation == "remove":
                removed = {item.value.casefold() for item in candidate_items}
                current = [item for item in current if item.value.casefold() not in removed]
            else:
                current = _merge_items(current, candidate_items)
        if previous_signature == _value_signature(current):
            continue

        addendum_citations = [citation_from_evidence(candidate[0], bid_id) for candidate in group]
        current_citations = _item_citations(current)
        current_citations = _unique_citations(current_citations + addendum_citations)
        changes.append(AddendumChange(
            field=name,
            previous_value=previous,
            current_value=list(current),
            previous_citations=_item_citations(previous),
            current_citations=current_citations,
            addendum_number=group_record.get("addendum_number"),
            effective_date=group_record.get("document_date"),
            controlling_citation=addendum_citations[-1],
            notes="Collection values reconciled using the addendum's additive, replacement, or removal wording.",
        ))

    field.value = current
    field.citations = _item_citations(current)
    field.status = "supported" if current else "not_found"
    field.confidence = 0.8 if current else 0.0
    field.notes = "Collection values reconciled against applicable addenda." if current else "No supported collection values remain after addendum reconciliation."
    return changes


def _collection_items_from_evidence(
    field: str,
    evidence: list[dict[str, Any]],
    bid_id: str,
    *,
    addenda: bool,
) -> list[FieldValueItem]:
    """Collect and deduplicate values from base or addendum evidence only."""
    if field == "Product Specification":
        table_pages = {
            (record.get("source_file"), record.get("page_number"))
            for evidence_item in evidence
            if is_addendum_evidence(evidence_item) == addenda
            for record in [evidence_item.get("record", evidence_item)]
            if record.get("content_kind") == "table"
        }
        evidence = [
            evidence_item for evidence_item in evidence
            if (record := evidence_item.get("record", evidence_item)).get("content_kind") == "table"
            or (record.get("source_file"), record.get("page_number")) not in table_pages
        ]
    items: list[FieldValueItem] = []
    for evidence_item in evidence:
        record = evidence_item.get("record", evidence_item)
        if is_addendum_evidence(evidence_item) != addenda:
            continue
        items = _merge_items(
            items,
            _items_with_citations(evidence_item, normalize_collection_items(field, record.get("text", "")), bid_id),
        )
    return items


def _items_with_citations(evidence: dict[str, Any], values: list[tuple[str, dict[str, Any]]], bid_id: str) -> list[FieldValueItem]:
    """Wrap normalized collection tuples as citation-required value items."""
    citation = citation_from_evidence(evidence, bid_id)
    return [FieldValueItem(value=" ".join(value.split()), attributes=attributes, citations=[citation]) for value, attributes in values if value]


def _merge_items(existing: list[FieldValueItem], incoming: list[FieldValueItem]) -> list[FieldValueItem]:
    """Merge case-insensitive duplicate values and combine attributes/citations."""
    merged = {item.value.casefold(): item for item in existing}
    for item in incoming:
        prior = merged.get(item.value.casefold())
        if prior is None:
            merged[item.value.casefold()] = item
            continue
        prior.attributes.update(item.attributes)
        prior.citations = _unique_citations(prior.citations + item.citations)
    return list(merged.values())


def _item_citations(items: list[FieldValueItem]) -> list[Any]:
    """Flatten item citations and remove duplicates by serialized citation."""
    return _unique_citations([citation for item in items for citation in item.citations])


def _unique_citations(citations: list[Any]) -> list[Any]:
    """Preserve first-seen order while deduplicating citation models."""
    unique = {citation.model_dump_json(): citation for citation in citations}
    return list(unique.values())


def _collection_operation(text: str) -> str:
    """Classify amendment wording as replace, remove, or additive by default."""
    if re.search(r"\b(?:replace[sd]?|replacement|supersed(?:e|es|ed)|instead of|in lieu of)\b", text, re.IGNORECASE):
        return "replace"
    if re.search(r"\b(?:no longer required|no longer needed|remove[sd]?|delete[sd]?)\b", text, re.IGNORECASE):
        return "remove"
    return "add"


def _parse_field_value(field: str, text: str, evidence: dict[str, Any], bid_id: str) -> Any:
    """Parse a scalar or collection update and attach its evidence citation."""
    if field in COLLECTION_FIELDS:
        items = normalize_collection_items(field, text)
        if not items:
            return None
        citation = citation_from_evidence(evidence, bid_id)
        return [FieldValueItem(value=value, attributes=attributes, citations=[citation]) for value, attributes in items if value]
    return normalize_value(field, text)


def _value_signature(value: Any) -> str:
    """Create a stable comparison string for scalar or collection values."""
    if isinstance(value, list):
        return "|".join(_value_signature(item) for item in value)
    if isinstance(value, FieldValueItem):
        attributes = tuple(sorted(value.attributes.items()))
        return f"{value.value!r}:{attributes!r}"
    return repr(value)
