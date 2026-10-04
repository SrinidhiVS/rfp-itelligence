"""Measure whether expected text and table evidence survived ingestion."""

from __future__ import annotations

import json
from pathlib import Path

from .models import (
    BidFolder,
    ExpectedTableCell,
    ExpectedTextSpan,
    RetentionItem,
    RetentionManifest,
    RetentionMeasurement,
    RetentionReport,
    SourceDocument,
)


def load_retention_manifest(path: Path) -> RetentionManifest:
    """Load and validate expected evidence spans/cells from a JSON manifest.

    Args:
        path: UTF-8 JSON file with manifest version, corpus name, documents,
            expected text spans, and expected table cells.

    Returns:
        Typed ``RetentionManifest`` with ``ExpectedTextSpan`` and
        ``ExpectedTableCell`` entries.

    Raises:
        ValueError: If required keys are missing or documents is not a list.
        OSError: If the file cannot be read.
        json.JSONDecodeError: If the file is malformed JSON.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"manifest_version", "corpus_name", "documents", "expected_text_spans", "expected_table_cells"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError(f"Retention manifest is missing fields: {sorted(required.difference(payload if isinstance(payload, dict) else {}))}")
    if not isinstance(payload["documents"], list):
        raise ValueError("Retention manifest documents must be a list")

    text_spans = [
        ExpectedTextSpan(
            file_name=item["file_name"],
            expected_text=item["expected_text"],
            page_number=item.get("page_number"),
            section_title=item.get("section_title"),
            source_locator=item.get("source_locator", {}),
        )
        for item in payload["expected_text_spans"]
    ]
    table_cells = [
        ExpectedTableCell(
            file_name=item["file_name"],
            page_number=item["page_number"],
            table_index=item["table_index"],
            row_index=item["row_index"],
            column_index=item["column_index"],
            expected_text=item["expected_text"],
            source_locator=item.get("source_locator", {}),
        )
        for item in payload["expected_table_cells"]
    ]
    return RetentionManifest(
        str(payload["manifest_version"]),
        str(payload["corpus_name"]),
        payload["documents"],
        text_spans,
        table_cells,
    )


def _normalize_path(value: str) -> str:
    """Normalize a path for case-insensitive retention-manifest matching."""
    return value.replace("\\", "/").strip("/").casefold()


def _matching_document(report: BidFolder, file_name: str) -> SourceDocument | None:
    """Find a unique report document matching a manifest path or suffix."""
    expected = _normalize_path(file_name)
    matches = [
        document
        for document in report.files
        if _normalize_path(document.relative_path) == expected
        or _normalize_path(document.relative_path).endswith("/" + expected)
        or expected.endswith("/" + _normalize_path(document.relative_path))
    ]
    return matches[0] if len(matches) == 1 else None


def _pages_for_file(document: SourceDocument, page_number: int | None):
    """Select all pages or the page matching a manifest page number."""
    if page_number is None:
        return document.pages
    return [
        page
        for ordinal, page in enumerate(document.pages, start=1)
        if page.page_number == page_number or (page.page_number is None and ordinal == page_number)
    ]


def _measurement(items: list[RetentionItem]) -> RetentionMeasurement:
    """Aggregate retained/missing/uncertain counts and coverage fraction."""
    retained = sum(item.status == "retained" for item in items)
    missing = sum(item.status == "missing" for item in items)
    uncertain = sum(item.status == "uncertain" for item in items)
    expected = len(items)
    return RetentionMeasurement(
        expected,
        retained,
        missing,
        uncertain,
        retained / expected if expected else None,
    )


def measure_retention(report: BidFolder, manifest: RetentionManifest) -> RetentionReport:
    """Compare manifest text spans and table cells against an ingestion report.

    Args:
        report: Parsed bid folder containing source documents and page/table
            output.
        manifest: Expected evidence definitions loaded from a retention JSON
            manifest.

    Returns:
        ``RetentionReport`` with one status-bearing item per expectation and
        separate text/table measurements. Coverage is retained/expected or
        ``None`` when a category has no expectations; uncertain indicates
        source processing was insufficient to prove loss or retention.
    """
    items: list[RetentionItem] = []
    for span in manifest.expected_text_spans:
        document = _matching_document(report, span.file_name)
        locator = {**span.source_locator, "page_number": span.page_number}
        if document is None:
            status = "uncertain"
        else:
            pages = _pages_for_file(document, span.page_number)
            if not pages:
                status = "uncertain"
            elif any(span.expected_text in (page.normalized_text or "") for page in pages):
                status = "retained"
            elif any(page.status in {"partial", "failed", "empty"} for page in pages):
                status = "uncertain"
            else:
                status = "missing"
        items.append(RetentionItem("text_span", span.file_name, status, locator, span.expected_text))

    for cell in manifest.expected_table_cells:
        document = _matching_document(report, cell.file_name)
        locator = {
            **cell.source_locator,
            "page_number": cell.page_number,
            "table_index": cell.table_index,
            "row_index": cell.row_index,
            "column_index": cell.column_index,
        }
        if document is None:
            status = "uncertain"
        else:
            pages = _pages_for_file(document, cell.page_number)
            if not pages:
                status = "uncertain"
            else:
                tables = pages[0].tables
                if cell.table_index >= len(tables):
                    status = "uncertain" if pages[0].status in {"partial", "failed"} else "missing"
                else:
                    table = tables[cell.table_index]
                    if cell.row_index >= len(table.rows) or cell.column_index >= len(table.rows[cell.row_index]):
                        status = "uncertain" if table.status != "parsed" else "missing"
                    else:
                        actual = table.rows[cell.row_index][cell.column_index] or ""
                        if cell.expected_text in actual:
                            status = "retained"
                        else:
                            status = "uncertain" if table.status != "parsed" else "missing"
        items.append(RetentionItem("table_cell", cell.file_name, status, locator, cell.expected_text))

    text_items = [item for item in items if item.item_kind == "text_span"]
    table_items = [item for item in items if item.item_kind == "table_cell"]
    return RetentionReport(
        manifest.corpus_name,
        manifest.manifest_version,
        _measurement(text_items),
        _measurement(table_items),
        items,
    )
