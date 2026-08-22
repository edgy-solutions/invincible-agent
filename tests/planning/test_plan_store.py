"""The server-side plan store — Seam 1's ruling, under test.

WHAT THIS FILE IS DEFENDING. The plan's Seam-1 ruling moved plan state to the server because
a server verb cannot read a browser selector. That ruling is only worth anything if the
properties it depends on actually hold: that `apply_ops` never mutates its input (or a diff
compares a state against itself), that a scenario resolves through its base (or forking a
fork silently loses ops), that baseline cannot be edited by a drag (the anti-goal), and that
a bad op is rejected at POST time rather than surfacing at read time.

Each test below is one of those properties. None of them is about "does the store work."
"""
from __future__ import annotations

import copy

import pytest

from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed
from agent_fleet.planning_agent.state import (
    MoveProject, MoveSiteImpact, PlanStore, SetCommitment, SetCost, UnknownTarget, apply_ops,
)
from agent_fleet.planning_agent.entities import Interval

M = 1_000_000.0


@pytest.fixture
def store():
    return PlanStore(build_seed())


# ─────────────────────────────────────────────────────────────────────────────
# Purity — the property the whole diff engine rests on
# ─────────────────────────────────────────────────────────────────────────────

def test_apply_ops_does_not_mutate_its_input():
    """If this fails, EVERY diff is a comparison of a state against itself and reads as
    'no change'. The most expensive possible silent failure in this subsystem."""
    base = build_seed()
    before = copy.deepcopy(base)
    apply_ops(base, [MoveProject("P5", Interval("2027-01-01", "2027-03-31"))])
    assert base.project("P5").planned == before.project("P5").planned
    assert len(base.requirements) == len(before.requirements)


def test_a_measure_over_two_states_is_the_diff(store):
    """ADR-0042 OQ2, resolved as 'one verb over two state refs'. This is the mechanism."""
    baseline_rows = measures.plan_cost_curve(store.resolve("baseline"))
    store.fork("SC1", "Option A")
    store.append_op("SC1", SetCost("P3", "capex", "FY26-Q3", 1.20 * M))
    scenario_rows = measures.plan_cost_curve(store.resolve("SC1"))

    b_q3 = next(r for r in baseline_rows if r["period"] == "FY26-Q3")
    s_q3 = next(r for r in scenario_rows if r["period"] == "FY26-Q3")
    assert b_q3["total"] == pytest.approx(5.05 * M)
    assert s_q3["total"] == pytest.approx(4.05 * M)   # 2.20 -> 1.20 capex
    assert b_q3["over_cap"] is True
    assert s_q3["over_cap"] is True                   # 4.05 still over the 4.00 cap
    assert s_q3["overage"] == pytest.approx(0.05 * M)


def test_ops_apply_in_order_so_the_later_move_wins(store):
    """A room dragging the same bar twice expects the second drag to be what happened."""
    store.fork("SC1", "Option A")
    store.append_op("SC1", MoveProject("P5", Interval("2027-01-01", "2027-03-31")))
    store.append_op("SC1", MoveProject("P5", Interval("2027-04-01", "2027-06-30")))
    assert store.resolve("SC1").project("P5").planned.start == "2027-04-01"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_a_scenario_resolves_through_its_base(store):
    """Fork-of-a-fork is allowed and must compose. Forbidding it later is harder than
    supporting it now, and a base that silently drops its parent's ops is the worst of
    both — it looks like it worked."""
    store.fork("SC1", "Option A")
    store.append_op("SC1", MoveProject("P5", Interval("2027-01-01", "2027-03-31")))
    store.fork("SC2", "Option A prime", base="SC1")
    store.append_op("SC2", SetCost("P4", "capex", "FY26-Q3", 0.50 * M))

    s2 = store.resolve("SC2")
    assert s2.project("P5").planned.start == "2027-01-01"          # inherited from SC1
    q3 = next(r for r in measures.plan_cost_curve(s2) if r["period"] == "FY26-Q3")
    assert q3["capex"] == pytest.approx((2.20 + 0.50 + 0.20) * M)  # own op applied


def test_baseline_is_unchanged_until_commit(store):
    """The plan's Gate 3 snapshot property, asserted at the store where it is decidable."""
    store.fork("SC1", "Option A")
    store.append_op("SC1", MoveProject("P5", Interval("2027-01-01", "2027-03-31")))
    assert store.resolve("baseline").project("P5").planned.start == "2026-10-01"

    store.commit("SC1")
    assert store.resolve("baseline").project("P5").planned.start == "2027-01-01"
    assert store.scenario("SC1").archived is True
    assert store.scenarios() == []       # archived scenarios leave the working set


# ─────────────────────────────────────────────────────────────────────────────
# The anti-goal, enforced rather than documented
# ─────────────────────────────────────────────────────────────────────────────

def test_a_schedule_change_cannot_be_written_to_baseline_directly(store):
    """'No editing baseline directly from a drag' is an anti-goal. An anti-goal that lives
    only in prose is a suggestion; this is the same rule with a stack trace."""
    with pytest.raises(UnknownTarget) as exc:
        store.write_baseline_op(MoveProject("P5", Interval("2027-01-01", "2027-03-31")))
    assert "require a scenario" in str(exc.value)


def test_funding_entry_may_write_baseline_because_costs_must_persist(store):
    """The plan's ONE deliberate exception. Narrow on purpose: funding ops only."""
    v0 = store.version_of("baseline")
    store.write_baseline_op(SetCost("P3", "capex", "FY26-Q3", 3.00 * M))
    q3 = next(r for r in measures.plan_cost_curve(store.resolve("baseline")) if r["period"] == "FY26-Q3")
    assert q3["capex"] == pytest.approx((3.00 + 1.80 + 0.20) * M)
    assert store.version_of("baseline") == v0 + 1


# ─────────────────────────────────────────────────────────────────────────────
# Rejection at post time, not read time
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("op,fragment", [
    (MoveProject("P99", Interval("2027-01-01", "2027-03-31")), "unknown project"),
    (MoveProject("P5", Interval("2027-03-31", "2027-01-01")), "inverted"),
    (SetCost("P99", "capex", "FY26-Q3", 1.0), "unknown project"),
    (SetCommitment("P3", "O99", "FY26-Q3", "capex", 1.0), "unknown org"),
    (MoveSiteImpact("P1", "S1", Interval("2026-01-01", "2026-02-01")), "no impact"),
])
def test_a_bad_op_is_rejected_when_posted(store, op, fragment):
    """A silently-dropped op is the worst outcome available: the room believes it made a
    change, the diff shows nothing, and the decision artifact records an op that never
    applied. Rejecting at post time means the room finds out while it still has the context
    to understand why."""
    store.fork("SC1", "Option A")
    with pytest.raises(UnknownTarget) as exc:
        store.append_op("SC1", op)
    assert fragment in str(exc.value)
    assert store.scenario("SC1").ops == []      # nothing half-appended
    assert store.scenario("SC1").version == 0   # and no phantom version bump


def test_an_unknown_scenario_is_named_not_guessed(store):
    with pytest.raises(UnknownTarget) as exc:
        store.resolve("SC-nope")
    assert "SC-nope" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# Versioning — ADR-0042 OQ1's pull trigger
# ─────────────────────────────────────────────────────────────────────────────

def test_the_version_bumps_on_every_op_so_a_stale_client_can_tell(store):
    """OQ1 resolved to PULL on a server-issued version. A client holding an older number
    knows to re-request; it never has to be told, which is what survives a reconnect."""
    store.fork("SC1", "Option A")
    assert store.version_of("SC1") == 0
    store.append_op("SC1", MoveProject("P5", Interval("2027-01-01", "2027-03-31")))
    assert store.version_of("SC1") == 1
    store.append_op("SC1", SetCost("P3", "capex", "FY26-Q3", 1.0 * M))
    assert store.version_of("SC1") == 2


def test_forking_an_existing_id_is_refused(store):
    store.fork("SC1", "Option A")
    with pytest.raises(UnknownTarget):
        store.fork("SC1", "Option A again")
