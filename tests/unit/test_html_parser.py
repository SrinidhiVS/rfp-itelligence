from pathlib import Path

from src.ingestion.html_parser import parse_html


def test_html_parser_preserves_heading_and_table(tmp_path: Path) -> None:
    source = tmp_path / "bid.html"
    source.write_text("<html><body><h1>Bid</h1><p>Deadline</p><table><tr><th>Field</th><th>Value</th></tr><tr><td>A</td><td>B</td></tr></table></body></html>", encoding="utf-8")
    page = parse_html(source, "doc")[0]
    assert page.section_title == "Bid"
    assert page.normalized_text == "Bid\nDeadline\nField Value A B"
    assert page.tables[0].rows == [["A", "B"]]


def test_html_parser_retains_nested_structure_and_source_order(tmp_path: Path) -> None:
    source = tmp_path / "structured-bid.html"
    source.write_text(
        """<html><body>
        <h1>Solicitation</h1>
        <section><h2>Scope</h2><p>Provide devices.</p><div>Supplemental terms apply.</div>
        <ul><li>Warranty</li><li>Support</li></ul>
        <table><tr><th>Field</th><th>Value</th></tr><tr><td>Term</td><td>Three years</td></tr></table>
        </section></body></html>""",
        encoding="utf-8",
    )

    page = parse_html(source, "doc")[0]

    assert [section.kind for section in page.sections] == [
        "heading", "heading", "paragraph", "other", "list_item", "list_item", "table"
    ]
    scope = page.sections[2]
    assert scope.heading_path == ["Solicitation", "Scope"]
    assert all("element_index" in section.source_locator for section in page.sections)
    assert page.sections[-1].table_id == page.tables[0].table_id
    assert "Provide devices." in page.normalized_text
    assert "Supplemental terms apply." in page.normalized_text


def test_html_parser_keeps_distinct_paragraph_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "paragraph-boundaries.html"
    source.write_text(
        "<html><body><p>The contract must remain</p><p>subject to review when schedules change</p></body></html>",
        encoding="utf-8",
    )

    page = parse_html(source, "doc")[0]

    assert page.normalized_text == "The contract must remain\nsubject to review when schedules change"


def test_headerless_html_table_preserves_first_row_as_data(tmp_path: Path) -> None:
    source = tmp_path / "headerless.html"
    source.write_text(
        "<html><body><table><tr><td>Model A</td><td>16 GB</td></tr><tr><td>Model B</td><td>32 GB</td></tr></table></body></html>",
        encoding="utf-8",
    )

    table = parse_html(source, "headerless-doc")[0].tables[0]

    assert table.has_header is False
    assert table.columns == [None, None]
    assert table.rows == [["Model A", "16 GB"], ["Model B", "32 GB"]]
