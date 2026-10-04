"""Generate deterministic IDs and relative paths for ingestion provenance."""

from __future__ import annotations

import hashlib
from pathlib import Path


def stable_id(*parts: object) -> str:
    """Hash ordered identity components into a compact stable identifier.

    Args:
        *parts: Values converted to strings and joined with ``|``.

    Returns:
        First 16 lowercase hexadecimal characters of the SHA-256 digest.
    """
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def document_id(bid_id: str, relative_path: str) -> str:
    """Generate a document ID scoped to a bid and relative source path."""
    return stable_id("document", bid_id, relative_path)


def page_id(document: str, location: str) -> str:
    """Generate a page ID from a document ID and page-location key."""
    return stable_id("page", document, location)


def table_id(page: str, index: int) -> str:
    """Generate a table ID from its page ID and zero-based table index."""
    return stable_id("table", page, index)


def chunk_id(document: str, page: str | None, index: int, text: str) -> str:
    """Generate a chunk ID from document/page/index identity and text."""
    return stable_id("chunk", document, page, index, text)


def relative_path(root: Path, path: Path) -> str:
    """Return a source path relative to root using POSIX separators."""
    return path.relative_to(root).as_posix()
