from src.search.models import IndexRecord, RankedEvidence, SearchQuery
from src.search.qa import QAService


class ComparisonSearch:
    def search(self, query):
        records = []
        for bid in ("Bid1", "Bid2"):
            record = IndexRecord(bid, bid, f"{bid}:file", "fp", f"{bid} warranty requirement", bid, f"{bid}.pdf", 1, None, "rfp", None, None, {}, [])
            records.append(RankedEvidence(bid, len(records) + 1, 0.5, record, ["hybrid"], "complete"))
        return {"results": records, "diagnostics": []}


def test_comparison_evidence_is_grouped_by_bid() -> None:
    answer = QAService(ComparisonSearch()).answer(SearchQuery("compare warranty requirements"))
    assert set(answer.evidence_by_bid) == {"Bid1", "Bid2"}
    assert all(len(items) == 1 for items in answer.evidence_by_bid.values())
