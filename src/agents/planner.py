"""Map user goals to extraction field groups or a QA task plan."""

from __future__ import annotations

import re

from src.field_registry import AGENT_PLANNER_ALIASES

FIELD_GROUPS = {
    "submission": ["submission_deadline", "submission_method", "solicitation_number"],
    "commercial": ["bid_bond", "warranty", "insurance"],
    "compliance": ["affidavits", "mandatory_requirements", "evaluation_criteria"],
    "product": ["model_number"],
}

FIELD_ALIASES = AGENT_PLANNER_ALIASES


def build_plan(mode: str, goal: str, bid_ids: list[str]) -> dict:
    """Create a serializable workflow plan from mode, goal, and bid scope.

    Args:
        mode: ``extraction`` or ``qa``.
        goal: Requested extraction fields or natural-language question.
        bid_ids: Bid identifiers included in the workflow.

    Returns:
        Mapping with mode, goal, bid IDs, selected ``field_groups``,
        ``subtasks``, and ``unsupported_work``. QA creates one question group;
        extraction selects recognized aliases or all groups for broad goals.

    Raises:
        ValueError: If mode is not extraction or QA.
    """
    if mode not in {"extraction", "qa"}:
        raise ValueError("mode must be extraction or qa")
    if mode == "qa":
        return {"mode": mode, "goal": goal, "bid_ids": bid_ids, "field_groups": {"question": [goal]}, "subtasks": ["answer:question"], "unsupported_work": []}
    lowered = goal.lower().strip()
    broad = lowered in {"extract", "extraction", "extract complete bid record", "complete bid record", "all fields"}
    groups = {
        group: [field for field in fields if broad or any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in FIELD_ALIASES[field])]
        for group, fields in FIELD_GROUPS.items()
    }
    groups = {group: fields for group, fields in groups.items() if fields}
    unsupported = []
    if not broad:
        for part in re.split(r"\band\b|,", lowered):
            if part.strip() and not any(re.search(rf"\b{re.escape(alias)}\b", part) for aliases in FIELD_ALIASES.values() for alias in aliases):
                unsupported.append(part.strip())
    return {
        "mode": mode,
        "goal": goal,
        "bid_ids": bid_ids,
        "field_groups": groups,
        "subtasks": [f"retrieve:{field}" for fields in groups.values() for field in fields],
        "unsupported_work": unsupported,
    }
