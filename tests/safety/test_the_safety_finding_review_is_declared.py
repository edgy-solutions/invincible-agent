"""ADR-0063 section 2 -- the `safety_finding_review` declarations, through the real loaders.

WHAT THIS DRIVES. The real workflow loader on `policy/workflows/safety_finding_review.yaml`, the
real task-kind composer on the structural seed plus the sample overlay, and the real
`task_grants.yaml` / `groups.yaml` / `users.yaml` through `validate_policy`.

WHAT IT PINS, written here rather than read from the files (a seal that reads its expectation
from its subject asserts only that the file parses):
  * the three outcomes, in order: confirmed, dismissed, new_hazard -- and NO `accepted`, which in
    `risk_acceptance_*` means residual risk accepted;
  * `dismissed` requires a reason;
  * the audience string, identical in the workflow step and the grant key;
  * the workflow's task kind is the overlay row's kind, and its stages are the ruled three;
  * the grant names a group that exists and has members (else the task routes to nobody).

The workflow is AUTHORED, NOT TRIGGERED: nothing here asserts it runs.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_POLICY = _REPO / "policy"
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_REPO), str(_POLICY / "sync")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_AUDIENCE = "safety_finding_review:SUSTAINMENT"
_KIND = "safety_finding_review"
_OUTCOMES = ["confirmed", "dismissed", "new_hazard"]


def _workflow():
    from agent_fleet.restate_analyst.workflow_definition import load_workflow_definition

    return load_workflow_definition(_POLICY / "workflows" / "safety_finding_review.yaml")


def _kind_row():
    compose = pytest.importorskip(
        "iagent_mesh.task_kinds",
        reason="iagent-mesh SDK not installed -- this seal is VOID, not green, without it",
    ).compose
    rows = compose(_POLICY / "task_kinds", [str(_POLICY / "overlays" / "sample" / "task_kinds")])
    return {str(r.kind): r for r in rows}[_KIND]


def test_the_workflow_loads_with_one_step_and_the_ruled_stages():
    wf = _workflow()
    assert wf.id == "safety_finding_review"
    assert list(wf.domain_stages) == ["received", "review_pending", "disposed"]
    assert len(wf.steps) == 1, [s.id for s in wf.steps]


def test_the_step_names_the_audience_and_the_overlay_kind():
    step = _workflow().steps[0]
    assert step.audience == _AUDIENCE
    assert step.task_kind == _KIND


def test_the_overlay_row_carries_the_three_outcomes_and_no_accepted():
    row = _kind_row()
    assert list(row.accepts) == _OUTCOMES
    assert "accepted" not in row.accepts, "`accepted` means residual risk accepted; this task has none"
    assert row.renders_as.archetype == "APPROVAL_TASK"
    assert row.renders_as.badge == "FINDING"


def test_dismissed_requires_a_reason():
    row = _kind_row()
    assert "dismissed" in list(row.reason_required)
    assert "confirmed" not in list(row.reason_required)


def test_the_grant_row_is_keyed_by_the_audience_and_names_a_populated_group():
    import task_grant_sync as tgs
    from validate_policy import unusable_group_audiences

    load = lambda n: yaml.safe_load((_POLICY / n).read_text(encoding="utf-8"))  # noqa: E731
    audiences, errors = tgs.load_audiences(load("task_grants.yaml"))
    assert errors == [], errors
    row = {a.key: a for a in audiences}.get(_AUDIENCE)
    assert row is not None, "no grant row for the audience: the task would route to nobody"
    assert row.grant_to_groups, "the grant row names no group"
    assert row.granted_by and row.reason
    bad = unusable_group_audiences([row], load("groups.yaml")["groups"], load("users.yaml")["users"])
    assert not bad, bad
