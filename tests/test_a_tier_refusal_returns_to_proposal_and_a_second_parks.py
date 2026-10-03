"""A TIER'S REFUSAL RETURNS THE CASE TO PROPOSED WITH ITS REASON; A SECOND ONE PARKS IT.

Ruled by the architect on 2026-10-02 (item 6): ``tier_refused`` -> proposed, with the refusal's
reason; a second refusal -> deferred, with a revisit time, as a decision row.

Three generic pieces carry it, and nothing in Python names maintenance:
* ``outcome_repeated`` -- the runner MEASURES whether this definition has ended with this outcome
  before in the case. A table matches by equality only (ADR-0039), so "second" must be a fact; it
  is a bool, so the second refusal and every later one read the same.
* ``reason_required`` on ``signal_await`` -- a refusal that goes back to a maintainer must say why,
  and the case carries the reason onto the hop.
* a join seal: every attribute a chaining table matches is one the runner supplies, ``chosen.*``,
  or a fact some trigger requires. A table keyed on anything else refuses every case ending there.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.test_a_case_runs_from_trigger_to_terminal import (
    R, _body, _Cluster, _refused, main, wd, wr)
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 -- fixture
    ACK, DECIDE, _event, _path, _real_policy, _run, registered)

TIER = "tier@x"


# ── THE PATHS ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_A_FIRST_REFUSAL_RETURNS_TO_PROPOSED_AND_THE_HOP_CARRIES_ITS_REASON(registered):
    out, _ = await _run(_event(), [(DECIDE, "replace_after_resupply"), (ACK, "tier_refused", TIER),
                                   (DECIDE, "defer_with_restriction"), (ACK, "released", TIER)])
    assert _path(out) == [("triaged", "selected", "maint_fault_propose"),
                          ("maint_fault_propose", "replace_after_resupply", "maint_release"),
                          ("maint_release", "tier_refused", "maint_fault_propose"),
                          ("maint_fault_propose", "defer_with_restriction", "maint_release"),
                          ("maint_release", "released", "closed")], _path(out)
    hop = out["transitions"][4]
    assert (hop["outcome"], hop["by"], hop["reason"]) == ("tier_refused", TIER, "because 2"), hop
    assert out["terminal"] == "closed", out


@pytest.mark.asyncio
async def test_A_SECOND_REFUSAL_PARKS_THE_CASE_AND_IT_COMES_BACK_PROPOSED(registered):
    out, _ = await _run(_event(), [(DECIDE, "replace_after_resupply"), (ACK, "tier_refused", TIER),
                                   (DECIDE, "replace_after_resupply"), (ACK, "tier_refused", TIER),
                                   None,
                                   (DECIDE, "defer_with_restriction"), (ACK, "released", TIER)])
    assert _path(out)[2:5] == [("maint_release", "tier_refused", "maint_fault_propose"),
                               ("maint_fault_propose", "replace_after_resupply", "maint_release"),
                               ("maint_release", "tier_refused", "maint_fault_park")], _path(out)
    assert _path(out)[5] == ("maint_fault_park", "elapsed", "maint_fault_propose"), _path(out)
    assert out["terminal"] == "closed", out


@pytest.mark.asyncio
async def test_A_THIRD_REFUSAL_PARKS_AGAIN_RATHER_THAN_RETURNING_TO_THE_MAINTAINER(registered):
    refuse = [(DECIDE, "replace_after_resupply"), (ACK, "tier_refused", TIER)]
    out, _ = await _run(_event(), [*refuse, *refuse, None, *refuse, None,
                                   (DECIDE, "defer_with_restriction"), (ACK, "released", TIER)])
    refusals = [to for frm, oc, to in _path(out) if oc == "tier_refused"]
    assert refusals == ["maint_fault_propose", "maint_fault_park", "maint_fault_park"], _path(out)


def test_THE_REFUSAL_ROWS_ARE_TOTAL_AND_NONE_IS_A_TERMINAL():
    """A refusal never closes the case: it was the dead end the ruling replaced."""
    table = R.chaining_index()["maint_release"]
    assert "tier_refused" not in (table.get("terminals") or []), table
    got = {rep: R._dt.decide(table, {"outcome": "tier_refused", "outcome_repeated": rep})
           for rep in (False, True)}
    assert {k: (d.then, d.terminal) for k, d in got.items()} == {
        False: ("maint_fault_propose", False), True: ("maint_fault_park", False)}, got


# ── THE MEASURED FACT ───────────────────────────────────────────────────────────────────────

def test_OUTCOME_REPEATED_IS_THIS_DEFINITION_WITH_THIS_OUTCOME_EARLIER_IN_THE_CASE():
    env = {"outcome": "tier_refused", "outputs": {}}
    f = lambda ts: R.termination_facts({}, env, "rel", ts)["outcome_repeated"]  # noqa: E731
    assert f([]) is False
    assert f([{"from": "rel", "outcome": "tier_refused"}]) is True
    # NEITHER HALF ALONE: another definition's refusal, or this one's other outcome, is not a repeat.
    assert f([{"from": "other", "outcome": "tier_refused"}]) is False
    assert f([{"from": "rel", "outcome": "released"}]) is False
    assert R.termination_facts({}, env, "rel")["outcome_repeated"] is False


def test_A_TRIGGER_FACT_NAMED_OUTCOME_REPEATED_IS_REFUSED_AT_INTAKE():
    t = R.Trigger(trigger="t", selection="s", key="event_id")
    with pytest.raises(R.CaseRoutingError, match="outcome_repeated"):
        R.check_intake(t, R.flatten({"event_id": "E", "outcome_repeated": False}), "E")


# ── THE JOIN: what a chaining table matches must reach it ───────────────────────────────────

def test_EVERY_ATTRIBUTE_A_CHAINING_TABLE_MATCHES_IS_ONE_SOMETHING_SUPPLIES():
    required = {f for t in R.load_triggers().values() for f in t.requires}
    supplied = set(R.TERMINATION_FACTS) | required
    idx = R.chaining_index()
    assert idx, "no chaining tables -- the seal would pass on nothing"
    stray = {(name, a) for name, t in idx.items() for a in (t.get("matches") or [])
             if a not in supplied and not a.startswith("chosen.")}
    assert not stray, f"matched by a table, supplied by nothing: {sorted(stray)}"
    # POSITIVE CONTROL: the runner's measured fact is in use, so the seal reaches it.
    assert any("outcome_repeated" in (t.get("matches") or []) for t in idx.values()), idx


# ── THE REASON ON A SIGNAL ──────────────────────────────────────────────────────────────────

def _tier_ctx():
    c = _Cluster().ctx("EV-1~2")
    c.state[main._signal_accepts_key("tier_ack")] = ["released", "tier_refused"]
    c.state[main._signal_reason_key("tier_ack")] = ["tier_refused"]
    c.state[main._audience_key("tier_ack")] = "maint_tier_ack:ORG"
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize("comments", [None, "", "   "])
async def test_A_REFUSAL_WITHOUT_A_REASON_IS_REFUSED_AND_RESOLVES_NOTHING(monkeypatch, comments):
    monkeypatch.setattr(main, "_check_can_act", lambda aud, who: True)
    ctx = _tier_ctx()
    req = {"signal": "tier_ack", "status": "tier_refused", "acted_by": TIER}
    if comments is not None:
        req["comments"] = comments
    await _refused(_body(wr.signal)(ctx, req), 400)
    assert ctx.resolved == [], ctx.resolved


@pytest.mark.asyncio
async def test_CONTROL_A_RELEASE_NEEDS_NO_REASON_AND_A_REASONED_REFUSAL_PASSES(monkeypatch):
    monkeypatch.setattr(main, "_check_can_act", lambda aud, who: True)
    ctx = _tier_ctx()
    for req in ({"signal": "tier_ack", "status": "released", "acted_by": TIER},
                {"signal": "tier_ack", "status": "tier_refused", "acted_by": TIER,
                 "comments": "no hangar slot"}):
        try:
            await _body(wr.signal)(ctx, req)
        except wr.restate.TerminalError as e:
            raise AssertionError(f"a signal the reason rule should pass was refused: {req} -> {e}")
    assert [p["status"] for _, p in ctx.resolved] == ["released", "tier_refused"], ctx.resolved


def test_THE_RELEASE_DEFINITION_REQUIRES_A_REASON_ON_REFUSAL_ONLY():
    import workflow_definition as wdm
    [ack] = [s for s in wdm.get_workflow_definition("maint_release").steps
             if s.kind == "signal_await"]
    assert ack.reason_required == ["tier_refused"], ack


def test_A_REASON_FOR_A_STATUS_THE_SIGNAL_DOES_NOT_ACCEPT_IS_REFUSED_AT_LOAD():
    with pytest.raises(ValidationError, match="reason_required"):
        wd.SignalAwaitStep(kind="signal_await", id="s", signal="s", audience="a:b",
                           accepts=["ok"], reason_required=["refused"])


@pytest.mark.asyncio
async def test_ONLY_A_SIGNAL_THAT_DECLARES_REASONS_JOURNALS_THEM(registered, monkeypatch):
    """Replay-unchanged for every signal that declares nothing: `origin_written` declares no
    reason, and the origin case journals no reason key; the release's `tier_ack` does."""
    out, c = await _run(_event(), [(DECIDE, "replace_after_resupply"), (ACK, "released", TIER)])
    assert out["terminal"] == "closed", out
    keys = {k: v for ctx in c.ctxs.values() for k, v in ctx.state.items()
            if k.startswith("signal_reason_")}
    assert keys == {main._signal_reason_key("tier_ack"): ["tier_refused"]}, keys

    from tests import test_an_origin_suggestion_runs_as_a_case as og
    out, c = await og._run(og._suggestion(), [(og.CONFIRM, "accepted"),
                                              (og.WRITTEN, "written", "w@x")])
    assert out["terminal"] == "resolved", out
    assert not [k for ctx in c.ctxs.values() for k in ctx.state
                if k.startswith("signal_reason_")], "a signal that declares no reason journalled one"
