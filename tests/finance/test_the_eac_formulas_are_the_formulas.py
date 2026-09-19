"""The EAC forecast can be INVERTED and nothing notices. Five of six mutations survived.

R-029's mutate-the-unit check, run before the `fin_eac_calculation` extraction. Standing seal
`803071e`, 2026-09-02, twelve days old:

    CPI method: bac * cpi instead of bac / cpi        ->  0 red   ⚠
    REMAINING_AT_BUDGET drops the spend               ->  0 red   ⚠
    CPI_SPI divides by cpi only, not cpi * spi        ->  1 red   ✅
    vac sign flipped                                  ->  0 red   ⚠
    etc measured from bcwp instead of acwp            ->  0 red   ⚠
    percent_complete over acwp instead of bac         ->  0 red   ⚠

**Every survivor changes real values here** — checked before claiming:

    bac/cpi      14,152,381   vs   bac*cpi      10,174,966
    acwp+(bac-bcwp) 13,130,000 vs  bac-bcwp      5,700,000
    vac            -2,152,380  vs  flipped      +2,152,380
    etc from acwp   6,722,380  vs  from bcwp     7,852,380
    percent          0.5250    vs                  0.8479

── WHY THIS IS THE WORST OF THE THREE VERBS CHECKED SO FAR ──────────────────────────────────
**The CPI mutation does not make the forecast wrong by a margin — it reverses its sign.** The
correct answer says this program will overrun by 2.15M; multiplying instead of dividing says it
lands 1.8M **under** budget. A reader acts on the difference between "we are over" and "we are
under", and nothing in 151 tests could tell them apart.

`vac` flipped is the same reversal one field along, and `percent_complete` over ACWP turns a
program half complete into one 85% complete — **each pointing the same reassuring way.**

**TEST-ONLY. The verb is correct.** Every formula matches public EVM methodology, as the module
docstring states: `EAC = ACWP + (BAC − BCWP)`, `EAC = BAC / CPI`,
`EAC = ACWP + (BAC − BCWP) / (CPI × SPI)`. What was missing is any assertion that the code
computes what the docstring says.

── THE ONE THAT DID RED, AND WHY IT IS NOT REASSURING ───────────────────────────────────────
`CPI_SPI` dividing by `cpi` alone reds — through `fin_eac_comparison`'s seals, which compare the
three methods' spread. **A spread check notices when one method moves relative to the others; it
cannot notice all three being wrong in the same direction, nor a single method being wrong in a
way that keeps the ordering.** `bac * cpi` keeps CPI below CPI_SPI and the comparison stays
happy.
"""
from __future__ import annotations

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PROGRAM = "NP-MERIDIAN"
METHODS = ("REMAINING_AT_BUDGET", "CPI", "CPI_SPI")


def _row(method):
    return m.fin_eac_calculation(STATE, program_id=PROGRAM, method=method)[0]


@pytest.fixture(scope="module")
def rows():
    out = {meth: _row(meth) for meth in METHODS}
    assert len(out) == 3, "not every method answered; seals below would skip silently"
    return out


def test_REMAINING_AT_BUDGET_is_spend_to_date_plus_the_work_left_at_budget(rows):
    """EAC = ACWP + (BAC − BCWP). It projects NO index, which is why it always answers.

    Recomputed from the row's own published quantities, so the check cannot pass by restating
    the expression — it asserts the response is internally consistent.
    """
    row = rows["REMAINING_AT_BUDGET"]
    assert row["eac"] == pytest.approx(row["acwp"] + (row["bac"] - row["bcwp"]))


def test_the_CPI_method_DIVIDES_by_the_index_and_does_not_multiply(rows):
    """⚠ THE INVERSION. EAC = BAC / CPI.

    With CPI below 1 — work costing more than it earns — dividing raises the forecast and
    multiplying lowers it. **The mutation does not shift the number, it reverses the finding**,
    and this is the assertion that pins which way round it goes.
    """
    row = rows["CPI"]
    assert row["eac"] == pytest.approx(row["bac"] / row["cpi"])
    assert row["eac"] != pytest.approx(row["bac"] * row["cpi"]), (
        "dividing and multiplying agree here, so the seed cannot discriminate"
    )


def test_the_index_is_BELOW_ONE_so_the_direction_is_actually_exercised(rows):
    """THE CONTROL. At CPI exactly 1.0 multiply and divide agree and the seal above proves
    nothing; above 1.0 it still discriminates but tests the opposite sign of the finding."""
    cpi = rows["CPI"]["cpi"]
    assert cpi < 1.0, (
        f"cpi is {cpi}; this seed no longer shows a program overrunning, so the inversion "
        f"mutation tests a direction the fixture does not exercise"
    )


def test_CPI_SPI_divides_the_remaining_work_by_BOTH_indices(rows):
    """EAC = ACWP + (BAC − BCWP) / (CPI × SPI). Dividing by one index is a different method
    wearing this one's name."""
    row = rows["CPI_SPI"]
    assert row["eac"] == pytest.approx(
        row["acwp"] + (row["bac"] - row["bcwp"]) / (row["cpi"] * row["spi"])
    )
    assert row["spi"] != pytest.approx(1.0), (
        "spi is 1.0, so dividing by cpi alone would be an equivalent mutant"
    )


@pytest.mark.parametrize("method", METHODS)
def test_VAC_is_BUDGET_MINUS_FORECAST_so_a_negative_means_overrun(method):
    """The sign is the finding. Flipped, an overrun reads as an underrun."""
    row = _row(method)
    assert row["vac"] == pytest.approx(row["bac"] - row["eac"])


def test_the_VAC_is_actually_NEGATIVE_here_so_the_flip_is_detectable():
    """THE CONTROL for the sign. On a program forecast exactly at budget, VAC is zero and the
    flip is an equivalent mutant."""
    assert _row("CPI")["vac"] < 0, (
        "vac is not negative in this seed, so a flipped sign convention would be undetectable"
    )


@pytest.mark.parametrize("method", METHODS)
def test_ETC_is_measured_from_WHAT_HAS_BEEN_SPENT_not_from_what_was_earned(method):
    """ETC = EAC − ACWP: what the remaining work is forecast to cost FROM HERE.

    Measuring from BCWP answers a different question — how much more the forecast exceeds the
    value already earned — and the two differ by exactly the cost variance.
    """
    row = _row(method)
    assert row["etc"] == pytest.approx(row["eac"] - row["acwp"])
    assert row["acwp"] != pytest.approx(row["bcwp"]), (
        "acwp equals bcwp, so measuring ETC from either would be undetectable"
    )


@pytest.mark.parametrize("method", METHODS)
def test_percent_complete_is_VALUE_EARNED_OVER_BUDGET(method):
    """BCWP / BAC — how much of the authorised work is done.

    Over ACWP it becomes a performance index wearing a progress label, and in this seed that
    turns a program 52% complete into one reading 85%.
    """
    row = _row(method)
    assert row["percent_complete"] == pytest.approx(row["bcwp"] / row["bac"])
    assert row["bac"] != pytest.approx(row["acwp"])


def test_the_method_and_its_formula_ride_on_every_row(rows):
    """Not metadata: they are the half of the answer that makes the number interpretable.

    A card showing the figure without them reproduces exactly the ambiguity the mandatory
    method slot exists to refuse.
    """
    for method, row in rows.items():
        assert row["method"] == method
        assert row["formula"] == m.EAC_FORMULA[method]
        assert row["formula"], "an empty formula string is worse than an absent one"


def test_the_three_methods_do_not_all_agree(rows):
    """THE CONTROL ON THE WHOLE FILE. If every method returned the same figure, most of the
    assertions above could be satisfied by the wrong formula — and `fin_eac_comparison`'s
    spread would be zero, which is the state its own seals were written to detect."""
    values = {round(row["eac"], 2) for row in rows.values()}
    assert len(values) == 3, f"methods collapsed to {values}"
