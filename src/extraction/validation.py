"""Validate field support, citation completeness, conflicts, and confidence."""

from __future__ import annotations

import json
import re
from datetime import datetime

from .fields import COLLECTION_FIELDS
from .models import ExtractedField, FieldValueItem, ValidationSummary
from .normalization import normalize_collection_items, normalize_value
from src.field_registry import FIELD_VALIDATION_LABELS


def review_required_field(name: str, reason: str) -> ExtractedField:
    """Create a null field requiring review with zero confidence and no citations."""
    return ExtractedField(name=name, value=None, citations=[], confidence=0.0, notes=reason, status="review_required")


def confidence_for_field(field: ExtractedField) -> float:
    """Score evidence strength for a supported field on the 0..0.99 scale.

    Args:
        field: Extracted field and its source citations.

    Returns:
        Rounded confidence based on value support, explicit labels, locatable
        citations, corroboration, authority, and collection coverage. Invalid,
        unsupported, or conflicting values score 0.
    """
    if field.status != "supported" or field.value is None or not field.citations:
        return 0.0
    if not _supports_field_value(field) or _has_conflicting_cited_values(field):
        return 0.0
    citations = _field_citations(field)
    if not citations:
        return 0.0
    explicit = sum(_has_field_label(field.name, citation) for citation in citations) / len(citations)
    locatable = sum(citation.page is not None or citation.location is not None for citation in citations) / len(citations)
    source_files = {citation.file for citation in citations}
    corroborated = 1.0 if len(source_files) > 1 else 0.0
    authoritative = 1.0 if any(
        (citation.authority_status or "").lower() in {"current", "official", "authoritative"}
        for citation in citations
    ) else 0.0
    collection_completeness = _collection_citation_coverage(field) if field.name in COLLECTION_FIELDS else 0.0
    score = 0.35 + 0.2 * explicit + 0.15 * locatable + 0.1 * corroborated + 0.1 * authoritative + 0.1 + 0.1 * collection_completeness
    return round(min(score, 0.99), 2)


def _field_citations(field: ExtractedField) -> list:
    """Return unique citations, flattening item citations for collections."""
    if field.name not in COLLECTION_FIELDS:
        return field.citations
    citations = {
        citation.model_dump_json() if hasattr(citation, "model_dump_json") else json.dumps(citation, sort_keys=True): citation
        for item in field.value
        for citation in (item.citations if isinstance(item, FieldValueItem) else item.get("citations", []))
    }
    return list(citations.values())


def _has_field_label(field_name: str, citation: object) -> bool:
    """Check whether citation excerpt/location contains a configured field label."""
    excerpt = citation.excerpt or ""
    location = citation.location if isinstance(citation.location, str) else ""
    text = f"{excerpt} {location}".casefold()
    return any(label in text for label in FIELD_VALIDATION_LABELS.get(field_name, ()))


def _collection_citation_coverage(field: ExtractedField) -> float:
    """Return fraction of collection items supported by at least one citation."""
    items = field.value if isinstance(field.value, list) else []
    if not items:
        return 0.0
    supported = 0
    for item in items:
        value = item.value if isinstance(item, FieldValueItem) else item.get("value")
        attributes = item.attributes if isinstance(item, FieldValueItem) else item.get("attributes", {})
        citations = item.citations if isinstance(item, FieldValueItem) else item.get("citations", [])
        if value and citations and any(
            _collection_citation_supports(field.name, value, attributes, citation)
            for citation in citations
        ):
            supported += 1
    return supported / len(items)


def _supports_field_value(field: ExtractedField) -> bool:
    """Verify field-specific value-to-citation support requirements."""
    if field.name == "Bid Summary":
        if not isinstance(field.value, str):
            return False
        sentences = [part for part in re.split(r"(?<=[.!?])\s+", field.value.strip()) if part]
        return 3 <= len(sentences) <= 6 and bool(field.citations)
    if field.name in COLLECTION_FIELDS:
        items = field.value if isinstance(field.value, list) else []
        if not items:
            return False
        for item in items:
            value = item.value if isinstance(item, FieldValueItem) else item.get("value")
            attributes = item.attributes if isinstance(item, FieldValueItem) else item.get("attributes", {})
            citations = item.citations if isinstance(item, FieldValueItem) else item.get("citations", [])
            if not value or not citations:
                return False
            if not any(_collection_citation_supports(field.name, value, attributes, citation) for citation in citations):
                return False
        return True
    if field.name == "Due Date" and isinstance(field.value, str):
        return any(
            citation.excerpt and normalize_value(field.name, citation.excerpt) == field.value
            or _citation_supports_detailed_deadline(field.value, citation)
            for citation in field.citations
        )
    return any(citation.excerpt and normalize_value(field.name, citation.excerpt) == field.value for citation in field.citations)


def _citation_supports_detailed_deadline(value: str, citation: object) -> bool:
    """Check whether a dates-section citation supports date, time, and zone."""
    excerpt = citation.excerpt if hasattr(citation, "excerpt") else citation.get("excerpt")
    locator = citation.location if hasattr(citation, "location") else citation.get("location")
    if not excerpt or not isinstance(locator, dict) or locator.get("section_title", "").casefold() != "dates":
        return False
    parts = value.split()
    if len(parts) < 3:
        return False
    try:
        date_text = datetime.strptime(parts[0], "%Y-%m-%d").strftime("%m/%d/%Y")
        time_value = datetime.strptime(parts[1], "%H:%M")
        time_text = time_value.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return False
    excerpt_lower = excerpt.casefold()
    return date_text.casefold() in excerpt_lower and time_text.casefold() in excerpt_lower and parts[2].casefold() in excerpt_lower


def _has_conflicting_cited_values(field: ExtractedField) -> bool:
    """Detect disagreement among normalized scalar values in citations."""
    if field.name in COLLECTION_FIELDS or field.name == "Bid Summary":
        return False
    normalized_values = [
        value
        for citation in field.citations
        if citation.excerpt and (value := normalize_value(field.name, citation.excerpt)) is not None
    ]
    values = {repr(value) for value in normalized_values}
    if field.name == "Due Date" and len(values) > 1:
        parts = [value.split() for value in normalized_values if isinstance(value, str)]
        dates = {part[0] for part in parts if part}
        if len(dates) == 1:
            time_values = {part[1] for part in parts if len(part) > 1 and ":" in part[1]}
            zone_values = {part[2] for part in parts if len(part) > 2}
            return len(time_values) > 1 or len(zone_values) > 1
    return len(values) > 1


def _collection_citation_supports(field: str, value: object, attributes: dict[str, object], citation: object) -> bool:
    """Check that excerpt normalization yields the exact item and attributes."""
    excerpt = citation.excerpt if hasattr(citation, "excerpt") else citation.get("excerpt")
    if not excerpt:
        return False
    expected_value = " ".join(str(value).split()).casefold()
    if field == "Any Additional Documentation Required" and expected_value.startswith("addendum "):
        file_name = citation.file if hasattr(citation, "file") else citation.get("file", "")
        if expected_value in file_name.casefold() and re.search(r"\b(?:sign|submit|return|acknowledge)\b.{0,80}\baddendum\b", excerpt, re.IGNORECASE):
            return True
    for item_value, item_attributes in normalize_collection_items(field, excerpt):
        if " ".join(item_value.split()).casefold() != expected_value:
            continue
        if all(
            key in item_attributes and _attribute_values_match(expected, item_attributes[key])
            for key, expected in attributes.items()
        ):
            return True
    return False


def _attribute_values_match(expected: object, observed: object) -> bool:
    """Compare string attributes case-insensitively and other values directly."""
    if isinstance(expected, str) and isinstance(observed, str):
        return expected.casefold() == observed.casefold()
    return expected == observed


def summarize(fields: dict[str, ExtractedField]) -> ValidationSummary:
    """Validate all fields, update invalid dispositions, and count outcomes.

    Args:
        fields: Mapping from canonical field names to mutable extracted fields.

    Returns:
        ``ValidationSummary`` with passed/failed/not_found/review_required
        counts and one result dictionary per field. Unsupported evidence marks
        a field failed; contradictory cited scalar values mark it
        review_required.
    """
    counts = {"passed": 0, "failed": 0, "not_found": 0, "review_required": 0}
    results = []
    for name, field in fields.items():
        status = field.status
        evidence_supported = _supports_field_value(field) if status == "supported" else False
        conflict_detected = status == "supported" and _has_conflicting_cited_values(field)
        if conflict_detected:
            status = "review_required"
            field.status = "review_required"
            field.value = None
            field.confidence = 0.0
            field.notes = f"{field.notes} Conflicting cited values require review.".strip()
            evidence_supported = False
        elif status == "supported" and not evidence_supported:
            status = "failed"
            field.status = "failed"
            field.confidence = 0.0
            field.notes = f"{field.notes} Citation evidence does not support this field value.".strip()
        elif status == "supported":
            field.confidence = confidence_for_field(field)
        elif field.value is None:
            field.confidence = 0.0
        count_status = "passed" if status == "supported" else status
        counts[count_status] += 1
        results.append({
            "field": name,
            "status": status,
            "citation_complete": bool(field.citations) if field.value is not None else True,
            "evidence_supported": evidence_supported,
            "conflict_detected": conflict_detected,
            "confidence": field.confidence,
            "notes": field.notes,
        })
    return ValidationSummary(**counts, results=results)
