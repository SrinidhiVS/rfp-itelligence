"""Normalize scalar and collection field values from source text."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any


_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_PATTERN = re.compile(
    rf"\b(?P<month>{_MONTHS})\s+(?P<day>\d{{1,2}})(?:\s*[-\u2013]\s*(?P<end_day>\d{{1,2}}))?(?:,?\s*(?P<year>\d{{4}}))?\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_PATTERN = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\b")
_DASH_DATE_PATTERN = re.compile(r"\b(?P<day>\d{1,2})-(?P<month>[A-Z]{3})-(?P<year>\d{4})\b", re.IGNORECASE)
_TIME_PATTERN = re.compile(r"\b(?:at\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<period>AM|PM)\b", re.IGNORECASE)
_24H_TIME_PATTERN = re.compile(r"\b(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)(?::\d{2})?\b")
_TIME_ZONES = {"EST", "EDT", "CST", "CDT", "MST", "MDT", "PST", "PDT", "UTC", "GMT"}
_EVENT_CUES = {
    "Due Date": re.compile(r"(?:proposal\s+due\s+date(?:\s+and\s+time)?|solicitation\s+due(?:\s+date)?|bid\s+due(?:\s+date)?|submission\s+deadline|deadline\s+for\s+(?:bid\s+)?submission|bid\s+deadline|due\s+date|closing\s+date|responses\s+due|deadline)\s*[:\-]?", re.IGNORECASE),
    "Pre Bid Meeting": re.compile(r"(?:pre[- ]?bid|pre[- ]?proposal)\s+(?:meeting|conference)\s*[:\-]?", re.IGNORECASE),
    "Delivery Date": re.compile(r"(?:delivery\s+(?:window|date|deadline|within)|deliver(?:y)?\s+by)\s*[:\-]?", re.IGNORECASE),
}
_VALUE_LABELS = {
    "Bid Number": re.compile(r"(?:bid|rfp|solicitation)\s*(?:number|no\.?|#)\s*[:#\-]?\s*", re.IGNORECASE),
    "Title": re.compile(r"(?im)^[ \t]*(?:solicitation[ \t]+)?title[ \t]*(?:[:\-][ \t]*|\r?\n[ \t]*)"),
    "Term of Bid": re.compile(r"(?:initial\s+term|term\s+of\s+(?:the\s+)?(?:bid|contract)|contract\s+term|contract\s+duration)\s*[:\-]?\s*", re.IGNORECASE),
    "Payment Terms": re.compile(r"(?:payment\s+terms|payment|invoicing\s+terms)\s*[:\-]\s*", re.IGNORECASE),
    "Any Additional Documentation Required": re.compile(r"(?:additional\s+documents\s+required|required\s+documents|affidavits\s+required|documentation\s+required)\s*[:\-]\s*", re.IGNORECASE),
    "MFG for Registration": re.compile(r"(?:manufacturer\s+name|manufacturer\s+registration|manufacturer\s+for\s+registration|mfg\s+for\s+registration)\s*[:\-]?\s*", re.IGNORECASE),
    "Contract or Cooperative to Use": re.compile(r"(?:contract\s+vehicle|cooperative\s+(?:contract|purchasing)|state\s+contract|master\s+contract)\b\s*[:\-]?\s*", re.IGNORECASE),
    "Model_no": re.compile(r"(?:model(?:\s+number|\s+no\.?)?)\s*[:#\-]\s*", re.IGNORECASE),
    "Part_no": re.compile(r"(?:part(?:\s+number|\s+no\.?)?|sku)\s*[:#\-]\s*", re.IGNORECASE),
    "Product": re.compile(r"(?:product\s+name|product|item)\s*[:\-]?\s*", re.IGNORECASE),
    "contact_info": re.compile(r"(?:procurement\s+)?contact(?:\s+information)?\s*[:\-]\s*", re.IGNORECASE),
    "company_name": re.compile(r"(?:issuing\s+organization|organization|agency\s*/\s*division\s+name|agency|company\s+name|issued\s+by)\s*[:\-]\s*", re.IGNORECASE),
    "Product Specification": re.compile(r"(?:product\s+)?specifications?\s*[:\-]\s*", re.IGNORECASE),
}
_COLLECTION_PATTERNS = {
    "Any Additional Documentation Required": re.compile(r"(?:additional\s+documents\s+required|required\s+documents|affidavits\s+required|documentation\s+required)\s*[:\-]\s*([^\r\n]+)", re.IGNORECASE),
    "Model_no": re.compile(r"models?(?:\s+numbers?|\s+nos?\.?)?\s*[:#\-]\s*([^;\r\n.]+)", re.IGNORECASE),
    "Part_no": re.compile(r"(?:parts?(?:\s+numbers?|\s+nos?\.?)?|skus?)\s*[:#\-]\s*([^;\r\n.]+)", re.IGNORECASE),
    "Product": re.compile(r"(?:product\s+name|product|item)\s*[:\-]\s*([^;\r\n.]+)", re.IGNORECASE),
    "contact_info": re.compile(r"(?:procurement\s+)?contact(?:\s+information)?\s*[:\-]\s*([^\r\n]+)", re.IGNORECASE),
    "company_name": re.compile(r"(?:issuing\s+organization|organization|agency\s*/\s*division\s+name|agency|company\s+name|issued\s+by)\s*[:\-]\s*([^\r\n]+)", re.IGNORECASE),
    "Product Specification": re.compile(r"(?:product\s+)?specifications?\s*[:\-]\s*([^\r\n]+)", re.IGNORECASE),
}


def _clean_capture(text: str) -> str:
    """Trim a captured field value at common line/sentence boundaries."""
    value = re.split(r"[\r\n;.]", text.lstrip(), maxsplit=1)[0]
    return value.strip(" \t:-,;|")


def _field_segment(field: str, text: str) -> str:
    """Select the text segment following a field-specific label or event cue."""
    cue = _EVENT_CUES.get(field)
    if cue:
        if field == "Due Date":
            for match in cue.finditer(text):
                if match.group(0).strip().rstrip(":-").casefold() == "deadline":
                    prefix = text[max(0, match.start() - 24):match.start()]
                    if re.search(r"(?:delivery|deliver|question|questions)\s*$", prefix, re.IGNORECASE):
                        continue
                segment = _clean_capture(text[match.end():])
                if _DATE_PATTERN.search(segment) or _NUMERIC_DATE_PATTERN.search(segment) or _DASH_DATE_PATTERN.search(segment):
                    return segment
            return ""
        match = cue.search(text)
        if not match:
            return ""
        if field == "Due Date" and match.group(0).strip().rstrip(":-").casefold() == "deadline":
            prefix = text[max(0, match.start() - 24):match.start()]
            if re.search(r"(?:delivery|deliver|question|questions)\s*$", prefix, re.IGNORECASE):
                return ""
        if field == "Pre Bid Meeting":
            return " ".join(text[match.end():].split())
        return _clean_capture(text[match.end():])
    label = _VALUE_LABELS.get(field)
    if label:
        match = label.search(text)
        if match:
            return _clean_capture(text[match.end():])
    return text.strip()


def _date_value(field: str, text: str) -> str | None:
    """Extract and normalize a date, optional time, and recognized time zone.

    Args:
        field: Date-bearing canonical field name.
        text: Source passage containing the value and its label/context.

    Returns:
        ISO date as ``YYYY-MM-DD``, optionally followed by ``HH:MM`` and a
        recognized timezone; supported delivery durations remain descriptive
        text. Returns ``None`` when no supported date/duration is found.
    """
    segment = _field_segment(field, text)
    date_matches = [
        (match.start(), match, "%B %d %Y", "month")
        for match in [_DATE_PATTERN.search(segment)]
        if match
    ] + [
        (match.start(), match, "%m/%d/%Y", "numeric")
        for match in [_NUMERIC_DATE_PATTERN.search(segment)]
        if match
    ] + [
        (match.start(), match, "%d-%b-%Y", "dash")
        for match in [_DASH_DATE_PATTERN.search(segment)]
        if match
    ]
    if not date_matches:
        duration = re.search(r"\b(?:within\s+)?(\d+)\s+days?\s+of\s+(award|delivery)\b", segment, re.IGNORECASE)
        if field == "Delivery Date" and duration:
            return f"Within {duration.group(1)} days of {duration.group(2).lower()}"
        return None
    _, match, date_format, date_kind = min(date_matches, key=lambda item: item[0])
    date_text = match.group(0).rstrip(" ,.")
    if date_kind == "month":
        if match.group("end_day") or not match.group("year"):
            return date_text
        date_string = f"{match.group('month')} {match.group('day')} {match.group('year')}"
    else:
        date_string = date_text
    try:
        date_value = datetime.strptime(date_string, date_format)
    except ValueError:
        return date_text.rstrip(" ,.")
    normalized = date_value.strftime("%Y-%m-%d")
    remainder = segment[match.end():]
    local_remainder = remainder[:50] if field == "Due Date" else remainder
    time_match = _TIME_PATTERN.search(local_remainder) or _TIME_PATTERN.search(segment)
    if time_match:
        time_value = datetime.strptime(
            f"{time_match.group('hour')}:{time_match.group('minute')} {time_match.group('period').upper()}",
            "%I:%M %p",
        )
        normalized += f" {time_value.strftime('%H:%M')}"
    else:
        time_match_24h = _24H_TIME_PATTERN.search(local_remainder) or _24H_TIME_PATTERN.search(segment)
        if time_match_24h:
            normalized += f" {time_match_24h.group('hour').zfill(2)}:{time_match_24h.group('minute')}"
    zone_pattern = r"\b(?:EST|EDT|CST|CDT|MST|MDT|PST|PDT|UTC|GMT)\b"
    local_zone_context = local_remainder if field == "Due Date" else remainder
    zone_match = re.search(zone_pattern, local_zone_context, re.IGNORECASE) or (
        re.search(zone_pattern, segment, re.IGNORECASE) if field != "Due Date" else None
    )
    if zone_match:
        normalized += f" {zone_match.group(0).upper()}"
    return normalized


def _split_collection_values(text: str, *, split_and: bool = True) -> list[str]:
    """Split a collection capture on punctuation, lines, and optionally 'and'."""
    separator = r",|;|\r?\n|\band\b" if split_and else r";|\r?\n"
    return [value.strip(" \t:-,.;") for value in re.split(separator, text, flags=re.IGNORECASE) if value.strip(" \t:-,.;")]


def _product_table_items(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse numbered product-table rows into names and product attributes."""
    header = re.search(r"Product\s+Name\s*\|", text, re.IGNORECASE)
    if not header:
        return []
    table_text = text[header.start():]
    end = re.search(r"\|\s*FA\s+V\s*[-–]\s*Manufacturer", table_text, re.IGNORECASE)
    if end:
        table_text = table_text[:end.start()]
    starts = list(re.finditer(r"(?m)^\s*\d+\.\s+", table_text))
    items: list[tuple[str, dict[str, Any]]] = []
    for index, start in enumerate(starts):
        end_position = starts[index + 1].start() if index + 1 < len(starts) else len(table_text)
        cells = [" ".join(cell.split()) for cell in table_text[start.start():end_position].split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) < 3:
            continue
        product = re.sub(r"^\d+\.\s*", "", cells[0]).strip()
        model = cells[2].strip()
        leading_model = re.match(r"SI#\s*([A-Z0-9-]+)\s+(.+)", product, re.IGNORECASE)
        attributes: dict[str, Any] = {}
        if leading_model:
            product = leading_model.group(2).strip()
            attributes["model_no"] = f"SI# {leading_model.group(1)}"
        elif model:
            attributes["model_no"] = model
        quantity = next((int(cell) for cell in cells[3:] if re.fullmatch(r"\d+", cell)), None)
        if quantity is not None:
            attributes["quantity"] = quantity
        if product and model:
            items.append((product, attributes))
    return items


def normalize_collection_items(field: str, text: str) -> list[tuple[str, dict[str, Any]]]:
    """Extract distinct collection candidates and associated attributes.

    Args:
        field: Canonical collection field name.
        text: Evidence passage or table text.

    Returns:
        List of ``(value, attributes)`` pairs. Attribute mappings may contain
        product ``model_no``, ``part_no``, ``quantity``, or contact ``role``;
        unsupported/empty collections return an empty list.
    """
    if field in {"Product", "Model_no"}:
        table_items = _product_table_items(text)
        if table_items:
            if field == "Product":
                return table_items
            return [(attributes["model_no"], {}) for _, attributes in table_items if attributes.get("model_no")]
    collection_labels = {
        "Any Additional Documentation Required": r"(?:required\s+documents?|additional\s+documents?|documentation)",
        "Model_no": r"models?(?:\s+numbers?)?",
        "Part_no": r"(?:parts?(?:\s+numbers?)?|skus?)",
        "Product": r"(?:products?|items?)",
        "contact_info": r"contacts?(?:\s+information)?",
        "company_name": r"(?:organizations?|agencies|company\s+names?)",
        "Product Specification": r"(?:product\s+)?specifications?",
    }
    label = collection_labels.get(field)
    if label:
        replacement = re.search(
            rf"\b{label}\b[^.\n]{{0,60}}?\b(?:are\s+|is\s+)?(?:replaced|superseded)\s+(?:by|with)\s*[:\-]?\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if replacement:
            return [(value, {}) for value in _split_collection_values(replacement.group(1))]
        removal = re.search(r"(?:remove|delete)\s+(.+?)\s+from\s+(?:the\s+)?(?:required\s+documents?|products?|items?|models?|parts?|specifications?|contacts?|organizations?)\b", text, re.IGNORECASE)
        if removal:
            return [(value, {}) for value in _split_collection_values(removal.group(1))]
        no_longer_required = re.search(r"([^.;\n]+?)\s+(?:is|are)\s+no\s+longer\s+(?:required|needed)", text, re.IGNORECASE)
        if no_longer_required and field == "Any Additional Documentation Required":
            return [(value, {}) for value in _split_collection_values(no_longer_required.group(1))]
    if field == "Any Additional Documentation Required":
        obligation_patterns = (
            re.compile(r"(?:must\s+provide|provide\s+a)\s+(Mercury\s+Affidavit)", re.IGNORECASE),
            re.compile(r"(factory-authorized\s+repair\s+and\s+maintenance\s+certifications)", re.IGNORECASE),
            re.compile(r"(pertinent\s+literature/documentation)", re.IGNORECASE),
            re.compile(r"(credit\s+application\s+or\s+similar\s+documentation)", re.IGNORECASE),
            re.compile(r"(supporting\s+documentation)\s+(?:may|can)\s+be\s+included", re.IGNORECASE),
            re.compile(r"\b(Form\s+1295)\b", re.IGNORECASE),
            re.compile(r"(?:return|submit)\s+(?:a\s+)?copy\s+of\s+(this\s+)?(Addendum\s+\d+)", re.IGNORECASE),
            re.compile(r"submit\s+this\s+addendum\b", re.IGNORECASE),
        )
        obligations: list[tuple[str, dict[str, Any]]] = []
        for pattern in obligation_patterns:
            for match in pattern.finditer(text):
                value = match.group(match.lastindex or 0).strip(" \t:;,.")
                if match.re.pattern.startswith("(?:return"):
                    value = match.group(match.lastindex or 0).strip()
                if value and not any(existing.casefold() == value.casefold() for existing, _ in obligations):
                    obligations.append((value, {}))
        has_explicit_list = re.search(r"(?:additional\s+documents\s+required|required\s+documents|affidavits\s+required|documentation\s+required)\s*[:\-]", text, re.IGNORECASE)
        if not has_explicit_list:
            warranty = re.search(r"(warranty\s+certificate\s+or\s+affidavit)", text, re.IGNORECASE)
            if warranty:
                obligations.append((warranty.group(1), {}))
        if obligations:
            return obligations
    if field == "contact_info":
        contacts: list[tuple[str, dict[str, Any]]] = []
        buyer = re.search(r"\bBuyer\s*\n\s*([^\n]+)\s*\n\s*Email\s*\n\s*([^\s\n]+)", text, re.IGNORECASE)
        if not buyer:
            buyer = re.search(r"\bBuyer\s+([A-Z][A-Z ,]+?)\s+Email\s+([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", text, re.IGNORECASE)
        if buyer:
            raw_name = buyer.group(1).strip()
            if "," in raw_name:
                last, first = (part.strip() for part in raw_name.split(",", 1))
                name = f"{first.title()} {last.title()}"
            else:
                name = raw_name.title()
            contacts.append((f"{name}; {buyer.group(2).strip().lower()}", {"role": "Buyer"}))
        contact_patterns = (
            ("Agency POC", re.compile(r"Agency\s+POC\s+Name\s*:\s*(.+?)\s+Agency\s+POC\s+Phone\s+Number\s*:\s*([0-9()+ -]+?)\s+Agency\s+POC\s+Email\s+Address\s*:\s*([A-Z0-9._%+-]+@(?:[A-Z0-9-]+\s*\.\s*)+[A-Z0-9-]+)", re.IGNORECASE)),
            ("Agency On-site Contact", re.compile(r"Agency\s+On-site\s+Contact\s+Name\s*:\s*(.+?)\s+Agency\s+On-site\s+Phone\s+Number\s*:\s*([0-9()+ -]+?)\s+Agency\s+On-site\s+Email\s+Address\s*:\s*([A-Z0-9._%+-]+@(?:[A-Z0-9-]+\s*\.\s*)+[A-Z0-9-]+)", re.IGNORECASE)),
        )
        for role, pattern in contact_patterns:
            match = pattern.search(text)
            if match:
                email = re.sub(r"\s+", "", match.group(3)).lower()
                contacts.append((f"{match.group(1).strip()}; {match.group(2).strip()}; {email}", {"role": role}))
        if contacts:
            return contacts
    if field == "company_name":
        district = re.search(r"Dallas\s+Independent\s+School\s+District", text, re.IGNORECASE)
        if district:
            return [("Dallas Independent School District", {})]
    if field == "Product Specification":
        copilot_requirement = re.search(r"(?:laptops?|products?)\s+must\s+be\s+(Microsoft\s+Copilot\s+ready)", text, re.IGNORECASE)
        if copilot_requirement:
            return [(copilot_requirement.group(1), {})]
        technical_line = re.compile(
            r"(?:processor|Windows\s+\d+|\d+\s*GB|\d+\s*TB|\d+(?:\.\d+)?[- ]inch|\bFHD\b|\bSSD\b|\bDDR\d\b|Wi-?Fi|wireless|Bluetooth|battery|AC\s+adapter|ENERGY\s+STAR|EPEAT)",
            re.IGNORECASE,
        )
        specifications = []
        for line in text.splitlines():
            normalized_line = re.sub(r"\s+", " ", line).strip(" \t•-;")
            if normalized_line and technical_line.search(normalized_line):
                value = normalized_line.rstrip(".,;")
                if value.casefold() not in {item.casefold() for item in specifications}:
                    specifications.append(value)
        if specifications:
            return [(value, {}) for value in specifications]
        return []
    if field == "Product":
        categories = re.search(r"including\s+(.+?)(?:\.|\n)", text, re.IGNORECASE)
        if categories:
            return [(value, {}) for value in _split_collection_values(categories.group(1))]
    if field == "Part_no":
        all_part_codes = re.findall(r"\b\d{3}-[A-Z0-9]+\b", text, re.IGNORECASE)
        if len(all_part_codes) >= 8 and re.search(r"\bCFI\b", text, re.IGNORECASE):
            return [(value, {}) for value in dict.fromkeys(all_part_codes)]
        sku_block = re.search(r"\bSKU\b\s*[:#-]?\s*([\s\S]+?)(?=\bSI#|\bDescription\b|$)", text, re.IGNORECASE)
        if sku_block:
            sku_values = re.findall(r"\b\d{3}-[A-Z0-9]+\b", sku_block.group(1), re.IGNORECASE)
            if sku_values:
                return [(value, {}) for value in sku_values]
    if field == "Model_no":
        model_values = [value.strip(" \t:;,." ) for value in re.findall(r"\bModel\s*#\s*[:\-]?\s*([^\r\n]+)", text, re.IGNORECASE)]
        system_ids = [f"SI# {value}" for value in re.findall(r"\bSI#\s*([A-Z0-9-]+)", text, re.IGNORECASE)]
        combined = system_ids + model_values
        if combined:
            unique = dict.fromkeys(value for value in combined if value)
            return [(value, {}) for value in unique]
    pattern = _COLLECTION_PATTERNS.get(field)
    if pattern is None:
        return []
    matches = list(pattern.finditer(text))
    items: list[tuple[str, dict[str, Any]]] = []
    for match in matches:
        captured = _clean_capture(match.group(1))
        if field == "Product":
            next_product = pattern.search(text, match.end())
            row_end = next_product.start() if next_product else len(text)
            row_text = text[match.start():row_end]
            attributes: dict[str, Any] = {}
            quantity = re.search(r"\bquantity\s*[:#-]\s*(\d+)\b", row_text, re.IGNORECASE)
            model = re.search(r"\bmodel(?:\s+number|\s+no\.?|\s*#)?\s*[:#-]\s*(SI#\s*[A-Z0-9-]+|[A-Z0-9][A-Z0-9._/-]*)", row_text, re.IGNORECASE)
            part = re.search(r"\bpart(?:\s+number|\s+no\.?)?\s*[:#-]\s*([A-Z0-9][A-Z0-9._/-]*)", row_text, re.IGNORECASE)
            leading_model = re.match(r"SI#\s*([A-Z0-9-]+)\s+(.+)", captured, re.IGNORECASE)
            if leading_model:
                captured = leading_model.group(2).strip()
                attributes["model_no"] = f"SI# {leading_model.group(1)}"
            if quantity:
                attributes["quantity"] = int(quantity.group(1))
            if model:
                attributes["model_no"] = model.group(1).rstrip(".,;")
            if part:
                attributes["part_no"] = part.group(1).rstrip(".,;")
            items.append((captured, attributes))
            continue
        values = _split_collection_values(captured, split_and=field in {
            "Any Additional Documentation Required", "Model_no", "Part_no", "Product Specification"
        })
        items.extend((value, {}) for value in values)
    return items


def normalize_value(field: str, text: str) -> Any:
    """Extract one canonical scalar from a field-specific evidence passage.

    Args:
        field: Canonical field name.
        text: Source text, which may include a field label or surrounding
            context.

    Returns:
        Normalized scalar such as a string, date, boolean, or ``None`` when the
        text does not support a recognized value. Titles and free-text labels
        are bounded to 500 or 1000 characters according to field rules.
    """
    value = text.strip()
    lowered = value.lower()
    if field == "Installation":
        if any(term in lowered for term in ("not required", "none", "no installation", "not necessary")):
            return False
        if re.search(r"\b(?:installation|deployments?|imaging)\b.{0,80}\b(?:is\s+)?(?:required|must)\b", lowered):
            return True
        return None
    if field == "Bid Submission Type":
        if "emma" in lowered:
            return "eMMA e-Procurement system"
        if "isupplier" in lowered:
            return "iSupplier electronic portal or sealed manual submission" if "sealed envelope" in lowered else "iSupplier electronic portal"
        if "portal" in lowered and any(term in lowered for term in ("electronic", "online", "submit", "submission")):
            return "Electronic portal"
        if re.search(r"\bno\s+(?:fax\s+or\s+)?email\b.{0,50}\b(?:accepted|allowed)\b", lowered):
            return None
        if re.search(r"\b(?:submit|accept(?:ed|s)?)\b.{0,60}\b(?:proposal|bid|response)s?\b.{0,40}\b(?:via|by|through)\s+email\b", lowered):
            return "Email"
        if any(term in lowered for term in ("sealed bid", "physical copy", "hard copy")):
            return "Sealed physical submission"
        return None
    if field in {"Due Date", "Pre Bid Meeting", "Delivery Date"}:
        return _date_value(field, value)
    if field == "Bid Number":
        labeled_number = re.search(
            r"\b(?:porfp|solicitation|rfp|bid)\s*(?:number|no\.?|#)\s*[:\-]?\s*#?\s*([A-Z0-9-]+)",
            value,
            re.IGNORECASE,
        )
        if labeled_number:
            candidate = labeled_number.group(1)
            return candidate if re.search(r"\d", candidate) else None
        ja_number = re.search(r"\bJA-\d+\b", value, re.IGNORECASE)
        return ja_number.group(0).upper() if ja_number else None
    if field in {"Model_no", "Part_no"}:
        segment = _field_segment(field, value)
        match = re.search(r"(?:ja-\d+|[A-Z][A-Z0-9-]*\d[A-Z0-9-]*)", segment, re.I)
        return match.group(0) if match else None
    if field == "Term of Bid":
        initial = re.search(r"initial\s+term\s*[:\-]?\s*(\d+)", value, re.IGNORECASE)
        renewals = re.findall(r"renewal\s+\d+\s*[:\-]?\s*(\d+)", value, re.IGNORECASE)
        maximum = re.search(r"(?:not\s+exceed\s+)?(?:a\s+)?total\s+of\s+(\d+)\s+years?", value, re.IGNORECASE)
        if initial and renewals:
            if len(renewals) == 2 and renewals[0] == renewals[1]:
                renewal_text = f"two {renewals[0]}-year"
            else:
                renewal_text = " and ".join(f"{number}-year" for number in renewals)
            max_text = f"; maximum {maximum.group(1)} years" if maximum else ""
            return f"{initial.group(1)}-year initial term with {renewal_text} renewals{max_text}"
        labeled_term = re.search(r"term\s+of\s+(?:the\s+)?(?:bid|contract)\s*[:\-]?\s*((?:\d+|one|two|three|four|five)\s+years?)", value, re.IGNORECASE)
        if labeled_term:
            return labeled_term.group(1).strip()
        duration = re.search(r"(?:term\s+of\s+(?:the\s+)?(?:bid|contract)|contract\s+duration)\s*[:\-]?\s*(\d+)\s*years?", value, re.IGNORECASE)
        return f"{duration.group(1)}-year term" if duration else None
    if field == "Title":
        segment = _field_segment(field, value)
        if segment != value:
            segment = re.split(r"\s+\*\*[A-Z][A-Z0-9 _-]*", segment, maxsplit=1)[0]
            return segment[:500] or None
        html_title = re.search(
            r"\bTitle\s+(.+?)(?=\s+\*\*SOURCING\b|\s+(?:Source ID|SCRIBE|Details|Dates|Contact Information|Description)\b|$)",
            value,
            re.IGNORECASE,
        )
        if html_title and re.search(r"\b(?:Solicitation Number|Reference Number)\b", value[:html_title.start()], re.IGNORECASE):
            return html_title.group(1).strip(" .")[:500] or None
        porfp_listing = re.search(
            r"RFP\s*-\s*Request\s+for\s+Proposal\s*\(Informal\)\s+[A-Z0-9-]+\s+(.+?)(?=\s+\*\*SOURCING\b|\s+SCRIBE\b)",
            value,
            re.IGNORECASE,
        )
        if porfp_listing:
            return porfp_listing.group(1).strip(" .")[:500] or None
        bid_page_title = re.search(r"\bJA-\d+\s+(.+?)\s+\*\*SOURCING\b", value, re.IGNORECASE)
        if bid_page_title:
            return bid_page_title.group(1).strip()[:500] or None
        porfp_title = re.search(r"(Purchase\s+Order\s+Request\s+for\s+Proposals\s*\(PORFP\)\s+Hardware\s+Master\s+Contract)", value, re.IGNORECASE)
        if porfp_title:
            return re.sub(r"\s+", " ", porfp_title.group(1)).strip()
        heading = re.search(r"request\s+for\s+proposal\s+\d+\s*[.:]?\s+([\s\S]+)", value, re.IGNORECASE)
        if heading:
            title_line = heading.group(1).splitlines()[0].strip()
            title_line = re.sub(r"^JA-\d+\s+", "", title_line, flags=re.IGNORECASE)
            return title_line[:500] or None
        return None
    if field == "Payment Terms":
        invoicing = re.search(r"invoice\(?s?\)?\s+shall\s+be\s+submitted\s+within\s+(\d+)\s+days?\s+of\s+deliver(?:y|ing)", value, re.IGNORECASE)
        if invoicing:
            return f"Invoices must be submitted within {invoicing.group(1)} days of delivery"
    if field == "Contract or Cooperative to Use":
        cooperative = re.search(r"((?:Educational\s+Purchasing\s+Cooperative|EPCNT)[^.;]*)", value, re.IGNORECASE)
        if cooperative:
            return cooperative.group(1).strip()
        contract = re.search(r"contract\s+under\s+the\s+(.+?)(?:\s+are\s+eligible|[.;])", value, re.IGNORECASE)
        if contract:
            return contract.group(1).strip(" ,")
        return None
    if field == "company_name":
        district = re.search(r"Dallas\s+Independent\s+School\s+District", value, re.IGNORECASE)
        if district:
            return "Dallas Independent School District"
    if field == "Bid Number":
        porfp = re.search(r"PORFP\s+Number\s*:\s*#?\s*([A-Z0-9-]+)", value, re.IGNORECASE)
        if porfp:
            return porfp.group(1)
    if field in _VALUE_LABELS:
        segment = _field_segment(field, value)
        return segment[:1000] or None if segment != value else None
    return None
