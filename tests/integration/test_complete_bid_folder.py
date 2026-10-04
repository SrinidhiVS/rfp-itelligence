from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


ROOT = Path(__file__).resolve().parents[2]


def test_complete_bid_folders_and_unseen_shape() -> None:
    pipeline = IngestionPipeline()
    bid1 = pipeline.process(ROOT / "Initial_docs" / "Bid1")
    bid2 = pipeline.process(ROOT / "Initial_docs" / "Bid2")
    unseen = pipeline.process(ROOT / "tests" / "fixtures" / "acceptance", bid_id="unseen")
    assert len(bid1.files) == 4
    assert len(bid2.files) == 5
    assert unseen.files[0].file_name == "expected.json" or unseen.files[0].file_name == "retention.html"
    assert bid1.chunks and bid2.chunks and unseen.chunks
