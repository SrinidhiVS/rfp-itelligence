"""Create source-scoped diagnostics for extraction failures."""

from __future__ import annotations

from .models import ProcessingDiagnostic


def diagnostic_for_source(source_file: str, error: Exception | str, *, recoverable: bool = True) -> ProcessingDiagnostic:
    """Convert an exception/message into a typed source-processing diagnostic.

    Args:
        source_file: Source filename associated with the failure.
        error: Exception or human-readable message.
        recoverable: Select warning/recoverable or error/non-recoverable status.

    Returns:
        ``ProcessingDiagnostic`` with code ``source_processing_failed`` and
        stringified error details.
    """
    return ProcessingDiagnostic(code="source_processing_failed", severity="warning" if recoverable else "error", source_file=source_file, message=str(error), recoverable=recoverable)
