"""The diff verb — INV-3's engine. "The answer to what-if is a diff, not a state."

ADR-0042 OQ2 resolved this as ONE VERB OVER TWO STATE REFS, which is only expressible because
Seam 1 made scenarios server-addressable and `apply_ops` never mutates its input. Run every
measure over both states, subtract, and emit effects.

WHAT THESE TESTS ARE ACTUALLY DEFENDING:

  * NO LLM ANYWHERE NEAR A NUMBER. Every magnitude is computed and every one of these
    assertions is a hand-computed literal from the seed. The plan's highest-severity
    correctness risk is "diff magnitudes wrong in the room", and its stated mitigation is
    exactly this file.

  * DIRECTION IS A JUDGEMENT AND THE MEASURE OWNS IT. "Cost went down" is improved; "load went
    up" is degraded; "a violation appeared" is degraded regardless of magnitude. A diff engine
    that reports deltas without direction makes the room do the interpretation, which is the
    work the tool exists to remove.

  * MATERIALITY FLOORS SUPPRESS NOISE, NOT SIGNAL. A floor that hides a new constraint
    violation because the number is small would be a floor that hides the thing most worth
    seeing.
"""
from __future__ import annotations

import pytest

from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed
from agent_fleet.planning_agent.state import MoveProject, PlanStore, SetCost
from agent_fleet.planning_agent.entities import Interval

M = 1_000_000.0


@pytest.fixture
def store():
    return PlanStore(build_seed())


def _diff(store: PlanStore, scenario_id: str):
    return measures.plan_diff(
        store.resolve(scenario_id), baseline_state=store.resolve("baseline")
    )


# ─────────────────────────────────────────────────────────────────────────────

def test_an_unchanged_scenario_produces_NO_effects(store):
    """The floor. A fork with no ops must diff to nothing — if it does not, every real diff is
    buried in noise and the card stops being readable."""
    store.fork("SC1", "untouched")
    assert _diff(store, "SC1")["effects"] == []


def test_a_cost_reduction_reads_as_IMPROVED_with_a_computed_magnitude(store):
    """Hand-computed: FY26-Q3 capex 2.20M -> 1.20M, so total 5.05M -> 4.05M, a 1.00M drop."""
    store.fork("SC1", "trim P3")
    store.append_op("SC1", SetCost("P3", "capex", "FY26-Q3", 1.20 * M))
    effects = _diff(store, "SC1")["effects"]

    cost = [e for e in effects if e["metric"] == "plan_cost_curve"]
    assert len(cost) == 1
    assert cost[0]["direction"] == "improved"
    assert cost[0]["delta"] == pytest.approx(-1.00 * M)
    assert "FY26-Q3" in cost[0]["affected"]
    # The magnitude is FORMATTED FROM THE COMPUTED VALUE, never authored.
    assert "1.00M" in cost[0]["magnitude"] and "FY26-Q3" in cost[0]["magnitude"]


def test_a_new_constraint_violation_reads_as_DEGRADED(store):
    """The seeded trap. Dragging P5 left to relieve Q3 breaks D4 — and a violation is degraded
    on APPEARANCE, not on magnitude: 'you broke a dependency' has no small version."""
    store.fork("SC1", "slide P5 left")
    store.append_op("SC1", MoveProject("P5", Interval("2026-07-01", "2026-09-30")))
    effects = _diff(store, "SC1")["effects"]

    dep = [e for e in effects if e["metric"] == "plan_dependency_violations"]
    assert len(dep) == 1
    assert dep[0]["direction"] == "degraded"
    assert dep[0]["delta"] == 1
    assert "D4" in dep[0]["affected"]


def test_the_seeded_TRADE_appears_as_two_effects_in_opposite_directions(store):
    """The demo's INV-3 beat. One move, one thing better and one thing worse — which is the
    whole reason a diff beats a state: the room sees the price, not just the win."""
    store.fork("SC1", "Option A")
    store.append_op("SC1", SetCost("P3", "capex", "FY26-Q3", 1.20 * M))   # Q3 improves
    store.append_op("SC1", MoveProject("P5", Interval("2026-07-01", "2026-09-30")))  # D4 breaks
    effects = _diff(store, "SC1")["effects"]

    directions = {e["metric"]: e["direction"] for e in effects}
    assert directions["plan_cost_curve"] == "improved"
    assert directions["plan_dependency_violations"] == "degraded"


def test_the_scripted_drag_pushes_Site_B_OVER_and_reads_as_DEGRADED(store):
    """The demo's consequence beat: the room's own move crosses the line.

    THIS TEST GOT THE BEAT IT ORIGINALLY ASKED FOR. Its first version tried exactly this —
    push a site over by moving a window, assert `degraded` — and FAILED, because the seed then
    held Site B already over and no site had the headroom to be pushed. The failure was
    recorded honestly rather than engineered around, with the condition for fixing it stated:

        "A new breach needs a new impact... If a 'push a site over' beat is ever wanted, the
         seed needs the headroom first."

    The seed was given that headroom on 2026-08-24 by ruling: Site B now sits at 1.8 against
    its 2.0 line, visibly near the ceiling, and P12's impact is PARKED in FY27-Q1. Pulling it
    back into Q4 restores 2.7 and crosses. So this test is the prediction being collected.
    """
    from agent_fleet.planning_agent.state import MoveSiteImpact
    store.fork("SC1", "pull the supplier feed forward")
    store.append_op("SC1", MoveSiteImpact("P12", "S2", Interval("2026-07-15", "2026-09-30")))
    effects = _diff(store, "SC1")["effects"]

    load = [e for e in effects if e["metric"] == "plan_site_load"]
    assert load, "crossing a threshold must be reported — the consequence IS the beat"
    assert load[0]["direction"] == "degraded"
    assert load[0]["affected"] == ["S2/FY26-Q4"]


def test_the_same_move_REVERSED_reads_as_relief(store):
    """The other direction, kept because a diff that only ever degrades is a diff nobody
    trusts. From the crossed state, parking the impact again clears the cell."""
    from agent_fleet.planning_agent.state import MoveSiteImpact
    store.fork("SC1", "cross it")
    store.append_op("SC1", MoveSiteImpact("P12", "S2", Interval("2026-07-15", "2026-09-30")))
    crossed = store.resolve("SC1")

    store.fork("SC2", "park it again", base="SC1")
    store.append_op("SC2", MoveSiteImpact("P12", "S2", Interval("2026-10-01", "2026-12-31")))
    from agent_fleet.planning_agent import measures as _m
    after = [r for r in _m.plan_site_load(store.resolve("SC2"))
             if r["site_id"] == "S2" and r["over_threshold"]]
    before = [r for r in _m.plan_site_load(crossed)
              if r["site_id"] == "S2" and r["over_threshold"]]
    assert before and not after


# ─────────────────────────────────────────────────────────────────────────────
# Materiality
# ─────────────────────────────────────────────────────────────────────────────

def test_a_trivial_cost_change_is_SUPPRESSED_as_noise(store):
    """Below the floor. A card listing a $50 move alongside a $1M move has made both
    unreadable."""
    store.fork("SC1", "rounding")
    store.append_op("SC1", SetCost("P3", "capex", "FY26-Q3", 2.20 * M + 50))
    assert [e for e in _diff(store, "SC1")["effects"] if e["metric"] == "plan_cost_curve"] == []


def test_a_new_violation_is_NEVER_suppressed_however_small(store):
    """The floor must not hide the thing most worth seeing. Constraint violations are counted,
    not measured, so no monetary floor can apply to them — asserted because a future
    'unify the floors' refactor is exactly how this would break."""
    store.fork("SC1", "slide P5 left")
    store.append_op("SC1", MoveProject("P5", Interval("2026-07-13", "2026-10-12")))  # 1 day short
    dep = [e for e in _diff(store, "SC1")["effects"] if e["metric"] == "plan_dependency_violations"]
    assert dep and dep[0]["delta"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# The contract of the verb itself
# ─────────────────────────────────────────────────────────────────────────────

def test_the_diff_names_no_view_and_declares_its_output_type():
    """ADR-0042 §2 at the verb layer. A diff is a DELTA_SET's payload; which archetype draws it
    is select_presentation's decision."""
    assert measures.OUTPUT_URI["plan_diff"] == "http://invincible-agent/mesh#EffectSet"


def test_every_effect_carries_the_four_fields_a_card_needs(store):
    store.fork("SC1", "Option A")
    store.append_op("SC1", SetCost("P3", "capex", "FY26-Q3", 1.20 * M))
    for e in _diff(store, "SC1")["effects"]:
        assert set(e) >= {"metric", "direction", "magnitude", "affected", "delta"}
        assert e["direction"] in ("improved", "degraded", "neutral")
        assert isinstance(e["affected"], list)


def test_the_diff_does_not_mutate_either_state(store):
    """It is a comparison. If it mutated, the second call would diff against the first call's
    output — and the failure would look like a flickering card."""
    store.fork("SC1", "Option A")
    store.append_op("SC1", SetCost("P3", "capex", "FY26-Q3", 1.20 * M))
    first = _diff(store, "SC1")
    second = _diff(store, "SC1")
    assert first == second
