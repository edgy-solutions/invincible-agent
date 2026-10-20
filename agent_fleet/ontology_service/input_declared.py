"""Input-declared classes: ground on the class the question's verb takes, when recall found only dead ends.

THE MEASURED DEFECT (live walk on 201, caller bob / SAFETY_ENGINEER / SUSTAINMENT). "what failed on
this part" and "risk of deferring this work order": `/resolve` recalled 10 classes for each and NONE
is served, so the productive-option gate stood down and kept the dead pool. The LLM then picked a
dead end (safety#FailureRecord, safety#RiskAssessment) and the router fell to the generalist. The
verbs the questions name are declared on classes that were never recalled:
`mesh:whatFailedOnThisPart` on safety#SafetyCriticalItem and pcn#Component, `mesh:assessDeferralRisk`
on the MaintenanceWorkOrderRecord class.

THE RULING (architect, 2026-10-20): the resolver prefers input-declared classes. Built to fire ONLY
when the served set is non-empty and no recalled candidate is served; every other path is unchanged.

WHY A FLOOR OF 0.80. Live verb recall (`predicate_hybrid_search`, SUSTAINMENT, as bob, 2026-10-20):
  "what failed on this part"            whatFailedOnThisPart 0.923 / 0.910, failureTrendForThisPlatformByMonth 0.834,
                                        mesh:rendersAs 0.523 ...
  "risk of deferring this work order"   assessDeferralRisk 0.893, rendersAs 0.618, draftRiskAssessment 0.519 ...
  off-topic "what color was Napoleon's horse"   rendersAs 0.763, 0.710, 0.700, traceLineage 0.692 ...
The two real questions score their verb at >= 0.89; the off-topic control tops out at 0.763. 0.80 sits
between them. THAT IS A MEASURED SAMPLE OF ONE NEGATIVE, NOT A DERIVED CONSTANT: it is env-tunable
(`INPUT_DECLARED_MIN_SCORE`) and should be re-measured when the verb corpus grows.

WHY TOP VERB ONLY. In the first question failureTrendForThisPlatformByMonth scores 0.834, above the
floor, and its input is safety#Platform, which the question does not name. Taking every verb above
the floor would bring Platform in. Only the top verb's rows count (a verb declared on two inputs has
two rows, and both are kept).

Rows with no `endpoint` are frontend renderers (`mesh:rendersAs`), not routes, and are dropped first.
Pure: no I/O, no import from main.
"""
from __future__ import annotations

DEFAULT_MIN_SCORE = 0.80


def input_declared_classes(verb_rows, *, served, visible, floor):
    """-> (classes: list[dict], trace: dict)"""
    rows = [
        r for r in (verb_rows or [])
        if r.get("endpoint") and r.get("score") is not None
    ]
    rows = sorted(rows, key=lambda r: r["score"], reverse=True)
    if not rows or rows[0]["score"] < floor:
        return [], {
            "reason": "no_verb_above_floor",
            "verb_iri": "",
            "top_score": rows[0]["score"] if rows else None,
            "floor": floor,
            "dropped": [],
        }
    top = rows[0]
    verb = top.get("verb_iri") or ""
    classes: list[dict] = []
    dropped: list[dict] = []
    seen: set = set()
    for r in rows:
        if (r.get("verb_iri") or "") != verb:
            continue
        uri = r.get("input_uri") or ""
        if not uri or uri in seen:
            continue
        seen.add(uri)
        if uri not in served:
            dropped.append({"uri": uri, "check": "not_served"})
            continue
        if not visible(uri):
            dropped.append({"uri": uri, "check": "not_visible"})
            continue
        classes.append({
            "uri": uri,
            "score": r["score"],
            "via_verb": verb,
            "verb_description": r.get("description") or "",
        })
    return classes, {
        "reason": "declared_input" if classes else "not_served_or_not_visible",
        "verb_iri": verb,
        "top_score": top["score"],
        "floor": floor,
        "dropped": dropped,
    }
