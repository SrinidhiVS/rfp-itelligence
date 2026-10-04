# Frontend Validation

## Startup

1. Start the backend with `uvicorn src.api.app:app --reload`.
2. Set `RFP_API_URL` if the backend is not at `http://127.0.0.1:8000`.
3. Set `RFP_BID_IDS` to a comma-separated configured bid list when using bids beyond Bid1/Bid2.
4. Start the UI with `streamlit run src/frontend/app.py`.

## Requirements coverage

- Q&A: single-bid questions, comparison questions, citations, not-found, and grouped evidence.
- Extraction: twenty fields, confidence, statuses, citations, addendum changes, validation, and diagnostics.
- Failure states: connection, timeout, validation, configuration, malformed response, partial, and review-required.
- Extraction jobs: queued/running/terminal status, bounded polling, resume after polling timeout, expired-job handling, and compatibility of the synchronous extraction endpoint.
- Long answers: concise claim previews with citations and collapsed full passages; addendum changes and collection fields render as structured details rather than raw JSON dumps.
- Safety: no API keys, provider secrets, hidden prompts, or unsupported claims in response views.
- Accessibility review: all selectors and inputs require labels; field sections and diagnostics must remain keyboard-navigable; citations must retain readable file/location text on narrow screens.

## Automated Responsive Interaction Checks

Install the test extra and Chromium before running the browser checks:

```powershell
python -m pip install -e ".[test]"
python -m playwright install chromium
python -m pytest -q tests/frontend/test_app_workflows.py tests/frontend/test_responsive_ui.py
```

The responsive suite launches the frontend against deterministic analysis responses and checks full Q&A/comparison, delayed extraction-job polling, import, and recoverable-error interactions at 1280px desktop and 480px narrow viewport widths. It verifies canonical field order, citation location text, collapsed long claims, visible statuses/diagnostics, retained retry context, and page overflow that could block reading or navigation. Jobs are process-local; restarting the API invalidates an in-flight job ID.

## Recorded Validation (2026-10-02)

- `python -m pytest -q tests/frontend`: 39 passed, including AppTest and browser workflows.
- `python -m pytest -q tests/frontend/test_responsive_ui.py`: 2 passed at 1280px and 480px, including delayed extraction-job polling and long-claim disclosure.
- `python -m pytest tests/unit/test_extraction_jobs.py tests/integration/test_extraction_jobs_api.py tests/integration/test_api.py -q`: 10 passed. One existing Starlette deprecation warning notes that `httpx` with `starlette.testclient` is deprecated.
- Full repository `python -m pytest -q`: 440 passed, 0 failed, with one existing Starlette/httpx deprecation warning. Supplemental case fixtures now resolve source-verified records in test-owned temporary corpora and do not depend on the contents of `output/search-index.json`.
- Responsive browser import workflows use temporary corpus and Chroma paths; the full test run left the workspace `output/search-index.json` and all six existing `output/chroma/` files unchanged.
- Responsive browser checks use a deterministic local analysis stub and import a temporary HTML file; they do not require configured provider credentials or a live analysis backend.
