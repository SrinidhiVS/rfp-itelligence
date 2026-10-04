import pytest

from src.agents.planner import FIELD_ALIASES
from src.agents.planner import build_plan
from src.field_registry import AGENT_FIELD_ALIASES
from src.field_registry import AGENT_PLANNER_ALIASES


def test_planner_creates_field_groups():
    plan = build_plan("extraction", "extract", ["Bid1"])
    assert "submission" in plan["field_groups"]


def test_planner_rejects_unknown_mode():
    with pytest.raises(ValueError):
        build_plan("other", "goal", ["Bid1"])


def test_planner_selects_only_requested_supported_fields():
    deadline = build_plan("extraction", "submission deadline and solicitation number", ["Bid1"])
    assert deadline["field_groups"] == {"submission": ["submission_deadline", "solicitation_number"]}
    compliance = build_plan("extraction", "check affidavits and evaluation criteria", ["Bid1"])
    assert compliance["field_groups"] == {"compliance": ["affidavits", "evaluation_criteria"]}
    assert compliance["subtasks"] != deadline["subtasks"]
    assert build_plan("extraction", "extract complete bid record", ["Bid1"])["field_groups"]
    unsupported = build_plan("extraction", "calculate carbon emissions", ["Bid1"])
    assert unsupported["field_groups"] == {}
    assert unsupported["unsupported_work"]
    question = build_plan("qa", "When is the deadline?", ["Bid1"])
    assert question["field_groups"] == {"question": ["When is the deadline?"]}


def test_planner_selects_model_number_field():
    plan = build_plan("extraction", "Extract the model number", ["Bid2"])
    assert plan["field_groups"] == {"product": ["model_number"]}


def test_planner_aliases_are_shared_with_the_field_registry():
    assert FIELD_ALIASES == AGENT_PLANNER_ALIASES


def test_planner_recognizes_agent_aliases_not_in_its_old_term_list():
    plan = build_plan("extraction", "submit by and certificate of insurance", ["Bid1"])

    assert plan["field_groups"] == {
        "submission": ["submission_deadline"],
        "commercial": ["insurance"],
    }
    assert not plan["unsupported_work"]
