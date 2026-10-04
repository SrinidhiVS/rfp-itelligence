from src.search.models import IndexRecord, RankedEvidence
from src.search.ranking import deduplicate, rerank


def evidence(record_id: str, text: str, page: int, doc_type: str = "rfp", addendum: int | None = None, score: float = 0.1) -> RankedEvidence:
    record = IndexRecord(record_id, record_id, f"Bid1:file-{page}.pdf", "fp", text, "Bid1", "file.pdf", page, None, doc_type, addendum, None, {}, [])
    return RankedEvidence(record_id, 1, score, record, ["keyword"], "complete")


def test_direct_deadline_evidence_outranks_incidental_match() -> None:
    incidental = evidence("incidental", "References will be contacted within the week following the solicitation due date.", 10)
    direct = evidence("direct", "The new due date for this RFP will be July 9, 2024 at 2:00 PM CST.", 1, "addendum", 2)
    results = rerank([incidental, direct], "What is the final submission deadline for JA-207652?")
    assert results[0].record.record_id == "direct"
    assert results[0].score >= results[1].score
    assert [item.rank for item in results] == [1, 2]


def test_near_duplicate_same_page_is_removed() -> None:
    first = evidence("a", "Solicitation Due June 27, 2024", 32, score=0.5)
    duplicate = evidence("b", "Solicitation Due June 27, 2024", 32, score=0.4)
    assert [item.record.record_id for item in deduplicate([first, duplicate])] == ["a"]
