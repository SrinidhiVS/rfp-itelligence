import json
from pathlib import Path
import re

from src.agents.report_agent import synthesize_answer
from tests.fixtures.supp_tasks_corpus import build_supp_tasks_corpus


def _records(corpus_path: Path, *evidence_keys):
    evidence_by_key, _ = build_supp_tasks_corpus(corpus_path)
    return [evidence_by_key[key] for key in evidence_keys]


def test_fixture_evidence_is_verbatim_and_locatable_in_indexed_source_records(tmp_path):
    fixture = json.loads(Path("tests/fixtures/supp_tasks_coverage.json").read_text(encoding="utf-8"))
    evidence_by_key, _ = build_supp_tasks_corpus(tmp_path / "corpus.json")

    for fixture_item in fixture["records"]:
        source = fixture_item["source"]
        record = evidence_by_key[fixture_item["evidence_key"]]["record"]
        assert source["bid_id"] == record["bid_id"]
        assert source["relative_path"] == record["source_locator"]["relative_path"]
        assert source["expected_excerpt"] in re.sub(r"\s+", " ", record["text"])
        assert source["page_number"] in record["source_locator"].get("page_numbers", [record["page_number"]])
        assert record["record_id"]


def test_affidavit_answer_aggregates_distinct_sources_and_citations(tmp_path):
    evidence = _records(
        tmp_path / "corpus.json",
        "bid2_mercury_affidavit",
        "bid2_contract_authority",
        "bid2_contract_workplace",
        "bid2_contract_contributions",
        "bid2_porfp_warranty",
    )

    output = synthesize_answer("What affidavit requirements apply to Bid2?", evidence)

    assert output["found"] is True
    assert len(output["claims"]) == 5
    assert "$200,000" in output["answer"] and "$500 or more" in output["answer"]
    assert "Warranty certificate or Affidavit to be presented upon award" in output["answer"]
    assert all(claim["bid_id"] == "Bid2" and claim["citations"] for claim in output["claims"])
    assert {citation["file"] for citation in output["citations"]} == {
        "PORFP_-_Dell_Laptop_Final.pdf",
        "Mercury_Affidavit.pdf",
        "Contract_Affidavit.pdf",
    }
    assert {citation["page"] for citation in output["citations"] if citation["file"] == "Contract_Affidavit.pdf"} == {1, 3}


def test_warranty_answer_separates_bids_and_cites_the_difference(tmp_path):
    evidence = _records(
        tmp_path / "corpus.json",
        "bid1_rfp_warranty",
        "bid1_rfp_tier1_requirements",
        "bid2_porfp_warranty",
    )

    output = synthesize_answer("Compare the warranty requirements for Bid1 and Bid2.", evidence)

    assert output["found"] is True
    assert {claim["bid_id"] for claim in output["claims"]} == {"Bid1", "Bid2"}
    assert all(claim["citations"] for claim in output["claims"])
    assert "Bid1" in output["answer"] and "Bid2" in output["answer"]
    assert "Difference" in output["answer"] or "differ" in output["answer"].lower()
    assert "material differences:" in output["answer"].casefold()
    assert "five (5) business days" in output["answer"]
    assert "Warranty certificate or Affidavit to be presented upon award" in output["answer"]
    assert {citation["bid_id"] for citation in output["citations"]} == {"Bid1", "Bid2"}


def test_bond_silence_or_indirect_reference_is_not_established(tmp_path):
    evidence = _records(tmp_path / "corpus.json", "bid1_rfp_offeror_requirements")

    output = synthesize_answer("Is a bond required, and what is the amount?", evidence)

    assert output["found"] is False
    assert "not establish" in output["answer"].lower()
    assert output["citations"] == []


def test_bond_explicit_requirement_reports_stated_amount_and_source():
    evidence = [{
        "authority_status": "supporting",
        "record": {
            "record_id": "bond-explicit",
            "bid_id": "Bid1",
            "source_file": "bond-requirement.pdf",
            "page_number": 12,
            "source_locator": {"section": "Bid Security"},
            "doc_type": "rfp",
            "text": "A bid bond of 5% of the total bid price is required with each proposal.",
        },
    }]

    output = synthesize_answer("Is a bond required, and what is the amount?", evidence)

    assert output["found"] is True
    assert "5%" in output["answer"]
    assert output["claims"][0]["citations"][0]["file"] == "bond-requirement.pdf"


def test_bond_explicit_nonrequirement_is_distinct_from_missing_evidence():
    evidence = [{
        "authority_status": "supporting",
        "record": {
            "record_id": "bond-not-required",
            "bid_id": "Bid1",
            "source_file": "no-bond.pdf",
            "page_number": 2,
            "source_locator": {"section": "Bid Security"},
            "doc_type": "rfp",
            "text": "No bid bond is required for this solicitation.",
        },
    }]

    output = synthesize_answer("Is a bond required?", evidence)

    assert output["found"] is True
    assert "not required" in output["answer"].lower()
    assert output["claims"][0]["citations"][0]["file"] == "no-bond.pdf"