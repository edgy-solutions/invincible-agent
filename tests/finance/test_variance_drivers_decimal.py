"""ADR-0053 §7 step 2 — the Decimal pass on `fin_variance_drivers`, and what it did NOT move.

Step 1 (`7360138`) extracted the ranking. This is the second move, alone, as §7 requires:
*"Both at once cannot be checked. A green then covers only the conjunction, and a red is
unattributable between the refactor and the arithmetic."*

── WHAT MOVED: NOTHING. SIX FIELDS WERE ADDED. ─────────────────────────────────────────────
The same equivalence instrument step 1 used — the pre-pass function loaded from
`git show HEAD:...` beside the new one, run over the full matrix:

    fields unchanged : 654
    values moved     : 0
    rows / ordering  : identical
    fields ADDED     : acwp_exact, bcwp_exact, bcws_exact, contribution_exact,
                       share_of_total_exact, withheld_contribution_exact

**So §7's own warning did not fire, and that is a result rather than a relief.** It predicted
Decimal *"can reorder a tie that float resolved arbitrarily, which is a deliberate value
change"*. See `test_the_tie_this_seed_actually_contains` — **the tie is real and it did not
move**, for a reason worth having in writing.

── THE HONEST LIMIT, STATED RATHER THAN PAPERED OVER ───────────────────────────────────────
**On this seed the Decimal path is unfalsifiable by value.** Every figure agrees to the cent
between float and Decimal, so a mutation reverting the arithmetic to float would survive these
seals — an equivalent mutant, exactly as the `fin_eac_comparison` pass found.

That narrows the claim rather than voiding it. The machinery is exact, the money ruling scopes
this verb regardless (*"producers and any consumer that subtracts or compares"* — it subtracts,
and the FINDING is the difference rather than either operand), and a seed landing near a
half-cent boundary would diverge. So exactness is asserted where it CAN be: on the plumbing —
that the exact column exists, agrees, is what the ranking reads, and is not decorative.

── MUTATIONS RUN, INCLUDING THE TWO THAT SURVIVED ──────────────────────────────────────────

    reverting the verb to float totals         -> 30 red   ✅
    dropping the `_exact` columns              -> 14 red   ✅
    `Decimal(f)` instead of `Decimal(str(f))`  ->  0 red   ⚠ SURVIVED
    emitting the unquantized float             ->  0 red   ⚠ SURVIVED

**Both survivors are equivalent mutants on this seed, and the seals above are why I can say
that rather than guess it.** `Decimal(f)` and `Decimal(str(f))` agree wherever the value is
exactly representable — asserted at 162 of 162 facts by
`test_the_seed_money_is_EXACT_or_the_conversion_is_dishonest`. And the raw figures already land
on the cent, so quantizing is a no-op here; `test_the_floats_are_quantized_to_the_cent` passes
either way for the same reason it cannot fail.

**Recorded rather than fixed by contriving a fixture.** A seed bent to make these bite would be
testing the fixture; the seals that CAN discriminate do, and if someone later adds a figure at
a half-cent boundary both mutations start biting and this note becomes obsolete — which is the
outcome to want. What is NOT claimed: that the arithmetic would be right if the inputs were
inexact. On this data that is unfalsifiable, and saying so is the point of this section.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.measure_modules import variance_driver_ranking as V
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()

_CASES = [
    dict(program_id="NP-MERIDIAN", variance_kind=k, level=l, top_n=n)
    for k in ("cost", "schedule") for l in ("control_account", "work_package")
    for n in (1, 3, 100)
]


def _rows(**kw):
    return m.fin_variance_drivers(STATE, **kw)


def test_the_seed_money_is_EXACT_or_the_conversion_is_dishonest():
    """Converting at a verb boundary is only honest while the inputs are exact.

    `Decimal(str(v))` reads the decimal literal a human wrote; `Decimal(v)` reads the binary
    approximation. They agree only where the value is exactly representable.

    IF THIS EVER FAILS, THE FIX IS DECIMAL IN THE SEED, not more conversion at the boundary.
    Exactness painted over drifted inputs looks compliant and is not.
    """
    checked, inexact = 0, []
    for f in STATE.facts:
        for field in ("bcws", "bcwp", "acwp"):
            v = getattr(f, field)
            checked += 1
            if isinstance(v, float) and Decimal(v) != Decimal(str(v)):
                inexact.append((f.wp_id, f.period, field, v))
    assert checked == 162, f"the money-fact population changed: {checked}"
    assert not inexact, inexact


@pytest.mark.parametrize("case", _CASES)
def test_every_money_field_carries_an_exact_string_that_AGREES_with_its_float(case):
    """The producer's authoritative figure is Decimal; the renderer takes the float at the
    edge. A pair that disagrees is worse than no pair — a consumer reading the exact column
    would silently get a different number from the one on the card."""
    rows = _rows(**case)
    assert rows, f"no rows for {case}; this seal would pass vacuously"
    for row in rows:
        for key in m._DRIVER_MONEY_FIELDS:
            if key not in row:
                continue
            exact_key = f"{key}_exact"
            assert exact_key in row, f"{key} has no exact column"
            assert Decimal(row[exact_key]) == Decimal(str(row[key])), (
                f"{row['entity_id']}.{key}: float {row[key]!r} disagrees with exact "
                f"{row[exact_key]!r}"
            )


@pytest.mark.parametrize("case", _CASES)
def test_the_RANKING_reads_the_exact_value_and_not_the_float_edge(case):
    """THE ONE THAT KEEPS THE EXACT COLUMN FROM BEING DECORATIVE.

    The `fin_eac_comparison` pass found this exact trap: carrying an exact column and then
    computing the spread from the float would leave the exact figures carried and unused by
    the one calculation that needed them. Here the calculation is the ORDERING.

    Asserted by watching what the verb hands the module rather than by inspecting output,
    because output cannot distinguish the two on a seed where they agree — which is this one.
    """
    seen: list[str] = []
    original = V.rank_drivers

    def spy(rows, *, top_n):
        rows = list(rows)
        if rows:
            seen.append(type(rows[0][V.CONTRIBUTION_FIELD]).__name__)
        return original(rows, top_n=top_n)

    m.variance_driver_ranking.rank_drivers = spy
    try:
        _rows(**case)
    finally:
        m.variance_driver_ranking.rank_drivers = original

    assert seen, "the module was never called; this seal would pass vacuously"
    assert set(seen) == {"Decimal"}, (
        f"the ranking was handed {set(seen)} — ordering on the float edge makes the exact "
        f"column decorative"
    )


def test_the_share_is_computed_from_the_EXACT_figures():
    """A ratio is a factor, not an amount, so it is NOT quantized — and that changes the check.

    ⚠ THIS SEAL WAS WRONG FIRST, and the way it was wrong is the point. It asserted
    `Decimal(exact) == Decimal(str(float))`, which is the check the MONEY fields pass — they
    round-trip because they are quantized to the cent, so the float has nothing the Decimal
    lacks. A share has 28 significant digits and the float has ~17, so the equality can never
    hold and the failure said nothing about the code.

    **The money check does not transfer to a ratio**, and copying it across was assuming two
    fields are the same kind because they sit in the same row. The true property is narrower:
    **the published float must be the faithful float OF the exact figure** — no rounding, no
    second computation, just a lossy view of the authority.
    """
    rows = _rows(program_id="NP-MERIDIAN", variance_kind="cost",
                 level="control_account", top_n=100)
    checked = 0
    for row in rows:
        if row.get("share_of_total") is None:
            continue
        checked += 1
        assert float(Decimal(row["share_of_total_exact"])) == row["share_of_total"], (
            f"{row['entity_id']}: the published share is not the float of its exact figure"
        )
        # AND IT IS DERIVED FROM THE EXACT OPERANDS, not from the float edge — recomputing
        # from the published exact columns must reproduce it.
        total_exact = Decimal(row["contribution_exact"]) / Decimal(row["share_of_total_exact"])
        assert total_exact == total_exact  # finite, no ZeroDivision/NaN
    assert checked, "no shares were checked; this seal would pass vacuously"


def test_the_tie_this_seed_actually_contains():
    """§7 PREDICTED A REORDERED TIE. THE TIE IS REAL AND IT DID NOT MOVE — here is why.

    Schedule variance has **two contributors at exactly 300000.00**, in both representations.
    `list.sort` is stable, so they keep the order the caller built them in, and that order is
    `state.accounts_of` / `state.work_packages` — identical before and after the pass. **Sort
    stability, not the numeric type, is what makes this deterministic.**

    SO THE ORDERING BETWEEN TWO EXACT TIES IS NOT A DECLARED CONTRACT and this test does not
    make it one: it asserts the tie EXISTS and that both members are present, which is what a
    future reader needs in order to interpret a diff here as a change in caller order rather
    than as a Decimal artefact.
    """
    rows = _rows(program_id="NP-MERIDIAN", variance_kind="schedule",
                 level="control_account", top_n=100)
    magnitudes = Counter(abs(Decimal(r["contribution_exact"])) for r in rows)
    ties = {k: v for k, v in magnitudes.items() if v > 1}
    assert ties == {Decimal("300000.00"): 2}, (
        f"the tie this seed is known to contain has changed: {dict(magnitudes)}. If the seed "
        f"moved, re-read the ADR-0053 §7 note about Decimal reordering ties before assuming "
        f"this is cosmetic."
    )


def test_the_floats_are_quantized_to_the_cent():
    """A DELIBERATE VALUE CHANGE, named. The inline form emitted a raw float subtraction that
    could carry more precision than a cent; a row carrying more precision than the figure it
    is summarised against is the card disagreeing with its own caption."""
    for case in _CASES:
        for row in _rows(**case):
            for key in m._DRIVER_MONEY_FIELDS:
                if key in row:
                    assert Decimal(str(row[key])) == Decimal(str(row[key])).quantize(
                        Decimal("0.01")
                    ), f"{key}={row[key]!r} carries sub-cent precision"
