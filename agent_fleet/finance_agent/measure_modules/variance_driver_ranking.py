"""Which contributors to a variance are drivers, and in what order. ADR-0053 §1.

EXTRACTED FROM `measures.fin_variance_drivers` 2026-09-12, BEHAVIOUR-PRESERVING, values
unchanged. ADR-0053 §7 names this verb as the first extraction and gives the reason: it
**ranks by `abs(contribution)`**, so the money ruling's *"producers and any consumer that
subtracts or compares"* clause catches it. **The ranking is the measure**, which is why this
module owns the ordering rules and not the payload shaping.

── WHAT THIS MODULE DELIBERATELY DOES NOT OWN ──────────────────────────────────────────────
The **variance convention** (`_variance`, `_is_favourable`) stays in `measures.py`. Those have
five and three callers respectively across other verbs; they are the engine's vocabulary, not
this measure's, and moving them would widen a behaviour-preserving extraction into a change
touching verbs nobody is checking today.

Nor does it own **state access**. The caller gathers; this computes. That is the seam that
makes "no I/O" true rather than aspirational.

── THE DECIMAL PASS IS NOT THIS COMMIT, AND MAY NOT BE BEHAVIOUR-PRESERVING ────────────────
ADR-0053 §7: *"Decimal can reorder a tie that float resolved arbitrarily, which is a
deliberate value change — exactly the thing that must not be entangled with a refactor."*
`_ordering_is_stable_on_ties` below is where that will show, and it is documented now so the
reader of the Decimal diff knows where to look.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

#: This module's own version, not the engine's. Bumping it is a claim that figures may change.
#: 1.0.0 is the extracted-unchanged state: the same numbers the inline form produced.
VERSION = "1.0.0"

#: The field ranked on. Named rather than inlined because the ordering rule and the field it
#: reads are one decision, and a caller passing rows with a different key should fail loudly
#: rather than rank everything at zero.
CONTRIBUTION_FIELD = "contribution"


def rank_drivers(
    rows: Iterable[dict[str, Any]],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """Drop non-contributors, order by absolute contribution, truncate, and declare the tail.

    `rows` are candidate contributor rows already carrying a `contribution`. They are MUTATED
    in place with `rank`, and with the withheld fields when truncation occurs — matching the
    inline form exactly, which built rows and then annotated them.

    FOUR RULES, and each was a decision in the original:

    1. **A contributor of nothing is not a driver.** A zero contribution is dropped rather
       than ranked last. It is not a small driver; it is not one.
    2. **Order by ABSOLUTE contribution, with the sign left on the row.** Favourable
       contributors are ranked too, and that is not a completeness gesture: ranking only the
       unfavourable rows produces a list whose magnitudes sum to MORE than the variance they
       claim to explain, and a reader doing the obvious arithmetic finds the numbers do not
       add up.
    3. **Rank is 1-based and assigned after truncation**, so the visible list reads 1..n.
    4. **The tail is declared where it is truncated.** `top_n` hiding contributors without
       saying so is a partial list that looks complete. Every returned row carries the count
       withheld and their summed contribution, so a reader can see the ranking is a window.
    """
    if top_n < 1:
        # A GUARD ON THE MODULE'S OWN CONTRACT, raised as ValueError rather than the engine's
        # NotInModel: a measure module may not depend on engine exception types (§1, no
        # imports beyond its own needs). The VERB keeps its own NotInModel check with its own
        # message, so the caller-facing refusal is unchanged by this extraction.
        raise ValueError(f"top_n must be at least 1, got {top_n!r}")

    scored = [r for r in rows if r.get(CONTRIBUTION_FIELD)]
    scored.sort(key=lambda r: abs(r[CONTRIBUTION_FIELD]), reverse=True)

    ranked = scored[:top_n]
    for i, row in enumerate(ranked, start=1):
        row["rank"] = i

    if len(scored) > len(ranked):
        withheld = sum(r[CONTRIBUTION_FIELD] for r in scored[top_n:])
        for row in ranked:
            row["withheld_contributors"] = len(scored) - len(ranked)
            row["withheld_contribution"] = withheld
    return ranked


def share_of_total(contribution: Any, total: Any) -> Optional[Any]:
    """A contributor's share, or None where the total is zero.

    NONE, NOT ZERO. A variance of zero has no contributors-as-a-proportion — the ratio is
    undefined, not "nobody contributed". Both substitutes are assertions nobody made, and a
    card would draw either as a real share. Same rule as `measures._ratio`, stated here
    because this module cannot import it without taking a dependency the contract forbids.
    """
    return (contribution / total) if total else None


def _ordering_is_stable_on_ties() -> str:
    """Documentation-as-code for the property the Decimal pass will test.

    `list.sort` is stable, so contributors with equal `abs(contribution)` keep the order the
    CALLER built them in — which is the order `state.accounts_of` / `state.work_packages`
    returns. That is deterministic today and it is not a DECLARED ordering: nothing asserts
    what happens between two exact ties.

    ADR-0053 §7 flags that the Decimal pass may REORDER such a tie, which would be a
    deliberate value change. This function exists so that sentence has a named place in the
    code rather than living only in the ADR.
    """
    return "stable; ties keep caller order; not a declared ordering"
