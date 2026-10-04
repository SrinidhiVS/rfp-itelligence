"""Compose the RFP planning, ingestion, retrieval, extraction, and reporting graph."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from .addendum_agent import reconcile_changes
from .extraction_agent import extract_fields
from .ingestion_agent import ensure_index
from .messages import make_message, validate_message
from .planner import build_plan
from .providers import ModelProvider, configured_provider
from .report_agent import extraction_response, qa_response, synthesize_answer
from .retrieval_agent import RetrievalAgent
from .state import Diagnostic, ExtractionField, ExtractionResult, ModelUsage, WorkflowHandoffPayload, WorkflowRuntimePayload, WorkflowState
from .tracing import TraceRecorder
from .langsmith_sink import LangSmithTraceSink
from .settings import Settings
from .validator_agent import validate_fields


class AnalysisWorkflow:
    """Compile and invoke the versioned multi-agent RFP analysis workflow.

    Args:
        retrieval_agent: Optional retrieval implementation; a configured
            ``RetrievalAgent`` is created when omitted.
        max_retries: Maximum validation-driven retrieval/extraction retries.
        model_provider: Optional extraction/report provider; selected from
            settings when omitted.
        settings: Optional runtime configuration for model, index, trace, and
            provider settings.
    """

    def __init__(self, retrieval_agent: RetrievalAgent | None = None, max_retries: int = 2, model_provider: ModelProvider | None = None, settings: Settings | None = None):
        """Initialize dependencies and compile the workflow graph."""
        self.retrieval = retrieval_agent or RetrievalAgent()
        self.max_retries = max_retries
        self.settings = settings or Settings.from_env()
        self.model_provider = model_provider or configured_provider(self.settings)
        self.trace_sink = LangSmithTraceSink(self.settings.langsmith_api_key, self.settings.langsmith_project)
        self.graph = self._build().compile()

    def _build(self):
        """Create the LangGraph state graph and its retry/report transitions.

        Returns:
            Uncompiled ``StateGraph`` with planner, ingestion, retrieval,
            extraction, reconciliation, validation, and report nodes.
        """
        graph = StateGraph(dict)
        nodes = {
            "planner": self._planner,
            "ingestion": self._ingestion,
            "retrieval": self._retrieval,
            "extraction": self._extraction,
            "reconciliation": self._reconciliation,
            "validation": self._validation,
            "report": self._report,
        }
        for name, operation in nodes.items():
            graph.add_node(name, self._agent_boundary(name, operation))
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "ingestion")
        graph.add_edge("ingestion", "retrieval")
        graph.add_edge("retrieval", "extraction")
        graph.add_edge("extraction", "reconciliation")
        graph.add_edge("reconciliation", "validation")
        graph.add_conditional_edges("validation", self._route_after_validation, {"retry": "retrieval", "report": "report"})
        graph.add_edge("report", END)
        return graph

    def _agent_boundary(self, node: str, operation):
        """Wrap a node with validated handoff input/output message envelopes.

        Args:
            node: Agent node name used for sender/recipient validation.
            operation: Callable transforming a workflow-state dictionary.

        Returns:
            Callable accepting and returning workflow-state dictionaries. For
            downstream nodes it consumes ``_handoff``; for nonterminal nodes
            it emits a validated next-agent handoff.
        """
        previous = {
            "ingestion": "planner",
            "retrieval": {"ingestion", "validation"},
            "extraction": "retrieval",
            "reconciliation": "extraction",
            "validation": "reconciliation",
            "report": "validation",
        }
        following = {
            "planner": "ingestion",
            "ingestion": "retrieval",
            "retrieval": "extraction",
            "extraction": "reconciliation",
            "reconciliation": "validation",
        }

        def run(data: dict[str, Any]) -> dict[str, Any]:
            """Validate incoming handoff, run the node, and build next handoff."""
            data = dict(data)
            trace = data.get("_trace")
            if node != "planner":
                incoming = data.pop("_handoff", None)
                if incoming is None:
                    raise ValueError(f"missing agent handoff for {node}")
                message = validate_message(
                    incoming,
                    expected_sender=previous[node],
                    expected_recipient=node,
                    expected_run_id=data.get("run_id"),
                )
                handoff = WorkflowHandoffPayload.model_validate(message.payload)
                data = handoff.state.__dict__.copy()
                data["_trace"] = trace
                if handoff.runtime.retry_evidence is not None:
                    data["_retry_evidence"] = handoff.runtime.retry_evidence
                if handoff.runtime.extraction_usage:
                    data["_extraction_usage"] = handoff.runtime.extraction_usage

            result = operation(data)
            recipient = self._route_after_validation(result) if node == "validation" else following.get(node)
            if recipient == "retry":
                recipient = "retrieval"
            if recipient:
                business_state = WorkflowState.model_validate({
                    key: value for key, value in result.items() if not key.startswith("_")
                })
                payload = WorkflowHandoffPayload(
                    state=business_state,
                    runtime=WorkflowRuntimePayload(
                        retry_evidence=result.get("_retry_evidence"),
                        extraction_usage=result.get("_extraction_usage", []),
                    ),
                ).model_dump(mode="python")
                message = make_message(
                    run_id=result["run_id"],
                    task_id=f"{node}:{result.get('retry_count', 0)}",
                    agent=node,
                    recipient=recipient,
                    payload_type="workflow_handoff",
                    payload=payload,
                    state_version=result.get("retry_count", 0),
                )
                result["_handoff"] = message.model_dump(mode="python")
            return result

        return run

    def _route_after_validation(self, data: dict[str, Any]) -> str:
        """Select retrieval retry or report based on populated retry fields."""
        return "retry" if data.get("retry_fields") else "report"

    def invoke(self, state: WorkflowState) -> WorkflowState:
        """Run the graph and return completed or failed workflow state.

        Args:
            state: Validated initial workflow state including mode, goal, and
                requested bid IDs.

        Returns:
            Updated ``WorkflowState`` with plan, evidence, fields/answer,
            diagnostics, status, evaluation-ready data, and trace reference.
            Uncaught graph errors are converted to failed status and an error
            output instead of propagating.
        """
        initial = state.model_dump(mode="python")
        initial["_trace"] = TraceRecorder(run_id=state.run_id)
        try:
            result = self.graph.invoke(initial)
        except Exception as exc:
            state.status = "failed"
            state.diagnostics.append(Diagnostic(code="workflow_failure", message=str(exc), severity="error"))
            state.final_output = {"error": "workflow failed", "reason": str(exc)}
            return state
        result.pop("_trace", None)
        return WorkflowState.model_validate(result)

    @staticmethod
    def _trace(data: dict[str, Any]) -> TraceRecorder:
        """Return the trace recorder stored in internal workflow state."""
        return data["_trace"]

    def _planner(self, data: dict[str, Any]) -> dict[str, Any]:
        """Populate plan and unsupported-work diagnostics from the user goal."""
        trace = self._trace(data)
        plan = trace.run("Planner", data["goal"], lambda: build_plan(data["mode"], data["goal"], data["bid_ids"]))
        data["plan"] = plan
        data["unsupported_work"] = plan.get("unsupported_work", [])
        data["diagnostics"].extend(Diagnostic(code="unsupported_work", message=f"unsupported request: {item}") for item in data["unsupported_work"])
        return data

    def _ingestion(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure requested bids are indexed and report indexing diagnostics."""
        trace = self._trace(data)
        result = trace.run("Ingestion", data["bid_ids"], lambda: trace.run_tool(
            "bid_indexing",
            {"bid_ids": data["bid_ids"]},
            lambda: ensure_index(data["bid_ids"], Path(self.settings.index_path), data.get("submitted_bid_folders")),
            output_summary=lambda value: {
                "indexed": value.get("indexed"),
                "updated": value.get("updated"),
                "diagnostic_count": len(value.get("diagnostics", [])),
            },
        ))
        if result["updated"]:
            self.retrieval.refresh()
        data["diagnostics"].extend(Diagnostic(code="missing_evidence", message=message, severity="error" if data.get("submitted_bid_folders") else "warning") for message in result["diagnostics"])
        vector_index = result.get("vector_index") or {}
        if vector_index.get("failed", 0):
            data["diagnostics"].extend(
                Diagnostic(code="vector_index", message=message)
                for message in vector_index.get("diagnostics", ["automatic Chroma sync failed"])
            )
        return data

    def _retrieval(self, data: dict[str, Any]) -> dict[str, Any]:
        """Retrieve QA evidence or field-group evidence, preserving retry data."""
        if data["mode"] == "qa":
            query = data["goal"]
            query_lower = query.casefold()
            top_k = None if "affidavit" in query_lower else 50 if any(
                term in query_lower
                for term in ("affidavit", "warranty", "warranties", "addendum", "amendment", "deadline", "due date", "bond")
            ) else 10
            trace = self._trace(data)
            result = trace.run("Retrieval", query, lambda: trace.run_tool(
                "retrieval",
                {"query": query, "bid_ids": data["bid_ids"], "top_k": top_k, "filters": data.get("search_filters")},
                lambda: self.retrieval.search(query, data["bid_ids"], top_k=top_k, filters=data.get("search_filters")),
                output_summary=lambda value: {"result_count": len(value.get("results", [])), "diagnostic_count": len(value.get("diagnostics", []))},
            ))
            data["retrieved_evidence"] = result["results"]
            data["diagnostics"].extend(Diagnostic(code="retrieval", message=item) for item in result["diagnostics"])
            return data
        evidence: list[dict[str, Any]] = []
        selected_fields = data.get("retry_fields") or [field for fields in data["plan"]["field_groups"].values() for field in fields]
        queries = [f"{field.replace('_', ' ')} {data['goal']}" for field in selected_fields]
        trace = self._trace(data)
        with ThreadPoolExecutor(max_workers=max(1, len(queries))) as executor:
            results = list(executor.map(
                lambda query: trace.run_tool(
                    "retrieval",
                    {"query": query, "bid_ids": data["bid_ids"], "top_k": None, "filters": data.get("search_filters")},
                    lambda: self.retrieval.search(query, data["bid_ids"], top_k=None, filters=data.get("search_filters")),
                    output_summary=lambda value: {"result_count": len(value.get("results", [])), "diagnostic_count": len(value.get("diagnostics", []))},
                ),
                queries,
            ))
        for query, result in zip(queries, results):
            self._trace(data).event("Retrieval", "end", input_value=query, output_value={"result_count": len(result["results"])})
            evidence.extend(result["results"])
            data["diagnostics"].extend(Diagnostic(code="retrieval", message=item) for item in result["diagnostics"])
        if data.get("retry_fields"):
            data["_retry_evidence"] = _unique_evidence(evidence)
            data["retrieved_evidence"] = _unique_evidence(data["retrieved_evidence"] + evidence)
        else:
            data["retrieved_evidence"] = _unique_evidence(evidence)
        return data

    def _extraction(self, data: dict[str, Any]) -> dict[str, Any]:
        """Synthesize QA output or concurrently extract planned field groups.

        Extraction failures become review-required fields and diagnostics;
        successful calls retain provider token usage in internal runtime state.
        """
        self._trace(data).event("Extraction", "start", input_value={"mode": data["mode"], "evidence_count": len(data["retrieved_evidence"])})
        if data["mode"] == "qa":
            data["final_output"] = synthesize_answer(data["goal"], data["retrieved_evidence"])
            if data["final_output"].get("found") and not data["final_output"].get("disputed") and data["final_output"].get("claims"):
                try:
                    generated = self._trace(data).run_model(
                        "Report Generation",
                        lambda: self.model_provider.generate_report(
                            data["goal"], data["final_output"]["claims"], data["final_output"]["answer"]
                        ),
                        provider=getattr(self.model_provider, "provider_name", type(self.model_provider).__name__),
                        model=getattr(self.model_provider, "model", None),
                    )
                    data["final_output"]["answer"] = generated.values["answer"]
                    data["final_output"]["report_generation"] = generated.usage.model_dump(mode="json")
                except Exception as exc:
                    provider_name = getattr(self.model_provider, "provider_name", type(self.model_provider).__name__)
                    status_code = getattr(exc, "status_code", None)
                    reason = f"HTTP {status_code}" if status_code else type(exc).__name__
                    if provider_name == "ollama" and status_code == 404:
                        reason += "; verify the Ollama /v1 URL and that the configured model is pulled"
                    data["diagnostics"].append(Diagnostic(
                        code="report_generation_fallback",
                        message=f"{provider_name} report generation failed ({reason}); deterministic answer returned",
                        severity="warning",
                    ))
            self._trace(data).event("Extraction", "end", output_value={"found": data["final_output"]["found"], "claim_count": len(data["final_output"]["claims"])})
            return data
        fields = data.get("retry_fields") or [field for values in data["plan"]["field_groups"].values() for field in values]
        selected_evidence = data.pop("_retry_evidence", data["retrieved_evidence"])
        selected = set(fields)
        groups = [
            (group, [field for field in group_fields if field in selected])
            for group, group_fields in data["plan"]["field_groups"].items()
        ]
        groups = [(group, group_fields) for group, group_fields in groups if group_fields]
        group_results: dict[str, tuple[dict[str, ExtractionField], ModelUsage]] = {}
        group_errors: dict[str, list[str]] = {}
        group_fields_by_name = dict(groups)
        selected_group_names = set(group_fields_by_name)
        dependencies = {
            group: set(data["plan"].get("group_dependencies", {}).get(group, []))
            for group, _ in groups
        }
        completed_groups = {
            dependency
            for group_dependencies in dependencies.values()
            for dependency in group_dependencies - selected_group_names
            if data["plan"]["field_groups"].get(dependency)
            and all(
                field in data["draft_fields"]
                and data["draft_fields"][field].status == "supported"
                for field in data["plan"]["field_groups"][dependency]
            )
        }

        def extract_group(group_fields: list[str]) -> tuple[dict[str, ExtractionField], ModelUsage]:
            """Run one dependency-ready group through model and local extraction."""
            provider_result = self._trace(data).run_model(
                "Extraction",
                lambda: self.model_provider.extract_fields(selected_evidence, group_fields),
                provider=getattr(self.model_provider, "provider_name", type(self.model_provider).__name__),
                model=getattr(self.model_provider, "model", None),
            )
            if isinstance(provider_result, ExtractionResult):
                model_values = provider_result.values
                usage = provider_result.usage
            elif isinstance(provider_result, dict):
                model_values = provider_result
                usage = ModelUsage()
            else:
                raise TypeError("model provider returned an unsupported extraction result")
            return extract_fields(selected_evidence, group_fields, model_values, goal=data["goal"]), usage

        pending_groups = dict(groups)
        if groups:
            with ThreadPoolExecutor(max_workers=min(4, len(groups))) as executor:
                while pending_groups:
                    blocked = [
                        group
                        for group in pending_groups
                        if dependencies[group] & group_errors.keys()
                        or any(
                            dependency not in pending_groups and dependency not in completed_groups
                            for dependency in dependencies[group]
                        )
                    ]
                    for group in blocked:
                        group_errors[group] = pending_groups.pop(group)

                    ready = [
                        group
                        for group in pending_groups
                        if dependencies[group] <= completed_groups
                    ]
                    if not ready:
                        for group, group_fields in pending_groups.items():
                            group_errors[group] = group_fields
                        pending_groups.clear()
                        break

                    futures = {
                        executor.submit(extract_group, pending_groups[group]): group
                        for group in ready
                    }
                    for future in as_completed(futures):
                        group = futures[future]
                        try:
                            group_results[group] = future.result()
                            completed_groups.add(group)
                        except Exception:
                            group_errors[group] = pending_groups[group]
                        pending_groups.pop(group)

        updated_fields: dict[str, ExtractionField] = {}
        data["_extraction_usage"] = []
        for group, group_fields in groups:
            if group in group_errors:
                for field in group_errors[group]:
                    updated_fields[field] = ExtractionField(
                        name=field,
                        status="review_required",
                        notes="Extraction group failed",
                    )
                    data["diagnostics"].append(Diagnostic(
                        code="extraction_group_failed",
                        message=f"extraction group '{group}' failed",
                        severity="error",
                        field=field,
                    ))
                continue
            fields_result, usage = group_results[group]
            updated_fields.update(fields_result)
            data["_extraction_usage"].append({"group": group, **usage.model_dump(mode="python")})
        if data.get("retry_fields"):
            data["draft_fields"].update(updated_fields)
        else:
            data["draft_fields"] = updated_fields
        self._trace(data).event("Extraction", "end", output_value={"field_count": len(data["draft_fields"])})
        return data

    def _reconciliation(self, data: dict[str, Any]) -> dict[str, Any]:
        """Apply addendum changes to extraction fields and append change records."""
        self._trace(data).event("Reconciliation", "start", input_value={"mode": data["mode"]})
        if data["mode"] == "extraction":
            selected = {name: data["draft_fields"][name] for name in data["retry_fields"]} if data.get("retry_fields") else data["draft_fields"]
            changes = reconcile_changes(selected, data["retrieved_evidence"])
            data["addendum_changes"] = data["addendum_changes"] + changes if data.get("retry_fields") else changes
        self._trace(data).event("Reconciliation", "end", output_value={"change_count": len(data["addendum_changes"])})
        return data

    def _validation(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate extracted fields, schedule bounded retries, and set run status."""
        self._trace(data).event("Validation", "start", input_value={"mode": data["mode"]})
        if data["mode"] == "extraction":
            results, diagnostics = validate_fields(data["draft_fields"], data["retrieved_evidence"])
            data["validation_results"] = results
            data["diagnostics"].extend(diagnostics)
            rejected = [result.field for result in results if result.retry_eligible and result.field]
            data["retry_fields"] = []
            if rejected and data["retry_count"] < data["max_retries"]:
                data["retry_count"] += 1
                data["retry_fields"] = rejected
                for field in rejected:
                    data["retry_attempts"][field] = data["retry_attempts"].get(field, 0) + 1
                    data["diagnostics"].append(Diagnostic(code="retry_scheduled", message=f"retrying {field}", field=field, retryable=True))
            elif rejected:
                data["diagnostics"].append(Diagnostic(code="retry_exhausted", message="retry budget exhausted", severity="warning", retryable=False))
        if data["mode"] == "qa" and data.get("final_output", {}).get("disputed"):
            data["status"] = "review_required"
        elif data["mode"] == "qa" and not data.get("final_output", {}).get("found"):
            data["status"] = "partial"
        else:
            data["status"] = "partial" if data.get("unsupported_work") or any(field.status != "supported" for field in data["draft_fields"].values()) or any(result.status != "passed" for result in data["validation_results"]) or any(item.severity == "error" for item in data["diagnostics"]) else "completed"
        self._trace(data).event("Validation", "end", output_value={"result_count": len(data["validation_results"])})
        return data

    def _report(self, data: dict[str, Any]) -> dict[str, Any]:
        """Build the public response payload and persist/deliver trace metadata."""
        self._trace(data).event("Report", "start", input_value={"mode": data["mode"]})
        state = WorkflowState.model_validate({key: value for key, value in data.items() if key != "_trace"})
        data["final_output"] = (extraction_response(state) if state.mode == "extraction" else qa_response(state)).output
        data["trace_reference"] = self._trace(data).trace.trace_id
        self._trace(data).event("Report", "end", output_value={"status": data["status"]})
        trace = self._trace(data).trace
        if not self.settings.trace_enabled:
            trace.delivery_status = "disabled"
            trace.local_persistence_status = "disabled"
        elif not self.settings.langsmith_api_key:
            trace.delivery_status = "unconfigured"
        else:
            trace.delivery_status = "failed"
        if self.settings.trace_enabled:
            try:
                remote_id = self.trace_sink.record(trace.model_dump(mode="python"))
                if remote_id:
                    trace.delivery_status = "delivered"
            except Exception:
                trace.delivery_status = "failed"
            try:
                trace_path = Path(self.settings.trace_path)
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                trace_path.write_text(json.dumps(trace.model_dump(mode="python"), indent=2), encoding="utf-8")
            except OSError as exc:
                trace.local_persistence_status = "failed"
                self._trace(data).event("TracePersistence", "end", status="failed", error=type(exc).__name__)
            else:
                trace.local_persistence_status = "persisted"
        data["trace"] = trace.model_dump(mode="python")
        return data


def _unique_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate evidence by nested source record ID, keeping the last item."""
    unique = {}
    for item in items:
        unique[item["record"]["record_id"]] = item
    return list(unique.values())


def _citation_dict(item: dict[str, Any]) -> dict[str, Any]:
    """Serialize ranked evidence source metadata as a citation dictionary."""
    record = item["record"]
    return {"file": record["source_file"], "page": record.get("page_number"), "bid_id": record["bid_id"], "locator": record.get("source_locator", {}), "authority_status": item.get("authority_status"), "superseded_by": item.get("superseded_by")}
