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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from iagent.verb_lookup import find_compatible_verbs
from iagent_pure.routing_record import (
    graph_trace_record as build_graph_trace_record,
    routing_record as build_routing_record,
)
from iagent_pure.verb_eligibility import (
    filter_verbs_by_arity,
    predicate_from_compat_record,
)

__all__ = [
    "DirectOutcome",
    "ROUTED", "ASK", "ABSTAIN", "FALL_BACK",
    "STAGE_VERIFYING", "STAGE_CALLING", "STAGE_RENDERING", "DISPATCH_STAGES",
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
    spoken_answer: str,
    user_query: str,
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
    flagged: List[dict] = []
    if verbs:
        verbs, flagged = filter_verbs_by_arity(verbs, not instance_id)

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

    # ── 3. SLOTS. Validated against the menu that offered them, not splatted ────────────
    acceptance = accept_slots(dict(bound_slots or {}), predicate.get("slots") or [])
    params = dict(getattr(acceptance, "params", {}) or {})
    refusals = [
        {"name": r.name, "reason": r.reason, "spoken": r.spoken}
        for r in (getattr(acceptance, "refusals", []) or [])
    ]

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

    # ── 4. THE ARITY PRECONDITION, before any dispatch ──────────────────────────────────
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

    slots_mat = materialization(
        verb_iri=verb,
        disposition="route",
        accepted_slots=_json(params),
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
    try:
        resp = _post(
            endpoint,
            json={"query": user_query, "params": params},
            headers=headers or None,
            timeout=engine_timeout,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        # A TYPED FAILURE, not a fall-back. The verb was right and the engine did not answer;
        # re-running the whole thing through Dagster would call the same engine again and
        # produce the same failure a further twenty seconds later.
        _stage(STAGE_CALLING, "failed")
        return DirectOutcome(
            ABSTAIN, f"engine did not answer: {type(exc).__name__}: {exc}",
            routing_mat=routing_mat, graph_trace_mat=graph_trace_mat,
            slots_mat=slots_mat, predicate=predicate, accepted_params=params,
            refusals=refusals,
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
