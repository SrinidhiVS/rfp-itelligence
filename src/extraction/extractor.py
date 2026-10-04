"""Extract canonical procurement fields from ranked source evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .citations import citation_from_evidence
from .fields import CANONICAL_FIELDS, COLLECTION_FIELDS, FIELD_TERMS
from .identity import normalized_bid_id
from .models import ExtractedField, FieldValueItem, ProcessingDiagnostic
from .normalization import normalize_collection_items, normalize_value
from .reconciliation import is_addendum_evidence, reconcile
from .record_builder import build_record


class StructuredExtractor:
    """Build a validated structured bid record from indexed evidence.

    Args:
        evidence_provider: Optional callable accepting a normalized bid ID and
            returning evidence dictionaries; explicit ``evidence`` passed to
            ``extract`` takes precedence.
    """

    def __init__(self, evidence_provider=None):
        """Store an optional callable that supplies evidence for a bid ID."""
        self.evidence_provider = evidence_provider

    def extract(self, bid_folder: str, evidence: Iterable[dict[str, Any]] | None = None, diagnostics: list[ProcessingDiagnostic] | None = None):
        """Extract all canonical fields and reconcile applicable addenda.

        Args:
            bid_folder: Bid folder path or identifier; its final path component
                is used as the requested ID.
            evidence: Optional iterable of evidence mappings. Each may contain
                a nested ``record`` mapping or record fields at the top level.
                Records are scoped to the requested bid; unscoped evidence is
                used when no requested-bid evidence is present.
            diagnostics: Optional ingestion/extraction diagnostics appended to
                evidence-availability diagnostics.

        Returns:
            ``BidExtractionRecord`` with every canonical field, citations,
            addendum changes, validation summary, and diagnostics. Collection
            field values are ``FieldValueItem`` lists; missing fields are
            explicit null values with ``not_found`` status.
        """
        requested_bid_id = Path(bid_folder).name
        if evidence is None and self.evidence_provider:
            bid_id = normalized_bid_id(bid_folder)
            evidence_items = list(self.evidence_provider(bid_id))
            evidence_items = [
                item for item in evidence_items
                if not item.get("record", item).get("bid_id")
                or item.get("record", item).get("bid_id") == bid_id
            ]
        else:
            all_evidence = list(evidence or [])
            matching_evidence = [
                item for item in all_evidence
                if item.get("record", item).get("bid_id") == requested_bid_id
            ]
            if matching_evidence:
                bid_id = requested_bid_id
                evidence_items = matching_evidence
            else:
                bid_id = normalized_bid_id(bid_folder)
                evidence_items = [
                    item for item in all_evidence
                    if not item.get("record", item).get("bid_id")
                ]
        base_evidence = [
            item for item in evidence_items
            if not is_addendum_evidence(item)
        ]
        fields: dict[str, ExtractedField] = {}
        for field in CANONICAL_FIELDS:
            if field in COLLECTION_FIELDS:
                fields[field] = self._extract_collection(field, base_evidence, bid_id)
                continue
            matches = []
            for item in base_evidence:
                if not self._matches(field, item):
                    continue
                record = item.get("record", item)
                text = record.get("text", "")
                locator = record.get("source_locator")
                section_title = record.get("section_title") or (locator.get("section_title", "") if isinstance(locator, dict) else "") or ""
                if field == "Due Date" and section_title.casefold() == "dates":
                    date_matches = list(re.finditer(r"\b\d{1,2}/\d{1,2}/\d{4}\b", text))
                    if len(date_matches) >= 2:
                        text = "Closing Date " + text[date_matches[1].start():]
                normalized = normalize_value(field, text)
                if normalized is not None:
                    matches.append((item, normalized))
            if field == "Bid Number":
                porfp_matches = [
                    match for match in matches
                    if re.search(r"\bPORFP\s+Number\b", match[0].get("record", match[0]).get("text", ""), re.IGNORECASE)
                ]
                if porfp_matches:
                    matches = porfp_matches
            elif field == "Term of Bid":
                matches.sort(key=lambda match: len(str(match[1])), reverse=True)
            if not matches:
                note = f"Not found in documents: no indexed evidence was found for {field}; verify source coverage before treating it as absent."
                if field == "Bid Number":
                    note += f" Official identifier unavailable; generated numeric bid_id '{bid_id}' is retained for this folder."
                fields[field] = ExtractedField(name=field, value=None, citations=[], confidence=0.0, notes=note, status="not_found")
                continue
            item, value = matches[0]
            field_citations = None
            if field == "Due Date":
                primary = next(
                    (match for match in matches if match[0].get("record", match[0]).get("doc_type") != "bid_page"),
                    matches[0],
                )
                primary_date = primary[1].split()[0]
                same_date = [match for match in matches if match[1].split()[0] == primary_date]
                detailed = [match for match in same_date if len(match[1].split()) > len(primary[1].split())]
                if detailed:
                    item, value = max(detailed, key=lambda match: len(match[1].split()))
                    field_citations = [citation_from_evidence(match[0], bid_id) for match in same_date]
                else:
                    item, value = primary
            record = item.get("record", item)
            citation = citation_from_evidence(item, bid_id)
            fields[field] = ExtractedField(name=field, value=value, citations=field_citations or [citation], confidence=0.8, notes="Extracted from cited evidence.", status="supported")
        changes = reconcile(fields, evidence_items, bid_id)
        return build_record(bid_id, fields, changes=changes, diagnostics=(diagnostics or []) + self._diagnostics(evidence_items))

    @classmethod
    def _extract_collection(cls, field: str, evidence: list[dict[str, Any]], bid_id: str) -> ExtractedField:
        """Extract, deduplicate, and cite all supported values for a list field.

        Args:
            field: Canonical collection field name.
            evidence: Non-addendum evidence mappings.
            bid_id: Bid ID written into generated citations.

        Returns:
            Supported ``ExtractedField`` containing distinct item-level values
            and citations, or a not_found field with ``value=None``.
        """
        if field == "company_name":
            official_evidence = [
                item for item in evidence
                if item.get("record", item).get("doc_type") != "bid_page"
                and normalize_collection_items(field, item.get("record", item).get("text", ""))
            ]
            if official_evidence:
                evidence = official_evidence
        preferred_kind = "table" if field in {"Product Specification", "Model_no"} else "text" if field in {"company_name", "contact_info"} else None
        if preferred_kind:
            preferred_pages = {
                (record.get("source_file"), record.get("page_number"))
                for item in evidence
                if (record := item.get("record", item)).get("content_kind") == preferred_kind
            }
            if preferred_pages:
                evidence = [
                    item for item in evidence
                    if (item.get("record", item).get("source_file"), item.get("record", item).get("page_number")) not in preferred_pages
                    or item.get("record", item).get("content_kind") == preferred_kind
                ]
        unique_items: dict[str, FieldValueItem] = {}
        for item in evidence:
            if not cls._matches(field, item):
                continue
            record = item.get("record", item)
            for value, attributes in normalize_collection_items(field, record.get("text", "")):
                if not value:
                    continue
                value = " ".join(value.split())
                key = value.casefold()
                citation = citation_from_evidence(item, bid_id)
                existing = unique_items.get(key)
                if existing:
                    if attributes:
                        existing.attributes.update(attributes)
                    if citation not in existing.citations:
                        existing.citations.append(citation)
                    continue
                unique_items[key] = FieldValueItem(value=value, attributes=attributes, citations=[citation])
        if not unique_items:
            return ExtractedField(
                name=field,
                value=None,
                citations=[],
                confidence=0.0,
                notes=f"Not found in documents: no indexed evidence was found for {field}; verify source coverage before treating it as absent.",
                status="not_found",
            )
        items = list(unique_items.values())
        citations_by_key = {
            citation.model_dump_json(): citation
            for value_item in items
            for citation in value_item.citations
        }
        citations = list(citations_by_key.values())
        return ExtractedField(
            name=field,
            value=items,
            citations=citations,
            confidence=0.8,
            notes="Extracted distinct values with item-level evidence.",
            status="supported",
        )

    @staticmethod
    def _matches(field: str, item: dict[str, Any]) -> bool:
        """Return whether an evidence item contains signals for a field.

        Args:
            field: Canonical field name.
            item: Evidence mapping with optional nested ``record``.

        Returns:
            Boolean match based on special field rules or configured field
            terms.
        """
        record = item.get("record", item)
        locator = record.get("source_locator")
        section_title = record.get("section_title") or (locator.get("section_title", "") if isinstance(locator, dict) else "") or ""
        if field == "Due Date" and section_title.casefold() == "dates":
            return True
        text = record.get("text", "")
        lowered = text.lower()
        if field == "Bid Number" and re.match(r"^\s*[A-Z]{1,8}[-_]\d{3,}\b", text):
            return True
        if field in {"Bid Number", "Title"} and re.search(
            r"\b(?:request\s+for\s+proposal|request\s+for\s+quotation|invitation\s+to\s+bid)\b"
            r"(?:\s*\([^)]*\))?\s+(?:\d{3,}\s+)?[A-Z]{1,8}[-_]\d{3,}\b",
            text, re.IGNORECASE,
        ):
            return True
        if field == "company_name":
            return bool(re.search(
                r"issuing\s+organization|agency\s*/\s*division\s+name|dallas\s+independent\s+school\s+district\s+(?:\(Dallas ISD[^)]*\)\s+)?is\s+soliciting",
                text,
                re.IGNORECASE,
            ))
        if field == "contact_info":
            return bool(re.search(r"\bBuyer\b[\s\S]{0,100}\bEmail\b|Agency\s+POC\s+Name|Agency\s+On-site\s+Contact\s+Name", text, re.IGNORECASE))
        if field == "Product":
            return bool(re.search(r"\bincluding\s+(?:laptops|desktops|tablet)|Product(?:\s+Name)?\s*[:|]", text, re.IGNORECASE))
        if field == "Any Additional Documentation Required":
            record = item.get("record", item)
            if record.get("doc_type") == "affidavit":
                return False
            return bool(re.search(
                r"(?:additional\s+documents\s+required|required\s+documents)\s*[:\-]|Form\s+1295|Mercury\s+Affidavit|factory-authorized repair and maintenance certifications|"
                r"pertinent literature/documentation|credit application or similar documentation|"
                r"warranty certificate or affidavit|acknowledge and return.{0,60}Addendum|"
                r"submit this addendum|sign this addendum|supporting documentation",
                text,
                re.IGNORECASE,
            ))
        if field == "Model_no":
            return bool(re.search(r"(?:\bModel\s*(?:#|number|no\.?)|\bSI#)", text, re.IGNORECASE))
        if field == "Part_no":
            return bool(re.search(r"\b(?:SKU|Part\s*(?:#|number|no\.?))\b", text, re.IGNORECASE))
        if field == "Product Specification":
            if record.get("doc_type") == "bid_page":
                return False
            return bool(re.search(
                r"\b(?:processor|\d+\s*(?:GB|TB)|DDR\d|NVMe|SSD|eMMC|FHD|Wi-?Fi|802\.11|Bluetooth|battery|AC adapter|ENERGY STAR|EPEAT|Copilot ready)\b",
                text,
                re.IGNORECASE,
            ))
        return any(term in lowered for term in FIELD_TERMS[field])

    @staticmethod
    def _diagnostics(evidence: list[dict[str, Any]]) -> list[ProcessingDiagnostic]:
        """Return an empty-evidence warning when no indexed evidence exists."""
        return [ProcessingDiagnostic(code="empty_evidence", severity="warning", message="No indexed evidence was available.", recoverable=True)] if not evidence else []
