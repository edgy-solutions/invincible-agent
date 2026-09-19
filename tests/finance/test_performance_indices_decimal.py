"""ADR-0053 §7 step 2 for `fin_performance_indices` — and it scoped itself.

Step 1 (`799b4bc`) extracted the series construction. This changes the arithmetic, alone, as §7
requires: both at once means a green covers only the conjunction and a red is unattributable
between the refactor and the money.

── WHY THIS VERB IS IN SCOPE BY THE RULING'S OWN TEST, NOT BY ANALOGY ───────────────────────
It produces `cost_variance` (BCWP − ACWP) and `schedule_variance` (BCWP − BCWS). **Two
subtractions, and the FINDING is the difference rather than either operand** — which is exactly
the *"producers and any consumer that subtracts or compares"* clause. The four indices are
divisions over the same quantities and come back exact for free.

── WHAT MOVED: NOTHING. TWELVE FIELDS WERE ADDED. ───────────────────────────────────────────
Same instrument as every extraction here — the pre-pass verb from `git show HEAD:...` beside
the new one, over the full matrix (program level, every control account, four window shapes):

    fields unchanged : 750
    values moved     : 0
    fields ADDED     : 12 `_exact` columns

**AND THE SHARED HELPER WAS PROVEN NOT TO DISTURB ITS OTHER CALLER.** `_emit_money` was
generalized from one hardcoded field list to a parameter, which touches `fin_variance_drivers`.
Re-running THAT verb's equivalence harness: 654 fields unchanged, 0 moved, the same six columns
as before. A shared-helper change inside a single verb's move is only safe if the other callers
are measured, not reasoned about.

── THE HONEST LIMIT ─────────────────────────────────────────────────────────────────────────
On this seed the Decimal path is **unfalsifiable by value** — every figure agrees to the cent,
so reverting the arithmetic to float would survive these seals. The machinery is exact, the
ruling scopes the verb regardless, and a seed landing near a half-cent boundary would diverge.
Exactness is asserted where it CAN be: that the exact column exists, agrees, and is what the
derived figures are computed from.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PROGRAM = "NP-MERIDIAN"


@pytest.fixture(scope="module")
def rows():
    out = m.fin_performance_indices(STATE, program_id=PROGRAM)
    assert out, "no rows; every seal here would pass vacuously"
    return out


def test_every_money_field_carries_an_exact_string_that_AGREES_with_its_float(rows):
    """The producer's authoritative figure is Decimal; the renderer takes the float at the
    edge. A pair that disagrees is worse than no pair — a consumer reading the exact column
    would silently get a different number from the one on the card."""
    for row in rows:
        for key in m._INDEX_MONEY_FIELDS:
            assert f"{key}_exact" in row, f"{key} has no exact column"
            assert Decimal(row[f"{key}_exact"]) == Decimal(str(row[key])), (
                f"{row['period']}.{key}: float {row[key]!r} disagrees with exact"
            )


def test_the_INDICES_carry_an_exact_ratio_and_the_float_is_its_faithful_float(rows):
    """A ratio is NOT quantized, so the money check does not transfer — 28 significant digits
    against the float's ~17, and `Decimal(exact) == Decimal(str(float))` can never hold.

    I got this wrong the first time on `fin_variance_drivers`' share, by copying the money
    assertion across on the assumption that two fields in one row are the same kind. **The
    true property is narrower: the published float is a lossy VIEW of the authority**, not a
    second computation of it.
    """
    checked = 0
    for row in rows:
        for key in ("cpi", "spi", "cum_cpi", "cum_spi"):
            if row[key] is None:
                continue
            checked += 1
            assert float(Decimal(row[f"{key}_exact"])) == row[key], (
                f"{row['period']}.{key} is not the float of its exact figure"
            )
    assert checked, "no indices checked; this seal would pass vacuously"


def test_the_VARIANCES_are_the_exact_subtraction_of_the_exact_operands(rows):
    """THE REASON THIS VERB IS IN SCOPE. Recomputed from the row's own exact columns, so the
    check cannot pass by restating the implementation — a response whose variance disagrees
    with the quantities printed beside it contradicts itself."""
    for row in rows:
        bcws, bcwp = Decimal(row["bcws_exact"]), Decimal(row["bcwp_exact"])
        acwp = Decimal(row["acwp_exact"])
        assert Decimal(row["cost_variance_exact"]) == m._money(bcwp - acwp)
        assert Decimal(row["schedule_variance_exact"]) == m._money(bcwp - bcws)


def test_the_indices_are_taken_over_the_EXACT_quantities_beside_them(rows):
    """CPI = BCWP/ACWP and SPI = BCWP/BCWS, in Decimal, against the row's own exact columns.

    The swapped-index mutation that survived twelve days is caught in three places now; this
    is the one that catches it AFTER the Decimal pass, where a float-edge assertion would
    have started rounding past the difference.
    """
    for row in rows:
        if row["cpi"] is not None:
            assert Decimal(row["cpi_exact"]) == (
                Decimal(row["bcwp_exact"]) / Decimal(row["acwp_exact"])
            )
        if row["spi"] is not None:
            assert Decimal(row["spi_exact"]) == (
                Decimal(row["bcwp_exact"]) / Decimal(row["bcws_exact"])
            )


def test_the_running_totals_accumulate_IN_DECIMAL_without_a_float_seed(rows):
    """The module's accumulator seeds at int 0, not 0.0.

    `0.0 + Decimal(...)` is a TypeError, so a float seed silently pins the module to float
    inputs — ONE LINE that would have made it un-liftable while looking like a formatting
    choice. This is the seal that would fail if someone 'tidied' it back.
    """
    running = Decimal("0")
    for row in rows:
        running += Decimal(row["bcwp_exact"])
        assert Decimal(row["cum_bcwp_exact"]) == m._money(running)


def test_an_undefined_index_is_NONE_and_carries_no_exact_column_either(rows):
    """None, not 1.0 and not 0.0 — and absence rather than an exact string saying "none".

    A row carrying `cpi: null` beside `cpi_exact: "0"` would let two consumers disagree about
    whether the index existed, which is the same two-readings defect the None rule exists to
    prevent.
    """
    for row in rows:
        for key in ("cpi", "spi", "cum_cpi", "cum_spi"):
            if row[key] is None:
                assert f"{key}_exact" not in row, (
                    f"{row['period']}.{key} is undefined but publishes an exact column"
                )
