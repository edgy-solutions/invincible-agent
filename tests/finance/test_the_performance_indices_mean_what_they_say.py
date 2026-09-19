"""CPI and SPI could be SWAPPED and nothing in this suite would notice. Found by R-029's check.

R-029 requires, before an ADR-0053 §7 extraction, that you **mutate the unit and see what the
standing seal actually asserts about it** — rather than inheriting §7's claim that a
battle-tested seal covers it. Run against `fin_performance_indices` on 2026-09-14, seal
`803071e` dated 2026-09-02:

    emit deliberate-absent periods instead of skipping  ->  1 red   ✅
    cumulative CPI computed from the PERIOD figures     ->  0 red   ⚠ SURVIVED
    SWAP cpi AND spi                                    ->  0 red   ⚠ SURVIVED

**Both survivors change real values in this seed**, so neither is an equivalent mutant: CPI and
SPI differ in all six rows (0.995 against 0.8696 in the first), and the cumulative diverges
from the period figure from the third row on (0.8367 against 0.9342).

**So two of the four ratios this verb exists to produce could be silently wrong.** A reader
acting on "CPI 0.84" would be acting on schedule performance, and the two say opposite things
about what to do: a cost index says the work costs more than it earns, a schedule index says
less work was claimed than planned.

THIS IS A TEST-ONLY COMMIT. The verb is correct — CPI is BCWP/ACWP and SPI is BCWP/BCWS, both
as written. What was missing is any assertion that they are. The extraction follows separately,
which is ADR-0053 §7's whole discipline.

── HOW THESE AVOID RESTATING THE IMPLEMENTATION ─────────────────────────────────────────────
Each row carries the raw quantities its ratios were computed from (`bcws`/`bcwp`/`acwp` and the
cumulative three). So the check recomputes from the ROW's own published inputs rather than
re-deriving them from state — if the ratios and the quantities beside them disagree, the
response contradicts itself, which is checkable without a second implementation of the verb.
"""
from __future__ import annotations

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PROGRAM = "NP-MERIDIAN"


@pytest.fixture(scope="module")
def rows():
    out = m.fin_performance_indices(STATE, program_id=PROGRAM)
    assert out, "no rows; every seal in this file would pass vacuously"
    return out


def test_CPI_is_cost_and_SPI_is_schedule_and_they_are_NOT_interchangeable(rows):
    """The mutation that survived. CPI = BCWP/ACWP, SPI = BCWP/BCWS.

    Recomputed from the quantities the row itself publishes, so this cannot pass by restating
    the implementation — it asserts the response is internally consistent.
    """
    for row in rows:
        assert row["cpi"] == pytest.approx(row["bcwp"] / row["acwp"]), (
            f"{row['period']}: cpi is not BCWP/ACWP — a cost index reading a schedule quantity"
        )
        assert row["spi"] == pytest.approx(row["bcwp"] / row["bcws"]), (
            f"{row['period']}: spi is not BCWP/BCWS"
        )


def test_the_two_indices_ACTUALLY_DIFFER_so_the_check_above_can_discriminate(rows):
    """THE CONTROL. Without it, a seed where CPI equals SPI would make the swap an equivalent
    mutant and the assertion above would be green while proving nothing.

    Measured: they differ in every row of this seed. If a future seed makes them equal, this
    fails and says so, rather than letting the pair above quietly stop discriminating.
    """
    differing = [r["period"] for r in rows if r["cpi"] != r["spi"]]
    assert len(differing) == len(rows), (
        f"cpi equals spi in {len(rows) - len(differing)} row(s); the swap mutation would be "
        f"undetectable there and the seed no longer exercises the distinction"
    )


def test_the_CUMULATIVE_indices_accumulate_and_are_not_the_period_ones(rows):
    """The other survivor: `cum_cpi` computed from the period figures instead of the running
    totals. Undetectable while the two agree, which they do until the third row."""
    for row in rows:
        assert row["cum_cpi"] == pytest.approx(row["cum_bcwp"] / row["cum_acwp"])
        assert row["cum_spi"] == pytest.approx(row["cum_bcwp"] / row["cum_bcws"])

    diverged = [r["period"] for r in rows
                if r["cpi"] != pytest.approx(r["cum_cpi"])]
    assert diverged, (
        "the cumulative index never differs from the period index in this seed, so computing "
        "one from the other would be undetectable — the assertions above cannot discriminate"
    )


def test_the_running_totals_are_the_RUNNING_SUM_of_the_period_quantities(rows):
    """The accumulator itself, independently of the ratios built on it. A cumulative that
    resets, double-counts, or tracks only the last period is invisible in a ratio that happens
    to look plausible."""
    for field, cum_field in (("bcws", "cum_bcws"), ("bcwp", "cum_bcwp"), ("acwp", "cum_acwp")):
        running = 0.0
        for row in rows:
            running += row[field]
            assert row[cum_field] == pytest.approx(running), (
                f"{row['period']}: {cum_field} is not the running sum of {field}"
            )


def test_a_period_with_nothing_reported_is_ABSENT_and_not_a_row_of_zeroes(rows):
    """The one rule the standing seal already held, kept here beside the others.

    A period with nothing reported is not a period of zero performance; emitting a row draws a
    point on the trend asserting the program stopped, which the data does not claim.
    """
    from agent_fleet.finance_agent.entities import periods_in

    assert len(rows) < len(periods_in(None)), (
        "every period produced a row, so this seed no longer contains an unreported period "
        "and the skip rule is not being exercised"
    )
    for row in rows:
        assert not (row["bcws"] == 0 and row["bcwp"] == 0 and row["acwp"] == 0)


def test_an_undefined_ratio_is_NONE_and_never_a_number(rows):
    """None, not 1.0 and not 0.0. A period in which nothing was spent has no cost performance
    index — the ratio is undefined, not perfect and not catastrophic, and both substitutes are
    assertions about performance that nobody made."""
    for row in rows:
        for key, denominator in (("cpi", "acwp"), ("spi", "bcws"),
                                 ("cum_cpi", "cum_acwp"), ("cum_spi", "cum_bcws")):
            if row[denominator] == 0:
                assert row[key] is None, f"{row['period']}.{key} is a number over a zero"
