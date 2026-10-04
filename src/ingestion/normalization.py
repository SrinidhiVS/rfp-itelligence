"""Normalize extracted text and remove repeated page-edge furniture."""

from __future__ import annotations

import re


def _is_layout_noise(line: str) -> bool:
    """Return whether a line is a generic header/footer/page-number marker."""
    lowered = line.lower()
    return bool(
        re.fullmatch(r"(?:header|footer)(?:\s+\d+)?", lowered)
        or re.fullmatch(r"page\s+\d+(?:\s+of\s+\d+)?", lowered)
    )


def _edge_line_key(line: str) -> str:
    """Normalize variable page-edge text for cross-page repetition checks."""
    normalized = re.sub(r"\s+", " ", line.casefold()).strip()
    normalized = re.sub(r"\bpage\s+\d+(?:\s+of\s+\d+)?\b", "page #", normalized)
    normalized = re.sub(r"\b\d+\b", "#", normalized)
    return re.sub(r"[^\w#]+", " ", normalized, flags=re.UNICODE).strip()


def remove_repeated_page_furniture(
    pages: list[list[str]],
) -> tuple[list[list[str]], list[list[str]], list[list[str]]]:
    """Remove repeated edge lines while retaining uncertain candidates.

    Args:
        pages: Page-ordered lists of source text lines.

    Returns:
        Three page-aligned lists: cleaned lines, removed lines, and repeated
        but below-threshold uncertain lines. Only short lines near page edges
        are considered furniture.
    """
    if len(pages) < 2:
        return [list(page) for page in pages], [[] for _ in pages], [[] for _ in pages]

    occurrences: dict[str, set[int]] = {}
    for page_index, lines in enumerate(pages):
        last_edge_index = len(lines) - 1
        for line_index, line in enumerate(lines):
            if not line.strip() or len(line) > 120:
                continue
            if line_index >= 2 and line_index < last_edge_index:
                continue
            key = _edge_line_key(line)
            if key:
                occurrences.setdefault(key, set()).add(page_index)

    required_pages = max(2, (3 * len(pages) + 4) // 5)
    repeated = {key for key, page_indexes in occurrences.items() if len(page_indexes) >= required_pages}
    uncertain = {
        key
        for key, page_indexes in occurrences.items()
        if 2 <= len(page_indexes) < required_pages
    }
    cleaned_pages: list[list[str]] = []
    removed_pages: list[list[str]] = []
    uncertain_pages: list[list[str]] = []
    for lines in pages:
        cleaned: list[str] = []
        removed: list[str] = []
        uncertain_lines: list[str] = []
        last_edge_index = len(lines) - 1
        for line_index, line in enumerate(lines):
            key = _edge_line_key(line)
            is_edge = line_index < 2 or line_index >= last_edge_index
            if is_edge and key in repeated:
                removed.append(line)
            else:
                cleaned.append(line)
                if is_edge and key in uncertain:
                    uncertain_lines.append(line)
        cleaned_pages.append(cleaned)
        removed_pages.append(removed)
        uncertain_pages.append(uncertain_lines)
    return cleaned_pages, removed_pages, uncertain_pages


def _is_structural_line(line: str) -> bool:
    """Identify list/table/punctuation lines that should not join paragraphs."""
    return bool(
        re.match(r"^(?:[-*•▪]|\d+[.)])\s+", line)
        or "|" in line
        or line.endswith((".", "!", "?", ":", ";"))
    )


def _can_join(current: str, following: str) -> bool:
    """Return whether adjacent extracted lines appear to be one paragraph."""
    if not current or not following or _is_structural_line(current) or _is_structural_line(following):
        return False
    if len(current.split()) < 3:
        return False
    return following[0].islower() or following[0] in ",)]}"


def normalize_text(text: str) -> str:
    """Clean line breaks, dehyphenate wraps, join prose, and remove layout noise.

    Args:
        text: Raw extracted page or section text.

    Returns:
        Trimmed normalized text with repeated blank lines collapsed, safe
        sentence continuations joined, and common repeated header/footer noise
        removed.
    """
    text = text.replace("\u00ad", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    source_lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    lines: list[str] = []
    index = 0
    while index < len(source_lines):
        current = source_lines[index]
        if not current:
            index += 1
            continue
        while index + 1 < len(source_lines):
            following = source_lines[index + 1]
            if not following:
                break
            if re.search(r"(?<=\w)-$", current) and following[0].islower():
                current = current[:-1] + following
                index += 1
                continue
            if _can_join(current, following):
                current = f"{current} {following}"
                index += 1
                continue
            break
        lines.append(current)
        index += 1
    if len(lines) > 2:
        counts: dict[str, int] = {}
        for line in lines:
            counts[line] = counts.get(line, 0) + 1
        repeated = {line for line, count in counts.items() if count >= 3 and len(line) < 120 and _is_layout_noise(line)}
        lines = [line for line in lines if line not in repeated]
    return "\n".join(lines).strip()
