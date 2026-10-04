import re

from src.extraction.fields import CANONICAL_FIELDS
from src.extraction.models import ExtractedField, SourceCitation
from src.extraction.record_builder import build_record


def _empty_fields():
    return {
        name: ExtractedField(name=name, value=None, confidence=0.0, notes="Not found in documents", status="not_found")
        for name in CANONICAL_FIELDS
    }


def test_bid_summary_uses_three_to_six_supported_cited_sentences():
    fields = _empty_fields()
    fields["Title"] = ExtractedField(
        name="Title", value="Laptop Procurement", citations=[SourceCitation(file="title.pdf", page=1, bid_id="Bid1", excerpt="Title: Laptop Procurement.")], confidence=0.9, status="supported"
    )
    fields["Due Date"] = ExtractedField(
        name="Due Date", value="2026-06-03", citations=[SourceCitation(file="deadline.pdf", page=2, bid_id="Bid1", excerpt="Submission deadline: June 3, 2026.")], confidence=0.9, status="supported"
    )
    fields["Payment Terms"] = ExtractedField(
        name="Payment Terms", value="Net 30", citations=[SourceCitation(file="terms.pdf", page=3, bid_id="Bid1", excerpt="Payment terms: Net 30.")], confidence=0.9, status="supported"
    )

    record = build_record("Bid1", fields)
    summary = record.fields["Bid Summary"]
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", summary.value.strip()) if part]

    assert 3 <= len(sentences) <= 6
    assert {citation.file for citation in summary.citations} == {"title.pdf", "deadline.pdf", "terms.pdf"}
    assert summary.status == "supported"


def test_bid_summary_is_not_padded_when_fewer_than_three_facts_are_supported():
    fields = _empty_fields()
    fields["Title"] = ExtractedField(
        name="Title", value="Laptop Procurement", citations=[SourceCitation(file="title.pdf", page=1, bid_id="Bid1", excerpt="Title: Laptop Procurement.")], confidence=0.9, status="supported"
    )

    record = build_record("Bid1", fields)

    assert record.fields["Bid Summary"].value is None
    assert record.fields["Bid Summary"].status == "not_found"


def test_bid_summary_excludes_values_rejected_by_field_evidence_validation():
    fields = _empty_fields()
    fields["Title"] = ExtractedField(
        name="Title", value="Unsupported title", citations=[SourceCitation(file="deadline.pdf", page=1, bid_id="Bid1", excerpt="Submission deadline: June 3, 2026.")], confidence=0.9, status="supported"
    )
    fields["Due Date"] = ExtractedField(
        name="Due Date", value="2026-06-03", citations=[SourceCitation(file="deadline.pdf", page=1, bid_id="Bid1", excerpt="Submission deadline: June 3, 2026.")], confidence=0.9, status="supported"
    )
    fields["Payment Terms"] = ExtractedField(
        name="Payment Terms", value="Net 30", citations=[SourceCitation(file="terms.pdf", page=3, bid_id="Bid1", excerpt="Payment terms: Net 30.")], confidence=0.9, status="supported"
    )
    fields["Bid Submission Type"] = ExtractedField(
        name="Bid Submission Type", value="Electronic portal", citations=[SourceCitation(file="submission.pdf", page=4, bid_id="Bid1", excerpt="Submit bids through the electronic portal.")], confidence=0.9, status="supported"
    )

    record = build_record("Bid1", fields)

    assert fields["Title"].status == "failed"
    assert "Unsupported title" not in record.fields["Bid Summary"].value
    assert 3 <= len(re.split(r"(?<=[.!?])\s+", record.fields["Bid Summary"].value.strip())) <= 6