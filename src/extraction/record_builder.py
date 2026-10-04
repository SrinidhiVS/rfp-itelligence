"""Assemble validated extraction records and citation-backed summaries."""

from __future__ import annotations

from .models import BidExtractionRecord, ExtractedField, FieldValueItem, ProcessingDiagnostic, SourceCitation
from .validation import summarize


def build_record(bid_id: str, fields: dict[str, ExtractedField], *, changes=None, diagnostics: list[ProcessingDiagnostic] | None = None) -> BidExtractionRecord:
    """Build the final bid record and calculate its validation summary.

    Args:
        bid_id: Canonical or generated identifier for the bid.
        fields: Canonical extracted fields; Bid Summary is rebuilt when present.
        changes: Optional addendum change models, defaulting to an empty list.
        diagnostics: Optional processing diagnostics, defaulting to empty.

    Returns:
        ``BidExtractionRecord`` with fields, changes, diagnostics, and a
        computed validation summary.
    """
    if "Bid Summary" in fields:
        summarize({name: field for name, field in fields.items() if name != "Bid Summary"})
        fields["Bid Summary"] = build_summary(fields)
    return BidExtractionRecord(bid_id=bid_id, fields=fields, addendum_changes=changes or [], validation=summarize(fields), diagnostics=diagnostics or [])


def build_summary(fields: dict[str, ExtractedField]) -> ExtractedField:
    """Compose a three-to-six-sentence summary from supported cited fields.

    Args:
        fields: Canonical field mapping whose supported values/citations may
            contribute summary statements.

    Returns:
        Supported ``Bid Summary`` field with deduplicated source citations, or
        an explicit not_found field when fewer than three supported facts are
        available.
    """
    sentence_builders = (
        ("Title", "The solicitation is titled {value}."),
        ("Due Date", "The submission deadline is {value}."),
        ("Bid Submission Type", "The submission method is {value}."),
        ("Term of Bid", "The contract term is {value}."),
        ("Pre Bid Meeting", "The pre-bid meeting information is {value}."),
        ("Delivery Date", "The delivery requirement is {value}."),
        ("Payment Terms", "Payment terms are {value}."),
        ("Bid Bond Requirement", "The bid bond requirement is {value}."),
        ("Product", "Requested products include {value}."),
        ("Any Additional Documentation Required", "Required documents include {value}."),
        ("Contract or Cooperative to Use", "The contract vehicle is {value}."),
        ("Product Specification", "Product specifications include {value}."),
    )
    sentences: list[str] = []
    citations: dict[str, SourceCitation] = {}
    for name, template in sentence_builders:
        field = fields.get(name)
        if not field or field.status != "supported" or field.value is None or not field.citations:
            continue
        value = _display_value(field.value)
        if not value:
            continue
        sentences.append(template.format(value=value))
        for citation in field.citations:
            citations[citation.model_dump_json()] = citation
        if len(sentences) == 6:
            break
    if len(sentences) < 3:
        return ExtractedField(
            name="Bid Summary",
            value=None,
            citations=[],
            confidence=0.0,
            notes="Not enough independently supported facts to write a three-sentence summary.",
            status="not_found",
        )
    return ExtractedField(
        name="Bid Summary",
        value=" ".join(sentences),
        citations=list(citations.values()),
        confidence=0.0,
        notes="Summary statements are derived from validated cited fields.",
        status="supported",
    )


def _display_value(value: object) -> str:
    """Render scalar/list field values as concise summary prose."""
    if isinstance(value, list):
        display_items = [
            item.value if isinstance(item, FieldValueItem) else item.get("value", "")
            for item in value
        ]
        return ", ".join(str(item) for item in display_items if item)
    if isinstance(value, bool):
        return "required" if value else "not required"
    return str(value).strip()
