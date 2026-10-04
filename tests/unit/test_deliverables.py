import json
from types import SimpleNamespace

import pytest

from src.agents.state import AgentTrace
from src.deliverables import export_records, format_retrieval_report, refresh_cases, write_json


def test_case_mapping_preserves_labels_and_handles_whitespace():
    record = SimpleNamespace(record_id="current", bid_id="Bid1", source_file="bid.html", page_number=None,
                             text="Title:\nPortable Computers", source_locator={"element_index": 3})
    case = {"case_id": "C1", "query": "computer title", "bid_id": "Bid1", "category": "title", "expected_record_ids": ["old"],
            "expected_passages": [{"record_id": "old", "bid_id": "Bid1", "source_file": "bid.html", "page_number": None, "excerpt": "Title: Portable Computers"}]}
    mapped = refresh_cases([case], [record])[0]
    assert mapped["expected_record_ids"] == ["current"]
    assert mapped["expected_passages"][0]["excerpt"] == record.text
    assert case["expected_record_ids"] == ["old"]


def test_case_mapping_rejects_missing_source_evidence():
    case = {"case_id": "C1", "expected_passages": [{"bid_id": "Bid1", "source_file": "missing.pdf", "page_number": 1, "excerpt": "deadline"}]}
    with pytest.raises(ValueError, match="labeled source excerpt no longer exists"):
        refresh_cases([case], [])


def test_record_export_rejects_unindexed_bid_folder(tmp_path):
    (tmp_path / "documents" / "Bid1").mkdir(parents=True)
    with pytest.raises(ValueError, match="no indexed evidence"):
        export_records(tmp_path / "documents", tmp_path / "artifacts", [])


def test_trace_model_round_trips_as_json(tmp_path):
    write_json(tmp_path / "trace.json", AgentTrace(trace_id="example"))
    assert json.loads((tmp_path / "trace.json").read_text())["trace_id"] == "example"


def test_retrieval_report_is_plain_text():
    report = {
        "run_context": {"evaluated_at": "2026-10-04T12:00:00+00:00"},
        "configurations": [{
            "configuration": "hybrid",
            "recall_at_k": 0.75,
            "mrr": 0.5,
            "actual_mode": "indexed-hybrid",
            "reranker_status": "heuristic",
        }],
    }
    cases = [{"case_id": "C1", "bid_id": "Bid1", "query": "What is the deadline?"}]

    text = format_retrieval_report(report, cases, 42, 5, 1)

    assert "Retrieval Evaluation\n" in text
    assert "Recall at 5: 0.7500" in text
    assert "MRR: 0.5000" in text
    assert "C1 (Bid1): What is the deadline?" in text
    assert text.endswith("\n")
    assert "#" not in text
    assert "|" not in text
    assert "\n- " not in text