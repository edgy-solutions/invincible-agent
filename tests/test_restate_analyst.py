"""Engine-A request-model shapes.

SELF-SUFFICIENT IMPORT. This file used to do a bare module-level
``from agent_fleet.restate_analyst.main import ...``, which only worked when some OTHER
test file had already put ``agent_fleet/restate_analyst`` on ``sys.path`` -- engine-a's
``main.py`` does ``from orchestrator.auth import ...`` at line 600, and ``orchestrator`` is
a CHILD of that directory (the container flattens it). Run alone, this file was the last
collection ERROR in the suite: ``ModuleNotFoundError: No module named 'orchestrator'``.

The coupling was already known and filed -- ``test_workflow_start_disabled.py``'s
``engine_a_main`` fixture names THIS file in its docstring. It was filed and never fixed;
that gap is the whole point of the class. Same fixture shape adopted here, including the
reason it inserts INSIDE the fixture rather than at module import: doing it at collection
time mutates ``sys.path`` for every other test in the session, which is the very
ambient-state coupling being worked around.

See docs/principles/a-stub-that-needs-another-test-is-not-a-stub.md
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ra_main():
    """Import engine-a's main, adding the path its own internals assume."""
    ra = str(_ROOT / "agent_fleet" / "restate_analyst")
    if ra not in sys.path:
        sys.path.insert(0, ra)
    return pytest.importorskip(
        "agent_fleet.restate_analyst.main",
        reason="engine-a's main pulls smolagents/baml; source pins still hold",
    )


def test_analyze_request(ra_main):
    req = ra_main.AnalyzeRequest(
        task_description="Analyze data",
        dataset_id="dataset_1"
    )
    assert req.task_description == "Analyze data"
    assert req.dataset_id == "dataset_1"


def test_analyze_request_defaults(ra_main):
    req = ra_main.AnalyzeRequest(
        task_description="Analyze data",
        dataset_id="dataset_1"
    )
    assert req.semantic_context is None


def test_workflow_start_request(ra_main):
    req = ra_main.WorkflowStartRequest(
        workflow_id="wf_1",
        tasks=[]
    )
    assert req.workflow_id == "wf_1"
    assert req.tasks == []


def test_approval_request(ra_main):
    req = ra_main.ApprovalRequest(
        status="APPROVED",
        comments="Looks good"
    )
    assert req.status == "APPROVED"
    assert req.comments == "Looks good"
