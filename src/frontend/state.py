"""Pydantic request and session-state models for the Streamlit frontend."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RequestState = Literal["idle", "loading", "success", "partial", "review_required", "error"]


class QuestionRequest(BaseModel):
    """Frontend QA request payload with one or more bid identifiers."""

    mode: Literal["qa"] = "qa"
    question: str
    bid_ids: list[str]
    trace: bool = True


class ExtractionRequest(BaseModel):
    """Frontend extraction payload with retry and trace controls."""

    mode: Literal["extraction"] = "extraction"
    bid_id: str
    max_retries: int = Field(default=2, ge=0)
    trace: bool = True


class UiErrorState(BaseModel):
    """Normalize frontend-facing error category, message, details, and retryability."""

    category: Literal["connection", "validation", "configuration", "timeout", "malformed_response", "dependency", "unknown"]
    message: str
    retryable: bool = True
    details: str | None = None


class FrontendSession(BaseModel):
    """Persist selected bids, request lifecycle, response, and error in session state."""

    selected_bid_ids: list[str] = Field(default_factory=list)
    question: str = ""
    active_mode: Literal["qa", "extraction"] = "qa"
    request_state: RequestState = "idle"
    active_job_id: str | None = None
    response: dict[str, Any] | None = None
    error: UiErrorState | None = None

    def begin_request(self, mode: Literal["qa", "extraction"]) -> None:
        """Reset prior response/error and mark the selected workflow loading."""
        self.active_mode = mode
        self.request_state = "loading"
        self.active_job_id = None
        self.response = None
        self.error = None

    def complete(self, response: dict[str, Any]) -> None:
        """Store a successful/partial response and map backend status to UI state."""
        self.response = response
        self.active_job_id = None
        status = response.get("status", "completed")
        self.request_state = "review_required" if status == "review_required" else "partial" if status == "partial" else "success"

    def fail(self, error: UiErrorState) -> None:
        """Store the error and transition the session to its error state."""
        self.error = error
        self.request_state = "error"
