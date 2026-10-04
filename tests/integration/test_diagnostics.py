from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_folder_status_rolls_up_file_diagnostics() -> None:
    root = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "partial-bid"
    report = IngestionPipeline().process(root)
    assert report.status == "incomplete"
    assert report.diagnostic_count >= 2
    assert {item.status for item in report.files} >= {"parsed", "failed", "unsupported"}
