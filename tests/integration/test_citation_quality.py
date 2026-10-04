import json
import re
from pathlib import Path

from src.extraction.extractor import StructuredExtractor
from src.search.config import index_path
from src.search.storage import CorpusStore


def test_non_null_values_have_reviewer_locatable_citations():
    record = StructuredExtractor().extract("Bid1", [{"record": {"source_file": "bid.html", "page_number": None, "source_locator": "deadline", "bid_id": "Bid1", "text": "submission deadline October 20"}}])
    field = record.fields["Due Date"]
    assert field.value is not None
    assert field.citations[0].file and field.citations[0].location


def test_delivery_deadline_does_not_support_bid_due_date():
    evidence = [{"record": {"source_file": "delivery.pdf", "page_number": 2, "source_locator": "delivery schedule", "bid_id": "Bid1", "doc_type": "rfp", "text": "Delivery deadline: August 9, 2026."}}]

    record = StructuredExtractor().extract("Bid1", evidence)

    assert record.fields["Delivery Date"].value == "2026-08-09"
    assert record.fields["Due Date"].value is None
    assert record.fields["Due Date"].citations == []


def test_indexed_bid_summaries_have_source_backed_cited_claims():
    fixture = json.loads(Path("tests/fixtures/structured_extraction/value-level-acceptance.json").read_text(encoding="utf-8"))
    indexed_records = CorpusStore(index_path()).load().records
    sentence_prefixes = {
        "Title": "The solicitation is titled ",
        "Due Date": "The submission deadline is ",
        "Bid Submission Type": "The submission method is ",
        "Term of Bid": "The contract term is ",
        "Pre Bid Meeting": "The pre-bid meeting information is ",
        "Delivery Date": "The delivery requirement is ",
        "Payment Terms": "Payment terms are ",
        "Bid Bond Requirement": "The bid bond requirement is ",
        "Product": "Requested products include ",
        "Any Additional Documentation Required": "Required documents include ",
        "Contract or Cooperative to Use": "The contract vehicle is ",
        "Product Specification": "Product specifications include ",
    }

    for bid_id in ("Bid1", "Bid2"):
        evidence = [
            {"record": record.__dict__, "authority_status": record.status}
            for record in indexed_records
            if record.bid_id == bid_id
        ]
        record = StructuredExtractor().extract(bid_id, evidence)
        summary = record.fields["Bid Summary"]
        assert summary.status == "supported" and summary.value
        sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+", summary.value.strip()) if sentence]
        assert 3 <= len(sentences) <= 6, (bid_id, sentences)
        summary_sources = {(citation.file, citation.page) for citation in summary.citations}
        assert summary.citations

        for sentence in sentences:
            matching_fields = [
                name for name, prefix in sentence_prefixes.items()
                if sentence.startswith(prefix)
            ]
            assert len(matching_fields) == 1, (bid_id, sentence)
            name = matching_fields[0]
            field = record.fields[name]
            value = field.value
            if isinstance(value, list):
                value_text = ", ".join(
                    str(item.value if hasattr(item, "value") else item.get("value", ""))
                    for item in value
                )
            else:
                value_text = str(value).strip()
            assert sentence == f"{sentence_prefixes[name]}{value_text}.", (bid_id, sentence)
            assert field.status == "supported" and field.citations, (bid_id, name)
            field_sources = {(citation.file, citation.page) for citation in field.citations}
            assert field_sources <= summary_sources, (bid_id, name)
            assert all(
                citation.file and (citation.page is not None or citation.location) and citation.excerpt
                for citation in field.citations
            ), (bid_id, name)

            expected = fixture["bids"][bid_id]["supported"][name]
            expected_citations = expected.get("citations", [])
            if "items" in expected:
                expected_citations = expected_citations or [
                    citation
                    for item in expected["items"] if isinstance(item, dict)
                    for citation in item.get("citations", [])
                ]
            expected_sources = {(citation["file"], citation.get("page")) for citation in expected_citations}
            assert expected_sources <= field_sources, (bid_id, name)
