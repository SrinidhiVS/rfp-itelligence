import json
from pathlib import Path

from src.ingestion.html_parser import parse_html


def test_labeled_text_and_table_retention_metrics() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance"
    expected = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    page = parse_html(root / "retention.html", "acceptance")[0]
    text_hits = sum(value in (page.normalized_text or "") for value in expected["expected_text"])
    table_hits = sum(any(value in (cell or "") for row in table.rows for cell in row) for value, table in zip(expected["expected_tables"], page.tables))
    assert text_hits / len(expected["expected_text"]) >= 0.95
    assert table_hits / len(expected["expected_tables"]) >= 0.90
