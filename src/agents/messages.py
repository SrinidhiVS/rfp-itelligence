"""Create, type-check, and reject versioned inter-agent message envelopes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .state import AgentMessage, Diagnostic, WorkflowHandoffPayload


class PlanPayload(BaseModel):
    """Represent a plan handoff with mode, field groups, tasks, and exclusions."""

    mode: Literal["extraction", "qa"]
    field_groups: dict[str, list[str]] = Field(default_factory=dict)
    subtasks: list[str] = Field(default_factory=list)
    unsupported_work: list[str] = Field(default_factory=list)


class EvidencePayload(BaseModel):
    """Represent retrieval results and string diagnostics in a handoff."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class RejectionPayload(BaseModel):
    """Represent an optional human-readable message rejection reason."""

    reason: str | None = None


PAYLOAD_MODELS = {
    "plan": PlanPayload,
    "evidence": EvidencePayload,
    "rejection": RejectionPayload,
    "workflow_handoff": WorkflowHandoffPayload,
}
SUPPORTED_MESSAGE_VERSION = 1


def make_message(
    run_id: str,
    task_id: str,
    agent: str,
    payload_type: str,
    payload: dict[str, Any],
    *,
    recipient: str,
    message_version: int = SUPPORTED_MESSAGE_VERSION,
    state_version: int = 0,
    citations=None,
    diagnostics=None,
    status="ok",
) -> AgentMessage:
    """Build a versioned message whose sender identity matches its agent.

    Args:
        run_id: Workflow run identifier.
        task_id: Task identifier within the run.
        agent: Sending agent name.
        payload_type: Registered message payload schema key.
        payload: Payload dictionary validated by the receiver.
        recipient: Destination agent.
        message_version: Envelope version; defaults to the supported version 1.
        state_version: Non-negative state revision associated with this message.
        citations: Optional source citations attached to the envelope.
        diagnostics: Optional typed diagnostics attached to the envelope.
        status: Message status, defaulting to ``ok``.

    Returns:
        Validated ``AgentMessage`` object.
    """
    return AgentMessage(
        run_id=run_id,
        task_id=task_id,
        agent=agent,
        sender=agent,
        recipient=recipient,
        message_version=message_version,
        payload_type=payload_type,
        payload=payload,
        state_version=state_version,
        citations=citations or [],
        diagnostics=diagnostics or [],
        status=status,
    )


def validate_message(
    value: AgentMessage | dict[str, Any],
    *,
    expected_sender: str | set[str] | None = None,
    expected_recipient: str | None = None,
    expected_run_id: str | None = None,
) -> AgentMessage:
    """Validate an envelope, payload schema, version, and expected identities.

    Args:
        value: Existing message model or raw mapping.
        expected_sender: Optional allowed sender string or set of strings.
        expected_recipient: Optional required recipient.
        expected_run_id: Optional required workflow run ID.

    Returns:
        Normalized ``AgentMessage`` with payload reserialized from its typed
        payload model.

    Raises:
        ValueError: If envelope/payload schema, message version, or any supplied
            identity constraint is invalid.
    """
    try:
        raw = value.model_dump(mode="python") if isinstance(value, AgentMessage) else value
        message = AgentMessage.model_validate(raw)
    except ValidationError as exc:
        raise ValueError("invalid agent message schema") from exc
    if not message.run_id or not message.task_id or not message.sender or not message.recipient or not message.payload_type:
        raise ValueError("agent message identity is required")
    if message.message_version != SUPPORTED_MESSAGE_VERSION:
        raise ValueError(f"unsupported agent message version: {message.message_version}")
    payload_model = PAYLOAD_MODELS.get(message.payload_type)
    if payload_model is None:
        raise ValueError(f"unknown agent payload type: {message.payload_type}")
    try:
        message.payload = payload_model.model_validate(message.payload).model_dump(mode="python")
    except ValidationError as exc:
        raise ValueError("invalid agent payload schema") from exc
    allowed_senders = {expected_sender} if isinstance(expected_sender, str) else expected_sender
    if allowed_senders is not None and message.sender not in allowed_senders:
        raise ValueError(f"agent message sender mismatch: {message.sender}")
    if expected_recipient is not None and message.recipient != expected_recipient:
        raise ValueError(f"agent message recipient mismatch: {message.recipient}")
    if expected_run_id is not None and message.run_id != expected_run_id:
        raise ValueError("agent message run identity mismatch")
    return message


def rejection(run_id: str, task_id: str, agent: str, reason: str, *, recipient: str | None = None) -> AgentMessage:
    """Create a rejected message carrying a typed invalid-message diagnostic."""
    return make_message(
        run_id, task_id, agent, "rejection", {"reason": reason}, recipient=recipient or agent, status="rejected",
        diagnostics=[Diagnostic(code="invalid_message", message=reason, severity="error")],
    )
