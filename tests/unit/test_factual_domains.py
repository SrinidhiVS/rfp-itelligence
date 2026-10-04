from src.search.models import IndexRecord, RankedEvidence
from src.search.ranking import rerank


def evidence(identifier: str, text: str) -> RankedEvidence:
    record = IndexRecord(identifier, identifier, identifier, "fp", text, "Bid1", "file.pdf", 1, None, "rfp", None, None, {}, [])
    return RankedEvidence(identifier, 1, 0.4, record, ["hybrid"], "complete")


def test_factual_domains_beat_reference_sentences() -> None:
    reference = evidence("reference", "Specifications are detailed elsewhere in this RFP.")
    concrete = evidence("concrete", "Warranty must be three years, quantity is 25 units, and delivery is required within 30 days.")
    results = rerank([reference, concrete], "warranty quantity delivery")
    assert results[0].record.record_id == "concrete"
