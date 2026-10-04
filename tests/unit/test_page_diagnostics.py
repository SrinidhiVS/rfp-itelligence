from pathlib import Path
from types import SimpleNamespace

import pymupdf

from src.ingestion.pdf_parser import parse_pdf


def test_empty_pdf_page_is_explicitly_diagnosed(tmp_path: Path) -> None:
    source = tmp_path / "empty.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(source)
    document.close()
    page = parse_pdf(source, "doc")[0]
    assert page.status == "empty"
    assert page.diagnostics[0].code == "empty_page"


def test_table_failure_preserves_page_text_and_reports_partial_status(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    class TextPage:
        def get_text(self, _kind: str) -> str:
            return "The procurement body remains usable."

        def get_images(self) -> list[object]:
            return []

        def find_tables(self) -> object:
            raise RuntimeError("table layout could not be read")

    class FakePdf:
        def __enter__(self) -> list[TextPage]:
            return [TextPage()]

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr(parser, "import_module", lambda _name: SimpleNamespace(open=lambda _path: FakePdf()))

    page = parse_pdf(Path("table-failure.pdf"), "doc")[0]

    assert page.status == "partial"
    assert page.normalized_text == "The procurement body remains usable."
    assert any(item.code == "table_parse_failure" for item in page.diagnostics)
