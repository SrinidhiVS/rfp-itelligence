from pathlib import Path

from src.ingestion.classification import classify, classify_document


def test_procurement_document_types() -> None:
    assert classify(Path("Student RFP Final.pdf")) == "rfp"
    assert classify(Path("Addendum 2.pdf")) == "addendum"
    assert classify(Path("Contract Affidavit.pdf")) == "affidavit"
    assert classify(Path("Laptop Specs.pdf")) == "specs"
    assert classify(Path("supporting.pdf")) == "supporting"


def test_explicit_content_classification_overrides_filename_evidence() -> None:
    classification = classify_document(
        Path("Addendum 1 RFP.pdf"),
        "ADDENDUM NO. 2 TO THE REQUEST FOR PROPOSAL",
    )

    assert classification.doc_type == "addendum"
    assert classification.addendum_number == 2
    assert classification.status == "classified"
    assert any(item.source_kind == "content" and item.strength == "explicit" for item in classification.evidence)
    assert any(item.source_kind == "filename" for item in classification.evidence)


def test_addendum_heading_outranks_underlying_rfp_identifier() -> None:
    classification = classify_document(
        Path("Addendum 2 RFP JA-207652.pdf"),
        "Page 1 | 1\nADDENDUM No. 2\nRFP JA-207652 Student and Staff Computing Devices\n"
        "The Purpose of this Addendum is to extend the due date of this RFP.",
    )

    assert classification.doc_type == "addendum"
    assert classification.addendum_number == 2
    assert classification.status == "classified"


def test_conflicting_explicit_addendum_numbers_remain_unresolved() -> None:
    classification = classify_document(
        Path("Addendum 1.pdf"),
        "ADDENDUM NO. 2\nADDENDUM NO. 3",
    )

    assert classification.doc_type == "addendum"
    assert classification.addendum_number is None
    assert classification.status == "conflict"
    assert {item.candidate_value for item in classification.evidence if item.field == "addendum_number"} >= {1, 2, 3}


def test_filename_only_classification_is_not_promoted_to_content_evidence() -> None:
    classification = classify_document(Path("generic.pdf"), "This file contains procurement requirements.")

    assert classification.doc_type is None
    assert classification.addendum_number is None
    assert classification.status == "unknown"


def test_generic_html_extension_alone_does_not_classify_as_bid_page() -> None:
    classification = classify_document(Path("generic.html"), "Plain text without a document classification label.")

    assert classification.doc_type is None
    assert classification.status == "unknown"


def test_explicit_title_evidence_outranks_incidental_body_mentions() -> None:
    classification = classify_document(
        Path("Technical Specifications.pdf"),
        "REQUEST FOR PROPOSAL\nThe proposal requires a contract affidavit and technical specifications.",
    )

    assert classification.doc_type == "rfp"
    assert classification.status == "classified"
    selected = next(item for item in classification.evidence if item.evidence_id == classification.selected_evidence_id)
    assert selected.field == "doc_type"
    assert selected.candidate_value == "rfp"
    assert selected.strength == "explicit"
