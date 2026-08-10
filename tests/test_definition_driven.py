"""DEFINITION-DRIVEN SEAL (M3.2 build 4/5) — the funded acceptance, made checkable.

The claim M3.2 is funded to prove: **the runner is definition-driven, not class-driven.**
Two git-asserted YAMLs that differ by ONE step run on the SAME ``_run_definition`` with the
same step-kind executor and zero workflow-specific Python. A claim like that is worth
exactly as much as the thing that would go red if it stopped being true.

The pair:
  * ``grouped_review``    — supervised. A grouped ``human_await`` gated by Topaz ``can_act``
    on the audience; the fan-out is that authorized decision's mechanical consequence.
  * ``autonomous_review`` — the same process with the decision ABSENT. No human gate exists,
    so ``can_invoke(initiator, mesh:dispatchDispositions)`` is the ONLY gate.

That asymmetry is deliberate and is asserted here, because "both are gated" is true while
"gated the same way" is false, and a seal that blurred them would license adding a redundant
capability check to the supervised path — which strands approved work at a 403.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import main  # noqa: E402
import restate  # noqa: E402
import spo_step_executor as _flat_executor  # noqa: E402  — the CONTAINER-path module object
from agent_fleet.restate_analyst import spo_step_executor as _pkg_executor  # noqa: E402
from agent_fleet.restate_analyst.workflow_definition import (  # noqa: E402
    get_workflow_definition, load_all_workflows,
)


def _stub_can_invoke(monkeypatch, fn) -> None:
    """Patch the gate on BOTH module objects.

    ``_run_definition`` does the flatten-the-dir import dance, so ``spo_step_executor`` and
    ``agent_fleet.restate_analyst.spo_step_executor`` are DISTINCT modules and patching one
    leaves the other live. That is not a detail: patching only the package copy let the DENY
    arm below pass while the stub was never consulted — it denied because the real Topaz
    check failed, so a test that would have passed against a gate stuck permanently shut
    reported green. The ALLOW arm is what exposed it. A deny-only assertion cannot tell a
    working gate from a broken one; it needs the positive control beside it.
    """
    for mod in (_flat_executor, _pkg_executor):
        monkeypatch.setattr(mod, "check_can_invoke", fn)

_WORKFLOWS = _REPO / "policy" / "workflows"
_SERVICE_ID = "svc:disposition-pipeline"


class _Resp:
    def __init__(self, code=200, body=None):
        self.status_code, self._body = code, body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _Ctx:
    """Minimal WorkflowContext: journals ctx.run, records sends, never suspends (the
    autonomous path has nothing to suspend on — which is the point)."""

    def __init__(self, key="autonomous-IPCN25300X"):
        self._key = key
        self.state: dict = {}
        self.runs: list = []
        self.sends: list = []
        self.escalations: list = []

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        self.runs.append(name)
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        return r

    def promise(self, name, type_hint=None):
        raise AssertionError(
            f"the autonomous path suspended on promise {name!r} — it has no human_await, "
            "so a suspend here means the wrong definition ran"
        )

    def object_send(self, tpe, key, arg, idempotency_key=None, **kw):
        self.sends.append(key)

    def workflow_send(self, tpe, key, arg, **kw):
        """ESCALATION's observable. Recorded separately from `sends` because the discriminating
        claim is that a refused notice dispatches NOTHING and escalates instead — collapsing both
        into one list would let a dispatch masquerade as an escalation."""
        self.escalations.append({"key": key, "arg": arg})


# A CLEAN batch: every row cleanly proposed, so the autonomous path resolves and fans out.
# `dispatch_endpoint` is gone — the step no longer takes one, which is the point of the rename.
_CLEAN_ITEM = {"mpn": "NSR01L30NXT5G", "relevance": 1.0,
               "subject": "http://internal/components/NSR01L30NXT5G",
               "proposed_disposition": "dispatchQualification", "needs_review": False,
               "proposed_by_ruleset": "rules@abc"}
# One UNVERIFIED row — `needs_review` with no override. resolve_batch refuses the WHOLE batch on it.
_DIRTY_ITEM = {**_CLEAN_ITEM, "mpn": "MPN-UNVERIFIED", "needs_review": True}

_TRIGGER = {
    "authz_id": _SERVICE_ID,
    "approver": _SERVICE_ID,
    "compartment": "SUSTAINMENT",
    "notice_id": "IPCN25300X",
    "notice_fingerprint": "IPCN25300X",
    "request_key": "epoch|abc123-sustainment/inbound/x/review.json",
    "trust_table_ref": "trust@testref",
    "batch_items": [_CLEAN_ITEM],
}


# ===========================================================================
# The DEPLOY seam — caught pre-roll, not after breaking sandbox
# ===========================================================================
def test_registry_resolves_under_the_FLATTENED_container_layout():
    """The image flattens the service dir into /app, so this module ships as
    /app/workflow_definition.py — which has exactly TWO parents. The original
    `parents[2]` raised IndexError there, crashing BEFORE the loud, specific
    WorkflowDefinitionError could be raised: an honest error path that was
    unreachable in the only environment needing it.

    Asserted on the PURE candidate function, so it needs no container to run."""
    from agent_fleet.restate_analyst.workflow_definition import candidate_definition_dirs

    # Asserted as a RELATIONSHIP, not a literal path: on Windows `Path("/app/x").resolve()`
    # yields `C:/app/x`, so a literal "/app/policy/workflows" comparison would fail on the
    # host while passing in the container — a test whose verdict depends on where it runs.
    flat = candidate_definition_dirs(Path("/app/workflow_definition.py"))
    assert flat, "no candidates for the flattened layout — parents[2] would have raised"
    assert flat[-1].parts[-3:] == ("app", "policy", "workflows"), flat
    assert flat[-1].parent.parent.name == "app", flat

    repo = candidate_definition_dirs(_RA / "workflow_definition.py")
    assert repo[0] == _REPO / "policy" / "workflows", repo


def test_registry_witness_reports_the_INVENTORY_not_a_count():
    """Step 7's witness, as an assertion. The roll's claim is that the image carries
    the definitions the gate tested, BY NAME — 'loaded 2' passes over the wrong two as
    happily as the right two."""
    from agent_fleet.restate_analyst.workflow_definition import describe_registry

    w = describe_registry()
    assert w["exists"] is True, w
    assert "grouped_review" in w["ids"], w
    assert "autonomous_review" in w["ids"], w


# ===========================================================================
# The pair differs by exactly one step, and both are the SAME runner
# ===========================================================================
def test_the_two_definitions_differ_by_exactly_the_human_step():
    supervised = get_workflow_definition("grouped_review")
    autonomous = get_workflow_definition("autonomous_review")

    assert [s.kind for s in supervised.steps] == ["human_await"]
    # RENAMED 2026-08-09 `direct_call` -> `dispatch_fanout`. The CLAIM is unchanged — the two
    # definitions differ by exactly one step — only the autonomous step now has an honest name.
    # It never made a generic HTTP call; it proved a capability gate, and the false generality is
    # what let `{dispatch_endpoint}` sit unbound for months.
    assert [s.kind for s in autonomous.steps] == ["dispatch_fanout"]
    assert not [s for s in autonomous.steps if s.kind == "human_await"], (
        "the autonomous path grew a human_await — it is no longer the unsupervised path"
    )
    # `awaiting_review` is the supervised path's distinguishing stage; nothing waits here.
    assert "awaiting_review" in supervised.domain_stages
    assert "awaiting_review" not in autonomous.domain_stages


def test_every_definition_is_executable_by_the_one_runner():
    """No definition may require a step kind the single executor does not implement — that
    would be a class-driven runner with extra steps."""
    implemented = {"human_await", "spo_operation", "direct_call", "dispatch_fanout"}
    for wf_id, wf in load_all_workflows(_WORKFLOWS).items():
        for step in wf.steps:
            assert step.kind in implemented, f"{wf_id}/{step.id}: unrunnable kind {step.kind!r}"


# ===========================================================================
# The gate asymmetry — the reason the capability lives on ONE of the two
# ===========================================================================
def test_capability_gate_lives_on_the_unsupervised_path_only():
    """Workflow 2 declares the capability; workflow 1 must NOT. On the supervised path the
    grouped human_await IS the gate (can_act on the audience), and adding a second gate to
    the send produces an approved review whose dispatch 403s — a human decision the system
    accepted and won't execute."""
    autonomous = get_workflow_definition("autonomous_review")
    assert [s.capability for s in autonomous.steps if s.kind == "dispatch_fanout"] == [
        "mesh:dispatchDispositions"
    ]
    supervised = get_workflow_definition("grouped_review")
    assert not [s for s in supervised.steps if s.kind in ("direct_call", "dispatch_fanout")], (
        "the supervised path grew a capability-gated send — double-gating strands approved work"
    )


@pytest.mark.asyncio
async def test_autonomous_dispatch_denies_without_the_grant(monkeypatch):
    """PENDING-DENY IS THE HONEST STATE until the grant lands with the trust-table promotion.
    A denial must FAIL-AND-RELEASE (terminal), never park — a parked unsupervised workflow is
    an effect waiting to happen on a permission that was refused."""
    _stub_can_invoke(monkeypatch, lambda cap, caller, **k: False)
    posted: list = []
    monkeypatch.setattr(requests, "post", lambda url, **k: (posted.append(url), _Resp())[1])

    wf = get_workflow_definition("autonomous_review")
    with pytest.raises(restate.exceptions.TerminalError) as exc:
        await main._run_definition(_Ctx(), "autonomous-IPCN25300X", wf.model_dump(), _TRIGGER)
    assert "can_invoke" in str(exc.value) or "not authorized" in str(exc.value)
    assert posted == [], "the endpoint was called despite a denied capability — gate ran too late"


@pytest.mark.asyncio
async def test_autonomous_dispatch_allows_for_the_granted_identity_only(monkeypatch):
    """THE DISCRIMINATING PAIR, which is what the morning must witness live rather than a lone
    green: with the grant seeded, THIS initiator's can_invoke flips to allow while any OTHER
    caller stays denied. A gate that allows everyone answers just as cheerfully as one that
    works — the ALLOW arm alone proves only that something responded."""
    _stub_can_invoke(
        monkeypatch,
        lambda cap, caller, **k: caller == _SERVICE_ID and cap == "mesh:dispatchDispositions",
    )
    wf = get_workflow_definition("autonomous_review")

    # OBSERVES THE FAN-OUT, not an HTTP post. Since the rename the step dispatches the review's own
    # batch through `fan_out_dispatch` -> `ctx.object_send`, so the old `requests.post` observable
    # would now be empty on BOTH arms — a discriminating pair that had stopped discriminating.
    granted = _Ctx()
    out = await main._run_definition(granted, "autonomous-IPCN25300X", wf.model_dump(), _TRIGGER)
    assert out["status"] == "COMPLETED"
    assert granted.sends == ["IPCN25300X:NSR01L30NXT5G"], (
        f"granted identity was allowed but the per-item fan-out did not fire: {granted.sends}")
    assert granted.escalations == [], "a clean notice must not escalate"

    denied = _Ctx()
    other = {**_TRIGGER, "authz_id": "svc:some-other-pipeline"}
    with pytest.raises(restate.exceptions.TerminalError):
        await main._run_definition(denied, "autonomous-IPCN25300X", wf.model_dump(), other)
    assert denied.sends == [], "a non-granted identity dispatched — the gate does not discriminate"
    assert denied.escalations == [], (
        "a DENIED caller must not escalate either — a denial is not a refusal, and turning one into "
        "a human review would file work for an authz failure")

@pytest.mark.asyncio
async def test_a_DIRTY_notice_escalates_WHOLE_and_dispatches_NOTHING(monkeypatch):
    """THE ESCALATION MECHANISM'S OWN DISCRIMINATING PAIR.

    Same definition, same granted identity, same everything — one row differs. A `needs_review` row
    with no override makes `resolve_batch` refuse, and the refusal is at NOTICE grain: the clean row
    sitting beside it is NOT dispatched. That is what "escalated whole" means, and it is the property
    a per-row implementation would silently violate while still looking like it escalated.

    Zero-compensation is asserted here too: `sends == []` means nothing was dispatched before the
    refusal, so the escalation has no partial effects to unwind.
    """
    _stub_can_invoke(monkeypatch, lambda cap, caller, **k: caller == _SERVICE_ID)
    wf = get_workflow_definition("autonomous_review")
    ctx = _Ctx()
    dirty = {**_TRIGGER, "batch_items": [_CLEAN_ITEM, _DIRTY_ITEM]}

    out = await main._run_definition(ctx, "autonomous-IPCN25300X", wf.model_dump(), dirty)

    assert ctx.sends == [], (
        f"a refused notice dispatched {ctx.sends} — the clean row rode along, so the grain is the "
        f"ROW not the NOTICE and a human will review a batch whose effects have already started")
    assert len(ctx.escalations) == 1, f"expected exactly one escalation, got {ctx.escalations}"
    esc = ctx.escalations[0]
    assert esc["arg"]["admitted_by"] == "escalation", (
        "the escalated review must say policy REFUSED, not repeat the rung that admitted it")
    assert "MPN-UNVERIFIED" in esc["arg"]["escalation_reason"], (
        "the record must name the row that refused — 'a check failed' sends a reviewer hunting")
    assert esc["arg"]["batch_items"] == dirty["batch_items"], (
        "the human must review the SAME batch that refused; re-composing could yield a different "
        "one and the reviewer would be judging something the pipeline never saw")
    assert out["status"] == "COMPLETED", (
        "escalation is an OUTCOME, not a failure — the autonomous workflow did its job by refusing")


@pytest.mark.asyncio
async def test_the_escalated_start_uses_a_NOVEL_key(monkeypatch):
    """THE LEG-3 LESSON AS A STANDING ASSERTION. Workflow 1 and workflow 2 take the SAME trigger, so
    an escalation re-sent under the SAME key collides with the very run that refused it — Restate
    attaches, returns the autonomous result, and the notice is dropped with nothing red."""
    _stub_can_invoke(monkeypatch, lambda cap, caller, **k: caller == _SERVICE_ID)
    wf = get_workflow_definition("autonomous_review")
    ctx = _Ctx()
    dirty = {**_TRIGGER, "batch_items": [_DIRTY_ITEM]}
    await main._run_definition(ctx, "autonomous-IPCN25300X", wf.model_dump(), dirty)

    esc = ctx.escalations[0]
    assert esc["key"] != "autonomous-IPCN25300X", "the escalation reused the refusing run's key"
    assert esc["arg"]["request_key"] != _TRIGGER["request_key"], (
        "the escalation carries the ORIGINAL request_key — the BFF keys ingress idempotency on "
        "(request_key, approver), so this would be swallowed by the admission that refused it")
    assert "autonomous-IPCN25300X" in esc["arg"]["escalated_from_workflow"], (
        "the escalation must point BACK at the refusing run, or the chain is lost")
