"""A reschedule is TWO OPS, and this is their one home.

WHY A POLICY AND NOT A CO-MOVE. `MoveProject` sets `proj.planned` and does not touch
site-impact windows, and that independence is domain truth rather than an oversight: a
rollout's DISRUPTIVE PHASE is narrower than the rollout. P12 runs Apr-Sep while its Site B
impact is a Jul-Sep subset. Making `MoveProject` drag impacts with it would delete the very
distinction that makes site load a different measure from schedule — and would make the demo
lie about the model in order to make a beat work.

So the ops stay SEPARATE and a policy CO-EMITS them. `MoveProject` is still innocent; the
reschedule endpoint is what knows that moving a project ought to move its disruption too.

WHY THE SERVER OWNS IT. The obvious home was the client — the component that saw the drag.
Measured 2026-08-24: site impacts do not exist in cortex-ui AT ALL (zero references), and
`IntervalRow` carries no impact windows. The client cannot compute an offset it has no data
for. The alternative was widening `plan_schedule`'s rows to carry site-impact data, which puts
one measure's concerns inside another's payload. State lives in PlanStore; the derivation
lives with it.

THE RULE: OFFSET-PRESERVED. Impacts shift by the SAME DELTA as the project, which keeps each
impact's position RELATIVE to its project intact. A Jul-Sep window inside an Apr-Sep project
stays "the third quarter of this rollout" after the move rather than becoming an absolute date
that happens to survive. Clamping or recomputing would silently re-author the model's
semantics; shifting preserves them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.planning_agent import measures  # noqa: E402
from agent_fleet.planning_agent.entities import Interval  # noqa: E402
from agent_fleet.planning_agent.seed import build_seed  # noqa: E402
from agent_fleet.planning_agent.state import (  # noqa: E402
    MoveProject, MoveSiteImpact, PlanStore, apply_ops,
)


@pytest.fixture
def state():
    return build_seed()


def test_it_returns_a_MoveProject_FIRST(state):
    """Order is preserved and it matters: the schedule move is what the room did, and the
    impact moves are its consequence. A log read in the other order would suggest the site
    change caused the reschedule."""
    ops = measures.derive_reschedule(state, project_id="P12",
                                     new_planned=Interval("2026-07-01", "2026-12-31"))
    assert isinstance(ops[0], MoveProject)
    assert ops[0].project_id == "P12"


def test_it_co_emits_a_MoveSiteImpact_for_EVERY_impact_the_project_carries(state):
    """P12 loads exactly one site. A project loading three would produce three impact ops —
    one per impact, never a single fused 'move everything' op."""
    impacts = [i for i in state.site_impacts if i.project_id == "P12"]
    ops = measures.derive_reschedule(state, project_id="P12",
                                     new_planned=Interval("2026-07-01", "2026-12-31"))
    impact_ops = [o for o in ops if isinstance(o, MoveSiteImpact)]
    assert len(impact_ops) == len(impacts) == 1
    assert impact_ops[0].site_id == "S2"


def test_the_impact_shifts_by_the_SAME_DELTA_as_the_project(state):
    """OFFSET-PRESERVED. P12's project starts 2026-04-01 and its impact starts 2026-10-01 —
    183 days in. Move the project back 92 days and the impact must move back 92 days, keeping
    it 183 days into the rollout rather than at some absolute date that survived by accident.
    """
    proj = state.project("P12")
    old_impact = next(i for i in state.site_impacts if i.project_id == "P12")
    new_start = "2026-01-01"
    ops = measures.derive_reschedule(
        state, project_id="P12",
        new_planned=Interval(new_start, "2026-06-30"))
    moved = next(o for o in ops if isinstance(o, MoveSiteImpact))

    from datetime import date
    d = lambda s: date.fromisoformat(s)
    project_delta = (d(new_start) - d(proj.planned.start)).days
    impact_delta = (d(moved.new_window.start) - d(old_impact.window.start)).days
    assert impact_delta == project_delta

    # The window's LENGTH is unchanged — a shift, never a stretch.
    assert (d(moved.new_window.end) - d(moved.new_window.start)).days == \
           (d(old_impact.window.end) - d(old_impact.window.start)).days


def test_a_project_with_NO_impacts_yields_only_the_move(state):
    """Most projects touch no site. The policy must not invent an impact to have something to
    co-emit."""
    no_impact = next(p for p in state.projects
                     if not [i for i in state.site_impacts if i.project_id == p.project_id])
    ops = measures.derive_reschedule(state, project_id=no_impact.project_id,
                                     new_planned=Interval("2026-01-01", "2026-03-31"))
    assert len(ops) == 1 and isinstance(ops[0], MoveProject)


def test_an_unknown_project_RAISES(state):
    with pytest.raises(measures.NotInModel):
        measures.derive_reschedule(state, project_id="P99",
                                   new_planned=Interval("2026-01-01", "2026-03-31"))


def test_an_INVERTED_interval_RAISES_before_any_op_is_built(state):
    """Refuse first. A policy that returned ops for an impossible move would push the failure
    into apply_ops, after the caller had already been told the reschedule was valid."""
    with pytest.raises(measures.NotInModel):
        measures.derive_reschedule(state, project_id="P12",
                                   new_planned=Interval("2026-06-30", "2026-01-01"))


# ── THE BEAT, end to end ─────────────────────────────────────────────────────────────────

def test_the_SCRIPTED_RESCHEDULE_crosses_Site_B(state):
    """Beat 2's payload: the room's action crosses the line.

    Pulling P12 forward so its Jul-Sep-relative impact lands back in FY26-Q4 takes Site B from
    1.8 to 2.7 against its 2.0 threshold. This is the whole causal claim, executed.
    """
    before = [r for r in measures.plan_site_load(state) if r.get("over_threshold")]
    assert before == [], "precondition: nothing is over at baseline"

    # P12's impact currently sits in FY27-Q1; a 92-day pull-forward returns it to Q4.
    ops = measures.derive_reschedule(state, project_id="P12",
                                     new_planned=Interval("2026-01-01", "2026-06-30"))
    after = apply_ops(state, ops)

    over = [(r["site_id"], r["period"]) for r in measures.plan_site_load(after)
            if r.get("over_threshold")]
    assert over == [("S2", "FY26-Q4")], f"expected only Site B to cross, got {over}"


def test_the_reschedule_is_REVERSIBLE_and_baseline_is_untouched(state):
    """`apply_ops` never mutates its input. Pinned because the demo drags live."""
    before = [(r["site_id"], r["period"], r["load"]) for r in measures.plan_site_load(state)]
    ops = measures.derive_reschedule(state, project_id="P12",
                                     new_planned=Interval("2026-01-01", "2026-06-30"))
    apply_ops(state, ops)
    after = [(r["site_id"], r["period"], r["load"]) for r in measures.plan_site_load(state)]
    assert before == after


def test_the_ops_survive_a_SCENARIO_round_trip(state):
    """The route appends them to a scenario, so they must be ordinary ops — not a special
    fused shape the store would have to learn."""
    store = PlanStore(state)
    store.fork("SC1", "pull the supplier feed forward")
    for op in measures.derive_reschedule(state, project_id="P12",
                                         new_planned=Interval("2026-01-01", "2026-06-30")):
        store.append_op("SC1", op)
    assert len(store.scenario("SC1").ops) == 2
    over = [r["site_id"] for r in measures.plan_site_load(store.resolve("SC1"))
            if r.get("over_threshold")]
    assert over == ["S2"]


# ── the route ────────────────────────────────────────────────────────────────────────────

def test_the_route_appends_BOTH_ops_and_NAMES_them():
    """THE PRE-FLIGHT CHECK, as a test. Beat 2's failure mode is a drag that emits only the
    project move: the bar shifts, Site B stays green, and the causality the beat exists for
    is gone. The response names the ops so a witness can SEE both landed rather than trust a
    count."""
    from fastapi.testclient import TestClient
    from agent_fleet.planning_agent import main as _main

    client = TestClient(_main.app)
    assert client.post("/scenario", json={"scenario_id": "SC-R", "name": "pull forward"}).status_code == 200
    r = client.post("/scenario/SC-R/reschedule",
                    json={"project_id": "P12", "start": "2026-01-01", "end": "2026-06-30"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ops_appended"] == 2
    assert body["ops"] == ["MoveProject", "MoveSiteImpact"]

    load = client.post("/measure/plan_site_load", json={"state_ref": "SC-R"}).json()
    over = [(x["site_id"], x["period"]) for x in load["rows"] if x["over_threshold"]]
    assert over == [("S2", "FY26-Q4")], f"the drag did not cross Site B: {over}"


def test_the_route_REFUSES_an_inverted_move_without_appending():
    """Refuse first, and leave the scenario clean — a half-applied reschedule would be a
    scenario nobody asked for."""
    from fastapi.testclient import TestClient
    from agent_fleet.planning_agent import main as _main

    client = TestClient(_main.app)
    client.post("/scenario", json={"scenario_id": "SC-BAD", "name": "inverted"})
    r = client.post("/scenario/SC-BAD/reschedule",
                    json={"project_id": "P12", "start": "2026-06-30", "end": "2026-01-01"})
    assert r.status_code == 422
    assert _main.STORE.scenario("SC-BAD").ops == []
