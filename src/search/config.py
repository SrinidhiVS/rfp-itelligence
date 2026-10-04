"""Resolve search-index paths and defaults from environment variables."""

from __future__ import annotations

import os
from pathlib import Path


def index_path() -> Path:
    """Return the lexical index path from ``RFP_INDEX_PATH`` or its default."""
    return Path(os.getenv("RFP_INDEX_PATH", "output/search-index.json"))


def default_top_k() -> int:
    """Return positive default result count from ``RFP_TOP_K`` (default 5)."""
    return max(1, int(os.getenv("RFP_TOP_K", "5")))


def vector_index_path() -> Path:
    """Return the vector-index path from ``RFP_VECTOR_INDEX_PATH``."""
    return Path(os.getenv("RFP_VECTOR_INDEX_PATH", "output/search-vectors.json"))


def chroma_index_path() -> Path:
    """Return the Chroma directory from ``RFP_CHROMA_PATH``."""
    return Path(os.getenv("RFP_CHROMA_PATH", "output/chroma"))
