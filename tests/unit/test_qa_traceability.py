from src.search.models import IndexRecord, RankedEvidence, SearchQuery
from src.search.qa import QAService


class OneSearch:
    def search(self, query):
        record = IndexRecord("r", "c", "Bid1:addendum.pdf", "fp", "The new due date is July 9.", "Bid1", "addendum.pdf", 1, "Deadline", "addendum", 2, None, {"relative_path": "addendum.pdf"}, [])
        return {"results": [RankedEvidence("r", 1, 0.9, record, ["keyword"], "complete")], "diagnostics": []}


def test_citations_preserve_source_metadata_and_answer_is_focused() -> None:
    answer = QAService(OneSearch()).answer(SearchQuery("final deadline"))
    assert answer.answer == "The new due date is July 9."
    assert answer.citations[0]["doc_type"] == "addendum"
    assert answer.citations[0]["addendum_number"] == 2
    assert answer.citations[0]["page"] == 1
