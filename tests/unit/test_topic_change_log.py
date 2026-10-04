from src.search.models import IndexRecord, RankedEvidence, SearchQuery
from src.search.qa import QAService


class AddendaSearch:
    def search(self, query):
        deadline = IndexRecord("deadline", "deadline", "scope1", "fp", "new due date July 9", "Bid1", "Addendum 2.pdf", 1, None, "addendum", 2, None, {}, [])
        warranty = IndexRecord("warranty", "warranty", "scope2", "fp", "warranty coverage updated", "Bid1", "Addendum 3.pdf", 2, None, "addendum", 3, None, {}, [])
        return {"results": [RankedEvidence("deadline", 1, 1.0, deadline, ["hybrid"], "complete"), RankedEvidence("warranty", 2, 0.5, warranty, ["hybrid"], "complete")], "diagnostics": []}


def test_change_log_uses_query_relevant_addenda() -> None:
    answer = QAService(AddendaSearch()).answer(SearchQuery("final deadline"))
    assert all("warranty" not in citation["file"].lower() for citation in answer.citations if citation["file"])
