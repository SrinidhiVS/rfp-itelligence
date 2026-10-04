from src.search.models import IndexRecord, SearchQuery
from src.search.query import filter_records


def test_bid_filter_accepts_multiple_bid_ids():
    records = [
        IndexRecord("r1", "c1", "s1", "f1", "deadline Bid1", "Bid1", "bid1.pdf", 1, None, "rfp", None, None, {}),
        IndexRecord("r2", "c2", "s2", "f2", "deadline Bid2", "Bid2", "bid2.pdf", 1, None, "rfp", None, None, {}),
    ]
    result = filter_records(records, SearchQuery(text="deadline", filters={"bid_id": ["Bid2"]}))
    assert [record.bid_id for record in result] == ["Bid2"]