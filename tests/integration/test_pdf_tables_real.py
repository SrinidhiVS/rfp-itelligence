from pathlib import Path

import pytest

from src.ingestion.pdf_parser import parse_pdf


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative_path", "page_number", "row_count", "column_count", "expected_cells"),
    [
        (
            "Initial_docs/Bid1/JA-207652 Student and Staff Computing Devices FINAL.pdf",
            4,
            2,
            2,
            [("rows", 1, 0, "Tier 1 Small Student Chromebook Laptop Minimum Requirements")],
        ),
        (
            "Initial_docs/Bid2/PORFP_-_Dell_Laptop_Final.pdf",
            2,
            6,
            4,
            [("columns", 2, "Questions Due (Closing) Date and Time:"), ("columns", 2, "06/01/2024 at 2:00 PM EDT")],
        ),
        pytest.param(
            "Initial_docs/Bid3/PORFP_-_Dell_Laptop_Final.pdf",
            2,
            6,
            4,
            [("columns", 2, "Questions Due (Closing) Date and Time:"), ("columns", 2, "06/01/2024 at 2:00 PM EDT")],
            marks=pytest.mark.skipif(
                not (ROOT / "Initial_docs/Bid3/PORFP_-_Dell_Laptop_Final.pdf").is_file(),
                reason="optional Bid3 source PDF is not present",
            ),
        ),
    ],
)
def test_real_procurement_tables_retain_page_and_cell_content(
    relative_path: str,
    page_number: int,
    row_count: int,
    column_count: int,
    expected_cells: list[tuple],
) -> None:
    pages = parse_pdf(ROOT / relative_path, relative_path)
    page = pages[page_number - 1]

    assert page.page_number == page_number
    assert page.tables
    assert all(table.page_id == page.page_id for table in page.tables)
    table = page.tables[0]
    assert len(table.rows) == row_count
    assert len(table.columns) == column_count
    assert table.source_bounds is not None
    for expectation in expected_cells:
        if expectation[0] == "rows":
            _, row_index, column_index, expected_text = expectation
            cell = table.rows[row_index][column_index]
        else:
            _, column_index, expected_text = expectation
            cell = table.columns[column_index]
        assert expected_text in (cell or "")