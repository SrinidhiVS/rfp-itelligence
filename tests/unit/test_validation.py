from src.extraction.extractor import StructuredExtractor
from src.extraction.models import ExtractedField, SourceCitation
from src.extraction.validation import summarize


def test_validation_counts_supported_and_not_found():
    record = StructuredExtractor().extract("Bid1", [{"record": {"source_file": "rfp.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "text": "deadline October 20"}}])
    assert record.validation.passed >= 1
    assert record.validation.not_found >= 1
    assert record.validation.passed + record.validation.not_found == 20


def test_validation_rejects_value_not_supported_by_its_citation():
    field = ExtractedField(
        name="Due Date",
        value="2026-10-20",
        citations=[SourceCitation(file="rfp.pdf", page=1, bid_id="Bid1", excerpt="Submission deadline: October 21, 2026.")],
        confidence=0.8,
        status="supported",
    )

    result = summarize({"Due Date": field})

    assert field.status == "failed"
    assert field.confidence == 0.0
    assert result.failed == 1
    assert result.results[0]["evidence_supported"] is False


def test_validation_keeps_conflicting_cited_deadlines_in_review():
    field = ExtractedField(
        name="Due Date",
        value="2026-10-20 14:00 CST",
        citations=[
            SourceCitation(file="rfp.pdf", page=1, bid_id="Bid1", excerpt="Submission deadline: October 20, 2026 at 2:00 PM CST."),
            SourceCitation(file="addendum.pdf", page=1, bid_id="Bid1", excerpt="Submission deadline: October 21, 2026 at 2:00 PM CST."),
        ],
        confidence=0.8,
        status="supported",
    )

    result = summarize({"Due Date": field})

    assert field.status == "review_required"
    assert field.value is None
    assert field.confidence == 0.0
    assert result.review_required == 1
    assert result.results[0]["conflict_detected"] is True
