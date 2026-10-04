from src.extraction.extractor import StructuredExtractor


def test_latest_addendum_controls_due_date():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "doc_type": "rfp", "addendum_number": None, "text": "submission deadline October 10"}},
        {"record": {"source_file": "addendum-2.pdf", "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 2, "text": "submission deadline revised October 20"}},
    ]
    record = StructuredExtractor().extract("Bid1", evidence)
    assert record.addendum_changes
    assert record.addendum_changes[0].addendum_number == 2
    assert "October 20" in record.fields["Due Date"].value


def test_due_date_change_log_preserves_source_time_and_timezone():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 2, "source_locator": "Solicitation Due", "bid_id": "Bid1", "doc_type": "rfp", "text": "Solicitation Due: June 27, 2024 at 2:00 PM CST."}},
        {"record": {"source_file": "addendum-2.pdf", "page_number": 1, "source_locator": "New due date", "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 2, "text": "The new due date for this RFP will be July 9, 2024 at 2:00 PM CST."}},
    ]

    record = StructuredExtractor().extract("Bid1", evidence)

    change = next(change for change in record.addendum_changes if change.field == "Due Date")
    assert record.fields["Due Date"].value == "2024-07-09 14:00 CST"
    assert change.previous_value == "2024-06-27 14:00 CST"
    assert change.current_value == "2024-07-09 14:00 CST"
    assert change.previous_citations[0].file == "base.pdf"
    assert change.controlling_citation.file == "addendum-2.pdf"
    assert change.addendum_number == 2
    assert not change.review_required


def test_addendum_updates_payment_terms_and_leaves_unaffected_term_unchanged():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": "payment", "bid_id": "Bid1", "doc_type": "rfp", "text": "Payment terms: Net 30."}},
        {"record": {"source_file": "base.pdf", "page_number": 2, "source_locator": "term", "bid_id": "Bid1", "doc_type": "rfp", "text": "Term of bid: Three years."}},
        {"record": {"source_file": "addendum-2.pdf", "page_number": 1, "source_locator": "revised payment", "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 2, "text": "Payment terms: Net 45."}},
    ]

    record = StructuredExtractor().extract("Bid1", evidence)

    payment_change = next(change for change in record.addendum_changes if change.field == "Payment Terms")
    assert record.fields["Payment Terms"].value == "Net 45"
    assert payment_change.previous_value == "Net 30"
    assert payment_change.current_value == "Net 45"
    assert payment_change.previous_citations[0].file == "base.pdf"
    assert payment_change.current_citations[0].file == "addendum-2.pdf"
    assert record.fields["Term of Bid"].value == "Three years"
    assert all(change.field != "Term of Bid" for change in record.addendum_changes)


def test_addendum_adds_collection_item_without_dropping_base_items():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": "required documents", "bid_id": "Bid1", "doc_type": "rfp", "text": "Required documents: Base Form."}},
        {"record": {"source_file": "addendum-1.pdf", "page_number": 2, "source_locator": "additional document", "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 1, "text": "Additional documents required: New Certificate."}},
    ]

    record = StructuredExtractor().extract("Bid1", evidence)

    field = record.fields["Any Additional Documentation Required"]
    change = next(change for change in record.addendum_changes if change.field == "Any Additional Documentation Required")
    assert [item.value for item in field.value] == ["Base Form", "New Certificate"]
    assert [item.value for item in change.previous_value] == ["Base Form"]
    assert [item.value for item in change.current_value] == ["Base Form", "New Certificate"]
    assert change.previous_citations[0].file == "base.pdf"
    assert {citation.file for citation in change.current_citations} == {"base.pdf", "addendum-1.pdf"}


def test_explicit_collection_replacement_removes_superseded_items():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": "required documents", "bid_id": "Bid1", "doc_type": "rfp", "text": "Required documents: Base Form, Insurance Certificate."}},
        {"record": {"source_file": "addendum-1.pdf", "page_number": 2, "source_locator": "replacement list", "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 1, "text": "Required documents are replaced by: New Vendor Form."}},
    ]

    record = StructuredExtractor().extract("Bid1", evidence)

    field = record.fields["Any Additional Documentation Required"]
    change = next(change for change in record.addendum_changes if change.field == "Any Additional Documentation Required")
    assert [item.value for item in field.value] == ["New Vendor Form"]
    assert [item.value for item in change.previous_value] == ["Base Form", "Insurance Certificate"]
    assert [item.value for item in change.current_value] == ["New Vendor Form"]
    assert change.previous_citations[0].file == "base.pdf"
    assert change.current_citations[0].file == "addendum-1.pdf"


def test_addendum_removes_collection_item_marked_no_longer_required():
    evidence = [
        {"record": {"source_file": "base.pdf", "page_number": 1, "source_locator": "required documents", "bid_id": "Bid1", "doc_type": "rfp", "text": "Required documents: Base Form, Insurance Certificate."}},
        {"record": {"source_file": "addendum-1.pdf", "page_number": 2, "source_locator": "removed requirement", "bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 1, "text": "Base Form is no longer required."}},
    ]

    record = StructuredExtractor().extract("Bid1", evidence)

    field = record.fields["Any Additional Documentation Required"]
    change = next(change for change in record.addendum_changes if change.field == "Any Additional Documentation Required")
    assert [item.value for item in field.value] == ["Insurance Certificate"]
    assert [item.value for item in change.previous_value] == ["Base Form", "Insurance Certificate"]
    assert [item.value for item in change.current_value] == ["Insurance Certificate"]
    assert change.controlling_citation.file == "addendum-1.pdf"
