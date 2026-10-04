"""Parse HTML bid sources into normalized sections, tables, and metadata."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .diagnostics import diagnostic
from .metadata import make_date_candidate
from .models import DocumentMetadata, HtmlSection, MetadataValue, NormalizedPage, ProcessingDiagnostic
from .normalization import normalize_text
from .normalization import remove_repeated_page_furniture
from .provenance import page_id
from .tables import table_from_rows


def _is_explicit_page_block(node: object) -> bool:
    """Recognize an HTML element explicitly marked as a page boundary."""
    classes = getattr(node, "get", lambda *_: None)("class", []) or []
    if isinstance(classes, str):
        classes = classes.split()
    page_classes = {"page", "pdf-page", "document-page", "page-container"}
    if page_classes.intersection(str(value).casefold() for value in classes):
        return True
    if getattr(node, "has_attr", lambda *_: False)("data-page") or getattr(node, "has_attr", lambda *_: False)("data-page-number"):
        return True
    style = str(getattr(node, "get", lambda *_: "")("style", ""))
    return bool(re.search(r"(?:page-break-(?:before|after)|break-(?:before|after))\s*:\s*(?:always|left|right)\b", style, re.I))


def _html_page_furniture(
    body: object,
    path: Path,
) -> tuple[set[int], list[ProcessingDiagnostic]]:
    """Identify repeated edge furniture inside explicit HTML page containers.

    Args:
        body: Parsed body/root node containing page-like descendants.
        path: HTML source path used in diagnostic locators.

    Returns:
        Pair of excluded element identities and informational diagnostics.
        Fewer than two explicit page blocks produces empty results.
    """
    page_nodes = [node for node in body.find_all(True) if _is_explicit_page_block(node)]
    page_ids = {id(node) for node in page_nodes}
    page_nodes = [
        node
        for node in page_nodes
        if not any(id(parent) in page_ids for parent in node.parents if parent is not body)
    ]
    if len(page_nodes) < 2:
        return set(), []

    content_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"}
    page_content: list[list[object]] = []
    page_lines: list[list[str]] = []
    for page_node in page_nodes:
        elements = [node for node in page_node.find_all(True) if node.name and node.name.lower() in content_tags]
        page_content.append(elements)
        page_lines.append([node.get_text(" ", strip=True) for node in elements])

    _, removed_pages, uncertain_pages = remove_repeated_page_furniture(page_lines)
    excluded: set[int] = set()
    diagnostics: list[ProcessingDiagnostic] = []
    for page_index, (elements, lines) in enumerate(zip(page_content, page_lines)):
        removed_counts = Counter(removed_pages[page_index])
        uncertain_counts = Counter(uncertain_pages[page_index])
        removed_count = 0
        uncertain_count = 0
        for element_index, (element, line) in enumerate(zip(elements, lines)):
            edge = element_index < 2 or element_index >= len(lines) - 1
            if edge and removed_counts[line] > 0:
                excluded.add(id(element))
                removed_counts[line] -= 1
                removed_count += 1
            elif edge and uncertain_counts[line] > 0:
                uncertain_counts[line] -= 1
                uncertain_count += 1
        locator = {"relative_path": path.name, "page_block_index": page_index}
        if removed_count:
            diagnostics.append(
                diagnostic(
                    "page",
                    "repeated_page_furniture_removed",
                    f"Removed {removed_count} repeated edge line(s) from an explicit HTML page block",
                    source_locator=locator,
                    severity="info",
                    affects_completeness=False,
                )
            )
        if uncertain_count:
            diagnostics.append(
                diagnostic(
                    "page",
                    "repeated_page_furniture_uncertain",
                    f"Preserved {uncertain_count} repeated edge candidate line(s) in an explicit HTML page block",
                    source_locator=locator,
                    severity="info",
                    affects_completeness=False,
                )
            )
    return excluded, diagnostics


def _metadata_locator(path: Path, node: object, element_index: int, **details: object) -> dict:
    """Build an HTML metadata locator with element index and source line."""
    locator = {"relative_path": path.name, "element_index": element_index, **details}
    source_line = getattr(node, "sourceline", None)
    if source_line is not None:
        locator["source_line"] = source_line
    return locator


def _html_metadata(soup: BeautifulSoup, path: Path) -> tuple[DocumentMetadata, list[ProcessingDiagnostic]]:
    """Extract HTML title, description, language, canonical URL, and dates.

    Args:
        soup: Parsed BeautifulSoup HTML document.
        path: Source path included in metadata locators.

    Returns:
        Pair of ``DocumentMetadata`` and informational validation diagnostics.
    """
    metadata = DocumentMetadata()
    diagnostics: list[ProcessingDiagnostic] = []
    values: list[MetadataValue] = []
    candidates = []
    html_node = soup.find("html")
    html_language = html_node.get("lang") if html_node else None
    if isinstance(html_language, str) and html_language.strip():
        metadata.language = html_language.strip()
        values.append(MetadataValue("language", metadata.language, "html_attribute", _metadata_locator(path, html_node, 0, tag="html", attribute="lang")))

    title_node = soup.find("title")
    if title_node:
        title = title_node.get_text(" ", strip=True)
        if title:
            metadata.title = title
            values.append(MetadataValue("title", title, "html_title", _metadata_locator(path, title_node, 0, tag="title")))

    for element_index, node in enumerate(soup.find_all("meta")):
        key = node.get("name") or node.get("property") or node.get("itemprop") or node.get("http-equiv")
        content = node.get("content")
        if not isinstance(key, str) or not isinstance(content, str) or not content.strip():
            continue
        key = key.strip()
        content = content.strip()
        key_folded = key.casefold()
        attribute = next((name for name in ("name", "property", "itemprop", "http-equiv") if node.get(name)), "content")
        locator = _metadata_locator(path, node, element_index, tag="meta", attribute=attribute, key=key)
        values.append(MetadataValue(key, content, "html_meta", locator))
        if key_folded in {"description", "og:description"} and metadata.description is None:
            metadata.description = content
        if key_folded == "og:title" and metadata.title is None:
            metadata.title = content

        compact_key = "".join(character for character in key_folded if character.isalnum())
        if compact_key in {"datepublished", "publicationdate", "dateissued", "issuedate"} or key_folded in {
            "article:published_time", "dc.date.issued", "datepublished"
        }:
            candidates.append(make_date_candidate(content, "semantic_metadata", locator, 0))
        elif compact_key in {"datemodified", "modifieddate"} or key_folded == "article:modified_time":
            candidate = make_date_candidate(content, "modified_metadata", locator, 99)
            candidate.status = "technical_only"
            candidates.append(candidate)
        elif compact_key in {"date", "dcdate"}:
            candidates.append(make_date_candidate(content, "html_date_metadata", locator, 2))

    for element_index, node in enumerate(soup.find_all("link")):
        rel = node.get("rel") or []
        if isinstance(rel, str):
            rel = rel.split()
        href = node.get("href")
        if "canonical" not in [str(item).casefold() for item in rel] or not isinstance(href, str) or not href.strip():
            continue
        canonical = href.strip()
        locator = _metadata_locator(path, node, element_index, tag="link", attribute="href", rel="canonical")
        values.append(MetadataValue("canonical", canonical, "html_link", locator))
        parsed = urlsplit(canonical)
        if parsed.scheme in {"http", "https"} and parsed.netloc and not any(character.isspace() for character in canonical):
            metadata.canonical_url = canonical
        else:
            diagnostics.append(
                diagnostic("page", "html_metadata_invalid", "Canonical URL is not an absolute HTTP(S) URL", source_locator=locator, severity="info", affects_completeness=False)
            )

    metadata.values = values
    metadata.date_candidates = candidates
    if not values:
        diagnostics.append(
            diagnostic("page", "html_metadata_missing", "No supported HTML document metadata was found", source_locator={"relative_path": path.name}, severity="info", affects_completeness=False)
        )
    return metadata, diagnostics


def parse_html(path: Path, document_id: str) -> list[NormalizedPage]:
    """Parse one HTML file into a single normalized page with sections/tables.

    Args:
        path: HTML source file, decoded as UTF-8 with replacement for invalid
            byte sequences.
        document_id: Stable source document ID used to derive the page ID.

    Returns:
        One-element list containing a ``NormalizedPage`` with raw and
        normalized text, structured sections, extracted tables, metadata, and
        parse diagnostics.

    Raises:
        OSError: If the file cannot be read.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")
    page_identifier = page_id(document_id, "html-1")
    metadata, metadata_diagnostics = _html_metadata(soup, path)
    sections: list[HtmlSection] = []
    tables = []
    heading_path: list[str] = []
    text_parts: list[str] = []
    body = soup.body or soup
    excluded_furniture, furniture_diagnostics = _html_page_furniture(body, path)

    for element_index, node in enumerate(body.find_all(True)):
        if id(node) in excluded_furniture:
            continue
        name = node.name.lower()
        if name in {"script", "style", "noscript", "template"}:
            continue
        if name in {"th", "td", "tr"} or node.find_parent("table"):
            if name != "table":
                continue
        heading_level = int(name[1]) if name in {f"h{level}" for level in range(1, 7)} else None
        kind = None
        table_identifier = None

        if heading_level is not None:
            content = node.get_text(" ", strip=True)
            heading_path = heading_path[: heading_level - 1]
            heading_path.append(content)
            kind = "heading"
        elif name == "p":
            content = node.get_text(" ", strip=True)
            kind = "paragraph"
        elif name == "li":
            content = node.get_text(" ", strip=True)
            kind = "list_item"
        elif name == "span" and any(str(value).endswith("field-label") for value in node.get("class", [])):
            label = node.get_text(" ", strip=True)
            content = label.rstrip(":") + ":" if label else ""
            kind = "other"
        elif name == "table":
            table_rows = node.find_all("tr")
            first_row_cells = table_rows[0].find_all(["th", "td"], recursive=False) if table_rows else []
            has_header = bool(node.find("thead")) or bool(first_row_cells and all(cell.name == "th" for cell in first_row_cells))
            rows = [
                [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"], recursive=False)]
                for row in table_rows
            ]
            rows = [row for row in rows if row]
            if rows:
                table = table_from_rows(page_identifier, len(tables), rows, has_header=has_header)
                tables.append(table)
                table_identifier = table.table_id
            content = node.get_text(" ", strip=True)
            kind = "table"
        elif name in {"div", "section", "article", "main", "aside", "blockquote"} and not node.find(
            ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "div", "section", "article", "main", "aside", "blockquote"]
        ):
            content = node.get_text(" ", strip=True)
            kind = "other"
        else:
            continue

        if not content:
            continue
        source_locator = {"relative_path": path.name, "element_index": element_index}
        if getattr(node, "sourceline", None) is not None:
            source_locator["source_line"] = node.sourceline
        sections.append(
            HtmlSection(
                section_id=f"{page_identifier}-section-{len(sections)}",
                kind=kind,
                text=content,
                heading_level=heading_level,
                heading_path=list(heading_path),
                page_id=page_identifier,
                table_id=table_identifier,
                source_locator=source_locator,
            )
        )
        text_parts.append(content)

    normalized_parts = [normalize_text(part) for part in text_parts]
    normalized = "\n".join(part for part in normalized_parts if part)
    if not normalized:
        normalized = normalize_text(soup.get_text("\n"))
    first_heading = next((section.text for section in sections if section.kind == "heading"), None)
    page = NormalizedPage(
        page_identifier,
        document_id,
        None,
        first_heading,
        raw,
        normalized,
        tables=tables,
        status="partial" if any(item.severity == "warning" for item in metadata_diagnostics) else "parsed",
        diagnostics=[*metadata_diagnostics, *furniture_diagnostics],
        sections=sections,
        metadata=metadata,
    )
    return [page]
