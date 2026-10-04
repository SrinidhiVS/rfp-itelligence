"""Typed configuration and records used by semantic vector indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EmbeddingConfig:
    """Immutable embedding model and vector-shape configuration.

    ``provider`` and ``model_name`` identify the encoder; ``dimension`` is an
    optional expected vector width; ``normalize`` controls embedding
    normalization; and ``batch_size`` configures model encoding batches.
    """

    provider: str = "sentence-transformers"
    model_name: str = "all-MiniLM-L6-v2"
    dimension: int | None = None
    normalize: bool = True
    batch_size: int = 32


@dataclass
class VectorRecord:
    """Persist one embedding with source, citation, and authority metadata.

    Required values identify the record, vector, source scope/hash, bid,
    source file, locator, and passage text. Optional fields retain page,
    document type/date, addendum, authority status, superseding record,
    section, and content-kind metadata.
    """

    record_id: str
    vector: list[float]
    scope_id: str
    content_fingerprint: str
    bid_id: str
    source_file: str
    page_number: int | None
    source_locator: dict[str, Any]
    text: str
    doc_type: str | None = None
    addendum_number: int | None = None
    document_date: str | None = None
    authority_status: str = "unknown"
    superseded_by: str | None = None
    section_title: str | None = None
    content_kind: str | None = None


@dataclass
class VectorIndexManifest:
    """Describe the collection's embedding compatibility and source hashes.

    The manifest stores index version and collection name, provider/model,
    vector dimension, normalization setting, per-scope fingerprints, and an
    optional ISO-8601 UTC update timestamp.
    """

    index_version: str = "1"
    collection_name: str = "rfp_passages"
    provider: str = "sentence-transformers"
    model_name: str = "all-MiniLM-L6-v2"
    dimension: int = 0
    normalize: bool = True
    scope_fingerprints: dict[str, str] = field(default_factory=dict)
    updated_at: str | None = None


@dataclass
class EmbeddingDiagnostic:
    """Represent a coded embedding diagnostic and its recoverability.

    ``code`` is a machine-readable identifier, ``message`` is human-readable
    detail, and ``recoverable`` indicates whether processing may continue.
    """

    code: str
    message: str
    recoverable: bool = True
