"""Expose RFP extraction and QA workflows through a FastAPI JSON API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.graph import AnalysisWorkflow
from src.agents.settings import Settings
from src.agents.state import AnalysisResponse, Diagnostic, WorkflowState
from src.extraction.extractor import StructuredExtractor
from src.api.jobs import ExtractionJobCapacityError, ExtractionJobManager

app = FastAPI(title="RFP Multi-Agent Analysis", version="0.1.0")
settings = Settings.from_env()
workflow = AnalysisWorkflow(max_retries=settings.max_retries)
extraction_jobs = ExtractionJobManager()


class AnalysisFilters(BaseModel):
    """Optional document-type and addendum-number analysis filters."""

    model_config = ConfigDict(extra="forbid")

    doc_type: Literal["bid_page", "rfp", "addendum", "specs", "affidavit", "supporting", "unknown"] | None = None
    addendum_number: int | None = Field(default=None, ge=1, strict=True)


class ExtractionRequest(BaseModel):
    """Request complete structured extraction for one bid.

    JSON fields select extraction mode and bid ID, optional source filters and
    staged-folder references, a non-negative retry limit, and trace recording.
    """

    mode: str = "extraction"
    bid_id: str
    filters: AnalysisFilters | None = None
    submitted_bid_folders: dict[str, str] = Field(default_factory=dict)
    max_retries: int = Field(default=2, ge=0)
    trace: bool = True

    @model_validator(mode="after")
    def validate_folders(self) -> "ExtractionRequest":
        """Require submitted folder references to match the requested bid."""
        _validate_folder_refs([self.bid_id], self.submitted_bid_folders)
        return self


class QARequest(BaseModel):
    """Request a source-grounded answer for one or more bid IDs."""

    mode: str = "qa"
    question: str = Field(min_length=1)
    bid_ids: list[str] = Field(min_length=1)
    filters: AnalysisFilters | None = None
    submitted_bid_folders: dict[str, str] = Field(default_factory=dict)
    trace: bool = True

    @model_validator(mode="after")
    def validate_folders(self) -> "QARequest":
        """Require submitted folder references to match requested bid IDs."""
        _validate_folder_refs(self.bid_ids, self.submitted_bid_folders)
        return self


def _validate_folder_refs(bid_ids: list[str], references: dict[str, str]) -> None:
    """Validate relative staged-folder names against requested bid identifiers."""
    for bid_id, folder in references.items():
        if bid_id not in bid_ids or not folder or folder != bid_id or Path(folder).name != folder or Path(folder).is_absolute():
            raise ValueError("submitted folders must match requested bid IDs inside the staging root")


def _resolve_submissions(references: dict[str, str]) -> dict[str, str]:
    """Resolve staged folder names beneath the authorized submission root.

    Args:
        references: Mapping from requested bid ID to a safe relative folder
            name.

    Returns:
        Mapping to absolute staged-folder paths.

    Raises:
        HTTPException: 422 when a folder is missing or resolves outside the
            configured staging root.
    """
    root = Path(os.getenv("RFP_SUBMISSION_ROOT", "output/imported-bids")).resolve()
    resolved = {}
    for bid_id, reference in references.items():
        folder = (root / reference).resolve()
        if folder.parent != root or not folder.is_dir():
            raise HTTPException(status_code=422, detail={"code": "invalid_submission", "message": f"staged folder for {bid_id} is missing or outside the authorized root"})
        resolved[bid_id] = str(folder)
    return resolved


def _run(mode: str, goal: str, bid_ids: list[str], max_retries: int, trace: bool, submitted_bid_folders: dict[str, str] | None = None, filters: AnalysisFilters | None = None) -> AnalysisResponse:
    """Invoke the workflow and normalize its output to the public response model.

    Args:
        mode: ``extraction`` or ``qa`` workflow mode.
        goal: Extraction instruction or user question.
        bid_ids: Bid scope for the run.
        max_retries: Maximum validation retries.
        trace: Whether local/remote trace recording is enabled for the request.
        submitted_bid_folders: Optional safe folder references resolved beneath
            the staging root.
        filters: Optional validated document/addendum filters.

    Returns:
        ``AnalysisResponse`` with run ID, status, output, diagnostics, trace
        reference, and evaluation report. Extraction output is merged with
        canonical structured-extraction fields.

    Raises:
        HTTPException: 503 for runtime configuration errors or 500 for other
            workflow failures.
    """
    state = WorkflowState(
        mode=mode,
        goal=goal,
        bid_ids=bid_ids,
        max_retries=max_retries,
        submitted_bid_folders=_resolve_submissions(submitted_bid_folders or {}),
        search_filters=filters.model_dump(exclude_none=True) if filters is not None else None,
    )
    try:
        result = workflow.invoke(state)
        response = AnalysisResponse.model_validate(result.final_output) if result.final_output and "run_id" in result.final_output else None
        if response is None:
            from src.agents.report_agent import extraction_response, qa_response
            response = extraction_response(result) if mode == "extraction" else qa_response(result)
        if mode == "extraction":
            bid_id = result.bid_ids[0] if result.bid_ids else "unknown-bid"
            evidence = [
                item
                for item in result.retrieved_evidence
                if item.get("record", item).get("bid_id") == bid_id
            ]
            canonical_record = StructuredExtractor().extract(bid_id, evidence=evidence)
            canonical_fields = {
                name: field.model_dump(mode="json")
                for name, field in canonical_record.fields.items()
            }
            existing_fields = response.output.get("fields", {})
            response.output["fields"] = {**canonical_fields, **existing_fields}
        return response
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"code": "configuration_error", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "workflow_error", "message": str(exc)}) from exc


@app.post("/v1/analysis/extract", response_model=AnalysisResponse)
def extract(request: ExtractionRequest) -> AnalysisResponse:
    """Synchronously extract one bid and return its analysis response.

    Args:
        request: Extraction mode, bid ID, filters, staged folders, retry limit,
            and trace preference.

    Returns:
        JSON ``AnalysisResponse``; non-extraction mode is rejected with HTTP 422.
    """
    if request.mode != "extraction":
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "mode must be extraction"})
    return _run("extraction", "extract complete bid record", [request.bid_id], request.max_retries, request.trace, request.submitted_bid_folders, request.filters)


@app.post("/v1/analysis/extraction-jobs", status_code=202)
def start_extraction_job(request: ExtractionRequest) -> dict[str, object]:
    """Queue extraction and return the initial job status envelope."""
    if request.mode != "extraction":
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "mode must be extraction"})
    bid_ids = [request.bid_id]
    submitted = _resolve_submissions(request.submitted_bid_folders)
    try:
        return extraction_jobs.submit(
            lambda: _run("extraction", "extract complete bid record", bid_ids, request.max_retries, request.trace, submitted, request.filters)
        )
    except ExtractionJobCapacityError as exc:
        raise HTTPException(status_code=503, detail={"code": "job_capacity", "message": "Extraction is busy. Retry shortly."}) from exc


@app.get("/v1/analysis/extraction-jobs/{job_id}")
def get_extraction_job(job_id: str) -> dict[str, object]:
    """Return queued/running/terminal status and result for an extraction job."""
    job = extraction_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Extraction job was not found or has expired."})
    return job


@app.post("/v1/analysis/qa", response_model=AnalysisResponse)
def ask(request: QARequest) -> AnalysisResponse:
    """Run source-grounded QA for the requested bids and return analysis JSON."""
    if request.mode != "qa":
        raise HTTPException(status_code=422, detail={"code": "validation_error", "message": "mode must be qa"})
    return _run("qa", request.question, request.bid_ids, settings.max_retries, request.trace, request.submitted_bid_folders, request.filters)


@app.get("/health")
def health() -> dict[str, object]:
    """Return API health and semantic-retrieval readiness details."""
    return {"status": "ok", "semantic_search": workflow.retrieval.status()}


@app.get("/")
def root() -> dict[str, object]:
    """Return service identity, health status, and principal endpoint paths."""
    return {
        "service": "RFP Multi-Agent Analysis",
        "status": "ok",
        "endpoints": ["/health", "/v1/analysis/extract", "/v1/analysis/qa", "/docs"],
    }
