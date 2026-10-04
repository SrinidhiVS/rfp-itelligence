"""Build validated source citations from retrieved evidence records."""

from __future__ import annotations

from typing import Any

from .models import SourceCitation


def citation_from_evidence(item: dict[str, Any], bid_id: str) -> SourceCitation:
    """Convert one evidence mapping into the canonical citation model.

    Args:
        item: Evidence mapping containing either a nested ``record`` or the
            record fields directly; ranked-level authority status is preferred.
        bid_id: Fallback bid ID used when the source record omits one.

    Returns:
        ``SourceCitation`` with file, page, locator/section, bid, authority,
        and up to 5000 characters of source excerpt.
    """
    record = item.get("record", item)
    return SourceCitation(
        file=record.get("source_file", "unknown-source"),
        page=record.get("page_number"),
        location=record.get("source_locator") or record.get("section_title"),
        bid_id=record.get("bid_id", bid_id),
        authority_status=item.get("authority_status") or record.get("status"),
        excerpt=record.get("text", "")[:5000] or None,
    )
