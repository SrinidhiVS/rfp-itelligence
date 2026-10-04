import json
import sys
from pathlib import Path
from types import SimpleNamespace

import src.cli as ingestion_cli
from src.cli import main


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "acceptance"
MANIFEST = ROOT / "tests" / "fixtures" / "retention" / "procurement-corpus.json"


def test_cli_adds_retention_report_when_manifest_is_supplied(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "with-retention"
    monkeypatch.setenv("RFP_INDEX_PATH", str(output / "search-index.json"))
    monkeypatch.setattr(ingestion_cli, "sync_chroma_index", lambda store: {"failed": 0}, raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["rfp-ingest", "ingest", str(FIXTURE_ROOT), "--output", str(output), "--bid-id", "acceptance", "--retention-manifest", str(MANIFEST)],
    )

    assert main() == 0
    payload = json.loads((output / "processing-report.json").read_text(encoding="utf-8"))

    assert payload["retention_report"]["corpus_name"] == "acceptance-retention-html"
    assert payload["retention_report"]["text"]["expected"] == 20
    assert payload["retention_report"]["text"]["retained"] == 20
    assert payload["retention_report"]["tables"]["expected"] == 10
    assert payload["retention_report"]["tables"]["retained"] == 10


def test_cli_does_not_claim_retention_without_manifest(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "without-retention"
    monkeypatch.setenv("RFP_INDEX_PATH", str(output / "search-index.json"))
    monkeypatch.setattr(ingestion_cli, "sync_chroma_index", lambda store: {"failed": 0}, raising=False)
    monkeypatch.setattr(sys, "argv", ["rfp-ingest", "ingest", str(FIXTURE_ROOT), "--output", str(output)])

    assert main() == 0
    payload = json.loads((output / "processing-report.json").read_text(encoding="utf-8"))

    assert payload["retention_report"] is None


def test_cli_ingest_updates_search_and_chroma_indexes(tmp_path: Path, monkeypatch, capsys) -> None:
    calls = {}
    report = SimpleNamespace(bid_id="new-bid", status="complete", discovered_file_count=1)
    payload = {
        "status": "complete",
        "chunks": [{"chunk_id": "chunk-1", "text": "submission deadline", "source_file": "rfp.html", "source_locator": {"relative_path": "rfp.html"}}],
        "documents": [{"relative_path": "rfp.html", "status": "parsed"}],
    }

    class FakeIngestionPipeline:
        def process(self, folder, bid_id=None):
            calls["folder"] = folder
            return report

    class FakeCorpusStore:
        def __init__(self, path):
            calls["store_path"] = path

    class FakeIndexService:
        def __init__(self, store):
            calls["store"] = store

        def update(self, request):
            calls["index_request"] = request
            return {"indexed": 1, "failed": 0}

    monkeypatch.setattr(sys, "argv", ["rfp-ingest", "ingest", str(FIXTURE_ROOT), "--output", str(tmp_path), "--bid-id", "new-bid"])
    monkeypatch.setattr(ingestion_cli, "IngestionPipeline", FakeIngestionPipeline)
    monkeypatch.setattr(ingestion_cli, "report_dict", lambda value: payload)
    monkeypatch.setattr(ingestion_cli, "CorpusStore", FakeCorpusStore, raising=False)
    monkeypatch.setattr(ingestion_cli, "IndexService", FakeIndexService, raising=False)
    monkeypatch.setattr(ingestion_cli, "index_path", lambda: tmp_path / "search-index.json", raising=False)

    def fake_sync(store):
        calls["synced_store"] = store
        return {"embedded": 1, "failed": 0}

    monkeypatch.setattr(ingestion_cli, "sync_chroma_index", fake_sync, raising=False)

    assert main() == 0

    assert calls["index_request"]["bid_id"] == "new-bid"
    assert calls["index_request"]["chunks"] == payload["chunks"]
    assert calls["synced_store"] is calls["store"]
    output = json.loads(capsys.readouterr().out)
    assert output["vector_index"]["embedded"] == 1
