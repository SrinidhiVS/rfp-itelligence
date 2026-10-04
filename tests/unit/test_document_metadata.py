from pathlib import Path

import pymupdf

from src.ingestion.html_parser import parse_html
from src.ingestion.pipeline import IngestionPipeline


def test_html_parser_retains_metadata_values_and_provenance(tmp_path: Path) -> None:
    source = tmp_path / "bid.html"
    source.write_text(
        """<!doctype html>
        <html lang="en"><head>
        <title>Device Procurement</title>
        <link rel="canonical" href="https://example.gov/bids/42">
        <meta name="description" content="Student and staff computing devices">
        <meta property="article:published_time" content="2025-06-10T10:30:00-04:00">
        <meta property="article:modified_time" content="2025-06-12T09:00:00-04:00">
        </head><body><h1>Computing Devices</h1><p>Open solicitation.</p></body></html>""",
        encoding="utf-8",
    )

    page = parse_html(source, "doc")[0]

    assert page.metadata is not None
    assert page.metadata.title == "Device Procurement"
    assert page.metadata.canonical_url == "https://example.gov/bids/42"
    assert page.metadata.description == "Student and staff computing devices"
    assert page.metadata.language == "en"
    assert any(value.key == "description" and value.source_locator.get("tag") == "meta" for value in page.metadata.values)
    published = next(candidate for candidate in page.metadata.date_candidates if candidate.source_kind == "semantic_metadata")
    assert published.raw_value == "2025-06-10T10:30:00-04:00"
    assert published.normalized_date == "2025-06-10"
    assert published.source_locator.get("source_line") is not None


def test_pipeline_prefers_published_metadata_and_reports_lower_rank_conflict(tmp_path: Path) -> None:
    source = tmp_path / "bid.html"
    source.write_text(
        """<html><head>
        <meta property="datePublished" content="2025-06-10">
        </head><body><h1>Device Procurement</h1>
        <p>Published: June 11, 2025</p><p>Delivery is required.</p>
        </body></html>""",
        encoding="utf-8",
    )

    report = IngestionPipeline().process(tmp_path, bid_id="metadata-bid")
    document = report.files[0]

    assert document.document_date == "2025-06-10"
    assert document.metadata is not None
    assert document.metadata.selected_document_date == "2025-06-10"
    assert report.pages[0].metadata is document.metadata
    assert report.pages[0].document_date == "2025-06-10"
    assert report.chunks[0].document_date == "2025-06-10"
    conflict = next(item for item in document.diagnostics if item.code == "document_date_conflict")
    assert conflict.affects_completeness is False


def test_equal_priority_publication_dates_remain_unselected_and_conflicting(tmp_path: Path) -> None:
    source = tmp_path / "conflicting-dates.html"
    source.write_text(
        """<html><head>
        <meta property="datePublished" content="2025-06-10">
        <meta property="article:published_time" content="2025-06-12">
        </head><body><h1>Procurement notice</h1></body></html>""",
        encoding="utf-8",
    )

    document = IngestionPipeline().process(tmp_path, bid_id="date-conflict").files[0]

    assert document.document_date is None
    assert document.metadata is not None
    assert [candidate.raw_value for candidate in document.metadata.date_candidates if candidate.status == "conflicting"] == [
        "2025-06-10", "2025-06-12"
    ]
    assert any(item.code == "document_date_conflict" for item in document.diagnostics)


def test_pipeline_does_not_select_ambiguous_numeric_date(tmp_path: Path) -> None:
    source = tmp_path / "bid.html"
    source.write_text("<html><body><h1>Bid</h1><p>Issue date: 01/02/2025</p></body></html>", encoding="utf-8")

    report = IngestionPipeline().process(tmp_path, bid_id="ambiguous-date")
    document = report.files[0]

    assert document.document_date is None
    assert document.metadata is not None
    assert document.metadata.date_candidates[0].status == "ambiguous"
    ambiguity = next(item for item in document.diagnostics if item.code == "document_date_ambiguous")
    assert ambiguity.affects_completeness is False


def test_modified_metadata_does_not_override_visible_publication_date(tmp_path: Path) -> None:
    source = tmp_path / "bid.html"
    source.write_text(
        """<html><head><meta property="dateModified" content="2025-06-12"></head>
        <body><p>Published: June 11, 2025</p><p>Bid requirements.</p></body></html>""",
        encoding="utf-8",
    )

    document = IngestionPipeline().process(tmp_path, bid_id="modified-date").files[0]

    assert document.document_date == "2025-06-11"
    assert document.metadata is not None
    modified = next(candidate for candidate in document.metadata.date_candidates if candidate.source_kind == "modified_metadata")
    assert modified.status == "technical_only"


def test_malformed_or_missing_html_metadata_does_not_discard_content(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.html"
    malformed.write_text(
        '<html><head><link rel="canonical" href="/relative/path"></head><body><h1>Usable Bid</h1></body></html>',
        encoding="utf-8",
    )
    missing = tmp_path / "missing.html"
    missing.write_text("<html><body><h1>Another Usable Bid</h1></body></html>", encoding="utf-8")

    malformed_page = parse_html(malformed, "malformed")[0]
    missing_page = parse_html(missing, "missing")[0]

    assert "Usable Bid" in malformed_page.normalized_text
    assert any(item.code == "html_metadata_invalid" for item in malformed_page.diagnostics)
    assert "Another Usable Bid" in missing_page.normalized_text
    assert any(item.code == "html_metadata_missing" for item in missing_page.diagnostics)


def test_pdf_info_timestamps_are_retained_but_not_selected(tmp_path: Path) -> None:
    source = tmp_path / "procurement.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Procurement requirements are listed below.")
    metadata = pdf.metadata
    metadata["title"] = "Procurement Request"
    metadata["creationDate"] = "D:20240101120000Z"
    metadata["modDate"] = "D:20240201120000Z"
    pdf.set_metadata(metadata)
    pdf.save(source)
    pdf.close()

    report = IngestionPipeline().process(tmp_path, bid_id="pdf-metadata")
    document = report.files[0]

    assert document.document_date is None
    assert document.metadata is not None
    technical_dates = [candidate for candidate in document.metadata.date_candidates if candidate.source_kind == "technical_timestamp"]
    assert {candidate.raw_value for candidate in technical_dates} >= {"D:20240101120000Z", "D:20240201120000Z"}
    assert all(candidate.status == "technical_only" for candidate in technical_dates)
    assert any(candidate.source_locator.get("filesystem_field") == "mtime" for candidate in technical_dates)


def test_metadata_and_section_locators_use_document_relative_paths(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    html_source = nested / "bid.html"
    html_source.write_text(
        """<html><head><title>Bid</title><meta property="datePublished" content="2025-06-10"></head>
        <body><h1>Requirements</h1><p>Devices are required.</p></body></html>""",
        encoding="utf-8",
    )
    pdf_source = nested / "terms.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Terms apply.")
    metadata = pdf.metadata
    metadata["title"] = "Terms"
    metadata["creationDate"] = "D:20240101120000Z"
    pdf.set_metadata(metadata)
    pdf.save(pdf_source)
    pdf.close()

    report = IngestionPipeline().process(tmp_path, bid_id="relative-provenance")

    for document in report.files:
        assert document.metadata is not None
        for value in document.metadata.values:
            assert value.source_locator["relative_path"] == document.relative_path
        for candidate in document.metadata.date_candidates:
            if "relative_path" in candidate.source_locator:
                assert candidate.source_locator["relative_path"] == document.relative_path
        for page in document.pages:
            for section in page.sections:
                assert section.source_locator["relative_path"] == document.relative_path