from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_processing_is_deterministic() -> None:
    root = Path(__file__).resolve().parents[2] / "Initial_docs" / "Bid1"
    first = IngestionPipeline().process(root)
    second = IngestionPipeline().process(root)
    assert [item.document_id for item in first.files] == [item.document_id for item in second.files]
    assert [item.chunk_id for item in first.chunks] == [item.chunk_id for item in second.chunks]
    assert [item.normalized_text for item in first.pages] == [item.normalized_text for item in second.pages]
