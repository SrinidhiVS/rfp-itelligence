"""Central registry for canonical fields, aliases, strategies, and validation rules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldDefinition:
    """Describe one canonical or agent field and its extraction contract.

    ``field_id`` is the stable internal key; ``name`` and ``aliases`` identify
    user/source terminology; ``value_type`` and ``extraction_strategy`` guide
    normalization; ``validation_rules`` name required evidence checks;
    ``canonical_name`` links structured extraction; agent/planner aliases
    support workflow planning; validation/label aliases guide support checks;
    and ``is_collection`` distinguishes item-level values from scalars.
    """

    field_id: str
    name: str
    aliases: tuple[str, ...]
    value_type: str
    extraction_strategy: str
    validation_rules: tuple[str, ...]
    canonical_name: str | None = None
    agent_keys: tuple[str, ...] = ()
    agent_aliases: tuple[str, ...] = ()
    planner_aliases: tuple[str, ...] = ()
    validation_labels: tuple[str, ...] = ()
    label_aliases: tuple[str, ...] = ()
    is_collection: bool = False


FIELD_DEFINITIONS = (
    FieldDefinition(
        "bid_number", "Bid Number",
        ("solicitation", "bid number", "rfp number", "solicitation number", "porfp number"),
        "string", "labeled_identifier", ("source_evidence", "citation_required", "conflict_review"),
        canonical_name="Bid Number", agent_keys=("solicitation_number",),
        agent_aliases=("solicitation number", "bid number", "rfp number", "solicitation", "rfp"),
        planner_aliases=("solicitation number", "bid number", "rfp number"),
        validation_labels=("bid number", "rfp number", "solicitation number", "porfp number"),
    ),
    FieldDefinition(
        "title", "Title",
        ("title", "solicitation title", "bid title"),
        "string", "labeled_text", ("source_evidence", "citation_required"),
        canonical_name="Title",
        validation_labels=("title:", "request for proposal"),
    ),
    FieldDefinition(
        "due_date", "Due Date",
        ("submission deadline", "bid deadline", "bid due", "due date", "closing date", "responses due", "solicitation due", "deadline", "proposal due date and time", "solicitation due date"),
        "string", "date_time", ("source_evidence", "citation_required", "addendum_precedence", "conflict_review"),
        canonical_name="Due Date", agent_keys=("submission_deadline",),
        agent_aliases=("submission deadline", "deadline", "due date", "submit by", "closing date"),
        planner_aliases=("submission deadline", "deadline", "due date", "closing date", "submit by"),
        validation_labels=("submission deadline", "due date", "proposal due date", "solicitation due", "bid deadline"),
    ),
    FieldDefinition(
        "bid_submission_type", "Bid Submission Type",
        ("submission method", "submit proposals", "submit bids", "procurement portal", "isupplier portal", "electronic system", "emma", "e-procurement", "sealed bid", "sealed envelope", "submit by email"),
        "string", "submission_method", ("source_evidence", "citation_required"),
        canonical_name="Bid Submission Type", agent_keys=("submission_method",),
        agent_aliases=("submission method", "how to submit", "submission portal", "submit", "submission", "sealed", "electronic", "portal"),
        planner_aliases=("submission method", "how to submit", "submission portal"),
        validation_labels=("submission method", "bid submission instructions", "e-procurement", "isupplier"),
    ),
    FieldDefinition(
        "term_of_bid", "Term of Bid",
        ("term of bid", "contract term", "initial term", "contract duration", "renewal", "option year", "length of contract"),
        "string", "contract_term", ("source_evidence", "citation_required"),
        canonical_name="Term of Bid",
        validation_labels=("initial term", "term of bid", "length of contract"),
    ),
    FieldDefinition(
        "pre_bid_meeting", "Pre Bid Meeting",
        ("pre-bid", "pre bid", "prebid meeting", "conference", "pre-proposal meeting", "pre-bid meeting", "pre-bid conference"),
        "string", "event_date_time", ("source_evidence", "citation_required"),
        canonical_name="Pre Bid Meeting",
        validation_labels=("pre-proposal meeting", "pre-bid meeting", "pre-bid conference"),
    ),
    FieldDefinition(
        "installation", "Installation",
        ("installation", "deployment", "deployments", "imaging"),
        "boolean", "boolean_requirement", ("source_evidence", "citation_required", "explicit_polarity"),
        canonical_name="Installation",
        validation_labels=("installation:", "installation is"),
    ),
    FieldDefinition(
        "bid_bond_requirement", "Bid Bond Requirement",
        ("bid bond", "bid security", "bond required"),
        "string", "bond_requirement", ("source_evidence", "citation_required"),
        canonical_name="Bid Bond Requirement", agent_keys=("bid_bond",),
        agent_aliases=("bid bond", "bid security", "bond required"),
        planner_aliases=("bid bond", "bid security"),
        validation_labels=("bid bond", "bid security"),
    ),
    FieldDefinition(
        "delivery_date", "Delivery Date",
        ("delivery", "deliver by", "delivery window", "delivery date", "delivery within"),
        "string", "delivery_timing", ("source_evidence", "citation_required"),
        canonical_name="Delivery Date",
        validation_labels=("delivery date", "delivery window", "delivery within", "deliver by"),
    ),
    FieldDefinition(
        "payment_terms", "Payment Terms",
        ("payment", "invoice", "invoices", "invoice terms", "net 30", "invoicing", "payment terms", "invoicing terms", "terms of payment"),
        "string", "payment_terms", ("source_evidence", "citation_required"),
        canonical_name="Payment Terms",
        validation_labels=("payment terms", "invoicing terms", "invoice(s)"),
    ),
    FieldDefinition(
        "additional_documentation", "Any Additional Documentation Required",
        ("affidavit", "form", "certificate", "certifications", "insurance", "w-9", "documentation", "literature", "credit application", "addendum", "required documents", "additional documents", "additional documents required", "affidavits required", "documentation required", "must include", "must provide"),
        "collection", "required_documents", ("source_evidence", "item_citation_required", "collection_completeness"),
        canonical_name="Any Additional Documentation Required", agent_keys=("affidavits",),
        agent_aliases=("affidavit", "affidavits"), is_collection=True,
        planner_aliases=("affidavit", "affidavits"),
        validation_labels=("required documents", "additional documents", "must include", "must provide"),
        label_aliases=("required documents", "additional documents", "additional documents required", "affidavits required", "documentation required"),
    ),
    FieldDefinition(
        "manufacturer_registration", "MFG for Registration",
        ("manufacturer", "mfg", "authorized", "registered", "manufacturer name", "manufacturer registration", "mfg for registration"),
        "string", "manufacturer_registration", ("source_evidence", "citation_required"),
        canonical_name="MFG for Registration",
        label_aliases=("manufacturer name", "manufacturer registration", "manufacturer for registration", "mfg for registration"),
        validation_labels=("manufacturer name", "manufacturer registration", "mfg for registration"),
    ),
    FieldDefinition(
        "contract_or_cooperative", "Contract or Cooperative to Use",
        ("cooperative", "contract vehicle", "master contract", "cooperative contract", "state contract"),
        "string", "contract_vehicle", ("source_evidence", "citation_required"),
        canonical_name="Contract or Cooperative to Use",
        validation_labels=("cooperative", "master contract", "contract vehicle"),
    ),
    FieldDefinition(
        "model_number", "Model_no",
        ("model", "model number", "model #", "model no.", "si#"),
        "collection", "model_identifier", ("source_evidence", "item_citation_required", "value_format"),
        canonical_name="Model_no", agent_keys=("model_number",),
        agent_aliases=("model number", "model #", "model no.", "si#"), is_collection=True,
        planner_aliases=("model number", "model #", "model no."),
        validation_labels=("model number", "model #", "si#"),
    ),
    FieldDefinition(
        "part_number", "Part_no",
        ("part", "part number", "sku"),
        "collection", "part_identifier", ("source_evidence", "item_citation_required", "value_format"),
        canonical_name="Part_no", validation_labels=("part number", "sku"), is_collection=True,
        label_aliases=("part number", "part numbers", "part no", "part no.", "part #", "sku", "sku number"),
    ),
    FieldDefinition(
        "product", "Product",
        ("product name", "product description", "item description", "product", "item"),
        "collection", "product_table_or_labeled_text", ("source_evidence", "item_citation_required", "preserve_item_attributes"),
        canonical_name="Product", validation_labels=("product:", "product name:", "including laptops"), is_collection=True,
    ),
    FieldDefinition(
        "contact_info", "contact_info",
        ("contact", "contact information", "contact person", "contact name", "email", "email address", "phone", "phone number", "procurement contact", "buyer", "agency poc name", "agency poc phone number", "agency poc email address", "agency poc fax", "agency poc mailing address", "agency on-site contact name", "agency on-site phone number", "agency on-site email address", "agency on-site fax", "agency on-site address"),
        "collection", "labeled_contact", ("source_evidence", "item_citation_required", "preserve_contact_role"),
        canonical_name="contact_info", is_collection=True,
        validation_labels=("buyer", "agency poc name", "contact:"),
        label_aliases=("buyer", "contact person", "contact name", "agency poc name", "agency poc phone number", "agency poc email address", "agency on-site contact name", "agency on-site phone number", "agency on-site email address", "email address", "phone number", "phone", "email"),
    ),
    FieldDefinition(
        "company_name", "company_name",
        ("issuing organization", "issuing agency", "agency / division name", "agency name", "company name", "organization name", "purchasing entity", "issued by"),
        "collection", "labeled_organization", ("source_evidence", "item_citation_required"),
        canonical_name="company_name", is_collection=True,
        validation_labels=("organization", "agency / division name", "company name"),
    ),
    FieldDefinition(
        "bid_summary", "Bid Summary",
        ("summary", "overview", "scope"),
        "string", "evidence_summary", ("source_evidence", "citation_required", "three_to_six_sentences"),
        canonical_name="Bid Summary",
    ),
    FieldDefinition(
        "product_specification", "Product Specification",
        ("specification", "cpu", "ram", "storage", "display", "processor", "windows", "ddr", "ssd", "wi-fi", "wireless", "battery", "adapter", "energy star"),
        "collection", "technical_specification", ("source_evidence", "item_citation_required", "preserve_item_attributes"),
        canonical_name="Product Specification", is_collection=True,
        validation_labels=("specification", "processor", "memory", "display"),
        label_aliases=("specification", "processor", "memory", "display", "storage", "windows", "ddr", "ssd", "nvme", "emmc", "fhd", "wi-fi", "wireless", "802.11", "bluetooth", "battery", "ac adapter", "energy star", "epeat", "copilot ready"),
    ),
    FieldDefinition(
        "warranty", "warranty", ("warranty", "warranties", "extended warranty"),
        "string", "agent_term_line", ("source_evidence", "citation_required"), agent_keys=("warranty",),
        agent_aliases=("warranty", "warranties", "extended warranty"),
    ),
    FieldDefinition(
        "insurance", "insurance", ("insurance", "certificate of insurance"),
        "string", "agent_term_line", ("source_evidence", "citation_required"), agent_keys=("insurance",),
        agent_aliases=("insurance", "certificate of insurance"),
    ),
    FieldDefinition(
        "mandatory_requirements", "mandatory_requirements", ("must", "mandatory", "required"),
        "string", "agent_requirement_clause", ("source_evidence", "citation_required", "context_required"),
        agent_keys=("mandatory_requirements",), agent_aliases=("must", "mandatory", "required"),
        planner_aliases=("mandatory requirements", "mandatory requirement"),
    ),
    FieldDefinition(
        "evaluation_criteria", "evaluation_criteria", ("evaluation", "scoring", "criteria"),
        "string", "agent_term_line", ("source_evidence", "citation_required"),
        agent_keys=("evaluation_criteria",), agent_aliases=("evaluation", "scoring", "criteria"),
        planner_aliases=("evaluation criteria", "evaluation criterion", "scoring criteria"),
    ),
)

CANONICAL_FIELD_DEFINITIONS = tuple(
    definition for definition in FIELD_DEFINITIONS if definition.canonical_name is not None
)
AGENT_FIELD_DEFINITIONS = tuple(
    definition for definition in FIELD_DEFINITIONS if definition.agent_keys
)
FIELD_DEFINITIONS_BY_CANONICAL_NAME = {
    definition.canonical_name: definition for definition in CANONICAL_FIELD_DEFINITIONS
}
FIELD_DEFINITIONS_BY_AGENT_KEY = {
    agent_key: definition
    for definition in AGENT_FIELD_DEFINITIONS
    for agent_key in definition.agent_keys
}
AGENT_FIELD_ALIASES = {
    agent_key: definition.agent_aliases or definition.aliases
    for agent_key, definition in FIELD_DEFINITIONS_BY_AGENT_KEY.items()
}
AGENT_PLANNER_ALIASES = {
    agent_key: definition.planner_aliases or definition.agent_aliases or definition.aliases
    for agent_key, definition in FIELD_DEFINITIONS_BY_AGENT_KEY.items()
}
FIELD_VALIDATION_LABELS = {
    definition.canonical_name: definition.validation_labels
    for definition in CANONICAL_FIELD_DEFINITIONS
    if definition.canonical_name is not None and definition.validation_labels
}
