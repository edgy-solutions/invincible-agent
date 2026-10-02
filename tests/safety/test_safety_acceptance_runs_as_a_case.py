"""Safety acceptance runs as a CASE through the generic runner, from the policy the image ships.

`SafetyAcceptance` ran the FIRST definition `safety_acceptance_selection` chose and stopped. For a
Serious or High risk that definition is `safety_concurrence`, so the acceptance MIL-STD-882E
4.3.7 puts after the concurrence never opened: `safety_concurrence_chaining` and
`safety_acceptance_chaining` had no consumer. And it registered every await under the request's
`risk_acceptance_{level}` kind, so a concurrence row offered `accepted` at `/act`.

The gateway now opens `WorkflowRunner` on the `safety_review_request` trigger. Every arm below
reads the REAL policy tree -- no env override, no tmp rows -- because the claim is about what the
sample overlay routes, and a fixture tree would control the runner's logic and nothing about
whether that logic still points at the rows production reads.

What safety needed that the runner did not already do: NOTHING in Python. The three definitions
declare `task_kind:` on their awaits, the chaining tables declare `after:`, `safety_redraft` got a
chaining table of its own, and the trigger row names the key. That is the dispatch's proof that
the runner is generic.

Run: uv run --frozen pytest tests/safety/test_safety_acceptance_runs_as_a_case.py -v
"""
from __future__ import annotations

import pytest

# The double and the runner module objects are the case runner's own seal's: one cluster fake,
# not a second one free to drift from it.
from tests.test_a_case_runs_from_trigger_to_terminal import R, _answer, _Cluster, main, wr
from src.iagent_pure import acceptance_request as ar


@pytest.fixture(autouse=True)
def _real_policy(monkeypatch):
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def registered(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append(
                            (wf, task["audience"], kind)) or {})
    return rows


def _trigger(level="High", hazard="HAZ-9001", **extra):
    rr = {"kind": f"risk_acceptance_{level.lower()}", "subject_ref": hazard,
          "payload": {"hazard_id": hazard, "risk_level": level,
                      "risk_level_slug": level.lower()}}
    return {**ar.acceptance_trigger(rr), **extra}


async def _run(trigger, answers):
    """Drive one case; `answers` are (promise name, verb) in instance order, one per instance.
    The safety awaits DECLARE `promise_name`, so the promise is not `approval_{step id}`."""
    key = trigger["acceptance_id"]
    c = _Cluster({(f"{key}~{n}", step): _answer(verb, "u@x", f"why {n}")
                  for n, (step, verb) in enumerate(answers, start=1)})
    try:
        out = await c.start(key, ar.SAFETY_TRIGGER, trigger)
    except Exception as exc:  # noqa: BLE001 -- a case that did not CLOSE is the arm's red
        raise AssertionError(
            f"the case ended in {type(exc).__name__}: {exc}; case={c.case(key)}") from exc
    return out, c.case(key)


def _path(case):
    """The hops after intake: (from, outcome, to)."""
    return [(t["from"], t["outcome"], t["to"]) for t in case["transitions"]][2:]


def test_THE_TRIGGER_THE_GATEWAY_SENDS_IS_DECLARED_AND_KEYED_ON_THE_ACCEPTANCE_ID():
    declared = R.load_triggers()
    assert ar.SAFETY_TRIGGER in declared, (
        f"the gateway sends {ar.SAFETY_TRIGGER!r} and the policy declares {sorted(declared)}")
    t = declared[ar.SAFETY_TRIGGER]
    trig = _trigger()
    assert t.key == "acceptance_id", t
    assert trig["acceptance_id"] == ar.acceptance_workflow_id("HAZ-9001", "high"), trig
    R.check_intake(t, R.flatten(trig), trig["acceptance_id"])


@pytest.mark.asyncio
async def test_A_HIGH_RISK_IS_CONCURRED_THEN_ACCEPTED_IN_ONE_CASE(registered):
    out, case = await _run(_trigger(), [("concurrence", "concurred"), ("acceptance", "accepted")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "risk_accepted"), out
    assert _path(case) == [("triaged", "selected", "safety_concurrence"),
                           ("safety_concurrence", "concurred", "safety_acceptance_direct"),
                           ("safety_acceptance_direct", "accepted", "risk_accepted")], _path(case)
    key = _trigger()["acceptance_id"]
    # EACH ROW UNDER ITS OWN KIND: the concurrence row is the concurrence kind, whose accepts are
    # [concurred, not_concurred, returned_for_rework] -- never `accepted`.
    assert registered == [
        (f"{key}~1", "risk_acceptance_concurrence_high:SUSTAINMENT",
         "risk_acceptance_concurrence_high"),
        (f"{key}~2", "risk_acceptance_high:SUSTAINMENT", "risk_acceptance_high"),
    ], registered


@pytest.mark.asyncio
async def test_A_MEDIUM_RISK_GOES_STRAIGHT_TO_ACCEPTANCE(registered):
    out, case = await _run(_trigger("Medium"), [("acceptance", "rejected")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "risk_rejected"), out
    assert [k for *_, k in registered] == ["risk_acceptance_medium"], registered


@pytest.mark.asyncio
async def test_A_NON_CONCURRENCE_REDRAFTS_AND_COMES_BACK_TO_CONCURRENCE(registered):
    """The loop stays IN the case, as new instances. Under SafetyAcceptance a re-draft re-sent
    at the same level reached the same workflow key and was answered from the old journal."""
    out, case = await _run(_trigger(), [("concurrence", "not_concurred"), ("redraft", "redrafted"),
                                        ("concurrence", "concurred"), ("acceptance", "accepted")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "risk_accepted"), out
    assert [h[2] for h in _path(case)] == [
        "safety_concurrence", "safety_redraft", "safety_concurrence", "safety_acceptance_direct",
        "risk_accepted"], _path(case)
    assert [k for *_, k in registered] == [
        "risk_acceptance_concurrence_high", "safety_redraft",
        "risk_acceptance_concurrence_high", "risk_acceptance_high"], registered
    assert registered[1][1] == "risk_redraft:SUSTAINMENT", registered


@pytest.mark.asyncio
async def test_A_RETURNED_MEDIUM_REDRAFT_COMES_BACK_TO_DIRECT_ACCEPTANCE(registered):
    out, case = await _run(_trigger("Medium"), [("acceptance", "returned_for_rework"),
                                                ("redraft", "redrafted"),
                                                ("acceptance", "accepted")])
    assert out["terminal"] == "risk_accepted", out
    assert [h[2] for h in _path(case)] == [
        "safety_acceptance_direct", "safety_redraft", "safety_acceptance_direct",
        "risk_accepted"], _path(case)


@pytest.mark.asyncio
async def test_A_WITHDRAWN_ASSESSMENT_ENDS_AT_ITS_DECLARED_TERMINAL(registered):
    out, case = await _run(_trigger("Serious"), [("concurrence", "not_concurred"),
                                                 ("redraft", "withdrawn")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "assessment_withdrawn"), out


@pytest.mark.asyncio
async def test_THE_ROW_KIND_IS_THE_DEFINITIONS_NOT_THE_REQUESTS(registered):
    """A request naming the wrong kind changes nothing: the kind is declared on the await, and
    the runner reads it from the registry -- the request is facts, never a route or a kind."""
    trig = _trigger("High", kind="risk_acceptance_low")
    out, _ = await _run(trig, [("concurrence", "concurred"), ("acceptance", "accepted")])
    assert out["terminal"] == "risk_accepted", out
    assert [k for *_, k in registered] == [
        "risk_acceptance_concurrence_high", "risk_acceptance_high"], registered


def test_EVERY_SAFETY_DEFINITION_HAS_A_TABLE_THAT_FOLLOWS_IT():
    """A selected or chained-to definition with no `after:` table ends its case FAILED."""
    idx = R.chaining_index()
    reachable = {r["then"] for r in R._dt.load_table("safety_acceptance_selection")["rows"]}
    frontier = set(reachable)
    while frontier:
        d = frontier.pop()
        assert d in idx, f"{d} is reachable and nothing declares `after: {d}`"
        t = idx[d]
        for row in t["rows"]:
            if row["then"] not in t.get("terminals", []) and row["then"] not in reachable:
                reachable.add(row["then"])
                frontier.add(row["then"])
    assert reachable == {"safety_concurrence", "safety_acceptance_direct", "safety_redraft"}, (
        reachable)
