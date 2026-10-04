"""Validate request mappings and evidence objects at search boundaries."""

from __future__ import annotations

from typing import Any


def validate_index_request(request: dict[str, Any]) -> None:
    """Check required fields and basic container types for index updates.

    Args:
        request: Index request mapping; requires a truthy ``bid_id`` and a
            list-valued ``chunks`` field when provided.

    Returns:
        ``None`` when valid.

    Raises:
        ValueError: If the bid identifier is missing or ``chunks`` is not a
            list.
    """
    if not request.get("bid_id"):
        raise ValueError("bid_id is required")
    if not isinstance(request.get("chunks", []), list):
        raise ValueError("chunks must be a list")


def validate_query_request(request: dict[str, Any]) -> None:
    """Validate query text, result limit, and supported query mode.

    Args:
        request: Query request mapping with non-empty ``text``, positive
            integer-convertible ``top_k``, and ``mode`` equal to ``search`` or
            ``answer``.

    Returns:
        ``None`` when valid.

    Raises:
        ValueError: If query text is blank, the result limit is below one, or
            the mode is unsupported.
    """
    if not str(request.get("text", "")).strip():
        raise ValueError("query text must not be empty")
    if int(request.get("top_k", 5)) < 1:
        raise ValueError("top_k must be positive")
    if request.get("mode", "search") not in {"search", "answer"}:
        raise ValueError("mode must be search or answer")


def validate_result(result: Any) -> None:
    """Verify ranked evidence has ranking and source-traceability fields.

    Args:
        result: Ranked evidence-like object with attributes for record ID,
            rank, score, source record, retrieval methods, completeness, and
            authority status.

    Returns:
        ``None`` when required fields and values are valid.

    Raises:
        ValueError: If required citation fields, a positive rank, an allowed
            authority status, or source file/bid traceability is missing.
    """
    required = {"record_id", "rank", "score", "record", "retrieval_methods", "source_completeness"}
    if not required.issubset(set(result.__dict__)):
        raise ValueError("ranked evidence is missing citation fields")
    if result.rank < 1:
        raise ValueError("ranked evidence rank must be positive")
    if result.authority_status not in {"current", "superseded", "supporting", "unknown"}:
        raise ValueError("ranked evidence has invalid authority status")
    if not result.record.source_file or not result.record.bid_id:
        raise ValueError("ranked evidence is missing source traceability")
