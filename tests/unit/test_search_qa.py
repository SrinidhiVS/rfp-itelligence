from src.search.models import SearchQuery
from src.search.qa import QAService


class EmptySearch:
    def search(self, query):
        return {"results": [], "diagnostics": ["no_supporting_evidence"]}


def test_qa_returns_explicit_not_found() -> None:
    answer = QAService(EmptySearch()).answer(SearchQuery("unknown"))
    assert answer.found is False
    assert answer.answer == "Not found in documents"
