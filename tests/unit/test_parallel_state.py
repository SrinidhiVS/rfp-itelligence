from src.agents.state import ExtractionField, WorkflowState


def test_parallel_field_groups_have_independent_keys():
    state = WorkflowState(mode="extraction", goal="extract", draft_fields={
        "deadline": ExtractionField(name="deadline"),
        "warranty": ExtractionField(name="warranty"),
    })
    state.draft_fields["deadline"].notes = "updated"
    assert state.draft_fields["warranty"].notes == ""
