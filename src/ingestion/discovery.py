"""Discover source files beneath a bid folder in deterministic path order."""

from __future__ import annotations

from pathlib import Path


def discover_files(root: Path) -> list[Path]:
    """Recursively list files below a root directory.

    Args:
        root: Directory to scan.

    Returns:
        File paths sorted case-insensitively by POSIX-form path; a missing or
        non-directory root returns an empty list.
    """
    if not root.is_dir():
        return []
    return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: path.as_posix().lower())
