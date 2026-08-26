"""`plan_capability_path` claims INTERVAL_TIMELINE, so its rows must BE timeline rows.

WHY THIS IS ASSERTED AGAINST `plan_schedule` RATHER THAN A FIELD LIST. The archetype's
declared shape lives in cortex-ui's TypeScript contract, which this repo cannot import. The
tempting substitute is a hand-copied list of field names here — and that is a SECOND SOURCE
OF TRUTH for a shape this side does not own, which goes stale silently the first time the
contract grows a field.

`plan_schedule` is the archetype's incumbent producer. Comparing against it is
self-maintaining: add a field to the schedule row and this test names the path row as the
thing that drifted, which is the actual failure mode. Two producers of one archetype that
disagree about their keys render correctly until a renderer reads the field only one of them
supplies, and then the SECOND card is blank for a reason the first card's success hides.

THE MILESTONE FLAG IS NOT `overdue`, DELIBERATELY. The contract's boolean asserts a target was
missed; this model has no per-plateau maturity requirement and cannot know that. The producer
emits a generic `flag` carrying domain vocabulary instead — the `risk_flag` pattern — and this
test pins that choice so a later "the contract says overdue, just emit overdue" does not quietly
reintroduce the overclaim the verb's docstring already refused once under the name `missed`.
"""
from __future__ import annotations

import pytest

from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed


@pytest.fixture(scope="module")
def state():
    return build_seed()


def test_the_two_producers_agree_on_the_row_shape(state):
    """Positive control first: both sides must be non-empty, or this compares nothing."""
    sched = measures.plan_schedule(state, group_by="capability")
    path = measures.plan_capability_path(state, capability_id="C4")
    assert sched, "the schedule produced no rows — the comparison would be vacuous"
    assert path["rows"], "the capability path produced no rows"

    schedule_keys = set(sched[0])
    for row in path["rows"]:
        assert set(row) == schedule_keys, (
            f"capability-path row {row.get('project_id')!r} does not carry the timeline's "
            f"row shape.\n  missing: {sorted(schedule_keys - set(row))}\n"
            f"  extra:   {sorted(set(row) - schedule_keys)}"
        )


def test_the_path_states_its_pivot_rather_than_leaving_it_inferred(state):
    """The contract says `group_kind` is stated and never inferred. A renderer guessing
    "capability" from the shape of an id is how a pivot renders as the wrong one."""
    path = measures.plan_capability_path(state, capability_id="C4")
    assert path["group_kind"] == "capability"
    assert all(r["group_kind"] == "capability" for r in path["rows"])
    assert all(r["group_id"] == "C4" for r in path["rows"]), (
        "the path fanned out beyond the capability it was asked about"
    )


def test_milestones_carry_the_three_declared_marker_keys(state):
    path = measures.plan_capability_path(state, capability_id="C4")
    assert path["milestones"]
    for m in path["milestones"]:
        for key in ("milestone_id", "label", "date"):
            assert m.get(key), f"milestone missing {key}: {m}"


def test_the_marker_flag_is_generic_vocabulary_and_never_an_overdue_verdict(state):
    """See the module docstring. `overdue` claims the target was MISSED; nothing here knows."""
    path = measures.plan_capability_path(state, capability_id="C4")
    flagged = [m for m in path["milestones"] if m["flag"]]
    assert flagged, "C4's contributions land after two plateaus — expected a flagged marker"
    assert all(m["flag"] == "contributions-outstanding" for m in flagged)
    assert all("overdue" not in m for m in path["milestones"]), (
        "an `overdue` key reintroduces the overclaim this verb refused under the name `missed`"
    )
    # Negative control — a marker AFTER the last contribution claims nothing.
    assert any(m["flag"] is None for m in path["milestones"]), (
        "every marker flagged — a measure that only ever finds problems is indistinguishable "
        "from one broken toward alarm"
    )


def test_no_bar_carries_the_shared_condition_as_its_own_risk(state):
    """Outstanding-ness belongs to a (capability, plateau) pair. Painting it on a bar would
    attribute a shared condition to whichever project happens to finish last."""
    path = measures.plan_capability_path(state, capability_id="C4")
    assert all(r["risk_flag"] is None for r in path["rows"])
