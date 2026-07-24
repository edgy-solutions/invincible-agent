"""PCN/PDN grouped-review WORKFLOW sealed — the call-site's two joints made properties.

RIDER 1 — refusal routing (the POLICY-failure sibling of suspend-vs-fail): a grouped decision the
bulk-resolve core REFUSES (unverified row without an explicit override, a row with no disposition, a
blank override reason) must leave the review SUSPENDED and surface why — never resolve the promise,
never fan out. Only an accepted decision wakes the workflow.

RIDER 2 — fan-out partial-failure isolation: the fan-out runs on the workflow's journaled context
(each send durable), and a poisoned item (malformed payload -> engine-o 400) TERMINAL-fails ITS OWN
keyed object without wedging the other N-1.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with pytest-asyncio \
        pytest ../../tests/test_pcn_workflow.py -v
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

import restate  # noqa: E402
from agent_fleet.restate_analyst import pcn_driver, pcn_workflow  # noqa: E402
from agent_fleet.restate_analyst.pcn_dispatch import plan_dispatch  # noqa: E402
from agent_fleet.restate_analyst.workflow_bulk_resolve import (  # noqa: E402
    ItemResolution, PartItem, ReviewBatch,
)

_SUBMIT = pcn_workflow.submit_decision.__wrapped__
_RUN = pcn_workflow.run.__wrapped__


# ---------------------------------------------------------------------------
# Small HTTP stub + a minimal journaling object ctx (poisoned-isolation seal)
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class _MinObjectCtx:
    """One-shot journaling object ctx — enough to run pcn_driver.dispatch to completion or a
    TerminalError. No crash injection (that lives in test_pcn_driver); here we watch isolation."""

    def __init__(self, key, state):
        self._key = key
        self._state = state

    def key(self):
        return self._key

    async def get(self, k):
        return self._state.get(k)

    def set(self, k, v):
        self._state[k] = v

    async def run(self, name, fn):
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        return r


def _dispatch_payload(disposition="dispatchQualification", *, mpn="NSR01L30NXT5G", subject):
    res = ItemResolution(
        mpn=mpn, subject=subject, disposition=disposition,
        idempotency_key=f"IPCN25300X:{mpn}", needs_review=False,
        override_reason=None, proposed_by_ruleset="rules@abc123def456",
    )
    return pcn_driver.plan_to_payload(plan_dispatch(res, notice_fingerprint="IPCN25300X", notice_id="IPCN25300X"))


# ---------------------------------------------------------------------------
# Fake workflow contexts
# ---------------------------------------------------------------------------
class _SharedPromise:
    def __init__(self, rec, name):
        self._rec, self._name = rec, name

    async def resolve(self, value):
        self._rec.append((self._name, value))


class FakeSharedContext:
    """WorkflowSharedContext stand-in: reads server state, records promise resolves (so a test can
    assert the promise was NOT resolved on refusal -> workflow stays suspended)."""

    def __init__(self, state):
        self._state = state
        self.resolved: list = []

    async def get(self, name, **kw):
        return self._state.get(name)

    def promise(self, name, type_hint=None):
        return _SharedPromise(self.resolved, name)


class _WfPromise:
    def __init__(self, value):
        self._value = value

    def value(self):
        async def _a():
            return self._value
        return _a()


class FakeWorkflowContext:
    """WorkflowContext stand-in: journals ctx.run, hands the pre-resolved decision back from the
    promise, and records object_send (the fan-out on the workflow ctx — rider 2 journaled-in-context)."""

    def __init__(self, decision, key="pcn-review-IPCN25300X-qa"):
        self._decision = decision
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
        return _WfPromise(self._decision)

    def object_send(self, tpe, key, arg, idempotency_key=None, **kw):
        self.sends.append({"key": key, "idempotency_key": idempotency_key, "arg": arg})


# ===========================================================================
# RIDER 1 — refusal routing (pure core)
# ===========================================================================
def _batch(*items):
    return ReviewBatch(approver="qa", items=list(items))


def test_evaluate_accepts_a_clean_batch():
    batch = _batch(PartItem(mpn="A", subject="http://internal/components/A",
                            proposed_disposition="dispatchQualification"))
    sub = pcn_workflow.evaluate_submission(batch, {"overrides": {}}, notice_fingerprint="IPCN25300X")
    assert sub.accepted and len(sub.resolutions) == 1


def test_evaluate_refuses_unverified_row_riding_accept_all():
    """An unverified (needs_review) row with NO explicit override cannot ride accept-all — refused."""
    batch = _batch(PartItem(mpn="A", subject="http://internal/components/A",
                            proposed_disposition="dispatchQualification", needs_review=True))
    sub = pcn_workflow.evaluate_submission(batch, {"overrides": {}}, notice_fingerprint="IPCN25300X")
    assert not sub.accepted and not sub.resolutions
    assert "unverified" in sub.reason.lower() or "needs_review" in sub.reason.lower()


def test_evaluate_refuses_row_with_no_disposition():
    batch = _batch(PartItem(mpn="A", subject="http://internal/components/A", proposed_disposition=None))
    sub = pcn_workflow.evaluate_submission(batch, {"overrides": {}}, notice_fingerprint="IPCN25300X")
    assert not sub.accepted and not sub.resolutions
    assert "no" in sub.reason.lower() and "disposition" in sub.reason.lower()


def test_evaluate_refuses_blank_override_reason():
    """capture-why is structural: a blank override reason is a refusal, not a silent accept."""
    batch = _batch(PartItem(mpn="A", subject="http://internal/components/A",
                            proposed_disposition="dispatchQualification"))
    sub = pcn_workflow.evaluate_submission(
        batch, {"overrides": {"A": {"disposition": "archive", "reason": "  "}}},
        notice_fingerprint="IPCN25300X",
    )
    assert not sub.accepted and not sub.resolutions


# ===========================================================================
# RIDER 1 — the durable joint: submit_decision resolves the promise ONLY on accept
# ===========================================================================
@pytest.mark.asyncio
async def test_submit_refusal_leaves_workflow_suspended_no_promise_resolved():
    """The load-bearing seal: a refused decision does NOT resolve the promise (workflow stays
    suspended) and returns still_pending + reason — so NO fan-out can fire."""
    state = {
        "batch_items": [{"mpn": "A", "subject": "http://internal/components/A",
                         "proposed_disposition": "dispatchQualification", "needs_review": True}],
        "approver": "qa", "notice_fingerprint": "IPCN25300X",
    }
    ctx = FakeSharedContext(state)
    out = await _SUBMIT(ctx, {"decision": {"overrides": {}}})
    assert out["accepted"] is False and out["status"] == "still_pending"
    assert out["reason"]
    assert ctx.resolved == [], "a refused decision resolved the promise — workflow would wake and fan out"


@pytest.mark.asyncio
async def test_submit_accept_resolves_promise_once():
    state = {
        "batch_items": [{"mpn": "A", "subject": "http://internal/components/A",
                         "proposed_disposition": "dispatchQualification", "needs_review": False}],
        "approver": "qa", "notice_fingerprint": "IPCN25300X",
    }
    ctx = FakeSharedContext(state)
    out = await _SUBMIT(ctx, {"decision": {"overrides": {}}})
    assert out["accepted"] is True and out["status"] == "accepted"
    assert len(ctx.resolved) == 1, "an accepted decision must resolve the promise exactly once (wake -> fan out)"


# ===========================================================================
# RIDER 1 + fan-out — run(): register -> suspend -> fan out on accept
# ===========================================================================
@pytest.mark.asyncio
async def test_run_registers_task_then_fans_out_on_accept(monkeypatch):
    posts = []
    monkeypatch.setattr(pcn_driver.requests, "post",
                        lambda url, **k: (posts.append((url, k.get("json"))), _Resp(200, {"task_id": "t"}))[1])
    batch_items = [
        {"mpn": f"MPN-{i}", "subject": f"http://internal/components/MPN-{i}",
         "proposed_disposition": "dispatchQualification", "needs_review": False}
        for i in range(2)
    ]
    ctx = FakeWorkflowContext(decision={"overrides": {}})
    out = await _RUN(ctx, {
        "approver": "qa", "audience": "qualification",
        "notice_fingerprint": "IPCN25300X", "notice_id": "IPCN25300X",
        "batch_items": batch_items,
    })
    assert ctx.runs and ctx.runs[0] == "register_grouped_task", "grouped task not registered before suspend"
    assert out["status"] == "DISPATCHED" and out["count"] == 2
    assert [s["key"] for s in ctx.sends] == ["IPCN25300X:MPN-0", "IPCN25300X:MPN-1"]
    assert [s["idempotency_key"] for s in ctx.sends] == ["IPCN25300X:MPN-0", "IPCN25300X:MPN-1"]
    # The grouped-task register (the FIRST post) MUST carry this workflow's own key as workflow_id —
    # else cortex-bff's /act has nothing to address submit_decision on and the review dangles.
    grouped_register = posts[0][1]
    assert grouped_register["kind"] == "pcn_grouped_review"
    assert grouped_register["workflow_id"] == ctx.key() == "pcn-review-IPCN25300X-qa", \
        "grouped-review register dropped workflow_id — /act could not resume the review"


# ===========================================================================
# RIDER 2 — a poisoned item terminal-fails only itself
# ===========================================================================
@pytest.mark.asyncio
async def test_poisoned_item_terminal_fails_only_itself(monkeypatch):
    """One malformed item (engine-o 400 on its state write) TERMINAL-fails its OWN keyed object; a
    healthy item on its own key completes untouched. Per-item isolation is a property, not a hope."""
    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/internal/human_tasks/register"):
            return _Resp(200, {"task_id": json["task_id"]})
        if url.endswith("/write_pcn_disposition_state"):
            status = 400 if json["subject_iri"].endswith("POISON") else 200
            return _Resp(status, {"ok": status == 200})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(pcn_driver.requests, "post", _post)
    _DISPATCH = pcn_driver.dispatch.__wrapped__

    healthy_state: dict = {}
    healthy = await _DISPATCH(_MinObjectCtx("IPCN25300X:GOOD", healthy_state),
                              _dispatch_payload(mpn="GOOD", subject="http://internal/components/GOOD"))
    assert healthy["state_written"] and healthy_state.get("dispatched") is not None

    poison_state: dict = {}
    with pytest.raises(restate.TerminalError):
        await _DISPATCH(_MinObjectCtx("IPCN25300X:POISON", poison_state),
                        _dispatch_payload(mpn="POISON", subject="http://internal/components/POISON"))
    # Isolation: the poisoned object never marked complete; the healthy object is entirely unaffected.
    assert poison_state.get("dispatched") is None
    assert healthy_state.get("dispatched") is not None
