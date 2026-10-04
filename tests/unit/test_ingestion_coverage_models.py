from src.ingestion.models import (
    ClassificationEvidence,
    DocumentClassification,
    DocumentSection,
    ExtractedTable,
    HtmlSection,
    NormalizedChunk,
    NormalizedPage,
    ProcessingDiagnostic,
    RetentionItem,
    RetentionManifest,
    RetentionMeasurement,
    RetentionReport,
)


def test_identity_classification_section_and_table_fields_are_additive() -> None:
    evidence = ClassificationEvidence("e1", "doc_type", "rfp", "content", {"page_number": 1}, "explicit")
    classification = DocumentClassification("rfp", None, "classified", [evidence], "e1")
    page = NormalizedPage(
        "page", "doc", 1, "Requirements", "raw", "text",
        bid_id="Bid1", file_name="generic.pdf", classification=classification,
        sections=[DocumentSection("s1", "heading", "Requirements", 1, ["Requirements"], "page", None, {}, "explicit")],
    )
    chunk = NormalizedChunk("c1", "Bid1", "doc", "page", 0, "Requirements", "text", "text", "generic.pdf", 1, {}, file_name="generic.pdf")
    table = ExtractedTable("t1", "page", None, [None, None], [["Item", "Value"]], has_header=False)

    assert page.bid_id == chunk.bid_id == "Bid1"
    assert page.file_name == chunk.file_name == chunk.source_file == "generic.pdf"
    assert page.classification.status == "classified"
    assert page.sections[0].kind == "heading"
    assert HtmlSection is DocumentSection
    assert table.has_header is False
    assert table.rows == [["Item", "Value"]]


def test_diagnostic_recovery_and_retention_entities() -> None:
    diagnostic = ProcessingDiagnostic("d1", "page", "page_text_extraction_failure", "failed", recovery_status="partial")
    manifest = RetentionManifest("1.0", "fixture-corpus", [{"file_name": "bid.html"}], [], [])
    measurement = RetentionMeasurement(2, 1, 0, 1, 0.5)
    item = RetentionItem("text_span", "bid.html", "uncertain", {"page_number": 1}, "Expected clause")
    report = RetentionReport("fixture-corpus", "1.0", measurement, RetentionMeasurement(0, 0, 0, 0, None), [item])

    assert diagnostic.recovery_status == "partial"
    assert manifest.corpus_name == report.corpus_name
    assert report.text.coverage == 0.5
    assert report.tables.coverage is None
    assert report.items[0].status == "uncertain"
