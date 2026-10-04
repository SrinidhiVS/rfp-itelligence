"""HTTP client and local bid-import adapter for the Streamlit interface."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .config import FrontendConfig
from .state import ExtractionRequest, QuestionRequest, UiErrorState
from src.extraction.identity import normalized_bid_id
from src.ingestion.pipeline import IngestionPipeline
from src.ingestion.serialization import report_dict
from src.search.config import index_path
from src.search.index import IndexService
from src.search.storage import CorpusStore
from src.search.chroma_sync import sync_chroma_index


class FrontendClient:
    """Call analysis endpoints, poll extraction jobs, and import local files.

    Args:
        config: API URL and timeout/polling configuration; loaded from the
            environment when omitted.
        transport: Optional injected ``httpx.Client`` used for requests.
    """

    def __init__(self, config: FrontendConfig | None = None, transport: httpx.Client | None = None):
        """Use supplied configuration/transport or construct defaults."""
        self.config = config or FrontendConfig.from_env()
        self.transport = transport or httpx.Client(base_url=self.config.api_url, timeout=self.config.timeout_seconds)

    def close(self) -> None:
        """Close the underlying HTTP transport."""
        self.transport.close()

    def ask(self, request: QuestionRequest) -> dict[str, Any]:
        """Submit a nonblank QA request and return the validated response object."""
        if not request.question.strip():
            raise FrontendRequestError(UiErrorState(category="validation", message="Enter a question before submitting.", retryable=False))
        return self._post("/v1/analysis/qa", request.model_dump(mode="json"))

    def extract(self, request: ExtractionRequest) -> dict[str, Any]:
        """Submit synchronous extraction and validate the response envelope."""
        return self._post("/v1/analysis/extract", request.model_dump(mode="json"))

    def start_extraction_job(self, request: ExtractionRequest) -> dict[str, Any]:
        """Queue extraction and require a job ID/status response."""
        data = self._request(
            "POST",
            "/v1/analysis/extraction-jobs",
            payload=request.model_dump(mode="json"),
            timeout_seconds=self.config.job_request_timeout_seconds,
        )
        if not {"job_id", "status"}.issubset(data):
            raise FrontendRequestError(UiErrorState(category="malformed_response", message="The backend returned an invalid extraction job."))
        return data

    def get_extraction_job(self, job_id: str) -> dict[str, Any]:
        """Fetch one job's current status, result, and error fields."""
        data = self._request(
            "GET",
            f"/v1/analysis/extraction-jobs/{job_id}",
            timeout_seconds=self.config.job_request_timeout_seconds,
        )
        if not {"job_id", "status"}.issubset(data):
            raise FrontendRequestError(UiErrorState(category="malformed_response", message="The backend returned an invalid extraction job status."))
        return data

    def wait_for_extraction_job(
        self,
        job_id: str,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Poll until terminal completion, failure, or configured timeout.

        Args:
            job_id: Existing extraction job identifier.
            on_update: Optional callback invoked with each job status mapping.

        Returns:
            Terminal extraction result mapping.

        Raises:
            FrontendRequestError: On failed job, unknown status, or polling
                timeout. Timeout remains retryable so the same job can resume.
        """
        deadline = time.monotonic() + self.config.job_max_wait_seconds
        terminal = {"completed", "partial", "review_required", "failed"}
        while time.monotonic() < deadline:
            job = self.get_extraction_job(job_id)
            if on_update is not None:
                on_update(job)
            status = job["status"]
            if status in terminal:
                if job.get("result") is not None:
                    return job["result"]
                error = job.get("error") or {}
                raise FrontendRequestError(UiErrorState(
                    category="dependency",
                    message=error.get("message", "Extraction job failed."),
                    retryable=False,
                ))
            if status not in {"queued", "running"}:
                raise FrontendRequestError(UiErrorState(category="malformed_response", message="The backend returned an unknown extraction job state."))
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(self.config.job_poll_interval_seconds, remaining))
        raise FrontendRequestError(UiErrorState(
            category="timeout",
            message="Extraction is still running. Resume checking the current job instead of starting another.",
            retryable=True,
        ))

    def health(self) -> dict[str, Any]:
        """Fetch backend health and semantic-search readiness JSON."""
        try:
            response = self.transport.get(f"{self.config.api_url}/health")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise FrontendRequestError(UiErrorState(category="connection", message="The backend health check is unavailable.", details=str(exc))) from exc

    def import_bid_files(self, folder_name: str, uploaded_files: list[Any]) -> dict[str, Any]:
        """Persist uploaded HTML/PDF files locally, ingest, and index the bid.

        Args:
            folder_name: User-provided bid folder label used to derive a stable
                bid ID.
            uploaded_files: Streamlit upload objects exposing ``name`` and
                ``getvalue``; unsupported extensions are skipped.

        Returns:
            Mapping with ``bid_id``, serialized ingestion ``report``, lexical
            index counts, and Chroma vector-index update result.

        Raises:
            FrontendRequestError: If name/files are missing.
        """
        if not folder_name.strip() or not uploaded_files:
            raise FrontendRequestError(UiErrorState(category="validation", message="Provide a bid folder name and at least one HTML or PDF file.", retryable=False))
        bid_id = normalized_bid_id(folder_name)
        root = Path("output/imported-bids") / bid_id
        root.mkdir(parents=True, exist_ok=True)
        for uploaded_file in uploaded_files:
            file_name = Path(uploaded_file.name).name
            if Path(file_name).suffix.lower() not in {".html", ".htm", ".pdf"}:
                continue
            (root / file_name).write_bytes(uploaded_file.getvalue())
        report = IngestionPipeline().process(root, bid_id=bid_id)
        payload = report_dict(report)
        store = CorpusStore(index_path())
        index_result = IndexService(store).update({"bid_id": bid_id, "chunks": payload["chunks"]})
        vector_result = sync_chroma_index(store)
        return {"bid_id": bid_id, "report": payload, "index": index_result, "vector_index": vector_result}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON and require the standard analysis response keys."""
        data = self._request("POST", path, payload=payload)
        required = {"run_id", "status", "output", "diagnostics", "trace_reference", "evaluation"}
        if not required.issubset(data):
            raise FrontendRequestError(UiErrorState(category="malformed_response", message="The backend response is missing required fields."))
        return data

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request and normalize transport/server failures.

        Args:
            method: HTTP verb.
            path: API path appended to configured base URL.
            payload: Optional JSON object request body.
            timeout_seconds: Optional per-call override.

        Returns:
            Parsed JSON response object.

        Raises:
            FrontendRequestError: For timeout, connection, HTTP status, invalid
                JSON, or malformed response conditions.
        """
        try:
            response = self.transport.request(
                method,
                f"{self.config.api_url}{path}",
                json=payload,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise FrontendRequestError(UiErrorState(category="timeout", message="The backend took too long to respond.", details=str(exc))) from exc
        except httpx.ConnectError as exc:
            raise FrontendRequestError(UiErrorState(category="connection", message="The backend is unavailable. Start the API and retry.", details=str(exc))) from exc
        except httpx.HTTPStatusError as exc:
            category = "validation" if exc.response.status_code == 422 else "dependency" if exc.response.status_code >= 500 else "unknown"
            expired_job = exc.response.status_code == 404 and "/extraction-jobs/" in path
            message = "This extraction job expired or is unavailable. Start a new extraction." if expired_job else f"The backend returned HTTP {exc.response.status_code}."
            raise FrontendRequestError(UiErrorState(category=category, message=message, retryable=not expired_job, details=_safe_detail(exc.response))) from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise FrontendRequestError(UiErrorState(category="malformed_response", message="The backend returned an invalid response.")) from exc
        return data


class FrontendRequestError(RuntimeError):
    """Carry a typed ``UiErrorState`` alongside a readable exception message."""

    def __init__(self, error: UiErrorState):
        """Initialize with the structured frontend error payload."""
        super().__init__(error.message)
        self.error = error


def _safe_detail(response: httpx.Response) -> str | None:
    """Extract at most 500 characters of a JSON HTTP error detail."""
    try:
        payload = response.json()
        return str(payload.get("detail"))[:500] if isinstance(payload, dict) else None
    except ValueError:
        return None
