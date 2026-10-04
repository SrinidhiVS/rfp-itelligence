"""Resolve extraction output location and missing-field confidence defaults."""

from __future__ import annotations

import os
from pathlib import Path


def output_root() -> Path:
    """Return ``RFP_EXTRACTION_OUTPUT`` or the default bid-records directory."""
    return Path(os.getenv("RFP_EXTRACTION_OUTPUT", "output/bid-records"))


def missing_confidence() -> float:
    """Return the fixed confidence score for missing or unsupported values."""
    return 0.0
