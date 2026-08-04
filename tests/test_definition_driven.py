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


_TRIGGER = {
    "authz_id": _SERVICE_ID,
    "compartment": "SUSTAINMENT",
    "dispatch_endpoint": "http://engine-o/dispatch",
    "notice_id": "IPCN25300X",
}


# ===========================================================================
# The pair differs by exactly one step, and both are the SAME runner
# ===========================================================================
def test_the_two_definitions_differ_by_exactly_the_human_step():
    supervised = get_workflow_definition("grouped_review")
    autonomous = get_workflow_definition("autonomous_review")

    assert [s.kind for s in supervised.steps] == ["human_await"]
    assert [s.kind for s in autonomous.steps] == ["direct_call"]
    assert not [s for s in autonomous.steps if s.kind == "human_await"], (
        "the autonomous path grew a human_await — it is no longer the unsupervised path"
    )
    # `awaiting_review` is the supervised path's distinguishing stage; nothing waits here.
    assert "awaiting_review" in supervised.domain_stages
    assert "awaiting_review" not in autonomous.domain_stages


def test_every_definition_is_executable_by_the_one_runner():
    """No definition may require a step kind the single executor does not implement — that
    would be a class-driven runner with extra steps."""
    implemented = {"human_await", "spo_operation", "direct_call"}
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
    assert [s.capability for s in autonomous.steps if s.kind == "direct_call"] == [
        "mesh:dispatchDispositions"
    ]
    supervised = get_workflow_definition("grouped_review")
    assert not [s for s in supervised.steps if s.kind == "direct_call"], (
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
    calls: list = []
    monkeypatch.setattr(requests, "post",
                        lambda url, **k: (calls.append(url), _Resp(200, {"ok": True}))[1])
    wf = get_workflow_definition("autonomous_review")

    out = await main._run_definition(_Ctx(), "autonomous-IPCN25300X", wf.model_dump(), _TRIGGER)
    assert out["status"] == "COMPLETED"
    assert calls, "granted identity was allowed but nothing was dispatched"

    calls.clear()
    other = {**_TRIGGER, "authz_id": "svc:some-other-pipeline"}
    with pytest.raises(restate.exceptions.TerminalError):
        await main._run_definition(_Ctx(), "autonomous-IPCN25300X", wf.model_dump(), other)
    assert calls == [], "a non-granted identity reached the endpoint — the gate does not discriminate"
