"""VERB ELIGIBILITY — the two rules that decide WHICH verb may act on a subject.

Both were private to `dynamic_supervisor` until 2026-09-08. They move here because the
pre-resolved re-ask is about to run OUTSIDE Dagster, straight from the BFF, and it needs the
same two rules. A second copy in the gateway is the shape this repo has already paid for: the
card and the routing record each had a rule for picking the primary subtask, the two agreed
in a docstring, and they disagreed in production.

PURE BY CONSTRUCTION — no network, no Dagster context, no logging. Both take records that
`/find_compatible_verbs` returned and answer questions about them. That is what makes them
safe to call from either side of the Dagster boundary, and it is the property to preserve:
anything needing a `context` or an HTTP client does NOT belong in this module.

The supervisor keeps its underscore-prefixed names as aliases, so every existing call site and
seal reads unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, List

from iagent_pure.slot_acceptance import decode_declarations

__all__ = ["filter_verbs_by_arity", "predicate_from_compat_record"]


def filter_verbs_by_arity(
    compatible_verbs: list[dict], query_is_set: bool
) -> tuple[list[dict], list[dict]]:
    """Query-shape eligibility — FLAGS a single-asset verb, no longer excludes it.

    When the query is SET-shaped (subject resolved to a CLASS, with no specific
    instance), a verb declaring ``arity == "single"`` cannot run as asked. It is marked
    ``needs_instance`` and KEPT as a candidate. Returns ``(all_verbs, flagged)``.

    WHY EXCLUSION WAS THE WRONG DISPOSAL, ruled 2026-09-04 after H06 failed live.
    "What is the capability path" grounds to `Capability` cleanly and then reports NO VERB
    CLASSIFIED, because `planCapabilityPath` is `arity: single`, the question names no
    instance, and this gate removed the only verb that fits — FOR THE REASON IT WOULD HAVE
    ASKED ABOUT.

    MEASURED AGAINST THE DEPLOYED GRAPH 2026-09-05, and the pool did NOT go empty: Capability
    carries TWO verbs under PORTFOLIO_PLANNING, and dropping `planCapabilityPath` left
    `planMaturityGrid` — which does not answer "what is the capability path". So the classifier
    was handed one wrong candidate and honestly returned UNKNOWN. The gate did not starve it;
    it starved it of the RIGHT option, which is the harder failure to see.

    THE GATE'S OWN PREMISE IS OBSOLETE, AND ITS CITATION SAYS SO. `arity_for` was written
    against `a-missing-mandatory-slot-is-a-400-not-an-ask.md`: routing a set-shaped question
    to a single verb "gets a 400 for a missing mandatory slot, two hops later and with no
    surface a reader can act on". **That 400 is now an ASK.** The disposition offers a menu
    — Capability has nine members under the bound, and the fan-out is live. Excluding the
    verb to avoid an error that no longer happens costs the answer instead.

    KEEPING IT CANNOT PRODUCE A SILENT DISPATCH, and that is structural rather than lucky.
    `arity_for` derives "single" from exactly one condition: the measure has a slot that is
    both REQUIRED and a REFERENT. So the property that makes a verb single-arity IS the
    property the slot layer asks about — a kept single verb whose instance was never named
    reaches `decide_disposition` with an unfilled mandatory referent, which is an ASK or an
    ABSTAIN, never a dispatch. The two mechanisms were built five weeks apart and meet here.

    THE OTHER HALF OF THE GATE STANDS: a set-shaped question must not route to a single verb
    SILENTLY. It no longer can — but the flag is carried so the disposition and the decision
    path can both see WHY an ask was owed, rather than inferring it from a missing slot.

    Still PURE — no LLM, no network. Null arity stays unflagged (an incomplete backfill must
    never over-restrict), and instance-shaped queries flag nothing.
    """
    if not query_is_set or not compatible_verbs:
        return compatible_verbs, []
    flagged: list[dict] = []
    out: list[dict] = []
    for v in compatible_verbs:
        if str(v.get("arity") or "").lower() == "single":
            # Copied rather than mutated: these dicts come from
            # /find_compatible_verbs and are read elsewhere in the turn.
            marked = dict(v)
            marked["needs_instance"] = True
            flagged.append(marked)
            out.append(marked)
        else:
            out.append(v)
    return out, flagged


def predicate_from_compat_record(cv: dict) -> dict:
    """Dispatch coordinates for one verb, built from Neo4j's compat-walk record.

    ONE BUILDER, TWO CALLERS, and the second caller is why it was extracted. The pre-resolved
    path needs exactly this dict and could trivially have built its own - which is the shape
    this repo has already paid for: the card and the routing record each had a rule for
    picking the primary subtask, the two agreed in a docstring, and they disagreed in
    production. Two dicts that match on today's fields drift on the next field added to one.

    Neo4j is authoritative for dispatch coordinates (see the endpoint-authority note at the
    override site): /find_compatible_verbs reads verb edges Engine O rebuilt deterministically
    from the TTL, not a vector-search blob that a rename can orphan.
    """
    return {
        "verb_iri": cv.get("verb_iri"),
        "verb_type": cv.get("verb_local"),
        "input_uri": cv.get("input_uri"),
        "output_uri": cv.get("output_uri"),
        "endpoint": cv.get("endpoint_url") or "",
        "owner_persona": cv.get("owner_persona"),
        "domains": cv.get("domains") or [],
        "cost_class": cv.get("cost_class"),
        "requires_human_approval": cv.get("requires_human_approval", False),
        # WHAT THE VERB TAKES - the acceptance schema for spoken slots, projected from the
        # engine's registration (`mesh_slots`). `[]` until doc-tools' aitool_linker allowlist
        # carries it, and `[]` means every spoken slot is refused, which is today's behaviour
        # exactly.
        "slots": decode_declarations(cv.get("slots")),
    }
