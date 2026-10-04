from src.extraction.fields import CANONICAL_FIELDS
import pytest
from pydantic import ValidationError

from src.extraction.models import AddendumChange, BidExtractionRecord, ExtractedField, FieldValueItem, SourceCitation, ValidationSummary


def test_record_contract_has_twenty_fields_and_validation_counts():
    fields = {name: ExtractedField(name=name, value=None, confidence=0.0, notes="Not found in documents", status="not_found") for name in CANONICAL_FIELDS}
    record = BidExtractionRecord(bid_id="bid-one", fields=fields, validation=ValidationSummary(not_found=20))
    assert len(record.fields) == 20
    assert record.validation.not_found == 20


def test_supported_value_requires_citation_and_confidence_range():
    field = ExtractedField(name="Title", value="RFP", citations=[SourceCitation(file="bid.html", bid_id="bid-one")], confidence=0.8, status="supported")
    assert field.citations[0].file == "bid.html"


def test_field_value_item_retains_attributes_and_citations():
    citation = SourceCitation(file="products.pdf", page=2, bid_id="bid-one", excerpt="12 laptops")
    item = FieldValueItem(value="Laptop", attributes={"quantity": 12}, citations=[citation])

    assert item.value == "Laptop"
    assert item.attributes == {"quantity": 12}
    assert item.citations[0].file == "products.pdf"


def test_field_value_item_requires_supporting_citation():
    with pytest.raises(ValidationError, match="at least one citation"):
        FieldValueItem(value="Laptop", attributes={}, citations=[])


def test_addendum_change_keeps_previous_and_current_citations():
    previous = SourceCitation(file="base.pdf", page=1, bid_id="bid-one")
    current = SourceCitation(file="addendum-2.pdf", page=2, bid_id="bid-one")
    change = AddendumChange(
        field="Payment Terms",
        previous_value="Net 30",
        current_value="Net 45",
        previous_citations=[previous],
        current_citations=[current],
        controlling_citation=current,
        notes="Revised by Addendum 2.",
    )

    assert change.previous_citations[0].file == "base.pdf"
    assert change.current_citations[0].file == "addendum-2.pdf"
    assert change.controlling_citation.file == "addendum-2.pdf"
