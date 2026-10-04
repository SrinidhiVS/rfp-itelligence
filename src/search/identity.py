"""Create normalized paths and stable hashes for indexed source content."""

from __future__ import annotations

import hashlib
import json


def normalize_relative_path(path: str) -> str:
    """Normalize separators and remove leading dot/slash characters.

    Args:
        path: Relative path using either Windows or POSIX separators.

    Returns:
        A slash-separated string with leading ``./`` and ``/`` characters
        stripped.
    """
    return path.replace("\\", "/").lstrip("./")


def scope_id(bid_id: str, relative_path: str) -> str:
    """Build the stable source-scope key for one bid file.

    Args:
        bid_id: Bid identifier owning the source.
        relative_path: Path relative to the bid's source root.

    Returns:
        String in the form ``<bid_id>:<normalized_relative_path>``.
    """
    return f"{bid_id}:{normalize_relative_path(relative_path)}"


def fingerprint(value: object) -> str:
    """Hash a JSON representation of arbitrary structured content.

    Args:
        value: JSON-serializable value; unsupported values use ``str`` as the
            JSON fallback.

    Returns:
        Full lowercase SHA-256 hex digest of canonicalized JSON.
    """
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_id(scope: str, chunk_id: str, content_fingerprint: str) -> str:
    """Derive a compact stable ID from a source scope and chunk fingerprint.

    Args:
        scope: Canonical source-scope identifier.
        chunk_id: Identifier of the source chunk.
        content_fingerprint: Fingerprint of the chunk content and metadata.

    Returns:
        First 24 hexadecimal characters of the canonical SHA-256 digest.
    """
    return fingerprint([scope, chunk_id, content_fingerprint])[:24]
