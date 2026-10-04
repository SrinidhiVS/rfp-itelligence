import json
from pathlib import Path

from src.ingestion.models import (
    BidFolder,
    ExtractedTable,
    ExpectedTableCell,
    ExpectedTextSpan,
    NormalizedPage,
    RetentionManifest,
    SourceDocument,
)
from src.ingestion.retention import load_retention_manifest, measure_retention


ROOT = Path(__file__).resolve().parents[2]


def test_curated_manifest_loads_versioned_expected_items() -> None:
    manifest = load_retention_manifest(ROOT / "tests" / "fixtures" / "retention" / "procurement-corpus.json")

    assert manifest.corpus_name == "acceptance-retention-html"
    assert manifest.manifest_version == "1.0"
    assert len(manifest.expected_text_spans) == 20
    assert len(manifest.expected_table_cells) == 10
    assert all(span.file_name == "tests/fixtures/acceptance/retention.html" for span in manifest.expected_text_spans)


def test_retention_report_counts_retained_missing_uncertain_and_empty_sets() -> None:
    relative_path = "bids/retention.html"
    page = NormalizedPage(
        "page-1", "doc-1", 1, None, "Deadline is October 20.", "Deadline is October 20.",
        bid_id="Bid-Retention", file_name="retention.html",
    )
    table = ExtractedTable(
        "table-1", "page-1", None, ["Field", "Value"], [["Award term", "Three years"]],
        status="partial", has_header=True,
    )
    page.tables.append(table)
    document = SourceDocument(
        "doc-1", "Bid-Retention", "retention.html", relative_path, "html", "rfp", None, None, "parsed", [page],
    )
    report = BidFolder("Bid-Retention", "bids", "complete", 1, 1, 0, [document], [page], [table])
    manifest = RetentionManifest(
        "1.0",
        "unit-test-corpus",
        documents=[{"file_name": relative_path}],
        expected_text_spans=[
            ExpectedTextSpan(relative_path, "Deadline is October 20", page_number=1),
            ExpectedTextSpan(relative_path, "Missing clause", page_number=1),
            ExpectedTextSpan("unavailable.html", "Unlocatable clause", page_number=1),
        ],
        expected_table_cells=[
            ExpectedTableCell(relative_path, 1, 0, 0, 0, "Award term"),
            ExpectedTableCell(relative_path, 1, 0, 0, 1, "Uncertain value"),
        ],
    )

    measured = measure_retention(report, manifest)
    empty = measure_retention(report, RetentionManifest("1.0", "empty"))

    assert measured.text.expected == 3
    assert measured.text.retained == 1
    assert measured.text.missing == 1
    assert measured.text.uncertain == 1
    assert measured.text.coverage == 1 / 3
    assert measured.tables.expected == 2
    assert measured.tables.retained == 1
    assert measured.tables.missing == 0
    assert measured.tables.uncertain == 1
    assert measured.tables.coverage == 0.5
    assert empty.text.coverage is None
    assert empty.tables.coverage is None
    assert {item.status for item in measured.items} == {"retained", "missing", "uncertain"}
