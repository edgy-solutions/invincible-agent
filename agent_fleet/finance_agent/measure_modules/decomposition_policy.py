"""When a variance decomposition stops, and what it does with what it drops. ADR-0053 §1.

EXTRACTED FROM `measures.fin_variance_analysis` 2026-09-15, BEHAVIOUR-PRESERVING — the last of
the five.

── WHY THE POLICY AND NOT THE TRAVERSAL ─────────────────────────────────────────────────────
Walking the tree needs state: children come from the program's control accounts and their work
packages, and each node's quantities are a sum over periods. **Deciding whether to keep walking
does not.** That is the seam, and it is where both of R-029's unreachable rules live.

R-029's check found four survivors on this verb, and **three were equivalent mutants against the
reference seed** (`7e2f8a5`): the materiality floor never fires there and the depth limit is
never reached — measured, `{decomposed: 4, leaf: 3}` and **no `explained`, no `depth`**. Those
are the two rules the verb's docstring argues for at greatest length, and nothing but prose
asserted either.

**Taking the decisions as arguments makes both one line to construct.** *A rule becomes
checkable by being lifted* — sixth instance, and the debt this commit owed.

── THE ONE ARITHMETIC LIE THIS ENGINE IS MOST LIKELY TO TELL ────────────────────────────────
Contributors that do not sum to their parent's variance. Dropping an immaterial child silently
is exactly that, so `partition` returns the **residual** and the caller reports it as a row.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

#: This module's own version, not the engine's. 1.0.0 is the extracted-unchanged state.
VERSION = "1.0.0"

#: Every reason a node stops, and each is a DIFFERENT answer to "is this branch complete?".
#:
#: A tree truncated by a depth limit and a tree that genuinely ended look identical from the
#: outside, and only one of them is a complete answer — which is why the reason is a field
#: rather than something a reader infers from an absent list.
STOP_REASONS = ("leaf", "explained", "depth", "decomposed")


def stop_reason(
    *,
    has_children: bool,
    variance: Any,
    floor: Any,
    depth: int,
    max_depth: int,
) -> str:
    """Why this node stops, or `"decomposed"` if it does not.

    THE ORDER OF THESE TESTS IS THE POLICY, not an implementation detail:

    1. **`leaf`** — nothing beneath it in the model. Checked first because a leaf is a fact
       about the data, and reporting a leaf as `depth` would blame the limit for the model's
       shape.
    2. **`explained`** — the node's own variance is immaterial against the ROOT's, so drilling
       further enumerates noise.
    3. **`depth`** — the limit was reached. Last of the three, so a node that was going to stop
       anyway is not reported as truncated.
    """
    if not has_children:
        return "leaf"
    if abs(variance) < floor:
        return "explained"
    if depth >= max_depth:
        return "depth"
    return "decomposed"


def materiality_floor(root_variance: Any, materiality: Any) -> Any:
    """The absolute variance below which a contributor is noise.

    ⚠ A FRACTION OF THE **ROOT** VARIANCE, NEVER OF THE PARENT'S. Against the parent, a $1,000
    variance inside a $2,000 account is 50% and drills; against the root it is noise. **The root
    is the question that was asked, so the root is the scale that matters** — and a
    parent-relative floor would drill deepest exactly where the amounts are smallest.
    """
    return abs(root_variance) * materiality


def partition(
    children: Sequence[dict[str, Any]],
    *,
    variance: Any,
    floor: Any,
) -> tuple[list[dict[str, Any]], Any]:
    """Material children, and the residual the immaterial ones account for.

    THE RESIDUAL IS THE POINT. Contributors that do not sum to their parent's variance is the
    arithmetic lie this engine is most likely to tell — a reader adds the rows up, finds they
    fall short, and cannot tell whether something was hidden or the maths is wrong.

    Returned rather than reported here: the caller phrases the note, because the wording
    carries a currency and a percentage that are the engine's vocabulary, not this module's.
    """
    material = [c for c in children if abs(c["variance"]) >= floor]
    residual = variance - sum(c["variance"] for c in material)
    return material, residual


def share_of_root(variance: Any, root_variance: Any) -> Optional[Any]:
    """This node's share of the variance that was asked about. NODE OVER ROOT.

    None where the root variance is zero — a decomposition of nothing has no shares, and every
    substitute is a proportion nobody computed.

    ⚠ A FAVOURABLE CONTRIBUTOR INSIDE AN UNFAVOURABLE ROOT GETS A NEGATIVE SHARE while carrying
    a POSITIVE variance. **The two signs on one node disagree, and both are correct** — which is
    why the producer emits a `favourable` verdict rather than letting a card colour from either.
    """
    return (variance / root_variance) if root_variance else None


def immaterial_count(children: Iterable[dict[str, Any]], material: Sequence[dict[str, Any]]) -> int:
    """How many contributors were dropped. Reported so the residual has a denominator —
    "netting -40,000" says nothing about whether that is one line or twenty."""
    return len(list(children)) - len(material)
