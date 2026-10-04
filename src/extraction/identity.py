"""Resolve official bid IDs or create deterministic numeric folder IDs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def normalized_bid_id(bid_folder: str | Path, official_number: str | None = None) -> str:
    """Return an official number or stable 12-digit ID derived from folder name.

    Args:
        bid_folder: Bid folder path; its basename supplies the fallback identity.
        official_number: Optional official solicitation/bid number. A nonblank
            value is returned trimmed without transformation.

    Returns:
        Trimmed official number, or a deterministic numeric string from
        100000000000 through 999999999999.
    """
    if official_number and official_number.strip():
        return official_number.strip()
    name = Path(bid_folder).name.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    normalized = normalized or "unknown-bid"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return str(100_000_000_000 + (int(digest[:16], 16) % 900_000_000_000))
