"""Typed lexical corpus, query, ranked evidence, and cited-answer models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class SourceFileScope:
    """Track indexing state and fingerprint for one source file.

    Fields are serialized as a JSON object: ``bid_id`` identifies the owning
    bid; ``relative_path`` is the normalized source path; ``scope_id`` is its
    stable index key; ``content_fingerprint`` detects changes; and ``state``
    is one of ``new``, ``changed``, ``unchanged``, ``deleted``, or ``failed``.
    """

    bid_id: str
    relative_path: str
    scope_id: str
    content_fingerprint: str
    state: Literal["new", "changed", "unchanged", "deleted", "failed"]


@dataclass
class IndexRecord:
    """Represent one searchable passage and its source citation metadata.

    Required fields identify the record, chunk, source scope, content hash,
    text, bid, and source file. Optional citation fields include page,
    section, document type, addendum number, date, source locator, diagnostic
    IDs, current/superseded status, and content kind. The JSON form preserves
    these names and maps lists/dictionaries to JSON arrays/objects.
    """

    record_id: str
    chunk_id: str
    scope_id: str
    content_fingerprint: str
    text: str
    bid_id: str
    source_file: str
    page_number: int | None
    section_title: str | None
    doc_type: str | None
    addendum_number: int | None
    document_date: str | None
    source_locator: dict[str, Any]
    diagnostic_ids: list[str] = field(default_factory=list)
    status: Literal["current", "superseded"] = "current"
    content_kind: str | None = None


@dataclass
class IndexedCorpus:
    """Store the complete lexical index and source-change manifest.

    ``corpus_id`` and ``schema_version`` identify the corpus format;
    ``records`` contains ``IndexRecord`` entries; ``source_fingerprints`` maps
    scope IDs to hashes; ``source_manifest`` tracks source files; and
    ``updated_at`` is an optional ISO-8601 UTC timestamp.
    """

    corpus_id: str
    schema_version: str
    records: list[IndexRecord] = field(default_factory=list)
    source_fingerprints: dict[str, str] = field(default_factory=dict)
    source_manifest: list[SourceFileScope] = field(default_factory=list)
    updated_at: str | None = None


@dataclass
class SearchQuery:
    """Describe a normalized search or answer request.

    ``text`` is the query string; ``filters`` may constrain bid, document
    type, or addendum number; ``top_k`` is the positive result limit; ``mode``
    is ``search`` or ``answer``; and ``include_incomplete`` controls whether
    records carrying source diagnostics are eligible.
    """

    text: str
    filters: dict[str, Any] = field(default_factory=dict)
    top_k: int = 5
    mode: Literal["search", "answer"] = "search"
    include_incomplete: bool = False


@dataclass
class QueryVariant:
    """Store an original query and its vocabulary-expanded alternatives.

    ``original`` is unchanged input text, ``variants`` includes it and any
    generated alternatives, ``expansion_terms`` lists generated alternatives,
    and ``diagnostics`` carries expansion notes.
    """

    original: str
    variants: list[str]
    expansion_terms: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


@dataclass
class CandidateResult:
    """Represent one record returned by a single retrieval method.

    Fields provide the record ID, retrieval-method label, method-specific
    numeric score, one-based rank, and the underlying ``IndexRecord``.
    """

    record_id: str
    retrieval_method: str
    method_score: float
    rank: int
    record: IndexRecord


@dataclass
class RankedEvidence:
    """Represent fused and reranked evidence returned to search callers.

    Fields include the record ID, one-based rank, combined score, source
    record, contributing retrieval methods, completeness label, authority
    status, and optional ID of a controlling replacement record.
    """

    record_id: str
    rank: int
    score: float
    record: IndexRecord
    retrieval_methods: list[str]
    source_completeness: str
    authority_status: str = "unknown"
    superseded_by: str | None = None


@dataclass
class AddendumChange:
    """Describe a field-value transition attributed to addendum evidence.

    ``field`` names the affected field; ``previous_value`` and ``new_value``
    contain the transition; ``addendum_number`` may be absent; ``citations``
    is a list of source dictionaries; ``reason`` identifies conflict or
    replacement; and ``review_required`` marks unresolved changes.
    """

    field: str
    previous_value: Any
    new_value: Any
    addendum_number: int | None
    citations: list[dict[str, Any]]
    reason: str
    review_required: bool = False


@dataclass
class CitedAnswer:
    """Package an answer with evidence, citations, diagnostics, and changes.

    The JSON-compatible output includes the originating ``query``, answer
    string, ``found`` flag, ranked ``evidence``, citation dictionaries,
    diagnostic strings, addendum ``change_log``, and ``evidence_by_bid`` map.
    """

    query: SearchQuery
    answer: str
    found: bool
    evidence: list[RankedEvidence] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    change_log: list[AddendumChange] = field(default_factory=list)
    evidence_by_bid: dict[str, list[RankedEvidence]] = field(default_factory=dict)


def as_dict(value: Any) -> Any:
    """Recursively convert dataclasses and nested containers to plain values.

    Args:
        value: Dataclass instance, list, dictionary, or scalar value.

    Returns:
        Nested dictionaries/lists/scalars suitable for JSON serialization.
        Dataclass instances are converted using their declared fields.
    """
    if hasattr(value, "__dataclass_fields__"):
        return {key: as_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [as_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: as_dict(item) for key, item in value.items()}
    return value


def record_from_dict(data: dict[str, Any]) -> IndexRecord:
    """Construct an ``IndexRecord`` from a serialized field mapping.

    Args:
        data: Mapping whose keys match the ``IndexRecord`` constructor fields.

    Returns:
        Reconstructed ``IndexRecord`` instance.

    Raises:
        TypeError: If required fields are missing or unexpected constructor
            keys are supplied.
    """
    return IndexRecord(**data)
