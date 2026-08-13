"""APPROVAL AUTHORITY GATE — the approval plane checks WHO, on every surface.

`approval-bypass-bpmn-runner`, declared HIGH on 2026-08-10, fixed 2026-08-11. Until then
any caller who could reach the Restate ingress or engine-a could resolve the durable
promise that wakes a paused human approval — as anyone, with no record of who did it.
A system whose thesis is *one authority, checked at the enforcement point* had an
approval plane that checked nobody.

WHY THIS FILE IS SHAPED AS DISCRIMINATING PAIRS. A gate that refuses everyone passes a
refusal test and is broken-closed; a gate that admits everyone passes an acceptance test
and is the original bug. Neither half is evidence on its own. Every surface below is
asserted BOTH ways against the SAME fixture, changing only the caller — so the assertion
is that the gate DISCRIMINATES, not merely that it fires.

THREE SURFACES, NOT TWO. The packet named engine-a's HTTP route and the Restate `approve`
handler. Building the fix surfaced a third: `GroupedReview.submit_decision` resolves the
grouped review's decision promise — the same authority write, on a different runner,
equally reachable from the ingress. It validated the CONTENT of a submission thoroughly
and never asked who was submitting; having one authority question answered well is what
made the other easy to miss. Gating two of three would have been the false green the
packet's own two-surface caveat warns about, one rung up.

Run:  uv run --frozen --with pytest --with pytest-asyncio pytest tests/security/test_approval_authority_gate.py -v
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import restate  # noqa: E402

import main  # noqa: E402  — the real handler + route
from agent_fleet.restate_analyst import grouped_review_workflow  # noqa: E402

_APPROVE = main.approve.__wrapped__
_SUBMIT = grouped_review_workflow.submit_decision.__wrapped__

ENTITLED = "approver@example.com"
STRANGER = "someone-else@example.com"
AUDIENCE = "promotion:SUSTAINMENT"
OTHER_AUDIENCE = "promotion:DATA_ENGINEERING"


# ---------------------------------------------------------------------------
# The decider stub IS the subject of these tests, so it is deliberately NOT a
# blanket allow. It answers the real question — (audience, caller) — from a
# grant table, so a gate that asked the WRONG question (wrong audience, wrong
# subject, or a constant) produces a different answer and the pair goes red.
# ---------------------------------------------------------------------------
_GRANTS = {(AUDIENCE, ENTITLED)}
_ASKED: list[tuple[str, str]] = []


def _decider(audience: str, caller: str) -> bool:
    _ASKED.append((audience, caller))
    return (audience, caller) in _GRANTS


@pytest.fixture(autouse=True)
def _install_decider(monkeypatch):
    """Patch BOTH module identities (the flatten dance): sys.path carries the repo root
    AND agent_fleet/restate_analyst, so `spo_step_executor` and
    `agent_fleet.restate_analyst.spo_step_executor` are two distinct module objects and
    patching one leaves the other live."""
    _ASKED.clear()
    patched = 0
    for name in ("spo_step_executor", "agent_fleet.restate_analyst.spo_step_executor"):
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        monkeypatch.setattr(mod, "check_can_act", _decider, raising=False)
        patched += 1
    assert patched, "no spo_step_executor module identity was patched — the stub is not installed"


class _Promise:
    def __init__(self, rec, name):
        self._rec, self._name = rec, name

    async def resolve(self, value):
        self._rec.append((self._name, value))


class _Ctx:
    """WorkflowSharedContext stand-in that records every promise resolution."""

    def __init__(self, state: dict):
        self._state = state
        self.resolved: list = []

    async def get(self, name, **kw):
        return self._state.get(name)

    def promise(self, name, type_hint=None):
        return _Promise(self.resolved, name)


def _approve_state(promise_name="approval_step-1", audience=AUDIENCE):
    return {main._audience_key(promise_name): audience}


def _grouped_state(audience=AUDIENCE):
    return {
        "batch_items": [{
            "mpn": "MPN-1", "subject": "http://internal/components/MPN-1",
            "proposed_disposition": "dispatchQualification", "needs_review": False,
        }],
        "approver": "svc:review-starter",
        "notice_fingerprint": "IPCN25300X",
        main._audience_key("decision"): audience,
    }


# ===========================================================================
# SURFACE 1 — the Restate `approve` handler (its own entry point)
# ===========================================================================
@pytest.mark.asyncio
async def test_surface1_entitled_caller_resolves_and_the_identity_is_recorded():
    ctx = _Ctx(_approve_state())
    out = await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED", "acted_by": ENTITLED})

    assert len(ctx.resolved) == 1, "an entitled approval must resolve the promise"
    name, payload = ctx.resolved[0]
    assert name == "approval_step-1"
    # THE APPROVAL CARRIES ITS ACTOR. An approval with no actor is unauditable, and the
    # verified identity — not one the body asserted — is what must travel with it.
    assert payload["acted_by"] == ENTITLED, payload
    assert out["message"]


@pytest.mark.asyncio
async def test_surface1_unentitled_caller_is_refused_and_nothing_is_resolved():
    ctx = _Ctx(_approve_state())
    with pytest.raises(restate.TerminalError) as exc:
        await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED", "acted_by": STRANGER})

    assert exc.value.status_code == 403
    assert ctx.resolved == [], (
        "an unauthorized approval resolved the promise — the workflow would have resumed "
        "and fanned out real effects on a decision nobody was entitled to make"
    )


@pytest.mark.asyncio
async def test_surface1_missing_identity_is_401_not_a_silent_default():
    """No actor is a DIFFERENT failure from a known-and-denied actor, and the codes must
    say so: 401 (who are you) vs 403 (you may not). Collapsing them would send an
    unauthenticated caller hunting for a missing grant."""
    ctx = _Ctx(_approve_state())
    with pytest.raises(restate.TerminalError) as exc:
        await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED"})
    assert exc.value.status_code == 401
    assert ctx.resolved == []


@pytest.mark.asyncio
async def test_surface1_audience_comes_from_the_JOURNAL_not_the_request():
    """THE SPOOF CASE, and the reason the audience is journalled at all.

    The caller supplies an audience they ARE entitled to act on, for a promise whose
    journalled audience is one they are NOT. If the gate read the request, this would be
    admitted — the attacker would be choosing the question the gate asks."""
    ctx = _Ctx(_approve_state(audience=OTHER_AUDIENCE))
    with pytest.raises(restate.TerminalError) as exc:
        await _APPROVE(ctx, {
            "task_id": "step-1", "status": "APPROVED", "acted_by": ENTITLED,
            "audience": AUDIENCE,          # <- the lie
        })
    assert exc.value.status_code == 403
    assert ctx.resolved == []
    assert (OTHER_AUDIENCE, ENTITLED) in _ASKED, (
        f"the gate asked {_ASKED!r} — it must ask about the JOURNALLED audience "
        f"({OTHER_AUDIENCE!r}), never the one the request supplied"
    )


@pytest.mark.asyncio
async def test_surface1_no_journalled_audience_fails_CLOSED():
    """A promise with no journalled audience cannot be authorized, so it is refused.
    Resolving anyway would be the broken-closed inversion: waving through exactly the
    cases the gate cannot evaluate."""
    ctx = _Ctx({})
    with pytest.raises(restate.TerminalError) as exc:
        await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED", "acted_by": ENTITLED})
    assert exc.value.status_code == 403
    assert ctx.resolved == []


# ===========================================================================
# SURFACE 2 — engine-a's HTTP route
# ===========================================================================
class _FakeCaller:
    def __init__(self, authz_id, verified=True, reason="ok"):
        self.authz_id, self.verified, self.reason = authz_id, verified, reason


class _FakeResp:
    def __init__(self, code=200, body=None):
        self.status_code, self._body = code, (body or {})
        self.text = str(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Req:
    status = "APPROVED"
    comments = ""


@pytest.mark.asyncio
async def test_surface2_verified_caller_forwards_the_verified_identity(monkeypatch):
    sent: dict = {}

    def _post(url, json=None, headers=None, timeout=None):
        sent.update(json or {})
        return _FakeResp(200, {"ok": True})

    monkeypatch.setattr(main.requests, "post", _post)
    resp = await main.approve_task("wf-1", "step-1", _Req(), caller=_FakeCaller(ENTITLED))

    assert resp.status_code == 200
    assert sent.get("acted_by") == ENTITLED, (
        f"the route must thread the VERIFIED identity to the handler; sent {sent!r}"
    )


@pytest.mark.asyncio
async def test_surface2_unverified_caller_is_refused_BEFORE_the_call_is_made(monkeypatch):
    """Identity is required here regardless of transport posture. The app-wide dependency
    runs in OBSERVE until the ENABLE_AGENTIC_AUTH flip and refuses nothing — correct for
    ordinary routes, wrong for an authority write. Deferring this gate to that flip would
    leave the approval plane open until the most-deferred change in the programme landed.

    Asserts the call is not merely refused but NEVER ISSUED — a route that forwards and
    then discards the response would leak the effect while reporting a denial."""
    calls: list = []
    monkeypatch.setattr(main.requests, "post",
                        lambda *a, **k: calls.append(a) or _FakeResp(200, {}))

    resp = await main.approve_task(
        "wf-1", "step-1", _Req(), caller=_FakeCaller("", verified=False, reason="absent"))

    assert resp.status_code == 401
    assert calls == [], "the route called the approve handler despite refusing the caller"


@pytest.mark.asyncio
async def test_surface2_handler_denial_surfaces_as_403_not_502(monkeypatch):
    """An error surface that mislabels a denial as an outage sends the operator to hunt a
    broken service instead of a missing grant. The reporter must fail louder than what it
    reports, and it must fail with the RIGHT NAME."""
    monkeypatch.setattr(
        main.requests, "post",
        lambda *a, **k: _FakeResp(403, {"message": "caller is not authorized (can_act)"}))

    resp = await main.approve_task("wf-1", "step-1", _Req(), caller=_FakeCaller(STRANGER))
    assert resp.status_code == 403, "a handler denial must not be reported as a 502 outage"
    body = resp.body.decode()
    assert "not_authorized_to_act" in body
    assert "can_act" in body, "the refusal must carry its reason, not just its code"


# ===========================================================================
# SURFACE 3 — GroupedReview.submit_decision (the surface the packet missed)
# ===========================================================================
@pytest.mark.asyncio
async def test_surface3_entitled_caller_settles_the_review():
    ctx = _Ctx(_grouped_state())
    out = await _SUBMIT(ctx, {"decision": {"overrides": {}}, "acted_by": ENTITLED})
    assert out["accepted"] is True, out
    assert len(ctx.resolved) == 1


@pytest.mark.asyncio
async def test_surface3_unentitled_caller_is_refused_and_the_review_stays_suspended():
    ctx = _Ctx(_grouped_state())
    with pytest.raises(restate.TerminalError) as exc:
        await _SUBMIT(ctx, {"decision": {"overrides": {}}, "acted_by": STRANGER})
    assert exc.value.status_code == 403
    assert ctx.resolved == [], (
        "an unauthorized submission resolved the decision promise — the review would have "
        "woken and dispatched its whole batch"
    )


@pytest.mark.asyncio
async def test_surface3_gate_precedes_content_validation():
    """Authorization before content, for the same reason cortex-bff validates the verb
    after authz: a refusal must never leak what the task contains. A stranger submitting
    against a batch that would also FAIL validation must be told 403, not the validation
    reason — otherwise the error message is an oracle."""
    state = _grouped_state()
    state["batch_items"] = [{
        "mpn": "MPN-1", "subject": "http://internal/components/MPN-1",
        "proposed_disposition": "dispatchQualification", "needs_review": True,  # would refuse
    }]
    ctx = _Ctx(state)
    with pytest.raises(restate.TerminalError) as exc:
        await _SUBMIT(ctx, {"decision": {"overrides": {}}, "acted_by": STRANGER})
    assert exc.value.status_code == 403


# ===========================================================================
# POSITIVE CONTROL — the harness can distinguish, and the stub is really installed
# ===========================================================================
@pytest.mark.asyncio
async def test_positive_control_the_decider_is_actually_consulted():
    """If the gate were removed, every test above that expects a refusal would go red —
    but every test that expects an ACCEPT would still pass, because an ungated handler
    accepts everyone. This asserts the accept path is earned: the decider was ASKED, with
    the right pair. Without it, the green half of each discriminating pair is compatible
    with there being no gate at all."""
    ctx = _Ctx(_approve_state())
    await _APPROVE(ctx, {"task_id": "step-1", "status": "APPROVED", "acted_by": ENTITLED})
    assert (AUDIENCE, ENTITLED) in _ASKED, (
        f"the accept path did not consult the decider (asked: {_ASKED!r}) — the gate may "
        "not be running at all"
    )
