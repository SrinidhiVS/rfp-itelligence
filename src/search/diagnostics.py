"""Create stable diagnostic codes used by search response envelopes."""

from __future__ import annotations


def no_match(reason: str = "no_supporting_evidence") -> list[str]:
    """Wrap one no-match reason in the standard diagnostics list format.

    Args:
        reason: Diagnostic code to report; defaults to
            ``no_supporting_evidence``.

    Returns:
        A one-element list containing ``reason``.
    """
    return [reason]


def source_completeness(diagnostic_ids: list[str]) -> str:
    """Classify evidence completeness from its attached diagnostic IDs.

    Args:
        diagnostic_ids: Source processing diagnostics associated with a record.

    Returns:
        ``partial`` when diagnostics exist, otherwise ``complete``.
    """
    return "partial" if diagnostic_ids else "complete"
