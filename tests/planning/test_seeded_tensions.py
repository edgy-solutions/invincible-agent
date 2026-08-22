"""Gate 0's acceptance instrument: every seeded tension is DETECTED BY A MEASURE.

WHY THIS SHAPE. The plan's Gate 0 does not ask "do the measures run" — it asks whether each
deliberately-seeded tension is found. A measure that runs and returns rows proves nothing;
`site_load` returning an empty grid is a passing function and a failed demo. So each test
here names the tension by its plan letter and asserts the measure surfaces it.

READ THIS BEFORE "FIXING" A FAILURE. If one of these goes red, the SEED changed, not the
measure — `agent_fleet/planning_agent/seed.py` is the first place to look. The tensions are
demo beats; losing one silently is losing a beat in the room.

The magnitudes are hand-computed from the seed and written as literals rather than derived
from the code under test. A test that recomputes the thing it is testing asserts only that
the function is deterministic.
"""
from __future__ import annotations

import pytest

from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed, check_consistency

M = 1_000_000.0


@pytest.fixture(scope="module")
def state():
    return build_seed()


# ─────────────────────────────────────────────────────────────────────────────
# Consistency — the floor. A seed that does not resolve makes every test below
# a statement about garbage.
# ─────────────────────────────────────────────────────────────────────────────

def test_seed_is_internally_consistent(state):
    problems = check_consistency(state)
    assert problems == [], "seed consistency failures:\n  " + "\n  ".join(problems)


def test_seed_is_at_the_scale_the_plan_specifies(state):
    """Positive control on the seed's own size. A seed that silently shrank would make
    every tension test below pass over a smaller, easier world."""
    assert len(state.initiatives) == 3
    assert len(state.phases) == 12
    assert 12 <= len(state.projects) <= 15
    assert len(state.sites) == 4
    # 9, not 8: C9 is deliberately uncovered so the coverage-gap verb has data.
    assert len(state.capabilities) == 9
    assert len(state.processes) == 2
    assert len(state.technologies) == 5
    assert len(state.organizations) == 3


# ─────────────────────────────────────────────────────────────────────────────
# TENSION (a) — FY26-Q3 requirements exceed the cap. "Why is Q3 red?"
# ─────────────────────────────────────────────────────────────────────────────

def test_tension_a_q3_is_over_its_cap(state):
    rows = measures.plan_cost_curve(state)
    q3 = next(r for r in rows if r["period"] == "FY26-Q3")
    # hand-computed: capex 2.20 + 1.80 + 0.20 = 4.20M; expense 0.40 + 0.30 + 0.15 = 0.85M
    assert q3["capex"] == pytest.approx(4.20 * M)
    assert q3["expense"] == pytest.approx(0.85 * M)
    assert q3["total"] == pytest.approx(5.05 * M)
    assert q3["cap"] == pytest.approx(4.00 * M)
    assert q3["over_cap"] is True
    assert q3["overage"] == pytest.approx(1.05 * M)


def test_an_uncapped_period_is_honestly_uncapped_not_capped_at_zero(state):
    """FY27-Q2 has no cap line. The honest render is 'no cap recorded', never a zero that
    paints the bar red — the deliberate-empty discipline, at the data layer where it starts."""
    rows = measures.plan_cost_curve(state)
    q = next(r for r in rows if r["period"] == "FY27-Q2")
    assert q["cap"] is None
    assert q["over_cap"] is False
    assert q["overage"] is None


# ─────────────────────────────────────────────────────────────────────────────
# TENSION (b) — an FS dependency a natural drag-left would violate
# ─────────────────────────────────────────────────────────────────────────────

def test_tension_b_baseline_has_no_violations(state):
    """The trap must be UNSPRUNG at rest. A baseline that already shows red teaches the room
    to ignore red, which destroys the diff card's only signal."""
    assert measures.plan_dependency_violations(state) == []


def test_tension_b_dragging_p5_left_springs_the_trap(state):
    """D4: P3 finishes 2026-06-30, P5 must start >= 14 days later (2026-07-14). Moving P5
    left to relieve the Q3 peak — the natural first move in the room — violates it."""
    from agent_fleet.planning_agent.state import MoveProject, apply_ops
    from agent_fleet.planning_agent.types import Interval

    moved = apply_ops(state, [MoveProject("P5", Interval("2026-07-01", "2026-09-30"))])
    violations = measures.plan_dependency_violations(moved)
    assert len(violations) == 1
    v = violations[0]
    assert v["dependency_id"] == "D4"
    assert v["dep_type"] == "FS"
    assert v["required_earliest_start"] == "2026-07-14"
    assert v["actual_start"] == "2026-07-01"
    assert v["shortfall_days"] == 13


# ─────────────────────────────────────────────────────────────────────────────
# TENSION (c) — Site B over threshold in FY26-Q4
# ─────────────────────────────────────────────────────────────────────────────

def test_tension_c_site_b_is_over_threshold_in_q4(state):
    rows = measures.plan_site_load(state)
    cell = next(r for r in rows if r["site_id"] == "S2" and r["period"] == "FY26-Q4")
    # hand-computed: P8 1.2 + P12 0.9 + P13 0.6 = 2.7 against a 2.0 threshold
    assert cell["load"] == pytest.approx(2.7)
    assert cell["threshold"] == pytest.approx(2.0)
    assert cell["over_threshold"] is True
    assert sorted(cell["contributors"]) == ["P12", "P13", "P8"]


def test_no_other_site_period_is_over_threshold(state):
    """Pins the tension as THE tension. If a second cell goes red, the demo's 'which sites
    are getting hammered' beat stops having one answer."""
    over = [(r["site_id"], r["period"]) for r in measures.plan_site_load(state) if r["over_threshold"]]
    assert over == [("S2", "FY26-Q4")]


# ─────────────────────────────────────────────────────────────────────────────
# TENSION (d) — one org's commitments leave a visible gap
# ─────────────────────────────────────────────────────────────────────────────

def test_tension_d_o3_underfunds_initiative_3_in_q4(state):
    rows = measures.plan_funding_gap(state, group_by="org")
    o3_q4 = next(r for r in rows if r["org_id"] == "O3" and r["period"] == "FY26-Q4")
    # required 1.00 + 0.40 + 0.80 + 0.30 = 2.50M; committed 0.90 + 0.50 = 1.40M
    assert o3_q4["required"] == pytest.approx(2.50 * M)
    assert o3_q4["committed"] == pytest.approx(1.40 * M)
    assert o3_q4["gap"] == pytest.approx(1.10 * M)


def test_a_fully_funded_period_shows_no_gap(state):
    """The gap measure must be able to say zero. A measure that only ever finds problems is
    indistinguishable from one that is broken in the direction of alarm."""
    rows = measures.plan_funding_gap(state, group_by="org")
    o1_q3 = next(r for r in rows if r["org_id"] == "O1" and r["period"] == "FY26-Q3")
    assert o1_q3["gap"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# TENSION (e) — a capability path that misses its process plateau
# ─────────────────────────────────────────────────────────────────────────────

def test_tension_e_c4_has_work_outstanding_past_its_process_plateaus(state):
    """C4 enables BP2. Its last contributor (P10) runs to 2027-06-30, which is after BOTH
    BP2-T1 (2026-06-30) and BP2-T2 (2026-12-31).

    THE FIRST DRAFT OF THIS TEST ASSERTED ONLY BP2-T2 AND WAS WRONG — the measure was right
    and the assertion was the error. Recorded because it is the same overclaim the measure's
    own field name carried: it is tempting to think of one plateau as "the" missed one, when
    what the model actually supports is "contributions still landing after this date," which
    is true of both.
    """
    path = measures.plan_capability_path(state, capability_id="C4")
    assert [r["project_id"] for r in path["projects"]] == ["P8", "P10"]
    assert path["last_contribution_end"] == "2027-06-30"

    outstanding = [m for m in path["plateaus"] if m["contributions_outstanding"]]
    assert [m["plateau_id"] for m in outstanding] == ["BP2-T1", "BP2-T2"]

    t2 = next(m for m in outstanding if m["plateau_id"] == "BP2-T2")
    assert t2["target_date"] == "2026-12-31"
    assert t2["outstanding_days"] == 181

    # BP2-T3 (2027-09-30) is AFTER the last contribution, so nothing is outstanding for it.
    t3 = next(m for m in path["plateaus"] if m["plateau_id"] == "BP2-T3")
    assert t3["contributions_outstanding"] is False
    assert t3["outstanding_days"] is None


def test_a_capability_whose_work_lands_early_reports_nothing_outstanding(state):
    """C3's contributors all finish by 2026-09-30, ahead of BP2-T2. Negative control — a
    measure that only ever finds problems is indistinguishable from one broken toward alarm."""
    path = measures.plan_capability_path(state, capability_id="C3")
    t2 = next(m for m in path["plateaus"] if m["plateau_id"] == "BP2-T2")
    assert t2["contributions_outstanding"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Honest-empty — the deliberate-empty discipline at the measure layer
# ─────────────────────────────────────────────────────────────────────────────

def test_an_unknown_capability_refuses_rather_than_returning_empty(state):
    """A measure asked about something not in the model must SAY SO. Returning an empty
    result set is the shape that renders as 'no contributing projects', which is a false
    statement about a capability that does not exist."""
    with pytest.raises(measures.NotInModel) as exc:
        measures.plan_capability_path(state, capability_id="C99")
    assert "C99" in str(exc.value)


def test_a_project_with_no_site_impact_is_absent_not_zero(state):
    """P1 touches no site. It must not appear as a zero-load contributor anywhere — a zero
    that looks like data is the failure Gate 1's honest-empty criterion names."""
    rows = measures.plan_site_load(state)
    assert all("P1" not in r["contributors"] for r in rows)
