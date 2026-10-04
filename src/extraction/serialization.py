"""Read and write structured bid extraction records as validated JSON."""

from __future__ import annotations

import json
from pathlib import Path

from .models import BidExtractionRecord


def write_record(record: BidExtractionRecord, output_directory: str | Path) -> Path:
    """Write one record to ``<output>/<bid_id>/structured-record.json``.

    Args:
        record: Validated extraction record to serialize.
        output_directory: Root directory beneath which the bid-specific folder
            is created.

    Returns:
        Path to the UTF-8, indented JSON file.

    Raises:
        OSError: If the destination directory or file cannot be written.
    """
    destination = Path(output_directory) / record.bid_id / "structured-record.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return destination


def read_record(path: str | Path) -> BidExtractionRecord:
    """Read JSON from disk and validate it as a bid extraction record.

    Args:
        path: Structured-record JSON file path.

    Returns:
        Parsed ``BidExtractionRecord`` instance.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If JSON parsing or Pydantic schema validation fails.
    """
    return BidExtractionRecord.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
