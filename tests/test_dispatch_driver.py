"""PCN/PDN dispatch DRIVER sealed — the two-write convergence made a durable PROPERTY, not an adjective.

The heart is the TWO-DIRECTION failure-injection seal (§7, [[feedback_lifecycle_state_observable]] /
[[feedback_composed_path_seal]]): kill the driver AFTER each of the two journaled writes, restart, and
assert the end state is EXACTLY ONE task and EXACTLY ONE state stamp — in both directions. That two-
mechanism exactly-one (ctx.run journaling for crash-between; a durable marker for a second whole
invocation) is what makes "durable" a property. The plan is built through the REAL plan_dispatch +
plan_to_payload (composed path, not synthetic dicts), so the serialization is under test too.

Also sealed: TASK-FIRST ordering, archive (state, no task), unresolved-subject (task-only, carrying
re-link provenance), the dedup no-op on a second invocation, suspend-vs-fail on an auth denial, and the
execution-grain fan-out (one grouped approval -> N keyed sends).

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with pytest-asyncio \
        pytest ../../tests/test_dispatch_driver.py -v
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
from agent_fleet.restate_analyst import dispatch_driver  # noqa: E402
from agent_fleet.restate_analyst.dispatch_plan import plan_dispatch  # noqa: E402
from agent_fleet.restate_analyst.workflow_bulk_resolve import ItemResolution  # noqa: E402

_DISPATCH = dispatch_driver.dispatch.__wrapped__  # unwrap the @handler coroutine to call it directly


# ---------------------------------------------------------------------------
# Payload builders — through the REAL plan_dispatch + plan_to_payload
# ---------------------------------------------------------------------------
def _payload(disposition, *, mpn="NSR01L30NXT5G",
             subject="http://internal/components/NSR01L30NXT5G",
             needs_review=False, ruleset="rules@abc123def456", user_jwt="jwt-abc"):
    res = ItemResolution(
        mpn=mpn, subject=subject, disposition=disposition,
        idempotency_key=f"IPCN25300X:{mpn}", needs_review=needs_review,
        override_reason=None, proposed_by_ruleset=ruleset,
    )
    plan = plan_dispatch(res, notice_fingerprint="IPCN25300X", notice_id="IPCN25300X")
    return dispatch_driver.plan_to_payload(plan, user_jwt=user_jwt)


# ---------------------------------------------------------------------------
# A Restate-faithful journaling ObjectContext + crash injection
# ---------------------------------------------------------------------------
class _Crash(Exception):
    """A simulated mid-dispatch crash — Restate replays the invocation from the top on restart."""


class JournalingObjectContext:
    """Models the durable semantics the seal depends on (more than a re-call-every-time fake):

    - ``run(name, fn)``: a step already in THIS invocation's journal replays its cached result WITHOUT
      re-calling fn (so a completed effect is never re-executed). A fresh step calls fn, journals the
      result, then — if ``crash_after`` names it — raises ``_Crash`` AFTER journaling (mirroring a
      crash once the effect landed but before the next step).
    - ``get``/``set``: the OBJECT's durable state (keyed), surviving across replays AND invocations —
      VirtualObject state is not lost on a crash.

    One journal per invocation (shared across that invocation's replays); one state dict per key
    (shared across invocations)."""

    def __init__(self, key, state, journal, *, crash_after=None):
        self._key = key
        self._state = state
        self._journal = journal
        self._crash_after = crash_after

    def key(self):
        return self._key

    async def get(self, k):
        return self._state.get(k)

    def set(self, k, v):
        self._state[k] = v

    async def run(self, name, fn):
        if name in self._journal:
            return self._journal[name]          # replay — the effect already happened, do not repeat it
        result = fn()
        if hasattr(result, "__await__"):
            result = await result
        self._journal[name] = result
        if self._crash_after == name:
            raise _Crash(f"crash after {name!r}")
        return result


async def _invoke(payload, state, *, crash_after=None):
    """Run ONE invocation to completion the way Restate would: on a crash, restart from the top with
    the SAME journal (completed steps cached) until it finishes clean. The injected fault is one-time
    (the restart succeeds), which is the scenario the seal asserts convergence over."""
    journal: dict = {}
    ca = crash_after
    while True:
        ctx = JournalingObjectContext("IPCN25300X:NSR01L30NXT5G", state, journal, crash_after=ca)
        try:
            return await _DISPATCH(ctx, payload)
        except _Crash:
            ca = None  # the process restarted; the transient fault does not recur


# ---------------------------------------------------------------------------
# HTTP recorder — counts REAL executions (replays don't call; journaled)
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


@pytest.fixture
def http(monkeypatch):
    rec = {"mint": 0, "state": 0, "mint_bodies": [], "state_bodies": [], "status": {"mint": 200, "state": 200}}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/internal/human_tasks/register"):
            rec["mint"] += 1
            rec["mint_bodies"].append(json)
            return _Resp(rec["status"]["mint"], {"task_id": json["task_id"], "queued": True})
        if url.endswith("/write_item_state"):
            rec["state"] += 1
            rec["state_bodies"].append(json)
            return _Resp(rec["status"]["state"], {"ok": True, "subject_iri": json["subject_iri"]})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(dispatch_driver.requests, "post", _post)
    return rec


# ===========================================================================
# THE SEAL — two-direction failure injection: EXACTLY ONE task + EXACTLY ONE state
# ===========================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize("crash_after", ["mint_task", "write_state"])
async def test_crash_between_writes_converges_to_exactly_one_each(http, crash_after):
    """Kill AFTER each write, restart, assert convergence — both writes land EXACTLY ONCE. A crash
    after mint (before state) must not double-mint on resume; a crash after state (before the marker)
    must not re-run either. This is what makes the two-write convergence durable, not hopeful."""
    state: dict = {}
    outcome = await _invoke(_payload("dispatchQualification"), state, crash_after=crash_after)

    assert http["mint"] == 1, f"task minted {http['mint']}x (expected exactly 1) after crash_after={crash_after}"
    assert http["state"] == 1, f"state written {http['state']}x (expected exactly 1) after crash_after={crash_after}"
    assert outcome["task_minted"] and outcome["state_written"]
    assert state.get("dispatched") is not None, "durable exactly-one marker not set after convergence"


@pytest.mark.asyncio
async def test_task_is_minted_before_state(http):
    """Ordering is load-bearing (§Decisions): task-without-state is visible-and-recoverable; the
    reverse is silent-and-stuck. Under a clean run the register POST precedes the state POST."""
    seq: list[str] = []
    orig = dispatch_driver.requests.post

    def _tracking(url, **kw):
        seq.append("mint" if url.endswith("/register") else "state")
        return orig(url, **kw)

    dispatch_driver.requests.post = _tracking
    try:
        await _invoke(_payload("dispatchLTB"), {})
    finally:
        dispatch_driver.requests.post = orig
    assert seq == ["mint", "state"], f"expected task-first ordering, got {seq}"


# ===========================================================================
# Dedup — a second WHOLE invocation to the same key is a no-op (exactly-one across invocations)
# ===========================================================================
@pytest.mark.asyncio
async def test_second_invocation_same_key_is_noop(http):
    """The dedup-on-(notice x part) the keying 'should give for free' — asserted. A redelivered whole
    invocation (fresh journal, same object state) returns the prior outcome and writes nothing new."""
    state: dict = {}
    first = await _invoke(_payload("dispatchQualification"), state)
    assert (http["mint"], http["state"]) == (1, 1)

    second = await _invoke(_payload("dispatchQualification"), state)
    assert (http["mint"], http["state"]) == (1, 1), "a second invocation re-ran a write — not idempotent on key"
    assert second == first


# ===========================================================================
# archive -> state, no task ;  unresolved subject -> task-only, re-link provenance
# ===========================================================================
@pytest.mark.asyncio
async def test_archive_writes_state_but_mints_no_task(http):
    outcome = await _invoke(_payload("archive"), {})
    assert http["mint"] == 0, "archive opened a task (should be acknowledge-only)"
    assert http["state"] == 1
    assert outcome["state_written"] and not outcome["task_minted"]


@pytest.mark.asyncio
async def test_unresolved_subject_mints_task_only_with_relink_provenance(http):
    """No subject -> no node to stamp -> NO state write, but the task still opens carrying mpn +
    notice_fingerprint + subject_unresolved so a later pass can stamp state retroactively (never an
    orphan). The rider seam, sealed at the driver."""
    res = ItemResolution(
        mpn="MPN-UNRES", subject=None, disposition="dispatchQualification",
        idempotency_key="IPCN25300X:MPN-UNRES", needs_review=False,
        override_reason=None, proposed_by_ruleset="rules@abc123def456",
    )
    payload = dispatch_driver.plan_to_payload(
        plan_dispatch(res, notice_fingerprint="IPCN25300X", notice_id="IPCN25300X"),
    )
    outcome = await _invoke(payload, {})

    assert http["state"] == 0, "stamped state on an unresolved subject (no node exists)"
    assert http["mint"] == 1
    assert outcome["subject_unresolved"] is True
    body = http["mint_bodies"][0]
    assert body["mpn"] == "MPN-UNRES"
    assert body["notice_fingerprint"] == "IPCN25300X"
    assert body["subject_unresolved"] is True
    assert "requested_by" in body, "cortex-bff register REQUIRES requested_by (422 without it)"


# ===========================================================================
# Suspend-vs-fail — a persistent auth denial on the mint is a FAILURE, never retry-and-park
# ===========================================================================
@pytest.mark.asyncio
async def test_auth_denial_on_mint_is_terminal_not_park(http):
    """A 401/403 on the register won't heal on retry — it must raise TerminalError (release state),
    not bubble a retryable error that parks the durable execution (the DoS a denial must avoid).
    And the state write never happens (task-first, the denial stops the chain)."""
    http["status"]["mint"] = 403
    with pytest.raises(restate.TerminalError):
        await _invoke(_payload("dispatchQualification"), {})
    assert http["state"] == 0, "state was written despite the task-mint denial (chain should have stopped)"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 422])
async def test_malformed_mint_4xx_is_terminal_not_park(http, status):
    """The classifier past 401/403: any 4xx (a 422 missing-field, a 400 bad request, a 404) is a
    POISONED payload that won't heal on retry -> TerminalError (release), never retry-park. Found live:
    a 422 (missing requested_by) would otherwise have parked the item's object forever."""
    http["status"]["mint"] = status
    with pytest.raises(restate.TerminalError):
        await _invoke(_payload("dispatchQualification"), {})
    assert http["state"] == 0


@pytest.mark.asyncio
async def test_rate_limited_mint_429_stays_retryable(http):
    """429 is the exception — a rate limit IS transient, so it must NOT be terminal (stays retryable so
    Restate backs off and retries)."""
    http["status"]["mint"] = 429
    with pytest.raises(Exception) as ei:
        await _invoke(_payload("dispatchQualification"), {})
    assert not isinstance(ei.value, restate.TerminalError), "429 (rate limit) must stay retryable, not terminal"


# ===========================================================================
# Fan-out — one grouped approval -> N keyed sends (execution grain, §1)
# ===========================================================================
class _SendRecorder:
    def __init__(self):
        self.sends: list[dict] = []

    def object_send(self, tpe, key, arg, idempotency_key=None, **kw):
        self.sends.append({"key": key, "idempotency_key": idempotency_key, "arg": arg})


def test_fan_out_sends_one_keyed_invocation_per_item():
    """One approval, N resolutions -> N sends, each keyed by its own idempotency_key (notice x part),
    the invocation idempotency_key matching so a workflow-replay re-fan-out collapses onto the same
    invocation. Execution grain stays per-item even though approval was one gesture."""
    resolutions = [
        ItemResolution(mpn=f"MPN-{i}", subject=f"http://internal/components/MPN-{i}",
                       disposition="dispatchQualification", idempotency_key=f"IPCN25300X:MPN-{i}",
                       needs_review=False, override_reason=None, proposed_by_ruleset="rules@abc123def456")
        for i in range(3)
    ]
    ctx = _SendRecorder()
    keys = dispatch_driver.fan_out_dispatch(ctx, resolutions, notice_fingerprint="IPCN25300X",
                                       notice_id="IPCN25300X", user_jwt="jwt-abc")
    assert keys == ["IPCN25300X:MPN-0", "IPCN25300X:MPN-1", "IPCN25300X:MPN-2"]
    assert [s["key"] for s in ctx.sends] == keys
    assert [s["idempotency_key"] for s in ctx.sends] == keys, "invocation dedup key must be the notice x part key"
    assert all(s["arg"]["human_task"]["audience"] == "qualification" for s in ctx.sends)
