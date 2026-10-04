"""Pydantic contracts for workflow state, evidence, diagnostics, and responses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


Status = Literal["ok", "rejected", "failed", "review_required"]
FieldStatus = Literal["supported", "not_found", "rejected", "review_required"]
RunStatus = Literal["planned", "completed", "partial", "review_required", "failed"]


class Citation(BaseModel):
    """Identify one source citation and its authority/supersession metadata."""

    file: str
    page: int | None = None
    bid_id: str
    locator: dict[str, Any] = Field(default_factory=dict)
    authority_status: str | None = None
    superseded_by: str | None = None


class Diagnostic(BaseModel):
    """Represent a workflow warning, error, or informational diagnostic."""

    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    field: str | None = None
    retryable: bool = False


class ExtractionField(BaseModel):
    """Represent one agent-extracted value and its supporting citations."""

    name: str
    value: Any = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    citations: list[Citation] = Field(default_factory=list)
    status: FieldStatus = "not_found"
    notes: str = ""

    @model_validator(mode="after")
    def require_support(self) -> "ExtractionField":
        """Require at least one citation for supported non-null values."""
        if self.value is not None and self.status == "supported" and not self.citations:
            raise ValueError("supported extracted values require a citation")
        return self


class ValidationResult(BaseModel):
    """Record field/run validation disposition and retry eligibility."""

    scope: Literal["field", "run"]
    status: Literal["passed", "rejected", "review_required"]
    field: str | None = None
    evidence_supported: bool = False
    citation_complete: bool = False
    format_valid: bool = True
    consistency_valid: bool = True
    unsupported_claim: bool = False
    compliance_notes: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None
    retry_eligible: bool = False


class RetryRequest(BaseModel):
    """Describe one rejected field retry and its configured attempt budget."""

    field: str
    reason: str
    attempt: int = Field(ge=0)
    max_retries: int = Field(ge=0)


class AddendumChange(BaseModel):
    """Represent a field update attributed to a specific addendum."""

    field: str
    previous_value: Any = None
    new_value: Any = None
    addendum_number: int | None = None
    citations: list[Citation] = Field(default_factory=list)
    reason: str
    review_required: bool = False


class EvaluationReport(BaseModel):
    """Summarize citation coverage, validation results, retries, and field outcomes."""

    citation_coverage: float = Field(default=0, ge=0, le=1)
    validation_results: list[ValidationResult] = Field(default_factory=list)
    retry_count: int = 0
    field_dispositions: dict[str, str] = Field(default_factory=dict)


class ModelUsage(BaseModel):
    """Report optional provider/model identity and token usage availability."""

    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    availability: Literal["reported", "unavailable"] = "unavailable"

    @model_validator(mode="after")
    def validate_availability(self) -> "ModelUsage":
        """Require token counts for reported usage and prohibit them otherwise."""
        counts = (self.input_tokens, self.output_tokens, self.total_tokens)
        if self.availability == "reported" and all(count is None for count in counts):
            raise ValueError("reported model usage requires at least one token count")
        if self.availability == "unavailable" and any(count is not None for count in counts):
            raise ValueError("unavailable model usage cannot contain token counts")
        return self


class ExtractionResult(BaseModel):
    """Carry model-produced field values and their token-usage report."""

    values: dict[str, Any] = Field(default_factory=dict)
    usage: ModelUsage = Field(default_factory=ModelUsage)


class AgentTrace(BaseModel):
    """Track trace identity, remote delivery, local persistence, and events."""

    trace_id: str
    run_id: str | None = None
    delivery_status: Literal["disabled", "unconfigured", "delivered", "failed"] = "unconfigured"
    local_persistence_status: Literal["disabled", "pending", "persisted", "failed"] = "pending"
    events: list[dict[str, Any]] = Field(default_factory=list)


class AgentMessage(BaseModel):
    """Versioned agent-to-agent message envelope with typed payload metadata."""

    run_id: str
    task_id: str
    agent: str
    sender: str
    recipient: str
    message_version: int = Field(ge=1)
    payload_type: str
    payload: dict[str, Any]
    citations: list[Citation] = Field(default_factory=list)
    status: Status = "ok"
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    state_version: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def preserve_agent_sender_compatibility(cls, value: Any) -> Any:
        """Fill legacy agent/sender aliases before message validation."""
        if isinstance(value, dict):
            normalized = dict(value)
            sender = normalized.get("sender") or normalized.get("agent")
            agent = normalized.get("agent") or sender
            if sender is not None:
                normalized["sender"] = sender
            if agent is not None:
                normalized["agent"] = agent
            return normalized
        return value

    @model_validator(mode="after")
    def validate_message_identity(self) -> "AgentMessage":
        """Require the declared agent identity to match the sender identity."""
        if self.agent != self.sender:
            raise ValueError("agent and sender identities must match")
        return self


class WorkflowState(BaseModel):
    """Persist complete input, intermediate, retry, trace, and output state.

    ``mode`` selects extraction or QA; ``goal`` and ``bid_ids`` are user input;
    plans/evidence/draft fields/changes/validation hold workflow results;
    retry fields/counts track bounded retries; diagnostics and trace fields
    record execution; and ``final_output`` is the response payload. Search
    filters are restricted to supported document type and positive addendum
    number values.
    """

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    mode: Literal["extraction", "qa"]
    goal: str
    bid_ids: list[str] = Field(default_factory=list)
    search_filters: dict[str, Any] | None = None
    submitted_bid_folders: dict[str, str] = Field(default_factory=dict)
    unsupported_work: list[str] = Field(default_factory=list)
    retry_fields: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=2, ge=0)
    plan: dict[str, Any] = Field(default_factory=dict)
    retrieved_evidence: list[dict[str, Any]] = Field(default_factory=list)
    draft_fields: dict[str, ExtractionField] = Field(default_factory=dict)
    addendum_changes: list[AddendumChange] = Field(default_factory=list)
    validation_results: list[ValidationResult] = Field(default_factory=list)
    retry_count: int = 0
    retry_attempts: dict[str, int] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    trace_reference: str | None = None
    final_output: dict[str, Any] | None = None
    status: RunStatus = "planned"
    trace: AgentTrace | None = None
    retry_requests: list[RetryRequest] = Field(default_factory=list)

    @field_validator("search_filters")
    @classmethod
    def validate_search_filters(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Allow only supported doc_type and positive addendum_number filters."""
        if value is None:
            return None
        allowed_keys = {"doc_type", "addendum_number"}
        unsupported_keys = set(value) - allowed_keys
        if unsupported_keys:
            raise ValueError(f"unsupported search filter(s): {', '.join(sorted(unsupported_keys))}")
        allowed_document_types = {"bid_page", "rfp", "addendum", "specs", "affidavit", "supporting", "unknown"}
        doc_type = value.get("doc_type")
        if doc_type is not None and doc_type not in allowed_document_types:
            raise ValueError("doc_type is not a supported document type")
        addendum_number = value.get("addendum_number")
        if addendum_number is not None and (isinstance(addendum_number, bool) or not isinstance(addendum_number, int) or addendum_number < 1):
            raise ValueError("addendum_number must be a positive integer")
        return value

    @model_validator(mode="after")
    def validate_submission_scope(self) -> "WorkflowState":
        """Require submitted folder mappings to reference requested bid IDs."""
        if not set(self.submitted_bid_folders).issubset(self.bid_ids):
            raise ValueError("submitted folders must belong to requested bids")
        return self


class WorkflowRuntimePayload(BaseModel):
    """Transport ephemeral retry evidence and per-group provider usage."""

    retry_evidence: list[dict[str, Any]] | None = None
    extraction_usage: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowHandoffPayload(BaseModel):
    """Bundle validated workflow state with runtime-only handoff data."""

    state: WorkflowState
    runtime: WorkflowRuntimePayload = Field(default_factory=WorkflowRuntimePayload)


class AnalysisResponse(BaseModel):
    """Public workflow response containing status, output, diagnostics, and evaluation."""

    run_id: str
    status: RunStatus
    output: dict[str, Any]
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    trace_reference: str | None = None
    evaluation: EvaluationReport = Field(default_factory=EvaluationReport)


def utc_now() -> str:
    """Return the current timezone-aware UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()
