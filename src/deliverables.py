"""Generate source-verified extraction, retrieval evaluation, and QA artifacts."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from pydantic import BaseModel

from src.extraction.extractor import StructuredExtractor
from src.search.config import index_path
from src.search.evaluation import evaluate, load_cases, validate_cases
from src.search.storage import CorpusStore


QUESTIONS = (
    "What is the submission deadline?",
    "How should bids be submitted?",
    "What is the bid number?",
    "What products are requested?",
    "What model numbers are requested?",
    "What are the warranty requirements?",
    "What affidavits are required?",
    "Who is the procurement contact?",
    "What are the payment terms?",
    "When must delivery take place?",
    "What contract or cooperative should be used?",
    "What is the contract term?",
    "What is the solicitation number?",
    "Is a bid bond required?",
    "What insurance requirements apply?",
    "What did addendum 2 change?",
    "When does warranty coverage begin?",
    "What warranties apply to replacement parts?",
)


def write_json(path: Path, payload) -> None:
    """Write a JSON-compatible value as UTF-8, indented JSON with final newline.

    Args:
        path: Output file path; parent directories are created as needed.
        payload: Pydantic model or JSON-serializable object.

    Returns:
        ``None``.
    """
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def format_retrieval_report(
    report: dict,
    cases: list[dict],
    corpus_record_count: int,
    top_k: int,
    excluded_case_count: int,
) -> str:
    """Format retrieval metrics and questions as readable plain text.

    Args:
        report: Evaluation report containing run metadata and configurations.
        cases: Source-verified query cases included in the evaluation.
        corpus_record_count: Number of records in the indexed corpus.
        top_k: Result cutoff used for recall and reciprocal-rank metrics.
        excluded_case_count: Number of stale or unusable labels excluded.

    Returns:
        UTF-8-ready text with no Markdown heading, table, or list syntax and a
        trailing newline.
    """
    lines = [
        "Retrieval Evaluation",
        f"Measured: {report['run_context']['evaluated_at']}",
        f"Questions: {len(cases)}. Corpus records: {corpus_record_count}. Cutoff: {top_k}.",
        f"Excluded before evaluation: {excluded_case_count} stale heading-only labels. Details are in retrieval-exclusions.json.",
        "",
        "Configurations",
    ]
    for configuration in report["configurations"]:
        lines.extend([
            f"Configuration: {configuration['configuration']}",
            f"Recall at {top_k}: {configuration['recall_at_k']:.4f}",
            f"MRR: {configuration['mrr']:.4f}",
            f"Actual mode: {configuration['actual_mode']}",
            f"Reranker: {configuration['reranker_status']}",
            "",
        ])
    lines.extend([
        "Metric definitions",
        f"Recall at {top_k} is the mean fraction of labeled passages found in the first {top_k} results. MRR uses the first relevant rank within that cutoff. A not-found case scores 1 only when no results are returned.",
        "These measurements describe this small labeled collection, not general procurement accuracy. Semantic fallback is not counted as a successful indexed run.",
        "Labels retain the original question, source, page, and excerpt. IDs are mapped to the shortest matching current chunk after ingestion; this is not a like-for-like comparison with older chunking snapshots.",
        "",
        "Question Set",
    ])
    lines.extend(f"{case['case_id']} ({case['bid_id']}): {case['query']}" for case in cases)
    return "\n".join(lines) + "\n"


def refresh_cases(cases: list[dict], records: list) -> list[dict]:
    """Remap labeled excerpts to current chunks and revalidate evaluation cases.

    Args:
        cases: Labeled case dictionaries with expected passage source/excerpts.
        records: Current indexed corpus records.

    Returns:
        Deep-copied cases with current record IDs, matched excerpt spans, and
        source locators.

    Raises:
        ValueError: If a labeled excerpt is no longer present or refreshed
            cases violate retrieval evaluation contracts.
    """
    refreshed = deepcopy(cases)
    for case in refreshed:
        passages = []
        for passage in case["expected_passages"]:
            pattern = re.compile(r"\s+".join(re.escape(word) for word in passage["excerpt"].split()))
            candidates = [
                (record, pattern.search(record.text)) for record in records
                if record.bid_id == passage["bid_id"]
                and record.source_file == passage["source_file"]
                and record.page_number == passage["page_number"]
            ]
            candidates = [(record, match) for record, match in candidates if match]
            if not candidates:
                raise ValueError(f"{case['case_id']}: labeled source excerpt no longer exists; review the case against the documents")
            record, match = min(candidates, key=lambda item: (len(item[0].text), item[0].record_id))
            updated = {**passage, "record_id": record.record_id, "excerpt": match.group(), "source_locator": record.source_locator}
            if not any(item["record_id"] == record.record_id for item in passages):
                passages.append(updated)
        case["expected_passages"] = passages
        case["expected_record_ids"] = [item["record_id"] for item in passages]
    validate_cases(refreshed, records)
    return refreshed


def export_records(documents: Path, output: Path, records: list) -> list[str]:
    """Extract every bid folder and write one structured JSON record per bid.

    Args:
        documents: Directory containing bid folders.
        output: Deliverable root; records are written beneath ``bids/<bid_id>``.
        records: Current indexed corpus records used as source evidence.

    Returns:
        Bid folder names exported in sorted order.

    Raises:
        ValueError: If no bid folders exist or a bid has no indexed evidence.
    """
    folders = sorted(folder for folder in documents.iterdir() if folder.is_dir())
    if not folders:
        raise ValueError("No bid folders found")
    bids = []
    for folder in folders:
        evidence = [
            {"record": record.__dict__, "authority_status": record.status}
            for record in records if record.bid_id == folder.name
        ]
        if not evidence:
            raise ValueError(f"{folder.name}: no indexed evidence; ingest the folder first")
        record = StructuredExtractor().extract(folder.name, evidence)
        write_json(output / "bids" / folder.name / "structured-record.json", record.model_dump(mode="json"))
        bids.append(folder.name)
    return bids


def main(argv: list[str] | None = None) -> int:
    """Generate extraction JSON, retrieval metrics, trace, and cited QA samples.

    Args:
        argv: Optional CLI argument sequence for documents, output, case file,
            and positive top-k cutoff.

    Returns:
        Process code 0 after all artifacts and quality gates are written.

    Raises:
        ValueError: If no source-verified evaluation cases remain.
        RuntimeError: If vector evaluation, example workflow execution, or
            minimum cited-answer quality gates fail.
    """
    parser = argparse.ArgumentParser(description="Export real bid records, retrieval metrics, cited Q&A, and an agent trace")
    parser.add_argument("--documents", type=Path, default=Path("Initial_docs"))
    parser.add_argument("--output", type=Path, default=Path("output/sample-outputs"))
    parser.add_argument("--cases", type=Path, default=Path("eval/cases.json"))
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    from src.agents.graph import AnalysisWorkflow
    from src.agents.providers import DeterministicModelProvider
    from src.agents.settings import Settings
    from src.agents.state import WorkflowState
    from src.search.cli import _service, _vector_readiness

    corpus = CorpusStore(index_path()).load()
    bids = export_records(args.documents, args.output, corpus.records)
    cases = []
    excluded_cases = []
    for case in load_cases(args.cases):
        try:
            cases.extend(refresh_cases([case], corpus.records))
        except ValueError as exc:
            excluded_cases.append({"case": case, "reason": str(exc)})
    if not cases:
        raise ValueError("No source-verified retrieval cases remain")
    write_json(args.output / "retrieval-cases.json", cases)
    write_json(args.output / "retrieval-exclusions.json", excluded_cases)
    _, search = _service()
    readiness = _vector_readiness(search.vector_search, corpus.records)
    if not readiness["available"]:
        raise RuntimeError(f"Indexed semantic evaluation unavailable: {readiness['diagnostics']}")
    report = evaluate(
        search, cases, ["semantic-only", "hybrid"], args.top_k, warm_up=True,
        run_context={
            "case_set_path": str(args.output / "retrieval-cases.json"),
            "original_case_set_path": str(args.cases),
            "excluded_case_ids": [item["case"]["case_id"] for item in excluded_cases],
            "label_mapping": "Same bid, source file, page, and whitespace-equivalent labeled excerpt; shortest matching current chunk",
            "corpus": {"index_path": str(index_path()), "corpus_id": corpus.corpus_id, "record_count": len(corpus.records), "updated_at": corpus.updated_at},
            "vector_index": readiness,
        },
        require_vectors=True, vector_status=readiness,
    )
    write_json(args.output / "retrieval-report.json", report)
    if any(not item["available"] for item in report["configurations"]):
        raise RuntimeError("Evaluation encountered a vector fallback; inspect retrieval-report.json")
    retrieval_report_text = format_retrieval_report(
        report,
        cases,
        len(corpus.records),
        args.top_k,
        len(excluded_cases),
    )
    (args.output / "retrieval-report.txt").write_text(retrieval_report_text, encoding="utf-8")

    settings = Settings(index_path=str(index_path()), trace_enabled=False, max_retries=0)
    workflow = AnalysisWorkflow(settings=settings, model_provider=DeterministicModelProvider())
    extraction = workflow.invoke(WorkflowState(mode="extraction", goal="extract complete bid record", bid_ids=[bids[0]], max_retries=0))
    if extraction.status == "failed" or not extraction.trace:
        raise RuntimeError("Example extraction trace was not completed")
    write_json(args.output / "agent-trace.json", extraction.trace)
    write_json(args.output / "agent-extraction.json", extraction.final_output)
    entries = []
    for question in QUESTIONS:
        for bid in bids[:2]:
            result = workflow.invoke(WorkflowState(mode="qa", goal=question, bid_ids=[bid], max_retries=0))
            if result.status == "failed":
                raise RuntimeError(f"Q&A workflow failed: {bid}: {question}")
            entries.append({"bid_id": bid, "question": question, "run_id": result.run_id, "status": result.status, "output": result.final_output})
    cited = sum(bool(entry["output"].get("citations")) for entry in entries)
    write_json(args.output / "sample-qa.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_provider": "deterministic", "question_count": len(entries), "cited_answer_count": cited, "entries": entries,
    })
    if cited < 10:
        raise RuntimeError(f"Only {cited} cited answers were produced; inspect sample-qa.json before publishing")
    print(json.dumps({"output": str(args.output), "bids": bids, "evaluation_cases": len(cases), "qa_questions": len(entries), "cited_answers": cited}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())