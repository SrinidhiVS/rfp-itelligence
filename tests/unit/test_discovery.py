from pathlib import Path

from src.ingestion.classification import classify, detected_format
from src.ingestion.discovery import discover_files


def test_discovery_is_recursive_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "z.pdf").write_bytes(b"pdf")
    (tmp_path / "nested" / "a.html").write_text("<html></html>", encoding="utf-8")
    assert [path.name for path in discover_files(tmp_path)] == ["a.html", "z.pdf"]


def test_classification_uses_format_and_filename_evidence() -> None:
    assert detected_format(Path("Addendum 2.pdf")) == "pdf"
    assert classify(Path("Addendum 2.pdf")) == "addendum"
    assert classify(Path("Dell Laptop Specs.pdf")) == "specs"
    assert classify(Path("BidNet Direct.html")) == "bid_page"
