"""PCN/PDN disposition proposer — the deterministic funnel-input core (feeds [[workflow_bulk_resolve]]).

Turns a notice's affected parts into ``PartItem``s for ``run_funnel``: a relevance score (is this part
in OUR scope) and a SYSTEM-PROPOSED disposition (what to do about it). Pure, deterministic, no LLM —
the disposition is a proposal the approver accepts-with-exceptions, never an automated decision.

The rule is an INITIAL, defensible heuristic (refine with domain input); its structure keeps the
judgment in one place. The load-bearing property is honest degradation at the PROPOSER level: when the
rule cannot confidently propose (unknown/ambiguous change), it returns ``None`` — the part then has no
proposed disposition, so it cannot ride accept-all and the approver must dispose it explicitly (the
same discipline as a no-disposition row in the core). The system proposes only what it's sure of.
"""
from __future__ import annotations

from typing import Optional

try:  # same lazy-import dance as the other restate_analyst cores
    from workflow_bulk_resolve import PartItem  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_bulk_resolve import PartItem

# Dispositions (mesh verbs) — kept as plain strings; the core routes, it does not enumerate elsewhere.
_LTB = "dispatchLTB"
_QUALIFY = "dispatchQualification"
_ALT = "dispatchAltSourcing"          # noqa: F841 - part of the vocabulary; reserved for the alt path
_ARCHIVE = "archive"

# Change categories that affect form/fit/function -> a replacement must be qualified.
_FFF_CATEGORIES = {"Material", "Process", "Testing", "Discontinuation"}
# Purely administrative changes -> acknowledge, no engineering action.
_ADMIN_CATEGORIES = {"Location", "Packaging"}


def propose_disposition(
    doc_type: str,
    *,
    has_replacement: bool,
    categories: Optional[list[str]] = None,
) -> Optional[str]:
    """The system-proposed disposition, or ``None`` when the rule can't confidently propose.

    * Discontinuation (``doc_type`` PDN, or a PCN carrying the ``Discontinuation`` category):
      a named replacement -> qualify it (``dispatchQualification``); none -> last-time buy to bridge
      (``dispatchLTB``).
    * A PCN change: any form/fit/function category (Material/Process/Testing) -> qualify; ONLY
      administrative categories (Location/Packaging) -> archive (FYI).
    * Anything the rule can't classify (no categories, unknown category only) -> ``None`` (honest:
      the approver decides; the part cannot ride accept-all)."""
    cats = set(categories or [])
    is_discontinuation = str(doc_type).upper() == "PDN" or "Discontinuation" in cats
    if is_discontinuation:
        return _QUALIFY if has_replacement else _LTB
    # A PCN change (not a discontinuation).
    if cats & _FFF_CATEGORIES:
        return _QUALIFY
    if cats and cats <= _ADMIN_CATEGORIES:
        return _ARCHIVE
    return None  # unclassifiable -> no proposal; the approver must dispose it explicitly


def score_relevance(mpn: str, *, in_scope_mpns: set) -> float:
    """1.0 if the affected part is in OUR scope (BOM/AVL), else 0.0 (the funnel filters it). Scope is
    an INPUT — no optimistic default: a part we don't own is not our problem, and we don't fabricate
    relevance for parts we can't place. An empty scope set means nothing is in scope (all filtered),
    which is honest, not a bug — supply the real scope."""
    return 1.0 if (mpn or "") in (in_scope_mpns or set()) else 0.0


def build_part_items(
    impacted_parts: list[dict],
    *,
    doc_type: str,
    categories: Optional[list[str]] = None,
    in_scope_mpns: set,
) -> list[PartItem]:
    """Assemble ``PartItem``s (funnel input) from a notice's impacted parts. ``subject`` is left None —
    it is filled by the resolveInstance step (the deterministic component IRI); the proposer owns the
    DISPOSITION + RELEVANCE judgment only. ``needs_review`` is carried straight from the extraction."""
    items: list[PartItem] = []
    for p in impacted_parts:
        mpn = str(p.get("affected_mpn") or "").strip()
        if not mpn:
            continue
        has_replacement = bool(str(p.get("replacement_mpn") or "").strip())
        items.append(PartItem(
            mpn=mpn,
            relevance=score_relevance(mpn, in_scope_mpns=in_scope_mpns),
            subject=None,  # filled by the resolveInstance step
            proposed_disposition=propose_disposition(
                doc_type, has_replacement=has_replacement, categories=categories),
            needs_review=bool(p.get("needs_review", False)),
        ))
    return items
