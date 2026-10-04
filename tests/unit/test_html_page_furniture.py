from pathlib import Path

from src.ingestion.html_parser import parse_html


def test_html_page_blocks_remove_repeated_edge_furniture_and_keep_body(tmp_path: Path) -> None:
    source = tmp_path / "exported-pages.html"
    source.write_text(
        """<html><body>
        <div class="page"><p>District Procurement</p><p>Solicitation 42</p><p>Recurring body requirement</p><p>Page 1 of 2</p></div>
        <div class="page"><p>District Procurement</p><p>Solicitation 42</p><p>Recurring body requirement</p><p>Page 2 of 2</p></div>
        </body></html>""",
        encoding="utf-8",
    )

    page = parse_html(source, "html-pages")[0]

    assert page.normalized_text.count("Recurring body requirement") == 2
    assert "District Procurement" not in page.normalized_text
    assert "Page 1 of 2" not in page.normalized_text
    assert "Page 2 of 2" not in page.normalized_text
    assert any(item.code == "repeated_page_furniture_removed" for item in page.diagnostics)


def test_ordinary_html_repeated_paragraphs_are_not_treated_as_pages(tmp_path: Path) -> None:
    source = tmp_path / "ordinary.html"
    source.write_text(
        "<html><body><p>Recurring body requirement</p><p>Recurring body requirement</p></body></html>",
        encoding="utf-8",
    )

    page = parse_html(source, "ordinary-html")[0]

    assert page.normalized_text.count("Recurring body requirement") == 2
    assert not any(item.code == "repeated_page_furniture_removed" for item in page.diagnostics)


def test_html_page_blocks_preserve_and_diagnose_uncertain_edge_candidates(tmp_path: Path) -> None:
    source = tmp_path / "uncertain-pages.html"
    source.write_text(
        """<html><body>
        <div class="page"><p>Possible Bid Header</p><p>Header detail 1</p><p>Body content 1</p><p>Footer detail 1</p></div>
        <div class="page"><p>Possible Bid Header</p><p>Header detail 2</p><p>Body content 2</p><p>Footer detail 2</p></div>
        <div class="page"><p>Other Header 3</p><p>Header detail 3</p><p>Body content 3</p><p>Footer detail 3</p></div>
        <div class="page"><p>Other Header 4</p><p>Header detail 4</p><p>Body content 4</p><p>Footer detail 4</p></div>
        <div class="page"><p>Other Header 5</p><p>Header detail 5</p><p>Body content 5</p><p>Footer detail 5</p></div>
        </body></html>""",
        encoding="utf-8",
    )

    page = parse_html(source, "uncertain-pages")[0]

    assert page.normalized_text.count("Possible Bid Header") == 2
    assert any(item.code == "repeated_page_furniture_uncertain" for item in page.diagnostics)
