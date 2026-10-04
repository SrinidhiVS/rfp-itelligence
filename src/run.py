"""Prepare bid indexes and launch the local API and Streamlit UI together."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def preloaded_bid_ids(documents: Path) -> list[str]:
    """Return bid IDs defined by immediate folders in the configured source root.

    Args:
        documents: Directory containing preloaded bid folders.

    Returns:
        Sorted folder names used as the launch-time bid selector options.

    Raises:
        ValueError: If the source root does not exist or contains no bid folders.
    """
    if not documents.is_dir():
        raise ValueError(f"Bid document root does not exist: {documents}")
    bid_ids = sorted(folder.name for folder in documents.iterdir() if folder.is_dir())
    if not bid_ids:
        raise ValueError(f"No bid folders found in {documents}")
    return bid_ids


def available_port(preferred: int) -> int:
    """Return the preferred loopback port or an available ephemeral port.

    Args:
        preferred: Preferred TCP port to bind on ``127.0.0.1``.

    Returns:
        Preferred port when bindable, otherwise a free OS-assigned port.
    """
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", preferred))
        except OSError:
            listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def prepare(documents: Path, env: dict[str, str]) -> list[str]:
    """Ingest each immediate bid subfolder and return its folder-name IDs.

    Args:
        documents: Directory containing one folder per bid.
        env: Environment mapping passed to child ingestion processes.

    Returns:
        Sorted bid folder names after successful ingestion.

    Raises:
        ValueError: If the document root is missing or contains no bid folders.
        subprocess.CalledProcessError: If any child ingestion command fails.
    """
    bid_ids = preloaded_bid_ids(documents)
    for bid_id in bid_ids:
        folder = documents / bid_id
        subprocess.run(
            [sys.executable, "-m", "src.cli", "ingest", str(folder), "--output", str(ROOT / "output" / folder.name)],
            cwd=ROOT, env=env, check=True,
        )
    return bid_ids


def wait_for_api(process: subprocess.Popen, url: str, timeout: float = 120) -> None:
    """Poll the API health endpoint until ready, process exit, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("API exited before it became ready")
        try:
            with urlopen(f"{url}/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    return
        except (URLError, TimeoutError, OSError, ValueError):
            pass
        threading.Event().wait(0.2)
    raise RuntimeError("API readiness timed out; check the server output")


def stop(process: subprocess.Popen) -> None:
    """Terminate a running child process, escalating to kill after 10 seconds."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _handle_sigterm(_signum, _frame) -> None:
    raise KeyboardInterrupt


def _wait_for_children(api: subprocess.Popen, ui: subprocess.Popen) -> None:
    while api.poll() is None and ui.poll() is None:
        threading.Event().wait(0.5)


def serve(env: dict[str, str], api_port: int, ui_port: int, *, container_mode: bool = False) -> int:
    """Launch API and UI child processes and stop both when either exits.

    Args:
        env: Environment passed to API/UI processes, updated with API URL.
        api_port: API port, fixed in container mode or preferred locally.
        ui_port: UI port, fixed in container mode or preferred locally.
        container_mode: Bind services to all container interfaces and handle
            Docker's SIGTERM using the normal child-process cleanup path.

    Returns:
        Child process exit code, or 0 after Ctrl+C. Both children are stopped
        during cleanup.
    """
    bind_host = "0.0.0.0" if container_mode else "127.0.0.1"
    if container_mode:
        if api_port == ui_port:
            raise ValueError("API and UI ports must be different")
    else:
        api_port = available_port(api_port)
        ui_port = available_port(ui_port)
        while ui_port == api_port:
            ui_port = available_port(0)
    env = {**env, "RFP_API_URL": f"http://127.0.0.1:{api_port}"}
    processes = []
    previous_sigterm_handler = None
    try:
        if container_mode and threading.current_thread() is threading.main_thread():
            previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _handle_sigterm)
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.api.app:app", "--host", bind_host, "--port", str(api_port)],
            cwd=ROOT, env=env,
        )
        processes.append(api)
        wait_for_api(api, env["RFP_API_URL"])
        ui = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "src/frontend/app.py", "--server.address", bind_host,
             "--server.port", str(ui_port), "--server.headless", "true"],
            cwd=ROOT, env=env,
        )
        processes.append(ui)
        print(f"UI: http://127.0.0.1:{ui_port}  API: {env['RFP_API_URL']}  (Ctrl+C to stop)", flush=True)
        _wait_for_children(api, ui)
        return api.returncode or ui.returncode or 0
    except KeyboardInterrupt:
        return 0
    finally:
        if previous_sigterm_handler is not None:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
        for process in reversed(processes):
            stop(process)


def main(argv: list[str] | None = None) -> int:
    """Parse startup options, optionally ingest bids, and launch local services.

    Args:
        argv: Optional CLI argument sequence; ``None`` uses process arguments.
            Options control input documents, ingest skipping, and API/UI ports.

    Returns:
        0 on normal shutdown; 1 for startup, input, or child-process errors.
    """
    load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="Prepare bid indexes and launch the API and UI together")
    parser.add_argument("--documents", type=Path, default=ROOT / "Initial_docs")
    parser.add_argument("--skip-ingest", action="store_true", help="reuse the existing corpus and vectors")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=8501)
    parser.add_argument("--container", action="store_true", help="bind fixed ports on all interfaces for container use")
    args = parser.parse_args(argv)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        documents = args.documents.resolve()
        bids = preloaded_bid_ids(documents) if args.skip_ingest else prepare(documents, env)
        env["RFP_BID_IDS"] = ",".join(bids)
        return serve(env, args.api_port, args.ui_port, container_mode=args.container)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())