"""Workflow observation — the 3-audience gate sealed deterministically (ADR-0029 Slice 3).

The Topaz calls are injected, so the GATING LOGIC is testable without a cluster. These prove
the properties Decision 4 requires:

  * a non-participant, non-cleared observer sees a DENY (existence-oracle);
  * a participant sees the declared domain-stage state + their OWN human action;
  * an agent action is clearance-bounded — visible iff you can_view its subject;
  * another party's human action is DENY-BY-DEFAULT and redacted ENTIRELY (not just the actor
    blanked) — its existence must not leak;
  * an `internal` field (observable_state) is never surfaced, even to a fully-cleared participant;
  * deny-by-default is STRUCTURAL — the safe defaults hide agent + other-human steps when a
    driver forgets to inject grants.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_workflow_observation.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.workflow_definition import WorkflowDefinition  # noqa: E402
from agent_fleet.restate_analyst.workflow_observation import (  # noqa: E402
    StepRuntime, WorkflowRuntimeState, project_observation,
)

# A promotion-shaped definition: an agent step, a human-await, a gated publish; the publish's
# status+result are declared INTERNAL, the rest visible.
DEF = WorkflowDefinition.model_validate({
    "id": "promote_answer_artifact",
    "name": "Promote an AnswerArtifact",
    "classification": "DATA_ENGINEERING",
    "participants": [{"role": "initiator"}, {"role": "approver"}],
    "domain_stages": ["awaiting_approval", "publishing", "published"],
    "steps": [
        {"kind": "spo_operation", "id": "analyze", "subject": "mesh#AgentTask", "verb": "mesh:analyzeWithCodeAgent"},
        {"kind": "human_await", "id": "approve", "audience": "promotion:DATA_ENGINEERING"},
        {"kind": "direct_call", "id": "publish", "endpoint": "{ep}", "capability": "mesh:publishArtifact"},
    ],
    "observable_state": {
        "visible": ["domain_stages", "analyze.status", "approve.status"],
        "internal": ["publish.status", "publish.result"],
    },
})


def _runtime() -> WorkflowRuntimeState:
    return WorkflowRuntimeState(
        workflow_id="wf-1",
        current_stage="awaiting_approval",
        steps=[
            StepRuntime(id="analyze", kind="spo_operation", status="done", subject="mesh#AgentTask"),
            StepRuntime(id="approve", kind="human_await", status="suspended", assignee_role="approver"),
            StepRuntime(id="publish", kind="direct_call", status="pending"),
        ],
        participant_bindings={"initiator": "alice@ex", "approver": "bob@ex"},
    )


_ALLOW_ALL = lambda _s: True
_DENY_ALL = lambda _s: False


def _step_ids(proj):
    return {s["id"] for s in proj.steps}


# ---------------------------------------------------------------------------
# Tier 0 — see the workflow at all
# ---------------------------------------------------------------------------

def test_non_participant_uncleared_gets_deny():
    """carol is neither a participant nor classification-cleared -> DENY, nothing leaked."""
    proj = project_observation(DEF, _runtime(), "carol@ex",
                               observer_role=None, can_observe_workflow=False)
    assert proj.visible is False
    assert proj.steps == [] and proj.participants == []
    assert proj.domain_stages == [] and proj.current_stage is None


# ---------------------------------------------------------------------------
# Self-participation
# ---------------------------------------------------------------------------

def test_participant_sees_stages_and_own_human_step():
    """bob (approver) sees the declared domain-stage state and his OWN awaited step."""
    proj = project_observation(DEF, _runtime(), "bob@ex",
                               observer_role="approver", can_observe_workflow=True,
                               can_view_subject=_ALLOW_ALL)
    assert proj.visible is True
    assert proj.domain_stages == ["awaiting_approval", "publishing", "published"]
    assert proj.current_stage == "awaiting_approval"
    approve = next(s for s in proj.steps if s["id"] == "approve")
    assert approve["actor"] == "you"  # self-participation, not another party's identity


# ---------------------------------------------------------------------------
# Agent-actions, clearance-bounded
# ---------------------------------------------------------------------------

def test_agent_step_hidden_when_cannot_view_subject():
    proj = project_observation(DEF, _runtime(), "bob@ex",
                               observer_role="approver", can_observe_workflow=True,
                               can_view_subject=_DENY_ALL)
    assert "analyze" not in _step_ids(proj)
    assert any("analyze" in r and "cannot view" in r for r in proj.redactions)


def test_agent_step_visible_when_can_view_subject():
    proj = project_observation(DEF, _runtime(), "bob@ex",
                               observer_role="approver", can_observe_workflow=True,
                               can_view_subject=_ALLOW_ALL)
    assert "analyze" in _step_ids(proj)


# ---------------------------------------------------------------------------
# Other-humans, restricted (existence-oracle) — the sharpest tier
# ---------------------------------------------------------------------------

def test_other_human_action_denied_by_default_and_redacted_entirely():
    """dave is cleared to observe the workflow but is NOT a participant and has no
    other-observers grant -> bob's human step is redacted ENTIRELY (existence-oracle):
    not in steps, actor never leaked, only a reasons-line records that something was hidden."""
    proj = project_observation(DEF, _runtime(), "dave@ex",
                               observer_role=None, can_observe_workflow=True,
                               can_view_subject=_ALLOW_ALL)  # note: can_observe_others defaults False
    assert "approve" not in _step_ids(proj)                 # the step itself is gone
    assert all("bob@ex" not in r for r in proj.redactions)  # the actor is NOT leaked in the reason
    assert any("approve" in r and "restricted" in r for r in proj.redactions)
    # bob's participant binding is also withheld (existence-oracle on parties)
    assert all(p.get("identity") != "bob@ex" for p in proj.participants)


def test_other_human_action_visible_with_explicit_grant():
    proj = project_observation(DEF, _runtime(), "dave@ex",
                               observer_role=None, can_observe_workflow=True,
                               can_view_subject=_ALLOW_ALL, can_observe_others=True)
    approve = next(s for s in proj.steps if s["id"] == "approve")
    assert approve["actor"] is None or approve["actor"] == "bob@ex"  # revealed under the grant
    assert any(p.get("identity") == "bob@ex" for p in proj.participants)


# ---------------------------------------------------------------------------
# Declared surface — internal fields never surface
# ---------------------------------------------------------------------------

def test_internal_field_never_surfaces_even_to_cleared_participant():
    """publish.status/result are declared internal -> the publish step never appears, even for
    a fully-cleared participant with every grant."""
    proj = project_observation(DEF, _runtime(), "bob@ex",
                               observer_role="approver", can_observe_workflow=True,
                               can_view_subject=_ALLOW_ALL, can_observe_others=True)
    assert "publish" not in _step_ids(proj)
    assert any("publish" in r and "internal" in r for r in proj.redactions)


# ---------------------------------------------------------------------------
# Deny-by-default is STRUCTURAL — a driver that injects nothing fails closed
# ---------------------------------------------------------------------------

def test_defaults_fail_closed():
    """Only can_observe_workflow injected (no can_view, no can_observe_others): the domain
    stages show, but the agent step (subject) AND the other-human step are both hidden."""
    proj = project_observation(DEF, _runtime(), "dave@ex",
                               observer_role=None, can_observe_workflow=True)
    assert proj.visible is True
    assert proj.domain_stages and proj.current_stage == "awaiting_approval"
    assert _step_ids(proj) == set()  # agent step hidden (can_view default deny), human step deny-by-default


def test_unknown_step_kind_fails_closed():
    rt = _runtime()
    rt.steps.append(StepRuntime(id="mystery", kind="weird_kind", status="done"))
    # declare it visible so only the kind-gate can hide it
    d = WorkflowDefinition.model_validate({
        **DEF.model_dump(exclude_none=True),
        "observable_state": {"visible": ["domain_stages", "mystery.status"], "internal": []},
    })
    proj = project_observation(d, rt, "bob@ex",
                               observer_role="approver", can_observe_workflow=True,
                               can_view_subject=_ALLOW_ALL)
    assert "mystery" not in _step_ids(proj)
    assert any("mystery" in r and "fail-closed" in r for r in proj.redactions)
