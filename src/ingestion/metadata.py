"""Parse source dates and select the best-supported document date."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .diagnostics import diagnostic
from .models import DateCandidate, ProcessingDiagnostic


_MONTH = r"January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
_DATE_PATTERN = re.compile(
    rf"\b(?:20\d{{2}}-\d{{2}}-\d{{2}}(?:[Tt][0-9:.+\-Zz]+)?|20\d{{2}}/\d{{1,2}}/\d{{1,2}}|"
    rf"\d{{1,2}}/\d{{1,2}}/20\d{{2}}|(?:{_MONTH})\s+\d{{1,2}},?\s+20\d{{2}}|"
    rf"\d{{1,2}}\s+(?:{_MONTH})\s+20\d{{2}})\b",
    re.IGNORECASE,
)


def parse_date_value(raw_value: str) -> tuple[str | None, str]:
    """Parse a recognized date spelling into ISO format and a status label.

    Args:
        raw_value: Date text, including supported ISO, slash-separated,
            month-name, or PDF metadata forms.

    Returns:
        Pair of ``(YYYY-MM-DD or None, status)`` where status is ``candidate``,
        ``ambiguous``, or ``invalid``.
    """
    value = raw_value.strip()
    pdf_date = re.fullmatch(r"D:(20\d{2})(\d{2})(\d{2}).*", value)
    if pdf_date:
        value = "-".join(pdf_date.groups())

    iso_prefix = re.match(r"^(20\d{2}-\d{2}-\d{2})", value)
    year_first = re.fullmatch(r"(20\d{2})/(\d{1,2})/(\d{1,2})", value)
    try:
        if iso_prefix:
            return date.fromisoformat(iso_prefix.group(1)).isoformat(), "candidate"
        if year_first:
            year, month, day = (int(part) for part in year_first.groups())
            return date(year, month, day).isoformat(), "candidate"
    except ValueError:
        return None, "invalid"

    numeric = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(20\d{2})", value)
    if numeric:
        first, second, year = (int(part) for part in numeric.groups())
        if first <= 12 and second <= 12:
            return None, "ambiguous"
        month, day = (first, second) if first <= 12 else (second, first)
        try:
            return date(year, month, day).isoformat(), "candidate"
        except ValueError:
            return None, "invalid"

    for pattern in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat(), "candidate"
        except ValueError:
            continue
    return None, "invalid"


def make_date_candidate(
    raw_value: str,
    source_kind: str,
    source_locator: dict,
    precedence: int,
) -> DateCandidate:
    """Create a date candidate with parsed value and source provenance.

    Args:
        raw_value: Original date string.
        source_kind: Source category used during precedence selection.
        source_locator: Mapping locating the date in its source document.
        precedence: Lower integer values indicate more authoritative sources.

    Returns:
        ``DateCandidate`` containing the raw value, normalized ISO date when
        valid, source metadata, precedence, and parse status.
    """
    normalized_date, status = parse_date_value(raw_value)
    return DateCandidate(raw_value, normalized_date, source_kind, dict(source_locator), precedence, status)


def date_candidates_from_text(
    text: str,
    *,
    source_locator: dict | None = None,
) -> list[DateCandidate]:
    """Find date candidates in visible text and classify nearby date labels.

    Args:
        text: Source text to scan using supported date patterns.
        source_locator: Optional base locator copied into each candidate.

    Returns:
        Candidates in text order. Each locator includes the character
        ``text_offset``; visibly labeled issue/publication dates receive higher
        precedence than unlabeled dates.
    """
    candidates: list[DateCandidate] = []
    for match in _DATE_PATTERN.finditer(text):
        raw_value = match.group(0)
        preceding_text = text[max(0, match.start() - 48) : match.start()]
        labeled = bool(
            re.search(r"(?:issue|issued|publication|published|release|solicitation)\s*(?:date)?\s*[:\-]?\s*$", preceding_text, re.I)
        )
        locator = dict(source_locator or {})
        locator["text_offset"] = match.start()
        candidates.append(
            make_date_candidate(
                raw_value,
                "labeled_visible_text" if labeled else "visible_text",
                locator,
                2 if labeled else 3,
            )
        )
    return candidates


def select_document_date(
    candidates: list[DateCandidate],
) -> tuple[str | None, list[ProcessingDiagnostic]]:
    """Select a reliable date while detecting ambiguity and conflicts.

    Args:
        candidates: Parsed date candidates, mutated to selected/conflicting
            statuses as appropriate.

    Returns:
        Pair of selected ISO date or ``None``, and diagnostics describing
        invalid, ambiguous, unavailable, or conflicting candidates.
    """
    diagnostics: list[ProcessingDiagnostic] = []
    eligible = [
        candidate
        for candidate in candidates
        if candidate.source_kind not in {"technical_timestamp", "modified_metadata"}
    ]
    ambiguous = [candidate for candidate in eligible if candidate.status == "ambiguous"]
    valid = [candidate for candidate in eligible if candidate.normalized_date is not None]

    for candidate in eligible:
        if candidate.status == "invalid":
            diagnostics.append(
                diagnostic(
                    "file",
                    "document_date_invalid",
                    "A document date candidate could not be parsed",
                    source_locator=candidate.source_locator,
                    affects_completeness=False,
                )
            )
        elif candidate.status == "ambiguous":
            diagnostics.append(
                diagnostic(
                    "file",
                    "document_date_ambiguous",
                    "A numeric document date has an ambiguous month/day order",
                    source_locator=candidate.source_locator,
                    affects_completeness=False,
                )
            )

    if ambiguous and (not valid or min(item.precedence for item in ambiguous) <= min(item.precedence for item in valid)):
        return None, diagnostics
    if not valid:
        if not ambiguous and not any(candidate.status == "invalid" for candidate in eligible):
            diagnostics.append(
                diagnostic(
                    "file",
                    "document_date_unavailable",
                    "No reliable document date candidate was available",
                    severity="info",
                    affects_completeness=False,
                )
            )
        return None, diagnostics

    highest_precedence = min(candidate.precedence for candidate in valid)
    highest = [candidate for candidate in valid if candidate.precedence == highest_precedence]
    highest_dates = {candidate.normalized_date for candidate in highest}
    if len(highest_dates) > 1:
        for candidate in highest:
            candidate.status = "conflicting"
        diagnostics.append(
            diagnostic(
                "file",
                "document_date_conflict",
                "Equally authoritative document date candidates disagree",
                source_locator={"candidates": [candidate.source_locator for candidate in highest]},
                affects_completeness=False,
            )
        )
        return None, diagnostics

    selected = highest[0]
    selected.status = "selected"
    selected_date = selected.normalized_date
    conflicting = [candidate for candidate in valid if candidate.normalized_date != selected_date]
    for candidate in conflicting:
        candidate.status = "conflicting"
    if conflicting:
        diagnostics.append(
            diagnostic(
                "file",
                "document_date_conflict",
                "Lower-priority document date candidates disagree with the selected date",
                source_locator={"selected": selected.source_locator, "conflicting": [item.source_locator for item in conflicting]},
                affects_completeness=False,
            )
        )
    return selected_date, diagnostics


def document_date(text: str) -> str | None:
    """Return the selected date found in visible text, if any.

    Args:
        text: Document text to scan.

    Returns:
        Selected ISO date string or ``None`` when no reliable date exists.
    """
    selected, _ = select_document_date(date_candidates_from_text(text))
    return selected


def html_location(path: Path, section: str | None) -> dict[str, str | None]:
    """Build a compact HTML source locator from path and section title."""
    return {"relative_path": path.as_posix(), "section_title": section}
