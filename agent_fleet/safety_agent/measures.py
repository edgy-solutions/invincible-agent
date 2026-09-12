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
    from matrix import resolve_risk_level
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
    from agent_fleet.safety_agent.matrix import resolve_risk_level  # type: ignore[no-redef]


#: A hazard is LIVE if it is open or mitigated. `not_assessed` is neither, and
#: that is the whole point of the third state: it is not evidence of safety and
#: it is not evidence of danger, so it is reported separately rather than
#: folded into either. `closed` is done.
_LIVE_STATUSES = frozenset({"open", "mitigated"})

#: The levels MIL-STD-882E 4.3.7 requires a user-representative concurrence for (§5.1).
#:
#: NOT a stylistic choice and NOT extendable by preference: the standard names Serious and High
#: and says nothing about Medium or Low, so inventing a concurrence step for those would be as
#: wrong as omitting one here. Held as a SET OF LEVEL NAMES rather than a rank threshold because
#: the standard names levels — a threshold would silently acquire any level a tailored matrix
#: later inserted above it, which is a rule growing by accident.
_CONCURRENCE_LEVELS = frozenset({"High", "Serious"})


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


def draft_risk_assessment(state: Any = None, *, hazard_id: str) -> Dict[str, Any]:
    """Draft a risk assessment for one hazard: severity, probability, level, authority, citations.

    THE VERB THIS WHOLE ADR IS ABOUT, AND THE ONE IT MOST CAREFULLY LIMITS.

    It drafts. `acceptance_status` is `drafted` and this function contains no path that writes
    anything else — asserted by seal 2's AST half, not by this sentence. Acceptance is a HumanTask
    disposition by an authority entitled at the level the draft IMPLIES (ADR-0051 §5, §7).

    THE RISK LEVEL COMES FROM THE RATIFIED MATRIX, NOT FROM HERE. `resolve_risk_level` reads
    `safety_risk_matrix.ttl`; this function only carries what it is told. That is §2's whole claim
    and seal 4 is what makes it true of the build rather than of the ADR: change one row in the TTL
    and the drafted level changes with no code edit.

    CITE-OR-OMIT (seal 11). Every figure in the draft names the source object it came from. A
    severity this engine cannot source is reported as `not_assessed` with the gap named — never
    inferred from a neighbouring hazard, never defaulted to the bottom of the matrix, which reads as
    assessed-and-negligible.
    """
    if not hazard_id:
        return {"refused": True, "reason": "which hazard?"}

    h = BY_HAZARD_ID.get(hazard_id)
    if h is None:
        # An unknown hazard REFUSES. Returning an empty draft would be a risk assessment
        # asserting nothing about a hazard that does not exist, which is worse than a refusal
        # because it renders as a completed assessment.
        return {"refused": True, "reason": f"unknown hazard '{hazard_id}'"}

    # DERIVED_FROM: every source object this draft actually read. Seal 10 asserts each one
    # resolves; a fabricated entry must go red, which is why they are collected as they are used
    # rather than declared up front from a list someone remembered.
    derived_from: List[str] = [h.hazard_id]
    citations: Dict[str, str] = {}

    out: Dict[str, Any] = {
        "refused": False,
        "hazard_id": h.hazard_id,
        "hazard": h.description,
        "tail": h.tail,
        "platform": h.platform,
        # THE ONE VALUE THIS VERB MAY WRITE.
        "acceptance_status": "drafted",
    }

    if h.severity is None or h.probability is None:
        # NOT ASSESSED, AND SAID SO. The matrix is not consulted, no level is invented, and the
        # gap names which half is missing so the reader knows what to go and get.
        out["assessment"] = "not_assessed"
        out["severity"] = h.severity
        out["probability"] = h.probability
        out["gap"] = (
            "severity" if h.severity is None else "probability"
        ) + " is not assessed on this hazard; no risk level is resolved and no authority is implied"
        out["derived_from"] = derived_from
        out["citations"] = citations
        return out

    out["severity"] = h.severity
    out["probability"] = h.probability
    citations["severity"] = f"hazard {h.hazard_id}"
    citations["probability"] = f"hazard {h.hazard_id}"

    level, audience, source = resolve_risk_level(h.severity, h.probability)
    if level is None:
        # An unrecognized pair REFUSES LOUDLY, naming the vocabulary and its file (seal 5).
        return {
            "refused": True,
            "reason": (
                f"severity '{h.severity}' / probability '{h.probability}' is not a cell in the "
                f"ratified matrix ({source})"
            ),
        }
    out["risk_level"] = level
    out["acceptance_audience"] = audience
    citations["risk_level"] = source
    citations["acceptance_audience"] = source
    derived_from.append(source)

    # The mitigation picture, cited per mitigation rather than summarised — a summary cannot be
    # traced back to which mitigation it described.
    mitigations = []
    for m in h.mitigations:
        mitigations.append({
            "mitigation_id": m.mitigation_id,
            "owner": m.owner,
            "verified_in_field": m.verified_in_field,
        })
        derived_from.append(m.mitigation_id)
    out["mitigations"] = mitigations
    out["orphan_reason"] = _orphan_reason(h)

    out["derived_from"] = derived_from
    out["citations"] = citations
    out["note"] = (
        f"DRAFTED. Accepting this risk requires an authority in '{audience}'. "
        "This engine cannot accept it; the acceptance is a task disposition with a required reason."
    )

    # ── THE REVIEW REQUEST — everything the gateway needs to open the acceptance,
    # and NOTHING THIS ENGINE MAY DO ITSELF.
    #
    # THE ENGINE DOES NOT CALL `register_task`, AND THAT IS THE ARCHITECTURE RATHER THAN
    # AN OMISSION. `register_task` is the gateway's (`gateway.py:644`); it resolves the
    # audience's actors from Topaz and materializes the queue rows. An engine that wrote
    # tasks would be mutating the plane it reads — the two-planes violation ADR-0035
    # rules on — and would put the acceptance substrate behind an engine's availability.
    #
    # So the draft carries a request the gateway can hand to `register_task` VERBATIM.
    # The keys are that function's keyword arguments deliberately: a shape that needs
    # translating is a shape that can be translated wrongly, and the translation would
    # live in whichever caller happened to write it first.
    #
    # THE PAYLOAD IS CLEARANCE-BOUNDED (§5): a reference and a clearance-safe summary,
    # never compartmented content, because the queue itself must not become the leak. The
    # citations travel because an acceptance without its evidence is the signature this
    # ADR exists to prevent; the hazard's full narrative does not.
    # ── WHICH TASK OPENS FIRST IS DECIDED BY THE LEVEL (§5.1) ──────────────────────────
    #
    # MIL-STD-882E §4.3.7 requires the user representative's formal concurrence BEFORE a
    # Serious or High acceptance decision. "Before" is in the standard's sentence, so it is
    # made STRUCTURAL rather than advisory: for those two levels the only task this draft
    # opens is the CONCURRENCE, and the acceptance request does not exist yet. It is built
    # by `acceptance_request_after_concurrence` from a disposed `concurred` record, which is
    # the only way to obtain one.
    #
    # A design that opened both at once would put an acceptance in an authority's queue
    # while the concurrence was outstanding — satisfying neither the letter nor the point,
    # and doing it invisibly, because both queues would look entirely normal.
    needs_concurrence = level in _CONCURRENCE_LEVELS
    out["requires_concurrence"] = needs_concurrence
    if needs_concurrence:
        out["review_request"] = {
            "kind": f"risk_acceptance_concurrence_{level.lower()}",
            "task_id": f"risk-concurrence-{h.hazard_id}",
            "audience": f"risk_acceptance_concurrence_{level.lower()}:SUSTAINMENT",
            "title": f"Concur on {level} risk — {h.hazard_id}",
            "summary": (
                f"{h.description} Severity {h.severity}, probability {h.probability}, "
                f"resolved {level}. USER REPRESENTATIVE CONCURRENCE, required before the "
                f"acceptance decision (MIL-STD-882E 4.3.7)."
            ),
            "requested_by": "engine-safety",
            "subject_ref": h.hazard_id,
            "payload": {
                "hazard_id": h.hazard_id,
                "severity": h.severity,
                "probability": h.probability,
                "risk_level": level,
                "citations": citations,
                "derived_from": derived_from,
                "reason_required": ["concurred", "not_concurred"],
                # NAMED SO THE CONCURRING PARTY KNOWS WHAT THEY ARE ENABLING. A concurrence
                # whose consequence is invisible is the rubber stamp peer-level exists to stop.
                "unblocks_acceptance_audience": audience,
            },
        }
        out["note"] = (
            f"DRAFTED. {level} risk requires the user representative's formal concurrence "
            f"BEFORE acceptance (MIL-STD-882E 4.3.7). The acceptance task for "
            f"'{audience}' is NOT opened until that concurrence is disposed `concurred`."
        )
        return out

    out["review_request"] = {
        "kind": f"risk_acceptance_{level.lower()}",
        "task_id": f"risk-acceptance-{h.hazard_id}",
        "audience": audience,
        "title": f"Accept {level} risk — {h.hazard_id}",
        "summary": (
            f"{h.description} Severity {h.severity}, probability {h.probability}, "
            f"resolved {level} from the ratified matrix. "
            f"{'No owned, field-verified mitigation.' if out.get('orphan_reason') else ''}"
        ).strip(),
        "requested_by": "engine-safety",
        "subject_ref": h.hazard_id,
        "payload": {
            "hazard_id": h.hazard_id,
            "severity": h.severity,
            "probability": h.probability,
            "risk_level": level,
            "citations": citations,
            "derived_from": derived_from,
            # STATED IN THE PAYLOAD, not only in this ADR: the disposer must see that a
            # reason is required before they act, not discover it from a refusal.
            "reason_required": ["accepted", "rejected"],
        },
    }
    return out




def acceptance_request_after_concurrence(
    state: Any = None, *, hazard_id: str, concurrence: Dict[str, Any]
) -> Dict[str, Any]:
    """The acceptance task for a Serious or High hazard — obtainable ONLY from a disposed
    `concurred` record.

    THIS FUNCTION IS THE "BEFORE" IN MIL-STD-882E 4.3.7, MADE STRUCTURAL. `draftRiskAssessment`
    does not emit an acceptance request for these levels; this is the only path to one, and it
    refuses without a concurrence that actually says `concurred`. A caller cannot skip the step
    by choosing not to call a checker, because there is nothing to skip TO.

    THE LINEAGE IS THE POINT, NOT THE GATE. The returned request carries `DERIVED_FROM` to the
    concurrence task and records who concurred and why, so "who signed, on what evidence" has
    TWO names on it. A gate that blocked the acceptance but left no record would satisfy the
    ordering and lose the thing the ordering exists to produce.
    """
    h = BY_HAZARD_ID.get(hazard_id)
    if h is None:
        return {"refused": True, "reason": f"unknown hazard '{hazard_id}'"}

    decision = (concurrence or {}).get("decision")
    if decision != "concurred":
        # NOT_CONCURRED AND UNDISPOSED ARE REPORTED DISTINCTLY. One is a decision the
        # authority must be told about; the other is a step still outstanding. Collapsing
        # them would turn "the user representative declined" into "not ready yet".
        return {
            "refused": True,
            "reason": (
                f"no acceptance task for {hazard_id}: concurrence is "
                f"{decision or 'not yet disposed'}, and MIL-STD-882E 4.3.7 requires formal "
                "concurrence BEFORE the acceptance decision"
            ),
            "concurrence_decision": decision,
        }
    if not (concurrence.get("comment") or "").strip():
        # The concurrence kind declares `concurred` reason-required. Enforced here too,
        # because the declaration does not yet bind at runtime (R-004(f)) and an acceptance
        # built on an unexplained concurrence is the rubber stamp peer-level exists to stop.
        return {
            "refused": True,
            "reason": f"concurrence on {hazard_id} carries no stated basis; it is reason-required",
        }

    draft = draft_risk_assessment(hazard_id=hazard_id)
    if draft.get("refused"):
        return draft
    level = draft["risk_level"]
    audience = draft["acceptance_audience"]
    derived_from = list(draft["derived_from"]) + [concurrence.get("task_id", "")]
    return {
        "refused": False,
        "kind": f"risk_acceptance_{level.lower()}",
        "task_id": f"risk-acceptance-{h.hazard_id}",
        "audience": audience,
        "title": f"Accept {level} risk — {h.hazard_id}",
        "summary": (
            f"{h.description} Severity {h.severity}, probability {h.probability}, resolved "
            f"{level}. User representative concurred: {concurrence.get('comment')}"
        ),
        "requested_by": "engine-safety",
        "subject_ref": h.hazard_id,
        "payload": {
            "hazard_id": h.hazard_id,
            "severity": h.severity,
            "probability": h.probability,
            "risk_level": level,
            "citations": draft["citations"],
            "derived_from": [d for d in derived_from if d],
            "reason_required": ["accepted", "rejected"],
            # THE SECOND NAME ON THE SIGNATURE.
            "concurred_by": concurrence.get("acted_by"),
            "concurrence_task_id": concurrence.get("task_id"),
            "concurrence_basis": concurrence.get("comment"),
        },
    }
