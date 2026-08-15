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


@pytest.fixture(autouse=True)
def _stub_service_mint(monkeypatch):
    """The register MINTS AT USE (2026-08-04), so every test touching the mint path would otherwise
    reach Keycloak — and fail with a bare ``KeyError`` on the missing env, which is honest in
    production and useless here. Stub the mint, do NOT set fake env: setting env would exercise a
    REAL client-credentials POST against a nonexistent Keycloak and turn these unit tests into
    network tests. The mint's own failure semantics are sealed separately; this suite seals the
    driver's convergence, and the two must not be tangled.

    PATCHES BOTH MODULE IDENTITIES — ``sys.path`` carries the repo root AND
    ``agent_fleet/restate_analyst``, so ``dispatch_driver`` and
    ``agent_fleet.restate_analyst.dispatch_driver`` are TWO distinct module objects with separate
    globals; patching one can leave the other live."""
    stub = lambda **_: "svc-token-stub"  # noqa: E731
    for _name in ("dispatch_driver", "agent_fleet.restate_analyst.dispatch_driver"):
        _mod = sys.modules.get(_name)
        if _mod is not None:
            monkeypatch.setattr(_mod, "mint_service_token", stub, raising=False)


# ---------------------------------------------------------------------------
# Payload builders — through the REAL plan_dispatch + plan_to_payload
# ---------------------------------------------------------------------------
def _payload(disposition, *, mpn="NSR01L30NXT5G",
             subject="http://internal/components/NSR01L30NXT5G",
             needs_review=False, ruleset="rules@abc123def456"):
    res = ItemResolution(
        mpn=mpn, subject=subject, disposition=disposition,
        idempotency_key=f"IPCN25300X:{mpn}", needs_review=needs_review,
        override_reason=None, proposed_by_ruleset=ruleset,
    )
    plan = plan_dispatch(res, notice_fingerprint="IPCN25300X", notice_id="IPCN25300X")
    # A COMPARTMENT IS SUPPLIED DELIBERATELY (2026-08-05). Without it, a terminal write failure takes
    # the effect-failure path's "cannot route" branch and raises a TerminalError about ROUTING —
    # which the terminal-vs-park tests below would happily accept, since they only assert the TYPE.
    # They would then pass while never reaching the denial they exist to measure. Supplying it keeps
    # those tests pointed at their own subject and exercises the real emission.
    return dispatch_driver.plan_to_payload(plan, compartment="SUSTAINMENT")


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
    rec = {"mint": 0, "state": 0, "mint_bodies": [], "state_bodies": [], "triage_bodies": [],
           "status": {"mint": 200, "state": 200, "triage": 200}}

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/internal/human_tasks/register"):
            rec["mint"] += 1
            rec["mint_bodies"].append(json)
            return _Resp(rec["status"]["mint"], {"task_id": json["task_id"], "queued": True})
        if url.endswith("/write_item_state"):
            rec["state"] += 1
            rec["state_bodies"].append(json)
            return _Resp(rec["status"]["state"], {"ok": True, "subject_iri": json["subject_iri"]})
        if url.endswith("/triage_tasks"):
            # The effect-failure surfacing (2026-08-05): a dispatch that dies TERMINALLY after a
            # human approved it files a triage row before re-raising.
            rec["triage_bodies"].append(json)
            return _Resp(rec["status"]["triage"],
                         {"task_id": (json or {}).get("task_id"), "status": "FILED", "recipients": 1})
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
    with pytest.raises(restate.TerminalError) as ei:
        await _invoke(_payload("dispatchQualification"), {})
    assert http["state"] == 0, "state was written despite the task-mint denial (chain should have stopped)"
    # ASSERT THE CAUSE, not merely the type. Since the effect-failure path also raises TerminalError,
    # a bare `raises(TerminalError)` can no longer distinguish "the denial this test is about" from
    # "the report of it failed to route" — and a test that cannot tell those apart has stopped
    # measuring its own subject.
    assert "access denied (403)" in str(ei.value), (
        f"caught a TerminalError, but not the auth denial this test measures: {ei.value}")
    # And the denial is SURFACED, not merely raised: the human already approved.
    assert len(http["triage_bodies"]) == 1, (
        "a post-approval dispatch died on a denial and no effect-failure row was filed")
    assert http["triage_bodies"][0]["audience"] == "dispatch_failure:SUSTAINMENT"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 422])
async def test_malformed_mint_4xx_is_terminal_not_park(http, status):
    """The classifier past 401/403: any 4xx (a 422 missing-field, a 400 bad request, a 404) is a
    POISONED payload that won't heal on retry -> TerminalError (release), never retry-park. Found live:
    a 422 (missing requested_by) would otherwise have parked the item's object forever."""
    http["status"]["mint"] = status
    with pytest.raises(restate.TerminalError) as ei:
        await _invoke(_payload("dispatchQualification"), {})
    assert http["state"] == 0
    assert f"({status})" in str(ei.value), (
        f"caught a TerminalError, but not the {status} this test measures: {ei.value}")
    assert len(http["triage_bodies"]) == 1, (
        f"a post-approval dispatch died on a {status} and no effect-failure row was filed")


@pytest.mark.asyncio
async def test_rate_limited_mint_429_stays_retryable(http):
    """429 is the exception — a rate limit IS transient, so it must NOT be terminal (stays retryable so
    Restate backs off and retries)."""
    http["status"]["mint"] = 429
    with pytest.raises(Exception) as ei:
        await _invoke(_payload("dispatchQualification"), {})
    assert not isinstance(ei.value, restate.TerminalError), "429 (rate limit) must stay retryable, not terminal"
    # AND IT MUST NOT CRY WOLF. The effect-failure row means "this dispatch will never happen" — a
    # transient that Restate is about to retry successfully has not earned one. Filing on every
    # blip would train operators to ignore the queue, which is how a real dead effect gets missed.
    assert http["triage_bodies"] == [], (
        "filed an effect-failure row for a RETRYABLE failure — the dispatch has not given up yet")


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
                                       notice_id="IPCN25300X")
    assert keys == ["IPCN25300X:MPN-0", "IPCN25300X:MPN-1", "IPCN25300X:MPN-2"]
    assert [s["key"] for s in ctx.sends] == keys
    assert [s["idempotency_key"] for s in ctx.sends] == keys, "invocation dedup key must be the notice x part key"
    assert all(s["arg"]["human_task"]["audience"] == "qualification" for s in ctx.sends)
    # NO CREDENTIAL IN A JOURNALED PAYLOAD (2026-08-04, the notice-A defect). An object_send body is
    # durable journal state, so a token in it is a credential at rest that a retry can replay long
    # after it expired. The register mints at use instead; this asserts the field cannot come back.
    # NESTED, NOT TOP-LEVEL (strengthened 2026-08-05). This used to read `"user_jwt" not in s["arg"]`,
    # which inspects only the OUTERMOST dict — so a deliberate regression that put the credential back
    # where it would really go (inside `human_task`, the sub-dict the register body is built from)
    # left this guard GREEN while a token rode the payload. Found by the break-on-purpose arm of
    # tests/test_expired_token_seal.py, which is the argument for breaking passing guards on purpose:
    # it did not fail, and the reason was a defect in the guard rather than health in the code.
    def _all_keys(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                here = f"{path}.{k}" if path else str(k)
                yield here
                yield from _all_keys(v, here)
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                yield from _all_keys(v, f"{path}[{i}]")

    _cred = ("user_jwt", "jwt", "token", "access_token", "bearer", "authorization", "secret")
    for s in ctx.sends:
        offenders = [p for p in _all_keys(s["arg"]) if p.rsplit(".", 1)[-1].lower() in _cred]
        assert not offenders, (
            f"a credential is riding the journaled dispatch payload at {offenders} — mint at use, "
            f"never carry a token across a suspend "
            f"(docs/plans/archive/2026-08-04-notice-a-dispatch-failure.md)"
        )
