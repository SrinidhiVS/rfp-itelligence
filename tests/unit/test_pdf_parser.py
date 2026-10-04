from pathlib import Path
from types import SimpleNamespace

import pymupdf

from src.ingestion.chunking import make_chunks
from src.ingestion.models import SourceDocument
from src.ingestion.pdf_parser import parse_pdf


def test_pdf_parser_preserves_page_text(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Bid deadline")
    document.save(source)
    document.close()
    pages = parse_pdf(source, "doc")
    assert pages[0].page_number == 1
    assert "Bid deadline" in pages[0].normalized_text


class FakePdf:
    def __init__(self, pages: list[object]) -> None:
        self.pages = pages

    def __enter__(self) -> list[object]:
        return self.pages

    def __exit__(self, *_: object) -> None:
        return None


class FakePage:
    def __init__(self, table_finder: object | None = None) -> None:
        self.table_finder = table_finder

    def get_text(self, _kind: str) -> str:
        return "Procurement body text"

    def get_images(self) -> list[object]:
        return []

    def find_tables(self) -> object:
        if isinstance(self.table_finder, Exception):
            raise self.table_finder
        return self.table_finder


class FakePageWithoutTableSupport:
    def get_text(self, _kind: str) -> str:
        return "Procurement body text"

    def get_images(self) -> list[object]:
        return []


def test_pdf_parser_reports_unavailable_table_extractor(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    page = FakePageWithoutTableSupport()
    fake_module = SimpleNamespace(open=lambda _path: FakePdf([page]))
    monkeypatch.setattr(parser, "import_module", lambda _name: fake_module)

    result = parse_pdf(Path("unavailable.pdf"), "doc")[0]

    assert result.status == "partial"
    assert any(item.code == "table_extraction_unavailable" for item in result.diagnostics)


def test_pdf_parser_reports_empty_detected_table(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    empty_table = SimpleNamespace(extract=lambda: [])
    page = FakePage(SimpleNamespace(tables=[empty_table]))
    fake_module = SimpleNamespace(open=lambda _path: FakePdf([page]))
    monkeypatch.setattr(parser, "import_module", lambda _name: fake_module)

    result = parse_pdf(Path("empty-table.pdf"), "doc")[0]

    assert result.status == "partial"
    assert any(item.code == "table_empty" for item in result.diagnostics)


def test_pdf_parser_continues_after_one_table_extraction_fails(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    broken_table = SimpleNamespace(extract=lambda: (_ for _ in ()).throw(ValueError("bad table")))
    good_table = SimpleNamespace(
        extract=lambda: [["Field", "Value"], ["Term", "Three years"]],
        bbox=(1, 2, 3, 4),
        header=SimpleNamespace(names=["Field", "Value"], external=False),
    )
    page = FakePage(SimpleNamespace(tables=[broken_table, good_table]))
    fake_module = SimpleNamespace(open=lambda _path: FakePdf([page]))
    monkeypatch.setattr(parser, "import_module", lambda _name: fake_module)

    result = parse_pdf(Path("partial-table.pdf"), "doc")[0]

    assert result.status == "partial"
    assert len(result.tables) == 1
    assert result.tables[0].rows == [["Term", "Three years"]]
    assert any(item.code == "table_parse_failure" for item in result.diagnostics)


def test_pdf_parser_removes_repeated_edge_lines_and_records_diagnostics(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    class TextPage:
        def __init__(self, page_number: int) -> None:
            self.text = (
                f"District Procurement | Page {page_number} of 2\n"
                "Bid requirements\n"
                "Product requirement applies\n"
                "Confidential"
            )

        def get_text(self, _kind: str) -> str:
            return self.text

        def get_images(self) -> list[object]:
            return []

        def find_tables(self) -> object:
            return SimpleNamespace(tables=[])

    fake_module = SimpleNamespace(open=lambda _path: FakePdf([TextPage(1), TextPage(2)]))
    monkeypatch.setattr(parser, "import_module", lambda _name: fake_module)

    results = parse_pdf(Path("multi-page.pdf"), "doc")

    assert all("District Procurement" not in page.normalized_text for page in results)
    assert all("Confidential" not in page.normalized_text for page in results)
    assert all("Product requirement applies" in page.normalized_text for page in results)
    assert all(any(item.code == "repeated_page_furniture_removed" for item in page.diagnostics) for page in results)


def test_pdf_parser_continues_after_page_text_extraction_failure(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    class FailedTextPage(FakePage):
        def get_text(self, _kind: str) -> str:
            raise RuntimeError("page text is unavailable")

    failed_page_table = SimpleNamespace(
        extract=lambda: [["Field", "Value"], ["Term", "Three years"]],
        header=SimpleNamespace(names=["Field", "Value"], external=False),
    )
    first = FailedTextPage(SimpleNamespace(tables=[failed_page_table]))
    second = FakePage(SimpleNamespace(tables=[]))
    fake_module = SimpleNamespace(open=lambda _path: FakePdf([first, second]))
    monkeypatch.setattr(parser, "import_module", lambda _name: fake_module)

    results = parse_pdf(Path("one-page-failure.pdf"), "doc")

    assert len(results) == 2
    assert results[0].status == "partial"
    assert any(item.code == "page_text_extraction_failure" for item in results[0].diagnostics)
    assert results[0].tables[0].rows == [["Term", "Three years"]]
    assert results[1].normalized_text == "Procurement body text"


def test_pdf_parser_traverses_document_pages_once(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    class CountingPdf:
        def __init__(self) -> None:
            self.pages = [FakePage(SimpleNamespace(tables=[])), FakePage(SimpleNamespace(tables=[]))]
            self.iterations = 0

        def __enter__(self) -> "CountingPdf":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def __iter__(self):
            self.iterations += 1
            return iter(self.pages)

    pdf = CountingPdf()
    fake_module = SimpleNamespace(open=lambda _path: pdf)
    monkeypatch.setattr(parser, "import_module", lambda _name: fake_module)

    results = parse_pdf(Path("one-pass.pdf"), "doc")

    assert len(results) == 2
    assert pdf.iterations == 1


def test_pdf_parser_extracts_heading_hierarchy_and_continuation_context(tmp_path: Path) -> None:
    source = tmp_path / "sections.pdf"
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 45), "REQUEST FOR PROPOSAL", fontsize=22, fontname="hebo")
    first.insert_text((72, 95), "Section 1 - General Information", fontsize=16, fontname="hebo")
    first.insert_text((72, 125), "The agency requests information from suppliers.", fontsize=10)
    second = document.new_page()
    second.insert_text((72, 72), "Additional supplier information follows.", fontsize=10)
    document.save(source)
    document.close()

    pages = parse_pdf(source, "sections-doc")
    heading_sections = [section for section in pages[0].sections if section.kind == "heading"]

    assert [section.text for section in heading_sections] == [
        "REQUEST FOR PROPOSAL", "Section 1 - General Information"
    ]
    assert heading_sections[1].heading_path == ["REQUEST FOR PROPOSAL", "Section 1 - General Information"]
    assert pages[1].section_title == "Section 1 - General Information"
    assert pages[1].sections[0].heading_path == ["REQUEST FOR PROPOSAL", "Section 1 - General Information"]
    assert all(section.source_locator.get("page_number") == page.page_number for page in pages for section in page.sections)


def test_pdf_parser_uses_confirmed_internal_table_header(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    table = SimpleNamespace(
        header=SimpleNamespace(names=["Item", "Amount"], external=False),
        extract=lambda: [["Item", "Amount"], ["Laptop", "$900"]],
        bbox=(1, 2, 3, 4),
    )
    page = FakePage(SimpleNamespace(tables=[table]))
    monkeypatch.setattr(parser, "import_module", lambda _name: SimpleNamespace(open=lambda _path: FakePdf([page])))

    extracted = parse_pdf(Path("headered.pdf"), "doc")[0].tables[0]

    assert extracted.has_header is True
    assert extracted.columns == ["Item", "Amount"]
    assert extracted.rows == [["Laptop", "$900"]]


def test_pdf_parser_preserves_headerless_and_external_header_rows(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    headerless_table = SimpleNamespace(
        header=SimpleNamespace(names=[], external=False),
        extract=lambda: [["Model A", "16 GB"], ["Model B", "32 GB"]],
        bbox=(1, 2, 3, 4),
    )
    external_header_table = SimpleNamespace(
        header=SimpleNamespace(names=["Item", "Amount"], external=True),
        extract=lambda: [["Laptop", "$900"]],
        bbox=(1, 2, 3, 4),
    )
    pages = [
        FakePage(SimpleNamespace(tables=[headerless_table])),
        FakePage(SimpleNamespace(tables=[external_header_table])),
    ]
    monkeypatch.setattr(parser, "import_module", lambda _name: SimpleNamespace(open=lambda _path: FakePdf(pages)))

    results = parse_pdf(Path("mixed-headers.pdf"), "doc")
    headerless, external = results[0].tables[0], results[1].tables[0]

    assert headerless.has_header is False
    assert headerless.columns == [None, None]
    assert headerless.rows == [["Model A", "16 GB"], ["Model B", "32 GB"]]
    assert external.has_header is True
    assert external.columns == ["Item", "Amount"]
    assert external.rows == [["Laptop", "$900"]]


def test_pdf_table_uses_heading_at_source_position_and_remains_in_reading_order(monkeypatch) -> None:
    import src.ingestion.pdf_parser as parser

    def text_block(text, y, size, font="Arial"):
        return {
            "type": 0,
            "bbox": [72, y, 500, y + 18],
            "lines": [{
                "bbox": [72, y, 500, y + 18],
                "spans": [{"text": text, "size": size, "font": font, "flags": 16 if "Bold" in font else 0}],
            }],
        }

    table = SimpleNamespace(
        extract=lambda: [["Item", "Value"], ["Warranty", "Three years"]],
        bbox=(72, 120, 500, 160),
        header=SimpleNamespace(names=["Item", "Value"], external=False),
    )

    class LayoutPage:
        def get_text(self, kind):
            if kind == "dict":
                return {"blocks": [
                    text_block("Section One", 50, 16, "Arial-Bold"),
                    text_block("Before the table.", 80, 10),
                    text_block("Section Two", 180, 16, "Arial-Bold"),
                    text_block("After the table.", 210, 10),
                ]}
            return "Section One\nBefore the table.\nSection Two\nAfter the table."

        def find_tables(self):
            return SimpleNamespace(tables=[table])

    monkeypatch.setattr(parser, "import_module", lambda _name: SimpleNamespace(open=lambda _path: FakePdf([LayoutPage()])))

    page = parse_pdf(Path("table-section.pdf"), "doc")[0]
    document = SourceDocument(
        "doc", "Bid1", "table-section.pdf", "table-section.pdf", "pdf", "rfp", None, None,
        "parsed", pages=[page],
    )
    chunks = make_chunks(document, "Bid1")

    assert [(chunk.content_kind, chunk.section_title) for chunk in chunks] == [
        ("text", "Section One"),
        ("table", "Section One"),
        ("text", "Section Two"),
    ]
    assert chunks[1].source_locator["table_id"] == page.tables[0].table_id
    assert chunks[1].source_locator["page_number"] == 1
