from src.extraction.models import ExtractedField, FieldValueItem, SourceCitation
from src.extraction.validation import confidence_for_field, summarize


def test_confidence_increases_with_precise_authoritative_corroboration():
    precise = ExtractedField(
        name="Due Date",
        value="2026-06-03",
        citations=[
            SourceCitation(file="official.pdf", page=1, location="submission deadline", bid_id="Bid1", authority_status="current", excerpt="Submission deadline: June 3, 2026."),
            SourceCitation(file="bid.html", location="deadline", bid_id="Bid1", excerpt="Submission deadline: June 3, 2026."),
        ],
        confidence=0.0,
        status="supported",
    )
    weak = ExtractedField(
        name="Due Date",
        value="2026-06-03",
        citations=[SourceCitation(file="snippet.txt", bid_id="Bid1", excerpt="Submission deadline: June 3, 2026.")],
        confidence=0.0,
        status="supported",
    )

    assert confidence_for_field(precise) > confidence_for_field(weak)
    assert confidence_for_field(precise) < 1.0


def test_missing_and_review_required_fields_have_zero_confidence():
    missing = ExtractedField(name="Payment Terms", value=None, confidence=0.0, status="not_found")
    disputed = ExtractedField(name="Due Date", value=None, confidence=0.0, status="review_required")

    assert confidence_for_field(missing) == 0.0
    assert confidence_for_field(disputed) == 0.0


def test_validation_rejects_citation_that_only_supports_another_field():
    field = ExtractedField(
        name="Due Date",
        value="2026-08-09",
        citations=[SourceCitation(file="delivery.pdf", page=2, location="delivery schedule", bid_id="Bid1", excerpt="Delivery deadline: August 9, 2026.")],
        confidence=0.8,
        status="supported",
    )

    validation = summarize({"Due Date": field})

    assert validation.failed == 1
    assert validation.results[0]["status"] == "failed"


def test_validation_rejects_product_attributes_not_supported_by_item_citation():
    citation = SourceCitation(
        file="products.pdf",
        page=2,
        bid_id="Bid1",
        excerpt="Product: Laptop Alpha; quantity: 10; model number: ZX100.",
    )
    field = ExtractedField(
        name="Product",
        value=[FieldValueItem(
            value="Laptop Alpha",
            attributes={"quantity": 999, "model_no": "WRONG"},
            citations=[citation],
        )],
        citations=[citation],
        confidence=0.9,
        status="supported",
    )

    validation = summarize({"Product": field})

    assert validation.failed == 1
    assert validation.results[0]["status"] == "failed"


def test_validation_accepts_product_attributes_supported_by_item_citation():
    citation = SourceCitation(
        file="products.pdf",
        page=2,
        bid_id="Bid1",
        excerpt="Product: Laptop Alpha; quantity: 10; model number: ZX100.",
    )
    field = ExtractedField(
        name="Product",
        value=[FieldValueItem(
            value="Laptop Alpha",
            attributes={"quantity": 10, "model_no": "ZX100"},
            citations=[citation],
        )],
        citations=[citation],
        confidence=0.9,
        status="supported",
    )

    validation = summarize({"Product": field})

    assert validation.passed == 1
    assert validation.results[0]["status"] == "supported"


def test_confidence_rewards_an_explicit_field_label_over_an_identifier_only_match():
    explicit = ExtractedField(
        name="Bid Number",
        value="JA-207652",
        citations=[SourceCitation(file="rfp.pdf", page=1, location="bid number", bid_id="Bid1", excerpt="Bid Number: JA-207652.")],
        confidence=0.0,
        status="supported",
    )
    implicit = ExtractedField(
        name="Bid Number",
        value="JA-207652",
        citations=[SourceCitation(file="rfp.pdf", page=1, location="cover", bid_id="Bid1", excerpt="JA-207652 Student and Staff Computing Devices")],
        confidence=0.0,
        status="supported",
    )

    assert confidence_for_field(explicit) > confidence_for_field(implicit)


def test_conflicting_cited_scalar_values_require_review_and_zero_confidence():
    field = ExtractedField(
        name="Due Date",
        value="2026-06-03",
        citations=[
            SourceCitation(file="base.pdf", page=1, location="due date", bid_id="Bid1", excerpt="Submission deadline: June 3, 2026."),
            SourceCitation(file="notice.pdf", page=1, location="due date", bid_id="Bid1", excerpt="Submission deadline: June 4, 2026."),
        ],
        confidence=0.9,
        status="supported",
    )

    validation = summarize({"Due Date": field})

    assert validation.review_required == 1
    assert field.status == "review_required"
    assert field.value is None
    assert field.confidence == 0.0