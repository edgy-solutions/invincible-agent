"""A case that returns to PROPOSED proposes against the newest picture of its event, not the first.

A maintenance case lasts days. When it comes back to proposed -- rejected, refused by the
supervisor or the tier, reopened after escalation, or a parked revisit -- the spares and the
battle condition may have moved. RULED (2026-10-02/03):

* SOURCE. The bridge PUSHES a newer picture as the same event_id again; it runs through intake
  and is appended to the episode's chain. A PULL is the SDK's ``RefreshSpec`` on the trigger; the
  runner refuses one until it holds the seeding delegate's credential (RULED 2026-10-06: the
  ``pull:`` stub verb echoed the kept push and added nothing, and its revision shape was a local
  reimplementation of the SDK's). ``refresh_url`` -- the pure half -- is sealed here.
* PLACEMENT, A ROW ATTRIBUTE. ``refresh_input: true`` on the chaining rows that return to proposed.
* REVISION, THE SDK's ``ArtifactRevision`` (RULED 2026-10-06). The case keeps
  ``input_revisions[]`` -- the chain as it READ it, ``{rev, received_at, provenance, supersedes}``
  with each revision's OWN ``ProvenanceBlock``; every instance sees ``input.revision`` and every
  option cites it. The original event is revision 1, supersedes nothing; the holder's claim plants
  it as the episode chain's head, and each push appends ``rev + 1`` superseding the head. No store
  write.
* ORDER, NEWEST RECEIVED (ruled 2026-10-03), NOW THE CHAIN'S. A push received BEFORE the head is
  refused at the door, so ``rev`` order is receipt order and the reader takes the head -- no sort.
  One clock tick is not "before": both are appended, in arrival order.

The cluster double is the case runner's own; the policy is the REAL overlay.

Run: uv run --frozen pytest tests/test_a_return_to_proposed_reads_the_newest_picture.py -v
"""
from __future__ import annotations

import copy
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import (
    DOOR_BLOCK, R, _answer, _body, _Cluster, _Ctx, _Promise, _refused, main, restate, wd, wr)
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 -- fixtures
    ACK, DECIDE, REVIEW, TRIGGER, _event, _path, _real_policy, registered)

import decision_table as dt  # noqa: E402 -- on sys.path via the runner test's import
import iagent_mesh.ingest as sdk_ingest  # noqa: E402
from iagent_mesh.provenance import AS_OF_UNKNOWN, DIRECT, make_provenance  # noqa: E402


#: Every ``_now_iso`` in these arms is one second after the last, so ORDER (by ``received_at``)
#: is an input here, not a race. The wall clock on this box returned one value for 1992 of 1999
#: back-to-back reads (Python 3.12, Windows). Measured 2026-10-03: with the real clock this file is
#: still green, because enough work separates a case's receipt from the push -- the fixture
#: removes a race, it does not hide a red.
_T0 = datetime(2026, 10, 3, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _ticking_clock(monkeypatch):
    tick = itertools.count(1)
    monkeypatch.setattr(main, "_now_iso", lambda: (_T0 + timedelta(seconds=next(tick))).isoformat())


def _at(s):
    return (_T0 + timedelta(seconds=s)).isoformat()


def _push_block(tag="push"):
    """A pushed revision's OWN provenance, as the event door builds it for a resend."""
    return make_provenance(
        authoritative_source="unconfirmed-at-intake", obtained_via=DIRECT, as_of=AS_OF_UNKNOWN,
        ingested_at="2026-10-06T00:00:01Z", ingest_run=f"event:{tag}", standing="supervised",
        ingest_id=tag)


def _head(at=0, facts=None):
    """An episode's chain head as the holder's claim plants it: revision 1 and its event."""
    return {"revision": R.first_revision(_at(at), DOOR_BLOCK).model_dump(),
            "facts": facts if facts is not None else {"orig": 1}}


# ── a double that lets a revision arrive WHILE an instance waits ────────────────────────────

class _HookCtx(_Ctx):
    def promise(self, name, type_hint=None):
        p = _Promise(self, name)
        hook = self.cluster.before.pop((self._key, name), None)
        if hook is None:
            return p

        class _Hooked:
            def value(_s):
                async def _v():
                    await hook()
                    return await p.value()
                return _v()

            async def resolve(_s, payload):
                await p.resolve(payload)
        return _Hooked()


class _RevCluster(_Cluster):
    def __init__(self, answers=None):
        super().__init__(answers)
        self.before: dict = {}

    def ctx(self, key):
        return self.ctxs.setdefault(key, _HookCtx(self, key))

    def invocation(self, key):
        """A NEW invocation on ``key``: its own journal, the key's shared state."""
        fresh = _HookCtx(self, key)
        fresh.state = self.ctx(key).state
        return fresh

    async def revise(self, key, facts, provenance="default"):
        req = {"facts": copy.deepcopy(facts)}
        if provenance == "default":
            provenance = _push_block()
        if provenance is not None:
            req["provenance"] = provenance
        return await _body(wr.revise)(self.invocation(key), req)


def _script(key, answers):
    out = {}
    for n, a in enumerate(answers, start=1):
        if a is None:
            continue
        promise, verb, who = (*a, "m@x") if len(a) == 2 else a
        out[(f"{key}~{n}", promise)] = _answer(verb, who, f"because {n}")
    return out


async def _start(c, event):
    try:
        return await c.start(event["event_id"], TRIGGER, copy.deepcopy(event))
    except Exception as exc:  # noqa: BLE001 -- a case that did not CLOSE is the arm's red
        raise AssertionError(
            f"the case ended in {type(exc).__name__}: {exc}; "
            f"case={c.case(event['event_id'])}") from exc


#: The newer picture: the asset became mission-essential and a nearer site has stock.
def _newer():
    ev = _event(me=True)
    ev["picture"]["nearest_spare"] = {"site": "SITE-C", "on_hand": 9,
                                      "as_of": "2026-10-03T00:00:00Z", "lead_time_days": 1,
                                      "lead_time_source": "supply-system"}
    return ev


def _spec(c, n, key="EV-1"):
    return c.ctx(key).state[f"instance:{n}"]


def _opts(c, n, key="EV-1"):
    """The options instance ``n`` rendered, as the case carried them to instance ``n+1``."""
    return _spec(c, n + 1, key)["outputs"]["maint_fault_propose"]["options"]


# ── THE CLAIM ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_REJECTION_REPROPOSES_AGAINST_THE_PUSHED_REVISION(registered):
    """The maintainer rejects; the bridge pushed a newer picture meanwhile. The second proposal
    reads it: its options cite revision 2 and the new nearest site, and the CHAINING reads it too --
    replace_now on a now mission-essential asset goes to the supervisor."""
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected"), (DECIDE, "replace_now"),
                                     (REVIEW, "approved", "s@x"), (ACK, "released", "tier@x")]))
    kept = []
    c.before[("EV-1~1", DECIDE)] = lambda: _keep(c, kept)
    out = await _start(c, _event(me=False))

    assert kept == [{"case_id": "EV-1", "revision": 2}], kept
    assert [h[2] for h in _path(out)] == [
        "maint_fault_propose", "maint_fault_propose", "maint_supervisor_review", "maint_release",
        "closed"], _path(out)
    revs = c.case("EV-1")["input_revisions"]
    # EACH REVISION CARRIES ITS OWN PROVENANCE: rev 1 the event door's, rev 2 the push's.
    assert [(r["rev"], r["supersedes"], r["provenance"]["ingest_run"]) for r in revs] == [
        (1, None, "event:evt-test"), (2, 1, "event:push")], revs
    assert [sdk_ingest.ArtifactRevision.model_validate(r).model_dump() for r in revs] == revs
    assert all(r["received_at"] for r in revs), revs
    assert [_spec(c, n)["input"]["supersedes"] for n in (1, 2)] == [None, 1]
    assert [_spec(c, n)["input"]["revision"] for n in (1, 2, 3, 4)] == [1, 2, 2, 2]
    assert {o["input_revision"] for o in _opts(c, 1)} == {1}
    assert {o["input_revision"] for o in _opts(c, 2)} == {2}
    assert _opts(c, 1)[1]["nearest_spare"]["site"] == "SITE-B"
    assert _opts(c, 2)[1]["nearest_spare"]["site"] == "SITE-C"
    hop = out["transitions"][3]
    assert (hop["outcome"], hop["to"], hop.get("input_revision")) == (
        "rejected", "maint_fault_propose", 2), hop


async def _keep(c, sink, facts=None):
    sink.append(await c.revise("EV-1", facts or _newer()))


@pytest.mark.asyncio
async def test_CONTROL_WITHOUT_A_REVISION_THE_SAME_ANSWERS_SKIP_THE_SUPERVISOR(registered):
    """The arm above is red only because of the revision: the same answers on the first picture
    release without a supervisor, and the refresh still records which revision it read."""
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected"), (DECIDE, "replace_now"),
                                     (ACK, "released", "tier@x")]))
    out = await _start(c, _event(me=False))
    assert [h[2] for h in _path(out)] == [
        "maint_fault_propose", "maint_fault_propose", "maint_release", "closed"], _path(out)
    assert [r["rev"] for r in c.case("EV-1")["input_revisions"]] == [1]
    assert out["transitions"][3].get("input_revision") == 1, out["transitions"][3]


@pytest.mark.asyncio
async def test_A_ROW_WITHOUT_REFRESH_KEEPS_THE_INPUT_IT_HAD(registered):
    """The refresh is the ROW's: approve -> release carries no `refresh_input`, so a revision kept
    while the maintainer decided is not read by the release, and the hop names no revision."""
    c = _RevCluster(_script("EV-1", [(DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    kept = []
    c.before[("EV-1~1", DECIDE)] = lambda: _keep(c, kept)
    out = await _start(c, _event(me=False))
    assert kept and [r["rev"] for r in c.case("EV-1")["input_revisions"]] == [1]
    assert _spec(c, 2)["input"]["revision"] == 1
    assert "input_revision" not in out["transitions"][3], out["transitions"][3]


@pytest.mark.asyncio
async def test_THE_NEWEST_OF_SEVERAL_PUSHES_IS_READ(registered):
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected"), (DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    kept = []
    older = _event(me=False)
    older["picture"]["nearest_spare"]["site"] = "SITE-OLD"

    async def _two():
        await _keep(c, kept, older)
        await _keep(c, kept, _newer())
    c.before[("EV-1~1", DECIDE)] = _two
    await _start(c, _event(me=False))
    assert [k["revision"] for k in kept] == [2, 3], kept
    # The case READ 1 and then the head, 3; 3 supersedes 2, which the case never read.
    assert [(r["rev"], r["supersedes"]) for r in c.case("EV-1")["input_revisions"]] == [
        (1, None), (3, 2)]
    assert _opts(c, 2)[1]["nearest_spare"]["site"] == "SITE-C"


@pytest.mark.asyncio
async def test_A_SECOND_RETURN_SKIPS_WHAT_THE_FIRST_READ_AND_READS_WHAT_CAME_AFTER(registered):
    """The floor carries forward: a later refresh compares against the revision the last one READ,
    so the same kept revision is not re-read, and a push after it still is."""
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected"), (DECIDE, "rejected"),
                                     (DECIDE, "rejected"), (DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    kept = []
    third = _newer()
    third["picture"]["nearest_spare"]["site"] = "SITE-D"
    c.before[("EV-1~1", DECIDE)] = lambda: _keep(c, kept)
    c.before[("EV-1~3", DECIDE)] = lambda: _keep(c, kept, third)
    await _start(c, _event(me=False))
    assert [k["revision"] for k in kept] == [2, 3], kept
    assert [r["rev"] for r in c.case("EV-1")["input_revisions"]] == [1, 2, 3]
    assert [_spec(c, n)["input"]["revision"] for n in (1, 2, 3, 4)] == [1, 2, 2, 3]
    assert _opts(c, 4)[1]["nearest_spare"]["site"] == "SITE-D"


@pytest.mark.asyncio
async def test_TWO_PUSHES_IN_ONE_CLOCK_TICK_ARE_BOTH_READ_IN_ORDER(registered, monkeypatch):
    """The clock never moves: the case and both pushes share one instant. One tick is not
    "before", so ``next_revision`` appends both, and ``rev`` -- counted on arrival -- orders them."""
    monkeypatch.setattr(main, "_now_iso", lambda: _at(0))
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected"), (DECIDE, "rejected"),
                                     (DECIDE, "rejected"), (DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    kept = []
    third = _newer()
    third["picture"]["nearest_spare"]["site"] = "SITE-D"
    c.before[("EV-1~1", DECIDE)] = lambda: _keep(c, kept)
    c.before[("EV-1~3", DECIDE)] = lambda: _keep(c, kept, third)
    await _start(c, _event(me=False))
    revs = c.case("EV-1")["input_revisions"]
    assert {r["received_at"] for r in revs} == {_at(0)}, revs
    assert [r["rev"] for r in revs] == [1, 2, 3], revs
    assert [_spec(c, n)["input"]["revision"] for n in (1, 2, 3, 4)] == [1, 2, 2, 3]
    assert _opts(c, 4)[1]["nearest_spare"]["site"] == "SITE-D"


# ── THE CHAIN: the SDK's ArtifactRevision, built by the runner ─────────────────────────────

def test_THE_CHAIN_STARTS_AT_ONE_AND_EACH_REVISION_SUPERSEDES_THE_HEAD():
    one = R.first_revision(_at(0), DOOR_BLOCK)
    two = R.next_revision(one, _at(1), _push_block("p2"))
    three = R.next_revision(two.model_dump(), _at(2), _push_block("p3"))
    assert [(r.rev, r.supersedes) for r in (one, two, three)] == [(1, None), (2, 1), (3, 2)]
    assert {type(r) for r in (one, two, three)} == {sdk_ingest.ArtifactRevision}
    assert three.provenance.ingest_run == "event:p3", three


def test_A_RECEIPT_BEFORE_THE_HEAD_IS_REFUSED_COMPARED_AS_INSTANTS():
    """Spelled in another zone: ``01:00:01+01:00`` is BEFORE a head at ``00:00:02Z`` though it
    sorts after it as a string, and ``01:00:02+01:00`` is the same instant -- not before."""
    head = R.next_revision(R.first_revision(_at(0), DOOR_BLOCK), _at(2), _push_block())
    with pytest.raises(R.CaseRoutingError, match="do not run backwards"):
        R.next_revision(head, "2026-10-03T01:00:01+01:00", _push_block())
    assert R.next_revision(head, "2026-10-03T01:00:02+01:00", _push_block()).rev == 3
    assert R.next_revision(head, _at(2), _push_block()).rev == 3


_UNORDERABLE = [None, "t", 1759449600, "2026-10-03T00:00:05"]


@pytest.mark.parametrize("at", _UNORDERABLE)
def test_A_REVISION_WHOSE_RECEIPT_CANNOT_BE_ORDERED_IS_REFUSED(at):
    """Missing, unparseable, not a string, or NAIVE: a naive time cannot be ordered against an
    aware one without inventing a zone."""
    with pytest.raises(R.CaseRoutingError, match="with its zone"):
        R.first_revision(at, DOOR_BLOCK)
    with pytest.raises(R.CaseRoutingError, match="with its zone"):
        R.next_revision(R.first_revision(_at(0), DOOR_BLOCK), at, _push_block())


_BAD_BLOCKS = [None, {}, {**DOOR_BLOCK, "obtained_via": "pushed"}, {**DOOR_BLOCK, "pulled": True}]


@pytest.mark.parametrize("block", _BAD_BLOCKS)
def test_A_REVISION_WITHOUT_ITS_OWN_PROVENANCE_BLOCK_IS_REFUSED(block):
    with pytest.raises(R.CaseRoutingError, match="provenance"):
        R.first_revision(_at(0), block)
    with pytest.raises(R.CaseRoutingError, match="provenance"):
        R.next_revision(R.first_revision(_at(0), DOOR_BLOCK), _at(1), block)


@pytest.mark.parametrize("head", [None, {"rev": 2, "received_at": _at(0)},
                                  {"rev": 2, "received_at": _at(0), "provenance": DOOR_BLOCK}])
def test_A_HEAD_THAT_IS_NOT_AN_ARTIFACT_REVISION_IS_REFUSED(head):
    """The last: rev 2 with no ``supersedes`` -- the SDK's own chain rule refuses it."""
    with pytest.raises(R.CaseRoutingError, match="not an ArtifactRevision"):
        R.next_revision(head, _at(1), _push_block())


def test_THE_HEAD_IS_NEWER_ONLY_FURTHER_ALONG_THE_CHAIN():
    head = R.next_revision(R.first_revision(_at(0), DOOR_BLOCK), _at(1), _push_block())
    kept = {"revision": head.model_dump(), "facts": {"b": 1}}
    assert R.newer_revision(1, kept) == kept
    assert R.newer_revision(2, kept) is None
    assert R.newer_revision(3, kept) is None
    assert R.newer_revision(1, None) is None


@pytest.mark.parametrize("kept, why", [
    ("rev 2", "and the event's `facts`"),
    ({"revision": None, "facts": {}}, "not an ArtifactRevision"),
    ({"revision": {"rev": 2, "received_at": _at(1), "provenance": "pushed", "supersedes": 1},
      "facts": {}}, "not an ArtifactRevision"),
    ({"revision": {"rev": 2, "received_at": _at(1), "provenance": DOOR_BLOCK, "supersedes": 1},
      "facts": None}, "and the event's `facts`"),
])
def test_A_KEPT_REVISION_IS_REVALIDATED_WHEN_READ(kept, why):
    with pytest.raises(R.CaseRoutingError, match=why):
        R.newer_revision(1, kept)


# ── THE PULL: the SDK's RefreshSpec, refused until the delegate exists ─────────────────────

def _trigger(**extra):
    return {**R.load_trigger(TRIGGER).model_dump(exclude={"refresh"}), **extra}


_SPEC = {"url_template": "https://picture.example/fault/{event_id}", "method": "GET",
         "auth": "seeding-delegate"}


@pytest.mark.parametrize("refresh, why", [
    (_SPEC, "cannot pull"),
    ({**_SPEC, "url_template": "https://picture.example/fault/{asset_id}"}, "must carry"),
    ({**_SPEC, "auth": "caller"}, "seeding-delegate"),
])
def test_A_TRIGGER_THAT_DECLARES_A_REFRESH_IS_REFUSED(refresh, why):
    with pytest.raises(ValueError, match=why):
        R.Trigger.model_validate(_trigger(refresh=refresh))


def test_CONTROL_THE_SAME_TRIGGER_WITHOUT_A_REFRESH_LOADS():
    assert R.Trigger.model_validate(_trigger()).refresh is None


def test_THE_RETIRED_PULL_KEY_IS_REFUSED_NOT_DROPPED():
    with pytest.raises(ValueError, match="pull"):
        R.Trigger.model_validate(_trigger(pull="maintenance_picture_read"))


def test_NO_SHIPPED_TRIGGER_DECLARES_A_REFRESH_AND_THE_PULL_STUB_IS_GONE():
    triggers = R.load_triggers()
    # POPULATION: the walk reaches the trigger whose stub this ruling retired.
    assert TRIGGER in triggers, sorted(triggers)
    assert {k: t.refresh for k, t in triggers.items() if t.refresh is not None} == {}
    assert "maintenance_picture_read" not in wd.load_stub_verbs()


def test_A_PULL_URL_IS_THE_EVENTS_KEY_FILLED():
    spec = sdk_ingest.RefreshSpec(**_SPEC)
    assert R.refresh_url(spec, "event_id", "EV-417") == "https://picture.example/fault/EV-417"


@pytest.mark.parametrize("value", [None, "", "  "])
def test_A_PULL_FOR_NO_EVENT_IS_REFUSED(value):
    with pytest.raises(R.CaseRoutingError, match="a pull needs the event's 'event_id'"):
        R.refresh_url(sdk_ingest.RefreshSpec(**_SPEC), "event_id", value)


def test_A_PULL_URL_KEYED_ON_ANOTHER_FACT_IS_REFUSED():
    spec = sdk_ingest.RefreshSpec(**{**_SPEC, "url_template": "https://p.example/{asset_id}"})
    with pytest.raises(R.CaseRoutingError, match="must carry {event_id}"):
        R.refresh_url(spec, "event_id", "EV-417")


# ── THE DOOR: what a revision must be ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_REVISION_OF_NO_CASE_IS_REFUSED():
    c = _RevCluster()
    await _refused(c.revise("EV-9", _event("EV-9")), 404)


@pytest.mark.asyncio
async def test_A_REVISION_FOR_A_CLOSED_CASE_KEEPS_NOTHING(registered):
    c = _RevCluster(_script("EV-1", [(DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    await _start(c, _event())
    await _refused(c.revise("EV-1", _newer()), 409)
    assert not any("revision" in o.state for o in c.objs.values()), c.objs


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate, status", [
    (lambda e: e.update(asset_id="AST-8"), 400),                    # another episode
    (lambda e: e["picture"]["battle_condition"].pop("mission_essential"), 400),  # requires
    (lambda e: e["picture"].pop("nearest_spare"), 400),             # carries
    (lambda e: e.update(event_id="EV-2"), 400),                     # not this case's event
])
async def test_A_REVISION_PASSES_THE_SAME_INTAKE_AND_STAYS_IN_ITS_EPISODE(
        registered, mutate, status):
    c = _RevCluster(_script("EV-1", [(DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    bad = _newer()
    mutate(bad)
    seen = []

    async def _try():
        with pytest.raises(restate.TerminalError) as exc:
            await c.revise("EV-1", bad)
        seen.append(exc.value.status_code)
        # CONTROL: the same door, the same moment, an unmutated revision is kept.
        seen.append((await c.revise("EV-1", _newer()))["revision"])
    c.before[("EV-1~1", DECIDE)] = _try
    await _start(c, _event())
    assert seen == [status, 2], seen


@pytest.mark.asyncio
@pytest.mark.parametrize("block", _BAD_BLOCKS)
async def test_A_CASE_WHOSE_TRIGGER_KEEPS_A_CHAIN_OPENS_ONLY_WITH_ITS_PROVENANCE(registered, block):
    """The maintenance trigger declares an episode, so its case keeps a chain from revision 1,
    whose provenance comes with the event. Absent or malformed, the case is the caller's 400 AT
    INTAKE, naming the provenance: without the intake check an absent block still ends in a 400,
    but from the first instance's render of ``{input.revision}``, after the case was recorded and
    its episode claimed (measured 2026-10-06) -- the status alone cannot tell the two apart."""
    c = _RevCluster(_script("EV-1", [(DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    why = await _refused(c.start("EV-1", TRIGGER, _event(), provenance=block), 400)
    assert ("keeps a revision chain" if block is None else "carries a `provenance` block") in why, why
    assert c.case("EV-1") is None, c.case("EV-1")
    assert not any(o.state.get("open") for o in c.objs.values()), c.objs
    # CONTROL: the same event with the door's block opens and closes.
    c2 = _RevCluster(_script("EV-1", [(DECIDE, "replace_after_resupply"),
                                      (ACK, "released", "tier@x")]))
    assert (await _start(c2, _event()))["status"] == "CLOSED"


@pytest.mark.asyncio
@pytest.mark.parametrize("block", _BAD_BLOCKS)
async def test_A_PUSH_WITHOUT_ITS_OWN_PROVENANCE_IS_REFUSED(registered, block):
    c = _RevCluster(_script("EV-1", [(DECIDE, "replace_after_resupply"),
                                     (ACK, "released", "tier@x")]))
    seen = []

    async def _try():
        with pytest.raises(restate.TerminalError) as exc:
            await c.revise("EV-1", _newer(), provenance=block)
        seen.append(exc.value.status_code)
        # CONTROL: the same door, the same moment, the same picture with its block is kept.
        seen.append((await c.revise("EV-1", _newer()))["revision"])
    c.before[("EV-1~1", DECIDE)] = _try
    await _start(c, _event())
    assert seen == [400, 2], seen


def _keep_req(case_id="EV-1", at=_at(1), facts=None, provenance="default"):
    return {"case_id": case_id, "facts": {"x": 1} if facts is None else facts,
            "received_at": at,
            "provenance": _push_block() if provenance == "default" else provenance}


def _held(head=True):
    o = _RevCluster().obj("ep")
    o.state["open"] = "EV-1"
    if head:
        o.state["revision"] = _head()
    return o


@pytest.mark.asyncio
async def test_ANOTHER_CASES_EVENT_KEEPS_NOTHING_ON_THIS_EPISODE():
    o = _held()
    before = copy.deepcopy(o.state["revision"])
    await _refused(_body(wr.keep_revision)(o, _keep_req(case_id="EV-2")), 409)
    assert o.state["revision"] == before


@pytest.mark.asyncio
async def test_A_HOLDER_WITH_NO_REVISION_ONE_KEEPS_NOTHING():
    """A chain is appended AFTER its head; a holder whose claim planted none has nothing to
    supersede, and inventing a rev 1 here would cite an event nobody received."""
    o = _held(head=False)
    await _refused(_body(wr.keep_revision)(o, _keep_req()), 409)
    assert o.state.get("revision") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("req", [
    _keep_req(facts="not the event"),
    _keep_req(at="2026-10-02T23:59:59+00:00"),       # before the head
    _keep_req(provenance=None),
    *[_keep_req(at=a) for a in _UNORDERABLE],
])
async def test_A_REVISION_THE_CHAIN_COULD_NOT_HOLD_IS_REFUSED_AT_THE_DOOR(req):
    """``keep_revision`` is on the ingress: refused here it is the caller's 400, where kept it
    would fail the holder's case at its next refresh. The head is untouched."""
    o = _held()
    before = copy.deepcopy(o.state["revision"])
    await _refused(_body(wr.keep_revision)(o, req), 400)
    assert o.state["revision"] == before


@pytest.mark.asyncio
async def test_CONTROL_A_PUSH_AFTER_THE_HEAD_IS_APPENDED():
    o = _held()
    assert await _body(wr.keep_revision)(o, _keep_req()) == {"case_id": "EV-1", "revision": 2}
    assert (o.state["revision"]["revision"]["rev"],
            o.state["revision"]["revision"]["supersedes"]) == (2, 1)


@pytest.mark.asyncio
async def test_AN_ATTACHED_DUPLICATE_DOES_NOT_REPLACE_THE_HOLDERS_CHAIN():
    o = _held()
    before = copy.deepcopy(o.state["revision"])
    assert await _body(wr.claim)(o, {"case_id": "EV-2", "head": _head(5, {"dup": 1})}) == "EV-1"
    assert o.state["revision"] == before


@pytest.mark.asyncio
async def test_A_KEPT_REVISION_IN_ANOTHER_EPISODE_FAILS_THE_CASE(registered):
    """``keep_revision`` is reachable directly, past ``revise``'s intake: the refresh checks what
    it reads again, and a picture of another asset fails the case rather than becoming its input."""
    moved = _newer()
    moved["asset_id"] = "AST-8"
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected")]))

    async def _plant():
        [ep] = [o for o in c.objs.values() if o.state.get("open") == "EV-1"]
        await _body(wr.keep_revision)(ep, _keep_req(facts=moved))
    c.before[("EV-1~1", DECIDE)] = _plant
    await _refused(c.start("EV-1", TRIGGER, _event()), 422)
    assert c.case("EV-1")["transitions"][-1]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_RELEASE_DROPS_THE_CHAIN_WITH_THE_EPISODE():
    """The next case on this episode opens on its own event, as revision 1; the last case's
    chain would otherwise be its 'newest picture'."""
    o = _held()
    assert await _body(wr.keep_revision)(o, _keep_req()) == {"case_id": "EV-1", "revision": 2}
    await _body(wr.release)(o, {"case_id": "EV-1"})
    own = _head(9, {"next": 1})
    assert await _body(wr.claim)(o, {"case_id": "EV-2", "head": own}) == "EV-2"
    assert await _body(wr.newest_revision)(o, {"case_id": "EV-2"}) == own


# ── THE ROW ATTRIBUTE ───────────────────────────────────────────────────────────────────────

_T = {"decision": "t", "matches": ["outcome"], "domain": {"outcome": ["a", "b"]},
      "terminals": ["done"],
      "rows": [{"when": {"outcome": "a"}, "then": "p"}, {"when": {"outcome": "b"}, "then": "done"}]}


@pytest.mark.parametrize("row, why", [
    ({"when": {"outcome": "a"}, "then": "p", "refresh_input": "yes"}, "true or false"),
    ({"when": {"outcome": "b"}, "then": "done", "refresh_input": True}, "terminal"),
    ({"when": {"outcome": "a"}, "then": "p", "refresh_inputs": True}, "may carry only"),
])
def test_A_REFRESH_THE_RUNNER_COULD_NOT_HONOUR_IS_REFUSED(row, why):
    i = 0 if row["when"]["outcome"] == "a" else 1
    t = copy.deepcopy(_T)
    t["rows"][i] = row
    with pytest.raises(dt.DecisionError, match=why):
        dt.decide(t, {"outcome": row["when"]["outcome"]})


def test_CONTROL_A_DECLARED_REFRESH_IS_DECIDED_AND_ABSENT_IS_FALSE():
    t = copy.deepcopy(_T)
    t["rows"][0]["refresh_input"] = True
    assert dt.decide(t, {"outcome": "a"}).refresh_input is True
    assert dt.decide(_T, {"outcome": "a"}).refresh_input is False


def test_EVERY_SHIPPED_ROW_IS_ONE_THE_RUNNER_CAN_HONOUR():
    """Build time, by the same function the runtime calls on the decided row."""
    tables = dt.load_tables()
    refreshing = {(n, r["then"]) for n, t in tables.items()
                  for i, r in enumerate(t.get("rows") or []) if dt.row_refreshes(t, i)}
    # POPULATION: the walk reaches the rows this ruling placed, so it is not passing on nothing.
    assert ("maint_fault_park_chaining", "maint_fault_propose") in refreshing, refreshing


def test_EVERY_ROW_THAT_RETURNS_TO_PROPOSED_REFRESHES():
    """'Decision rows place it at proposed and revisit': derived from the rows, not listed. A
    CHAINING row only -- selection opens the first proposal on the event itself, revision 1."""
    tables = dt.load_tables()
    chaining = {t["decision"] for t in R.chaining_index(tables).values()}
    back = [(n, i) for n, t in tables.items() if n in chaining
            for i, r in enumerate(t.get("rows") or []) if r.get("then") == "maint_fault_propose"]
    assert len(back) >= 5, back
    assert [(n, i) for n, i in back if not tables[n]["rows"][i].get("refresh_input")] == []


def test_EVERY_OPTION_CITES_THE_INPUT_REVISION():
    defn = wd.get_workflow_definition("maint_fault_propose")
    [render] = [s for s in defn.steps if s.kind == "render"]
    assert [o.get("input_revision") for o in render.template] == ["{input.revision}"] * 4
