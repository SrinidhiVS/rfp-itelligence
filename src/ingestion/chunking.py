"""Convert normalized document sections and tables into traceable chunks."""

from __future__ import annotations

import re

from .models import NormalizedChunk, NormalizedPage, SourceDocument
from .provenance import chunk_id

TARGET_CHUNK_WORDS = 120
MAX_CHUNK_WORDS = 150
CHUNK_OVERLAP_WORDS = 20


def make_chunks(document: SourceDocument, bid_id: str) -> list[NormalizedChunk]:
    """Create text/table chunks while preserving section and source locations.

    Args:
        document: Parsed document with normalized pages, sections, and tables.
        bid_id: Bid identifier attached to every generated chunk.

    Returns:
        Ordered ``NormalizedChunk`` objects. Text chunks include page/section
        IDs and source segments in ``source_locator``; table chunks serialize
        rows as pipe-separated text and carry the table ID. Text is split at
        paragraph/sentence boundaries near 120 words, capped at 150, with 20
        words of overlap.
    """
    chunks: list[NormalizedChunk] = []
    chunk_indices: dict[str, int] = {}
    pending_fragments: list[dict] = []
    pending_heading_path: tuple[str, ...] | None = None
    pending_title: str | None = None

    def emit_chunk(page: NormalizedPage, kind: str, text: str, title: str | None, locator: dict, diagnostic_ids: list[str]) -> None:
        """Append one chunk with stable ID, inherited metadata, and provenance."""
        chunk_index = chunk_indices.get(page.page_id, 0)
        chunks.append(NormalizedChunk(
            chunk_id(document.document_id, page.page_id, chunk_index, text),
            bid_id, document.document_id, page.page_id, chunk_index, title,
            text, kind, document.file_name, page.page_number, locator,
            diagnostic_ids, document.doc_type, document.addendum_number,
            document.document_date, document.file_name,
        ))
        chunk_indices[page.page_id] = chunk_index + 1

    def flush_text_section() -> None:
        """Split pending same-section fragments and emit source-mapped chunks."""
        nonlocal pending_heading_path, pending_title
        if not pending_fragments:
            return
        combined_text = "\n".join(fragment["text"] for fragment in pending_fragments)
        words = re.findall(r"\S+", combined_text)
        word_spans = list(re.finditer(r"\S+", combined_text))
        offsets: list[tuple[int, int]] = []
        offset = 0
        for fragment in pending_fragments:
            fragment_word_count = len(re.findall(r"\S+", fragment["text"]))
            offsets.append((offset, offset + fragment_word_count))
            offset += fragment_word_count

        for start, end in _split_word_ranges(combined_text, words):
            contributing = [
                (fragment, fragment_start, fragment_end)
                for fragment, (fragment_start, fragment_end) in zip(pending_fragments, offsets)
                if max(start, fragment_start) < min(end, fragment_end)
            ]
            if not contributing:
                continue
            source_segments = []
            page_ids = []
            page_numbers = []
            section_ids = []
            diagnostics = []
            for fragment, _, _ in contributing:
                page = fragment["page"]
                section_id = fragment["section_id"]
                segment = {
                    "page_id": page.page_id,
                    "page_number": page.page_number,
                    "source_locator": dict(fragment["source_locator"]),
                }
                if section_id is not None:
                    segment["section_id"] = section_id
                    section_ids.append(section_id)
                source_segments.append(segment)
                if page.page_id not in page_ids:
                    page_ids.append(page.page_id)
                if page.page_number is not None and page.page_number not in page_numbers:
                    page_numbers.append(page.page_number)
                diagnostics.extend(item.diagnostic_id for item in page.diagnostics if item.affects_completeness)

            first_fragment = contributing[0][0]
            first_page = first_fragment["page"]
            locator = dict(first_fragment["source_locator"])
            locator.update({
                "relative_path": document.relative_path,
                "page_number": first_page.page_number,
                "section_title": pending_title,
                "heading_path": list(pending_heading_path or ()),
                "page_ids": page_ids,
                "page_numbers": page_numbers,
                "section_ids": section_ids,
                "source_segments": source_segments,
            })
            text = (
                combined_text[word_spans[start].start():word_spans[end - 1].end()]
                if document.detected_format == "html"
                else " ".join(words[start:end])
            )
            emit_chunk(first_page, "text", text, pending_title, locator, list(dict.fromkeys(diagnostics)))

        pending_fragments.clear()
        pending_heading_path = None
        pending_title = None

    def append_table(page: NormalizedPage, table, table_section_title: str | None, source_locator: dict | None = None) -> None:
        """Serialize a non-empty table and emit it as a separate chunk."""
        table_text = "\n".join(" | ".join(cell or "" for cell in row) for row in [table.columns, *table.rows])
        if not table_text.strip():
            return
        locator = {
            "relative_path": document.relative_path,
            "page_number": page.page_number,
            "section_title": table_section_title,
            "table_id": table.table_id,
        }
        if source_locator:
            locator.update(source_locator)
            locator["relative_path"] = document.relative_path
            locator["page_number"] = page.page_number
            locator["section_title"] = table_section_title
            locator["table_id"] = table.table_id
        emit_chunk(page, "table", table_text, table_section_title, locator, [item.diagnostic_id for item in table.diagnostics])

    active_heading_path: tuple[str, ...] = ()
    for page in document.pages:
        tables_by_id = {table.table_id: table for table in page.tables}
        emitted_tables: set[str] = set()

        if page.sections:
            for section in page.sections:
                if section.kind == "heading":
                    flush_text_section()
                    active_heading_path = tuple(section.heading_path)
                    continue
                if section.kind == "table":
                    flush_text_section()
                    table = tables_by_id.get(section.table_id or "")
                    if table is not None:
                        table_path = tuple(section.heading_path) or active_heading_path
                        table_title = table_path[-1] if table_path else page.section_title
                        active_heading_path = table_path
                        append_table(page, table, table_title, section.source_locator)
                        emitted_tables.add(table.table_id)
                    continue
                if section.kind not in {"paragraph", "list_item", "other"} or not section.text.strip():
                    continue
                section_path = tuple(section.heading_path) or active_heading_path
                if not section_path and page.section_title:
                    section_path = (page.section_title,)
                if pending_fragments and pending_heading_path != section_path:
                    flush_text_section()
                active_heading_path = section_path
                if not pending_fragments:
                    pending_heading_path = section_path
                    pending_title = section_path[-1] if section_path else page.section_title
                pending_fragments.append({
                    "page": page,
                    "section_id": section.section_id,
                    "source_locator": section.source_locator,
                    "text": section.text.strip(),
                })
        elif page.normalized_text and page.normalized_text.strip():
            section_path = (page.section_title,) if page.section_title else active_heading_path
            if pending_fragments and pending_heading_path != section_path:
                flush_text_section()
            active_heading_path = section_path
            if not pending_fragments:
                pending_heading_path = section_path
                pending_title = section_path[-1] if section_path else None
            pending_fragments.append({
                "page": page,
                "section_id": None,
                "source_locator": {"page_number": page.page_number},
                "text": page.normalized_text.strip(),
            })

        for table in page.tables:
            if table.table_id not in emitted_tables:
                flush_text_section()
                append_table(page, table, page.section_title)
    flush_text_section()
    return chunks


def _split_section(text: str) -> list[str]:
    """Split text into word-bounded chunks using the shared overlap policy.

    Args:
        text: Section text to split.

    Returns:
        Ordered text fragments joined with single spaces.
    """
    words = re.findall(r"\S+", text)
    return [" ".join(words[start:end]) for start, end in _split_word_ranges(text, words)]


def _split_word_ranges(text: str, words: list[str]) -> list[tuple[int, int]]:
    """Choose word index ranges near target sizes and natural boundaries.

    Args:
        text: Original combined text used to identify paragraph boundaries.
        words: Non-whitespace tokens corresponding to ``text``.

    Returns:
        Half-open ``(start, end)`` word-index ranges with configured overlap;
        an empty word list returns no ranges.
    """
    matches = list(re.finditer(r"\S+", text))
    if not matches:
        return []
    paragraph_boundaries: set[int] = set()
    sentence_boundaries: set[int] = set()
    for index in range(1, len(matches)):
        gap = text[matches[index - 1].end():matches[index].start()]
        if "\n" in gap:
            paragraph_boundaries.add(index)
        if re.search(r"[.!?][\"')\]]*$", words[index - 1]):
            sentence_boundaries.add(index)

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(words):
        remaining = len(words) - start
        if remaining <= MAX_CHUNK_WORDS:
            end = len(words)
        else:
            target_end = min(start + TARGET_CHUNK_WORDS, len(words))
            maximum_end = min(start + MAX_CHUNK_WORDS, len(words))
            eligible = lambda boundaries: [position for position in boundaries if start + CHUNK_OVERLAP_WORDS < position <= target_end]
            paragraph_choices = eligible(paragraph_boundaries)
            sentence_choices = eligible(sentence_boundaries)
            if paragraph_choices:
                end = max(paragraph_choices)
            elif sentence_choices:
                end = max(sentence_choices)
            else:
                later_boundaries = [
                    position for position in paragraph_boundaries | sentence_boundaries
                    if target_end < position <= maximum_end
                ]
                end = min(later_boundaries) if later_boundaries else maximum_end
        ranges.append((start, end))
        if end == len(words):
            break
        start = max(start + 1, end - CHUNK_OVERLAP_WORDS)
    return ranges
