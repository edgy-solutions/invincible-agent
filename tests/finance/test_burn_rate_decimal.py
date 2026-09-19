"""ADR-0053 §7 step 2 for `fin_burn_rate` — and unlike the first two, values MOVED.

Step 1 (`4ac692e`) extracted the series. This changes the arithmetic, alone.

── IN SCOPE BY THE RULING'S OWN TEST ────────────────────────────────────────────────────────
The verb produces `variance_to_plan` (planned − burn) and `budget_remaining` (BAC − cumulative
burn). **Two subtractions**, and the money ruling names *"producers and any consumer that
subtracts or compares"*.

── WHAT MOVED, EACH NAMED, AS §7 REQUIRES ───────────────────────────────────────────────────
The first two passes moved nothing. This one moved two fields and neither is a correctness
change:

    trailing_rate    10 row-instances   max delta 0.0033      QUANTIZED to the cent
    runway_periods    5 row-instances   max delta 8.9e-16     one ULP, and MORE accurate

`trailing_rate` is a mean of three burns and lands on a repeating decimal —
`1,338,333.3333…` becomes `1,338,333.33`. **It is money — an amount per period, not a ratio —
so it quantizes with the rest.** A row carrying more precision than the figure it is summarised
against is the card disagreeing with its own caption.

`runway_periods` shifted by **one unit in the last place**, because dividing exact Decimals and
converting once is nearer the true value than dividing two floats. **The exact path is not
merely different, it is better**, and a seal that demanded byte-equality here would be pinning
the float path's error.

── THE BAC IS CONVERTED TOO, AND I OVERSTATED WHY ───────────────────────────────────────────
I first wrote that it removes a mixed-type subtraction. **It does not.** `int - Decimal` is
exact and lossless, so with today's integer BAC the conversion is a **no-op** — the mutation
removing it survives the whole suite, and **that survivor proved the claim wrong rather than
the code.**

What it actually guards is a **float** BAC, which raises `TypeError` on the first subtraction.
Real and cheap, just not what I said. `test_the_BAC_conversion_guards_a_FLOAT_bac_and_not_an_int_one`
exercises that case, because **a guard whose only evidence is an integer fixture is a guard
nobody has tested** — and the honest repair for an equivalent mutant is often a narrower claim
plus the test that makes the remaining claim real.

── THE OTHER TWO CALLERS OF THE SHARED HELPER WERE RE-MEASURED ──────────────────────────────
`_emit_money` now serves three verbs. After this change: **drivers 654 shared keys, 0 moved;
indices 750 shared keys, 0 moved, no field removed.** A shared-helper change is only safe if
the other callers are measured rather than reasoned about.
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
    out = m.fin_burn_rate(STATE, program_id=PROGRAM)
    assert out, "no rows; every seal here would pass vacuously"
    return out


def test_the_BAC_is_exact_or_converting_it_is_dishonest():
    """Converting an operand at a verb boundary is only honest while it is exactly
    representable. If this ever fails the fix is Decimal in the SEED, not more conversion."""
    for program in STATE.programs:
        assert Decimal(program.bac) == Decimal(str(program.bac)), program.program_id


def test_every_money_field_carries_an_exact_string_that_AGREES_with_its_float(rows):
    for row in rows:
        for key in m._BURN_MONEY_FIELDS:
            assert f"{key}_exact" in row, f"{key} has no exact column"
            assert Decimal(row[f"{key}_exact"]) == Decimal(str(row[key])), (
                f"{row['period']}.{key}: float {row[key]!r} disagrees with exact"
            )


def test_the_two_SUBTRACTIONS_are_exact_over_the_exact_operands(rows):
    """THE REASON THIS VERB IS IN SCOPE. Recomputed from the row's own exact columns, so the
    check cannot pass by restating the expression."""
    program = m._require_program(STATE, PROGRAM)
    bac = Decimal(str(program.bac))
    for row in rows:
        planned, burn = Decimal(row["planned_exact"]), Decimal(row["burn_exact"])
        assert Decimal(row["variance_to_plan_exact"]) == m._money(planned - burn)
        assert Decimal(row["budget_remaining_exact"]) == m._money(
            bac - Decimal(row["cum_burn_exact"])
        )


def test_trailing_rate_is_MONEY_and_quantizes_to_the_cent(rows):
    """An amount per period, not a ratio. This is the field that MOVED — a repeating mean
    presented to the cent — and it moved deliberately."""
    for row in rows:
        exact = Decimal(row["trailing_rate_exact"])
        assert exact == exact.quantize(Decimal("0.01")), (
            f"{row['period']}: trailing_rate carries sub-cent precision"
        )


def test_runway_periods_is_a_COUNT_and_is_NOT_quantized(rows):
    """A duration, not an amount. Rounding a forecast horizon to the cent would be putting a
    currency on a number of periods.

    THE FLOAT IS THE FAITHFUL FLOAT OF THE EXACT, which is the narrower property a ratio has —
    not the money round-trip, which only holds because money is quantized.
    """
    checked = 0
    for row in rows:
        if row["runway_periods"] is None:
            continue
        checked += 1
        assert float(Decimal(row["runway_periods_exact"])) == row["runway_periods"]
    assert checked, "no runways checked; this seal would pass vacuously"
    assert any(Decimal(r["runway_periods_exact"]) !=
               Decimal(r["runway_periods_exact"]).quantize(Decimal("0.01"))
               for r in rows if r["runway_periods"] is not None), (
        "every runway happens to land on a cent, so quantizing it would be undetectable"
    )


def test_the_runway_is_computed_from_the_UNQUANTIZED_rate(rows):
    """ORDER MATTERS: compute exact, present rounded.

    The module divides by the full-precision mean and `_emit_money` rounds afterwards. Dividing
    by the already-rounded rate would fold a presentation decision into a forecast — and on
    `trailing_rate` that rounding is 0.0033, which is exactly the kind of small, plausible,
    untraceable drift a reader cannot audit.
    """
    program = m._require_program(STATE, PROGRAM)
    bac = Decimal(str(program.bac))
    burns: list[Decimal] = []
    for row in rows:
        burns.append(Decimal(row["burn_exact"]))
        window = burns[-3:]
        unrounded = sum(window) / len(window)
        remaining = bac - Decimal(row["cum_burn_exact"])
        if row["runway_periods"] is None:
            continue
        assert Decimal(row["runway_periods_exact"]) == remaining / unrounded, (
            f"{row['period']}: the runway was computed from a rounded rate"
        )


def test_the_accumulators_stayed_DECIMAL_through_the_whole_series(rows):
    """A float seed would have raised on the first add; a float creeping in later would
    silently reintroduce binary error part-way down the series."""
    running = Decimal("0")
    for row in rows:
        running += Decimal(row["burn_exact"])
        assert Decimal(row["cum_burn_exact"]) == m._money(running)


def test_the_BAC_conversion_guards_a_FLOAT_bac_and_not_an_int_one():
    """⚠ THE MUTATION THAT SURVIVED, AND WHY IT IS HONEST.

    Removing `Decimal(str(program.bac))` reds nothing: `int - Decimal` is exact and lossless,
    so with today's integer BAC the conversion is a no-op. **My first comment claimed it
    removed a mixed-type subtraction — it does not, and the survivor proved the claim rather
    than the code was wrong.**

    What the conversion actually guards is a FLOAT bac, which raises on the first subtraction.
    That is real and cheap, and this is the case that exercises it — a guard whose only
    evidence is an integer fixture is a guard nobody has tested.
    """
    from agent_fleet.finance_agent.measure_modules import burn_series

    quantities = [("P0", Decimal("100"), Decimal("60"))]

    # The guarded form: a float BAC, converted the way the verb converts it.
    rows = burn_series.build(quantities,
                             budget_at_completion=Decimal(str(12_000_000.0)),
                             scope_label="s")
    assert rows[0]["budget_remaining"] == Decimal("11999940")

    # The unguarded form is the failure being prevented, asserted rather than described.
    with pytest.raises(TypeError):
        burn_series.build(quantities, budget_at_completion=12_000_000.0, scope_label="s")
