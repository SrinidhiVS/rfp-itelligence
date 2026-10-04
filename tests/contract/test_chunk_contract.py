from src.ingestion.chunking import make_chunks
from src.ingestion.models import DocumentSection, NormalizedChunk, NormalizedPage, SourceDocument
from src.ingestion.serialization import report_dict


def test_chunk_has_provenance_fields() -> None:
    chunk = NormalizedChunk("c", "bid", "doc", "page", 0, "Specs", "CPU", "text", "specs.pdf", 1, {"relative_path": "specs.pdf"})
    payload = report_dict(chunk)
    assert payload["bid_id"] == "bid"
    assert payload["source_locator"]["relative_path"] == "specs.pdf"
    assert set(payload) == {
        "chunk_id", "bid_id", "document_id", "page_id", "chunk_index", "section_title",
        "text", "content_kind", "source_file", "file_name", "page_number", "source_locator", "diagnostic_ids",
        "doc_type", "addendum_number", "document_date",
    }
    assert payload["file_name"] == payload["source_file"]


def test_section_chunk_retains_heading_and_page_provenance():
    section = DocumentSection(
        section_id="section-1",
        kind="paragraph",
        text="Submission requirements are listed here.",
        heading_level=None,
        heading_path=["Submission"],
        page_id="page-1",
        source_locator={"page_number": 3, "section_id": "section-1", "relative_path": "rfp.pdf"},
    )
    page = NormalizedPage(
        page_id="page-1",
        document_id="doc-1",
        page_number=3,
        section_title="Submission",
        raw_text=section.text,
        normalized_text=section.text,
        sections=[section],
    )
    document = SourceDocument(
        document_id="doc-1",
        bid_id="Bid1",
        file_name="rfp.pdf",
        relative_path="rfp.pdf",
        detected_format="pdf",
        doc_type="rfp",
        addendum_number=None,
        document_date=None,
        status="parsed",
        pages=[page],
    )

    payload = report_dict(make_chunks(document, "Bid1")[0])

    assert payload["section_title"] == "Submission"
    assert payload["page_number"] == 3
    assert payload["source_locator"]["relative_path"] == "rfp.pdf"
    assert payload["source_locator"]["section_id"] == "section-1"
