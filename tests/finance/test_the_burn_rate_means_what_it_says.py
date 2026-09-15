"""`fin_burn_rate` had NO effective coverage of its algorithm. Six mutations, six survivors.

R-029 requires the mutate-the-unit check before an ADR-0053 §7 extraction. Run against
`fin_burn_rate` on 2026-09-14 — standing seal `803071e`, dated 2026-09-02, **twelve days old**:

    trailing window 3 -> 1 (no smoothing at all)          ->  0 red   ⚠
    trailing window 3 -> every period                     ->  0 red   ⚠
    runway over CUMULATIVE burn instead of trailing rate  ->  0 red   ⚠
    variance_to_plan SIGN FLIPPED                         ->  0 red   ⚠
    budget_remaining IGNORES SPEND                        ->  0 red   ⚠
    skip rule: `and` -> `or`                              ->  0 red   (equivalent — see below)

**FIVE of the six change real values in this seed**, checked before claiming — a survivor on
data that cannot discriminate is an equivalent mutant and not a finding. The sixth, the skip
rule, genuinely is one: `and` and `or` differ only on a period where exactly one of plan and
spend is zero, and this seed has **none** (6 both-zero, 6 neither, 0 partly). It is recorded
rather than forced, and the extraction is what will make it testable.

    variance_to_plan changes sign at FY26-03   +145,000 -> -255,000
    budget_remaining falls                  10,995,000 -> 4,570,000
    trailing_rate differs from burn          1,088,333 vs 1,255,000
    runway falls                                 10.94 -> 3.29

**The two that matter most are the sign and the remaining budget.** A flipped
`variance_to_plan` turns a program running over plan into one running under it — the single
fact a reader acts on. A `budget_remaining` that ignores spend reports the full BAC forever,
and the runway computed from it inherits the error, so a program three periods from exhausting
its budget reads as comfortable.

**TEST-ONLY. The verb is correct.** What was missing is any assertion that it is. The extraction
follows as its own move — a correctness gap found during a refactor must not ride in the
refactor's commit.

── HOW THESE AVOID RESTATING THE IMPLEMENTATION ─────────────────────────────────────────────
Each row publishes the quantities its derived figures came from (`burn`, `planned`,
`trailing_periods`), so the checks recompute from the ROW's own outputs. A response whose
variance disagrees with the two amounts printed beside it contradicts itself, and that is
checkable without a second copy of the verb.
"""
from __future__ import annotations

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PROGRAM = "NP-MERIDIAN"


@pytest.fixture(scope="module")
def rows():
    out = m.fin_burn_rate(STATE, program_id=PROGRAM)
    assert out, "no rows; every seal here would pass vacuously"
    return out


def test_variance_to_plan_is_PLANNED_MINUS_BURN_and_its_sign_means_under_plan(rows):
    """The sign is the finding. Positive means spending BELOW plan.

    Recomputed from the two amounts the row publishes, so this cannot pass by restating the
    expression — it asserts the response is internally consistent.
    """
    for row in rows:
        assert row["variance_to_plan"] == pytest.approx(row["planned"] - row["burn"]), (
            f"{row['period']}: variance_to_plan is not planned - burn"
        )


def test_the_sign_ACTUALLY_VARIES_so_a_flip_is_detectable(rows):
    """THE CONTROL. On a seed that never crosses plan, flipping the sign is an equivalent
    mutant and the assertion above is green while proving nothing."""
    signs = {row["variance_to_plan"] > 0 for row in rows}
    assert signs == {True, False}, (
        "variance_to_plan never changes sign in this seed, so a flipped convention would be "
        "undetectable — the seed no longer exercises the distinction"
    )


def test_budget_remaining_is_BAC_less_CUMULATIVE_burn(rows):
    """A remaining budget that ignores spend reports the full BAC forever, and every forecast
    built on it inherits the error."""
    program = m._require_program(STATE, PROGRAM)
    for row in rows:
        assert row["budget_remaining"] == pytest.approx(program.bac - row["cum_burn"])


def test_budget_remaining_ACTUALLY_DECREASES_so_ignoring_spend_is_detectable(rows):
    """The control for the seal above. If nothing was ever spent, `bac - cum` equals `bac` and
    the mutation is invisible."""
    assert rows[0]["budget_remaining"] > rows[-1]["budget_remaining"], (
        "budget_remaining never decreases; a verb ignoring spend would be undetectable"
    )


def test_the_trailing_rate_is_the_mean_of_the_LAST_THREE_burns_at_most(rows):
    """Three is DECLARED rather than tuned — short enough to follow a turn, long enough not to
    chase one month — and the window length rides on the row so the figure can be argued with.

    Checked against the burns the response itself published, and against the row's own
    `trailing_periods`, so a changed window is caught by the figure AND by its own label.
    """
    burns = [row["burn"] for row in rows]
    for i, row in enumerate(rows):
        window = burns[max(0, i - 2): i + 1]
        assert row["trailing_periods"] == len(window), (
            f"{row['period']}: trailing_periods says {row['trailing_periods']}, window is "
            f"{len(window)}"
        )
        assert row["trailing_rate"] == pytest.approx(sum(window) / len(window))


def test_the_smoothing_IS_ACTIVE_so_widening_or_narrowing_it_is_detectable(rows):
    """The control. On a flat burn series every window length gives the same mean and all
    three window mutations become equivalent."""
    assert any(abs(r["trailing_rate"] - r["burn"]) > 1 for r in rows), (
        "trailing_rate equals burn everywhere; the window length is doing nothing in this "
        "seed and the smoothing mutations would be undetectable"
    )
    assert max(r["trailing_periods"] for r in rows) == 3, (
        "the window never fills, so narrowing it to 1 would be undetectable"
    )


def test_the_runway_is_over_the_TRAILING_RATE_and_not_the_cumulative_burn(rows):
    """A different denominator is a different forecast wearing the same name.

    PERIODS, NOT A DATE — converting would need a period-to-date map this model does not hold,
    and inventing one is how a forecast acquires a precision its inputs never had.
    """
    for row in rows:
        if row["runway_periods"] is None:
            continue
        assert row["runway_periods"] == pytest.approx(
            row["budget_remaining"] / row["trailing_rate"]
        )

    # THE CONTROL IS "DIFFER SOMEWHERE", NOT "DIFFER EVERYWHERE", and the first row is why.
    # With one period of history the cumulative burn IS the trailing rate, so requiring them to
    # disagree on every row fails against correct code — which is how this seal failed first.
    # The property that makes the mutation detectable is that they diverge at all.
    diverged = [r["period"] for r in rows
                if r["runway_periods"] is not None
                and r["runway_periods"] != pytest.approx(r["budget_remaining"] / r["cum_burn"])]
    assert diverged, (
        "the trailing rate and the cumulative burn agree in every row, so computing the "
        "runway over either would be undetectable and the assertion above cannot discriminate"
    )


def test_a_period_with_NEITHER_plan_NOR_spend_is_absent(rows):
    """The skip is for a period with nothing happening at all.

    ⚠ THIS SEAL CANNOT TELL `and` FROM `or`, AND SAYING SO IS THE POINT. The two differ only on
    a period where exactly one of plan and spend is zero, and **this seed has none** —
    measured: 6 periods with both zero, 6 with neither, 0 partly zero. So the `and` -> `or`
    mutation is an EQUIVALENT MUTANT here, and it is the one survivor of six that is not a
    finding.

    Contriving a seed to make it bite would be testing the fixture. The honest route is the
    extraction: once the skip rule lives in a module that takes quantities directly, a
    partly-zero period is three lines to construct — `index_series` already pins exactly that
    case, and it could only do so BECAUSE it was extracted. **The rule becomes testable by
    being lifted**, which is an argument for the move beyond tidiness, and pinning it there is
    owed by the commit that lifts it.
    """
    from agent_fleet.finance_agent.entities import periods_in

    assert len(rows) <= len(periods_in(None))
    for row in rows:
        assert not (row["planned"] == 0 and row["burn"] == 0)


def test_the_runway_is_NONE_where_the_rate_is_zero_rather_than_infinite(rows):
    """A program burning nothing has no runway in periods — the figure is undefined, not
    unlimited, and "unlimited" is an assertion about solvency nobody made."""
    for row in rows:
        if row["trailing_rate"] == 0:
            assert row["runway_periods"] is None
