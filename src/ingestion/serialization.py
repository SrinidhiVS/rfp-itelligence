"""Convert ingestion reports to validated JSON-compatible dictionaries."""

from __future__ import annotations

from .models import BidFolder, to_dict


def report_dict(report: BidFolder) -> dict:
    """Serialize a bid-folder report and expose source files as documents.

    Args:
        report: ``BidFolder`` returned by ``IngestionPipeline.process``.

    Returns:
        Nested JSON-compatible mapping with required bid/status/documents,
        pages, tables, chunks, and diagnostics keys. The internal ``files`` key
        is renamed to ``documents``.

    Raises:
        ValueError: If the serialized report omits required top-level fields.
    """
    payload = to_dict(report)
    if isinstance(report, BidFolder):
        payload["documents"] = payload.pop("files", [])
        validate_report(payload)
    return payload


def validate_report(payload: dict) -> None:
    """Check required top-level keys in an ingestion report mapping.

    Args:
        payload: Serialized report mapping.

    Returns:
        ``None`` when all required keys are present.

    Raises:
        ValueError: If any required report key is missing.
    """
    required = {"bid_id", "status", "documents", "pages", "tables", "chunks", "diagnostics"}
    missing = required.difference(payload)
    if missing:
        raise ValueError(f"Missing report fields: {sorted(missing)}")
