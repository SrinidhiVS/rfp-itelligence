"""Create stable ingestion diagnostics and derive document/folder status."""

from __future__ import annotations

from .models import BidFolder, ProcessingDiagnostic, SourceDocument
from .provenance import stable_id


def diagnostic(
    scope: str,
    code: str,
    message: str,
    *,
    source_locator: dict | None = None,
    severity: str = "warning",
    affects_completeness: bool = True,
) -> ProcessingDiagnostic:
    """Construct a deterministically identified processing diagnostic.

    Args:
        scope: Affected level such as folder, file, page, table, or chunk.
        code: Machine-readable diagnostic code.
        message: Human-readable explanation.
        source_locator: Optional dictionary locating the issue.
        severity: ``info``, ``warning``, or ``error``; defaults to warning.
        affects_completeness: Whether this issue makes source completeness
            partial; defaults to true.

    Returns:
        ``ProcessingDiagnostic`` with a stable ID derived from its scope, code,
        message, and locator.
    """
    identifier = stable_id(scope, code, message, source_locator or {})
    return ProcessingDiagnostic(
        diagnostic_id=identifier,
        scope=scope,  # type: ignore[arg-type]
        code=code,
        message=message,
        source_locator=source_locator,
        severity=severity,  # type: ignore[arg-type]
        affects_completeness=affects_completeness,
    )


def folder_status(folder: BidFolder) -> str:
    """Summarize all file outcomes as complete, incomplete, failed, or empty."""
    if not folder.files:
        return "empty"
    if any(item.status == "failed" for item in folder.files):
        return "failed" if all(item.status == "failed" for item in folder.files) else "incomplete"
    if any(item.status in {"partial", "unsupported"} for item in folder.files):
        return "incomplete"
    if any(item.affects_completeness for item in folder.diagnostics):
        return "incomplete"
    return "complete"


def document_status(document: SourceDocument) -> str:
    """Summarize document diagnostics as parsed, partial, or failed."""
    if any(item.severity == "error" for item in document.diagnostics):
        return "failed"
    if any(item.affects_completeness for item in document.diagnostics):
        return "partial"
    return "parsed"
