from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
from playwright.sync_api import sync_playwright

from src.extraction.fields import CANONICAL_FIELDS


class AnalysisStubHandler(BaseHTTPRequestHandler):
    last_qa_bid_ids: list[str] = []
    last_qa_question = ""
    extraction_job_polls = 0

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"semantic_search": {"semantic_enabled": True}})
            return
        if self.path == "/v1/analysis/extraction-jobs/browser-extraction-job":
            self.__class__.extraction_job_polls += 1
            if self.extraction_job_polls < 3:
                self._send_json(200, {"job_id": "browser-extraction-job", "status": "running"})
                return
            self._send_json(200, {
                "job_id": "browser-extraction-job",
                "status": "partial",
                "result": {
                    "run_id": "browser-extraction",
                    "status": "partial",
                    "output": {
                        "fields": {
                            name: {
                                "value": None,
                                "confidence": 0.0,
                                "status": "not_found",
                                "notes": "Not found in documents",
                                "citations": [],
                            }
                            for name in CANONICAL_FIELDS
                        },
                        "addendum_changes": [],
                        "validation": [],
                        "summary": "Review missing fields.",
                    },
                    "diagnostics": [{"message": "Fixture extraction diagnostic", "severity": "warning"}],
                    "trace_reference": None,
                    "evaluation": {},
                },
            })
            return
        self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/v1/analysis/qa":
            self.__class__.last_qa_bid_ids = request.get("bid_ids", [])
            self.__class__.last_qa_question = request.get("question", "")
            if "force-error" in request.get("question", ""):
                self._send_json(503, {"detail": "fixture backend failure"})
                return
            if "affidavit" in request.get("question", "").casefold():
                long_claim = "Bid2 affidavit requirement: " + "ordinary source detail " * 30 + "LONG-AFFIDAVIT-SOURCE-DETAIL"
                self._send_json(200, {
                    "run_id": "browser-affidavit",
                    "status": "completed",
                    "output": {
                        "answer": long_claim * 6,
                        "found": True,
                        "citations": [],
                        "claims": [{
                            "text": long_claim,
                            "bid_id": "Bid2",
                            "citations": [{"file": "affidavit.pdf", "page": 1, "bid_id": "Bid2"}],
                        }],
                        "evidence_by_bid": {"Bid2": [{"record": {"text": long_claim}}]},
                    },
                    "diagnostics": [],
                    "trace_reference": None,
                    "evaluation": {},
                })
                return
            self._send_json(
                200,
                {
                    "run_id": "browser-qa",
                    "status": "completed",
                    "output": {
                        "answer": "The deadline is October 30.",
                        "found": True,
                        "citations": [
                            {
                                "file": "bid.html",
                                "page": None,
                                "locator": {"heading_path": ["Submission", "Deadline"]},
                                "bid_id": "Bid1",
                            }
                        ],
                        "evidence_by_bid": {
                            "Bid1": [{"record": {"text": "Deadline is October 30."}}]
                        },
                    },
                    "diagnostics": [],
                    "trace_reference": None,
                    "evaluation": {},
                },
            )
            return
        if self.path == "/v1/analysis/extraction-jobs":
            self.__class__.extraction_job_polls = 0
            self._send_json(202, {"job_id": "browser-extraction-job", "status": "queued"})
            return
        if self.path == "/v1/analysis/extract":
            self._send_json(
                200,
                {
                    "run_id": "browser-extraction",
                    "status": "partial",
                    "output": {
                        "fields": {
                            name: {
                                "value": None,
                                "confidence": 0.0,
                                "status": "not_found",
                                "notes": "Not found in documents",
                                "citations": [],
                            }
                            for name in CANONICAL_FIELDS
                        },
                        "addendum_changes": [],
                        "validation": [],
                        "summary": "Review missing fields.",
                    },
                    "diagnostics": [{"message": "Fixture extraction diagnostic", "severity": "warning"}],
                    "trace_reference": None,
                    "evaluation": {},
                },
            )
            return
        self._send_json(404, {"detail": "not found"})


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_streamlit(process: subprocess.Popen, base_url: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Streamlit exited early with status {process.returncode}.")
        try:
            response = httpx.get(f"{base_url}/_stcore/health", timeout=1)
            if response.is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError("Streamlit did not become healthy within 45 seconds.")


def _select_bids(page, bid_ids: list[str]) -> None:
    selector = page.get_by_role("combobox", name="Bids")
    selected_tags = page.locator('[data-testid="stMultiSelect"] [data-baseweb="tag"]')
    for bid_id in bid_ids:
        if any(bid_id in tag for tag in selected_tags.all_text_contents()):
            continue
        selector.fill(bid_id)
        page.get_by_role("option", name=bid_id, exact=True).click()
        selected_tags.filter(has_text=bid_id).wait_for()
    page.keyboard.press("Escape")


def _assert_no_blocking_horizontal_overflow(page) -> None:
    page.wait_for_timeout(150)
    overflow = page.evaluate(
        "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth"
    )
    assert overflow <= 4, f"Page overflows viewport by {overflow}px."


@pytest.mark.parametrize("viewport_width", [1280, 480])
def test_frontend_workflows_remain_readable_at_desktop_and_narrow_widths(
    tmp_path: Path, viewport_width: int
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    api_server = ThreadingHTTPServer(("127.0.0.1", 0), AnalysisStubHandler)
    api_thread = threading.Thread(target=api_server.serve_forever, daemon=True)
    api_thread.start()

    frontend_port = _unused_port()
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    environment = os.environ.copy()
    environment["RFP_API_URL"] = f"http://127.0.0.1:{api_server.server_port}"
    environment["RFP_BID_IDS"] = "Bid1,Bid2"
    environment["RFP_INDEX_PATH"] = str(tmp_path / "output" / "search-index.json")
    environment["RFP_CHROMA_PATH"] = str(tmp_path / "output" / "chroma")
    environment["RFP_JOB_POLL_INTERVAL"] = "0.02"
    environment["RFP_JOB_MAX_WAIT"] = "10"
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(repository_root), environment.get("PYTHONPATH", "")])
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(repository_root / "src/frontend/app.py"),
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(frontend_port),
            "--server.headless",
            "true",
            "--server.fileWatcherType",
            "none",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_for_streamlit(process, frontend_url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": viewport_width, "height": 900})
            page.set_default_timeout(5000)
            page.goto(frontend_url, wait_until="domcontentloaded")
            page.get_by_text("RFP Intelligence", exact=True).wait_for()
            assert "<style>" not in page.locator("body").inner_text()

            _select_bids(page, ["Bid1", "Bid2"])
            page.get_by_role("textbox", name="Question").fill("What is the submission deadline?")
            page.get_by_role("button", name="Ask").click()
            page.get_by_text("The deadline is October 30.", exact=True).wait_for()
            page.get_by_text("Run status: Complete", exact=True).wait_for()
            assert set(AnalysisStubHandler.last_qa_bid_ids) == {"Bid1", "Bid2"}
            page.get_by_text("No evidence returned for Bid2.", exact=True).wait_for()
            page.get_by_text("Submission > Deadline", exact=False).wait_for()
            _assert_no_blocking_horizontal_overflow(page)

            question_box = page.get_by_role("textbox", name="Question")
            question_box.fill("Which affidavits are required for Bid2?")
            assert question_box.input_value() == "Which affidavits are required for Bid2?"
            page.get_by_role("button", name="Ask").click()
            page.wait_for_timeout(250)
            assert "affidavit" in AnalysisStubHandler.last_qa_question.casefold(), page.locator("body").inner_text()
            page.get_by_text("Evidence-backed answer", exact=True).wait_for()
            long_detail = page.get_by_text("LONG-AFFIDAVIT-SOURCE-DETAIL", exact=False)
            assert long_detail.count() >= 1
            assert all(not long_detail.nth(index).is_visible() for index in range(long_detail.count()))
            page.locator('[data-testid="stExpander"] summary').filter(has_text="Supporting evidence").click()
            claim_summary = page.locator('[data-testid="stExpander"] summary').filter(has_text="Bid2 affidavit requirement").first
            claim_summary.click()
            assert any(long_detail.nth(index).is_visible() for index in range(long_detail.count()))
            _assert_no_blocking_horizontal_overflow(page)

            page.locator("label").filter(has_text="Review extraction").click()
            page.get_by_role("button", name="Extract bid").click()
            page.get_by_text("Run status: Partial", exact=True).wait_for()
            page.get_by_text("Not found: 20", exact=True).wait_for()
            page.get_by_text("Fixture extraction diagnostic", exact=True).wait_for()
            body_text = page.locator("body").inner_text()
            field_positions = [body_text.find(name) for name in CANONICAL_FIELDS]
            assert all(position >= 0 for position in field_positions)
            assert field_positions == sorted(field_positions)
            _assert_no_blocking_horizontal_overflow(page)

            sidebar = page.get_by_test_id("stSidebar")
            if not sidebar.is_visible():
                    page.get_by_test_id("stExpandSidebarButton").click()
            page.get_by_text("Import new bid folder", exact=True).click()
            page.locator('[data-testid="stFileUploader"] input[type="file"]').set_input_files(
                {
                    "name": "notice.html",
                    "mimeType": "text/html",
                    "buffer": b"<html><body><h1>Notice</h1><p>Submission deadline October 30.</p></body></html>",
                }
            )
            page.get_by_text("notice.html", exact=True).wait_for()
            folder_name = page.get_by_label("Bid folder name")
            folder_name.fill("Browser Import")
            folder_name.press("Enter")
            import_button = page.get_by_role("button", name="Import and index")
            import_button.wait_for(state="visible")
            page.wait_for_function(
                "[...document.querySelectorAll('button')].some(button => button.textContent.trim() === 'Import and index' && !button.disabled)"
            )
            import_button.click()
            page.wait_for_function(
                "document.body.innerText.includes('Import status:') || document.body.innerText.includes('Import failed:')",
                timeout=60000,
            )
            import_output = page.locator("body").inner_text()
            assert "Import status:" in import_output, import_output
            _assert_no_blocking_horizontal_overflow(page)

            if sidebar.is_visible():
                sidebar.locator('[data-testid="stBaseButton-headerNoPadding"]').first.click()
            page.locator("label").filter(has_text="Ask questions").click()
            page.get_by_role("textbox", name="Question").fill("force-error")
            page.get_by_role("button", name="Ask").click()
            page.get_by_text("The backend returned HTTP 503.", exact=True).wait_for()
            assert page.get_by_role("textbox", name="Question").input_value() == "force-error"
            _assert_no_blocking_horizontal_overflow(page)
            browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        api_server.shutdown()
        api_server.server_close()