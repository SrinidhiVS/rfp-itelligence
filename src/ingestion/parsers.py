"""Dispatch source files to the matching HTML or PDF parser."""

from __future__ import annotations

from pathlib import Path

from .html_parser import parse_html
from .models import NormalizedPage
from .pdf_parser import parse_pdf


def parse_source(path: Path, document_id: str, file_format: str) -> list[NormalizedPage]:
    """Parse a file according to its previously detected format.

    Args:
        path: Source file path.
        document_id: Stable ID attached to generated pages and source locators.
        file_format: Supported format label, either ``html`` or ``pdf``.

    Returns:
        Parsed pages as ``NormalizedPage`` objects.

    Raises:
        ValueError: If ``file_format`` is unsupported.
        OSError: If the source cannot be read by its parser.
    """
    if file_format == "html":
        return parse_html(path, document_id)
    if file_format == "pdf":
        return parse_pdf(path, document_id)
    raise ValueError(f"Unsupported file format: {file_format}")
