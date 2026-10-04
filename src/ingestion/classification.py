"""Detect document formats and classify bid files using filename/content evidence."""

from __future__ import annotations

import re
from pathlib import Path

from .models import ClassificationEvidence, DocumentClassification, DocumentType
from .provenance import stable_id


def detected_format(path: Path) -> str:
    """Infer HTML, PDF, or unknown format from the filename extension.

    Args:
        path: Source file path.

    Returns:
        ``html`` for ``.html``/``.htm``, ``pdf`` for ``.pdf``, otherwise
        ``unknown``.
    """
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".pdf":
        return "pdf"
    return "unknown"


def has_format_mismatch(path: Path) -> bool:
    """Return whether a known extension disagrees with the file signature.

    Args:
        path: Source file path whose first 4096 bytes are inspected.

    Returns:
        ``True`` when a readable PDF/HTML file lacks its expected signature;
        unknown extensions and unreadable files return ``False``.
    """
    try:
        header = path.read_bytes()[:4096].lower()
    except OSError:
        return False
    if path.suffix.lower() == ".pdf":
        return not header.startswith(b"%pdf")
    if path.suffix.lower() in {".html", ".htm"}:
        return not any(marker in header for marker in (b"<html", b"<!doctype", b"<body", b"<head"))
    return False


def classify(path: Path) -> DocumentType | None:
    """Guess a coarse document type from common filename markers.

    Args:
        path: Source file path.

    Returns:
        One of the ``DocumentType`` labels, or ``None`` only if no recognized
        format is available from the filename.
    """
    name = path.name.lower()
    if detected_format(path) == "unknown":
        return "unknown"
    if "addendum" in name or "amendment" in name:
        return "addendum"
    if "affidavit" in name:
        return "affidavit"
    if "spec" in name:
        return "specs"
    if path.suffix.lower() in {".html", ".htm"} or "bidnet" in name or "bid information" in name:
        return "bid_page"
    if any(token in name for token in ("rfp", "porfp", "proposal", "final", "solicitation")):
        return "rfp"
    return "supporting"


def addendum_number(path: Path) -> int | None:
    """Extract the first numeric addendum/amendment label from a filename.

    Args:
        path: File path whose name may contain an addendum number.

    Returns:
        Parsed integer number, or ``None`` when no label is present.
    """
    match = re.search(r"(?:addendum|amendment)[^0-9]*(\d+)", path.name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def classify_document(
    path: Path,
    content: str,
    *,
    source_locator: dict | None = None,
) -> DocumentClassification:
    """Resolve document type and addendum number from content and filename.

    Args:
        path: Source path used as filename evidence.
        content: Extracted document text searched for explicit classification
            patterns and addendum numbers.
        source_locator: Optional base source-location mapping copied into
            content evidence; defaults to a relative filename locator.

    Returns:
        ``DocumentClassification`` with selected type/number, classified,
        unknown, or conflict status, all evidence entries, and the selected
        evidence ID where available. Explicit content evidence outranks
        filename evidence.
    """
    evidence: list[ClassificationEvidence] = []
    locator_base = dict(source_locator or {"relative_path": path.name})
    filename_type = classify(path)
    filename = path.name.casefold()
    filename_type_is_descriptive = not (
        filename_type == "bid_page"
        and path.suffix.casefold() in {".html", ".htm"}
        and not any(token in filename for token in ("bidnet", "bid information"))
    )
    if filename_type is not None and filename_type_is_descriptive and (filename_type != "supporting" or "supporting" in filename):
        evidence.append(
            ClassificationEvidence(
                stable_id("classification", "doc_type", "filename", path.name, filename_type),
                "doc_type",
                filename_type,
                "filename",
                {"relative_path": path.name},
                "supporting",
            )
        )
    filename_addendum = addendum_number(path)
    if filename_addendum is not None:
        evidence.append(
            ClassificationEvidence(
                stable_id("classification", "addendum_number", "filename", path.name, filename_addendum),
                "addendum_number",
                filename_addendum,
                "filename",
                {"relative_path": path.name},
                "supporting",
            )
        )

    content_patterns: tuple[tuple[DocumentType, re.Pattern[str]], ...] = (
        ("addendum", re.compile(r"\b(?:addendum|amendment)\b", re.IGNORECASE)),
        ("rfp", re.compile(r"\brequest for proposal\b|\b(?:RFP|PORFP)\b", re.IGNORECASE)),
        ("affidavit", re.compile(r"\baffidavit\b", re.IGNORECASE)),
        ("specs", re.compile(r"\b(?:technical\s+)?specifications?\b", re.IGNORECASE)),
        ("bid_page", re.compile(r"\bbid information\b|\bbidnet direct\b", re.IGNORECASE)),
    )
    explicit_addendum_heading = re.search(
        r"^\s*(?:addendum|amendment)\s*(?:no\.?|number)?\s*[:#-]?\s*\d+\b",
        content,
        re.IGNORECASE | re.MULTILINE,
    )

    def content_strength(offset: int) -> str:
        """Label early line-start content matches explicit, others supporting."""
        line_start = content.rfind("\n", 0, offset) + 1
        line_number = content.count("\n", 0, offset)
        return "explicit" if line_number < 10 and not content[line_start:offset].strip() else "supporting"

    for doc_type, pattern in content_patterns:
        for match in pattern.finditer(content):
            strength = content_strength(match.start())
            if (
                doc_type == "rfp"
                and explicit_addendum_heading is not None
                and match.start() > explicit_addendum_heading.end()
                and content.count("\n", explicit_addendum_heading.end(), match.start()) <= 3
            ):
                strength = "supporting"
            locator = {**locator_base, "text_offset": match.start()}
            evidence.append(
                ClassificationEvidence(
                    stable_id("classification", "doc_type", "content", match.start(), doc_type),
                    "doc_type",
                    doc_type,
                    "content",
                    locator,
                    strength,
                )
            )

    addendum_pattern = re.compile(
        r"\b(?:addendum|amendment)\s*(?:no\.?|number)?\s*[:#-]?\s*(\d+)\b",
        re.IGNORECASE,
    )
    for match in addendum_pattern.finditer(content):
        number = int(match.group(1))
        locator = {**locator_base, "text_offset": match.start()}
        evidence.append(
            ClassificationEvidence(
                stable_id("classification", "addendum_number", "content", match.start(), number),
                "addendum_number",
                number,
                "content",
                locator,
                content_strength(match.start()),
            )
        )

    selected_values: dict[str, str | int | None] = {}
    conflicts: set[str] = set()
    selected_evidence_id: str | None = None
    for field_name in ("doc_type", "addendum_number"):
        content_evidence = [item for item in evidence if item.field == field_name and item.source_kind == "content"]
        filename_evidence = [item for item in evidence if item.field == field_name and item.source_kind == "filename"]
        def evidence_rank(item: ClassificationEvidence) -> int:
            """Rank explicit content above filename and supporting content."""
            if item.source_kind == "content" and item.strength == "explicit":
                return 0
            if item.source_kind == "filename":
                return 1
            return 2

        candidates = content_evidence + filename_evidence
        best_rank = min((evidence_rank(item) for item in candidates), default=None)
        authoritative = [item for item in candidates if evidence_rank(item) == best_rank]
        values = {item.candidate_value for item in authoritative if item.candidate_value is not None}
        if len(values) > 1:
            conflicts.add(field_name)
            selected_values[field_name] = None
        elif values:
            selected_values[field_name] = next(iter(values))
            selected_evidence_id = selected_evidence_id or authoritative[0].evidence_id
        else:
            selected_values[field_name] = None

    if conflicts:
        status = "conflict"
    elif all(value is None for value in selected_values.values()):
        status = "unknown"
    else:
        status = "classified"

    selected_doc_type = selected_values["doc_type"]
    selected_addendum = selected_values["addendum_number"]
    return DocumentClassification(
        selected_doc_type if selected_doc_type in {"bid_page", "rfp", "addendum", "specs", "affidavit", "supporting", "unknown"} else None,
        selected_addendum if isinstance(selected_addendum, int) else None,
        status,
        evidence,
        selected_evidence_id,
    )
