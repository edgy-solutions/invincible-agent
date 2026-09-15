"""The three estimate-at-completion formulas, and the figures derived from one. ADR-0053 §1.

EXTRACTED FROM `measures.fin_eac_calculation` 2026-09-15, BEHAVIOUR-PRESERVING.

R-029's check found **five of six mutations surviving** a green suite here, the worst rate of the
five finance verbs. The worst single one was `BAC * CPI` in place of `BAC / CPI`: with CPI below
one that **reverses the sign of the forecast** — an overrun of 2.15M reading as 1.8M under
budget. Sealed in `9f2d4bb`; recorded in
`docs/plans/the-eac-forecast-could-be-inverted-unsealed.md`.

── WHY THIS MODULE IS THE ONE §2 WAS WRITTEN FOR ────────────────────────────────────────────
ADR-0053 §2 makes methods **registry rows**, and §2a requires each row to carry an **absolute
transcription seal** against the clause its `prov:wasDerivedFrom` cites. **This module is the
unit such a row points at.** Each formula is one expression with one standard behind it, and
`FORMULA` below carries the transcription a seal compares against — so a row that names a method
and a version is naming something checkable rather than a label.

**A comparison across methods does not substitute.** `fin_eac_comparison` compares the three
methods' spread and did **not** catch the inversion, because `BAC * CPI` preserves the ordering.
*A relative check is blind to what its subjects share.*

── WHAT THIS MODULE DOES NOT OWN ────────────────────────────────────────────────────────────
State access, the program, the period window, and the refusal when no method is named — the
caller gathers and refuses; this computes. `ratio` is passed in for the same reason
`index_series` takes it: `measures._ratio` has eleven call sites and is the engine's vocabulary
for *"an index, or None where the denominator is zero"*.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

#: This module's own version, not the engine's. 1.0.0 is the extracted-unchanged state.
VERSION = "1.0.0"

#: THE TRANSCRIPTION §2a COMPARES AGAINST. Public EVM methodology, written as the standard
#: states it rather than as Python spells it, so a reader checking a row against its clause is
#: comparing like with like.
#:
#: `REMAINING_AT_BUDGET` PROJECTS NO INDEX, which is why it always answers where the other two
#: can be undefined — and why the "every method undefined" refusal somebody first wrote here was
#: unreachable. That property is a fact about the formula, so it belongs beside it.
FORMULA: dict[str, str] = {
    "REMAINING_AT_BUDGET": "EAC = ACWP + (BAC - BCWP)",
    "CPI": "EAC = BAC / CPI",
    "CPI_SPI": "EAC = ACWP + (BAC - BCWP) / (CPI * SPI)",
}

#: Whether a method needs a performance index to answer. DATA, not a branch: §2 wants
#: `requires_index` on the row so a refusal's reachability is a property of the registry rather
#: than something discovered by reading code — which is how the unreachable refusal got written.
REQUIRES_INDEX: dict[str, bool] = {
    "REMAINING_AT_BUDGET": False,
    "CPI": True,
    "CPI_SPI": True,
}


def estimate_at_completion(
    method: str,
    *,
    bac: Any,
    bcwp: Any,
    acwp: Any,
    cpi: Optional[Any],
    spi: Optional[Any],
) -> Optional[Any]:
    """The forecast, or None where the method needs an index the data does not provide.

    NONE IS NOT ZERO. With no performance reported there is no index to project forward, and
    every substitute figure would be an invention — the caller turns this into a named refusal
    rather than a number.

    ⚠ `CPI` DIVIDES. With CPI below one — work costing more than it earns — dividing RAISES the
    forecast. Multiplying lowers it, which does not make the answer wrong by a margin: **it
    reverses the finding**, and a reader acts on the difference between "over" and "under".
    """
    if method == "REMAINING_AT_BUDGET":
        return acwp + (bac - bcwp)
    if method == "CPI":
        return (bac / cpi) if cpi else None
    if method == "CPI_SPI":
        return (acwp + (bac - bcwp) / (cpi * spi)) if (cpi and spi) else None
    raise ValueError(f"unknown EAC method {method!r}; known: {sorted(FORMULA)}")


def derived(eac: Any, *, bac: Any, acwp: Any, bcwp: Any,
            ratio: Callable[[Any, Any], Optional[Any]]) -> dict[str, Any]:
    """The three figures that follow from a forecast, each answering a different question.

    `vac`  — BAC − EAC. **Budget minus forecast, so NEGATIVE means overrun.** Flipped, an
             overrun reads as an underrun.
    `etc`  — EAC − ACWP. What the remaining work is forecast to cost FROM HERE. Measured from
             BCWP instead it answers how far the forecast exceeds the value already earned —
             a different question, and the two differ by exactly the cost variance.
    `percent_complete` — BCWP / BAC, the share of authorised work done. Over ACWP it becomes a
             performance index wearing a progress label.
    """
    return {
        "vac": bac - eac,
        "etc": eac - acwp,
        "percent_complete": ratio(bcwp, bac),
    }
