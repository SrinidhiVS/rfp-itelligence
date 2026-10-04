from src.extraction.extractor import StructuredExtractor
from src.extraction.models import AddendumChange, ExtractedField, FieldValueItem, SourceCitation
from src.extraction.serialization import read_record, write_record


def test_record_json_round_trip(tmp_path):
    record = StructuredExtractor().extract("Bid1", [])
    path = write_record(record, tmp_path)
    loaded = read_record(path)
    assert loaded.bid_id.isdigit()
    assert len(loaded.bid_id) == 12
    assert len(loaded.fields) == 20


def test_item_and_addendum_evidence_round_trip(tmp_path):
    record = StructuredExtractor().extract("Bid1", [])
    item_citation = SourceCitation(file="products.pdf", page=2, bid_id=record.bid_id, excerpt="12 laptops")
    record.fields["Product"] = ExtractedField(
        name="Product",
        value=[FieldValueItem(value="Laptop", attributes={"quantity": 12}, citations=[item_citation])],
        citations=[item_citation],
        confidence=0.9,
        status="supported",
    )
    base_citation = SourceCitation(file="base.pdf", page=1, bid_id=record.bid_id)
    addendum_citation = SourceCitation(file="addendum-2.pdf", page=2, bid_id=record.bid_id)
    record.addendum_changes = [
        AddendumChange(
            field="Payment Terms",
            previous_value="Net 30",
            current_value="Net 45",
            previous_citations=[base_citation],
            current_citations=[addendum_citation],
            controlling_citation=addendum_citation,
            notes="Revised by Addendum 2.",
        )
    ]

    loaded = read_record(write_record(record, tmp_path))

    assert isinstance(loaded.fields["Product"].value, list)
    assert len(loaded.fields["Product"].value) == 1
    assert loaded.fields["Product"].value[0]["citations"][0]["file"] == "products.pdf"
    assert loaded.addendum_changes[0].previous_citations[0].file == "base.pdf"
    assert loaded.addendum_changes[0].current_citations[0].file == "addendum-2.pdf"
