"""Burn against plan, with a trailing rate and a runway. ADR-0053 §1.

EXTRACTED FROM `measures.fin_burn_rate` 2026-09-14, BEHAVIOUR-PRESERVING — the third of the
remaining extractions.

R-029's check ran first and found **six survivors on a twelve-day-old seal**: the smoothing
window narrowed to one and widened to all, the runway taken over cumulative burn, the
`variance_to_plan` sign flipped, `budget_remaining` ignoring spend, and the skip rule's `and`
turned to `or`. Five were real wrong-answer paths and are sealed in `b42ce8f`, filed as their
own record — a correctness gap found during a refactor does not ride in the refactor.

── THE MEASURE IS THE SMOOTHING AND THE FORECAST IT FEEDS ───────────────────────────────────
Two of those survivors were the trailing window; a third was the runway's denominator. **That
is the unit**: what gets averaged, over how many periods, and which rate the remaining budget
is divided by. The state access, the program and the BAC are the caller's.

── THE SIXTH SURVIVOR IS WHY THIS MODULE EXISTS AT ALL, BEYOND TIDINESS ─────────────────────
`and` → `or` in the skip rule is an **equivalent mutant against the reference seed**, which has
no period where exactly one of plan and spend is zero — 6 both-zero, 6 neither, **0 partly**.
Contriving a seed to make it bite would be testing the fixture.

**Lifting the rule is what makes it testable**: this module takes quantities directly, so a
partly-zero period is three lines to construct, and `test_the_burn_series_measure_module.py`
constructs it. The rule becomes checkable BY BEING EXTRACTED, and pinning it here was owed by
this commit.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

#: This module's own version, not the engine's. 1.0.0 is the extracted-unchanged state.
VERSION = "1.0.0"

#: How many periods the trailing mean averages over.
#:
#: DECLARED RATHER THAN TUNED: short enough to follow a turn, long enough not to chase one
#: month. **It rides on every row as `trailing_periods` so the figure can be argued with** — a
#: smoothed rate whose window is invisible is a number a reader cannot check or disagree with.
TRAILING_PERIODS = 3


def build(
    quantities: Iterable[tuple[Any, float, float]],
    *,
    budget_at_completion: float,
    scope_label: str,
    value_unit: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Burn rows for a period series of (period, planned, burn).

    A PERIOD WITH NEITHER PLAN NOR SPEND PRODUCES NO ROW — `and`, never `or`. A period that
    PLANNED work and spent nothing is a real and interesting row: it is a stall, and dropping
    it would hide exactly the thing the series exists to show.

    `variance_to_plan` IS PLANNED MINUS BURN, so **positive means spending below plan**.
    Flipped, a program running over plan reads as running under it, which is the single fact a
    reader acts on.

    `runway_periods` IS OVER THE TRAILING RATE, not the cumulative burn. A different
    denominator is a different forecast wearing the same name — and on the first row the two
    are equal by arithmetic (one period of history), so they only diverge later.

    PERIODS, NOT A DATE. Converting would need a period-to-date map the caller's model does not
    hold, and inventing one is how a forecast acquires a precision its inputs never had.
    """
    rows: list[dict[str, Any]] = []
    # SEEDED AT INT ZERO so a Decimal caller works: `0.0 + Decimal(...)` raises. One character,
    # and it is the difference between a measure that lifts and one that does not — the trap
    # `index_series` shipped with and a seal now guards.
    cum_burn = cum_planned = 0
    burns: list[float] = []
    for period, planned, burn in quantities:
        if planned == 0 and burn == 0:
            continue
        cum_burn += burn
        cum_planned += planned
        burns.append(burn)

        trailing = burns[-TRAILING_PERIODS:]
        rate = sum(trailing) / len(trailing)
        remaining = budget_at_completion - cum_burn
        rows.append({
            "period": period,
            "scope_label": scope_label,
            "burn": burn,
            "planned": planned,
            "variance_to_plan": planned - burn,
            "cum_burn": cum_burn,
            "cum_planned": cum_planned,
            "budget_remaining": remaining,
            "trailing_rate": rate,
            "trailing_periods": len(trailing),
            # NONE, NOT INFINITY. A program burning nothing has no runway in periods — the
            # figure is undefined, and "unlimited" is an assertion about solvency nobody made.
            "runway_periods": (remaining / rate) if rate > 0 else None,
            "value_unit": value_unit,
        })
    return rows
