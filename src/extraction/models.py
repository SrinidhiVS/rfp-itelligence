"""Pydantic schemas for source citations, extracted fields, and bid records."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


FieldStatus = Literal["supported", "not_found", "failed", "review_required"]


class SourceCitation(BaseModel):
    """Identify the source passage supporting an extracted field value.

    Fields serialize as a JSON object with source ``file``, optional ``page``
    and ``location``, owning ``bid_id``, optional authority status, and excerpt.
    """

    file: str
    page: int | None = None
    location: str | dict[str, Any] | None = None
    bid_id: str
    authority_status: str | None = None
    excerpt: str | None = None


class FieldValueItem(BaseModel):
    """Represent one distinct collection value with attributes and citations.

    ``value`` and ``attributes`` must be JSON serializable. At least one
    ``SourceCitation`` is required, so each list item remains individually
    traceable.
    """

    value: Any
    attributes: dict[str, Any] = Field(default_factory=dict)
    citations: list[SourceCitation] = Field(default_factory=list)

    @field_validator("citations")
    @classmethod
    def requires_citation(cls, citations: list[SourceCitation]) -> list[SourceCitation]:
        """Reject collection entries without at least one source citation."""
        if not citations:
            raise ValueError("field value item requires at least one citation")
        return citations

    @model_validator(mode="after")
    def validate_json_value(self) -> "FieldValueItem":
        """Ensure value and attributes can be emitted as strict JSON."""
        try:
            json.dumps({"value": self.value, "attributes": self.attributes}, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("field value and attributes must be JSON serializable") from exc
        return self


class ExtractedField(BaseModel):
    """Store one canonical field's value, support, confidence, and disposition.

    ``value`` may be a scalar, a list of ``FieldValueItem`` objects, or
    ``None``; ``citations`` trace the value to source passages; confidence is
    constrained to 0..1; and status is supported, not_found, failed, or
    review_required. Unsupported/null values use confidence 0.
    """

    name: str
    value: Any = None
    citations: list[SourceCitation] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    notes: str = ""
    status: FieldStatus = "not_found"

    @model_validator(mode="after")
    def validate_evidence(self) -> "ExtractedField":
        """Enforce citation and zero-confidence invariants for unsupported data."""
        if self.status == "supported" and self.value is not None and not self.citations:
            raise ValueError("supported non-null fields require a citation")
        if self.value is None and self.status in {"not_found", "failed", "review_required"} and self.confidence != 0.0:
            raise ValueError("missing or unsupported fields require confidence 0.0")
        return self


class AddendumChange(BaseModel):
    """Describe an addendum-controlled transition in a canonical field."""

    field: str
    previous_value: Any = None
    current_value: Any = None
    previous_citations: list[SourceCitation] = Field(default_factory=list)
    current_citations: list[SourceCitation] = Field(default_factory=list)
    addendum_number: int | None = None
    effective_date: str | None = None
    controlling_citation: SourceCitation
    notes: str
    review_required: bool = False


class ValidationSummary(BaseModel):
    """Aggregate passed, failed, missing, and review-required field counts."""

    passed: int = 0
    failed: int = 0
    not_found: int = 0
    review_required: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def non_negative(self) -> "ValidationSummary":
        """Reject negative outcome counts."""
        if min(self.passed, self.failed, self.not_found, self.review_required) < 0:
            raise ValueError("validation counts cannot be negative")
        return self


class ProcessingDiagnostic(BaseModel):
    """Represent an extraction processing warning/error and its recoverability."""

    code: str
    severity: Literal["info", "warning", "error"]
    source_file: str | None = None
    message: str
    recoverable: bool = True


class BidExtractionRecord(BaseModel):
    """Serialize one bid's canonical fields, addendum changes, and validation.

    The record JSON contains ``bid_id``, non-empty field mapping, change list,
    required validation summary, and processing diagnostics.
    """

    bid_id: str
    fields: dict[str, ExtractedField]
    addendum_changes: list[AddendumChange] = Field(default_factory=list)
    validation: ValidationSummary
    diagnostics: list[ProcessingDiagnostic] = Field(default_factory=list)

    @field_validator("fields")
    @classmethod
    def fields_not_empty(cls, fields: dict[str, ExtractedField]) -> dict[str, ExtractedField]:
        """Require at least one canonical field in the record."""
        if not fields:
            raise ValueError("record must contain fields")
        return fields
