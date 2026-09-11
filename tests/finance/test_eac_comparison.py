"""R-001's consequence line: all three EAC methods on one panel.

The ruling says pinning hides the divergence that is the finding, and it was UNSATISFIABLE from
the day it was ruled — `fin_eac_calculation` takes one `method` Literal, so one panel is one
invocation is one method. These seals cover the sibling verb that makes the ruling keepable.
"""
from __future__ import annotations

import pytest

from agent_fleet.finance_agent import measures
from agent_fleet.finance_agent.entities import MethodRequired, NotInModel
from agent_fleet.finance_agent.measures import EAC_METHODS, SUMMARY
from agent_fleet.finance_agent.seed import build_seed


@pytest.fixture(scope="module")
def state():
    return build_seed()


@pytest.fixture(scope="module")
def program_id(state):
    return state.programs[0].program_id


def test_ALL_THREE_METHODS_ARE_PRESENT(state, program_id):
    """One row per recognised method, and the population is EAC_METHODS rather than a literal
    three — a fourth method added to the enum must appear here without editing this test."""
    rows = measures.fin_eac_comparison(state, program_id=program_id)
    assert [r["method"] for r in rows] == list(EAC_METHODS)
    assert all(r["formula"] for r in rows), "a method without its formula is an uninterpretable number"


def test_THE_METHODS_ACTUALLY_DISAGREE(state, program_id):
    """WITHOUT THIS THE WHOLE VERB IS DECORATIVE. If the three formulas produced the same figure
    on this seed, the panel would show three identical numbers and the ruling it satisfies would
    be about nothing. R-001 cites $13.13M / $14.15M / $14.79M against a $12.00M budget.
    """
    rows = measures.fin_eac_comparison(state, program_id=program_id)
    values = {round(r["eac"], 2) for r in rows if r["eac"] is not None}
    assert len(values) == len(EAC_METHODS), f"methods do not diverge on this seed: {values}"
    summary = SUMMARY["fin_eac_comparison"](rows)
    assert summary["spread"] > 0
    # The ruling's own figure, to one decimal of BAC — if the seed drifts so far that the
    # spread stops being material, the ruling's premise has changed and should be re-argued.
    assert summary["spread_percent_of_bac"] > 0.05, (
        "the spread is no longer material, so 'pinning hides the divergence' no longer holds "
        "on this data and R-001 needs re-examining rather than this test relaxing")


def test_THE_SPREAD_IS_CARRIED_not_left_to_the_reader(state, program_id):
    rows = measures.fin_eac_comparison(state, program_id=program_id)
    answered = [r["eac"] for r in rows if r["eac"] is not None]
    s = SUMMARY["fin_eac_comparison"](rows)
    assert s["lowest_eac"] == min(answered) and s["highest_eac"] == max(answered)
    assert abs(s["spread"] - (max(answered) - min(answered))) < 1e-6
    assert s["all_methods_answered"] is True
    # THE ENVELOPE FACT LIVES IN ONE PLACE. A per-row copy is a fact that can disagree with
    # itself, and the card would have to choose a row to believe.
    for row in rows:
        for key in ("spread", "lowest_eac", "highest_eac", "all_methods_answered"):
            assert key not in row, f"{key} leaked back onto a row"


def test_THE_COMPARISON_HAS_NO_METHOD_SLOT(state, program_id):
    """R-001's scope test is whether a reader shown the panel would want to know a choice was
    made. Here none is: that is the verb's whole reason to exist."""
    from agent_fleet.finance_agent.slots import slots_for

    names = {s["name"] for s in slots_for("fin_eac_comparison")}
    assert "method" not in names, "the comparison verb must not take the choice it exists to avoid"
    assert "program_id" in names


def test_THE_SINGLE_METHOD_VERB_STILL_REFUSES(state, program_id):
    """The sibling must not have weakened the mandatory slot. Asked for ONE forecast, a reader
    would want to know a choice was made — so that verb still refuses without one."""
    with pytest.raises(MethodRequired):
        measures.fin_eac_calculation(state, program_id=program_id, method=None)


def test_AN_UNDEFINED_METHOD_KEEPS_ITS_ROW(state, program_id, monkeypatch):
    """Dropping it would turn a comparison of three into a comparison of two WITHOUT APPEARING
    TO — and the divergence is the point, so a quietly shorter panel is the specific failure
    this verb exists to prevent.
    """
    monkeypatch.setattr(measures, "_ratio", lambda a, b: 0.0)
    try:
        rows = measures.fin_eac_comparison(state, program_id=program_id)
    except NotInModel:
        pytest.skip("VOID: with every index zeroed the verb refuses outright, which is a "
                    "different (and correct) path - this seal needs a PARTIAL failure")
    assert len(rows) == len(EAC_METHODS), "a method vanished instead of reporting why"
    blank = [r for r in rows if r["eac"] is None]
    assert blank, "this seal proves nothing unless at least one method is undefined here"
    for r in blank:
        assert r["unavailable_reason"], f"{r['method']} is blank and does not say why"
        assert r["vac"] is None and r["etc"] is None, "derived figures on an absent forecast"
    assert SUMMARY["fin_eac_comparison"](rows)["all_methods_answered"] is False


def test_THE_PANEL_CAN_NEVER_COME_BACK_EMPTY(state, program_id, monkeypatch):
    """I wrote a refusal for "every method undefined" and it was UNREACHABLE.

    `REMAINING_AT_BUDGET` is ACWP + (BAC - BCWP): arithmetic over figures that always exist,
    projecting no index. So it answers whenever the program does, and a blank three-row panel
    is impossible. The guard that could not fire is gone and the invariant is asserted at the
    point it would break — this seal is what makes that a checked claim rather than a comment.
    """
    monkeypatch.setattr(measures, "_totals", lambda *a, **k: (0.0, 0.0, 0.0))
    monkeypatch.setattr(measures, "_ratio", lambda a, b: 0.0)
    rows = measures.fin_eac_comparison(state, program_id=program_id)
    answered = [r for r in rows if r["eac"] is not None]
    assert [r["method"] for r in answered] == ["REMAINING_AT_BUDGET"], (
        "with every index zeroed, exactly the index-free method should still answer")
    s = SUMMARY["fin_eac_comparison"](rows)
    assert s["all_methods_answered"] is False
    assert s["spread"] == 0, "one answer has no spread, and that is not a disagreement"


def test_IT_IS_NOT_BOUND_TO_FORECAST_MEASURE():
    """UNBOUND ON PURPOSE, and the refusal is written down rather than left as an absence.

    FORECAST_MEASURE declares `exactlyOneRow: true` — "One forecast. A list of them is a series,
    which is a different archetype." A three-row payload would be REFUSED by the component, so
    binding there would produce a card that never draws. No existing archetype fits: the three
    values do not sum to a total (CONTRIBUTION_RANKING), are not a before-and-after (DELTA_SET),
    and are not indexed by period (MULTI_SERIES). They are COMPETING MEASUREMENTS OF ONE
    QUANTITY, which is a distinct axis and wants its own archetype.

    Unbound beats mis-bound: a mis-binding renders something plausible and wrong.
    """
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    bound = {b["subject_uri"] for b in PRESENTATION_CAPABILITIES}
    assert "fin:EstimateAtCompletionComparison" not in bound, (
        "if this is now bound, delete this seal and add a conformance case - but check the "
        "archetype accepts more than one row first")


def test_STRUCTURAL_NAMES_RIDE_BESIDE_THE_DOMAIN_ONES(state, program_id):
    """COMPETING_MEASURES is structurally named — three inflation indices want this card and
    none of them has an `eac`. cortex built an alias when my payload sent only domain names.

    Engine F's own rule answers it without a rename: emit both. The card reads its vocabulary,
    an analyst reading the payload still sees theirs, and neither side translates.

    WHAT THIS CANNOT DISTINGUISH: whether cortex actually prefers the structural name. It
    asserts the pair agrees, not which one is read.
    """
    rows = measures.fin_eac_comparison(state, program_id=program_id)
    for r in rows:
        assert r["value"] == r["eac"], f"{r['method']}: the two names disagree"
    s = SUMMARY["fin_eac_comparison"](rows)
    assert s["lowest_value"] == s["lowest_eac"] and s["highest_value"] == s["highest_eac"]


def test_AN_UNDEFINED_METHOD_IS_NULL_UNDER_BOTH_NAMES(state, program_id, monkeypatch):
    """An alias that stays populated when its twin goes null is worse than no alias: the card
    would read a stale figure for a method that could not be computed."""
    monkeypatch.setattr(measures, "_ratio", lambda a, b: 0.0)
    rows = measures.fin_eac_comparison(state, program_id=program_id)
    blank = [r for r in rows if r["eac"] is None]
    assert blank, "no method is undefined here - this seal proves nothing"
    for r in blank:
        assert r["value"] is None, f"{r['method']}: `value` survived a null `eac`"
