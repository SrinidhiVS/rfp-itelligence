from pathlib import Path

from src.agents.report_agent import synthesize_answer
from src.search.authority import apply_requirement_authority
from src.search.models import IndexRecord, RankedEvidence
from tests.fixtures.supp_tasks_corpus import build_supp_tasks_corpus


def _fixture_records(corpus_path: Path, *evidence_keys):
    evidence_by_key, _ = build_supp_tasks_corpus(corpus_path)
    return [evidence_by_key[key] for key in evidence_keys]


def _ranked(record_id, text, addendum_number, *, page=1, status="current", score=0.5):
    record = IndexRecord(
        record_id,
        record_id,
        f"Bid1:{record_id}",
        "fingerprint",
        text,
        "Bid1",
        f"Addendum {addendum_number or 'unknown'}.pdf",
        page,
        None,
        "addendum",
        addendum_number,
        None,
        {"relative_path": f"Addendum {addendum_number or 'unknown'}.pdf"},
        [],
        status,
    )
    return RankedEvidence(record_id, 1, score, record, ["keyword"], "complete")


def test_addendum_two_answer_compares_base_and_change_with_both_citations(tmp_path):
    records = _fixture_records(tmp_path / "corpus.json", "bid1_rfp_schedule", "bid1_addendum2_deadline")

    output = synthesize_answer("What changed in Addendum 2?", records)

    assert output["found"] is True
    assert "27-JUN-2024" in output["answer"]
    assert "July 9, 2024" in output["answer"]
    assert output["claims"]
    citations = output["claims"][0]["citations"]
    assert {citation["file"] for citation in citations} == {
        "JA-207652 Student and Staff Computing Devices FINAL.pdf",
        "Addendum 2 RFP JA-207652 Student and Staff Computing Devices.pdf",
    }
    assert all(citation["bid_id"] == "Bid1" for citation in citations)


def test_addendum_answer_reports_supported_non_deadline_field_changes():
    evidence = [
        {
            "authority_status": "supporting",
            "record": {
                "record_id": "base-warranty",
                "bid_id": "Bid1",
                "source_file": "base-rfp.pdf",
                "page_number": 4,
                "section_title": "Warranty",
                "doc_type": "rfp",
                "addendum_number": None,
                "source_locator": {"section": "Warranty"},
                "text": "Warranty period: 1 year.",
            },
        },
        {
            "authority_status": "current",
            "record": {
                "record_id": "addendum-warranty",
                "bid_id": "Bid1",
                "source_file": "addendum-2.pdf",
                "page_number": 1,
                "section_title": "Warranty change",
                "doc_type": "addendum",
                "addendum_number": 2,
                "source_locator": {"section": "Warranty change"},
                "text": "The warranty period is revised from 1 year to 3 years.",
            },
        },
    ]

    output = synthesize_answer("What changed in Addendum 2?", evidence)

    assert output["found"] is True
    assert "warranty" in output["answer"].casefold()
    assert "1 year" in output["answer"] and "3 years" in output["answer"]
    assert output["change_log"][0]["field"].casefold() == "warranty period"
    assert {citation["file"] for citation in output["claims"][0]["citations"]} == {
        "base-rfp.pdf",
        "addendum-2.pdf",
    }


def test_latest_valid_deadline_ignores_higher_numbered_superseded_addendum():
    addendum_two = _ranked("addendum-2", "The new due date is July 9, 2024.", 2)
    superseded_addendum_three = _ranked(
        "addendum-3-old",
        "The revised submission deadline is August 1, 2024.",
        3,
        status="superseded",
        score=0.99,
    )

    results = apply_requirement_authority(
        [superseded_addendum_three, addendum_two],
        "What is the latest submission deadline?",
    )

    by_id = {item.record_id: item for item in results}
    assert by_id["addendum-2"].authority_status == "current"
    assert by_id["addendum-3-old"].authority_status == "superseded"
    assert by_id["addendum-3-old"].superseded_by == "addendum-2"


def test_equal_order_conflicting_deadlines_require_review_not_rank_selection():
    first = _ranked("addendum-2-a", "The revised submission deadline is July 9, 2024.", 2, score=0.4)
    second = _ranked("addendum-2-b", "The revised submission deadline is July 12, 2024.", 2, score=0.99)

    results = apply_requirement_authority([first, second], "What is the latest submission deadline?")

    assert all(item.authority_status == "review_required" for item in results)
    assert all(item.superseded_by is None for item in results)