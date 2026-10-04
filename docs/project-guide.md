# Project Guide

## Purpose

RFP Document Intelligence ingests procurement bid folders, preserves source provenance, builds searchable text and vector indexes, and provides cited question answering and structured bid extraction. HTML and PDF sources are supported. The system is designed to process a folder per bid and to avoid inventing values when evidence is missing or conflicting.

The root [README](../README.md) is the quick-start and command reference. This guide describes the full runtime, the available modes, and the implementation decisions. The [architecture diagram](architecture.md) shows the major data flows.

## Requirements And Installation

- Python 3.10 or newer; Python 3.11 is the version used for workspace validation.
- Windows, macOS, or Linux. Examples below use PowerShell where shell syntax differs.
- Disk space for Python dependencies, the local embedding model cache, the search corpus, and Chroma data.
- No API credentials are required for ingestion, local indexing, search, deterministic extraction, the tests, or the standard UI workflow.

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

On macOS/Linux, activate the environment with `source .venv/bin/activate`. If PowerShell blocks activation, use `.venv\Scripts\python.exe -m pip ...` and `.venv\Scripts\python.exe -m ...` directly; changing the machine execution policy is not required.

Copy `.env.example` to `.env` only when changing defaults or configuring a provider. Keep `.env` private. The first vector-index operation downloads `sentence-transformers/all-MiniLM-L6-v2` into the model cache. Ollama, when selected, is a separate application and is not installed by pip.

## Sharing A Source Bundle

To create a smaller ZIP for another developer, run this PowerShell block from the repository root. It stages only Git-tracked and non-ignored files from the current working tree, so uncommitted changes are included:

```powershell
$repo = (Get-Location).Path
$projectName = Split-Path $repo -Leaf
$zip = Join-Path (Split-Path $repo -Parent) "$projectName-source.zip"
$stage = Join-Path $env:TEMP ("$projectName-source-" + [guid]::NewGuid().ToString("N"))
$stageRoot = Join-Path $stage $projectName
$exclude = '^(deletable|deliverables|output|\.venv|venv|rfp_document_ingestion\.egg-info|__pycache__|\.pytest_cache)(/|$)'

if (Test-Path -LiteralPath $zip) { throw "Archive already exists: $zip" }
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
$files = git -C $repo ls-files --cached --others --exclude-standard
foreach ($file in $files) {
	if ($file -match $exclude -or $file -eq "traces/runtime-trace.json") { continue }
	if ($file -match '^\.env(\..*)?$' -and $file -ne ".env.example") { continue }
	$source = Join-Path $repo $file
	if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
	$target = Join-Path $stageRoot $file
	New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
	Copy-Item -LiteralPath $source -Destination $target
}
Compress-Archive -Path $stageRoot -DestinationPath $zip -CompressionLevel Optimal
Remove-Item -LiteralPath $stage -Recurse -Force
```

The ZIP is written next to the repository. The staging step omits local environments, ignored generated data, deliverable snapshots, `.env` files, and the runtime trace; it does not delete or modify those files. Review the ZIP contents before sharing it, especially if you have added untracked files.

The source bundle includes `Initial_docs`, which contains the sample bid documents used by the default run. Share those documents only if you are permitted to distribute them. Otherwise remove them from the ZIP and provide authorized input documents separately.

After extracting the ZIP, another developer can follow the setup below to create a fresh virtual environment and install dependencies, then run `python -m src.run`. To use Docker instead, run `docker compose up --build`; the Docker setup installs its own dependencies and stores its generated corpus, vector index, traces, and downloaded model in Docker volumes. The first vector-indexing run needs internet access to download the embedding model.

## Dependencies

The installable requirements are declared in [pyproject.toml](../pyproject.toml); the ranges below are authoritative.

| Package | Role |
| --- | --- |
| `beautifulsoup4` | HTML parsing. |
| `PyMuPDF` | PDF text and table extraction. |
| `sentence-transformers` | Local passage embeddings and optional cross-encoder reranking. |
| `numpy` | Vector and numerical operations. |
| `chromadb` | Persistent local vector collection. |
| `filelock` | Protects local index updates across processes. |
| `fastapi`, `uvicorn` | HTTP API and ASGI server. |
| `streamlit` | Browser-based review and import interface. |
| `langgraph` | In-process workflow graph for analysis agents. |
| `pydantic` | Runtime validation of workflow messages, API requests, and response contracts. |
| `openai` | OpenAI-compatible model client, also used with Ollama's compatible endpoint. |
| `langsmith` | Optional LangSmith tracing integration. |
| `python-dotenv` | Optional root `.env` loading. |
| `pytest`, `jsonschema`, `playwright` | Test extra for unit/integration/contract checks and browser tests. |

The project uses local Sentence Transformers for embeddings. These are distinct from the optional language-model provider configured for extraction proposals and final answer prose.

## Run Modes

Run commands from the repository root with the project virtual environment active.

### Combined UI And API

This is the normal interactive path. It ingests every immediate bid folder under `Initial_docs`, incrementally updates the corpus and Chroma, starts FastAPI, waits for its health endpoint, then launches Streamlit:

```powershell
python -m src.run
```

The launcher prints the actual UI and API URLs. It chooses free loopback ports if the preferred ports are busy and stops only the child processes it started when interrupted with Ctrl+C. To reuse existing indexes, select another document root, or choose ports:

```powershell
python -m src.run --skip-ingest
python -m src.run --documents path\to\bid-folders --api-port 8001 --ui-port 8502
```

`--skip-ingest` still reads the immediate folder names for the UI bid selector; it does not ingest changed documents. Use the default launch command after source changes.

### Standalone Ingestion

Process one bid folder, write a processing report, and update its source-scoped records in the canonical corpus. The command also attempts to synchronize Chroma:

```powershell
python -m src.cli ingest Initial_docs\Bid1 --output output\Bid1
```

The report is `output/Bid1/processing-report.json`. It includes the discovered-file inventory, parser statuses, normalized pages, extracted tables, chunks, provenance, and diagnostics. Repeat for each bid folder. A failed/unsupported source is reported instead of being silently omitted; usable sources can still be indexed.

### Corpus And Vector Index

Index a previously generated processing report or rebuild the lexical corpus explicitly:

```powershell
python -m src.cli index --input output\Bid1\processing-report.json
python -m src.cli rebuild --input output\Bid1\processing-report.json
```

Build or refresh the persistent Chroma index from the current corpus:

```powershell
python -m src.cli vector-index
python -m src.cli vector-index --model all-MiniLM-L6-v2 --rebuild
```

Normal ingestion synchronizes changed source scopes automatically. `vector-index` is useful for first setup, manual repair, or a full re-embedding. Chroma is the active vector backend; the legacy `RFP_VECTOR_INDEX_PATH` JSON setting does not select the Chroma directory.

### Search, Question Answering, And Evaluation

```powershell
python -m src.cli search "submission deadline" --bid-id Bid1 --top-k 5
python -m src.cli ask "What is the submission deadline?" --bid-id Bid1
python -m src.cli evaluate --cases eval/cases.json --top-k 5 --warm-up
```

`search` returns ranked source evidence as JSON. `ask` returns an answer with citations where available. `evaluate` compares semantic-only and hybrid retrieval on a labeled case file and requires a ready, corpus-compatible vector index; it exits with an error rather than presenting a vector fallback as indexed evaluation. The checked-in deliverables contain a separate corpus/case snapshot and its recorded metrics; those numbers are not a general accuracy guarantee.

### Structured Extraction CLI

Ingest the bid before running extraction. The input's final path component identifies the bid ID; evidence is read from the canonical corpus:

```powershell
python -m src.cli ingest Initial_docs\Bid1 --output output\Bid1
python -m src.extraction.cli extract --input Bid1 --output output\bid-records
```

The result is `output/bid-records/Bid1/structured-record.json` by default. Configure the base output directory with `RFP_EXTRACTION_OUTPUT`. The record has twenty canonical fields, citations, confidence, status, addendum changes, validation counts, and source diagnostics. The one-command UI startup and deliverable exporter also use the shared corpus.

### API Only

Start the API independently when developing clients or the UI:

```powershell
uvicorn src.api.app:app --reload
```

Useful endpoints:

- `GET /health` reports service and semantic-search readiness.
- `GET /docs` opens the generated OpenAPI reference.
- `POST /v1/analysis/qa` runs cited Q&A for one or more bid IDs.
- `POST /v1/analysis/extract` runs synchronous structured extraction.
- `POST /v1/analysis/extraction-jobs` queues an extraction job; poll `GET /v1/analysis/extraction-jobs/{job_id}` for status/result.

API extraction jobs are held in process memory, capped at two simultaneous workers and 64 retained jobs; terminal jobs expire after one hour. Restarting the API loses active jobs. See [frontend validation](frontend-validation.md) for polling and recovery behavior.

### Streamlit UI Only

Start the API first, then run the UI in a second terminal:

```powershell
streamlit run src/frontend/app.py
```

Set `RFP_API_URL` if the API is not at `http://127.0.0.1:8000`. The UI supports Q&A, extraction review, and importing a new bid folder. For normal use, prefer the combined launcher above.

### Deliverables And Tests

Generate the structured records, retrieval evaluation, sample Q&A, and example workflow trace from the current corpus:

```powershell
python -m src.deliverables
```

Ingest the selected document folders and build the vector index first. Optional arguments are `--documents`, `--output`, `--cases`, and `--top-k`; run `python -m src.deliverables --help` for usage.

Run the full automated suite:

```powershell
python -m pytest -q
```

For browser-driven frontend tests, install Playwright's Chromium runtime once:

```powershell
python -m playwright install chromium
python -m pytest -q tests/frontend
```

Tests use deterministic providers and fixtures where possible; API/model credentials are not needed for the suite.

## Configuration

All settings are optional unless a selected provider requires credentials. Environment variables override defaults.

| Setting | Default / use |
| --- | --- |
| `RFP_MODEL_PROVIDER` | `auto`; `auto`, `openai`, or `ollama`. In `auto`, OpenAI is used only when `OPENAI_API_KEY` is set; otherwise the deterministic provider is selected. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional OpenAI credentials/model; model default is `gpt-4o-mini`. |
| `RFP_OLLAMA_MODEL`, `RFP_OLLAMA_BASE_URL` | Ollama model and OpenAI-compatible URL; defaults are `qwen2.5:3b` and `http://localhost:11434/v1`. |
| `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Optional LangSmith trace delivery; project default is `rfp-multi-agent-analysis`. |
| `RFP_INDEX_PATH` | Canonical corpus path; default `output/search-index.json`. |
| `RFP_CHROMA_PATH` | Persistent Chroma directory; default `output/chroma`. |
| `RFP_EMBEDDING_MODEL` | Sentence Transformers embedding model; default `all-MiniLM-L6-v2`. Changing it requires compatible vector re-embedding. |
| `RFP_RERANK_MODEL` | Optional Sentence Transformers cross-encoder model for final reranking; unset means deterministic heuristics only. |
| `RFP_TOP_K` | Search default result count (CLI commands also provide their own defaults/options); default `5`. |
| `RFP_MAX_RETRIES` | Maximum validation-driven retrieval retries; default `2`. |
| `RFP_TRACE`, `RFP_TRACE_PATH` | Toggle local trace recording and choose its path; defaults are enabled and `traces/runtime-trace.json`. |
| `RFP_API_URL`, `RFP_BID_IDS` | Streamlit API address and available bid IDs. The combined launcher sets both for its child UI. |
| `RFP_FRONTEND_TIMEOUT`, `RFP_JOB_REQUEST_TIMEOUT`, `RFP_JOB_POLL_INTERVAL`, `RFP_JOB_MAX_WAIT` | UI request and extraction-job polling behavior; defaults are 60, 15, 1, and 1800 seconds respectively. |
| `RFP_SUBMISSION_ROOT` | Authorized staged-upload folder root; default `output/imported-bids`. |
| `RFP_EXTRACTION_OUTPUT` | Structured extraction CLI output root; default `output/bid-records`. |

Never commit `.env` or expose provider credentials. OpenAI requests include selected evidence text. Ollama keeps model inference on the configured local server, but local network/security policy still applies. LangSmith tracing is optional and should only be enabled when its data handling is appropriate for the bid material.

## System Design

### Ingestion And Provenance

`src.ingestion` separates discovery/classification, HTML/PDF parser adapters, normalization, metadata, tables, chunking, diagnostics, and serialization. Both parsers produce a shared page/section/table model. Each bid is processed as its own scope; source statuses distinguish parsed, partial, failed, and unsupported files. Stable IDs and source locators retain bid, relative path, page or HTML location, section, and table identity. Missing dates and amendment numbers remain unknown instead of being inferred.

HTML headings and sections guide text boundaries; extracted tables are kept as separate chunks. Text chunks target 120 words, are capped at 150 words, and overlap adjacent chunks by 20 words within the same section. Splits favor paragraph and sentence boundaries before falling back to word boundaries. This balances focused retrieval with nearby context and prevents a table from being blended into prose.

### Embeddings And Retrieval

The default encoder is the local `sentence-transformers/all-MiniLM-L6-v2`, which returns 384-dimensional embeddings. Vectors are normalized, encoded in batches of 32, and persisted in the `rfp_passages` Chroma collection using cosine distance. Local encoding avoids a hosted embedding dependency. The initial model download is a setup cost; subsequent runs use the local model cache.

The JSON corpus at `output/search-index.json` remains the canonical source of text and metadata. Chroma stores vector representations and a manifest of embedding compatibility and source-scope fingerprints. Ingestion updates only changed `bid_id` plus normalized relative-path scopes; unchanged scopes are retained, changed scopes replaced, and removed sources reconciled. Writes are locked and use recovery metadata. Semantic search must not report a stale or incompatible vector index as ready.

Retrieval filters by bid, document type, and addendum before ranking. It creates exact/weighted keyword and bounded query-expansion candidates alongside semantic candidates; when Chroma is available, vector neighbors join the hybrid candidate set. Reciprocal-rank fusion uses rank contributions of `1 / (60 + rank)`, then near-duplicate passages from the same bid/file/page are consolidated. A deterministic heuristic reranker boosts query overlap, identifiers, procurement requirements, and relevant addendum language. `RFP_RERANK_MODEL` optionally enables a cross-encoder over at most ten candidates; errors fall back to the heuristic order. Exact numeric identifiers are guarded against vector-only mismatches.

Semantic-only and hybrid evaluation use the checked-in labeled cases and report Recall@k and MRR. Measurements are corpus- and label-specific. They should not be interpreted as an overall procurement accuracy claim.

### Agents, Framework, And Prompts

`src.agents.graph.AnalysisWorkflow` uses LangGraph to execute these in-process nodes:

1. Planner selects the requested QA task or extraction field groups.
2. Ingestion ensures requested bid evidence is indexed.
3. Retrieval gathers scoped passages; extraction field groups can retrieve concurrently.
4. Extraction proposes field values or synthesizes deterministic QA claims.
5. Reconciliation resolves addendum changes and authority conflicts.
6. Validation checks dispositions and can request bounded retrieval retries.
7. Report builds the final response and records citations/diagnostics.

Pydantic-validated handoff messages carry run/task IDs, state version, retry context, and typed state between graph nodes. This is one LangGraph process, not a set of distributed agent services. `RFP_MAX_RETRIES` bounds validation-driven retrieval loops.

The optional model provider is deliberately downstream of retrieval and does not establish citation metadata or override evidence validation. The configured provider can return extraction proposals, but a proposal is retained only if supported by the selected passage and local extraction result. QA claims, citations, conflict decisions, and not-found responses are determined before optional report wording.

The OpenAI-compatible extraction system prompt is:

> Extract only values supported by the supplied evidence. Use null when unsupported. Return JSON keyed by field name.

The report-writing system prompt is:

> Write a concise answer using only the supplied established claims. Do not add facts, values, dates, or qualifications. Return a JSON object with an 'answer' string.

Both calls use temperature zero and JSON response mode. The extraction payload limits each passage to 2,000 characters and includes field names plus evidence ID, bid, file, and page. The report payload includes the question and established claim text. With no selected external provider, extraction proposals are empty and final report prose uses the deterministic answer. Confidence values are evidence-quality heuristics, not calibrated probabilities.

### Structured Extraction And Safety Boundaries

The canonical structured extractor emits twenty stable fields. A supported value carries source citation, confidence, and status; missing evidence is `null`/`not_found` with confidence `0.0`; unresolved or weakly supported results remain review-required. Addendum reconciliation preserves previous/current values and controlling citations, and unresolved equal-authority conflicts require review. See [structured extraction](structured-extraction.md) for its output contract.

Image-only PDF pages produce incomplete-coverage diagnostics; automatic OCR is not implemented. The UI/API extraction job queue is in-memory, not durable. Search/evaluation quality depends on supplied sources, corpus freshness, and labeled cases. Review diagnostics and citations before relying on generated records for procurement decisions.

## Repository Map

| Path | Responsibility |
| --- | --- |
| `src/ingestion/` | Discovery, parsers, normalization, tables, provenance, chunking, reports. |
| `src/search/` | Canonical corpus indexing, keyword/vector search, retrieval, QA, evaluation. |
| `src/agents/` | LangGraph plan, retrieval/extraction/reconciliation/validation/report workflow and tracing. |
| `src/extraction/` | Canonical twenty-field structured record, validation, serialization, CLI. |
| `src/api/` | FastAPI routes and process-local extraction jobs. |
| `src/frontend/` | Streamlit Q&A, extraction review, and import UI. |
| `src/cli.py`, `src/run.py`, `src/deliverables.py` | Ingestion/search CLI, combined launcher, and artifact export. |
| `tests/` | Unit, integration, contract, and frontend checks. |
| `eval/` | Labeled retrieval and agent evaluation cases. |
| `Initial_docs/` | Supplied sample bid folders. |
| `output/`, `traces/` | Generated reports, indexes, deliverables, and runtime traces; do not treat generated output as source. |

## Related Documentation

- [Architecture and data-flow diagram](architecture.md)
- [Ingestion design](ingestion-design.md) and [ingestion validation](ingestion-validation.md)
- [Multi-agent design](multi-agent-design.md) and [multi-agent validation](multi-agent-validation.md)
- [Structured extraction design](structured-extraction.md) and [validation matrix](structured-extraction-validation.md)
- [Frontend validation](frontend-validation.md)
- [Search validation](search-validation.md)
- [Local embedding search validation](local-embedding-search-validation.md)
