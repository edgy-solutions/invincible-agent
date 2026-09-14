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

__all__ = [
    "filter_verbs_by_arity",
    "predicate_from_compat_record",
    "turn_is_set_shaped",
]


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


def turn_is_set_shaped(
    subject_instance_id: str | None,
    verb: Dict[str, Any],
    bound_slot_names: set[str] | None,
) -> bool:
    """Is THIS turn set-shaped for THIS verb - reading the bound slots, not just the subject.

    WHY THE SUBJECT FIELD ALONE IS THE WRONG READ, measured 2026-09-14 on the empty
    `finProgramBrief` card. The answer-after-a-pick turn gets its route from
    `_pre_resolved_from_ask`, which copies `subject_instance_id` out of **the ask artifact's**
    `resolved_intent`. The ask is by construction the turn where no instance was named, so
    that field is necessarily empty there - and it is copied forward unchanged onto the turn
    that finally supplies one. The picked value lands in the chain's bound slots
    (`accepted_slots: {"program_id": "NP-MERIDIAN"}`), which nothing promotes.

    So `not subject_instance_id` reported SET on the exact turn that named the instance, the
    arity gate flagged the verb `needs_instance`, and the dispatch precondition abstained -
    **for the reason the ask had just been answered.** Same shape as the H06 ruling that made
    this gate stop excluding, one layer further along: the gate is right that an instance is
    needed and wrong about whether one arrived.

    THE LINK IS DECLARED, NOT SNIFFED. A slot carrying `referent` names the class it
    identifies an instance of, and `arity: single` is FORCED by exactly that slot being both
    required and a referent (see `GraphManifest._arity_agrees_with_slots`). So the slot that
    makes a verb single-arity IS the slot whose binding supplies the instance - the same
    coincidence `filter_verbs_by_arity` already relies on to guarantee a kept verb cannot
    dispatch silently. Reading it here closes the loop rather than adding a rule.

    Conservative in the same direction as every other gate: unknown bound slots (``None``)
    means "nothing known to be bound", never "assume an instance".
    """
    if subject_instance_id:
        return False
    bound = bound_slot_names or set()
    if not bound:
        return True
    for decl in decode_declarations(verb.get("slots")):
        if not isinstance(decl, dict):
            continue
        if decl.get("referent") and decl.get("required") and decl.get("name") in bound:
            return False
    return True


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


# ── PROMOTING A BOUND REFERENT INTO THE RECORD ──────────────────────────────────────────────
#
# `turn_is_set_shaped` taught the arity GATE to read the chain's bound slots. It did not write
# the RECORD, so a turn that bound `program_id` from an offered menu still projected
# `instance_resolved: false` with an empty identifier - a resolved turn reporting as unresolved.
# That is a self-consistent false record, which no consistency check can see (R-056).
#
# THE GATE ON PROMOTION IS PROVENANCE, NOT SHAPE. `subject_instance_id` does not stop at the
# projection: it reaches the generalist fallback as `resolved_instance_id`, and Engine A does
# NOT re-resolve it. So promoting a value means an engine will act on a string without any
# validator having seen it - unless one already has.

#: Sources whose value a validator HAS already seen, and the reason for each.
#:
#:   picked  - chosen from a menu THIS SYSTEM enumerated at the hop that bound it, so the value
#:             is one of the options the graph itself produced.
#:   filled  - extracted from the question by the slot filler, which resolves against the graph.
#:
#: The two the architect named, and the reason is the same in both: a validator stands between
#: the value and the record.
PROMOTABLE_SLOT_SOURCES = frozenset({"picked", "filled"})

#: Sources NOT promoted, each with its reason. An exclusion list with reasons is auditable; one
#: without is the list nobody can read - and a source missing from BOTH sets is a hard failure
#: below rather than a quiet non-promotion.
NON_PROMOTABLE_SLOT_SOURCES: dict[str, str] = {
    "supplied": (
        "sent by an API caller with the request. THE ONE SOURCE NO VALIDATOR HAS SEEN - "
        "promoting it would have Engine A read an unchecked caller string as a resolved "
        "instance and skip re-resolution. Architect-ruled 2026-09-14."
    ),
    "spoken": (
        "UNDECIDED, AND EXCLUDED WHILE UNDECIDED. Typed in answer to a RESPEAK ask where NO "
        "menu existed, so no enumeration validated it; whether the resolver then saw it is not "
        "established here. The 2026-09-14 ruling named picked, filled and supplied and did not "
        "reach this one. Not promoting is the conservative arm - it leaves today's behaviour, "
        "where Engine A re-resolves - so it is excluded pending a ruling rather than decided by "
        "whichever set it fell into first."
    ),
}


def promotable_instance_from_slots(
    verb: Dict[str, Any],
    accumulated_slots: Dict[str, Any] | None,
) -> tuple[str, str, str] | None:
    """The bound value that identifies this verb's instance, IF a validator has seen it.

    Returns ``(value, slot_name, source)`` or ``None``. ``None`` means "leave the record as it
    was", which is today's behaviour and the safe arm in every uncertain case.

    THE SLOT IS FOUND BY THE SAME CONJUNCTION THE REST OF THIS MODULE USES: ``required`` AND
    ``referent``. That is what forces ``arity: single`` (`GraphManifest._arity_agrees_with_slots`)
    and therefore what makes this slot's binding the thing that supplies the instance. Reading
    the same declaration here means the gate and the promotion cannot drift apart into two
    opinions about which slot matters.
    """
    slots = accumulated_slots or {}
    if not slots:
        return None
    for decl in decode_declarations(verb.get("slots")):
        if not isinstance(decl, dict):
            continue
        if not (decl.get("referent") and decl.get("required")):
            continue
        rec = slots.get(decl.get("name"))
        if not isinstance(rec, dict):
            continue
        source = str(rec.get("source") or "")
        if source in NON_PROMOTABLE_SLOT_SOURCES:
            return None
        if source not in PROMOTABLE_SLOT_SOURCES:
            # AN UNKNOWN SOURCE IS NOT A DEFAULT, the same rule `_accumulated_slots` applies one
            # layer up. A fifth source added upstream must not be promoted by falling through.
            return None
        value = rec.get("value")
        if value in (None, ""):
            return None
        return str(value), str(decl.get("name") or ""), source
    return None
