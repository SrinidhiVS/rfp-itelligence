"""Extract PDF page text, layout sections, tables, metadata, and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import re

from .diagnostics import diagnostic
from .metadata import make_date_candidate
from .models import DocumentMetadata, DocumentSection, ExtractedTable, MetadataValue, NormalizedPage, ProcessingDiagnostic
from .normalization import normalize_text, remove_repeated_page_furniture
from .provenance import page_id
from .tables import table_from_rows


@dataclass
class _PdfPageResult:
    """Hold intermediate extraction results before cross-page normalization."""

    number: int
    source_page: object
    raw_text: str | None
    tables: list[ExtractedTable]
    sections: list[DocumentSection]
    section_title: str | None
    heading_path: list[str]
    diagnostics: list[ProcessingDiagnostic]
    text_failed: bool


def _extract_page_layout(
    source_page: object,
    document_id: str,
    page_number: int,
    heading_path: list[str],
) -> tuple[str | None, list[DocumentSection], str | None, list[str]]:
    """Extract text lines and infer heading hierarchy from a PyMuPDF page.

    Args:
        source_page: PyMuPDF page-like object exposing ``get_text("dict")``.
        document_id: Stable document ID used to generate section page IDs.
        page_number: One-based source page number.
        heading_path: Current heading ancestry, carried across page boundaries.

    Returns:
        Tuple of raw text or ``None``, layout-ordered sections, active section
        title or ``None``, and updated heading path. Heading locations include
        page/block/line indexes and bounding boxes when available.
    """
    layout = source_page.get_text("dict")
    if not isinstance(layout, dict):
        raw_text = layout if isinstance(layout, str) else None
        return raw_text, [], heading_path[-1] if heading_path else None, heading_path

    spans = [
        span
        for block in layout.get("blocks", [])
        if block.get("type", 0) == 0
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if isinstance(span.get("size"), (int, float))
    ]
    sizes = sorted(float(span["size"]) for span in spans)
    body_size = sizes[int((len(sizes) - 1) * 0.25)] if sizes else 0.0
    page_identifier = page_id(document_id, str(page_number))
    page_sections: list[DocumentSection] = []
    text_lines: list[str] = []

    for block_index, block in enumerate(layout.get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            line_spans = line.get("spans", [])
            text = re.sub("\\s+", " ", "".join(span.get("text", "") for span in line_spans)).strip()
            if not text:
                continue
            text_lines.append(text)
            line_sizes = [float(span["size"]) for span in line_spans if isinstance(span.get("size"), (int, float))]
            line_size = max(line_sizes, default=0.0)
            bold = any(
                bool(int(span.get("flags", 0)) & 16)
                or "bold" in str(span.get("font", "")).casefold()
                for span in line_spans
            )
            short_line = len(text) <= 120 and len(text.split()) <= 14
            list_item = bool(re.match(r"^(?:[-*•▪]|\d+[.)])\s+", text))
            size_ratio = line_size / body_size if body_size else 1.0
            is_heading = short_line and not list_item and (
                size_ratio >= 1.3 or (bold and size_ratio >= 1.08) or (text.isupper() and size_ratio >= 1.1)
            )

            if is_heading:
                heading_level = 1 if size_ratio >= 1.7 else 2 if size_ratio >= 1.3 else 3
                heading_level = min(heading_level, len(heading_path) + 1)
                heading_path = heading_path[: heading_level - 1]
                heading_path.append(text)
                kind = "heading"
            else:
                heading_level = None
                kind = "paragraph"

            bbox = line.get("bbox")
            locator = {"page_number": page_number, "block_index": block_index, "line_index": line_index}
            if bbox is not None:
                locator["bbox"] = list(bbox)
            page_sections.append(
                DocumentSection(
                    section_id=f"{page_identifier}-section-{len(page_sections)}",
                    kind=kind,
                    text=text,
                    heading_level=heading_level,
                    heading_path=list(heading_path),
                    page_id=page_identifier,
                    source_locator=locator,
                    evidence_status="inferred" if kind == "heading" else "explicit",
                )
            )

    return "\n".join(text_lines) or None, page_sections, heading_path[-1] if heading_path else None, heading_path


def parse_pdf(path: Path, document_id: str) -> list[NormalizedPage]:
    """Parse a PDF into one normalized page record per source page.

    Args:
        path: PDF source path opened through PyMuPDF.
        document_id: Stable source document ID used to derive page IDs.

    Returns:
        Ordered ``NormalizedPage`` objects with extracted text, inferred
        sections, normalized tables, first-page document metadata, and
        diagnostics for extraction failures, empty/image-only pages, and
        repeated page furniture.

    Raises:
        ImportError: If the PyMuPDF ``fitz`` module is unavailable.
        Exception: File-open failures from PyMuPDF are propagated.
    """
    fitz = import_module("fitz")
    page_results: list[_PdfPageResult] = []
    with fitz.open(path) as pdf:
        document_metadata = _pdf_document_metadata(getattr(pdf, "metadata", None), path)
        heading_path: list[str] = []
        for number, source_page in enumerate(pdf, start=1):
            page_identifier = page_id(document_id, str(number))
            page_diagnostics: list[ProcessingDiagnostic] = []
            text_failed = False
            page_start_heading_path = list(heading_path)
            try:
                raw_text, page_sections, section_title, heading_path = _extract_page_layout(
                    source_page, document_id, number, heading_path
                )
            except Exception as exc:
                raw_text = None
                page_sections = []
                section_title = heading_path[-1] if heading_path else None
                text_failed = True
                page_diagnostics.append(
                    diagnostic(
                        "page",
                        "page_text_extraction_failure",
                        str(exc),
                        source_locator={"page_number": number},
                    )
                )

            tables: list[ExtractedTable] = []
            find_tables = getattr(source_page, "find_tables", None)
            if not callable(find_tables):
                page_diagnostics.append(
                    diagnostic(
                        "page",
                        "table_extraction_unavailable",
                        "PDF table extraction is unavailable in this PyMuPDF runtime",
                        source_locator={"page_number": number},
                    )
                )
            else:
                try:
                    found_tables = find_tables().tables
                except Exception as exc:
                    page_diagnostics.append(
                        diagnostic(
                            "page",
                            "table_parse_failure",
                            str(exc),
                            source_locator={"page_number": number},
                        )
                    )
                    found_tables = []

                for index, table in enumerate(found_tables):
                    try:
                        rows = table.extract()
                        if not rows:
                            page_diagnostics.append(
                                diagnostic(
                                    "page",
                                    "table_empty",
                                    "A detected PDF table contained no extractable rows",
                                    source_locator={"page_number": number, "table_index": index},
                                )
                            )
                            continue
                        bounds = getattr(table, "bbox", None)
                        source_bounds = (
                            {"x0": bounds[0], "y0": bounds[1], "x1": bounds[2], "y1": bounds[3]}
                            if bounds
                            else None
                        )
                        table_header = getattr(table, "header", None)
                        header_names = getattr(table_header, "names", None) if table_header is not None else None
                        external_header = getattr(table_header, "external", None) if table_header is not None else None
                        if header_names and any(name is not None and str(name).strip() for name in header_names):
                            has_header = True
                            normalized_header_names = [str(name).strip() or None if name is not None else None for name in header_names]
                        elif table_header is not None and external_header is False:
                            has_header = False
                            normalized_header_names = None
                        else:
                            has_header = None
                            normalized_header_names = None
                        extracted_table = table_from_rows(
                            page_identifier,
                            index,
                            rows,
                            source_bounds=source_bounds,
                            has_header=has_header,
                            header_names=normalized_header_names if external_header is True else None,
                        )
                        tables.append(extracted_table)
                        table_text = "\n".join(
                            " | ".join(str(cell or "") for cell in row)
                            for row in [extracted_table.columns, *extracted_table.rows]
                        )
                        if table_text.strip():
                            locator = {"page_number": number, "table_index": index}
                            table_y = source_bounds.get("y0") if source_bounds else None
                            if table_y is not None:
                                locator["bbox"] = [
                                    source_bounds["x0"], source_bounds["y0"],
                                    source_bounds["x1"], source_bounds["y1"],
                                ]
                                insertion_index = next(
                                    (
                                        section_index
                                        for section_index, section in enumerate(page_sections)
                                        if (bbox := section.source_locator.get("bbox"))
                                        and bbox[1] > table_y
                                    ),
                                    len(page_sections),
                                )
                                preceding_headings = [
                                    section.heading_path
                                    for section in page_sections[:insertion_index]
                                    if section.kind == "heading"
                                ]
                                table_heading_path = preceding_headings[-1] if preceding_headings else page_start_heading_path
                            else:
                                insertion_index = len(page_sections)
                                table_heading_path = list(heading_path)
                            page_sections.insert(
                                insertion_index,
                                DocumentSection(
                                    section_id=f"{page_identifier}-table-section-{index}",
                                    kind="table",
                                    text=table_text,
                                    heading_level=None,
                                    heading_path=list(table_heading_path),
                                    page_id=page_identifier,
                                    table_id=extracted_table.table_id,
                                    source_locator=locator,
                                    evidence_status="explicit",
                                ),
                            )
                    except Exception as exc:
                        page_diagnostics.append(
                            diagnostic(
                                "page",
                                "table_parse_failure",
                                str(exc),
                                source_locator={"page_number": number, "table_index": index},
                            )
                        )

            page_results.append(
                _PdfPageResult(
                    number,
                    source_page,
                    raw_text,
                    tables,
                    page_sections,
                    section_title,
                    list(heading_path),
                    page_diagnostics,
                    text_failed,
                )
            )

        cleaned_lines, removed_lines, uncertain_lines = remove_repeated_page_furniture(
            [result.raw_text.splitlines() if result.raw_text else [] for result in page_results]
        )
        pages: list[NormalizedPage] = []
        for page_index, result in enumerate(page_results):
            number = result.number
            normalized = normalize_text("\n".join(cleaned_lines[page_index]))
            status = "partial" if result.text_failed else "parsed" if normalized else "empty"
            normalized_page = NormalizedPage(
                page_id(document_id, str(number)),
                document_id,
                number,
                result.section_title,
                result.raw_text,
                normalized or None,
                tables=result.tables,
                sections=[section for section in result.sections if section.text not in removed_lines[page_index]],
                status=status,
                diagnostics=result.diagnostics,
            )
            if number == 1:
                normalized_page.metadata = document_metadata
            if removed_lines[number - 1]:
                normalized_page.diagnostics.append(
                    diagnostic(
                        "page",
                        "repeated_page_furniture_removed",
                        f"Removed {len(removed_lines[number - 1])} repeated edge line(s)",
                        source_locator={"page_number": number, "removed_line_count": len(removed_lines[number - 1])},
                        severity="info",
                        affects_completeness=False,
                    )
                )
            if uncertain_lines[number - 1]:
                normalized_page.diagnostics.append(
                    diagnostic(
                        "page",
                        "repeated_page_furniture_uncertain",
                        f"Preserved {len(uncertain_lines[number - 1])} repeated edge candidate line(s) below the removal threshold",
                        source_locator={"page_number": number, "candidate_line_count": len(uncertain_lines[number - 1])},
                        severity="info",
                        affects_completeness=False,
                    )
                )
            if not normalized and not result.text_failed:
                try:
                    has_images = bool(result.source_page.get_images())
                except Exception as exc:
                    normalized_page.diagnostics.append(
                        diagnostic(
                            "page",
                            "page_image_inspection_failure",
                            str(exc),
                            source_locator={"page_number": number},
                        )
                    )
                    normalized_page.status = "partial"
                    has_images = False
                code = "ocr_required" if has_images else "empty_page"
                message = "Page contains images but no extractable text" if has_images else "No extractable text was found"
                normalized_page.diagnostics.append(diagnostic("page", code, message, source_locator={"page_number": number}))
            if any(
                item.affects_completeness and item.code not in {"empty_page", "ocr_required"}
                for item in normalized_page.diagnostics
            ):
                normalized_page.status = "partial"
            pages.append(normalized_page)
    return pages


def _pdf_document_metadata(raw_metadata: object, path: Path) -> DocumentMetadata | None:
    """Convert supported PyMuPDF document metadata into normalized fields.

    Args:
        raw_metadata: Metadata mapping returned by the opened PDF document.
        path: PDF path used for metadata provenance.

    Returns:
        ``DocumentMetadata`` with raw values and date candidates, or ``None``
        when no usable metadata entries are present.
    """
    if not isinstance(raw_metadata, dict):
        return None
    metadata = DocumentMetadata()
    for key, raw_value in raw_metadata.items():
        if not isinstance(key, str) or not isinstance(raw_value, str) or not raw_value.strip():
            continue
        value = raw_value.strip()
        key_folded = key.casefold()
        locator = {"relative_path": path.name, "metadata_key": key}
        metadata.values.append(MetadataValue(key, value, "embedded_document_metadata", locator))
        if key_folded == "title":
            metadata.title = value
        elif key_folded == "subject":
            metadata.description = value

        compact_key = re.sub(r"[^a-z]", "", key_folded)
        if compact_key in {"datepublished", "publicationdate", "dateissued", "issuedate", "issued"}:
            metadata.date_candidates.append(make_date_candidate(value, "semantic_metadata", locator, 0))
        elif compact_key in {"datemodified", "modifieddate"}:
            candidate = make_date_candidate(value, "modified_metadata", locator, 99)
            candidate.status = "technical_only"
            metadata.date_candidates.append(candidate)
        elif compact_key in {"creationdate", "moddate"}:
            candidate = make_date_candidate(value, "technical_timestamp", locator, 99)
            candidate.status = "technical_only"
            metadata.date_candidates.append(candidate)
    return metadata if metadata.values else None
