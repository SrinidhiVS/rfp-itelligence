# Architecture

```mermaid
flowchart TD
    Launch[One-command launcher] --> Parse[HTML and PDF ingestion]
    Files[Bid folders or UI uploads] --> Parse
    Parse --> Chunk[Section chunks and separate tables]
    Chunk --> Corpus[JSON corpus with source provenance]
    Chunk --> Embed[Sentence Transformers all-MiniLM-L6-v2]
    Embed --> Chroma[(Persistent Chroma vectors)]
    Launch --> API[FastAPI service]
    Launch --> UI[Streamlit UI]
    UI -->|HTTP Q&A or background extraction job| API
    API --> Planner[Planner agent]
    Planner -->|Validated workflow handoff| Ingest[Ingestion agent]
    Ingest -->|Ensure index and refresh| Corpus
    Ingest --> Retrieval[Retrieval agent]
    Retrieval --> Search[Search engine]
    Corpus --> Search
    Chroma --> Search
    Search --> Keyword[Exact tokens and query expansion]
    Search --> Semantic[Semantic candidates and vector neighbors]
    Keyword --> Rank[Rank fusion and deduplication]
    Semantic --> Rank
    Rank --> Authority[Optional reranker and addendum authority]
    Authority -->|Cited evidence with bid scope| Retrieval
    Retrieval --> Extract[Extraction agent and parallel field groups]
    Model[Deterministic or OpenAI or Ollama provider] --> Extract
    Extract --> Reconcile[Addendum reconciliation agent]
    Reconcile --> Validate[Validation agent]
    Validate -->|Bounded retry for unresolved fields| Retrieval
    Validate --> Report[Report agent]
    Report -->|Response or completed job| API
    API -->|Values, confidence, citations, diagnostics| UI
    Report --> Trace[Sanitized local agent trace]
    Trace -.->|Optional configured delivery| LangSmith[LangSmith]
    Corpus --> Export[Deliverable exporter]
    Export --> JSON[One canonical JSON record per bid folder]
    Search --> Eval[Recall at k and MRR evaluation]
    Eval --> Metrics[Report and labeled questions]
```

## Communication

The UI calls the API over loopback HTTP. Extraction runs in an API-managed background
job, and the UI polls for its validated response. Standalone synchronous endpoints remain
available. The launcher owns only its two child processes and forwards the actual API URL
and indexed bid IDs to Streamlit.

Agents execute as LangGraph nodes in one process, not independent network services.
Pydantic handoff messages identify sender, recipient, run, task, payload type, state version,
and retry context. Retrieval tool calls carry bid/document filters. Evidence preserves file,
page or HTML locator, text, authority status, and addendum identity across every boundary.

The canonical twenty-field extractor is reused by CLI/API export. Per-item citations and
confidence accompany collection values. Validation can request bounded additional retrieval;
missing facts remain null/not found, and unresolved conflicts remain review-required.

## Persistence And Limits

- Normalized reports: `output/<folder>/processing-report.json`.
- Corpus: `output/search-index.json`; active vector collection: `output/chroma`.
- Runtime trace path is configurable; exported examples live under `output/sample-outputs`.
- API extraction jobs are process-local and disappear on restart; they are not a durable queue.
- Optional remote model providers receive evidence text. Deterministic exports need no model credentials.
- Image-only source pages are diagnosed, not OCR-transcribed. Confidence is heuristic.
- Two legacy evaluation questions depend on removed headings and are audited as excluded, not scored as successes.