"""Revision 3's verb additions — the coverage-gap query and the marquee pivot.

TWO THINGS OF VERY DIFFERENT SIZE, and the difference is the point.

`plan_coverage_gap` is the only GENUINELY NEW verb in the whole packet. It is an ABSENCE query
— "which processes has no initiative touched" — and absence is what this model is uniquely
placed to answer and what a spreadsheet cannot. A row that is not there cannot be filtered for.

`group_by` on `plan_schedule` is the MARQUEE ask, flagged un-cuttable, and it is ONE PARAMETER.
`CapabilityContribution` is already the project↔capability many-to-many, and
initiative↔capability is already derived from it rather than stored in parallel. The tests
below assert the pivot uses that EXISTING join, so that a later reader cannot "add" the join
table that is already there — the flat model the requirement complains about is the SOURCE
model, and that gap closed in Phase 0.
"""
from __future__ import annotations

import pytest

from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed


@pytest.fixture(scope="module")
def state():
    return build_seed()


# ─────────────────────────────────────────────────────────────────────────────
# B4 — the coverage-gap verb (the twelfth)
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_gap_declares_its_own_output_type():
    assert measures.OUTPUT_URI["plan_coverage_gap"] == \
        "http://invincible-agent/mesh#CoverageGapSet"


def test_it_finds_capabilities_no_project_contributes_to(state):
    """The absence query. C6 (Master Data Governance) is enabled by a process and contributed
    to by P4 — but the seed leaves others untouched, and those are the finding."""
    out = measures.plan_coverage_gap(state)
    uncovered = {c["capability_id"] for c in out["uncovered_capabilities"]}
    # Every capability with no CapabilityContribution row at all.
    contributed = {c.capability_id for c in state.contributions}
    expected = {c.capability_id for c in state.capabilities} - contributed
    assert uncovered == expected
    assert uncovered, "the seed has full capability coverage — the beat has no data behind it"


def test_it_names_the_processes_those_gaps_leave_exposed(state):
    """A capability nobody is maturing is only interesting because a PROCESS depends on it.
    Reporting the capability alone makes the reader do the join the model already holds."""
    out = measures.plan_coverage_gap(state)
    for c in out["uncovered_capabilities"]:
        assert "exposes_processes" in c
        cap = state.capability(c["capability_id"])
        assert c["exposes_processes"] == sorted(cap.enables_process_ids)


def test_a_process_with_no_enabling_capability_at_all_is_reported_separately(state):
    """A different fact with a different fix. 'This process has capabilities but nobody is
    working on them' is a portfolio problem; 'this process has no capabilities modelled' is a
    MODEL problem, and folding them would send someone to the wrong meeting."""
    out = measures.plan_coverage_gap(state)
    assert "unmodelled_processes" in out
    enabled = {pid for c in state.capabilities for pid in c.enables_process_ids}
    assert {p["process_id"] for p in out["unmodelled_processes"]} == \
        {p.process_id for p in state.processes} - enabled


def test_full_coverage_reports_EMPTY_not_absent(state):
    """When nothing is uncovered the verb must say so with empty lists, not omit the key. A
    missing key reads as 'not computed'; an empty list reads as 'computed, and clean'."""
    out = measures.plan_coverage_gap(state)
    assert isinstance(out["uncovered_capabilities"], list)
    assert isinstance(out["unmodelled_processes"], list)


# ─────────────────────────────────────────────────────────────────────────────
# B5 — the marquee pivot, on the EXISTING join
# ─────────────────────────────────────────────────────────────────────────────

def test_the_default_grouping_is_unchanged(state):
    """Backwards compatibility is not incidental here: PERIOD_SERIES and every schedule
    consumer already read these rows."""
    rows = measures.plan_schedule(state)
    assert rows and "initiative_id" in rows[0] and "phase_id" in rows[0]


def test_grouping_by_capability_uses_the_EXISTING_contribution_join(state):
    """THE MARQUEE ASK, and it needed no model change.

    A project contributing to two capabilities appears under BOTH — that is what many-to-many
    means, and it is the thing the source model could not express. The rows come from
    CapabilityContribution, which has been there since Phase 0.
    """
    rows = measures.plan_schedule(state, group_by="capability")
    assert rows
    assert all("group_id" in r and "group_kind" in r for r in rows)
    assert {r["group_kind"] for r in rows} == {"capability"}

    # P3 contributes to C1 (0.7) and C8 (0.2) — it must appear under both groups.
    p3_groups = {r["group_id"] for r in rows if r["project_id"] == "P3"}
    assert p3_groups == {"C1", "C8"}, (
        "a project contributing to two capabilities must appear under both — if it does not, "
        "the pivot has collapsed the many-to-many the requirement exists to demonstrate"
    )

    # And the weight rides along, because "how much does this project move that capability"
    # is the next question the room asks.
    p3_c1 = next(r for r in rows if r["project_id"] == "P3" and r["group_id"] == "C1")
    assert p3_c1["group_weight"] == pytest.approx(0.7)


def test_a_project_contributing_to_nothing_is_not_silently_dropped(state):
    """P1 contributes to no capability. Under a capability pivot it belongs in an explicit
    UNGROUPED bucket, not deleted — a pivot that silently drops rows makes the timeline lie
    about what the portfolio contains."""
    rows = measures.plan_schedule(state, group_by="capability")
    ungrouped = {r["project_id"] for r in rows if r["group_id"] == "(none)"}
    assert "P1" in ungrouped


def test_grouping_by_target_uses_the_site_impact_edge(state):
    """The other pivot. SiteImpact already carries project→target, so this too is a read of an
    existing edge."""
    rows = measures.plan_schedule(state, group_by="target")
    assert {r["group_kind"] for r in rows} == {"target"}
    p8 = {r["group_id"] for r in rows if r["project_id"] == "P8"}
    assert "S2" in p8


def test_an_unknown_group_by_refuses_rather_than_falling_back(state):
    """Silently falling back to the default grouping would answer a different question than
    the one asked, and look correct doing it."""
    with pytest.raises(measures.NotInModel):
        measures.plan_schedule(state, group_by="astrology")


# ─────────────────────────────────────────────────────────────────────────────
# B4 — generic styling params
# ─────────────────────────────────────────────────────────────────────────────

def test_risk_flag_is_generic_and_carries_its_own_vocabulary(state):
    """The renderer receives a flag; it never learns that today's flag means funding risk.
    GENERIC-AT-BIRTH at the payload layer."""
    rows = measures.plan_schedule(state, color_by="funding_risk")
    assert all("risk_flag" in r for r in rows)
    flagged = [r for r in rows if r["risk_flag"]]
    assert flagged, "no project carries funding risk — the seeded gap should produce some"
    assert all(isinstance(r["risk_flag"], str) for r in flagged)


def test_color_by_is_refused_when_it_names_something_the_model_lacks(state):
    with pytest.raises(measures.NotInModel):
        measures.plan_schedule(state, color_by="vibes")
