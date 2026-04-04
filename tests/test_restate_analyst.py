import pytest
from agent_fleet.restate_analyst.main import AnalyzeRequest, WorkflowStartRequest, ApprovalRequest

def test_analyze_request():
    req = AnalyzeRequest(
        task_description="Analyze data",
        dataset_id="dataset_1"
    )
    assert req.task_description == "Analyze data"
    assert req.dataset_id == "dataset_1"

def test_analyze_request_defaults():
    req = AnalyzeRequest(
        task_description="Analyze data",
        dataset_id="dataset_1"
    )
    assert req.semantic_context is None

def test_workflow_start_request():
    req = WorkflowStartRequest(
        workflow_id="wf_1",
        tasks=[]
    )
    assert req.workflow_id == "wf_1"
    assert req.tasks == []

def test_approval_request():
    req = ApprovalRequest(
        status="APPROVED",
        comments="Looks good"
    )
    assert req.status == "APPROVED"
    assert req.comments == "Looks good"
