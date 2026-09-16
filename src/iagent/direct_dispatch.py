"""THE DIRECT PATH: executing a route the ask already established, without a Dagster run.

MEASURED 2026-09-08 on a pre-resolved pick: 24 seconds end to end, of which roughly ONE
second is work. Gateway 0.26s, Dagster run-launch 8.4s, the run itself 13.1s, write 1.5s. The
routing decision inside that run took 0.24s and the engine call about two seconds; everything
else is orchestration for a job with one op.

Dagster is right for a question that must be decomposed — `/plan` fan-out, the prime. It is
the wrong home for a turn that already knows its subject, its verb and its slots, because
there is nothing left to orchestrate. So this module executes that turn directly.

WHAT IT KEEPS FROM THE RUN, none of it optional:

  the eligibility verifier   `/find_compatible_verbs`, in front of the engine call. It is the
                             INVALIDATION — entitlements are revoked, engines retired, the TTL
                             re-primed — and a verb carried from an earlier ask is a cache
                             that nothing else expires. It is also re-read under whoever is
                             PICKING, so a persona change between ask and pick is caught here
                             rather than inherited.
  the arity gate             `needs_instance` is not on the compat-walk record; the filter puts
                             it there. Reading it without running the filter finds nothing,
                             every time, silently — and a single-asset verb then dispatches
                             against a set query instead of asking.
  slot acceptance            the same `accept_slots`, so a spoken answer is validated against
                             the menu that offered it and not merely splatted at an engine.
  the routing record         emitted in MATERIALIZATION SHAPE and projected by the gateway's
                             existing `_project_route_decision` / `_project_graph_trace`. One
                             projector, two producers. Building a second shaper here is how the
                             card and the routing record came to disagree in production once
                             already.

WHAT IT DOES NOT DO. It emits no SSE and writes no artifact. The gateway owns both: the
artifact goes through the SAME writer so `derived_from` and the projection are unchanged, and
the stream is a separate contract that must describe the stages this path ACTUALLY runs rather
than the five a Dagster run would have. Announcing "Understanding your question" for a turn
that understood nothing is a success line for work that never happened.

EVERY FAILURE FALLS BACK TO THE RUN rather than refusing. The worst outcome of a miss here is
a slow answer, which is exactly today's behaviour; refusing would be a regression on a path
that is meant to be strictly an optimisation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from iagent.verb_lookup import find_compatible_verbs
from iagent_pure.slot_acceptance import (
    SLOT_SOURCE_PICKED,
    SLOT_SOURCE_SPOKEN,
)
from iagent_pure.slot_disposition import (
    ABSTAIN as _ABSTAIN_ACTION,
    ASK as _ASK,
    ROUTE as _ROUTE,
    decide_disposition,
    mandatory_slots,
)
from iagent_pure.routing_record import (
    graph_trace_record as build_graph_trace_record,
    routing_record as build_routing_record,
)
from iagent_pure.verb_eligibility import (
    filter_verbs_by_arity,
    predicate_from_compat_record,
    promotable_instance_from_slots,
    turn_is_set_shaped,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DirectOutcome",
    "ROUTED", "ASK", "ABSTAIN", "FALL_BACK",
    "STAGE_VERIFYING", "STAGE_CALLING", "STAGE_RENDERING", "STAGE_FELL_BACK",
    "DISPATCH_STAGES",
    "dispatch_pre_resolved",
    "materialization",
]

ROUTED = "routed"
ASK = "ask"
ABSTAIN = "abstain"
FALL_BACK = "fall_back"

#: THE STAGES THIS PATH ACTUALLY RUNS, and the list is short because the path is short.
#: The Dagster stream's five kinds describe a decomposition, a resolution and a
#: classification — none of which happen here, because the ask already answered all three.
#: Emitting "understanding" for a turn that understood nothing is a success line for work
#: that never ran, so these are NEW kinds and the client renders what arrives rather than a
#: fixed five. `rendering_answer` is the gateway's: it makes the Engine F call, so it emits
#: that one and this module does not.
STAGE_VERIFYING = "verifying_route"
STAGE_CALLING = "calling_engine"
#: The Engine F render, emitted by the gateway because the gateway makes that call.
#:
#: NOT `writing_answer`. The artifact write is dispatched AFTER `stream_end`, deliberately —
#: delivery is never coupled to the Neo4j write — so a stage named for it could never be
#: reported completed to a client that has already been told the stream is over. A stage the
#: client can only ever see start is worse than no stage at all.
STAGE_RENDERING = "rendering_answer"
#: THE DECLINE, ANNOUNCED. Emitted by the gateway when the fast path hands the turn back to
#: the run. Without it a fall-back is indistinguishable from the fast path merely being
#: slow, and the only way to tell them apart is timing a pick by hand — which is exactly how
#: the original 24 seconds went unnoticed for a day. The FALLBACK RATE is the number that
#: says whether this path is real, and a rate needs an event per occurrence.
#:
#: NOT a second terminal on `verifying_route`: that stage has already reported `failed` on
#: two of the three decline paths, and a `completed` after a `failed` is the unbalanced pair
#: this module's own seal forbids.
STAGE_FELL_BACK = "fell_back"

#: Every kind this module may emit. The gateway's contract seal derives the expected set
#: from here rather than repeating it, so a stage added below cannot be forgotten there.
DISPATCH_STAGES = (STAGE_VERIFYING, STAGE_CALLING)

#: The engine call sits inside a request a person is waiting on, not a Dagster op that already
#: cost tens of seconds. The run's 1800s ceiling is right there and wrong here: a hung engine
#: must end the turn with a card that says so, not hold the connection open for half an hour.
#: Measured engine calls on this path are ~1-2s.
DEFAULT_ENGINE_TIMEOUT_S = 120.0


@dataclass
class DirectOutcome:
    """What the direct path decided, and the evidence for it.

    `kind` is the discriminant and the four values have genuinely different consequences —
    collapsing FALL_BACK into ABSTAIN would turn "we could not check" into "there is no
    answer", which is the same conflation this repo removed from Contract D's `missing`.
    """
    kind: str
    reason: str = ""
    #: Materialization-shaped, for the gateway's existing projectors. Never a projected record.
    routing_mat: Optional[dict] = None
    graph_trace_mat: Optional[dict] = None
    slots_mat: Optional[dict] = None
    #: The engine's own response body, verbatim.
    engine_response: Optional[dict] = None
    #: WHY A FAILED DISPATCH FAILED — status, body, exception — so the artifact records its own
    #: cause. Without it a `failed` artifact says WHICH VERB was tried and nothing about what
    #: came back, and the answer lives only in a pod log that rotates. Same class as the missing
    #: `verb_iri`: a failure recorded where nobody reads is a failure nobody can act on.
    failure_cause: Optional[dict] = None
    predicate: Optional[dict] = None
    accepted_params: Dict[str, Any] = field(default_factory=dict)
    refusals: List[dict] = field(default_factory=list)


def materialization(**metadata: Any) -> dict:
    """Build the `{"metadataEntries": [...]}` shape Dagster produces and the gateway parses.

    Emitting this rather than a projected record is the whole point: the gateway's
    `_project_route_decision` is then the ONE thing that turns routing facts into an artifact
    field, whether they came from a run or from here. A second shaper would agree today and
    drift on the next field added to one of them — which is precisely how the card and the
    routing record came to select different subtasks in production.

    Values are typed the way `_metadata_dict` expects: text for strings, floatValue for
    numbers, boolValue for booleans. A float sent as text reads back as a string and every
    comparison against it silently fails.
    """
    entries = []
    for label, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, bool):
            entries.append({"label": label, "boolValue": value})
        elif isinstance(value, (int, float)):
            entries.append({"label": label, "floatValue": float(value)})
        else:
            entries.append({"label": label, "text": str(value)})
    return {"metadataEntries": entries}


def dispatch_pre_resolved(
    *,
    pre_resolved: Dict[str, Any],
    bound_slots: Dict[str, Any],
    chain_slots: Optional[Dict[str, Any]] = None,
    spoken_answer: str,
    user_query: str,
    #: THE RUN THIS DISPATCH IS, and it has NO DEFAULT ON PURPOSE.
    #:
    #: A stateful graph row refuses a call without one - measured on
    #: artifact-2-1789497046894, whose recorded 422 body read: `fin_program_brief declares
    #: checkpointer: true, so it needs a thread_id to checkpoint under - the row's contract
    #: is thread_id = run id`. The request body recorded beside it was exactly
    #: `{query, params}`: the contract was never spoken on this side.
    #:
    #: NO DEFAULT HERE, because every plausible one is wrong in a way that PASSES. The
    #: session id scopes state to a SESSION, so turn 2 silently resumes turn 1's
    #: checkpoint; the graph's own name - the fallback the host deleted - scopes it to
    #: every caller at once. A default invented in the callee becomes a contract nobody
    #: agreed to, so the caller declares what its run is and this function only carries it.
    run_id: str,
    entitled_domains: List[str],
    acting_persona: str,
    ontology_url: str,
    accept_slots,
    engine_timeout: float = DEFAULT_ENGINE_TIMEOUT_S,
    headers: Optional[Dict[str, str]] = None,
    post=None,
    on_stage=None,
) -> DirectOutcome:
    """Execute a route the ask already established.

    `on_stage(kind, status)` is called at the REAL boundaries of the two stages this
    function runs — `verifying_route` and `calling_engine` — so the stream reports work
    that happened rather than a timeline composed after the fact. It is a plain callable,
    invoked synchronously, because this function is sync and runs in a worker thread; the
    caller decides how to deliver. Every `started` is followed by exactly one `completed`
    or `failed` on every return path, which is the property the stream contract rests on.

    `accept_slots` and `post` are injected rather than imported so this is testable without a
    network and without the slot module's transitive imports — and so a test that stubs the
    engine is stubbing THE call, not a copy of it.
    """
    _post = post or requests.post
    _stage = on_stage or (lambda *_a, **_k: None)
    subject = str(pre_resolved.get("subject_uri") or "")
    verb = str(pre_resolved.get("verb_iri") or "")
    instance_id = str(pre_resolved.get("subject_instance_id") or "")
    if not subject or not verb:
        return DirectOutcome(FALL_BACK, "no pre-resolved route")

    # ── 1. VERIFY. The invalidation, and it runs BEFORE anything is dispatched ──────────
    _stage(STAGE_VERIFYING, "started")
    verbs, err = find_compatible_verbs(subject, entitled_domains, ontology_url=ontology_url)
    if err is not None:
        # COULD NOT CHECK is not NOTHING IS COMPATIBLE. Falling back to the run means the
        # question still gets answered, by the path that has its own handling for this.
        _stage(STAGE_VERIFYING, "failed")
        return DirectOutcome(FALL_BACK, f"verifier unreachable: {err}")

    # ── 2. ARITY. The flag is not on the record; the filter puts it there ───────────────
    #
    # ⛔ THIS IS THE SITE THE DEFECT WAS MEASURED ON, and it is the one that RUNS. The
    # supervisor has the same gate for the fallback path; a pick-answer reaches here first.
    #
    # `instance_id` comes from the ASK artifact's `resolved_intent`, and the ask is by
    # construction the turn where nothing was named — so it is empty here and rides forward
    # onto the turn that finally supplies one. The picked value lands in `chain_slots`
    # (`{"program_id": {"value": "NP-MERIDIAN", "source": "picked"}}`), which nothing read.
    # So `not instance_id` reported SET on the exact turn that named the instance, the gate
    # flagged `needs_instance`, and the dispatch abstained FOR THE REASON THE ASK HAD JUST
    # BEEN ANSWERED.
    #
    # PER VERB, because the gate is a property of the VERB'S DECLARATION: the slot that is
    # both `required` and a `referent` forces `arity: single` AND is the slot whose binding
    # supplies the instance. A verb declaring no such slot is unaffected BY CONSTRUCTION,
    # which is what makes this safe for the three engines of four that declare no arity.
    # ⛔ THIS READ `chain_slots` ALONE AND THAT IS THE DEFECT THE WHOLE ARC WAS ABOUT.
    #
    # `chain_slots` is what the ANCESTORS bound. The pick that answers an ask arrives on THIS
    # turn, in `bound_slots`, and is by construction in no ancestor — measured on
    # artifact-4-1789438505471, whose own record carries
    # `{"program_id": {"value": "NP-MERIDIAN", "source": "picked"}}` while its parent, the ask,
    # carries `{}`. So the gate looked only where the value could never be and flagged
    # `needs_instance` on the turn that named the instance.
    #
    # The writer was correct and the reader was looking one hop upstream. Same shape as the
    # original defect — a value present in one place and read from another — reproduced inside
    # the fix for it.
    _turn_records = {
        k: {"value": v, "source": SLOT_SOURCE_PICKED} for k, v in dict(bound_slots or {}).items()
    }
    _provenance = {**{k: v for k, v in (chain_slots or {}).items() if isinstance(v, dict)},
                   **_turn_records}
    _bound_names = {str(k) for k in _provenance}
    flagged: List[dict] = []
    if verbs:
        _kept: List[dict] = []
        for _cv in verbs:
            _one, _f = filter_verbs_by_arity(
                [_cv], turn_is_set_shaped(instance_id, _cv, _bound_names),
            )
            _kept.extend(_one)
            flagged.extend(_f)
        verbs = _kept

    truth = next((cv for cv in (verbs or []) if cv.get("verb_iri") == verb), None)
    if truth is None:
        # The ask's verb is no longer eligible — revoked, retired, re-primed, or this picker
        # has a different persona from the asker. Recomputing is the correct answer.
        _stage(STAGE_VERIFYING, "failed")
        return DirectOutcome(FALL_BACK, f"verb {verb} no longer compatible with {subject}")

    _stage(STAGE_VERIFYING, "completed")
    predicate = predicate_from_compat_record(truth)
    if truth.get("needs_instance"):
        predicate["needs_instance"] = True
    # NO CLASSIFIER RAN, so there is no classifier confidence. Reporting a fabricated
    # 0.9-ish score would be the worse lie; the verb was carried from a decision a person
    # acted on and re-confirmed against the compat-walk one line above.
    predicate["score"] = 1.0

    # ── THE RECORD MUST SAY WHAT HAPPENED ───────────────────────────────────────────────
    #
    # The gate above reads the bound slots; without this the RECORD still would not, and both
    # record sites below write `instance_id`. A turn that bound `program_id` from an offered
    # menu would project `instance_resolved: false` with an empty identifier — a resolved turn
    # reporting as unresolved, which is self-consistent and false and therefore invisible to
    # any consistency check between those two fields (R-056).
    #
    # GATED ON PROVENANCE, NOT SHAPE. This field reaches the generalist fallback as
    # `resolved_instance_id` and Engine A does NOT re-resolve it, so only a value a validator
    # has already seen may be promoted: `picked` (a menu this system enumerated) and `filled`
    # (the slot filler, resolving against the graph). A caller-`supplied` id is REFUSED —
    # promoting it would have an engine act on an unchecked caller string. `spoken` is excluded
    # pending a ruling. Every source carries its reason in NON_PROMOTABLE_SLOT_SOURCES.
    if not instance_id:
        _promoted = promotable_instance_from_slots(truth, _provenance)
        if _promoted:
            instance_id = _promoted[0]
            logger.info(
                "instance_promoted verb_iri=%s slot=%s source=%s - the record now reports "
                "the instance this turn bound", verb, _promoted[1], _promoted[2],
            )

    # ── 3. SLOTS. Validated against the menu that offered them, not splatted ────────────
    _declared = predicate.get("slots") or []

    # ── THE CHAIN'S ALREADY-ANSWERED SLOTS ARE THE BASE LAYER ───────────────────────────
    #
    # MEASURED 2026-09-12 by invincible-agent-81: a two-slot verb took FOUR hops —
    # 1m15 → 1m42 → 2m07 → 2m34 — against 1m16 in a single hop when both values were in the
    # question, and every hop took the full path rather than this 535ms one. The cause was
    # that each turn carried ONLY its own answer, so a slot answered at hop 1 was absent by
    # hop 3 and got asked again.
    #
    # THIS TURN'S ANSWER WINS. A person who answers the same slot twice meant the second
    # answer; the chain is a floor, not an override.
    #
    # CARRYING A PICK FORWARD DOES NOT LAUNDER IT PAST THE MENU CHECK, and the reason is the
    # recorded SOURCE rather than trust. A slot bound as `picked` was validated against the
    # menu AT THE HOP THAT BOUND IT — `validate_bound_slots` ran then, against the menu that
    # existed then. Re-validating at hop 3 would re-refuse a pick whose menu has since become
    # `too_many`, punishing the user for answering. What must never happen is a pick arriving
    # with NO hop that validated it, which is why `_accumulated_slots` refuses any entry whose
    # source it does not recognise instead of defaulting it.
    #
    # UNDECLARED SLOTS ARE NOT FILTERED HERE. `accept_slots` below is the one site that
    # projects onto the declaration, and it already returns a Refusal per dropped slot which
    # reaches the routing record. Adding a filter here would be a second copy of that rule —
    # the same defect as three engines with three behaviours, one layer up.
    _chain = {k: v.get("value") for k, v in (chain_slots or {}).items() if isinstance(v, dict)}
    _supplied = {**_chain, **dict(bound_slots or {})}

    # ── WHERE EACH VALUE CAME FROM, tracked alongside the merge that produces it ────────
    #
    # Built here because this is where the layers are still distinguishable: one line later
    # `_supplied` is a flat dict and the provenance is unrecoverable. An inherited slot keeps
    # the source it was BOUND with — re-labelling it by the hop that carried it would turn a
    # caller-supplied id into a pick after one hop, which is the exact laundering the split
    # exists to prevent.
    _sources: Dict[str, str] = {
        k: str(v.get("source") or "")
        for k, v in (chain_slots or {}).items() if isinstance(v, dict)
    }
    _sources.update({k: SLOT_SOURCE_PICKED for k in dict(bound_slots or {})})

    # ── THE SPOKEN ANSWER IS AN ANSWER, and this path was DROPPING IT ───────────────────
    #
    # MEASURED 2026-09-08 23:34. `spoken_answer` was a parameter this function accepted and
    # never read — it appeared exactly once in the file, in the signature. So a person who
    # answered an ask by TYPING the value got `bound_slots={}`, the disposition correctly
    # said "slot lot unfilled", and the turn fell back to the run — which filled it via
    # `/fill_slots` and answered in 24 seconds. The fast path was structurally incapable of
    # ever answering the commonest pick there is.
    #
    # MY SEAL COULD NOT SEE IT: every test in the file passed `spoken_answer=""`. An unused
    # parameter whose fixture is always empty is invisible to any number of green tests, and
    # this one had thirty-four.
    #
    # EXACTLY ONE UNFILLED MANDATORY SLOT, OR NOTHING. With one, the ask asked for that slot
    # and the answer is its value — no inference, and `accept_slots` still type-checks it, so
    # a spoken "four" is REFUSED rather than guessed at. With two or more there is a genuine
    # ambiguity that `/fill_slots` resolves with a model; assigning here would be a coin
    # toss dressed as a fast path, so it falls back and the run does it properly.
    if spoken_answer:
        _unfilled = [
            str(dcl.get("name") or "")
            for dcl in mandatory_slots(_declared)
            if str(dcl.get("name") or "") and str(dcl.get("name")) not in _supplied
        ]
        if len(_unfilled) == 1:
            _supplied[_unfilled[0]] = spoken_answer
            # TYPED, WITH NO MENU BEHIND IT. Not `picked`: nothing enumerated this value, so
            # it is not promotable to a resolved instance until a resolver has seen it.
            _sources[_unfilled[0]] = SLOT_SOURCE_SPOKEN

    acceptance = accept_slots(_supplied, _declared, _sources)
    params = dict(getattr(acceptance, "params", {}) or {})
    refusals = [
        {"name": r.name, "reason": r.reason, "spoken": r.spoken}
        for r in (getattr(acceptance, "refusals", []) or [])
    ]

    # ── 3b. THE DISPOSITION. `route | ask | abstain`, THE SAME RULE THE RUN USES ────────
    #
    # THIS WAS MISSING AND IT COST A LIVE PICK (measured 2026-09-08, 23:05). The run calls
    # `decide_disposition` FIRST and the arity precondition second; the direct path had only
    # the second, which is strictly narrower. `arity_for` derives "single" from a slot that
    # is both REQUIRED and a REFERENT, so `needs_instance` never fires for a slot that is
    # merely required — `cost_category_breakdown`'s `lot` is exactly that. The fast path
    # dispatched with `params={}` and the engine answered "Request Refused — Missing Slot:
    # lot", which is the 400-instead-of-an-ask this repo removed a month ago, reintroduced
    # by a fast path that skipped the layer that removed it.
    #
    # I READ THE ARITY GATE'S DOCSTRING AS THE MECHANISM. It says a kept single-arity verb
    # "reaches `decide_disposition` with an unfilled mandatory referent, which is an ASK" —
    # true, and it describes the gate as a FLAG whose decision is made elsewhere. Carrying
    # the flag without its decider was reading half a sentence.
    #
    # `enumerate_class=None` IS CORRECT HERE AND NOT A SHORTCUT. This path does not build
    # the menu — an `ask` falls back to the run, which has the real enumerator — so all it
    # needs to know is THAT an ask is owed. None is reported as `no_provider`, never as
    # silence, which is the contract that makes passing it honest.
    disposition = decide_disposition(
        accepted=params,
        declared=_declared,
        resolution=getattr(acceptance, "resolution", {}) or {},
        enumerate_class=None,
    )

    # ── THE RE-ASK GUARD. A chain that asks for what it already holds is a DEFECT ────────
    #
    # Not a slow path to tolerate: asking a person for a value they already gave this chain
    # is the loop made visible, and it is the shape a user experiences as the system not
    # listening. The measured case reached FOUR hops on a two-slot verb; it should have
    # stopped at three with a reason.
    #
    # THIS FIRES ONLY WHEN THE CHAIN HOLDS THE SLOT AND THE DISPOSITION STILL ASKS FOR IT,
    # which means the value was carried in and then REJECTED — by the declaration, by a type
    # check, or by the menu. That is not the same as never having it, and the difference is
    # the whole diagnostic: a re-ask after a rejection is a contract problem between the
    # chain and the verb, and re-asking hides it behind a question.
    #
    # It REPORTS rather than refuses the turn. A refusal here would replace a slow answer
    # with no answer, and the user did nothing wrong — the record is what the next reader
    # needs, and `decide_disposition` keeps its say.
    # `Disposition.slot` is SINGULAR — one ask asks about one slot (slot_disposition.py:159).
    # The first draft read `.slots`, a field that does not exist, and `getattr` would have
    # returned None forever: a guard that cannot fire, written into the commit that adds a
    # guard. Read off the NamedTuple rather than assumed.
    # REPORTED INTO THE ROUTING RECORD, NOT INTO A LOG. This module deliberately carries no
    # logger — it takes `post` and `on_stage` and stays dependency-light — and the record is
    # the better home regardless: the hop that bound the slot ends up in the artifact a reader
    # opens, rather than in a line nobody greps for.
    _asked_slot = str(disposition.slot or "")
    if _asked_slot and _asked_slot in _chain and disposition.action != _ROUTE:
        _rec = (chain_slots or {}).get(_asked_slot) or {}
        refusals.append({
            "name": _asked_slot,
            # NAMES THE HOP, which is the whole diagnostic. "Asked again" is a symptom;
            # "bound at hop 1 by a pick and asked again at hop 3" says where to look.
            "reason": (
                f"re_ask_of_bound_slot: bound at hop {_rec.get('hop')} "
                f"(source={_rec.get('source')}, artifact={_rec.get('artifact_id')}); "
                f"disposition says {disposition.reason or 'unfilled'}"
            ),
            "spoken": str(_rec.get("value") or ""),
        })

    # ONE BUILDER, TWO EXECUTION SHAPES. The content comes from
    # `iagent_pure.routing_record` — the same function the supervisor's op calls — and only
    # the envelope differs. These were two hand-written mappings until 2026-09-08, sealed to
    # agree by an AST diff; that seal found THREE fields missing here on the day it was
    # written, including `route_status` on the graph trace, which is the key
    # `_primary_graph_trace_mat` selects by. A shared builder makes the diff unnecessary.
    routing_mat = materialization(**build_routing_record(
        status="matched",
        subject_uri=subject,
        # NO CLASSIFIER RAN, so there is no classifier confidence. A fabricated 0.9-ish
        # score would be the worse lie: the verb was carried from a decision a person acted
        # on and re-confirmed against the compat-walk a few lines above.
        subject_confidence=1.0,
        subject_instance_id=instance_id,
        subject_instance_label=pre_resolved.get("subject_instance_label") or "",
        verb_iri=verb,
        verb_confidence=1.0,
        classify_called=False,
        candidate_count=len(verbs or []),
        subject_candidates=[],
        fallback_reason="",
        eligibility_excluded=_excluded(flagged),
        acting_persona=acting_persona,
        acting_domains=list(entitled_domains or []),
        # ONE TASK, so the sub-query IS the user's phrase. Never composed here: the rewrite
        # fold exists so what the router records stays byte-equal to what the person asked.
        sub_query=user_query,
        predicate=predicate,
    ))
    graph_trace_mat = materialization(**build_graph_trace_record(
        status="matched",
        subject_uri=subject,
        picked_verb_iri=verb,
        compatible_verbs=list(verbs or []),
    ))

    # ── 4. THE DISPOSITION DECIDES, before any dispatch ─────────────────────────────────
    if disposition.action != _ROUTE:
        # AN ASK OR AN ABSTAIN IS NOT THIS PATH'S TO ANSWER. Both need the menu the
        # supervisor builds, so both hand the turn back — correct and slow rather than fast
        # and wrong. Reported with the SLOT and the disposition's own reason, because
        # "needs a slot" and "there is no such thing" send a reader to different places.
        # THE REFUSAL OUTRANKS "UNFILLED" WHEN THERE IS ONE. Both arrive with the slot
        # missing from `accepted`, and the disposition cannot tell them apart — it sees only
        # what survived. "unfilled" for a slot the person ANSWERED and that was REJECTED
        # sends a reader to look for a missing answer they already gave, which is the same
        # plausible-but-wrong reason as `classify_called` reporting false for a classifier
        # that ran.
        _refused = next(
            (r for r in refusals if r["name"] == disposition.slot), None
        )
        _why = (
            f"slot refused: {_refused['reason']}" if _refused
            else f"{disposition.action}: slot {disposition.slot or '?'} "
                 f"({disposition.reason or 'unfilled'})"
        )
        return DirectOutcome(
            ASK if disposition.action == _ASK else ABSTAIN,
            _why,
            routing_mat=routing_mat, graph_trace_mat=graph_trace_mat,
            predicate=predicate, refusals=refusals,
            # WHAT WAS ACCEPTED, even though an ask is still owed. Left empty at first, and
            # a mutation walked through the gap: a test asserting "no value was bound when
            # two slots were candidates" could not fail, because this field was `{}` on
            # every ask regardless. A record that reports nothing accepted whenever it asks
            # cannot distinguish "asked with nothing bound" from "asked with one of two
            # bound", and those have different follow-up questions.
            accepted_params=params,
        )

    # ── 4b. THE ARITY PRECONDITION, the half of the old gate that must survive ──────────
    # A single-asset verb whose instance was never named must ASK, never dispatch. This is
    # the case that made the ask fire in the first place, so a pick that lands back here is
    # a second ask — the one-option-menu shape — not an error.
    if predicate.get("needs_instance") and not params:
        # THE REASON MUST NAME WHAT ACTUALLY HAPPENED. Both of these arrive here with empty
        # params and they are different events:
        #
        #   nothing was supplied      -> the ask has not been answered yet
        #   what was supplied was REFUSED -> it was answered, and rejected
        #
        # Reporting `needs_instance` for the second is a plausible reason that is not the
        # real one, and it sends a reader to look for a missing answer they already gave.
        # Same family as `classify_called` reporting false for a classifier that ran.
        _reason = (
            f"slot refused: {refusals[0]['reason']}" if refusals else "needs_instance"
        )
        return DirectOutcome(
            ASK, _reason, routing_mat=routing_mat,
            graph_trace_mat=graph_trace_mat, predicate=predicate, refusals=refusals,
        )

    if getattr(acceptance, "unsourced", ()):
        # A BINDING WITH NO PROVENANCE IS A HOLE IN THE CHAIN, not a detail. It will not be
        # carried forward, so the next hop re-asks a slot this one answered.
        logger.warning(
            "accepted slot(s) %s carry NO source — they will not be carried to the next hop",
            list(acceptance.unsourced),
        )
    slots_mat = materialization(
        verb_iri=verb,
        disposition="route",
        accepted_slots=_json(params),
        # THE FIELD THAT WAS READ AND NEVER WRITTEN. Without it `_accumulated_slots` returns
        # {} for every chain, and the gate's bound-slot read plus the instance promotion are
        # both inert while their seals stay green (R-057).
        bound_slot_sources=_json(getattr(acceptance, "bound_slot_sources", {}) or {}),
        refused_slots=_json(refusals),
        slot_resolution=_json(getattr(acceptance, "resolution", {}) or {}),
        subject_uri=subject,
        subject_instance_id=instance_id or None,
        subject_instance_label=pre_resolved.get("subject_instance_label") or None,
        owner_persona=predicate.get("owner_persona") or "",
    )

    # ── 5. DISPATCH ─────────────────────────────────────────────────────────────────────
    endpoint = predicate.get("endpoint") or ""
    if not endpoint:
        return DirectOutcome(FALL_BACK, f"verb {verb} has no endpoint")
    _stage(STAGE_CALLING, "started")
    # THE BODY IS NAMED ONCE AND SENT ONCE. Built here rather than inline so the failure record
    # below carries THE REQUEST THAT WAS ACTUALLY MADE, not a reconstruction of it. Recovering
    # artifact-2-1789439072125's cause needed a hand-rebuilt body replayed against the pod, and
    # then a second read of both sides to trust the reconstruction — two reads because the one
    # thing that would have settled it in one was never written down.
    # `thread_id` TRAVELS ON EVERY DISPATCH, not only the ones known to be stateful.
    # Scoping it to endpoints matching "/graphs/" would be a URL-SHAPE PROXY for "does this
    # row checkpoint" - the same substitution that had `_repo_root` test for a checkout
    # shape instead of for the files it actually needed. The ROW declares whether it needs
    # a thread and the host enforces that; this side supplies the identity and lets the
    # declaration decide.
    #
    # Safe for engines that do not want it: no engine request model in this repo sets
    # `extra="forbid"` (checked across agent_fleet/ and src/), so an unrecognised key is
    # ignored rather than answered with the 422 this line exists to prevent.
    _request_body = {"query": user_query, "params": params, "thread_id": run_id}
    try:
        resp = _post(
            endpoint,
            json=_request_body,
            headers=headers or None,
            timeout=engine_timeout,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        # A TYPED FAILURE, not a fall-back. The verb was right and the engine did not answer;
        # re-running the whole thing through Dagster would call the same engine again and
        # produce the same failure a further twenty seconds later.
        #
        # ── THE CAUSE IS CAPTURED, NOT JUST THE EXCEPTION'S str() ────────────────────────────
        #
        # `{exc}` on an HTTPError is "422 Client Error: ... for url: ..." — the STATUS and the
        # URL, and none of the BODY. The body is where the answer is: measured on
        # artifact-2-1789439072125, the engine replied
        # `{"loc":["body","fn"],"msg":"Field required"}` and the artifact recorded no cause at
        # all, so reconstructing it took a replay against the live pod. The refusal was built to
        # NAME THE ARGUMENT and the naming was thrown away one layer up.
        _cause: Dict[str, Any] = {
            "exception": type(exc).__name__,
            "message": str(exc)[:600],
            # WHAT WE SENT, beside what came back. A 422 naming a field is only actionable
            # against the body that omitted it — "missing `fn`" and the body that had no `fn`
            # are one fact in two halves, and either alone still needs the other fetched.
            "endpoint": str(endpoint),
            "request_body": _request_body,
        }
        _r = getattr(exc, "response", None)
        if _r is not None:
            # Bounded: an engine that returns a page of HTML must not push the verb and the gate
            # out of the record this exists to keep readable.
            _cause["status_code"] = getattr(_r, "status_code", None)
            try:
                _cause["body"] = _r.text[:1200]
            except Exception:  # noqa: BLE001
                _cause["body"] = "<unreadable>"
        _stage(STAGE_CALLING, "failed")
        return DirectOutcome(
            ABSTAIN, f"engine did not answer: {type(exc).__name__}: {exc}",
            routing_mat=routing_mat, graph_trace_mat=graph_trace_mat,
            slots_mat=slots_mat, predicate=predicate, accepted_params=params,
            refusals=refusals, failure_cause=_cause,
        )

    _stage(STAGE_CALLING, "completed")
    return DirectOutcome(
        ROUTED, "", routing_mat=routing_mat, graph_trace_mat=graph_trace_mat,
        slots_mat=slots_mat, engine_response=body, predicate=predicate,
        accepted_params=params, refusals=refusals,
    )


# ── helpers ─────────────────────────────────────────────────────────────────

def _json(value: Any) -> str:
    import json
    return json.dumps(value, default=str)


def _excluded(flagged: List[dict]) -> List[dict]:
    """The arity gate's disposals, as a LIST. The record builder does the encoding —
    handing it a pre-encoded string would double-encode it into a quoted blob."""
    return ([
        {"uri": str(v.get("verb_iri") or ""), "gate": "arity",
         "reason": "needs_instance", "disposal": "flagged"}
        for v in flagged
    ])


# `_provider_from_endpoint` MOVED to iagent_pure.routing_record. It was a display-name
# fallback that only this route applied, which made the fast path and the slow path
# disagree about WHO answered the identical question. It now runs for both.
