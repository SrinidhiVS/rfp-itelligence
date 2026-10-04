import json
import subprocess
from unittest.mock import Mock

import pytest

from src import run


def test_prepare_propagates_ingestion_failure(tmp_path, monkeypatch):
    (tmp_path / "Bid1").mkdir()
    execute = Mock(side_effect=subprocess.CalledProcessError(1, "ingest"))
    monkeypatch.setattr(run.subprocess, "run", execute)
    with pytest.raises(subprocess.CalledProcessError):
        run.prepare(tmp_path, {})
    assert execute.call_args.args[0][1:4] == ["-m", "src.cli", "ingest"]
    assert execute.call_args.kwargs["check"] is True


def test_prepare_rejects_empty_or_missing_document_root(tmp_path):
    with pytest.raises(ValueError, match="No bid folders"):
        run.prepare(tmp_path, {})
    with pytest.raises(ValueError, match="does not exist"):
        run.prepare(tmp_path / "missing", {})


@pytest.mark.parametrize("skip_ingest", [False, True])
def test_main_only_exposes_preloaded_folders_not_stale_index_ids(tmp_path, monkeypatch, skip_ingest):
    documents = tmp_path / "documents"
    (documents / "Bid1").mkdir(parents=True)
    (documents / "Bid2").mkdir()
    index_path = tmp_path / "search-index.json"
    index_path.write_text(json.dumps({"records": [
        {"bid_id": "409736090529"},
        {"bid_id": "690720783822"},
        {"bid_id": "Bid3"},
    ]}), encoding="utf-8")
    monkeypatch.setenv("RFP_INDEX_PATH", str(index_path))
    monkeypatch.setenv("RFP_BID_IDS", "stale-environment-id")
    monkeypatch.setattr(run, "load_dotenv", Mock())
    if not skip_ingest:
        monkeypatch.setattr(run, "prepare", Mock(return_value=["Bid1", "Bid2"]))
    serve = Mock(return_value=0)
    monkeypatch.setattr(run, "serve", serve)
    args = ["--documents", str(documents)]
    if skip_ingest:
        args.append("--skip-ingest")

    assert run.main(args) == 0

    assert serve.call_args.args[0]["RFP_BID_IDS"] == "Bid1,Bid2"


def test_serve_cleans_up_api_when_readiness_fails(monkeypatch):
    api = Mock()
    api.poll.return_value = None
    monkeypatch.setattr(run.subprocess, "Popen", Mock(return_value=api))
    monkeypatch.setattr(run, "available_port", lambda port: port)
    monkeypatch.setattr(run, "wait_for_api", Mock(side_effect=RuntimeError("not ready")))
    with pytest.raises(RuntimeError, match="not ready"):
        run.serve({}, 8000, 8501)
    api.terminate.assert_called_once()


def test_serve_shares_api_url_and_stops_owned_children(monkeypatch):
    api, ui = Mock(), Mock()
    api.poll.side_effect = [None, None, None]
    ui.poll.side_effect = [0, 0]
    api.returncode = None
    ui.returncode = 0
    spawn = Mock(side_effect=[api, ui])
    monkeypatch.setattr(run.subprocess, "Popen", spawn)
    monkeypatch.setattr(run, "available_port", lambda port: port + 1)
    monkeypatch.setattr(run, "wait_for_api", Mock())
    assert run.serve({"RFP_BID_IDS": "Bid1,Bid2"}, 8000, 8501) == 0
    assert spawn.call_args_list[1].kwargs["env"]["RFP_API_URL"] == "http://127.0.0.1:8001"
    api.terminate.assert_called_once()


def test_serve_container_mode_uses_fixed_ports_and_all_interfaces(monkeypatch):
    api, ui = Mock(), Mock()
    api.poll.return_value = None
    api.returncode = None
    ui.poll.return_value = 0
    ui.returncode = 0
    spawn = Mock(side_effect=[api, ui])
    monkeypatch.setattr(run.subprocess, "Popen", spawn)
    monkeypatch.setattr(run, "available_port", Mock(side_effect=AssertionError("port should remain fixed")))
    monkeypatch.setattr(run, "wait_for_api", Mock())

    assert run.serve({}, 8000, 8501, container_mode=True) == 0

    api_command = spawn.call_args_list[0].args[0]
    ui_command = spawn.call_args_list[1].args[0]
    assert api_command[api_command.index("--host") + 1] == "0.0.0.0"
    assert api_command[api_command.index("--port") + 1] == "8000"
    assert ui_command[ui_command.index("--server.address") + 1] == "0.0.0.0"
    assert ui_command[ui_command.index("--server.port") + 1] == "8501"
    assert spawn.call_args_list[1].kwargs["env"]["RFP_API_URL"] == "http://127.0.0.1:8000"
    api.terminate.assert_called_once()


def test_serve_container_mode_sigterm_stops_both_children(monkeypatch):
    api, ui = Mock(), Mock()
    api.poll.return_value = None
    ui.poll.return_value = None
    spawn = Mock(side_effect=[api, ui])
    monkeypatch.setattr(run.subprocess, "Popen", spawn)
    monkeypatch.setattr(run, "available_port", Mock(side_effect=AssertionError("port should remain fixed")))
    monkeypatch.setattr(run, "wait_for_api", Mock())
    monkeypatch.setattr(run, "_wait_for_children", Mock(side_effect=KeyboardInterrupt))

    assert run.serve({}, 8000, 8501, container_mode=True) == 0

    api.terminate.assert_called_once()
    ui.terminate.assert_called_once()


def test_available_port_avoids_occupied_listener():
    with run.socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        assert run.available_port(listener.getsockname()[1]) != listener.getsockname()[1]


def test_wait_for_api_detects_early_exit():
    process = Mock()
    process.poll.return_value = 1
    with pytest.raises(RuntimeError, match="exited"):
        run.wait_for_api(process, "http://127.0.0.1:1")