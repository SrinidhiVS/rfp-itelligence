import sys
from types import SimpleNamespace

from src.search import cli
from src.search import embeddings, vector_store


def _invoke_vector_index(monkeypatch, arguments):
    calls = {}
    corpus = SimpleNamespace(records=["record"], source_manifest=["scope"])

    class FakeCorpusStore:
        def __init__(self, path):
            calls["corpus_path"] = path

        def load(self):
            return corpus

    class FakeVectorStore:
        def __init__(self, path):
            calls["vector_path"] = path

        def update_from_records(self, records, provider, full_rebuild=False, source_manifest=None):
            calls["records"] = records
            calls["provider"] = provider
            calls["full_rebuild"] = full_rebuild
            calls["source_manifest"] = source_manifest
            return {"embedded": 1, "skipped_empty": 0, "unchanged": 0, "replaced": 0, "removed": 0, "failed": 0, "diagnostics": []}

    monkeypatch.setattr(sys, "argv", ["src.cli", "vector-index", *arguments])
    monkeypatch.setattr(cli, "CorpusStore", FakeCorpusStore)
    monkeypatch.setattr(cli, "index_path", lambda: "corpus.json")
    monkeypatch.setattr(cli, "chroma_index_path", lambda: "chroma-db")
    monkeypatch.setattr(embeddings, "SentenceTransformerProvider", lambda config: "provider")
    monkeypatch.setattr(vector_store, "VectorStore", FakeVectorStore)

    return cli.main(), calls, corpus


def test_vector_index_cli_updates_incrementally_by_default(monkeypatch, capsys):
    exit_code, calls, corpus = _invoke_vector_index(monkeypatch, [])

    assert exit_code == 0
    assert calls["full_rebuild"] is False
    assert calls["records"] is corpus.records
    assert calls["source_manifest"] is corpus.source_manifest
    assert '"unchanged": 0' in capsys.readouterr().out


def test_vector_index_cli_requires_explicit_rebuild_flag(monkeypatch):
    exit_code, calls, _ = _invoke_vector_index(monkeypatch, ["--rebuild"])

    assert exit_code == 0
    assert calls["full_rebuild"] is True


def test_vector_index_cli_uses_chroma_path(monkeypatch):
    _, calls, _ = _invoke_vector_index(monkeypatch, [])

    assert str(calls["vector_path"]) == "chroma-db"