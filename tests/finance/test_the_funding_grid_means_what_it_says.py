"""`fin_funding_status`: six mutations, six survivors — three real, three equivalent.

R-029's mutate-the-unit check, run before the ADR-0053 §7 extraction.

    at_risk measured against obligated, not expended   ->  0 red   ⚠ REAL
    unexpended_balance = authorized - expended         ->  0 red   ⚠ REAL
    the window filter dropped entirely                 ->  0 red   ⚠ REAL
    shortfall loses its max(0.0, ...) floor            ->  0 red   (equivalent — see below)
    gap given the floor that belongs to shortfall      ->  0 red   (equivalent — see below)
    rows returned unsorted                             ->  0 red   (equivalent — see below)

**Which is which was measured, not guessed**, because a survivor on data that cannot
discriminate is an equivalent mutant rather than a finding:

    rows where obligated != expended            17 of 18   -> at_risk mutation is real
    rows where authorized != obligated          11 of 18   -> unexpended mutation is real
    rows inside vs outside a 2-period window     6 of 18   -> window mutation is real
    lines where authorized < obligated           0 of 18   -> the FLOOR never engages
    natural row order already equals sorted      yes       -> the SORT never reorders

── THE THREE THAT ARE REAL ──────────────────────────────────────────────────────────────────
**`at_risk` is authorised money not yet SPENT; `shortfall` is authorised money not yet
COMMITTED.** They answer different questions — one is exposure, the other is a funding gap —
and measuring `at_risk` against `obligated` silently collapses them into the same number.

**`unexpended_balance` is obligated minus expended**: money committed but not yet paid out.
From `authorized` it becomes a different quantity entirely — committed-and-uncommitted money
added together — under a name that says otherwise.

**The window filter dropped returns every period**, so a question about one quarter answers
with the programme's whole funding history. Three times the rows, all of them plausible.

── THE THREE THAT ARE EQUIVALENT, RECORDED RATHER THAN FORCED ───────────────────────────────
The `max(0.0, ...)` floor on `shortfall` never engages here: **no line in this seed is
over-obligated**, so `max(0, x)` and `x` agree on all 18 rows, and the `gap`/`shortfall` split —
`gap` signed, `shortfall` floored — cannot be told apart either.

The sort never reorders: **the seed is already in `(subject_id, period)` order.**

**Contriving a seed to make these bite would be testing the fixture.** The extraction is what
makes them testable — a module taking funding quantities directly can be handed an
over-obligated line and an out-of-order series in three lines each, exactly as
`burn_series` could be handed a partly-zero period. *A rule becomes checkable by being lifted.*
**Pinning all three is owed by the commit that lifts this verb.**

TEST-ONLY. The verb is correct; what was missing is any assertion that it is.
"""
from __future__ import annotations

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.entities import PERIOD_ORDER, periods_in
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PROGRAM = "NP-MERIDIAN"


@pytest.fixture(scope="module")
def rows():
    out = m.fin_funding_status(STATE, program_id=PROGRAM)
    assert out, "no rows; every seal here would pass vacuously"
    return out


def test_at_risk_is_authorised_money_NOT_YET_SPENT(rows):
    """Exposure, not a funding gap.

    `at_risk` measures against EXPENDED; `shortfall` measures against OBLIGATED. Collapsing
    them gives one number for two questions, and the number that survives is the smaller and
    more comfortable of the two.
    """
    for row in rows:
        assert row["at_risk"] == pytest.approx(
            max(0.0, row["authorized"] - row["expended"])
        ), f"{row['subject_id']}/{row['period']}: at_risk is not measured against expended"


def test_at_risk_and_shortfall_ACTUALLY_DIFFER_so_collapsing_them_is_detectable(rows):
    """THE CONTROL. Where obligated equals expended the two are identical and the mutation is
    an equivalent one — measured: they differ on 17 of 18 rows here."""
    differing = [r for r in rows if r["at_risk"] != r["shortfall"]]
    assert len(differing) >= 10, (
        f"at_risk and shortfall differ on only {len(differing)} rows; this seed barely "
        f"exercises the distinction and the seal above is close to vacuous"
    )


def test_unexpended_balance_is_COMMITTED_money_not_yet_paid_out(rows):
    """`obligated - expended`. From `authorized` it silently becomes committed and uncommitted
    money added together, under a name that says otherwise."""
    for row in rows:
        assert row["unexpended_balance"] == pytest.approx(
            row["obligated"] - row["expended"]
        )


def test_unobligated_balance_is_AUTHORISED_money_not_yet_committed(rows):
    """The other balance, and its partner above is the reason both are asserted: the two are
    one subtraction apart and swapping their operands is invisible in the field name."""
    for row in rows:
        assert row["unobligated_balance"] == pytest.approx(
            row["authorized"] - row["obligated"]
        )


def test_the_two_balances_DIFFER_so_a_swap_is_detectable(rows):
    """THE CONTROL for the pair above."""
    assert any(r["unobligated_balance"] != r["unexpended_balance"] for r in rows), (
        "the two balances agree on every row, so swapping their operands would be undetectable"
    )


def test_the_window_ACTUALLY_NARROWS_the_grid():
    """A dropped window filter answers a question about one quarter with the whole funding
    history — three times the rows here, all of them plausible."""
    everything = m.fin_funding_status(STATE, program_id=PROGRAM)
    narrowed = m.fin_funding_status(
        STATE, program_id=PROGRAM, window=periods_in(None)[:2]
    )
    assert narrowed, "the narrowed window returned nothing; the seal cannot discriminate"
    assert len(narrowed) < len(everything), (
        f"a 2-period window returned {len(narrowed)} of {len(everything)} rows — the filter "
        f"is not narrowing and a dropped filter would be undetectable"
    )
    asked = set(periods_in(None)[:2])
    assert all(r["period"] in asked for r in narrowed)


def test_the_verdict_and_its_IPMDAR_name_agree_on_every_row(rows):
    """Two vocabularies for one fact. A row whose `state` and `funding_state` disagree is the
    response contradicting itself, and each is what a different reader looks at."""
    expected = {"short": "unobligated-balance",
                "pledged-not-firm": "obligated-not-expended",
                "met": "expended"}
    for row in rows:
        assert row["funding_state"] == expected[row["state"]]


def test_the_grid_is_ordered_by_subject_then_period(rows):
    """⚠ THIS CANNOT TELL A SORT FROM NO SORT, AND SAYING SO IS THE POINT.

    The seed is already in `(subject_id, period)` order, so removing the sort entirely leaves
    every row where it was — measured, and an equivalent mutant rather than a finding.

    It is asserted anyway because the ORDER IS A CONTRACT a grid renderer relies on; what is
    missing is a fixture that could detect its absence. The extraction supplies that: a module
    taking funding rows directly can be handed them out of order in one line, which is where
    this belongs.
    """
    ordered = sorted(rows, key=lambda r: (r["subject_id"], PERIOD_ORDER[r["period"]]))
    assert rows == ordered
