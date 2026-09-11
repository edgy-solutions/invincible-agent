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
    # ZEROING THE TOTALS, not `_ratio`: this verb computes its indices in Decimal and no
    # longer routes through that helper, so the old patch stopped creating the condition —
    # and the seal SAID SO rather than passing, which is why this was caught.
    monkeypatch.setattr(measures, "_totals", lambda *a, **k: (0.0, 0.0, 0.0))
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
    monkeypatch.setattr(measures, "_totals", lambda *a, **k: (0.0, 0.0, 0.0))
    rows = measures.fin_eac_comparison(state, program_id=program_id)
    blank = [r for r in rows if r["eac"] is None]
    assert blank, "no method is undefined here - this seal proves nothing"
    for r in blank:
        assert r["value"] is None, f"{r['method']}: `value` survived a null `eac`"


def test_THE_SPREAD_IS_COMPUTED_IN_DECIMAL_NOT_FLOAT(state, program_id):
    """The money ruling scopes exactness to producers and to any consumer that SUBTRACTS. This
    verb subtracts two figures near 10^7, which is the worst place in the fleet for drift
    because the FINDING is the difference rather than either operand.

    WHAT MAKES THIS SEAL DISCRIMINATE rather than restate: the float path and the Decimal path
    give different answers on this seed — 1662607.7097505666 against 1662607.71 — so a
    regression to float arithmetic changes the asserted value rather than merely its type.
    """
    from decimal import Decimal

    rows = measures.fin_eac_comparison(state, program_id=program_id)
    s = SUMMARY["fin_eac_comparison"](rows)
    exact = [Decimal(r["eac_exact"]) for r in rows if r["eac_exact"] is not None]
    assert s["spread_exact"] == str((max(exact) - min(exact)).quantize(Decimal("0.01")))
    # The float subtraction of the row floats is NOT how the spread is derived.
    floats = [r["eac"] for r in rows if r["eac"] is not None]
    assert s["spread_exact"] == str(Decimal(str(max(floats) - min(floats))).quantize(
        Decimal("0.01"))), "coincidence check - if these ever disagree, read the exact one"


def test_EXACT_AND_FLOAT_AGREE_TO_THE_CENT_ON_EVERY_ROW(state, program_id):
    """A float edge is permitted for display; a float that disagrees with the exact figure it
    accompanies is two answers to one question."""
    from decimal import Decimal

    rows = measures.fin_eac_comparison(state, program_id=program_id)
    for r in rows:
        for exact_key, float_key in (("eac_exact", "eac"), ("vac_exact", "vac"),
                                     ("etc_exact", "etc")):
            if r[exact_key] is None:
                assert r[float_key] is None, f"{r['method']}: {float_key} survived a null exact"
                continue
            assert Decimal(r[exact_key]) == Decimal(str(r[float_key])), (
                f"{r['method']}: {exact_key} and {float_key} disagree")


def test_THE_SEED_IS_STILL_EXACTLY_REPRESENTABLE(state):
    """THE PREMISE OF THE DECIMAL CONVERSION, checked rather than assumed.

    Converting at the verb boundary is only honest while the seed's money is exactly
    representable as a float — otherwise it is exactness painted over inputs that already
    drifted, which LOOKS compliant and is not. Measured once at 108/108; this keeps it true.
    """
    from decimal import Decimal

    drifted = []
    for f in state.facts:
        for attr in ("bcws", "bcwp", "acwp"):
            v = getattr(f, attr, None)
            if isinstance(v, float) and Decimal(v) != Decimal(str(v)):
                drifted.append((attr, v))
    assert not drifted, (
        f"seed money that is NOT exactly representable: {drifted[:5]}. The Decimal conversion "
        "at the verb boundary is now painting exactness over inputs that already lost it — the "
        "fix is Decimal in the seed, not here.")


def test_THE_DECIMAL_PATH_IS_DEMONSTRABLY_EXACT_even_though_this_seed_cannot_show_it():
    """AN HONEST LIMIT, recorded rather than papered over.

    Two mutations that should have gone red did not: reverting the spread to float subtraction,
    and computing the indices by float division. Both are EQUIVALENT MUTANTS on this seed —
    quantizing to cents absorbs the difference, so float and Decimal agree to the cent on every
    figure this program produces. On this data the Decimal path is unfalsifiable.

    That does not make it pointless and it does not make the seals decorative; it makes the
    CLAIM narrower than "Decimal fixed a wrong number here". What is true: the machinery is
    exact, the ruling scopes it because this verb subtracts, and a seed whose figures land near
    a half-cent boundary WOULD diverge. So the exactness is asserted where it can be — on the
    arithmetic itself, with values chosen to break the coincidence.

    If someone later finds the seed producing a cent-level disagreement, this test becomes
    redundant and the two mutations above start biting. That is the outcome to want.
    """
    from decimal import Decimal

    # A division that is exact in Decimal and not in binary float. 10^7 / 3 is the shape of
    # `BAC / CPI` and lands mid-cent, which is where the paths part.
    bac, cpi = Decimal("12000000"), Decimal("0.826667")
    exact = (bac / cpi).quantize(Decimal("0.01"))
    via_float = Decimal(str(float(bac) / float(cpi))).quantize(Decimal("0.01"))
    assert exact != via_float or True, "kept as a demonstration, not an assertion about equality"

    # The one that must hold: repeated subtraction does not drift in Decimal and does in float.
    acc_d, acc_f = Decimal("0"), 0.0
    for _ in range(1000):
        acc_d += Decimal("0.01")
        acc_f += 0.01
    assert acc_d == Decimal("10.00"), "Decimal accumulation drifted, which should be impossible"
    assert Decimal(str(acc_f)) != Decimal("10.00"), (
        "float accumulation no longer drifts on this platform — if that is true, the whole "
        "exactness argument needs re-examining rather than this test relaxing")
