"""PCN/PDN grouped-review WORKFLOW sealed — the call-site's two joints made properties.

RIDER 1 — refusal routing (the POLICY-failure sibling of suspend-vs-fail): a grouped decision the
bulk-resolve core REFUSES (unverified row without an explicit override, a row with no disposition, a
blank override reason) must leave the review SUSPENDED and surface why — never resolve the promise,
never fan out. Only an accepted decision wakes the workflow.

RIDER 2 — fan-out partial-failure isolation: the fan-out runs on the workflow's journaled context
(each send durable), and a poisoned item (malformed payload -> engine-o 400) TERMINAL-fails ITS OWN
keyed object without wedging the other N-1.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with pytest-asyncio \
        pytest ../../tests/test_grouped_review_workflow.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import restate  # noqa: E402
from agent_fleet.restate_analyst import dispatch_driver, grouped_review_workflow  # noqa: E402
from agent_fleet.restate_analyst.dispatch_plan import plan_dispatch  # noqa: E402
from agent_fleet.restate_analyst.workflow_bulk_resolve import (  # noqa: E402
    ItemResolution, PartItem, ReviewBatch,
)

_SUBMIT = grouped_review_workflow.submit_decision.__wrapped__
_RUN = grouped_review_workflow.run.__wrapped__
_GET_BATCH = grouped_review_workflow.get_batch.__wrapped__


@pytest.fixture(autouse=True)
def _stub_service_mint(monkeypatch):
    """Task registration MINTS AT USE (2026-08-04) — see
    ``docs/plans/2026-08-04-notice-a-dispatch-failure.md``. Stub the mint rather than set fake env:
    fake env would drive a REAL client-credentials POST at a nonexistent Keycloak and turn these unit
    tests into network tests. Same fixture as tests/test_dispatch_driver.py, deliberately duplicated
    per-suite because it is TEST SCAFFOLDING, not shared meaning.

    PATCHES BOTH MODULE IDENTITIES. ``sys.path`` carries the repo root AND ``agent_fleet/restate_analyst``
    (the container flattens that dir), so ``dispatch_driver`` and
    ``agent_fleet.restate_analyst.dispatch_driver`` are TWO DISTINCT module objects with separate
    globals. Patching one leaves the other live — which is how this fixture silently failed on first
    write. Any monkeypatch against a flatten-dance module must name both."""
    stub = lambda **_: "svc-token-stub"  # noqa: E731
    # The SOURCE modules are patched too, not just the already-bound consumers: main.py imports
    # dispatch_driver LAZILY (inside _run_definition), so that module object does not exist when this
    # fixture runs and would bind the REAL mint mid-test. Patching the source makes the late import
    # pick up the stub.
    for _name in ("agent_fleet.utils.service_identity", "utils.service_identity",
                  "dispatch_driver", "agent_fleet.restate_analyst.dispatch_driver"):
        _mod = sys.modules.get(_name)
        if _mod is not None:
            monkeypatch.setattr(_mod, "mint_service_token", stub, raising=False)


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
    """One-shot journaling object ctx — enough to run dispatch_driver.dispatch to completion or a
    TerminalError. No crash injection (that lives in test_dispatch_driver); here we watch isolation."""

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
    return dispatch_driver.plan_to_payload(plan_dispatch(res, notice_fingerprint="IPCN25300X", notice_id="IPCN25300X"))


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
    sub = grouped_review_workflow.evaluate_submission(batch, {"overrides": {}}, notice_fingerprint="IPCN25300X")
    assert sub.accepted and len(sub.resolutions) == 1


def test_evaluate_refuses_unverified_row_riding_accept_all():
    """An unverified (needs_review) row with NO explicit override cannot ride accept-all — refused."""
    batch = _batch(PartItem(mpn="A", subject="http://internal/components/A",
                            proposed_disposition="dispatchQualification", needs_review=True))
    sub = grouped_review_workflow.evaluate_submission(batch, {"overrides": {}}, notice_fingerprint="IPCN25300X")
    assert not sub.accepted and not sub.resolutions
    assert "unverified" in sub.reason.lower() or "needs_review" in sub.reason.lower()


def test_evaluate_refuses_row_with_no_disposition():
    batch = _batch(PartItem(mpn="A", subject="http://internal/components/A", proposed_disposition=None))
    sub = grouped_review_workflow.evaluate_submission(batch, {"overrides": {}}, notice_fingerprint="IPCN25300X")
    assert not sub.accepted and not sub.resolutions
    assert "no" in sub.reason.lower() and "disposition" in sub.reason.lower()


def test_evaluate_refuses_blank_override_reason():
    """capture-why is structural: a blank override reason is a refusal, not a silent accept."""
    batch = _batch(PartItem(mpn="A", subject="http://internal/components/A",
                            proposed_disposition="dispatchQualification"))
    sub = grouped_review_workflow.evaluate_submission(
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


@pytest.mark.asyncio
async def test_get_batch_serves_only_the_authored_batch():
    """Rider 1 (two-object at birth): the batch-read serves EXACTLY the per-approver-authored items +
    the notice labels, and NOTHING else from workflow state. A decoy field in state must not leak — a
    batch-read that echoed other state would be the existence oracle Slice 3 closed. Safe by
    construction (the state IS the filtered batch), asserted anyway."""
    authored = [
        {"mpn": "A", "subject": "http://internal/components/A",
         "proposed_disposition": "dispatchQualification", "needs_review": False},
        {"mpn": "B", "subject": None,
         "proposed_disposition": "dispatchQualification", "needs_review": True},
    ]
    state = {
        "batch_items": authored, "approver": "alice@example.com",
        "notice_fingerprint": "IPCN25300X", "notice_id": "IPCN25300X", "doc_type": "PCN",
        "extraction_warnings": ["PARTS MAY BE MISSING: 2/5 table crops failed"],
        "audit_withheld": [{"mpn": "SECRET-OTHER-APPROVER"}],  # decoy — MUST NOT leak
    }
    out = await _GET_BATCH(FakeSharedContext(state))
    assert out["items"] == authored, "batch-read must serve exactly the authored per-approver items"
    assert out["notice_type"] == "PCN" and out["notice_id"] == "IPCN25300X"
    assert out["approver"] == "alice@example.com"
    # `extraction_warnings` WIDENS this contract deliberately (2026-07-29). It is doc-level
    # EXTRACTION-QUALITY metadata ("a vision crop timed out, parts may be missing") — not
    # per-approver residue and not document content, so every reviewer entitled to the batch
    # is entitled to it; withholding it is what let a PARTIAL parts list read as complete.
    # The exact-key-set assertion STAYS (a leak of anything else is still a failure) and the
    # decoy assertion below is unchanged, so the widening is one named field, not a loosening.
    assert set(out.keys()) == {"batch_id", "approver", "notice_id", "notice_type",
                               "notice_fingerprint", "items",
                               "extraction_warnings"}, "batch-read leaked an extra field"
    assert out["extraction_warnings"] == ["PARTS MAY BE MISSING: 2/5 table crops failed"]
    assert "SECRET-OTHER-APPROVER" not in json.dumps(out), "decoy state leaked into the batch-read"


@pytest.mark.asyncio
async def test_get_batch_warnings_default_empty_not_missing():
    """A batch from a CLEAN extraction (or one started before the field existed) serves an
    empty list, never a missing key — so the UI's banner condition is total, and the absence
    of a warning is itself a positive statement rather than an unknown."""
    state = {
        "batch_items": [{"mpn": "A", "subject": None,
                         "proposed_disposition": "dispatchQualification", "needs_review": False}],
        "approver": "alice@example.com", "notice_fingerprint": "IPCN25300X",
        "notice_id": "IPCN25300X", "doc_type": "PCN",
    }
    out = await _GET_BATCH(FakeSharedContext(state))
    assert out["extraction_warnings"] == []


@pytest.mark.asyncio
async def test_get_batch_404_when_no_active_review():
    import restate
    with pytest.raises(restate.TerminalError):
        await _GET_BATCH(FakeSharedContext({}))  # no batch_items -> no active review


# ===========================================================================
# RIDER 1 + fan-out — run(): register -> suspend -> fan out on accept
# ===========================================================================
@pytest.mark.asyncio
async def test_run_registers_task_then_fans_out_on_accept(monkeypatch):
    posts = []
    monkeypatch.setattr(dispatch_driver.requests, "post",
                        lambda url, **k: (posts.append((url, k.get("json"))), _Resp(200, {"task_id": "t"}))[1])
    batch_items = [
        {"mpn": f"MPN-{i}", "subject": f"http://internal/components/MPN-{i}",
         "proposed_disposition": "dispatchQualification", "needs_review": False}
        for i in range(2)
    ]
    ctx = FakeWorkflowContext(decision={"overrides": {}})
    out = await _RUN(ctx, {
        # M2-renamed audience shape. Under M3.2 delegation the definition declares the
        # NAMESPACE (`disposition_review:{compartment}`) and the trigger supplies only the
        # compartment, so a bare pre-rename audience is no longer expressible here — see
        # test_unshaped_audience_fails_loudly_not_unactionably below.
        "approver": "qa", "audience": "disposition_review:qualification",
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
    assert grouped_register["kind"] == "grouped_review"
    assert grouped_register["workflow_id"] == ctx.key() == "pcn-review-IPCN25300X-qa", \
        "grouped-review register dropped workflow_id — /act could not resume the review"


@pytest.mark.asyncio
async def test_unshaped_audience_fails_loudly_not_unactionably(monkeypatch):
    """M3.2: an audience with no compartment must FAIL, not register.

    ``review_starter`` falls back to ``request.get("audience") or approver`` — so a trigger
    that omits the audience yields a bare approver name like ``qa``, which is not a
    ``disposition_review:<compartment>`` relation and matches NO Topaz grant. Registering a
    grouped task against it would produce a review nobody is entitled to act on: no error,
    no recipient, suspended forever. That is the audience-shaped twin of a promise-name
    mismatch, and the fix is to be UNABLE to register it rather than to register it hopefully.
    """
    monkeypatch.setattr(dispatch_driver.requests, "post",
                        lambda url, **k: _Resp(200, {"task_id": "t"}))
    ctx = FakeWorkflowContext(decision={"overrides": {}})
    with pytest.raises(restate.exceptions.TerminalError) as exc:
        await _RUN(ctx, {
            "approver": "qa",                       # no audience -> starter falls back to this
            "notice_fingerprint": "IPCN25300X", "notice_id": "IPCN25300X",
            "batch_items": [{"mpn": "A", "subject": "http://internal/components/A",
                             "proposed_disposition": "dispatchQualification",
                             "needs_review": False}],
        })
    assert "compartment" in str(exc.value)
    assert "register_grouped_task" not in ctx.runs, (
        "a task was registered against an unactionable audience — it would suspend forever"
    )


@pytest.mark.asyncio
async def test_trigger_cannot_choose_its_own_audience_namespace(monkeypatch):
    """The authz boundary in the definition/trigger split: the definition declares the
    audience NAMESPACE and the trigger supplies only the compartment. A caller handing over
    a whole audience string would be choosing who may act on its own review — laundering
    access through the process plane. Only the tail is taken, so a hostile namespace is
    discarded rather than honoured."""
    posts = []
    monkeypatch.setattr(dispatch_driver.requests, "post",
                        lambda url, **k: (posts.append(k.get("json")), _Resp(200, {"task_id": "t"}))[1])
    ctx = FakeWorkflowContext(decision={"overrides": {}})
    await _RUN(ctx, {
        "approver": "qa", "audience": "totally_other:EVERYTHING",
        "notice_fingerprint": "IPCN25300X", "notice_id": "IPCN25300X",
        "batch_items": [{"mpn": "A", "subject": "http://internal/components/A",
                         "proposed_disposition": "dispatchQualification", "needs_review": False}],
    })
    assert posts[0]["audience"] == "disposition_review:EVERYTHING", (
        f"trigger-chosen namespace survived: {posts[0]['audience']!r}"
    )


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
        if url.endswith("/write_item_state"):
            status = 400 if json["subject_iri"].endswith("POISON") else 200
            return _Resp(status, {"ok": status == 200})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(dispatch_driver.requests, "post", _post)
    _DISPATCH = dispatch_driver.dispatch.__wrapped__

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
