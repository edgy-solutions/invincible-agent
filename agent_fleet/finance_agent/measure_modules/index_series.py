"""Performance indices as a period series, with running cumulatives. ADR-0053 §1.

EXTRACTED FROM `measures.fin_performance_indices` 2026-09-14, BEHAVIOUR-PRESERVING, values
unchanged — the second of ADR-0053 §7's remaining extractions.

THE MEASURE IS THE SERIES CONSTRUCTION, not the division. Four ratios come out of this, but
the part that is hard to get right and had no seal until `501d6b0` is the *shape*: which
periods produce a row at all, what accumulates across them, and which figures the cumulative
indices are taken over. R-029's required check found two live wrong-answer paths here — a
swapped CPI/SPI and a cumulative computed from period figures — neither of which the standing
seal could see.

── WHY `ratio` IS AN ARGUMENT AND NOT AN IMPORT ─────────────────────────────────────────────
`measures._ratio` has **eleven call sites** across this engine. It is the engine's vocabulary
for *"a performance index, or None where the denominator is zero"* — None rather than 1.0 or
0.0, because a period in which nothing was spent has no cost performance index and both
substitutes are assertions about performance that nobody made.

Defining a second one here would duplicate a **named rule** and let the two drift, with this
module holding the copy nobody greps for. Importing it would give a measure module a
dependency on the engine it is supposed to be liftable out of. **So the caller passes its
own**, which keeps one implementation, states the dependency in the signature, and leaves the
module pure — a callable argument is not I/O.

── WHAT THIS MODULE DELIBERATELY DOES NOT OWN ───────────────────────────────────────────────
State access, program resolution, the `ca_id` narrowing and `scope_label`. The caller gathers
a period-indexed series of quantities; this builds the rows. That seam is what makes the
module's "no I/O" true rather than aspirational, and it is the same one `variance_driver_ranking`
uses.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional, Sequence

#: This module's own version, not the engine's. 1.0.0 is the extracted-unchanged state.
VERSION = "1.0.0"

#: A period whose quantities are all zero produces NO ROW.
#:
#: DELIBERATE-ABSENT, and it is the rule most easily mistaken for a rounding choice. A period
#: with nothing reported is not a period of zero performance; emitting a row draws a point on
#: the trend line asserting the program stopped, which is a claim the data does not make.
_ABSENT = (0, 0, 0)


def build(
    quantities: Iterable[tuple[Any, float, float, float]],
    *,
    ratio: Callable[[float, float], Optional[float]],
    scope_label: str,
    amount_unit: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Index rows for a period series of (period, bcws, bcwp, acwp).

    `ratio` is the caller's undefined-safe division — see the module docstring for why it is
    not imported. It must return None where the denominator is zero; a callable that returns a
    number there changes what every row means, and `_ratio_is_undefined_safe` below is the
    cheap way to find out before building anything.

    FOUR RATIOS, TWO QUESTIONS. The period index says how this month went; the cumulative says
    where the program stands. **They are routinely confused and they diverge** — in the
    reference seed from the third row on — so both are reported rather than leaving a reader
    to guess which one a single figure was.

    CPI IS COST AND SPI IS SCHEDULE. `cpi = bcwp/acwp`, `spi = bcwp/bcws`. Swapping them is
    undetectable by shape: both are dimensionless, both sit near 1, and they say OPPOSITE
    things about what to do. Every row therefore carries the quantities its ratios were taken
    over, so a consumer can check the response against itself.
    """
    rows: list[dict[str, Any]] = []
    cum_bcws = cum_bcwp = cum_acwp = 0.0
    for period, bcws, bcwp, acwp in quantities:
        if (bcws, bcwp, acwp) == _ABSENT:
            continue
        cum_bcws += bcws
        cum_bcwp += bcwp
        cum_acwp += acwp
        rows.append({
            "period": period,
            "scope_label": scope_label,
            "cpi": ratio(bcwp, acwp),
            "spi": ratio(bcwp, bcws),
            "cum_cpi": ratio(cum_bcwp, cum_acwp),
            "cum_spi": ratio(cum_bcwp, cum_bcws),
            "bcws": bcws, "bcwp": bcwp, "acwp": acwp,
            "cum_bcws": cum_bcws, "cum_bcwp": cum_bcwp, "cum_acwp": cum_acwp,
            "cost_variance": bcwp - acwp,
            "schedule_variance": bcwp - bcws,
            # THE RATIOS ARE DIMENSIONLESS; the amounts beside them are not. Stating the unit
            # of the amounts keeps the response honest without putting a currency on a ratio.
            "amount_unit": amount_unit,
        })
    return rows


def ratio_is_undefined_safe(ratio: Callable[[float, float], Optional[float]]) -> bool:
    """Does this `ratio` answer None over a zero denominator?

    A CHEAP PRECONDITION ON AN INJECTED DEPENDENCY. Injection buys one implementation and
    costs the guarantee that the implementation is the right one — a caller passing
    `operator.truediv` gets a ZeroDivisionError, and one passing a lambda that returns 1.0
    gets a series quietly asserting perfect performance in periods where nothing was spent.

    Offered rather than enforced inside `build`: checking it per call would run the caller's
    function on data it never asked about, and a measure module that probes its arguments is
    doing something other than computing.

    CALLED FROM THE SEALS, NOT FROM BOOT — and that is a deliberate limit rather than an
    oversight. Wiring a new startup assertion inside an EXTRACTION would be a behaviour change
    riding in a behaviour-preserving move, which is the entanglement ADR-0053 §7 refuses. If
    this engine later grows a boot-time contract check for measure modules, this belongs in
    it; until then a green suite is the only thing asserting the precondition, and a caller
    who passes a bad `ratio` in production finds out from the figures.
    """
    try:
        return ratio(1.0, 0.0) is None
    except Exception:
        return False


def periods_present(rows: Sequence[dict[str, Any]]) -> list[Any]:
    """The periods that produced a row. NAMED so the absence is inspectable.

    A caller comparing this against the periods it asked for can see which were
    deliberate-absent, rather than inferring it from a length difference.
    """
    return [r["period"] for r in rows]
