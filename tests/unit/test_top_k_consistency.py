from src.search.models import IndexRecord
from src.search.search import SearchService
from src.search.query import make_query


def test_top_k_results_are_prefixes() -> None:
    records = [
        IndexRecord(str(index), str(index), f"Bid1:file{index}", "fp", f"deadline requirement {index}", "Bid1", f"file{index}.pdf", index, None, "rfp", None, None, {}, [])
        for index in range(1, 8)
    ]
    service = SearchService(records)
    results = {}
    for top_k in (1, 3, 5, 10):
        response = service.search(make_query({"text": "deadline", "filters": {"bid_id": "Bid1"}, "top_k": top_k}))
        results[top_k] = [item.record_id for item in response["results"]]
    assert results[1] == results[10][:1]
    assert results[3] == results[10][:3]
    assert results[5] == results[10][:5]
