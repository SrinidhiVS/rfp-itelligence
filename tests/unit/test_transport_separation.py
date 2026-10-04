from src.api import app as app_module
from src.agents.graph import AnalysisWorkflow


def test_transport_uses_callable_workflow_boundary():
    assert isinstance(app_module.workflow, AnalysisWorkflow)
    assert callable(app_module.workflow.invoke)
