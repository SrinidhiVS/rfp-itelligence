from src.ingestion.models import (
    BidFolder,
    DateCandidate,
    DocumentMetadata,
    ExtractedTable,
    HtmlSection,
    MetadataValue,
    NormalizedChunk,
    NormalizedPage,
    ProcessingDiagnostic,
    SourceDocument,
)
from src.ingestion.serialization import report_dict


def test_contract_serializes_required_fields() -> None:
    report = BidFolder("Bid1", "/tmp/Bid1", "complete", 0, 0, 0)
    payload = report_dict(report)
    assert payload["bid_id"] == "Bid1"
    assert set(("documents", "pages", "tables", "chunks", "diagnostics")) <= payload.keys()
    diagnostic = ProcessingDiagnostic("d1", "file", "unsupported_format", "unsupported")
    assert report_dict(diagnostic)["diagnostic_id"] == "d1"
    chunk = NormalizedChunk("c1", "Bid1", "doc", None, 0, None, "text", "text", "a.html", None, {})
    assert report_dict(chunk)["source_file"] == "a.html"


def test_structured_metadata_fields_are_optional_and_defaulted() -> None:
    page = NormalizedPage("page", "doc", None, None, "raw", "normalized")
    document = SourceDocument("doc", "bid", "bid.html", "bid.html", "html", None, None, None, "parsed")

    assert page.sections == []
    assert page.metadata is None
    assert document.metadata is None


def test_report_serializes_structured_metadata_sections_and_tables() -> None:
    metadata = DocumentMetadata(
        title="Bid",
        canonical_url="https://example.gov/bid/1",
        values=[MetadataValue("description", "Devices", "html_meta", {"tag": "meta"})],
        selected_document_date="2025-06-10",
        date_candidates=[DateCandidate("2025-06-10", "2025-06-10", "semantic_metadata", {}, 0, "selected")],
    )
    page = NormalizedPage(
        "page", "doc", None, "Bid", "raw", "Bid", metadata=metadata,
        sections=[HtmlSection("section", "heading", "Bid", 1, ["Bid"], "page")],
    )
    table = ExtractedTable("table", "page", None, ["Field"], [["Value"]])
    document = SourceDocument("doc", "bid", "bid.html", "bid.html", "html", None, None, "2025-06-10", "parsed", [page], [], metadata)
    report = BidFolder("bid", ".", "complete", 1, 1, 0, [document], [page], [table])

    payload = report_dict(report)

    assert payload["documents"][0]["metadata"]["canonical_url"] == "https://example.gov/bid/1"
    assert payload["pages"][0]["sections"][0]["heading_path"] == ["Bid"]
    assert payload["tables"][0]["rows"] == [["Value"]]
