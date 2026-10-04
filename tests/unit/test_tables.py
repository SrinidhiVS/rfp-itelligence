from pathlib import Path

from src.ingestion.chunking import make_chunks
from src.ingestion.html_parser import parse_html
from src.ingestion.models import SourceDocument
from src.ingestion.tables import table_from_rows


def test_table_preserves_blank_cells_and_rows() -> None:
    table = table_from_rows("page", 0, [["Field", "Value"], ["CPU", ""], ["RAM", None]])
    assert table.columns == ["Field", "Value"]
    assert table.rows == [["CPU", ""], ["RAM", None]]


def test_table_marks_inconsistent_rows_partial() -> None:
    table = table_from_rows("page", 1, [["Field", "Value"], ["CPU"]])
    assert table.status == "partial"
    assert table.diagnostics[0].code == "table_uncertain"


def test_headerless_table_preserves_first_row_as_data() -> None:
    table = table_from_rows(
        "page", 2, [["Model A", "16 GB"], ["Model B", "32 GB"]], has_header=False
    )

    assert table.has_header is False
    assert table.columns == [None, None]
    assert table.rows == [["Model A", "16 GB"], ["Model B", "32 GB"]]


def test_unknown_header_status_preserves_first_row_and_blank_cells() -> None:
    table = table_from_rows("page", 3, [["", "Price"], ["Laptop", ""]], has_header=None)

    assert table.has_header is None
    assert table.columns == [None, None]
    assert table.rows == [["", "Price"], ["Laptop", ""]]


def test_html_table_values_and_source_location_are_preserved() -> None:
    fixture = Path("tests/fixtures/robustness/table-document.html")
    pages = parse_html(fixture, "robustness-table")
    table = pages[0].tables[0]
    table_section = next(section for section in pages[0].sections if section.kind == "table")
    document = SourceDocument(
        "robustness-table",
        "RobustDocs",
        fixture.name,
        "procurement/table-document.html",
        "html",
        "rfp",
        None,
        None,
        "parsed",
        pages=pages,
    )

    table_chunk = next(chunk for chunk in make_chunks(document, "RobustDocs") if chunk.content_kind == "table")

    assert table.has_header is True
    assert table.columns == ["Requirement", "Value"]
    assert table.rows == [
        ["Submission deadline", "September 30, 2026"],
        ["Product", "Portable Air Monitor"],
    ]
    assert table_section.source_locator["element_index"] is not None
    assert table_chunk.source_locator["table_id"] == table.table_id
    assert table_chunk.source_locator["relative_path"] == "procurement/table-document.html"
    assert table_chunk.source_locator["element_index"] == table_section.source_locator["element_index"]
