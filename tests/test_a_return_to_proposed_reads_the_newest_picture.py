"""A case that returns to PROPOSED proposes against the newest picture of its event, not the first.

A maintenance case lasts days. When it comes back to proposed -- rejected, refused by the
supervisor or the tier, reopened after escalation, or a parked revisit -- the spares and the
battle condition may have moved. RULED (2026-10-02/03):

* SOURCE, BOTH IN ORDER. The bridge PUSHES a newer picture as the same event_id again; it runs
  through intake and is kept on the episode as revision k. A PULL verb is declared as a stub that
  returns the newest kept revision; when OpenDDIL's picture endpoint exists the same step reads the
  newest of pushed-or-pulled. Same step, two sources, no second mechanism later.
* PLACEMENT, A ROW ATTRIBUTE. ``refresh_input: true`` on the chaining rows that return to proposed.
* REVISION, A CASE INPUT REVISION. The case keeps ``input_revisions[]`` ({rev, event_id,
  received_at, provenance}); every instance sees ``input.revision`` and every option cites it.
  The original event is revision 1. No store write.
* ORDER, NEWEST RECEIVED (ruled 2026-10-03). The newest ``received_at`` wins; on a tie the pulled
  one, because it was asked for. Both are revisions of one artifact: an ordering rule, not a merge.

The cluster double is the case runner's own; the policy is the REAL overlay.

Run: uv run --frozen pytest tests/test_a_return_to_proposed_reads_the_newest_picture.py -v
"""
from __future__ import annotations

import copy
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import (
    R, _answer, _body, _Cluster, _Ctx, _Promise, _refused, main, restate, wd, wr)
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 -- fixtures
    ACK, DECIDE, REVIEW, TRIGGER, _event, _path, _real_policy, registered)

import decision_table as dt  # noqa: E402 -- on sys.path via the runner test's import


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


#: A case's current input, as the runner passes it: revision 1, received at the start.
_CUR = {"revision": 1, "received_at": _at(0)}


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

    async def revise(self, key, facts):
        return await _body(wr.revise)(self.invocation(key), {"facts": copy.deepcopy(facts)})


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
    assert [(r["rev"], r["event_id"], r["provenance"]) for r in revs] == [
        (1, "EV-1", "pushed"), (2, "EV-1", "pushed")], revs
    assert all(r["received_at"] for r in revs), revs
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
    assert [r["rev"] for r in c.case("EV-1")["input_revisions"]] == [1, 3]
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


# ── THE PULL SOURCE ─────────────────────────────────────────────────────────────────────────

def _stubs_with(monkeypatch, returns):
    real = wd.load_stub_verbs

    def _load():
        out = dict(real())
        out["maintenance_picture_read"] = wd.StubVerb.model_validate({
            "verb": "maintenance_picture_read", "stub": True, "retired_by": "test",
            "returns": returns})
        return out
    monkeypatch.setattr(wd, "load_stub_verbs", _load)


@pytest.mark.asyncio
async def test_A_NEWER_PULLED_PICTURE_IS_READ_AND_SAYS_IT_WAS_PULLED(registered, monkeypatch):
    """The second source: what the pull verb returns. A pulled revision above the current one
    replaces the input exactly as a pushed one would, and the record says it was pulled."""
    _stubs_with(monkeypatch, {"rev": 5, "event_id": "EV-1", "received_at": "2099-01-01T00:00:00Z",
                              "facts": _newer()})
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected"), (DECIDE, "replace_now"),
                                     (REVIEW, "approved", "s@x"), (ACK, "released", "tier@x")]))
    out = await _start(c, _event(me=False))
    revs = c.case("EV-1")["input_revisions"]
    assert [(r["rev"], r["provenance"]) for r in revs] == [(1, "pushed"), (5, "pulled")], revs
    assert "maint_supervisor_review" in [h[2] for h in _path(out)], _path(out)
    assert {o["input_revision"] for o in _opts(c, 2)} == {5}


@pytest.mark.asyncio
async def test_THE_SHIPPED_PULL_STUB_ECHOES_THE_KEPT_REVISION_AND_IT_STAYS_PUSHED(registered):
    """The shipped stub returns ``{kept}``: the SAME revision reached twice, which is not a tie, so
    it keeps its pushed provenance and pulling adds nothing until the endpoint is served."""
    stub = wd.load_stub_verbs()["maintenance_picture_read"]
    assert stub.returns == "{kept}" and stub.stub is True, stub
    kept = {"rev": 2, "event_id": "E", "received_at": _at(1), "facts": {"a": 1},
            "provenance": "pushed"}
    assert main._render(stub.returns, {"kept": kept}, where="t") == kept
    assert main._render(stub.returns, {"kept": None}, where="t") is None
    pulled = {**kept, "provenance": "pulled"}
    assert R.newest_revision(_CUR, [kept, pulled])["provenance"] == "pushed"
    assert R.newest_revision(_CUR, [pulled, kept])["provenance"] == "pushed"
    assert R.newest_revision(_CUR, [None, pulled])["provenance"] == "pulled"
    assert R.newest_revision({"revision": 2, "received_at": _at(1)}, [kept, pulled]) is None


def test_THE_NEWEST_RECEIVED_WINS_WHATEVER_ITS_REV_OR_SOURCE():
    """``rev`` labels a revision; it does not order one. A pulled picture received after a pushed
    one wins even with the lower rev, and a pushed one received later still beats it."""
    pushed = {"rev": 7, "received_at": _at(2), "facts": {}, "provenance": "pushed"}
    pulled = {"rev": 5, "received_at": _at(3), "facts": {}, "provenance": "pulled"}
    assert R.newest_revision(_CUR, [pushed, pulled]) is pulled
    assert R.newest_revision(_CUR, [pulled, pushed]) is pulled
    later = {**pushed, "received_at": _at(4)}
    assert R.newest_revision(_CUR, [later, pulled]) is later
    assert R.newest_revision(_CUR, [pulled, later]) is later


def test_ON_A_TIE_THE_PULLED_PICTURE_WINS_BECAUSE_IT_WAS_ASKED_FOR():
    """Two DIFFERENT pictures received at one instant -- compared as instants, not as strings
    (the pushed one's spelling sorts AFTER the pulled one's), and different by facts alone."""
    pushed = {"rev": 2, "received_at": "2026-10-03T01:00:02+01:00", "facts": {"a": 1},
              "provenance": "pushed"}
    pulled = {"rev": 2, "received_at": _at(2), "facts": {"a": 2}, "provenance": "pulled"}
    assert R.newest_revision(_CUR, [pushed, pulled]) is pulled
    assert R.newest_revision(_CUR, [pulled, pushed]) is pulled
    spelled_alike = {**pushed, "received_at": _at(2)}
    assert R.newest_revision(_CUR, [spelled_alike, pulled]) is pulled


def test_NOTHING_RECEIVED_AFTER_THE_CURRENT_INPUT_IS_NEWER():
    same = {"rev": 2, "received_at": _at(0), "facts": {"a": 1}, "provenance": "pulled"}
    older = {"rev": 3, "received_at": "2026-10-02T23:59:59+00:00", "facts": {}, "provenance": "pushed"}
    assert R.newest_revision(_CUR, [older, same]) is None


@pytest.mark.parametrize("bad", [{"rev": "2", "facts": {}}, {"rev": True, "facts": {}},
                                 {"rev": 2}, {"rev": 2, "facts": None}, "rev 2"])
def test_A_REVISION_WITHOUT_AN_INTEGER_REV_AND_FACTS_IS_REFUSED(bad):
    with pytest.raises(R.CaseRoutingError, match="integer `rev`"):
        R.newest_revision(_CUR, [bad])


_UNORDERABLE = [None, "t", 1759449600, "2026-10-03T00:00:05"]


@pytest.mark.parametrize("at", _UNORDERABLE)
def test_A_REVISION_WHOSE_RECEIPT_CANNOT_BE_ORDERED_IS_REFUSED(at):
    """Missing, unparseable, not a string, or NAIVE: a naive time cannot be ordered against an
    aware one without inventing a zone."""
    with pytest.raises(R.CaseRoutingError, match="with its zone"):
        R.newest_revision({"revision": 1, "received_at": at}, [])
    with pytest.raises(R.CaseRoutingError, match="with its zone"):
        R.newest_revision(_CUR, [{"rev": 2, "received_at": at, "facts": {}}])


@pytest.mark.asyncio
async def test_A_PULL_VERB_NOBODY_DECLARED_FAILS_THE_CASE(registered, monkeypatch):
    real = wd.load_stub_verbs
    monkeypatch.setattr(wd, "load_stub_verbs", lambda: {
        k: v for k, v in real().items() if k != "maintenance_picture_read"})
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected")]))
    await _refused(c.start("EV-1", TRIGGER, _event()), 500)
    assert c.case("EV-1")["transitions"][-1]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_A_PULLED_PICTURE_IN_ANOTHER_EPISODE_FAILS_THE_CASE(registered, monkeypatch):
    moved = _newer()
    moved["asset_id"] = "AST-8"
    _stubs_with(monkeypatch, {"rev": 5, "event_id": "EV-1", "received_at": "2099-01-01T00:00:00Z",
                              "facts": moved})
    c = _RevCluster(_script("EV-1", [(DECIDE, "rejected")]))
    await _refused(c.start("EV-1", TRIGGER, _event()), 422)


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
async def test_ANOTHER_CASES_EVENT_KEEPS_NOTHING_ON_THIS_EPISODE():
    c = _RevCluster()
    o = c.obj("ep")
    o.state["open"] = "EV-1"
    await _refused(_body(wr.keep_revision)(o, {"case_id": "EV-2", "event_id": "EV-2",
                                              "facts": {}, "received_at": _at(1)}), 409)
    assert "revision" not in o.state


@pytest.mark.asyncio
@pytest.mark.parametrize("at", _UNORDERABLE)
async def test_A_KEPT_REVISION_THE_REFRESH_COULD_NOT_ORDER_IS_REFUSED_AT_THE_DOOR(at):
    """``keep_revision`` is on the ingress: refused here it is the caller's 400, where kept it
    would fail the holder's case at its next refresh."""
    c = _RevCluster()
    o = c.obj("ep")
    o.state["open"] = "EV-1"
    await _refused(_body(wr.keep_revision)(o, {"case_id": "EV-1", "event_id": "EV-1",
                                              "facts": {}, "received_at": at}), 400)
    assert "revision" not in o.state


@pytest.mark.asyncio
async def test_RELEASE_DROPS_THE_KEPT_REVISION_WITH_THE_EPISODE():
    """The next case on this episode opens on its own event; a kept revision of the last one
    would otherwise be its 'newest picture'."""
    c = _RevCluster()
    o = c.obj("ep")
    o.state["open"] = "EV-1"
    got = await _body(wr.keep_revision)(o, {"case_id": "EV-1", "event_id": "EV-1",
                                           "facts": {"x": 1}, "received_at": _at(1)})
    assert got == {"case_id": "EV-1", "revision": 2}
    await _body(wr.release)(o, {"case_id": "EV-1"})
    assert await _body(wr.claim)(o, {"case_id": "EV-2"}) == "EV-2"
    assert await _body(wr.newest_revision)(o, {"case_id": "EV-2"}) is None


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


def test_EVERY_PULL_VERB_IS_A_DECLARED_STUB():
    stubs = wd.load_stub_verbs()
    pulls = {t.trigger: t.pull for t in R.load_triggers().values() if t.pull}
    assert pulls.get(TRIGGER) == "maintenance_picture_read", pulls
    assert {k: v for k, v in pulls.items() if v not in stubs} == {}


def test_EVERY_OPTION_CITES_THE_INPUT_REVISION():
    defn = wd.get_workflow_definition("maint_fault_propose")
    [render] = [s for s in defn.steps if s.kind == "render"]
    assert [o.get("input_revision") for o in render.template] == ["{input.revision}"] * 4
