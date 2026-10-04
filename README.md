# RFP Document Intelligence

This project ingests procurement bid folders, indexes normalized evidence, and exposes a
source-grounded multi-agent analysis workflow. It supports HTML bid pages and PDF documents
without hard-coding the supplied bids.

For complete setup instructions, all run modes, configuration, and design decisions, see the
[project guide](docs/project-guide.md). This README remains the quick-start and command reference.

## Setup

Python 3.10 or newer is required; this workspace was validated with Python 3.11.
Run from the project root. On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

If activation is restricted, use `.venv\Scripts\python.exe` directly instead of changing
your execution policy. On macOS/Linux, activate with `source .venv/bin/activate`.
The first embedding run downloads `sentence-transformers/all-MiniLM-L6-v2`; subsequent
runs can use its local cache. No API key is required for deterministic local operation.
Copy the settings from [.env.example](.env.example) into your local `.env` only when needed;
never publish credentials or upload confidential bid evidence to a remote model unintentionally.

### Dependencies

Versions are declared in [pyproject.toml](pyproject.toml). Beautiful Soup parses HTML;
PyMuPDF parses PDFs and tables. Sentence Transformers, NumPy, and Chroma provide local
embeddings and vector persistence; FileLock protects index writes. LangGraph orchestrates
agents, Pydantic validates contracts, and LangSmith optionally receives sanitized traces.
FastAPI/Uvicorn serve the API, Streamlit provides the UI, python-dotenv loads settings,
and the OpenAI SDK supports OpenAI and Ollama-compatible endpoints. The test extra installs
pytest, jsonschema, and Playwright. Ollama and its model are optional separate installations.

## Docker

Docker Compose v2.24 or newer is required. From the repository root, build and start the
container with:

The initial Docker image build takes about 15 minutes, followed by about 5 minutes to download
the embedding model on first startup. These are estimates; machine performance and internet
speed affect the actual time. Later starts reuse the built image and the persisted model cache.

```powershell
docker compose up --build
```

Open the UI at `http://127.0.0.1:8501`. The API stays private inside the container; the
launcher uses it for UI requests and Docker's health check. The container ingests each bid
folder from `Initial_docs` at startup, so include those input folders in the source checkout.
The same `Initial_docs` directory is mounted read-only; uploads from the UI are stored
separately in persistent Docker volumes.

Corpus data, Chroma vectors, imported bids, and generated reports persist in the `rfp-output`
volume. Traces persist in `rfp-traces`; downloaded embedding models persist in
`rfp-model-cache`, avoiding another download on later starts. Stop with Ctrl+C or
`docker compose down`. To intentionally remove persisted Docker data as well, run
`docker compose down --volumes`.

No API key is required for deterministic local operation. To configure optional OpenAI or
LangSmith integrations, create a `.env` from `.env.example` and set only the credentials you
intend to use; Compose passes that file into the container without copying it into the image.
The first vector-indexing run needs outbound access to download the configured embedding model.
When connecting to Ollama running on the host, set `RFP_OLLAMA_BASE_URL` to
`http://host.docker.internal:11434/v1` in `.env`.

Docker runs the combined API/UI launcher only. Existing local modes remain available: use
`python -m src.run` for the local combined launcher, `python -m src.cli` for CLI workflows,
or start Uvicorn and Streamlit separately as described below.

## One-Command UI

```text
python -m src.run
```

This discovers every folder in `Initial_docs`, ingests HTML/PDF sources, incrementally
updates the corpus and Chroma, waits for API readiness, and launches Streamlit with all
preloaded bid folders available. Older IDs left in the search index stay hidden until their
documents are imported. The terminal prints the actual UI URL, normally
`http://127.0.0.1:8501`. Occupied ports are replaced with free loopback ports; existing
servers are not stopped. Ctrl+C stops only the servers owned by this launcher.

Use **Ask questions** for cited Q&A, **Review extraction** for background extraction jobs,
or **Import new bid folder** to ingest additional files through the UI. No separate
backend command is needed. After installation, `rfp-ui` is an equivalent entry point.

```text
python -m src.run --skip-ingest
python -m src.run --documents path/to/bid-folders --api-port 8001 --ui-port 8502
```

`--skip-ingest` reuses existing indexes; use the default command after changing source files.
The launcher does not install dependencies, pull Ollama models, or alter `.env`.

## Run

```text
python -m src.cli ingest Initial_docs/Bid1 --output output/Bid1
python -m src.cli ingest Initial_docs/Bid2 --output output/Bid2
```

Each output folder contains `processing-report.json`. The report includes every discovered file,
source metadata, normalized pages, table rows, chunks, status values, and diagnostics.

## Validate

```text
python -m pytest -q
```

HTML and PDF parser adapters are separate, tables are first-class evidence, and provenance
identifiers are deterministic. Search, multi-agent analysis, and twenty-field extraction are
implemented. Image-only PDF pages produce coverage diagnostics; automatic OCR is not provided.

See the [ingestion design](docs/ingestion-design.md) and
[ingestion validation guide](docs/ingestion-validation.md).

## Multi-Agent Service

Configure providers through `.env` or the environment. Tests use deterministic doubles and do not
require credentials.

For local model-backed extraction and QA report writing, install Ollama, start its local server,
and pull a model:

```powershell
ollama pull qwen2.5:3b
```

Set these values in `.env` to select Ollama instead of OpenAI:

```dotenv
RFP_MODEL_PROVIDER=ollama
RFP_OLLAMA_MODEL=qwen2.5:3b
RFP_OLLAMA_BASE_URL=http://localhost:11434/v1
```

The same provider handles structured extraction and final QA answer prose. QA claims, citations,
conflict decisions, and not-found answers are still established by the deterministic evidence logic;
the model receives only those claims and cannot replace citation metadata. `RFP_MODEL_PROVIDER=auto`
preserves the existing behavior: use OpenAI when `OPENAI_API_KEY` is configured, otherwise use the
deterministic offline provider.

```text
uvicorn src.api.app:app --reload
```

Check the service before submitting a request:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/
Invoke-RestMethod http://127.0.0.1:8000/health
```

Use PowerShell's JSON serializer for POST requests:

```powershell
$body = @{ mode = "extraction"; bid_id = "Bid1"; trace = $true } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/v1/analysis/extract -Method Post -ContentType "application/json" -Body $body
```

Q&A example:

```powershell
$body = @{ mode = "qa"; question = "What is the submission deadline?"; bid_ids = @("Bid1"); trace = $true } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/v1/analysis/qa -Method Post -ContentType "application/json" -Body $body
```

The service also exposes `POST /v1/analysis/qa`. Responses preserve evidence citations, authority
metadata, diagnostics, retry counts, and a sanitized trace reference. Unsupported claims return
`Not found in documents`.

## Streamlit Frontend

For normal use, run `python -m src.run`. To run each server independently during development,
start the backend first, then launch the review interface:

```text
streamlit run src/frontend/app.py
```

Set `RFP_API_URL` when the backend is not running at `http://127.0.0.1:8000`. The interface
supports cited Q&A and twenty-field extraction review without changing backend contracts.
Extraction runs through a background job so long analyses do not hit the browser's request
timeout. The UI polls job status and can resume polling the same job after a temporary connection
or polling timeout. The existing synchronous `POST /v1/analysis/extract` route remains available
for existing API clients.

Tune frontend job polling with `RFP_JOB_REQUEST_TIMEOUT` (default `15` seconds per API call),
`RFP_JOB_POLL_INTERVAL` (default `1` second), and `RFP_JOB_MAX_WAIT` (default `1800` seconds).
Jobs are held in the API process, limited to two simultaneous workers and 64 retained jobs, and
terminal records expire after one hour. Restarting the API clears in-flight jobs; the UI reports
an expired/unknown job and allows a fresh extraction.

To add a new bid, expand **Import new bid folder** in the sidebar, enter a folder name, select its
HTML/PDF files, and choose **Import and index**. The generated bid ID is added to the bid selector
after ingestion and incremental indexing completes.

## RAG Search

Generate normalized reports first, then index them into the persistent search corpus:

```text
python -m src.cli index --input output/Bid1/processing-report.json
python -m src.cli index --input output/Bid2/processing-report.json
python -m src.cli search "deadline" --top-k 5
python -m src.cli ask "What is the submission deadline for Bid1?"
python -m src.deliverables
python -m src.cli evaluate --cases output/sample-outputs/retrieval-cases.json --top-k 5 --warm-up
```

### Retrieval Evaluation Results

The latest generated plain-text retrieval report evaluates 19 source-verified questions with a
cutoff of five on 497 corpus records. Two old heading-only labels are excluded before scoring.
Run `python -m src.deliverables` to regenerate the report and exclusion audit. Both configurations
use compatible Chroma vectors and heuristic ranking.

| Search mode | Recall@5 | MRR | Status |
|---|---:|---:|---|
| Semantic-only | 0.5263 | 0.3439 | Indexed vectors |
| Hybrid | 0.4737 | 0.2421 | Indexed vectors + keywords |

For this evaluator, Recall@5 is the mean fraction of each question's expected relevant
passages retrieved in the first five results. A no-match question scores 1 when no results
are returned, otherwise 0. MRR uses the first relevant result within that cutoff.
The JSON report includes case-set hash, corpus identity, timestamps, and model readiness.
These results are not directly comparable with the old 21-case, 180-record snapshot.
To reproduce on the same indexes and remapped labels:

```text
python -m src.deliverables
python -m src.cli evaluate --cases output/sample-outputs/retrieval-cases.json --top-k 5 --warm-up
```

The report includes case-set/index identity and actual mode status. A missing or
incompatible vector index prevents publication of a purported indexed comparison.
These values describe only the indexed bids and labeled case set above, not other
procurement collections.

Set `RFP_INDEX_PATH` to select a different corpus file. Index updates are scoped to
`bid_id` plus normalized relative source path; unchanged files are skipped, changed files are
replaced atomically, deleted files are removed, and other bids remain untouched. Use `rebuild`
instead of `index` for an explicit full rebuild.

### Evidence Chunking

Text is split within extracted headings and sections with a **120-word target**, a **150-word
maximum**, and **20 words of overlap** between adjacent chunks from the same section. Splits
prefer paragraph and sentence boundaries, then use word boundaries for oversized paragraphs.
Tables remain distinct chunks and are never merged into prose or included in text overlap. The
target keeps evidence passages focused, the maximum leaves input room for the local embedding
model's wordpiece expansion, and the overlap preserves nearby context without crossing section
boundaries.

### Embeddings And Retrieval

The default embedding model is `all-MiniLM-L6-v2`, with normalized 384-dimensional vectors
and batches of 32. It is small enough for CPU execution and avoids a hosted embedding service.
The active vector database is `output/chroma`; `RFP_CHROMA_PATH` selects another location.
Legacy vector JSON files are not the active Chroma backend and are retained for compatibility.

Hybrid search combines exact-token keyword candidates, expanded procurement queries,
semantic candidates, and Chroma neighbors using reciprocal-rank fusion, deduplication,
and addendum-aware authority handling. Filters constrain bid, document type, and amendment
number before final selection. Identifier matching protects exact model/part/solicitation queries.
An optional `RFP_RERANK_MODEL` enables a Sentence Transformers cross-encoder; otherwise
ranking is heuristic. Missing vectors are diagnosed rather than silently reported as semantic success.
The current small evaluation favors semantic-only; it does not establish a universal winner.

### Agent Framework And Prompts

LangGraph runs Planner -> Ingestion -> Retrieval -> Extraction -> Reconciliation -> Validation
-> Report, with bounded retrieval retries when validation requests more evidence. Agent handoffs
are Pydantic-validated messages carrying run/task IDs, state, and retry context. Extraction groups
run concurrently; the canonical extractor retains all matching bid records to avoid list truncation.
The central field registry keeps planner aliases and validation labels aligned.

Prompts are implemented in [src/agents/providers.py](src/agents/providers.py). The extraction
system prompt is: "Extract only values supported by the supplied evidence. Use null when
unsupported. Return JSON keyed by field name." Its user payload contains requested fields and
evidence IDs, bid IDs, file, page, and at most 2,000 characters of text per passage.

The report system prompt is: "Write a concise answer using only the supplied established claims.
Do not add facts, values, dates, or qualifications. Return a JSON object with an 'answer' string."
Temperature is zero and responses must be JSON. Deterministic validation, citations, and
addendum reconciliation remain authoritative; unsupported or conflicting facts are not invented.
Q&A supports specific factual intents, not arbitrary open-ended reasoning. Confidence scores
are evidence-quality heuristics, not calibrated probabilities.

## Generated Deliverables

```text
python -m src.deliverables
```

Ingest each bid first, or use the one-command UI startup. The exporter uses the real corpus,
cached/local embeddings, and the deterministic agent provider; it does not call a paid LLM or
send its example trace to LangSmith. Existing evaluation labels are mapped by source, page,
and whitespace-equivalent excerpt. Stale labels are audited separately before scoring.

- Curated [Bid1 JSON](output/sample-outputs/bids/Bid1/structured-record.json) and [Bid2 JSON](output/sample-outputs/bids/Bid2/structured-record.json): twenty fields with values, item-level citations, confidence, status, and addendum changes.
- `output/sample-outputs` currently contains only those two structured records. Running `python -m src.deliverables` regenerates the complete artifact set there, including retrieval reports, Q&A, and an agent trace.
- [Architecture diagram](docs/architecture.md): search components, agent communication, retries, and output paths.

The canonical CLI export is also available independently:

```text
python -m src.extraction.cli extract --input Bid1 --output output/bid-records
python -m src.cli vector-index
```

Bid1 includes five empty PDF pages and remains partially covered; review processing diagnostics
before relying on a not-found field. Bid3 is a separate supplied folder even where its documents
duplicate Bid2. Do not interpret generated JSON or retrieval scores as adjudicated legal conclusions.

See the [multi-agent design](docs/multi-agent-design.md), [validation guide](docs/multi-agent-validation.md),
and [architecture diagram](docs/architecture.md).
