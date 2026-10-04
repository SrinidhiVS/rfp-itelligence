from src.extraction.extractor import StructuredExtractor
from src.extraction.normalization import normalize_value


def evidence(text, source="rfp.pdf", doc_type="rfp", addendum_number=None):
    return [{"record": {"source_file": source, "page_number": 1, "source_locator": {}, "bid_id": "Bid1", "doc_type": doc_type, "addendum_number": addendum_number, "text": text}}]


def test_supported_field_has_value_citation_and_confidence():
    record = StructuredExtractor().extract("Bid1", evidence("submission deadline October 20 2026"))
    field = record.fields["Due Date"]
    assert field.value is not None
    assert field.citations[0].file == "rfp.pdf"
    assert 0 <= field.confidence <= 1


def test_missing_field_is_explicit():
    record = StructuredExtractor().extract("Bid1", evidence("unrelated content"))
    field = record.fields["Due Date"]
    assert field.value is None
    assert field.citations == []
    assert field.confidence == 0.0
    assert "Not found" in field.notes


def test_due_date_normalizes_date_time_and_preserves_timezone():
    value = normalize_value("Due Date", "Bid submission deadline: June 3, 2026 at 2:00 PM CST.")

    assert value == "2026-06-03 14:00 CST"


def test_delivery_window_preserves_range_instead_of_treating_it_as_due_date():
    value = normalize_value("Delivery Date", "Delivery window: July 10-15, 2026.")

    assert value == "July 10-15, 2026"


def test_installation_negative_is_not_lost_as_a_keyword_match():
    value = normalize_value("Installation", "Installation is not required.")

    assert value is False


def test_submission_type_normalizes_method_without_passage_noise():
    value = normalize_value("Bid Submission Type", "Submit proposals electronically through the procurement portal.")

    assert value == "Electronic portal"


def test_numeric_proposal_due_date_normalizes_without_using_question_deadline():
    value = normalize_value("Due Date", "PROPOSAL DUE DATE: 06/10/2024")

    assert value == "2024-06-10"


def test_term_normalizes_initial_period_and_renewal_options():
    text = "Initial Term:\n3\nRenewal 1:\n1\nRenewal 2:\n1\nThe term shall not exceed a total of 5 years."

    assert normalize_value("Term of Bid", text) == "3-year initial term with two 1-year renewals; maximum 5 years"


def test_emma_submission_and_delivery_window_are_field_specific():
    method = normalize_value("Bid Submission Type", "Responses will only be accepted through the State's eMMA e-Procurement system.")
    delivery = normalize_value("Delivery Date", "Delivery within 45 days of Award.")

    assert method == "eMMA e-Procurement system"
    assert delivery == "Within 45 days of award"


def test_rfp_header_normalizes_solicitation_title():
    title = normalize_value("Title", "Request For Proposal 168884\nJA-207652 Student and Staff Computing Devices")

    assert title == "Student and Staff Computing Devices"


def test_labeled_title_excludes_appended_portal_badge():
    assert normalize_value("Title", "Title:\nPortable Computers **SOURCING #123456**") == "Portable Computers"


def test_leading_bid_identifier_is_cited_without_a_label():
    record = StructuredExtractor().extract("Bid1", evidence("JA-207652 Student Computing Devices"))
    assert record.fields["Bid Number"].value == "JA-207652"
    assert record.fields["Bid Number"].citations[0].file == "rfp.pdf"
