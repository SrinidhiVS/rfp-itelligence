from pathlib import Path

from src.ingestion.pipeline import IngestionPipeline


def test_extension_mismatch_is_failed_and_diagnosed(tmp_path: Path) -> None:
    source = tmp_path / "not-really.pdf"
    source.write_text("<html><body>wrong extension</body></html>", encoding="utf-8")
    report = IngestionPipeline().process(tmp_path)
    assert report.files[0].status == "failed"
    assert report.diagnostics[0].code == "format_mismatch"
