"""THE GENERIC PIECES A TIER'S REFUSAL ONCE NEEDED: `outcome_repeated` and `reason_required`.

HISTORY. Ruled by the architect on 2026-10-02 (item 6): `tier_refused` -> proposed, with the
refusal's reason; a second refusal -> deferred, as a decision row. RETIRED 2026-10-28: the
supervisor's approval is the release, so `maint_release` waits for no tier and nothing is refused
(the paths and rows that proved it are gone; see tests/routing/
test_the_supervisor_approval_is_the_release.py). The mechanisms are generic and stay sealed here,
on definitions of their own, because the runner still supplies them to any table:
* ``outcome_repeated`` -- the runner MEASURES whether this definition has ended with this outcome
  before in the case. A table matches by equality only (ADR-0039), so "second" must be a fact.
* ``reason_required`` on ``signal_await`` -- a refusal must say why; the case carries the reason.
* a join seal: every attribute a chaining table matches is one the runner supplies, ``chosen.*``,
  or a fact some trigger requires. A table keyed on anything else refuses every case ending there.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.test_a_case_runs_from_trigger_to_terminal import (
    R, _answer, _body, _Cluster, _dump, _refused, main, wd, wr)
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 -- fixture
    _declared_walk_double, _real_policy, registered)

TIER = "tier@x"


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

def _stray(idx):
    required = {f for t in R.load_triggers().values() for f in t.requires}
    supplied = set(R.TERMINATION_FACTS) | required
    return {(name, a) for name, t in idx.items() for a in (t.get("matches") or [])
            if a not in supplied and not a.startswith("chosen.")}


def test_EVERY_ATTRIBUTE_A_CHAINING_TABLE_MATCHES_IS_ONE_SOMETHING_SUPPLIES():
    idx = R.chaining_index()
    assert idx, "no chaining tables -- the seal would pass on nothing"
    stray = _stray(idx)
    assert not stray, f"matched by a table, supplied by nothing: {sorted(stray)}"
    # POSITIVE CONTROLS. No committed table matches `outcome_repeated` since 2026-10-28, so the
    # control is synthetic: the runner's measured fact is supplied (not stray), and a fact
    # nothing supplies is caught.
    assert _stray({"t": {"matches": ["outcome", "outcome_repeated"]}}) == set()
    assert _stray({"t": {"matches": ["outcome", "nobody_supplies_this"]}}) == {
        ("t", "nobody_supplies_this")}


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


def test_A_REASON_FOR_A_STATUS_THE_SIGNAL_DOES_NOT_ACCEPT_IS_REFUSED_AT_LOAD():
    with pytest.raises(ValidationError, match="reason_required"):
        wd.SignalAwaitStep(kind="signal_await", id="s", signal="s", audience="a:b",
                           accepts=["ok"], reason_required=["refused"])


@pytest.mark.asyncio
async def test_ONLY_A_SIGNAL_THAT_DECLARES_REASONS_JOURNALS_THEM(registered, monkeypatch,
                                                                tmp_path):
    """Replay-unchanged for every signal that declares nothing. A signal declaring a reason
    journals it; a signal declaring none, answered WITH one, journals no key.

    No committed definition declares a signal since 2026-10-28, so both arms are definitions of
    their own, differing only in whether the signal declares a reason."""
    monkeypatch.setenv("CASE_TRIGGER_DIR", str(_dump(tmp_path / "triggers", {
        "acks": {"trigger": "acks", "selection": "sel_ack", "key": "event_id"},
        "reasons": {"trigger": "reasons", "selection": "sel_reason", "key": "event_id"}})))
    monkeypatch.setenv("DECISION_TABLE_DIR", str(_dump(tmp_path / "decisions", {
        "sel_ack": {"decision": "sel_ack", "matches": ["level"], "domain": {"level": ["hi"]},
                    "rows": [{"then": "plain"}]},
        "sel_reason": {"decision": "sel_reason", "matches": ["level"],
                       "domain": {"level": ["hi"]}, "rows": [{"then": "reasoned"}]},
        "reasoned_chain": {"decision": "reasoned_chain", "after": "reasoned",
                           "matches": ["outcome"],
                           "domain": {"outcome": ["fine", "tier_refused"]},
                           "terminals": ["done", "refused"],
                           "rows": [{"when": {"outcome": "fine"}, "then": "done"},
                                    {"when": {"outcome": "tier_refused"}, "then": "refused"}]},
        "plain_chain": {"decision": "plain_chain", "after": "plain", "matches": ["outcome"],
                        "domain": {"outcome": ["fine", "tier_refused"]},
                        "terminals": ["done", "refused"],
                        "rows": [{"when": {"outcome": "fine"}, "then": "done"},
                                 {"when": {"outcome": "tier_refused"}, "then": "refused"}]}})))
    monkeypatch.setenv("WORKFLOW_DEFINITIONS_DIR", str(_dump(tmp_path / "workflows", {
        "reasoned": {"id": "reasoned", "name": "reasoned", "steps": [
            {"kind": "signal_await", "id": "ack", "signal": "reasoned_ack", "audience": "ops:ORG",
             "accepts": ["fine", "tier_refused"], "reason_required": ["tier_refused"]}]},
        "plain": {"id": "plain", "name": "plain", "steps": [
            {"kind": "signal_await", "id": "ack", "signal": "plain_ack", "audience": "ops:ORG",
             "accepts": ["fine", "tier_refused"]}]}})))
    c = _Cluster({("R-1~1", "reasoned_ack"): _answer("tier_refused", TIER, "no hangar slot")})
    out = await c.start("R-1", "reasons", {"event_id": "R-1", "level": "hi"})
    assert out["terminal"] == "refused", out
    keys = {k: v for ctx in c.ctxs.values() for k, v in ctx.state.items()
            if k.startswith("signal_reason_")}
    assert keys == {main._signal_reason_key("reasoned_ack"): ["tier_refused"]}, keys

    c = _Cluster({("E-1~1", "plain_ack"): _answer("tier_refused", TIER, "a reason nobody asked for")})
    out = await c.start("E-1", "acks", {"event_id": "E-1", "level": "hi"})
    assert out["terminal"] == "refused", out
    assert not [k for ctx in c.ctxs.values() for k in ctx.state
                if k.startswith("signal_reason_")], "a signal that declares no reason journalled one"
