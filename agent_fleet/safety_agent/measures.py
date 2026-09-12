"""Engine S's verbs. Governed READING over the sustainment plane — nothing here mutates.

ADR-0051 §3. Two verbs in this increment; the rest wake as their increments land. Every
answer is drafted, cited, and refusable, and NO verb in this module can set an acceptance —
that act is a HumanTask disposition by an entitled authority (§5, §7).

── WHY EACH ANSWER CARRIES ITS OWN GAPS ────────────────────────────────────────────────────
A safety answer that omits what it could not determine is worse than no answer, because the
omission reads as a negative. So `findOrphanedHazards` reports WHY each hazard is orphaned
rather than just that it is, and `assessDeferralRisk` states explicitly when a deferral's
hazard cannot be resolved instead of returning a clean "no hazard".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:  # flat in the image (/app), packaged in the repo — runbook §5, flat FIRST
    from entities import (
        BY_HAZARD_ID,
        CRITICAL_ITEMS,
        HAZARDS,
        WORK_ORDERS,
        Hazard,
        Probability,
        Scope,
        Severity,
    )
except ImportError:
    from agent_fleet.safety_agent.entities import (  # type: ignore[no-redef]
        BY_HAZARD_ID,
        CRITICAL_ITEMS,
        HAZARDS,
        WORK_ORDERS,
        Hazard,
        Probability,
        Scope,
        Severity,
    )


#: A hazard is LIVE if it is open or mitigated. `not_assessed` is neither, and
#: that is the whole point of the third state: it is not evidence of safety and
#: it is not evidence of danger, so it is reported separately rather than
#: folded into either. `closed` is done.
_LIVE_STATUSES = frozenset({"open", "mitigated"})


def _orphan_reason(h: Hazard) -> Optional[str]:
    """WHY this hazard is orphaned, or None if it is not.

    THREE DISTINCT MECHANISMS, and the reason is returned rather than a boolean because
    "unowned" and "never verified in the field" need different people to do different things.
    A caller handed `True` has to go and re-derive which one it was.
    """
    if h.status not in _LIVE_STATUSES:
        return None
    if not h.mitigations:
        return "no mitigation recorded"
    if all(m.owner is None for m in h.mitigations):
        return "mitigation recorded but no owner"
    # An owned mitigation that nobody has confirmed in the field. THE PAPER-CLOSED
    # CASE: `verified_in_field` is three-state, so `not_verified` means nobody has
    # been to look, and `false` would mean somebody looked and it had not been done.
    # Both leave the hazard live; they are reported distinctly because the second
    # is a finding and the first is an absence.
    owned = [m for m in h.mitigations if m.owner is not None]
    if all(m.verified_in_field == "not_verified" for m in owned):
        return "mitigation owned but never verified in the field"
    if all(m.verified_in_field == "false" for m in owned):
        return "mitigation owned and verification FAILED in the field"
    return None


def _in_scope(h: Hazard, scope: Scope, scope_value: Optional[str]) -> bool:
    """Scope is referent-bound: `tail` and `platform` name a thing, `fleet` names everything.

    A scope of `tail` with no value is NOT silently widened to the fleet — that would answer
    a different question than the one asked and report it as the same. The caller-facing
    refusal for that lives in the verb.
    """
    if scope == "fleet":
        return True
    if scope == "platform":
        return h.platform == scope_value
    return h.tail == scope_value


def find_orphaned_hazards(
    state: Any = None,
    *,
    scope: Scope = "fleet",
    scope_value: Optional[str] = None,
) -> Dict[str, Any]:
    """Live hazards with no owned, field-verified mitigation — ranked by severity, then age.

    ADR-0051's first failure. A hazard is orphaned when it is still live and one of three
    things is true: no mitigation was recorded, a mitigation was recorded but nobody owns it,
    or an owner exists and nobody has confirmed the work in the field.

    THE THIRD IS THE ONE THAT HIDES. A mitigation that exists and is owned reads as handled in
    any view that checks only for its presence, which is why `verified_in_field` is three-state
    and why the reason travels with the row.

    NOT-ASSESSED HAZARDS ARE REPORTED SEPARATELY AND ARE NEVER COUNTED AS ORPHANS. A hazard
    nobody has characterised is not a hazard with a missing mitigation; it is a hazard with a
    missing assessment, and a different person fixes it. Folding the two together inflates the
    orphan count and buries the assessment gap.
    """
    if scope != "fleet" and not scope_value:
        return {
            "refused": True,
            "reason": f"scope '{scope}' names a thing; supply which {scope}",
            "orphans": [],
        }

    orphans: List[dict] = []
    not_assessed: List[dict] = []
    for h in HAZARDS:
        if not _in_scope(h, scope, scope_value):
            continue
        if h.status == "not_assessed":
            not_assessed.append({"hazard_id": h.hazard_id, "description": h.description,
                                 "tail": h.tail, "opened_on": h.opened_on})
            continue
        reason = _orphan_reason(h)
        if reason is None:
            continue
        orphans.append({
            "hazard_id": h.hazard_id,
            "description": h.description,
            "status": h.status,
            "severity": h.severity,
            "probability": h.probability,
            "tail": h.tail,
            "platform": h.platform,
            "opened_on": h.opened_on,
            "orphan_reason": reason,
        })

    # Severity first, then age. A severity of None sorts LAST rather than first:
    # an unassessed severity is not a severe one, and ranking it top would put the
    # least-known hazard above the worst-known one.
    orphans.sort(key=lambda r: (
        {"I": 1, "II": 2, "III": 3, "IV": 4}.get(r["severity"] or "", 99),
        r["opened_on"],
    ))
    return {
        "refused": False,
        "scope": scope,
        "scope_value": scope_value,
        "orphans": orphans,
        "orphan_count": len(orphans),
        # Reported, never merged into the count above.
        "not_assessed": not_assessed,
        "not_assessed_count": len(not_assessed),
    }


def assess_deferral_risk(state: Any = None, *, work_order_id: str) -> Dict[str, Any]:
    """Is this deferred work order's item safety-critical, and which hazard does it re-open?

    ADR-0051's third failure. The answer a person currently gives from memory: a work order is
    deferred, and whether that deferral re-opens a hazard depends on whether the item is on the
    critical items list — which nobody checks at fleet scale.

    EVERY BRANCH IS NAMED, INCLUDING THE UNEVENTFUL ONES. A deferral on a non-critical item
    returns `critical: false` with the list it was checked against, not an empty answer: the
    caller needs to know the check RAN. An unknown work order refuses rather than returning
    "not critical", because those two are the same shape and opposite facts.

    THE DRAFTED RISK IS DRAFTED. Severity and probability are carried from the hazard the
    deferral re-opens; this verb resolves neither a risk level nor an acceptance, and cannot
    set one.
    """
    if not work_order_id:
        return {"refused": True, "reason": "which work order?"}

    wo = next((w for w in WORK_ORDERS if w.work_order_id == work_order_id), None)
    if wo is None:
        # NOT the same as "not critical", and reported differently on purpose.
        return {"refused": True, "reason": f"unknown work order '{work_order_id}'"}

    csi = next((c for c in CRITICAL_ITEMS if c.part_number == wo.part_number), None)
    out: Dict[str, Any] = {
        "refused": False,
        "work_order_id": wo.work_order_id,
        "part_number": wo.part_number,
        "deferred": wo.deferred,
        "deferred_reason": wo.deferred_reason,
        "tail": wo.tail,
        "safety_critical": csi is not None,
        "critical_items_checked": len(CRITICAL_ITEMS),
    }
    if csi is None:
        out["assessment"] = "not_applicable"
        out["note"] = "Item is not on the critical items list; no hazard is re-opened by this deferral."
        return out

    out["csi_id"] = csi.csi_id
    hazard = BY_HAZARD_ID.get(csi.opens_hazard_id)
    if hazard is None:
        # The critical item names a hazard the plane does not hold. NAMED, not
        # swallowed: an unresolvable reference is a data defect somebody must fix,
        # and returning a clean "no hazard" would hide it.
        out["assessment"] = "not_assessed"
        out["note"] = (
            f"Critical item {csi.csi_id} names hazard {csi.opens_hazard_id}, "
            "which is not present in the graph."
        )
        return out

    out["reopens_hazard_id"] = hazard.hazard_id
    out["reopens_hazard"] = hazard.description
    out["hazard_status"] = hazard.status
    out["severity"] = hazard.severity
    out["probability"] = hazard.probability
    out["assessment"] = "drafted" if wo.deferred else "not_applicable"
    if not wo.deferred:
        out["note"] = "Work order is not deferred; the hazard is not re-opened by a deferral."
    else:
        out["note"] = (
            f"Deferring {wo.work_order_id} leaves {hazard.hazard_id} live. "
            "Severity and probability are carried from the hazard; the risk level and its "
            "acceptance authority are resolved from the ratified matrix, and neither is set here."
        )
    return out
