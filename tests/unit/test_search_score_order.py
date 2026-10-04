from src.search.models import IndexRecord, RankedEvidence
from src.search.ranking import rerank


def test_final_scores_descend_with_rank() -> None:
    records = [
        RankedEvidence("a", 1, 0.2, IndexRecord("a", "a", "s1", "f", "deadline", "Bid1", "a.pdf", 1, None, "rfp", None, None, {}, []), ["keyword"], "complete"),
        RankedEvidence("b", 2, 0.1, IndexRecord("b", "b", "s2", "f", "deadline", "Bid1", "b.pdf", 2, None, "rfp", None, None, {}, []), ["keyword"], "complete"),
    ]
    result = rerank(records, "deadline")
    assert all(result[index].score >= result[index + 1].score for index in range(len(result) - 1))
    assert [item.rank for item in result] == [1, 2]


def test_identifier_prefix_does_not_gain_exact_match_bonus() -> None:
    records = [
        RankedEvidence("partial", 1, 0.1, IndexRecord("partial", "a", "scope", "fp", "ZX-2100", "Bid1", "a.pdf", 1, None, "rfp", None, None, {}), ["keyword"], "complete"),
        RankedEvidence("unrelated", 2, 0.1, IndexRecord("unrelated", "b", "scope", "fp", "ZX-9999", "Bid1", "b.pdf", 1, None, "rfp", None, None, {}), ["keyword"], "complete"),
    ]
    results = rerank(records, "ZX-210")
    assert results[0].score == results[1].score
    assert [item.rank for item in results] == [1, 2]
