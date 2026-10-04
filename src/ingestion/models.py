"""Typed page, table, metadata, diagnostic, and bid-folder ingestion records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DocumentType = Literal["bid_page", "rfp", "addendum", "specs", "affidavit", "supporting", "unknown"]
DocumentStatus = Literal["parsed", "partial", "failed", "unsupported"]
PageStatus = Literal["parsed", "partial", "empty", "failed", "unsupported"]
DiagnosticSeverity = Literal["info", "warning", "error"]
ContentKind = Literal["text", "table", "mixed"]
HtmlSectionKind = Literal["heading", "paragraph", "list_item", "table", "other"]
DateCandidateStatus = Literal["candidate", "selected", "conflicting", "ambiguous", "invalid", "technical_only"]
ClassificationStatus = Literal["classified", "unknown", "conflict"]
ClassificationField = Literal["doc_type", "addendum_number"]
ClassificationSource = Literal["content", "filename"]
EvidenceStrength = Literal["explicit", "supporting", "ambiguous"]
RetentionItemStatus = Literal["retained", "missing", "uncertain"]


@dataclass
class ProcessingDiagnostic:
    """Describe a processing issue, its severity, and source location."""

    diagnostic_id: str
    scope: Literal["folder", "file", "page", "table", "chunk"]
    code: str
    message: str
    severity: DiagnosticSeverity = "warning"
    source_locator: dict[str, Any] | None = None
    affects_completeness: bool = True
    recovery_status: Literal["recovered", "partial", "failed"] | None = None


@dataclass
class ExtractedTable:
    """Represent normalized table columns, rows, bounds, and parse status."""

    table_id: str
    page_id: str
    title: str | None
    columns: list[str | None]
    rows: list[list[str | None]]
    source_bounds: dict[str, Any] | None = None
    status: Literal["parsed", "partial", "failed"] = "parsed"
    diagnostics: list[ProcessingDiagnostic] = field(default_factory=list)
    has_header: bool | None = None


@dataclass
class MetadataValue:
    """Preserve one raw metadata key/value with its source and locator."""

    key: str
    value: str
    source_kind: str
    source_locator: dict[str, Any] = field(default_factory=dict)


@dataclass
class DateCandidate:
    """Represent a raw date, parsed ISO value, precedence, and resolution state."""

    raw_value: str
    normalized_date: str | None
    source_kind: str
    source_locator: dict[str, Any] = field(default_factory=dict)
    precedence: int = 0
    status: DateCandidateStatus = "candidate"


@dataclass
class DocumentMetadata:
    """Collect normalized document metadata and all date candidates."""

    title: str | None = None
    canonical_url: str | None = None
    description: str | None = None
    language: str | None = None
    values: list[MetadataValue] = field(default_factory=list)
    selected_document_date: str | None = None
    date_candidates: list[DateCandidate] = field(default_factory=list)


@dataclass
class DocumentSection:
    """Represent a heading, text block, list item, or table in page order."""

    section_id: str
    kind: HtmlSectionKind
    text: str
    heading_level: int | None
    heading_path: list[str]
    page_id: str
    table_id: str | None = None
    source_locator: dict[str, Any] = field(default_factory=dict)
    evidence_status: Literal["explicit", "inferred", "uncertain"] = "explicit"


HtmlSection = DocumentSection


@dataclass
class ClassificationEvidence:
    """Record a filename/content candidate for type or addendum classification."""

    evidence_id: str
    field: ClassificationField
    candidate_value: str | int | None
    source_kind: ClassificationSource
    source_locator: dict[str, Any]
    strength: EvidenceStrength


@dataclass
class DocumentClassification:
    """Store the selected document type/number and supporting evidence."""

    doc_type: DocumentType | None
    addendum_number: int | None
    status: ClassificationStatus
    evidence: list[ClassificationEvidence] = field(default_factory=list)
    selected_evidence_id: str | None = None


@dataclass
class ExpectedTextSpan:
    """Define a required exact text excerpt for retention validation."""

    file_name: str
    expected_text: str
    page_number: int | None = None
    section_title: str | None = None
    source_locator: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExpectedTableCell:
    """Define a required table cell by file, page, table, row, and column."""

    file_name: str
    page_number: int
    table_index: int
    row_index: int
    column_index: int
    expected_text: str
    source_locator: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetentionManifest:
    """Describe a corpus and its expected text spans and table cells."""

    manifest_version: str
    corpus_name: str
    documents: list[dict[str, Any]] = field(default_factory=list)
    expected_text_spans: list[ExpectedTextSpan] = field(default_factory=list)
    expected_table_cells: list[ExpectedTableCell] = field(default_factory=list)


@dataclass
class RetentionMeasurement:
    """Aggregate expected, retained, missing, uncertain, and coverage values."""

    expected: int
    retained: int
    missing: int
    uncertain: int
    coverage: float | None


@dataclass
class RetentionItem:
    """Report the retained/missing/uncertain result for one expectation."""

    item_kind: Literal["text_span", "table_cell"]
    file_name: str
    status: RetentionItemStatus
    source_locator: dict[str, Any]
    expected_text: str
    matched_page_id: str | None = None


@dataclass
class RetentionReport:
    """Summarize text and table retention measurements for one corpus."""

    corpus_name: str
    manifest_version: str
    text: RetentionMeasurement
    tables: RetentionMeasurement
    items: list[RetentionItem] = field(default_factory=list)


@dataclass
class NormalizedPage:
    """Store parsed page text, sections, tables, metadata, and diagnostics."""

    page_id: str
    document_id: str
    page_number: int | None
    section_title: str | None
    raw_text: str | None
    normalized_text: str | None
    tables: list[ExtractedTable] = field(default_factory=list)
    status: PageStatus = "parsed"
    diagnostics: list[ProcessingDiagnostic] = field(default_factory=list)
    doc_type: DocumentType | None = None
    addendum_number: int | None = None
    document_date: str | None = None
    sections: list[DocumentSection] = field(default_factory=list)
    metadata: DocumentMetadata | None = None
    bid_id: str | None = None
    file_name: str | None = None
    classification: DocumentClassification | None = None


@dataclass
class NormalizedChunk:
    """Store a searchable text/table segment and complete source provenance."""

    chunk_id: str
    bid_id: str
    document_id: str
    page_id: str | None
    chunk_index: int
    section_title: str | None
    text: str
    content_kind: ContentKind
    source_file: str
    page_number: int | None
    source_locator: dict[str, Any]
    diagnostic_ids: list[str] = field(default_factory=list)
    doc_type: DocumentType | None = None
    addendum_number: int | None = None
    document_date: str | None = None
    file_name: str | None = None

    def __post_init__(self) -> None:
        """Default the compatibility ``file_name`` field to ``source_file``."""
        if self.file_name is None:
            self.file_name = self.source_file


@dataclass
class SourceDocument:
    """Collect one source file's classification, pages, metadata, and status."""

    document_id: str
    bid_id: str
    file_name: str
    relative_path: str
    detected_format: Literal["html", "pdf", "unknown"]
    doc_type: DocumentType | None
    addendum_number: int | None
    document_date: str | None
    status: DocumentStatus
    pages: list[NormalizedPage] = field(default_factory=list)
    diagnostics: list[ProcessingDiagnostic] = field(default_factory=list)
    metadata: DocumentMetadata | None = None
    classification: DocumentClassification | None = None


@dataclass
class BidFolder:
    """Aggregate all file, page, table, chunk, and diagnostic results for a bid."""

    bid_id: str
    root_path: str
    status: Literal["complete", "incomplete", "failed", "empty"]
    discovered_file_count: int
    processed_file_count: int
    diagnostic_count: int
    files: list[SourceDocument] = field(default_factory=list)
    pages: list[NormalizedPage] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    chunks: list[NormalizedChunk] = field(default_factory=list)
    diagnostics: list[ProcessingDiagnostic] = field(default_factory=list)
    retention_report: RetentionReport | None = None


def to_dict(value: Any) -> Any:
    """Recursively convert ingestion dataclasses to JSON-compatible values.

    Args:
        value: Dataclass instance, list, dictionary, or scalar value.

    Returns:
        Nested dictionaries, lists, and scalar values suitable for JSON output.
    """
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_dict(item) for key, item in value.items()}
    return value
