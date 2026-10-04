from src.search.evaluation import evaluate
from src.search.models import IndexRecord
from src.search.search import SearchService


def test_evaluation_reports_each_configuration() -> None:
    record = IndexRecord("r", "c", "Bid1:file", "fp", "deadline", "Bid1", "file.pdf", 1, None, "rfp", None, None, {}, [])
    report = evaluate(SearchService([record]), [{"case_id": "c", "query": "deadline", "expected_record_ids": ["r"]}], ["semantic-only", "hybrid"], 5)
    assert [item["configuration"] for item in report["configurations"]] == ["semantic-only", "hybrid"]
    assert all(item["cases"][0]["returned_record_ids"] for item in report["configurations"])
