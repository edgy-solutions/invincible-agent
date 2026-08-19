"""THE EXPIRED-TOKEN SEAL — the defect class no machine-latency witness can reach.

WHY THIS FILE EXISTS. Notice ``M32-A-WITNESS`` sat ~90 minutes between a review starting and a
human approving it. The credential captured at START was long dead by APPROVAL, so both dispatches
died on ``401 -> fail-and-release`` 160ms later, leaving the projection reading ``approved`` with no
effects. **Twelve M3.2 seals were green over that bug the whole time.** Not because they were weak —
because every one of them resolved its review in milliseconds, and a defect whose trigger is ELAPSED
TIME is structurally invisible to a witness that never elapses any.

So the fix is not another assertion. It is a HARNESS THAT CAN AGE. Time here is a variable this file
controls (``_Clock``), never wall-clock: ninety minutes is MANUFACTURED, not waited for. That is the
kill-seal move applied to expiry — if a seal has to wait for the defect, it will never be run.

THE HARNESS AGES HONESTLY, which is the part that makes the green mean something. The fake register
does not take a verdict from the test; it READS the presented token's expiry against the clock and
decides 401-vs-200 itself. So the SAME token yields 200 at t=0 and 401 at t=90min, and both arms are
witnessed in `test_the_harness_ages_a_token` below. A harness whose failure arm is hand-wired proves
only that the test can assert; this one reproduces the actual mechanism.

WHAT IS DELIBERATELY NOT STUBBED. ``tests/test_dispatch_driver.py`` stubs ``mint_service_token``
away (autouse) so its convergence seals do not become network tests. Three suites do. **This is the
one place that must not**, because the mint IS the subject. The stub here REPLACES the mint with a
clock-aware one rather than removing it.

THE STOP CONDITION, recorded before the work so nobody re-derives it at 3am. ``0c222c3`` already
landed mint-at-use, so an expired USER token can no longer reach the dispatch path — the field was
deleted from the journaled payload, and that door is bricked up. The staleness is therefore
re-introduced at the only point a credential is still CONSUMED: the service mint itself, bound at
module scope in ``dispatch_driver`` precisely so a test can reach it.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with pytest-asyncio \
        pytest ../../tests/test_expired_token_seal.py -v
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

_DISPATCH = dispatch_driver.dispatch.__wrapped__

# A realistic access-token lifetime. The POINT of the seal is that this number is IRRELEVANT to
# correctness — mint-at-use has no staleness window at any TTL — which is exactly why "just make it
# longer" was the rejected fix. Lifetime-tuning to outlast human reviewers converges on effectively
# unbounded credentials stored durably in journals.
_TTL_S = 300.0
_NINETY_MINUTES = 90 * 60.0   # notice M32-A-WITNESS's real suspend, to the minute


class _Clock:
    """Controllable time. The whole seal rests on ninety minutes being a VARIABLE."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _mint_at(clock: _Clock) -> str:
    """A token that CARRIES its own expiry, so the fake register can adjudicate it without being
    told the answer. Deliberately not a real JWT: parsing one would test pyjwt, and the property
    under seal is 'when was this minted relative to when it is used', which needs no crypto."""
    return f"svc-token.minted@{clock.t:.0f}.exp@{clock.t + _TTL_S:.0f}"


def _exp_of(token: str) -> float:
    return float(token.split("exp@")[1])


def _minted_at_of(token: str) -> float:
    return float(token.split("minted@")[1].split(".exp@")[0])


def _payload(disposition="dispatchQualification", *, mpn="NSR01L30NXT5G", compartment="SUSTAINMENT"):
    """Through the REAL plan_dispatch + plan_to_payload — composed path, never a synthetic dict.

    THE TWO IDENTITIES ARE DELIBERATELY DIFFERENT, and this fixture was WRONG until the live drive
    corrected it. It originally passed ``requested_by="alice@example.com"`` — one identity for both
    roles — which made every assertion about provenance pass trivially, because there was nothing
    for the code to confuse. Production does not look like that: the sensor's SERVICE identity
    starts the review and a HUMAN approves it. Mirroring that here is what lets a merge of the two
    fields FAIL, and a fixture that cannot express the defect cannot catch it
    ([[feedback_test_supplies_own_provenance]])."""
    res = ItemResolution(
        mpn=mpn, subject=f"http://internal/components/{mpn}", disposition=disposition,
        idempotency_key=f"M32-A-WITNESS:{mpn}", needs_review=False,
        override_reason=None, proposed_by_ruleset="rules@abc123def456",
    )
    plan = plan_dispatch(res, notice_fingerprint="M32-A-WITNESS", notice_id="M32-A-WITNESS")
    return dispatch_driver.plan_to_payload(
        plan,
        requested_by="svc:review-starter",   # who STARTED the review (a service, canonically)
        acted_by="alice@example.com",        # who APPROVED it (the human `/act` authorized)
        compartment=compartment,
    )


class _JournalingObjectContext:
    """Same durable semantics as the dispatch-driver seal's context: a journaled step replays its
    cached result without re-calling, and object state survives across invocations."""

    def __init__(self, key, state, journal):
        self._key, self._state, self._journal = key, state, journal

    def key(self):
        return self._key

    async def get(self, k):
        return self._state.get(k)

    def set(self, k, v):
        self._state[k] = v

    async def run(self, name, fn):
        if name in self._journal:
            return self._journal[name]
        result = fn()
        if hasattr(result, "__await__"):
            result = await result
        self._journal[name] = result
        return result


async def _invoke(payload, state=None):
    return await _DISPATCH(
        _JournalingObjectContext("M32-A-WITNESS:NSR01L30NXT5G", state if state is not None else {}, {}),
        payload,
    )


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


@pytest.fixture
def aging(monkeypatch):
    """A clock, a clock-aware mint, and a register that ADJUDICATES EXPIRY ITSELF.

    ``carry_token`` is the pre-fix behaviour in one switch: when set, the mint stops minting and
    hands back that fixed token forever — which is precisely what "capture at review start, use at
    approval" DID. It is how the seal's break-on-purpose arm reproduces the original defect without
    editing the source.
    """
    clock = _Clock()
    rec = {
        "clock": clock, "carry_token": None,
        "mint_calls": [], "register": [], "state": 0, "triage": [],
        "register_status": [],
    }

    def _mint(**_kw):
        if rec["carry_token"] is not None:
            rec["mint_calls"].append(("carried", rec["carry_token"]))
            return rec["carry_token"]
        tok = _mint_at(clock)
        rec["mint_calls"].append(("minted", tok))
        return tok

    # BOTH module identities — sys.path carries the repo root AND agent_fleet/restate_analyst, so
    # `dispatch_driver` and `agent_fleet.restate_analyst.dispatch_driver` are TWO module objects
    # with separate globals; patching one can leave the other live.
    # ACTIVELY IMPORT, don't poll sys.modules. The passive form
    # (`sys.modules.get(_name)` + `if _mod is not None`) patched NOTHING whenever the
    # module wasn't loaded yet — and this fixture's own docstring says that happens, since
    # the consumer imports lazily. A seal that silently declines to seal is worse than no
    # seal. Mirrors the `check_can_act` fixture in this same file, which already does it
    # this way. See docs/principles/a-stub-that-needs-another-test-is-not-a-stub.md
    import importlib  # noqa: PLC0415

    _bound = 0
    for _name in ("dispatch_driver", "agent_fleet.restate_analyst.dispatch_driver"):
        try:
            _mod = importlib.import_module(_name)
        except ImportError:
            continue
        monkeypatch.setattr(_mod, "mint_service_token", _mint, raising=False)
        _bound += 1
    assert _bound, (
        "mint_service_token was patched in ZERO modules -- the seal would run against the "
        "real mint and prove nothing. Import paths changed; update this fixture's name list."
    )

    def _post(url, json=None, headers=None, timeout=None):
        if url.endswith("/internal/human_tasks/register"):
            token = (headers or {}).get("Authorization", "").removeprefix("Bearer ").strip()
            rec["register"].append({"token": token, "body": json, "at": clock.t})
            # THE ADJUDICATION — the harness decides from the token and the clock, never from a
            # verdict the test handed it. This is what makes the green arm evidence.
            if not token or clock.t >= _exp_of(token):
                rec["register_status"].append(401)
                return _Resp(401, {"error": "token_expired"})
            rec["register_status"].append(200)
            return _Resp(200, {"task_id": json["task_id"], "queued": True})
        if url.endswith("/write_item_state"):
            rec["state"] += 1
            return _Resp(200, {"ok": True})
        if url.endswith("/triage_tasks"):
            rec["triage"].append({"body": json, "at": clock.t})
            return _Resp(200, {"task_id": (json or {}).get("task_id"), "status": "FILED",
                               "recipients": 1})
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(dispatch_driver.requests, "post", _post)
    return rec


# ===========================================================================
# 0. THE HARNESS PROVES IT CAN AGE — both arms, same token, before anything else is believed
# ===========================================================================
@pytest.mark.asyncio
async def test_the_harness_ages_a_token(aging):
    """POSITIVE AND NEGATIVE CONTROL IN ONE RUN, on the SAME credential.

    A seal about expiry is worthless if its harness cannot expire anything, and equally worthless if
    it can ONLY report expired (then every green below is a broken-closed lie). So: mint one token,
    use it fresh -> 200; advance the clock past its TTL, present THE SAME token -> 401.

    This runs first deliberately. Everything after it reads the register's verdict as evidence, and
    that is only legitimate once the verdict has been shown to move in both directions.
    """
    tok = _mint_at(aging["clock"])
    aging["carry_token"] = tok

    await _invoke(_payload())
    assert aging["register_status"] == [200], "a FRESH token was rejected — the harness cannot pass"

    aging["clock"].advance(_TTL_S + 1)
    with pytest.raises(restate.TerminalError):
        await _invoke(_payload())
    assert aging["register_status"] == [200, 401], (
        "the SAME token did not expire when the clock passed its exp — the harness cannot fail, so "
        "no green in this file would mean anything"
    )
    assert _minted_at_of(tok) == 0.0 and _exp_of(tok) == _TTL_S


# ===========================================================================
# 1. THE SEAL — ninety minutes of human latency cannot staleness a dispatch
# ===========================================================================
@pytest.mark.asyncio
async def test_ninety_minute_suspend_does_not_stale_the_dispatch(aging):
    """THE REGRESSION GATE. Reproduce notice A's timeline exactly — a token minted when the review
    STARTS, ninety minutes of human latency, then the dispatch — and assert the credential presented
    at the register was minted AT USE, not at review start.

    Under the pre-fix code this fails on both counts: the register receives the t=0 token and answers
    401. Under mint-at-use it receives a t=5400 token and answers 200. Ninety minutes is manufactured
    by one line; the defect that hid from twelve seals for an hour is caught in milliseconds.
    """
    review_start_token = _mint_at(aging["clock"])        # what the OLD code would have captured
    # The payload is BUILT AT REVIEW-START TIME on purpose. Everything that could capture a
    # credential does so here, at t=0, before the wait — which is the pre-fix shape (the token came
    # from workflow state written when the review started). Building it after the advance would
    # quietly hand the old code a fresh credential and the seal could never bite.
    payload_captured_at_review_start = _payload()
    aging["clock"].advance(_NINETY_MINUTES)              # the human goes to lunch

    outcome = await _invoke(payload_captured_at_review_start)

    assert len(aging["register"]) == 1
    presented = aging["register"][0]["token"]
    assert presented != review_start_token, (
        "the dispatch presented the credential captured at REVIEW START — a token carried across a "
        "suspend is stale by design (docs/plans/archive/2026-08-04-notice-a-dispatch-failure.md)"
    )
    assert _minted_at_of(presented) == _NINETY_MINUTES, (
        f"credential was minted at t={_minted_at_of(presented)}, not at use (t={_NINETY_MINUTES}) — "
        "there is a staleness window between mint and use"
    )
    assert aging["register_status"] == [200]
    assert outcome["task_minted"] and outcome["state_written"]


@pytest.mark.asyncio
async def test_every_attempt_mints_its_own_credential(aging):
    """The class, not the instance. A VirtualObject RETRIES, so an attempt can land minutes after
    the one before it. Each attempt must mint for ITSELF — a token threaded between attempts is the
    same defect in miniature, just with a shorter fuse.

    Two dispatches an hour apart (distinct keys, as two parts of one notice are) => two mints, each
    contemporaneous with its own use.
    """
    await _invoke(_payload(mpn="NSR01L30NXT5G"))
    aging["clock"].advance(3600)
    await _invoke(_payload(mpn="MPN-NEEDSREVIEW"), state={})

    minted = [t for kind, t in aging["mint_calls"] if kind == "minted"]
    assert len(minted) == 2, f"expected one mint per use, got {len(minted)}"
    assert [_minted_at_of(t) for t in minted] == [0.0, 3600.0]
    assert aging["register_status"] == [200, 200]
    for call in aging["register"]:
        assert _minted_at_of(call["token"]) == call["at"], (
            "a credential outlived the attempt that minted it")


def _walk_keys(node, path=""):
    """Every key path in a nested structure. The guard below needs this because the existing
    top-level check MISSED a credential — see that test's docstring."""
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}.{k}" if path else str(k)
            yield here, v
            yield from _walk_keys(v, here)
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            yield from _walk_keys(v, f"{path}[{i}]")


# Credential-shaped field names. Deliberately broader than the one field that bit: the class is
# "a secret in durable journal state", and naming only `user_jwt` would guard the instance.
_CREDENTIAL_KEYS = ("user_jwt", "jwt", "token", "access_token", "bearer", "authorization",
                    "secret", "password", "api_key", "client_secret")


@pytest.mark.asyncio
async def test_no_credential_rides_the_journaled_payload(aging):
    """The DISCLOSURE half, which expiry does not address. A journal is readable state with a
    retention window: notice A's dead JWT was still fully legible in ``sys_journal`` an hour after
    it stopped working. Expiry bounds what a credential can DO, never what it REVEALS.

    THIS GUARD WAS TOO SHALLOW AND THE BREAK-ON-PURPOSE CAUGHT IT (2026-08-05). The first version
    asserted ``"user_jwt" not in payload`` — a TOP-LEVEL check. When the deliberate regression put
    the credential back where it would actually go, nested under ``human_task`` (the sub-dict the
    register body is built from), the guard stayed GREEN while a token rode the payload. So did the
    sibling assertion in ``test_dispatch_driver.test_fan_out_...``, which is top-level too.

    That is the whole argument for breaking a passing guard on purpose: it did not fail, and the
    reason it did not fail was a defect in the guard, not health in the code. It now walks the
    WHOLE structure and matches a family of credential-shaped names rather than the one that bit.
    """
    payload = _payload()
    offenders = [p for p, _ in _walk_keys(payload)
                 if p.rsplit(".", 1)[-1].lower() in _CREDENTIAL_KEYS]
    assert not offenders, (
        f"credential-shaped field(s) riding a journaled payload at {offenders} — mint at use, "
        f"never carry a token across a suspend")
    flat = repr(payload)
    assert "Bearer" not in flat and "eyJ" not in flat, (
        f"something credential-shaped is riding a durable payload: {flat[:300]}")


# ===========================================================================
# 2. THE RED GATE FOR ITEM 2 — a dead credential at use must be SURFACED, not just terminal
# ===========================================================================
@pytest.mark.asyncio
async def test_expired_credential_at_use_fails_terminally(aging):
    """Half of the visibility claim, and the half that already holds: an expired credential is a
    persistent denial, so it must FAIL (release the item's keyed object) rather than retry-and-park.
    Parking on a denial is the DoS the suspend-vs-fail ruling forbids."""
    aging["carry_token"] = _mint_at(aging["clock"])
    aging["clock"].advance(_TTL_S + 1)

    with pytest.raises(restate.TerminalError):
        await _invoke(_payload())
    assert aging["state"] == 0, "state was written despite the register denial — chain should stop"


@pytest.mark.asyncio
async def test_terminal_dispatch_failure_after_approval_mints_a_triage_row(aging):
    """THE ONE THAT IS RED UNTIL ITEM 2 LANDS. This is the gate the triage-mint is built behind, and
    it is committed RED ON PURPOSE so the fix has something to turn green.

    The lie it measures: **a review reads ``approved`` while its effects died silently.** A human
    believes their decision executed and NOTHING ANYWHERE DISAGREES. Terminal-and-loud is not enough
    — the workflow already suspended and settled, so the TerminalError lands in a Restate journal
    nobody reads. "approved but effects failed" is a refusal one stage later, and the
    ``extraction_refusal`` shape already proves how a refusal reaches the people who own it.

    Audience is (b) per the packet's ruling: ``dispatch_failure:<compartment>`` — the operators who
    can actually fix a 401, not the reviewer who cannot.
    """
    aging["carry_token"] = _mint_at(aging["clock"])
    aging["clock"].advance(_NINETY_MINUTES)

    with pytest.raises(restate.TerminalError):
        await _invoke(_payload(compartment="SUSTAINMENT"))

    assert aging["triage"], (
        "a dispatch died terminally AFTER a human approved it and nothing was emitted — the "
        "approval still reads settled. Emit, do not only detect."
    )
    body = aging["triage"][0]["body"]
    assert body.get("audience") == "dispatch_failure:SUSTAINMENT", (
        f"effect-failure routed to {body.get('audience')!r}; ruling (b) sends it to the operators "
        f"who own execution, never to the reviewer who owns the decision")
    assert body.get("subject_ref"), "a triage row with no subject cannot be actioned"
    payload_field = body.get("payload") or {}
    assert payload_field.get("idempotency_key") or body.get("task_id"), (
        "the row carries no handle on the dispatch that failed — unactionable")

    # TWO IDENTITIES, TWO FIELDS, NEVER MERGED. The row must name the DECIDING human
    # (`approved_by`) and separately the review's INITIATOR (`review_started_by`). Merging them is
    # what made the live row say a service had approved a human's decision.
    assert payload_field.get("approved_by") == "alice@example.com", (
        f"the effect-failure row does not name the approving human — got "
        f"{payload_field.get('approved_by')!r}. An operator cannot tell whose decision died.")
    assert payload_field.get("review_started_by") == "svc:review-starter", (
        "the review-initiator provenance was lost or overwritten by the actor")
    assert payload_field["approved_by"] != payload_field["review_started_by"], (
        "the two identities collapsed into one value — 'who decided' and 'who requested' are "
        "different facts, and conflating them is the defect this fix exists to end")


@pytest.mark.asyncio
async def test_archive_failure_still_names_the_approver(aging):
    """The no-task disposition, which the first cut of this would have reported badly.

    ``archive`` is acknowledge-only: no HumanTask, state write alone. So a terminal failure on its
    graph write has no ``human_task.requested_by`` to read, and the effect-failure row would have
    said "(unrecorded)" on the one field an operator most needs — WHOSE decision failed to take
    effect. The approver now rides the payload top-level as well, and this pins it.

    Reachability again: the emission was written against the disposition that HAPPENS to carry a
    task, and every other branch is a different input that has to arrive intact.
    """
    def _state_400(url, json=None, headers=None, timeout=None):
        if url.endswith("/write_item_state"):
            return _Resp(400, {"error": "malformed_iri"})
        if url.endswith("/triage_tasks"):
            aging["triage"].append({"body": json, "at": aging["clock"].t})
            return _Resp(200, {"task_id": (json or {}).get("task_id"), "status": "FILED"})
        raise AssertionError(f"unexpected POST {url}")

    import pytest as _pytest
    _pytest.MonkeyPatch().setattr(dispatch_driver.requests, "post", _state_400)

    with pytest.raises(restate.TerminalError):
        await _invoke(_payload("archive"))

    assert aging["triage"], "an archive dispatch died terminally after approval and said nothing"
    body = aging["triage"][0]["body"]
    pf = body.get("payload") or {}
    assert pf.get("approved_by") == "alice@example.com", (
        "the effect-failure row for a no-task disposition lost the APPROVER — with no human_task "
        "to read, the payload-level fallback is the only source, and it is the field an operator "
        "most needs")
    assert pf.get("review_started_by") == "svc:review-starter", (
        "the no-task path lost the review-initiator provenance")
    assert body.get("audience") == "dispatch_failure:SUSTAINMENT"


@pytest.mark.asyncio
async def test_ordinary_dispatch_rows_also_name_the_approver(aging):
    """THE MISATTRIBUTION WAS NEVER TRIAGE-ONLY, and fixing only the triage row would have left the
    majority of it in place. Ordinary ``pcn_disposition`` rows — the ones that land in a persona's
    queue on every successful approval — carried the same ``requested_by: svc:review-starter`` and
    named no approver at all. Proven live on EFFECTFAIL02's two SURVIVING parts.

    So the register body must carry the deciding human too. It rides in ``payload.approved_by``, NOT
    under the name ``acted_by``: the projection already has an ``acted_by`` COLUMN meaning "who
    resolved THIS row", which for a freshly-registered dispatch task must stay empty until its
    assignee acts. Two meanings behind one identifier is the collision this codebase already
    documents elsewhere, and it is avoided here by construction.
    """
    await _invoke(_payload("dispatchQualification"))

    assert aging["register_status"] == [200]
    body = aging["register"][0]["body"]
    assert (body.get("payload") or {}).get("approved_by") == "alice@example.com", (
        f"an ordinary dispatch row does not name the approving human — payload="
        f"{body.get('payload')!r}. The queue-holder cannot tell whose decision produced their work.")
    assert body.get("requested_by") == "svc:review-starter", (
        "requested_by changed meaning — it must keep recording who STARTED the review, because "
        "three surfaces read it and a meaning change there is an expand/contract migration")
    assert "acted_by" not in (body.get("payload") or {}), (
        "the upstream approver was written under the name `acted_by`, which the projection already "
        "uses for 'who resolved THIS row' — one identifier, two meanings")


@pytest.mark.asyncio
async def test_compartment_reaches_the_dispatch_payload_from_the_workflow(aging):
    """VERIFY-THE-PIPE, per-branch. The emission above proves the driver ROUTES correctly when it is
    HANDED a compartment. It says nothing about whether a compartment can ARRIVE — and a threading
    break would send every effect-failure to ``dispatch_failure:`` , which grants nobody. That is
    the reachability class: behaviour proven on the inputs GIVEN, never that they can get there.

    So this drives the REAL ``fan_out_dispatch`` (the workflow's own call site) and asserts the
    compartment lands on the payload the VirtualObject will receive.
    """
    class _Sends:
        def __init__(self):
            self.sends = []

        def object_send(self, tpe, key, arg, idempotency_key=None, **kw):
            self.sends.append(arg)

    resolutions = [
        ItemResolution(mpn=f"MPN-{i}", subject=f"http://internal/components/MPN-{i}",
                       disposition="dispatchQualification", idempotency_key=f"M32-A-WITNESS:MPN-{i}",
                       needs_review=False, override_reason=None,
                       proposed_by_ruleset="rules@abc123def456")
        for i in range(2)
    ]
    ctx = _Sends()
    dispatch_driver.fan_out_dispatch(
        ctx, resolutions, notice_fingerprint="M32-A-WITNESS", notice_id="M32-A-WITNESS",
        requested_by="svc:review-starter", acted_by="alice@example.com",
        compartment="SUSTAINMENT")

    assert len(ctx.sends) == 2
    for arg in ctx.sends:
        assert arg.get("compartment") == "SUSTAINMENT", (
            "the compartment did not reach the dispatch payload — every effect-failure from this "
            "notice would route to `dispatch_failure:` and reach NOBODY")
        # Same verify-the-pipe argument for the actor: routing it correctly when HANDED one says
        # nothing about whether it can arrive from the workflow's call site.
        assert arg.get("acted_by") == "alice@example.com", (
            "the approver did not reach the dispatch payload — every row this notice mints would "
            "be unable to name whose decision produced it")
        assert arg.get("requested_by") == "svc:review-starter"


@pytest.mark.asyncio
async def test_unroutable_effect_failure_refuses_loudly_rather_than_filing_to_nobody(aging):
    """The failure mode of the fix itself. With no compartment the audience would be
    ``dispatch_failure:``, which matches no Topaz relation — so filing it anyway would produce an
    INVISIBLE REPORT OF AN INVISIBLE FAILURE, strictly worse than refusing.

    It must fail to NONE and attest: no triage POST at all, and an error that NAMES both facts —
    the dispatch died AND the report could not be routed. An optimistic default here (guess a
    compartment, use a catch-all) would be dishonest in exactly the way this arc keeps killing.
    """
    aging["carry_token"] = _mint_at(aging["clock"])
    aging["clock"].advance(_TTL_S + 1)

    with pytest.raises(restate.TerminalError) as ei:
        await _invoke(_payload(compartment=""))

    assert not aging["triage"], "filed an effect-failure row to an audience that grants nobody"
    msg = str(ei.value)
    assert "no compartment" in msg and "grants nobody" in msg, (
        f"the refusal does not name WHY the effect-failure could not be routed: {msg}")
    assert "settled with no effects" in msg, (
        "the refusal does not state the consequence — that an approval is now settled with no "
        "effects and no triage row")


@pytest.mark.asyncio
async def test_triage_emission_does_not_swallow_the_terminal_failure(aging):
    """The error path is itself an error surface. Emitting the triage row must not CONVERT a failed
    dispatch into a successful-looking one: the TerminalError still propagates (so Restate records
    the failure and the item's object is released), and the exactly-one marker is NOT set — the
    dispatch did not happen, and no durable state may claim it did."""
    aging["carry_token"] = _mint_at(aging["clock"])
    aging["clock"].advance(_TTL_S + 1)
    state: dict = {}

    with pytest.raises(restate.TerminalError):
        await _invoke(_payload(), state=state)

    assert state.get("dispatched") is None, (
        "the exactly-one marker was set on a dispatch that FAILED — a later redelivery would now "
        "no-op and the effect would never happen")
