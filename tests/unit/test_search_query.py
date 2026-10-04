from src.search.models import IndexRecord, SearchQuery
from src.search.query import expand, filter_records, make_query
from src.search.search import SearchService


def record(bid: str, doc_type: str, addendum: int | None, record_id: str | None = None) -> IndexRecord:
    return IndexRecord(record_id or bid, "chunk", f"{bid}:file", "fp", "deadline due date", bid, "file.pdf", 1, None, doc_type, addendum, None, {}, [])


def test_query_expansion_and_filters() -> None:
    query = make_query({"text": "deadline", "filters": {"bid_id": "Bid1", "addendum_number": 2}})
    assert "due date" in expand(query).variants
    assert all("Bid1" not in variant for variant in expand(query).variants)
    assert len(filter_records([record("Bid1", "addendum", 2), record("Bid2", "rfp", None)], query)) == 1


def test_deadline_expansion_preserves_identifier_and_intent() -> None:
    variants = expand(make_query({"text": "What is the final submission deadline for JA-207652?"})).variants
    assert any("JA-207652" in variant and "final" in variant.lower() for variant in variants)
    assert any("JA-207652" in variant and "revised due date" in variant.lower() for variant in variants)
    assert all("JA-207652" in variant for variant in variants[1:])


def test_procurement_expansion_keeps_full_context_and_original_filters() -> None:
    query = make_query({"text": "What is the latest delivery deadline for JA-207652?", "filters": {"bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 2}})
    result = expand(query)
    assert result.original == query.text == result.variants[0]
    assert len({variant.lower() for variant in result.variants}) == len(result.variants)
    assert result.expansion_terms and result.diagnostics == []
    assert all("JA-207652" in variant and "latest" in variant.lower() for variant in result.variants)
    assert any("shipping deadline" in variant.lower() for variant in result.variants)
    assert any("delivery due date" in variant.lower() for variant in result.variants)
    assert query.filters == {"bid_id": "Bid1", "doc_type": "addendum", "addendum_number": 2}
    records = [record("Bid1", "addendum", 2), record("Bid1", "rfp", None), record("Bid2", "addendum", 2)]
    assert filter_records(records, query) == records[:1]


def test_keyword_search_composes_bid_document_and_addendum_filters() -> None:
    records = [
        record("Bid1", "addendum", 2, "eligible"),
        record("Bid1", "addendum", 1, "wrong-addendum"),
        record("Bid1", "rfp", None, "wrong-document"),
        record("Bid2", "addendum", 2, "wrong-bid"),
    ]
    query = SearchQuery(
        "deadline due date",
        filters={"bid_id": ["Bid1"], "doc_type": "addendum", "addendum_number": 2},
    )

    response = SearchService(records).search(query, configuration="keyword-only")

    assert [item.record_id for item in response["results"]] == ["eligible"]
