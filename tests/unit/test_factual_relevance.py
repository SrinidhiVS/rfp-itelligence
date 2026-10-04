from src.search.models import IndexRecord, RankedEvidence
from src.search.ranking import rerank


def evidence(record_id: str, text: str, score: float) -> RankedEvidence:
    record = IndexRecord(record_id, record_id, f"Bid1:{record_id}", "fp", text, "Bid1", "file.pdf", 1, None, "rfp", None, None, {}, [])
    return RankedEvidence(record_id, 1, score, record, ["hybrid"], "complete")


def test_concrete_requirement_values_beat_reference_text() -> None:
    reference = evidence("reference", "All minimum specifications detailed in this RFP must be met.", 0.4)
    facts = evidence("facts", "Processor must be 2.4 GHz, memory minimum 16 GB, storage up to 512 GB.", 0.4)
    results = rerank([reference, facts], "device specifications")
    assert results[0].record.record_id == "facts"
