"""Funding cells: what is authorised, committed and spent, and the gap between them. ADR-0053 §1.

EXTRACTED FROM `measures.fin_funding_status` 2026-09-15, BEHAVIOUR-PRESERVING.

R-029's check found **six survivors, three real and three equivalent** (`48ceed9`). The three
real ones were `at_risk` measured against the wrong quantity, `unexpended_balance` taken from
the wrong operand, and a dropped window filter.

── THE THREE EQUIVALENTS ARE WHY THIS MODULE EXISTS BEYOND TIDINESS ─────────────────────────
The `max(0, ...)` floor, the `gap`/`shortfall` split, and the row ordering were **equivalent
mutants against the reference seed**: no line in it is over-obligated, and the rows arrive
already sorted. Contriving a seed to reach them would be testing the fixture.

**Taking cells as arguments makes all three constructible**, and
`test_the_funding_grid_measure_module.py` constructs them. *A rule becomes checkable by being
lifted* — fifth instance, and the debt this commit owed.

── THE PAIR THAT IS EASY TO SWAP AND IMPOSSIBLE TO SEE ──────────────────────────────────────
`unobligated_balance` is `authorized - obligated`; `unexpended_balance` is
`obligated - expended`. **One subtraction apart, both plausible under either name**, and the
field name gives no hint which operands it was taken over. They are computed side by side here
so the pairing is legible at the point it is decided.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

#: This module's own version, not the engine's. 1.0.0 is the extracted-unchanged state.
VERSION = "1.0.0"

#: The verdict's own vocabulary, and IPMDAR's name for the same cell. TWO VOCABULARIES FOR ONE
#: FACT, declared together so they cannot drift: each is what a different reader looks at, and a
#: row whose two names disagree is the response contradicting itself.
IPMDAR_NAME: dict[str, str] = {
    "short": "unobligated-balance",
    "pledged-not-firm": "obligated-not-expended",
    "met": "expended",
}


def build(
    cells: Iterable[tuple[str, str, str, Any, Any, Any]],
    *,
    verdict: Callable[[Any, Any, Any], str],
    order: Callable[[str], Any],
    value_unit: Optional[str] = "USD",
) -> list[dict[str, Any]]:
    """Grid rows for `(line_id, name, period, authorized, obligated, expended)` cells.

    `verdict` is the caller's — it is the engine's judgement about a funding state, not this
    module's arithmetic, and it is passed in for the same reason `index_series` takes `ratio`.
    `order` maps a period to its sort key, since period ordering is domain vocabulary the
    caller owns.

    ── THE FOUR DERIVED QUANTITIES, AND WHY EACH IS NOT THE OTHERS ──────────────────────────
    `shortfall` — authorised money not yet COMMITTED, **floored at zero**. An over-obligated
                  line has committed more than was authorised; that is a real condition and it
                  is not a negative shortfall, so the floor is the honest reading.
    `gap`       — the SAME subtraction, SIGNED. The floor loses the over-obligated case
                  entirely, so the signed figure is carried beside it rather than instead.
                  **Two fields because one number cannot say both.**
    `at_risk`   — authorised money not yet SPENT, floored. Exposure, not a funding gap: it
                  measures against `expended`, and against `obligated` it silently collapses
                  into `shortfall`.
    `unexpended_balance` — committed money not yet paid out, `obligated - expended`. From
                  `authorized` it becomes committed and uncommitted money added together.

    THE ROWS ARE SORTED BY `(subject, period)`. A grid renderer relies on it, and a caller
    handing cells in arrival order must still get a grid.
    """
    rows: list[dict[str, Any]] = []
    for line_id, name, period, authorized, obligated, expended in cells:
        state = verdict(authorized, obligated, expended)
        rows.append({
            # THE GRID'S CONTRACT: subject x period, three quantities, a verdict. `subject_id`
            # is the cell's POSITION and `line_id` is what it is ABOUT — the same split the
            # planning grid draws, and why the archetype cannot name the subject itself.
            "subject_id": line_id,
            "subject_name": name,
            "period": period,
            "required": authorized,
            "committed": obligated,
            "secured": expended,
            "shortfall": max(0, authorized - obligated),
            "gap": authorized - obligated,
            "at_risk": max(0, authorized - expended),
            "state": state,
            # the same cell in IPMDAR's words
            "line_id": line_id,
            "authorized": authorized,
            "obligated": obligated,
            "expended": expended,
            "unobligated_balance": authorized - obligated,
            "unexpended_balance": obligated - expended,
            "funding_state": IPMDAR_NAME[state],
            "value_unit": value_unit,
            "value_label": "Unobligated balance",
            "scope_label": name,
        })
    rows.sort(key=lambda r: (r["subject_id"], order(r["period"])))
    return rows
