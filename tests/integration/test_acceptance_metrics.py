from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_supplied_bids_have_inventory_and_traceable_chunks() -> None:
    root = Path(__file__).resolve().parents[2] / "Initial_docs"
    for name in ("Bid1", "Bid2"):
        report = IngestionPipeline().process(root / name)
        assert report.discovered_file_count == len(report.files)
        assert report.chunks
        assert all(chunk.source_file for chunk in report.chunks)
