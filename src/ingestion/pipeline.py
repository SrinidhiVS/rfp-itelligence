"""Orchestrate bid-folder discovery, parsing, normalization, and chunking."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .classification import addendum_number, classify, classify_document, detected_format, has_format_mismatch
from .diagnostics import diagnostic, document_status, folder_status
from .discovery import discover_files
from .logging import event, failure_event
from .metadata import date_candidates_from_text, make_date_candidate, select_document_date
from .models import BidFolder, DocumentMetadata, SourceDocument
from .parsers import parse_source
from .provenance import document_id, relative_path
from .chunking import make_chunks
from .retention import load_retention_manifest, measure_retention


_FAILURE_DIAGNOSTICS = {
    "format_mismatch",
    "unsupported_format",
    "parse_failure",
    "page_text_extraction_failure",
    "page_image_inspection_failure",
    "table_parse_failure",
    "table_empty",
    "table_uncertain",
    "table_extraction_unavailable",
    "empty_page",
    "ocr_required",
}


def _log_failure_events(document: SourceDocument, relative: str) -> None:
    """Emit structured failure events for incomplete document operations.

    Args:
        document: Processed source document whose diagnostics are inspected
            and annotated with recovery status.
        relative: Document path relative to the ingestion root.

    Returns:
        ``None``. Emits sanitized failure events for relevant diagnostic codes
        or error-severity diagnostics.
    """
    recovery_status = "failed" if document.status == "failed" else "partial" if document.status == "partial" else "recovered"
    safe_locator_keys = {
        "relative_path", "page_number", "table_index", "metadata_key", "text_offset",
        "block_index", "line_index", "candidate_line_count", "removed_line_count",
    }
    for item in document.diagnostics:
        if item.code not in _FAILURE_DIAGNOSTICS and item.severity != "error":
            continue
        locator = {
            key: value
            for key, value in (item.source_locator or {}).items()
            if key in safe_locator_keys
        }
        locator["relative_path"] = relative
        item.recovery_status = recovery_status
        if "table" in item.code:
            operation = "table_extraction"
        elif "text" in item.code or "ocr" in item.code:
            operation = "text_extraction"
        elif "format" in item.code:
            operation = "format_validation"
        else:
            operation = "document_processing"
        failure_event(
            bid_id=document.bid_id,
            document_id=document.document_id,
            file_name=document.file_name,
            relative_path=relative,
            operation=operation,
            diagnostic_code=item.code,
            severity=item.severity,
            source_locator=locator,
            recovery_status=recovery_status,
        )


class IngestionPipeline:
    """Process every supported source beneath a bid folder into normalized data."""

    def process(
        self,
        root: Path,
        bid_id: str | None = None,
        retention_manifest: Path | None = None,
    ) -> BidFolder:
        """Parse a bid folder and collect pages, tables, chunks, and diagnostics.

        Args:
            root: Folder recursively searched for source documents.
            bid_id: Optional owning bid ID; defaults to the root directory name.
            retention_manifest: Optional JSON manifest describing expected
                text spans and table cells for coverage measurement.

        Returns:
            ``BidFolder`` containing file-level ``SourceDocument`` objects,
            flattened pages/tables/chunks, aggregated diagnostics, folder
            status, and an optional retention report. Per-file parse failures
            are represented as diagnostics and processing continues.
        """
        root = root.resolve()
        bid_id = bid_id or root.name
        paths = discover_files(root)
        report = BidFolder(bid_id, str(root), "empty", len(paths), 0, 0)
        for path in paths:
            relative = relative_path(root, path)
            document = SourceDocument(document_id(bid_id, relative), bid_id, path.name, relative, detected_format(path), classify(path), addendum_number(path), None, "unsupported")
            try:
                if has_format_mismatch(path):
                    document.diagnostics.append(diagnostic("file", "format_mismatch", "File extension does not match detected content", source_locator={"relative_path": relative}))
                    document.status = "failed"
                    _log_failure_events(document, relative)
                    report.diagnostics.extend(document.diagnostics)
                    report.files.append(document)
                    report.processed_file_count += 1
                    continue
                if document.detected_format == "html":
                    document.pages = parse_source(path, document.document_id, document.detected_format)
                elif document.detected_format == "pdf":
                    document.pages = parse_source(path, document.document_id, document.detected_format)
                else:
                    document.diagnostics.append(diagnostic("file", "unsupported_format", f"Unsupported file format: {path.name}", source_locator={"relative_path": relative}))
                for page in document.pages:
                    for section in page.sections:
                        section.source_locator["relative_path"] = relative
                    for page_diagnostic in page.diagnostics:
                        page_diagnostic.source_locator = {
                            **(page_diagnostic.source_locator or {}),
                            "relative_path": relative,
                        }
                    for table in page.tables:
                        for table_diagnostic in table.diagnostics:
                            table_diagnostic.source_locator = {
                                **(table_diagnostic.source_locator or {}),
                                "relative_path": relative,
                            }
                    if page.metadata is not None:
                        for metadata_value in page.metadata.values:
                            if "relative_path" in metadata_value.source_locator:
                                metadata_value.source_locator["relative_path"] = relative
                        for candidate in page.metadata.date_candidates:
                            if "relative_path" in candidate.source_locator:
                                candidate.source_locator["relative_path"] = relative

                metadata = DocumentMetadata()
                date_candidates = []
                has_metadata = False
                for page in document.pages:
                    if page.metadata is not None:
                        has_metadata = True
                        metadata.title = metadata.title or page.metadata.title
                        metadata.canonical_url = metadata.canonical_url or page.metadata.canonical_url
                        metadata.description = metadata.description or page.metadata.description
                        metadata.language = metadata.language or page.metadata.language
                        metadata.values.extend(page.metadata.values)
                        date_candidates.extend(page.metadata.date_candidates)
                    date_candidates.extend(
                        date_candidates_from_text(
                            page.normalized_text or "",
                            source_locator={"relative_path": relative, "page_number": page.page_number},
                        )
                    )
                try:
                    filesystem_mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                    mtime_candidate = make_date_candidate(
                        filesystem_mtime,
                        "technical_timestamp",
                        {"relative_path": relative, "filesystem_field": "mtime"},
                        99,
                    )
                    mtime_candidate.status = "technical_only"
                    date_candidates.append(mtime_candidate)
                except OSError:
                    pass
                metadata.date_candidates = date_candidates
                document.document_date, date_diagnostics = select_document_date(date_candidates)
                metadata.selected_document_date = document.document_date
                document.metadata = metadata if has_metadata or date_candidates else None
                document.diagnostics.extend(date_diagnostics)
                if document.detected_format != "unknown":
                    source_text = "\n".join(page.normalized_text or "" for page in document.pages)
                    document.classification = classify_document(
                        path,
                        source_text,
                        source_locator={"relative_path": relative},
                    )
                    document.doc_type = document.classification.doc_type
                    document.addendum_number = document.classification.addendum_number
                for page in document.pages:
                    page.bid_id = bid_id
                    page.file_name = document.file_name
                    page.classification = document.classification
                    page.doc_type = document.doc_type
                    page.addendum_number = document.addendum_number
                    page.document_date = document.document_date
                    if document.metadata is not None:
                        page.metadata = document.metadata
                nested_diagnostics = [item for page in document.pages for item in page.diagnostics]
                nested_diagnostics.extend(item for page in document.pages for table in page.tables for item in table.diagnostics)
                document.diagnostics.extend(nested_diagnostics)
                if document.detected_format != "unknown":
                    document.status = document_status(document)
                report.pages.extend(document.pages)
                report.tables.extend(table for page in document.pages for table in page.tables)
                report.chunks.extend(make_chunks(document, bid_id))
            except Exception as exc:
                document.status = "failed"
                document.diagnostics.append(diagnostic("file", "parse_failure", str(exc), source_locator={"relative_path": relative}, severity="error"))
            _log_failure_events(document, relative)
            report.diagnostics.extend(document.diagnostics)
            report.files.append(document)
            report.processed_file_count += 1
            event("document_processed", bid_id=bid_id, file_name=path.name, status=document.status)
        report.diagnostic_count = len(report.diagnostics)
        report.status = folder_status(report)
        if retention_manifest is not None:
            report.retention_report = measure_retention(report, load_retention_manifest(retention_manifest))
        return report
