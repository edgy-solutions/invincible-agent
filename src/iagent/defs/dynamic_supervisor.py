"""
Phase 2: Dynamic Supervisor & Fan-Out

Dagster job that takes a complex multi-domain query, asks Engine O to decompose
it into Persona-specific sub-tasks, fans those out concurrently to Engine E 
(Neo4j Graph Expert), and synthesizes the results.
"""

import os
import json
import requests
import sys
import logging
from pathlib import Path
from typing import List, Dict, Any, NamedTuple, Optional

logger = logging.getLogger("iagent.supervisor")

# ---------------------------------------------------------------------------
# Service Discovery — defaults to K8s internal DNS, overridden via env
# ---------------------------------------------------------------------------
ONTOLOGY_SVC_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
NEO4J_EXPERT_SVC_URL = os.getenv("NEO4J_EXPERT_SVC_URL", "http://iagent-engine-e:8086")
DATAHUB_WRAPPER_URL = os.getenv("DATAHUB_WRAPPER_URL", "http://iagent-engine-d:8085")
LANGGRAPH_SUPPORT_SVC_URL = os.getenv("LANGGRAPH_SUPPORT_SVC_URL", "http://iagent-langgraph-support:8082")
PRESENTATION_AGENT_SVC_URL = os.getenv("PRESENTATION_AGENT_SVC_URL", "http://iagent-engine-f:8087")
RESTATE_ANALYST_URL = os.getenv("RESTATE_ANALYST_URL", "http://iagent-engine-a:8081")
DATA_ANALYST_URL = os.getenv("DATA_ANALYST_URL", "http://iagent-data-analyst:8089")

# ---------------------------------------------------------------------------
# Add baml_shared to Python path so we can import the generated client
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
if str(_BAML_CLIENT_PATH) not in sys.path:
    sys.path.insert(0, str(_BAML_CLIENT_PATH))

# Note: the supervisor no longer imports the BAML client. The /resolve and
# /classify_predicate endpoints on Engine O handle all LLM calls now; the
# supervisor just orchestrates the HTTP requests. The sys.path hack above
# stays only because other modules in this defs/ directory may still need
# baml_client and rely on this entry being present.

from dagster import (
    DynamicOut,
    DynamicOutput,
    Failure,
    In,
    Nothing,
    Out,
    job,
    op,
    Config,
    Output,
    MetadataValue,
    AssetMaterialization,
    in_process_executor,
    multiprocess_executor,
)


#: Default fallback score threshold per ADR-0008. Operator-tunable via the
#: ``PREDICATE_FALLBACK_SCORE_THRESHOLD`` env var; the supervisor's
#: SupervisorQueryConfig uses this as its default so a Dagster run can
#: also override per-launch from the gateway if needed.
_FALLBACK_SCORE_THRESHOLD_DEFAULT = float(
    os.getenv("PREDICATE_FALLBACK_SCORE_THRESHOLD", "0.40")
)

class SupervisorQueryConfig(Config):
    """Configuration for the supervisor job.

    Per ADR-0009 Step F'.3 / F'.6, the routing-relevant fields are:
      * ``user_persona`` — caller-side persona from JWT (auth.User.persona).
        Drives UI prefs and is the answerer-persona fallback when the
        matched predicate is persona-agnostic.
      * ``entitled_domains`` — caller's domain scope from JWT. Scopes the
        predicate-graph lookup in ``execute_subtask``.
      * ``entity_refs`` — output of ExtractIntent, available to subtasks
        for /resolve calls when subject grounding is required.

    Per ADR-0008, the fallback policy is parameterized by:
      * ``predicate_fallback_score_threshold`` — top hit must score at or
        above this to be used as-is; otherwise the supervisor falls back
        to Engine A with reason="low_confidence". Defaults to the
        ``PREDICATE_FALLBACK_SCORE_THRESHOLD`` env var (0.40 default).

    Routing itself uses each subtask's ``sub_query`` as the NL hint into
    Engine O's /search_predicates (Weaviate hybrid). Step F'.6 removed the
    LLM-extracted ``candidate_verb`` — vector search runs against the raw
    NL directly, so an intermediate verb token would just lose signal.

    Legacy fields (``persona``, ``domain``, ``candidate_verb``) are accepted
    for backward compatibility — older Dagster runs may have them in their
    serialized config — but ``execute_subtask`` doesn't branch on them.
    """
    user_query: str
    thread_id: str
    persona: str = "MECHANIC"  # legacy, prefer user_persona
    domain: str = "MAINTENANCE"  # legacy, no longer routes
    task_plan_json: str = ""  # Optional pre-computed plan from BFF
    user_id: str = "default_testing_user"
    # ADR-0025 hop 2: caller's entitlement key (email — what the seeded
    # Topaz `user` objects + policy/users.yaml key on; NOT the sub in
    # user_id). Forwarded to Engine A's generalist fallback so it can hand
    # it to Engine D's query_metadata Topaz can_view ask. Empty → denied.
    user_email: str = ""
    # ADR-0009 Step F'.2 / F'.3 additions:
    # ADR-0026 step 6: honest-empty. None when the caller has zero
    # Topaz entitlements — NOT a fabricated MECHANIC default. Flows
    # through as null so produced_for stays honest; the answerer voice
    # (owner_persona / engine-side) still defaults for the RESPONSE
    # shape, but the CALLER persona recorded in provenance stays None.
    user_persona: Optional[str] = None
    # ADR-0017 amendment: the calling frontend's registration key, threaded so Engine F can
    # resolve THIS caller's menu at decision time. Empty -> Engine F falls back to its
    # global capability table (the pre-seam behaviour), never to a silently smaller menu.
    frontend_id: str = ""
    entitled_domains: List[str] = []
    entity_refs: List[str] = []
    # THE SPOKEN SLOTS, argument name -> value, forwarded from /route_intent.
    #
    # NOT the same thing as `entity_refs` one line up, and the difference is the whole
    # finding: entity_refs are untyped VALUES ("FY26-Q4", "Northgate") carrying no argument
    # name, which is why the supervisor can hand them to /resolve but cannot call a verb
    # with them. These carry the name, so they can be splatted - after the acceptance
    # filter, never before.
    #
    # Empty on every request until the slot-filler is called, and empty is exactly today's
    # behaviour, which is what makes this landable ahead of the model work.
    slots: Dict[str, Any] = {}
    #: SLOTS A USER PICKED FROM AN ASK — kept SEPARATE from `slots`, not merged upstream,
    #: because the two have different provenance and earn different treatment. `slots` is what
    #: a caller supplied or the filler extracted; `bound_slots` is what a person chose from a
    #: menu this system offered, and only the second can be validated against that menu.
    #:
    #: Merging them at the gateway would have made the distinction unrecoverable here, and the
    #: consequence is not cosmetic: an API caller may legitimately supply an id for a class
    #: whose menu was `too_many` (no menu was ever offered), while a PICK for that same slot
    #: must be refused precisely because nothing was offered to pick from. One field cannot
    #: carry both rules.
    bound_slots: Dict[str, Any] = {}
    # Accepted for legacy-config compatibility (Step F'.6 stopped using it).
    candidate_verb: str = ""
    # ADR-0008 fallback policy (ADR-0018 simplified: single threshold
    # against the LLM's confidence from /classify_predicate, replacing the
    # BM25-era yellow-zone band + VerifyVerbChoice gate).
    predicate_fallback_score_threshold: float = _FALLBACK_SCORE_THRESHOLD_DEFAULT
    # Telemetry (ADR-0038): the request's trace + session ids, threaded from the BFF's
    # runConfig so execute_subtask can forward them to Engine A's /analyze — X-Trace-Id
    # unifies the conversation's spans under one trace, X-Session-Id groups the sitting.
    # Empty for older serialized runs / direct callers.
    trace_id: str = ""
    session_id: str = ""


@op(out=DynamicOut(Dict[str, Any]))
def create_task_plan(config: SupervisorQueryConfig):
    """
    Calls Engine O (Ontology Reasoner) to decompose a complex query into a
    SupervisorTaskPlan containing persona-specific sub-tasks.
    Yields each sub-task as a DynamicOutput for downstream fan-out.
    """
    # 1. Ask Engine O for the plan, or use the provided one
    if config.task_plan_json:
        logger.info("Using pre-computed task plan from BFF")
        try:
            plan = json.loads(config.task_plan_json)
        except Exception as e:
            logger.error(f"Failed to parse task_plan_json: {e}")
            raise e
    else:
        logger.info("Calling Engine O for task planning")
        # svc:supervisor via the helper THIS MODULE ALREADY DEFINES and already applies at the two
        # specialist legs. This site was the odd one out — and the reason it was missed is worth
        # keeping: it sits in the `else:` branch, while the `try` a scanner finds nearby guards the
        # `if config.task_plan_json:` branch above. Proximity is not enclosure.
        response = requests.post(
            f"{ONTOLOGY_SVC_URL}/plan",
            json={
                "query": config.user_query,
                "domain": config.domain
            },
            timeout=300,
            headers=_telemetry_headers(config),
        )
        response.raise_for_status()
        plan = response.json()

    # 2. Extract personas and broadcast intermediate roster + concepts
    tasks = plan.get("tasks", [])
    personas = [task.get("target_persona") for task in tasks if task.get("target_persona")]
    concepts = plan.get("extracted_concepts", [])
    
    yield AssetMaterialization(
        asset_key=["active_agent_roster"],
        metadata={
            "personas": MetadataValue.text(json.dumps(personas)),
            "extracted_concepts": MetadataValue.text(json.dumps(concepts))
        }
    )

    # 3. Fan-out: yield each task dynamically
    detected_domain = plan.get("domain") or config.domain
    logger.info(f"Fanning out tasks for domain: {detected_domain}")

    for idx, task in enumerate(tasks):
        # Inject the domain context so execute_subtask routes correctly
        task["domain"] = detected_domain
        logger.info(f"Yielding task {idx} ({task.get('target_persona')}) for domain {detected_domain}")
        
        # We must provide a valid mapping_key for each dynamic output
        yield DynamicOutput(
            value=task,
            mapping_key=f"task_{idx}"
        )


def get_datahub_context(datahub_wrapper_url: str) -> str:
    """Fetch the dynamic schema map from Engine D."""
    try:
        response = requests.get(f"{datahub_wrapper_url}/dynamic_context", timeout=3.0)
        response.raise_for_status()
        return response.json().get("schema_map", "")
    except Exception as e:
        logger.warning(f"Could not fetch DataHub schema map: {e}")
        return ""

# ADR-0008 routing outcomes. Distinguishing these three is the load-bearing
# decision: "no_match" routes to the LLM fallback (registry coverage gap is
# something an LLM can attempt), while "infra_error" aborts the subtask
# (masking an infrastructure outage by routing through Engine A would hide
# the very signal ops needs to fix it).
_ROUTING_MATCHED = "matched"
_ROUTING_NO_MATCH = "no_match"
_ROUTING_INFRA_ERROR = "infra_error"


def _resolve_subject(
    context,
    user_query: str,
    domain: str,
    entity_refs: List[str] | None = None,
    domains: List[str] | None = None,
    user_email: str = "",
) -> tuple[str, float, str, str, list, str | None, str]:
    """Ask Engine O's /resolve for the subject ontology class.

    /resolve does vector-recall (Weaviate hybrid over OntologyClass) +
    LLM-precision (ClassifyDomainIntent via TypeBuilder dynamic enum).
    Returns ``(subject_uri, confidence, reasoning, instance_id)``. On
    failure or UNKNOWN return ``("UNKNOWN", 0.0, "<reason>", "")`` so
    the downstream predicate classifier still runs against the raw query.

    ``entity_refs`` are the named-entity tokens /route_intent's BAML
    ExtractIntent surfaced from the user's query. They're plumbed
    through to /resolve as the over-fire guard for the precedence-fix
    branch there: when Weaviate hybrid + SPARQL fallback BOTH return
    zero class candidates AND entity_refs is non-empty, /resolve fans
    them out to the registered mesh:resolveInstance providers BEFORE
    declaring UNKNOWN. Closes the [[recipe-v2-preemption-gap]] failure
    mode the 2026-06-25 "who owns customer 360" surface exposed:
    engine_d would have returned Customer 360 at score 1.0 if asked,
    but the phone book was gated on class recall succeeding first, so
    it never fired.

    Subject classification was the missing leg of SPO routing for years
    (ADR-0004 proposed it; ADR-0009 Step F'.6 simplified it away). With
    the predicate side now using the same vector-recall + LLM-precision
    pattern (/classify_predicate), restoring this call gives the LLM
    classifier real SPO context — it picks a verb that's a sensible
    operation ON THE RESOLVED SUBJECT, not just lexically adjacent to
    the query text.

    The 4th return value, ``instance_id``, is the URN of the resolved
    instance when /resolve's provenance fan-out succeeded (e.g. Engine D
    matched a catalog dataset, Engine E matched a maintenance instance,
    Engine E's DMC capability matched a data module). Empty string when
    no instance matched (``provenance.instance_resolved=false``) or
    when /resolve was unreachable.

    The instance_id is propagated downstream in the dispatch payload so
    execution-layer engines (specifically Engine DA's data fetch) query
    the SAME URN that /resolve produced, rather than fabricating one
    from training data or `dynamic_schema_map` context. The fabrication
    pathway was the bug this thread closes (see deploy checklist §4 and
    state doc 2026-06-16 Tier-3 fix entry).
    """
    try:
        payload: Dict[str, Any] = {
            "query": user_query,
            # `domain` retained for backward-compat with Engine O's
            # ResolveRequest. `domains` (list, NEW 2026-06-28) is the
            # query-driven fix: when populated, Engine O scopes the
            # OntologyClass pool to the UNION of these and lets the
            # LLM pick the best match across them. Routes by query
            # within the entitlement scope instead of locking to
            # entitled_domains[0]. See
            # [[failure-mode-pluralism-in-fixes]] for the
            # diagnose-each-mechanism rationale.
            "domain": domain or "MAINTENANCE",
        }
        if domains:
            payload["domains"] = list(domains)
        if entity_refs:
            payload["entity_refs"] = list(entity_refs)
        # ADR-0025 ontology-IRI namespace: thread the caller's entitlement key
        # (email) so Engine O's can_view candidate-filter can discriminate on the
        # subject. Empty is honest-absent → deny-by-default on compartmented
        # classes at the seam. Identity-reaches-enforcement-point prereq.
        if user_email:
            payload["user_email"] = user_email
        resp = requests.post(
            f"{ONTOLOGY_SVC_URL}/resolve",
            json=payload,
            # 15s was too tight under realistic engine-o load: BAML's
            # ClassifyDomainIntent runs ~5-10s, Recipe v2's
            # instance-resolution fan-out adds 3-5s for engine_d's
            # DataHub call, and a warm-but-busy engine-o can stack
            # these past 15s. Caught 2026-06-24 when an analytical
            # query timed out at this layer and got incorrectly
            # routed through ADR-0019 Contract B to the generalist
            # fallback — verb registry had the correct specialist
            # but never got consulted. 30s gives comfortable
            # headroom while still bounding the worst case well
            # under the supervisor's 1800s per-engine call ceiling.
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        context.log.warning(
            "resolve_subject failed for query=%r: %s — predicate classifier "
            "will see subject_uri=UNKNOWN",
            user_query, exc,
        )
        # 7-tuple: empty candidates on the unreachable path (no pool
        # was computed), abstention_reason=None (an infra reach failure
        # is NOT a structural instance-not-found), instance_label="" (no
        # instance resolved). Keeps arity uniform with the success path —
        # the caller unpacks 7.
        return ("UNKNOWN", 0.0, f"/resolve unreachable: {exc}", "", [], None, "")

    provenance = data.get("provenance") or {}
    return (
        str(data.get("resolved_uri") or "UNKNOWN"),
        float(data.get("confidence_score") or 0.0),
        str(data.get("reasoning") or ""),
        str(provenance.get("instance_id") or ""),
        # 2026-07-02 (decision-path visualizer Part 0): the full
        # subject-class candidate pool with scores — winner AND losers.
        # /resolve now returns this (previously computed + discarded).
        # Threaded into telemetry so the decision-path resolver stage
        # can render what lost and by how much.
        list(data.get("candidates") or []),
        # 2026-07-03 (abstention-gate arc): Engine O's STRUCTURAL gate
        # sets provenance.abstention_reason="instance_not_found" when the
        # query named a specific individual (form) the phone book was
        # asked about and genuinely doesn't know (fact). Surfaced here so
        # the UNKNOWN branch below distinguishes "you named X, no provider
        # knows it" (instance_not_found) from a plain unresolved subject
        # (subject_unknown) — and carries the actionable message
        # (already in `reasoning`) instead of a bare UNKNOWN.
        str(provenance.get("abstention_reason") or "") or None,
        # 2026-07-10 (answer-first instance headline): the FRIENDLY label
        # of the resolved instance (e.g. "Customer 360"), which the
        # resolver returns in provenance ALONGSIDE the URN but the
        # supervisor previously discarded at this tuple — a
        # [[resolution-discard-pattern]] instance. Threaded so the answer
        # summary can lead with the specific thing (instance · verb) not
        # the category (class · verb). Empty when no instance resolved
        # (set/type-level query) → summary correctly falls back to the
        # class label.
        str(provenance.get("instance_label") or ""),
    )


def _find_compatible_verbs(
    context,
    subject_uri: str,
    entitled_domains: List[str],
) -> tuple[list[dict] | None, str | None]:
    """ADR-0018 addendum (proper SPO). Ask Engine O which predicates can
    operate on this subject according to Neo4j (the compatibility
    reasoner). Returns ``(verbs, error_or_None)``.

    Empty list = no verb whose registered ``input_uri`` covers this
    subject's class chain (caller routes to generalist fallback).
    ``error`` is a non-fatal message (e.g., Neo4j hiccup) — the caller
    treats it as "couldn't check; fall back to unconstrained classifier".
    """
    if not subject_uri or subject_uri == "UNKNOWN":
        return [], None
    try:
        resp = requests.post(
            f"{ONTOLOGY_SVC_URL}/find_compatible_verbs",
            json={
                "subject_uri": subject_uri,
                "max_hops": 5,
                "entitled_domains": entitled_domains,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("verbs") or []), None
    except Exception as exc:
        context.log.warning(
            "_find_compatible_verbs failed for subject_uri=%s: %s — "
            "falling through to unconstrained predicate classification",
            subject_uri, exc,
        )
        return None, str(exc)


def _filter_verbs_by_arity(
    compatible_verbs: list[dict], query_is_set: bool
) -> tuple[list[dict], list[dict]]:
    """Structural arity gate — query-shape verb eligibility.

    When the query is SET-shaped (subject resolved to a CLASS, no specific
    instance), a single-asset verb cannot answer it. Remove verbs that
    POSITIVELY declare ``arity == "single"``; KEEP "set" / "any" / null
    (null = unclassified → never excluded, so an incomplete backfill never
    over-restricts). Only the set-query direction is gated (conservative);
    instance/single queries keep every verb. Returns ``(kept, dropped)``.

    PURE — no LLM, no network. That is the entire point: arity is decided
    structurally UPSTREAM of the classifier, so the LLM never gets to pick
    a wrong-arity verb (it was never a candidate). Same discipline as the
    domain scope already applied in ``find_compatible_verbs`` — a second
    structural constraint composing into (domain ∩ arity) eligibility.
    """
    if not query_is_set or not compatible_verbs:
        return compatible_verbs, []
    kept: list[dict] = []
    dropped: list[dict] = []
    for v in compatible_verbs:
        if str(v.get("arity") or "").lower() == "single":
            dropped.append(v)
        else:
            kept.append(v)
    return kept, dropped


def _filter_verbs_by_argument_fit(
    compatible_verbs: list[dict], available_args: set[str] | None
) -> tuple[list[dict], list[dict]]:
    """Structural ARGUMENT-FIT gate — the last term of the verb-eligibility
    intersection (domain ∩ arity ∩ argument-fit ∩ permission).

    A verb that POSITIVELY declares ``required_args`` (argument keys it cannot
    run without — e.g. filterByTag needs "tag") is ineligible for a query that
    does not PROVIDE those args: it was never a candidate, so the classifier can
    never pick a verb it can't satisfy. Drop a verb iff its ``required_args`` are
    a NON-empty set NOT ⊆ the query's ``available_args``. Verbs with empty/absent
    ``required_args`` are ALWAYS kept (unconstrained).

    CONSERVATIVE, exactly like the arity gate: ``available_args is None`` means
    "no typed-argument signal for this query" → NEVER exclude (return everything).
    So until (a) verbs declare ``required_args`` AND (b) the query surfaces a
    typed-arg set, this gate is INERT — it can only ever remove a verb we are
    CONFIDENT cannot be satisfied, never over-restrict on a missing signal (the
    same "null = never excluded, incomplete backfill never over-restricts"
    discipline the arity gate uses). PURE — no LLM, no network.

    ``available_args`` is the extension point: today the supervisor has only
    untyped ``entity_refs`` (values, not arg keys), so it passes ``None`` (inert).
    When a typed-argument extraction lands (arg-key → value), pass its key set
    here and the gate activates with zero change to this logic or its callers.
    """
    if available_args is None or not compatible_verbs:
        return compatible_verbs, []
    kept: list[dict] = []
    dropped: list[dict] = []
    for v in compatible_verbs:
        required = {str(a) for a in (v.get("required_args") or []) if str(a).strip()}
        if required and not required.issubset(available_args):
            dropped.append(v)
        else:
            kept.append(v)
    return kept, dropped


def _classify_route(
    context,
    user_query: str,
    entitled_domains: List[str],
    routing_domain: str,
    entity_refs: List[str] | None = None,
    user_email: str = "",
) -> tuple[str, Dict[str, Any] | None, dict]:
    """Three-stage SPO routing per ADR-0018 + ADR-0019: /resolve →
    /find_compatible_verbs → /classify_predicate.

    The middle step is the load-bearing addition (ADR-0018 addendum):
    Neo4j returns the verbs whose registered ``input_uri`` covers the
    resolved subject's class chain (via ``subClassOf*``).
    /classify_predicate is then constrained to that subset — the LLM
    cannot pick an incompatible (subject, verb) pair because the
    offending verb never enters its enum.

    ADR-0019 Contract B: when ``/resolve`` returns ``UNKNOWN`` the
    router short-circuits to ``NO_MATCH`` *immediately*, with no LLM
    call. The prior fallthrough-to-unconstrained-classification path
    is the verb-only regression shape that caused the trigger
    incident; with no subject grounding the only sound route is the
    Engine A generalist (ADR-0008). The structural defense is
    "the LLM is not asked to pick a verb for a subject the graph
    didn't recognize" — confirmed by the routing-fallback test that
    asserts ``classify_predicate`` was not called for the
    UNKNOWN-subject branch.

    Returns ``(status, predicate_or_none, telemetry_dict)``.
    """
    # `routing_domain` is the legacy single-string fallback Engine O
    # still accepts for backward-compat. `entitled_domains` is the
    # NEW (2026-06-28) query-driven path: Engine O scopes the
    # OntologyClass pool to the UNION of these and lets the LLM pick
    # across them. Without this, the resolver was locked to
    # entitled_domains[0] regardless of query, funneling every query
    # for a multi-entitlement user through the SAME domain. See
    # [[failure-mode-pluralism-in-fixes]] for the fix-sequencing
    # rationale (this is Bug A; PROV contamination is Bug B,
    # diagnosed separately).
    (
        subject_uri, subject_conf, subject_reason, subject_instance_id,
        subject_candidates, subject_abstention_reason, subject_instance_label,
    ) = _resolve_subject(
        context,
        user_query,
        routing_domain,
        entity_refs=entity_refs,
        domains=list(entitled_domains) if entitled_domains else None,
        user_email=user_email,
    )

    # ADR-0019 Contract B — UNKNOWN-subject short-circuit. No
    # /find_compatible_verbs (would be empty), no /classify_predicate
    # (would be unconstrained and could emit a confident wrong verb).
    # The honest answer is the generalist; route there directly.
    if subject_uri == "UNKNOWN":
        # Abstention-gate arc (2026-07-03): Engine O's structural gate may
        # have marked this UNKNOWN as an INSTANCE-NOT-FOUND — the query
        # named a specific individual (form) the phone book was asked
        # about and genuinely doesn't know (fact). That's a distinct,
        # closed-enum fallback_reason from a plain unresolved subject, and
        # it carries an ACTIONABLE message ("you named X; no provider
        # knows it") that Engine O already put in `subject_reason`. A bare
        # UNKNOWN would leave the user nowhere to go; honest-empty is only
        # honest if it says what to do.
        is_instance_not_found = subject_abstention_reason == "instance_not_found"
        _fb_reason = "instance_not_found" if is_instance_not_found else "subject_unknown"
        context.log.info(
            "routing_decision subject_uri=UNKNOWN subject_conf=%s "
            "fallback_reason=%s → generalist fallback (ADR-0019 Contract "
            "B: no LLM call without subject grounding)",
            subject_conf, _fb_reason,
        )
        return _ROUTING_NO_MATCH, None, {
            "subject_uri": "UNKNOWN",
            "subject_confidence": subject_conf,
            "subject_reasoning": subject_reason,
            "subject_candidates": subject_candidates,
            # Structured fallback reason (decision-path Part 0): the
            # subject didn't ground at all. Distinct from "grounded but
            # no verb", from "verbs exist but your domain scope excluded
            # them" (domain_scope_excluded, the deny primitive's data
            # shadow), and — new (abstention-gate arc) — from
            # "instance_not_found" (a NAMED individual the registry
            # doesn't know, decided structurally, not by LLM sampling).
            # See the fallback_reason enum vocabulary in the module
            # docstring — this is a closed-enum ADDITION, not a reuse.
            "fallback_reason": _fb_reason,
            "verb_iri": "UNKNOWN",
            "verb_confidence": 0.0,
            "verb_reasoning": (
                # Instance-not-found carries Engine O's actionable message
                # through verbatim; the generic UNKNOWN keeps the
                # ADR-0019 Contract-B rationale.
                subject_reason
                if is_instance_not_found
                else (
                    "ADR-0019 Contract B: /resolve returned UNKNOWN, so the "
                    "router short-circuits to the generalist without asking "
                    "the LLM to pick a verb. Confident specialist routing "
                    "without subject grounding is the regression shape "
                    "ADR-0019 deletes."
                )
            ),
            "candidate_verbs": [],
            "compatible_verb_iris": [],
        }

    compatible_verbs, find_err = _find_compatible_verbs(
        context, subject_uri, entitled_domains,
    )

    # ARITY GATE (query-shape eligibility, ADR-0008 follow-up). Query-arity
    # comes from the abstention arc's own signal: the subject resolved to a
    # CLASS with no specific instance (subject_instance_id empty) → a
    # SET/collection query → single-asset verbs cannot answer it. Remove
    # verbs that POSITIVELY declare arity="single" BEFORE the classifier
    # sees them, so a set-query can never resolve to a single-asset verb
    # (the `show me data about customers → describeAsset → assets:[]`
    # defect). Verbs with arity set/any/null are kept (null = unclassified
    # → never over-excluded during backfill). Runs only when subject !=
    # UNKNOWN (abstention already short-circuited nothing-resolved above),
    # so "no instance" here means class-only/set, NEVER abstention — the
    # two gates read the resolution signal consistently. Deterministic, no
    # LLM; composes with the domain scope into the (domain ∩ arity)
    # eligibility intersection the enforcement arc extends with permission.
    if compatible_verbs:
        query_is_set = not subject_instance_id
        compatible_verbs, _arity_dropped = _filter_verbs_by_arity(
            compatible_verbs, query_is_set,
        )
        if _arity_dropped:
            context.log.info(
                "arity_gate subject_uri=%s set_query=%s dropped %d single-asset "
                "verb(s) from candidacy: %s",
                subject_uri, query_is_set, len(_arity_dropped),
                [v.get("verb_iri") for v in _arity_dropped],
            )

        # ARGUMENT-FIT GATE — the last term of the eligibility intersection
        # (domain ∩ arity ∩ argument-fit ∩ permission). Drops verbs whose
        # POSITIVELY-declared required_args the query cannot supply. Composes
        # after arity, same pure-structural discipline.
        #
        # available_args is None TODAY (INERT — proven inert by the routing
        # fixtures): the supervisor has only untyped entity_refs (VALUES), and
        # resolving a value to a typed arg-key ("is this entity_ref a tag?")
        # needs a vocabulary (e.g. the DataHub tag-vocab) that arrives WITH the
        # concrete arg-requiring verb. That resolver is the PLUGGABLE piece — it
        # is NOT baked here as a naive entity_refs string-match (which would be
        # wrong once a real tag-verb registers). The filter takes an already-
        # resolved arg-KEY set; wiring the resolver later populates it with zero
        # change to this call or the filter. Until then: None → excludes nothing.
        available_args = None  # ← resolver (value→arg-key, needs vocab) plugs in here
        compatible_verbs, _argfit_dropped = _filter_verbs_by_argument_fit(
            compatible_verbs, available_args,
        )
        if _argfit_dropped:
            context.log.info(
                "argument_fit_gate subject_uri=%s dropped %d verb(s) lacking "
                "required args: %s",
                subject_uri, len(_argfit_dropped),
                [v.get("verb_iri") for v in _argfit_dropped],
            )

    # compatible_verbs is None on Neo4j error → fall through unconstrained.
    # Empty list with valid Neo4j = subject is genuinely unsupported.
    compatible_verb_iris = (
        [v.get("verb_iri") for v in compatible_verbs if v.get("verb_iri")]
        if compatible_verbs
        else []
    )

    # When the subject is resolved AND Neo4j returns ZERO compatible
    # verbs, that's a hard no-match: no engine in the registry can
    # operate on this subject's class chain. Route to generalist
    # fallback without burning an LLM call on /classify_predicate.
    if subject_uri != "UNKNOWN" and compatible_verbs is not None and not compatible_verbs:
        # Structured fallback reason (decision-path Part 0): distinguish
        # "no verb exists for this subject" from "verbs exist but the
        # caller's domain scope excluded them all" — the deny primitive's
        # data shadow (ADR-0025 amendment). We detect it cheaply: only on
        # this empty-fallback path (rare), re-ask Neo4j UNSCOPED. If the
        # unscoped compat-walk returns verbs the scoped one didn't, the
        # emptiness was caused by domain scoping, not by genuine
        # unsupportedness. This is the difference between a relevance-miss
        # (fallback is fine) and a scope-exclusion (which, once the deny
        # primitive lands, must NOT silently fall back).
        fb_reason = "no_compatible_verbs"
        if entitled_domains:
            unscoped_verbs, _unscoped_err = _find_compatible_verbs(
                context, subject_uri, entitled_domains=[],
            )
            if unscoped_verbs:
                fb_reason = "domain_scope_excluded"
                context.log.warning(
                    "routing_decision subject_uri=%s domain_scope_excluded: "
                    "%d verb(s) exist unscoped but entitled_domains=%s "
                    "excluded them all. This is the deny-primitive's data "
                    "shadow — relevance-scope exclusion masquerading as "
                    "no-match. (ADR-0025 amendment.)",
                    subject_uri, len(unscoped_verbs), entitled_domains,
                )
        context.log.info(
            "routing_decision subject_uri=%s subject_conf=%s "
            "fallback_reason=%s → generalist fallback",
            subject_uri, subject_conf, fb_reason,
        )
        return _ROUTING_NO_MATCH, None, {
            "subject_uri": subject_uri,
            "subject_confidence": subject_conf,
            "subject_reasoning": subject_reason,
            "subject_candidates": subject_candidates,
            "fallback_reason": fb_reason,
            "verb_iri": "UNKNOWN",
            "verb_confidence": 0.0,
            "verb_reasoning": (
                "Neo4j marks zero verbs as compatible with this subject "
                f"(fallback_reason={fb_reason})."
            ),
            "candidate_verbs": [],
            "neo4j_find_error": find_err,
        }

    try:
        resp = requests.post(
            f"{ONTOLOGY_SVC_URL}/classify_predicate",
            json={
                "query": user_query,
                "subject_uri": subject_uri,
                "subject_reasoning": subject_reason,
                "entitled_domains": entitled_domains,
                "domain": routing_domain or "MAINTENANCE",
                # ADR-0018 addendum: constrain the LLM to graph-
                # compatible verbs. Empty = unconstrained (Weaviate
                # hybrid as before).
                "compatible_verb_iris": compatible_verb_iris,
            },
            timeout=30,  # LLM call inside; longer than /search_predicates.
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        context.log.error(
            "classify_predicate infrastructure error for query=%r: %s",
            user_query, exc,
        )
        return _ROUTING_INFRA_ERROR, None, {
            "subject_uri": subject_uri,
            "subject_confidence": subject_conf,
            "subject_candidates": subject_candidates,
            "fallback_reason": "infra_error",
            "compatible_verb_iris": compatible_verb_iris,
            "error": str(exc),
        }

    verb_iri = str(data.get("resolved_verb_iri") or "UNKNOWN")
    verb_conf = float(data.get("confidence_score") or 0.0)
    verb_reason = str(data.get("reasoning") or "")
    predicate = data.get("predicate")
    candidates = list(data.get("candidate_verb_iris") or [])

    # Per-candidate semantic scores (Weaviate hybrid query→verb match) from
    # classify. Merge them into the compatible_verbs records by verb_iri so
    # the decision-path map's alternate fan can SORT and LABEL by score
    # instead of rendering anonymous dashed lines — the verb-leg score
    # counterpart to the subject candidate pool. (Instance-4 lesson: the
    # signal exists upstream; thread it, don't let the consumer go mute.)
    candidate_scores = list(data.get("candidate_scores") or [])
    if compatible_verbs and candidate_scores:
        _score_by_verb = {
            s.get("verb_iri"): s.get("score")
            for s in candidate_scores
            if s.get("verb_iri")
        }
        for cv in compatible_verbs:
            vi = cv.get("verb_iri")
            if vi in _score_by_verb and _score_by_verb[vi] is not None:
                cv["classify_score"] = float(_score_by_verb[vi])

    # When the LLM picked a compatible verb but /classify_predicate
    # couldn't materialize a full predicate dict (Weaviate-vs-Neo4j sync
    # gap), fill it in from the Neo4j-returned compatible_verbs record so
    # the supervisor can still dispatch.
    if predicate is None and verb_iri != "UNKNOWN" and compatible_verbs:
        for cv in compatible_verbs:
            if cv.get("verb_iri") == verb_iri:
                predicate = {
                    "verb_iri": cv.get("verb_iri"),
                    "verb_type": cv.get("verb_local"),
                    "input_uri": cv.get("input_uri"),
                    "output_uri": cv.get("output_uri"),
                    "endpoint": cv.get("endpoint_url") or "",
                    "owner_persona": cv.get("owner_persona"),
                    "domains": cv.get("domains") or [],
                    "cost_class": cv.get("cost_class"),
                    "requires_human_approval": cv.get("requires_human_approval", False),
                    # WHAT THE VERB TAKES - the acceptance schema for spoken slots,
                    # projected from the engine's registration (`mesh_slots`). `[]` until
                    # doc-tools' aitool_linker allowlist carries it, and `[]` means every
                    # spoken slot is refused, which is today's behaviour exactly.
                    "slots": decode_declarations(cv.get("slots")),
                }
                break

    # --------------------------------------------------------------
    # Dispatch-endpoint authority: ALWAYS prefer Neo4j's compat-walk
    # record for the resolved verb_iri over the Weaviate-backed
    # predicate dict's `endpoint` / `domains` / `owner_persona`.
    #
    # Why: classify_predicate's predicate dict comes from Weaviate,
    # whose Predicate collection can carry stale or rename-orphan
    # records (uuid5 keyed on (verb_iri, input_uri); rename + scope
    # change mints a new UUID and leaves the old record orphaned,
    # with no compensate-on-rescope in register_engine_to_mesh). The
    # Neo4j compat-walk is authoritative on dispatch coordinates —
    # /find_compatible_verbs reads the verb edges that Engine O
    # rebuilt deterministically from the TTL + registration sync,
    # not the vector-search-returned blob. The Weaviate predicate
    # stays the source for "which verb the LLM picked"; Neo4j
    # becomes the source for "where to dispatch that verb."
    #
    # The override logs a WARNING when Weaviate and Neo4j disagree —
    # that disagreement is the contamination signal the substrate
    # dedup guard (step 3) and the phrasing-independence test
    # (step 4) will codify. Seeing this log fire is data, not noise.
    if predicate is not None and verb_iri != "UNKNOWN" and compatible_verbs:
        truth = next(
            (cv for cv in compatible_verbs if cv.get("verb_iri") == verb_iri),
            None,
        )
        if truth:
            neo4j_endpoint = truth.get("endpoint_url") or ""
            neo4j_domains = list(truth.get("domains") or [])
            neo4j_owner = truth.get("owner_persona")
            weav_endpoint = predicate.get("endpoint") or ""
            weav_domains = list(predicate.get("domains") or [])
            weav_owner = predicate.get("owner_persona")
            if (
                neo4j_endpoint != weav_endpoint
                or set(neo4j_domains) != set(weav_domains)
                or neo4j_owner != weav_owner
            ):
                context.log.warning(
                    "predicate_endpoint_skew verb_iri=%s "
                    "weaviate_endpoint=%s neo4j_endpoint=%s "
                    "weaviate_domains=%s neo4j_domains=%s "
                    "weaviate_owner=%s neo4j_owner=%s "
                    "→ overriding with Neo4j (authoritative).",
                    verb_iri,
                    weav_endpoint, neo4j_endpoint,
                    weav_domains, neo4j_domains,
                    weav_owner, neo4j_owner,
                )
            predicate["endpoint"] = neo4j_endpoint
            predicate["domains"] = neo4j_domains
            predicate["owner_persona"] = neo4j_owner
            # Declarations are a DISPATCH FACT - the same argument that makes Neo4j
            # authoritative for `endpoint` makes it authoritative for what the thing at
            # that endpoint accepts. Taking them from Weaviate's predicate dict instead
            # would let a stale copy widen what a verb may be told.
            # DECODED, not list()-ed. The graph carries this as a JSON STRING because a
            # Neo4j property cannot hold a list of maps; `list()` on that string yields one
            # entry PER CHARACTER, which is the same container-for-elements trade that
            # produced "unknown fiscal period(s): F, Y, 2, 6, -, Q, 4".
            predicate["slots"] = decode_declarations(truth.get("slots"))
        else:
            # Neo4j compat-walk doesn't have this verb. That's the
            # conjunctive-read invariant violation — Weaviate picked
            # a verb Neo4j can't confirm. Treat as no-match rather
            # than dispatching to whatever endpoint Weaviate claimed,
            # because the Neo4j absence means the verb-edge typing
            # doesn't actually cover this subject's class chain.
            context.log.warning(
                "predicate_neo4j_absence verb_iri=%s subject_uri=%s "
                "weaviate_endpoint=%s — Weaviate resolved a verb "
                "Neo4j does not include in the compat-walk; "
                "downgrading to NO_MATCH.",
                verb_iri, subject_uri, predicate.get("endpoint"),
            )
            predicate = None
            verb_iri = "UNKNOWN"

    telemetry = {
        "subject_uri": subject_uri,
        "subject_confidence": subject_conf,
        "subject_reasoning": subject_reason,
        # Resolver candidate pool with scores (decision-path Part 0).
        "subject_candidates": subject_candidates,
        # Structured fallback reason. MATCHED path leaves it None (no
        # fallback); classify-returned-UNKNOWN sets no_verb_classified
        # below. subject_unknown / instance_not_found / no_compatible_verbs
        # / domain_scope_excluded / infra_error are set in the earlier
        # short-circuit branches.
        "fallback_reason": (
            None if verb_iri != "UNKNOWN" else "no_verb_classified"
        ),
        # Resolved instance URN (e.g. urn:li:dataset:... for catalog
        # assets, urn:instance:... for maintenance instances) from
        # /resolve.provenance.instance_id. Empty string when no
        # instance matched. Propagated to dispatch payload as
        # `resolved_instance_id` so execution-layer engines (Engine DA)
        # query the SAME URN that /resolve produced rather than
        # fabricating one. See Tier-3 fix (state doc 2026-06-16).
        "subject_instance_id": subject_instance_id,
        # The friendly instance label (e.g. "Customer 360") alongside the
        # URN — so the answer summary can lead with instance · verb. Empty
        # for set/type-level queries (no specific instance resolved).
        "subject_instance_label": subject_instance_label,
        "compatible_verb_iris": compatible_verb_iris,
        # Full /find_compatible_verbs response (one dict per candidate verb)
        # surfaced for the subtask_graph_trace asset materialization in
        # execute_subtask. The supervisor consumes only `verb_iri` from
        # these for compat filtering; the full records (input_uri,
        # output_uri, hops, owner_persona, endpoint_url) are projected
        # into the typed graph_trace event the cortex-ui consumes. None
        # when /find_compatible_verbs failed; [] when subject was
        # genuinely unsupported.
        "compatible_verbs": compatible_verbs,
        "neo4j_find_error": find_err,
        "verb_iri": verb_iri,
        "verb_confidence": verb_conf,
        "verb_reasoning": verb_reason,
        "candidate_verbs": candidates,
    }

    if verb_iri == "UNKNOWN" or not predicate:
        context.log.warning(
            "classify_predicate no_match query=%r subject_uri=%s "
            "compatible=%s candidates=%s reasoning=%r",
            user_query, subject_uri, compatible_verb_iris,
            candidates, verb_reason,
        )
        return _ROUTING_NO_MATCH, None, telemetry

    # LLM confidence replaces the BM25 score on the predicate dict so
    # the supervisor's threshold check reads from the same field as
    # before. (Dispatch logic + audit log unchanged from ADR-0018.)
    predicate["score"] = verb_conf

    context.log.info(
        "routing_decision subject_uri=%s subject_conf=%s "
        "compatible_count=%d verb_iri=%s verb_conf=%s "
        "candidates=%s reasoning=%r",
        subject_uri, subject_conf, len(compatible_verb_iris),
        verb_iri, verb_conf, candidates, verb_reason,
    )
    return _ROUTING_MATCHED, predicate, telemetry


def _telemetry_headers(config, caller_token: str = "") -> Dict[str, str]:
    """The ADR-0038 trace/session headers the supervisor puts on every outbound engine call.

    SINGLE SOURCE for the header NAMES. Rename a key here and the receiving engines
    silently fall back to minting their own trace id: no error, just orphaned traces.
    Pinned by tests/test_specialist_dispatch_trace_headers.py.

    WHO ACTUALLY RECEIVES THIS, verified against the live verb registry rather than
    assumed (`MATCH ()-[r]->() WHERE r.endpoint_url IS NOT NULL`):
      * Engine W (`:8088/query_knowledge`) — registered specialist, joins on this header;
      * Engine O (`:8084/resolve_instance`) — registered specialist, same middleware.
    Engine F (presentation_agent) reads the SAME header name in its own middleware but is
    NOT a registered specialist — nothing here ever calls it. Its caller is cortex-bff,
    which is a separate seam and a separate ledger item; do not read F's middleware as
    evidence that this call site feeds it.

    TWO JOIN MECHANISMS, ON PURPOSE — state which one applies before instrumenting a new
    engine, and do not pick by whichever example you read first:
      * HTTP engines (W/O/F, FastAPI middleware) join on these HEADERS;
      * RESTATE engines (E, and D) join on the ``trace_id`` BODY FIELD, because a durable
        handler reads the request body and never sees HTTP headers.
    Engine E's proxy exists precisely to translate the first into the second.
    """
    headers: Dict[str, str] = {}

    # ── THE CALLER'S OWN IDENTITY, WHEN THE VERB REQUIRES IT ───────────────────────
    # `caller_token` is alice's own Ping-rooted token, redeemed from the BFF's identity
    # vault over the live in-cluster hop (see `_redeem_caller_token`). When present it
    # REPLACES the service identity, because the whole point of the ruled design is that
    # what reaches /canvas/seed is the SAME credential the browser sends on the button
    # path — not a new one minted on some broker's authority.
    #
    # IT IS EXPRESSED HERE RATHER THAN AT THE CALL SITE on purpose. This function's own
    # docstring is the reason: one home for outbound auth, so no call site can ever send
    # trace context without a credential or the reverse. "Which credential" is an
    # argument; "where the header is set" stays a single place.
    #
    # NO X-Auth-Status IS SET on this path. That header is the OBSERVE-phase gauge's
    # discriminant for a FAILED MINT, and nothing was minted here — a redemption failure
    # never reaches this branch because it fails the subtask loudly upstream.
    #
    # ONE EXIT, DELIBERATELY. Returning early from the caller-identity branch is the obvious
    # way to write it and it is wrong twice over: it gives this function a second exit, so
    # the trace headers below would need duplicating — the drift this helper was
    # consolidated to prevent — and it truncates the source slice that
    # tests/test_specialist_dispatch_trace_headers.py takes of this function, silently
    # turning a contract test green against a body it can no longer see. The credential is
    # CHOSEN below and applied once.
    #
    # AND MIND THE PROSE HERE. That neighbouring guard slices this function with a
    # non-greedy match ending at the first occurrence of its anchor phrase, so a COMMENT
    # that quotes the anchor truncates the slice just as effectively as real code does.
    # This comment cost one red run learning that. Do not write the anchor into prose.
    #
    # AUTHORIZATION RIDES THIS SAME HELPER, on purpose. Both outbound legs already share it
    # for the telemetry headers; putting the credential anywhere else guarantees that one day
    # a call site sends trace context without a token, or the reverse. One function, both
    # legs, one thing to verify.
    #
    # OBSERVE-PHASE BEHAVIOUR: engines currently accept unauthenticated callers (the SDK's
    # transport-auth default is OBSERVE), so a mint failure must NOT break dispatch — it is
    # logged and the call proceeds token-less, which the receiving engine records as
    # `caller: none`. That is the migration gauge filling in, not an outage. When
    # REQUIRE_TRANSPORT_AUTH flips, the same failure becomes a hard 401 at the engine, which
    # is the correct time for it to become loud.
    #
    # MINT AT USE — never a stored token (the time-machine rule). Shares the platform mint so
    # there is ONE claim contract to verify.
    if caller_token:
        # THE CALLER'S OWN IDENTITY. Alice's Ping-rooted token, redeemed from the BFF's
        # identity vault over the live in-cluster hop (see `_redeem_caller_token`). It
        # REPLACES the service identity rather than accompanying it: what reaches
        # /canvas/seed is the SAME credential the browser sends on the button path, never a
        # new one minted on some broker's authority.
        #
        # NOTHING IS MINTED HERE, so there is no mint to guard and no X-Auth-Status to set
        # — that header is the OBSERVE-phase gauge's discriminant for a FAILED MINT, and
        # setting it on this path would put a fabricated reading into the gauge. A
        # redemption failure never reaches this function; it fails the subtask loudly
        # upstream, which is the honest place for an identity fault to surface.
        headers["Authorization"] = f"Bearer {caller_token}"
    else:
        try:
            # mint_supervisor_token, NOT mint_service_token. The latter has a GENERAL NAME and
            # REVIEW-STARTER-SPECIFIC behaviour (it reads REVIEW_STARTER_CLIENT_ID/SECRET), so
            # this call site originally authenticated the supervisor as `svc:review-starter` and
            # would have carried that role's can_invoke(mesh:startReview) on EVERY specialist
            # dispatch — a confused deputy introduced while fixing the confused deputy. Inert only
            # because nothing verifies yet.
            from agent_fleet.utils.service_identity import mint_supervisor_token
            headers["Authorization"] = f"Bearer {mint_supervisor_token()}"
        except Exception as exc:  # noqa: BLE001 — see OBSERVE-PHASE note above
            # THE GAUGE NEEDS THE DISCRIMINANT. A token-less dispatch caused by a mint FAILURE and
            # one from a caller that never minted both surface at the engine as `caller: none`.
            # Without a discriminant, a Keycloak blip during the migration reads as caller-readiness
            # REGRESSING, and the gauge the contract flip depends on inherits noise it cannot
            # explain. So the cause travels as a DIAGNOSTIC header.
            #
            # X-Auth-Status IS DIAGNOSTIC ONLY AND MUST NEVER REACH AN AUTHORIZATION DECISION: it is
            # caller-asserted and therefore unverifiable — exactly the property that made the
            # payload-written subject a spoofing surface. It is legal to LOG and illegal to TRUST.
            headers["X-Auth-Status"] = f"mint-failed:{type(exc).__name__}"
            logging.getLogger(__name__).warning(
                "supervisor dispatch minting no token (%s: %s) — proceeding UNAUTHENTICATED; "
                "engines record caller:none (mint failed) until svc:supervisor is configured",
                type(exc).__name__, str(exc)[:120],
            )

    if getattr(config, "trace_id", ""):
        headers["X-Trace-Id"] = config.trace_id
    if getattr(config, "session_id", ""):
        headers["X-Session-Id"] = config.session_id
    return headers


# ══════════════════════════════════════════════════════════════════════════════════
# Redeeming the caller's identity at dispatch
# ══════════════════════════════════════════════════════════════════════════════════
#
# THE STRUCTURAL FACT THIS EXISTS TO WORK AROUND: this process is not a proxy inside
# alice's HTTP request — it is a JOB LAUNCHED BY IT. The only channel across that
# boundary is Dagster run config, which is durable Postgres readable over GraphQL and
# rendered in the Dagster UI, so alice's token cannot ride along and must not be put
# there. Run config carries her RUN ID, which it already carried and which was never
# secret; the credential itself is fetched here, over the live in-cluster hop this pod
# genuinely has (verified: iagent-cortex-bff:8090 answers 200 from the user-code pod).
#
# Full reasoning, and the six invariants the BFF half enforces:
# docs/plans/identity-propagation-must-not-cross-run-storage.md (1f4d645).

# ONE RESOLVER FOR BOTH LEGS. The registration (in cortex-bff) and this redemption call
# both need the BFF's base URL, and when they were two literals in two repos-worth of
# code they disagreed — the registration used an env name no chart sets. Sharing the
# resolver is what makes "they cannot drift" a property rather than a hope.
from iagent.service_urls import cortex_bff_base_url as _cortex_bff_base_url

_CORTEX_BFF_URL = _cortex_bff_base_url()

# WHICH VERBS NEED THE CALLER'S OWN IDENTITY — an ALLOW-LIST, deliberately.
#
# Scoped rather than universal because flipping every specialist dispatch from
# svc:supervisor to alice's token is a behaviour change far beyond the seed: it would
# move every engine off the service identity at once and take the OBSERVE-phase
# caller-readiness gauge with it. That may well be the eventual destination, but it is a
# separate ruling with its own blast radius, not a side effect of shipping the canvas.
#
# Stored COMPACT to match the registry. Verified convention (mesh_registrar/main.py, from
# 24 live rows on 2026-08-21): the verb position is stored compact, subject/object full.
# The local-name comparison below tolerates either form anyway — a registry that later
# expands verbs must not silently turn this gate off, and a silently-off gate here means
# a seed that 403s exactly the way it did before the fix.
_CALLER_IDENTITY_VERBS = frozenset({"seedPortfolioCanvas"})


class CallerIdentityUnavailable(Exception):
    """The caller's identity could not be obtained. The subtask fails LOUDLY, never back.

    THE FALLBACK IS THE TRAP: dispatching as svc:supervisor when this happens would
    reproduce the original `403 cell_not_entitled x5` — the same symptom, now with a
    second cause hidden behind it. A named failure here costs one message of diagnosis;
    the silent fallback costs the afternoon that filed the plan item.

    TWO FIELDS, AND THE SPLIT IS THE POINT (2026-08-31, from a live card).

    A seed failed with `KeyError: 'SUPERVISOR_CLIENT_SECRET'` rendered verbatim on the
    user's answer card, under a message saying the credential reference could not be
    REDEEMED. Both halves were wrong in the same way:

      * a raw Python exception is not a disposition. It is the same species as the
        `400 bad params … missing 1 required keyword-only argument` that leaked a function
        signature to a user;
      * and NO REDEMPTION WAS EVER ATTEMPTED. The supervisor could not authenticate
        ITSELF, so it never reached the vault — yet the message sent the reader to the
        vault, which is where the first diagnosis of this went and it was the wrong lane.

    So `cause` is a stable, user-safe disposition that names WHICH STEP failed, and
    `detail` is the raw text, which goes to the LOG and never to a card.
    """

    def __init__(self, cause: str, detail: str = "") -> None:
        self.cause = cause
        self.detail = detail
        super().__init__(f"{cause}: {detail}" if detail else cause)


#: Disposition -> what the PERSON who asked should be told. Keyed on the cause, so a new
#: cause without a sentence here degrades to the generic line rather than leaking a
#: traceback. The remedy differs per cause and so does the OWNER: a service-identity fault
#: is a deployment matter, an expired reference is "ask again", a replay is a security
#: event. One message that covered all three would misdirect two of them.
_CALLER_IDENTITY_MESSAGES = {
    "service_identity_unconfigured": (
        "This request runs under your own identity, and the service that fetches it is "
        "missing its own credentials, so nothing was attempted. This is a deployment "
        "configuration problem rather than anything about your access — it needs an "
        "operator, not a retry."
    ),
    "not_found": (
        "The credential reference for this request was no longer available, so nothing "
        "was attempted. Asking again creates a fresh one."
    ),
    "expired": (
        "This request took longer to start than its credential reference lasts, so "
        "nothing was attempted. Asking again creates a fresh one."
    ),
    "already_redeemed": (
        "The credential reference for this request had already been used, so nothing was "
        "attempted. Asking again creates a fresh one."
    ),
    "launcher_mismatch": (
        "The credential reference did not match the request that created it, so nothing "
        "was attempted. This one is worth reporting rather than retrying."
    ),
    "not_the_redeemer": (
        "The service that fetches your identity was refused, so nothing was attempted. "
        "This needs an operator rather than a retry."
    ),
}

_CALLER_IDENTITY_DEFAULT_MESSAGE = (
    "This request needs to run under your own identity, and that identity could not be "
    "obtained, so nothing was attempted. Asking again is safe."
)


def _verb_local_name(verb_iri: str) -> str:
    """Local name of a verb IRI in either the compact or expanded form."""
    v = (verb_iri or "").strip()
    if not v:
        return ""
    for sep in ("#", "/", ":"):
        if sep in v:
            v = v.rsplit(sep, 1)[-1]
    return v


def _verb_needs_caller_identity(predicate: Dict[str, Any]) -> bool:
    return _verb_local_name(str((predicate or {}).get("verb_iri") or "")) in _CALLER_IDENTITY_VERBS


def _redeem_caller_token(context, config) -> str:
    """Exchange this run's id for the caller's own token. Once, or not at all.

    ``context.run_id`` is DAGSTER'S OWN record of which run this is — not a value read
    back out of run config, which a caller could have written. Asking with the
    authoritative id is what makes the BFF's launcher cross-check meaningful rather than
    a comparison of two caller-supplied strings.
    """
    run_id = str(getattr(context, "run_id", "") or "")
    if not run_id:
        raise CallerIdentityUnavailable(
            "no_run_id", "this op has no run id, so there is no reference to redeem"
        )

    # ── STEP ONE: AUTHENTICATE OURSELVES. A DISTINCT FAILURE FROM A VAULT REFUSAL ──
    #
    # The supervisor authenticates AS ITSELF to redeem — invariant 1 at the far end checks
    # this is svc:supervisor specifically. The service identity still OPENS the vault; it
    # is simply no longer what dispatches.
    #
    # This mint is guarded separately because its failure has a DIFFERENT OWNER and a
    # different remedy. `mint_supervisor_token` reads SUPERVISOR_CLIENT_ID/SECRET straight
    # out of os.environ, so an unconfigured pod raises KeyError here — before any request
    # is made. Reporting that as "the reference could not be redeemed" is false twice: the
    # vault was never contacted, and the fix is a deployment one. That exact conflation
    # sent the first diagnosis of a live failure to the wrong lane.
    #
    # NOTE FOR WHOEVER MEETS THIS IN THE FIELD: the credentials arrive via `envFrom` on
    # the user-code deployment, which injects at POD START. A pod that started while the
    # secret was absent stays broken for its whole life even after the secret is fixed —
    # so the remedy is a RESTART, not only a chart edit.
    try:
        from agent_fleet.utils.service_identity import mint_supervisor_token
        _svc_token = mint_supervisor_token()
    except Exception as _mint_exc:  # noqa: BLE001
        raise CallerIdentityUnavailable(
            "service_identity_unconfigured",
            f"{type(_mint_exc).__name__}: {_mint_exc}",
        ) from _mint_exc

    resp = requests.post(
        f"{_CORTEX_BFF_URL}/internal/identity/redeem",
        json={
            "run_id": run_id,
            # Invariant 4: the launcher THIS RUN records, cross-checked at the BFF
            # against the subject of the token that was stashed.
            "claimed_launcher": getattr(config, "user_email", "") or "",
        },
        headers={"Authorization": f"Bearer {_svc_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        # NAME THE CAUSE. The BFF distinguishes not_found / expired / already_redeemed /
        # launcher_mismatch, and collapsing them into "redemption failed" here would
        # discard exactly the discrimination the vault was built to make.
        try:
            _err = (resp.json() or {}).get("detail") or {}
            _cause = _err.get("error") or f"http_{resp.status_code}"
            _msg = _err.get("message") or ""
        except Exception:  # noqa: BLE001
            _cause, _msg = f"http_{resp.status_code}", (resp.text or "")[:200]
        raise CallerIdentityUnavailable(_cause, _msg)

    token = str((resp.json() or {}).get("token") or "")
    if not token:
        # A 200 with no token is a contract violation, not an empty answer. Checking the
        # transport and THEN the payload, in that order, is the standing lesson from an
        # auth failure that once wore an empty result's clothes.
        raise CallerIdentityUnavailable(
            "malformed_vault_response", "the vault answered 200 with no token"
        )
    return token


def _call_engine_a_fallback(
    context,
    sub_query: str,
    config: "SupervisorQueryConfig",
    fallback_reason: str,
    fallback_score: float | None,
    rejected_predicate: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Route a subtask to Engine A as the ADR-0008 generalist fallback.

    Engine A's existing ``/analyze`` endpoint is reused unchanged at the
    transport layer — the fallback signals ride as JSON fields so the
    Restate analyst service can pick them up and adapt its smolagent
    system prompt. The fields are namespaced under ``fallback_*`` to
    keep them visually distinct from the routine request fields.

    A structured-log line is emitted for the telemetry counter the ADR
    describes (``predicate_fallback_total{reason=...}``): scrape with
    your log-based metrics pipeline (Loki / Datadog / GCP logging) on
    the key ``predicate_fallback_total``.
    """
    # ADR-0008 telemetry: structured log line scrapable as a counter.
    context.log.info(
        "predicate_fallback_total reason=%s score=%s query=%r",
        fallback_reason,
        fallback_score if fallback_score is not None else "none",
        sub_query,
    )

    # Engine A's /analyze proxy expects the AgentTask shape
    # (task_description / dataset_id), not the supervisor's specialist-path
    # user_query field. Match that contract so the proxy passes payload
    # through cleanly.
    payload = {
        "task_description": sub_query,
        "dataset_id": "generalist_fallback",
        # Persona split: Engine A is the generalist so the answerer
        # persona collapses to whoever asked (no specialist owner_persona
        # to inherit from).
        "user_persona": config.user_persona,
        "answerer_persona": config.user_persona,
        "persona": config.user_persona,
        "domain": "UNKNOWN",  # no scoped domain — generalist fallback
        # 2026-07-02 SECURITY: thread the caller's REAL entitled_domains
        # into the generalist fallback. Previously omitted — so when
        # Engine A's search_datahub queried the catalog, it had no
        # caller scope to forward and (worse) hardcoded DATA_STEWARD.
        # That let the generalist fallback launder catalog metadata the
        # routing layer had domain-scoped away — a confirmed PII-metadata
        # bypass. Engine A now forwards this to Engine D's query_metadata
        # gate; empty scope → Engine D denies (least-privileged). The
        # generalist being domain-AGNOSTIC for ROUTING does NOT make it
        # domain-agnostic for ACCESS. See ADR-0025 "catalog is an
        # enforcement surface".
        "entitled_domains": list(config.entitled_domains),
        # ADR-0025 hop 2: the caller's entitlement key travels WITH
        # entitled_domains so Engine D can ask Topaz can_view about this
        # exact subject (not a re-derived or defaulted identity).
        "user_email": config.user_email,
        "dynamic_schema_map": "",
        "user_id": config.user_id,
        # ADR-0008 fallback context — Engine A's handler reads these to
        # prepend a generalist-fallback preamble to its smolagent prompt.
        "fallback_reason": fallback_reason,           # "no_predicate_matched" | "low_confidence"
        "fallback_score": fallback_score,             # float or null
        "fallback_query": sub_query,                  # verbatim user phrasing
        "rejected_verb_iri": (
            rejected_predicate.get("verb_iri") if rejected_predicate else None
        ),
    }

    # Forward the request's trace + session ids so Engine A's /analyze proxy adopts them
    # (X-Trace-Id -> the analyst trace's seed; X-Session-Id -> the Langfuse session). The
    # conversation-path leg of ADR-0038: cortex-ui -> BFF -> supervisor -> Engine A.
    _tele_headers = _telemetry_headers(config)
    response = requests.post(
        f"{RESTATE_ANALYST_URL}/analyze",
        json=payload,
        headers=_tele_headers or None,
        timeout=300,
    )
    response.raise_for_status()
    data = response.json()

    trace = data.get("execution_trace")
    if trace:
        context.log.info(f"🧠 Fallback Agent Reasoning Trajectory:\n{trace}")

    return {
        "persona": config.user_persona,
        "user_persona": config.user_persona,
        "answerer_persona": config.user_persona,
        "predicate_verb_iri": None,
        "fallback_reason": fallback_reason,
        "fallback_score": fallback_score,
        "sub_query": sub_query,
        "expert_response": data,
    }


# ──────────────────────────────────────────────────────────────────────
# Phase 1 observability — supervisor-side asset materializations that
# the cortex-bff gateway projects into typed SSE events for the
# grounding panel.
#
# Two assets, both logged from execute_subtask after _classify_route
# returns:
#
#   subtask_routing_decision
#     One materialization per subtask. Metadata fields project the
#     /resolve + /find_compatible_verbs + /classify_predicate outcome
#     into the shape the typed `route_decision` event consumes:
#       subject_uri, subject_confidence, subject_instance_id
#       verb_iri, verb_confidence, classify_called, candidate_count
#       handler_provider, handler_endpoint, owner_persona
#       route_status (matched | no_match | infra_error)
#       sub_query (so multi-subtask runs can be distinguished)
#
#   subtask_graph_trace
#     One materialization per subtask, only when /find_compatible_verbs
#     returned a non-empty list. Surfaces the compat-walk in a form
#     the typed `graph_trace` event renders directly:
#       subject_uri (the resolved subject)
#       compatible_verbs: list of { verb_iri, verb_local, input_uri,
#                                   output_uri, hops, owner_persona,
#                                   endpoint_url, domains, cost_class }
#       picked_verb_iri (the verb /classify_predicate ultimately picked,
#                        for highlighting in the graph)
#
# The gateway projects the FIRST materialization per run into typed
# events (multi-subtask fan-out emits later materializations the
# gateway sees but doesn't re-emit — keeps the RoutingDecision card
# focused on the primary route the user's answer flows through).
#
# Architect's principle locked in: every metadata field below is a
# real pipeline value (from /resolve, /find_compatible_verbs,
# /classify_predicate, or the verb edge). Nothing synthesized.
# ──────────────────────────────────────────────────────────────────────


def _log_subtask_route_assets(
    context,
    *,
    telemetry: Dict[str, Any],
    predicate: Dict[str, Any] | None,
    status: str,
    sub_query: str,
) -> None:
    """Emit the two route-observability asset materializations."""
    # ── subtask_routing_decision ────────────────────────────────────
    routing_meta: Dict[str, Any] = {
        "route_status": MetadataValue.text(status),
        "subject_uri": MetadataValue.text(
            telemetry.get("subject_uri") or "UNKNOWN"
        ),
        "subject_confidence": MetadataValue.float(
            float(telemetry.get("subject_confidence") or 0.0)
        ),
        "subject_instance_id": MetadataValue.text(
            telemetry.get("subject_instance_id") or ""
        ),
        "subject_instance_label": MetadataValue.text(
            telemetry.get("subject_instance_label") or ""
        ),
        "verb_iri": MetadataValue.text(
            telemetry.get("verb_iri") or "UNKNOWN"
        ),
        "verb_confidence": MetadataValue.float(
            float(telemetry.get("verb_confidence") or 0.0)
        ),
        # classify_called is true whenever /classify_predicate ran
        # (status == matched OR status == no_match-after-classify-returned-UNKNOWN).
        # ADR-0019 Contract B short-circuit cases (subject UNKNOWN, or
        # Neo4j zero-compat) DO NOT invoke classify_predicate; status
        # carries that signal already.
        "classify_called": MetadataValue.bool(
            status == _ROUTING_MATCHED
            or telemetry.get("verb_iri") not in (None, "UNKNOWN")
        ),
        "candidate_count": MetadataValue.int(
            len(telemetry.get("compatible_verb_iris") or [])
        ),
        # Decision-path Part 0 captures: the resolver candidate pool
        # (winners AND losers with scores) as JSON, and the structured
        # fallback_reason. candidate_count above stays (cheap glance);
        # subject_candidates is the full pool the visualizer's resolver
        # stage renders. fallback_reason is a CLOSED enum (extended, never
        # collapsed into an existing value): subject_unknown |
        # instance_not_found | no_compatible_verbs | domain_scope_excluded
        # | no_verb_classified | infra_error, or empty on the matched
        # path. instance_not_found (abstention-gate arc, 2026-07-03) is a
        # NAMED individual the registry doesn't know, decided structurally
        # — distinct from subject_unknown (the class itself didn't ground).
        "subject_candidates": MetadataValue.text(
            json.dumps(telemetry.get("subject_candidates") or [])
        ),
        "fallback_reason": MetadataValue.text(
            str(telemetry.get("fallback_reason") or "")
        ),
        # Acting-persona provenance — the CALLER persona + domain the
        # decision was computed under (persona-driven verb eligibility).
        # The premise that makes a same-query-different-verb divergence
        # self-explaining. Distinct from owner_persona (answerer-side).
        "acting_persona": MetadataValue.text(
            str(telemetry.get("acting_persona") or "")
        ),
        "acting_domains": MetadataValue.text(
            ",".join(telemetry.get("acting_domains") or [])
        ),
        "sub_query": MetadataValue.text(sub_query or ""),
    }
    if predicate:
        routing_meta["handler_provider"] = MetadataValue.text(
            str(predicate.get("provider") or "")
        )
        routing_meta["handler_endpoint"] = MetadataValue.text(
            str(predicate.get("endpoint") or "")
        )
        routing_meta["owner_persona"] = MetadataValue.text(
            str(predicate.get("owner_persona") or "")
        )
        routing_meta["output_uri"] = MetadataValue.text(
            str(predicate.get("output_uri") or "")
        )
    context.log_event(
        AssetMaterialization(
            asset_key=["subtask_routing_decision"],
            metadata=routing_meta,
        )
    )

    # ── subtask_graph_trace ─────────────────────────────────────────
    # Only meaningful when the compat-walk returned candidates. Skip
    # the materialization on UNKNOWN subjects (Contract B short-circuit
    # has nothing to graph) and on infra errors.
    compatible_verbs = telemetry.get("compatible_verbs")
    subject_uri = telemetry.get("subject_uri")
    if (
        status != _ROUTING_INFRA_ERROR
        and subject_uri
        and subject_uri != "UNKNOWN"
        and compatible_verbs
    ):
        context.log_event(
            AssetMaterialization(
                asset_key=["subtask_graph_trace"],
                metadata={
                    "subject_uri": MetadataValue.text(subject_uri),
                    "picked_verb_iri": MetadataValue.text(
                        telemetry.get("verb_iri") or ""
                    ),
                    # Stash the full list as JSON text so the gateway
                    # can deserialize and project per-verb nodes for
                    # the typed graph_trace event.
                    "compatible_verbs": MetadataValue.text(
                        json.dumps(compatible_verbs)
                    ),
                },
            )
        )


# Pure helper lives in iagent_pure.predicate_routing — extracted there
# so pure-unit tests can pin its contract without dragging Dagster /
# psycopg2 through iagent/__init__.py. Re-exported under the legacy
# underscore name so this file's call site (and any future caller) is
# unchanged.
from iagent_pure.predicate_routing import (
    inject_predicate_output_uri as _inject_predicate_output_uri,
)
# Same rationale, same package: the acceptance filter is stdlib-only so the BFF, this
# supervisor and the unit tests can each import it without standing up the others.
from iagent_pure.slot_acceptance import accept_slots, decode_declarations
from iagent_pure.slot_disposition import (
    ask_card,
    decide_disposition,
    validate_bound_slots,
)

#: One model call's budget, CONDITIONAL ON THE ROUTED VERB'S SLOT CENSUS.
#:
#: The short budget's justification used to be stated unconditionally: "a slot REFINES a
#: question that will still be answered without it, so a slow extractor must cost the user a
#: default, never a timeout." THAT IS TRUE FOR spoken-OPTIONAL AND EXACTLY INVERTED FOR
#: spoken-MANDATORY. Without a mandatory slot the verb cannot run at all, so the timeout does
#: not cost a default — it converts a fully-specified question into an elicitation.
#:
#: MEASURED 2026-09-02: "why are we over budget on Notional Program Meridian" routed to
#: finVarianceAnalysis at 0.96; engine-o extracted program_id="Notional Program Meridian" at
#: 0.95 and returned 200 OK; the supervisor had already given up at 20s. The user was then
#: asked "which Program?" about a question that named the program. EVERY Engine F verb has a
#: spoken-mandatory slot, so this converted all six into asks and no card ever drew.
#: See docs/plans/a-mandatory-slot-does-not-refine.md.
#:
#: SO THE BUDGET IS NOT ONE NUMBER. A verb whose slots are all optional keeps the short one —
#: the original reasoning is sound there and waiting is the wrong trade. A verb with any
#: spoken-mandatory slot gets the long one, because the alternative to waiting is not a
#: default, it is asking the user something they already said.
_FILL_SLOTS_TIMEOUT_S = float(os.getenv("FILL_SLOTS_TIMEOUT_S", "20"))

#: The budget when the routed verb cannot run without something the speaker must say.
#: Larger than the observed extraction (which returned correctly AFTER 20s), and bounded:
#: the cost of waiting is one user's patience, the cost of timing out is a wrong question.
_FILL_SLOTS_TIMEOUT_MANDATORY_S = float(
    os.getenv("FILL_SLOTS_TIMEOUT_MANDATORY_S", "75")
)

#: Slot kinds whose ABSENCE the verb cannot run without. `handle` and `ceremony` are
#: route-supplied — the dispatcher resolves them from the store and no speaker names them —
#: so they never make a question un-runnable for want of extraction.
_MUST_BE_SPOKEN_KINDS = frozenset({"spoken-mandatory"})


def _fill_slots_budget(declarations) -> float:
    """The extraction budget for THIS verb, from its own declarations.

    Derived, never configured per-verb: the census is a fact about the signature the verb
    already published, so a verb that gains a mandatory slot gets the longer budget with no
    second place to update. Falls back to the short budget when the declarations are absent
    or unreadable — the conservative direction, matching every other degradation on this path.
    """
    try:
        for d in declarations or []:
            if isinstance(d, dict) and d.get("kind") in _MUST_BE_SPOKEN_KINDS:
                return _FILL_SLOTS_TIMEOUT_MANDATORY_S
    except TypeError:
        pass
    return _FILL_SLOTS_TIMEOUT_S

#: THE OPTION SOURCE FOR AN ELICITATION, AND IT IS NOT WIRED YET - deliberately, and the
#: gap is named rather than papered over.
#:
#: Engine P registered as a `mesh:enumerateInstances` provider (3516103), but there is no
#: ROUTER-SIDE FAN-OUT: nothing in Engine O dispatches an enumerate the way `/resolve` fans
#: out a resolve. A registration is not a reachable call, and the supervisor must not invent
#: a provider's URL - that is the phantom-service-URL shape this repo has already paid for.
#:
#: So the disposition runs with no enumerator and reports `free_text_reason: no_provider`,
#: which is the honest interim ADR-0033 permits WITH ITS ATTEMPT RECORDED. The day the
#: fan-out lands (the option-source lane's, per the ownership split), setting this env var
#: is the whole wiring - and `test_free_text_must_carry_a_provider_reason` fails the moment
#: an ask goes out with no menu and no reason.
_ENUMERATE_URL = os.getenv("ENUMERATE_INSTANCES_URL", "")
_ENUMERATE_TIMEOUT_S = float(os.getenv("ENUMERATE_TIMEOUT_S", "5"))


def _make_enumerator(context):
    """`class_uri -> {outcome, members, count}`, or None when no provider is reachable.

    None is NOT the same as an empty menu, and the disposition treats them differently:
    None becomes `no_provider` (nobody was asked), an empty `members` list becomes an
    abstain (the class is enumerable and holds nothing). Collapsing those is exactly how
    free text becomes a default instead of a reported outcome."""
    if not _ENUMERATE_URL:
        return None

    def _enumerate(class_uri: str) -> Dict[str, Any]:
        resp = requests.post(
            _ENUMERATE_URL, json={"class_uri": class_uri}, timeout=_ENUMERATE_TIMEOUT_S,
        )
        resp.raise_for_status()
        body = resp.json() or {}
        context.log.info(
            "enumerate_instances class_uri=%s outcome=%s count=%s",
            class_uri, body.get("outcome"), body.get("count"),
        )
        return body

    return _enumerate


class _FillResult(NamedTuple):
    """What the filler produced, and what it could not resolve. Two fields because the
    disposition needs both: `slots` is what reaches the verb, `resolution` is why a slot
    that names a referent is missing from it."""
    slots: Dict[str, Any]
    resolution: Dict[str, Any]


def _fill_slots_from_query(
    context,
    *,
    query: str,
    verb_iri: str,
    declarations,
) -> "_FillResult":
    """Ask Engine O which parameters the speaker named, for the verb already routed.

    HONEST-EMPTY ON EVERY FAILURE — unreachable, slow, non-200, or a malformed body all
    return `{}`, which is exactly the pre-slot behaviour: the verb runs on its signature
    defaults. This call must not be able to make routing worse than it was before slot
    filling existed, so every failure degrades to the old answer instead of raising.

    Deliberately NOT retried. A slot is a refinement of a question that will still be
    answered without it; spending a second model call and another few seconds of a user's
    wait to maybe refine it is the wrong trade. The generalist fallback next door retries
    because its failure means NO answer at all.

    THAT REASONING IS TRUE OF spoken-OPTIONAL SLOTS ONLY, and the budget above is now
    conditional for exactly that reason — see `_fill_slots_budget`. For a spoken-MANDATORY
    slot the failure DOES mean no answer: the honest-empty return leaves the slot unfilled,
    the ask disposition fires, and a fully-specified question becomes an elicitation.

    THE RESIDUE, NAMED RATHER THAN PAPERED OVER: a longer budget makes the timeout rare, it
    does not make `{}` honest. A genuine failure still returns the same empty dict as a
    successful extraction from a question that named nothing — identical shape, opposite
    meaning — so the ask cannot tell "the speaker did not say" from "we failed to look".
    Distinguishing those is a change to the ask disposition's input, not to this budget, and
    it is deliberately not made here.
    """
    try:
        resp = requests.post(
            f"{ONTOLOGY_SVC_URL}/fill_slots",
            json={"query": query, "verb_iri": verb_iri, "declarations": declarations},
            timeout=_fill_slots_budget(declarations),
        )
        if resp.status_code != 200:
            context.log.warning(
                "fill_slots non-200 verb_iri=%s status=%s — running on defaults",
                verb_iri, resp.status_code,
            )
            return _FillResult({}, {})
        body = resp.json() or {}
    except Exception as exc:  # noqa: BLE001
        context.log.warning(
            "fill_slots unavailable verb_iri=%s (%s) — running on defaults", verb_iri, exc
        )
        return _FillResult({}, {})

    slots = body.get("slots") or {}
    if not isinstance(slots, dict):
        context.log.warning("fill_slots returned a non-object for %s", verb_iri)
        return _FillResult({}, {})

    # THE TRI-STATE, CARRIED. Fix (1) made `/fill_slots` report per-slot resolution and
    # REMOVE an unresolved referent from `slots` rather than passing the spoken name
    # through. Reading only `slots` here would throw that away at the boundary — and it is
    # the difference between an ask that can offer `I1` and one that only knows something
    # is missing. `E05` is exactly this case.
    resolution = body.get("resolution") or {}
    if not isinstance(resolution, dict):
        resolution = {}

    # LOUD BOTH WAYS. The finding this closes was a parameter vanishing in silence, so
    # what was extracted is logged as prominently as what was refused.
    if slots:
        context.log.info(
            "slots_filled verb_iri=%s %s (confidence=%s) %s",
            verb_iri, slots, body.get("confidence"), body.get("reasoning", "")[:160],
        )
    for r in body.get("refused") or []:
        context.log.warning("slot_refused_at_extraction verb_iri=%s %s", verb_iri, r)
    for name, rec in sorted(resolution.items()):
        if isinstance(rec, dict) and rec.get("outcome") not in (None, "", "exact"):
            context.log.info(
                "slot_resolution verb_iri=%s slot=%s outcome=%s spoken=%r candidates=%d",
                verb_iri, name, rec.get("outcome"), rec.get("spoken", ""),
                len(rec.get("candidates") or []),
            )
    return _FillResult(slots, resolution)


def _log_subtask_sources_asset(
    context,
    *,
    engine_response: Dict[str, Any],
    verb_iri: str | None,
    sub_query: str,
) -> None:
    """Materialize a subtask_sources Dagster asset from the engine's
    response. The gateway projects this into the typed `sources` SSE
    event for the cortex-ui SourcesTrail.

    Engine response contract (Phase 3): if an engine attached the
    `sources` key to its response (top-level list[dict]), each dict
    matches the cortex-ui Source shape — `type`, `label`, `uri`,
    optional `snippet`, `relevance`, `open_url`. Engines that haven't
    been migrated yet (E and A in the first Phase 3 pass) don't
    include the key; the supervisor skips the materialization for
    them. SourcesTrail then renders its empty-state for those turns.

    The materialization metadata includes a JSON-serialized full
    `sources` list (so the gateway can deserialize and project) plus
    a `sources_count` summary scalar for at-a-glance Dagster UI audit.
    """
    sources = engine_response.get("sources") if isinstance(engine_response, dict) else None
    if not sources or not isinstance(sources, list):
        # Engine didn't attach sources (yet). Skip the asset.
        return

    # Defensive: cap at a reasonable max so a runaway engine response
    # can't fill Dagster metadata with megabytes of citations. 50 is
    # well above the 5-hit-per-tool-call default any engine uses today.
    capped = sources[:50]

    context.log_event(
        AssetMaterialization(
            asset_key=["subtask_sources"],
            metadata={
                "sources_count": MetadataValue.int(len(capped)),
                "verb_iri": MetadataValue.text(verb_iri or ""),
                "sub_query": MetadataValue.text(sub_query or ""),
                # Full payload as JSON text — the gateway deserializes.
                "sources_json": MetadataValue.text(json.dumps(capped)),
            },
        )
    )


def _log_subtask_access_denied_asset(
    context,
    *,
    engine_response: Dict[str, Any],
    sub_query: str,
) -> None:
    """Materialize a subtask_access_denied Dagster asset when an engine's
    response is a STRUCTURED access denial (Bug 2). The gateway projects
    this into a typed `access_denied` SSE event so the UI surfaces a
    'request access' state wired to the HITL /access_requests flow — the
    SPECIFIC denial signal, distinct from empty results / fumbles / errors.

    Engine contract: `status == "access_denied"`, with `denied_assets`
    (list[str] URNs) and `subject` (the authz_id the request is filed for).
    Emitted ONLY for that exact status — never for success/error — so the
    UI's request-access prompt fires only for real authorization denials.
    """
    if not isinstance(engine_response, dict):
        return
    if engine_response.get("status") != "access_denied":
        return
    denied = engine_response.get("denied_assets") or []
    context.log_event(
        AssetMaterialization(
            asset_key=["subtask_access_denied"],
            metadata={
                "denied_assets_json": MetadataValue.text(
                    json.dumps(denied[:20] if isinstance(denied, list) else [])
                ),
                "subject": MetadataValue.text(engine_response.get("subject") or ""),
                "sub_query": MetadataValue.text(sub_query or ""),
                "message": MetadataValue.text(engine_response.get("message") or ""),
            },
        )
    )


@op(ins={"task_def": In(Dict[str, Any])}, out=Out(Dict[str, Any]))
def execute_subtask(context, config: SupervisorQueryConfig, task_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a single decomposed sub-task by routing it through the
    predicate graph (ADR-0009 Step F'.3).

    The previous body branched on ``task_def['domain']`` to pick between
    Engine DA / Engine E / Engine A. That `if/elif` is gone — the
    supervisor now asks Engine O's ``/search_predicates`` which predicate
    matches the verb the user wanted, scoped by the caller's entitled
    domains. Engines self-declare both their domains and their answerer
    persona at registration; the supervisor reads them off the matched
    predicate without a code change per engine.

    Notes on persona:
      * ``answerer_persona`` is the matched predicate's ``owner_persona``
        — drives the engine's response shape (BAML union resolution in
        Engine E, UI archetype in Engine F).
      * ``user_persona`` is the caller's identity-derived persona — drives
        UI prefs and is the answerer fallback when the predicate is
        persona-agnostic.
    """
    sub_query = task_def.get("sub_query", "")

    # Symmetric SPO routing: /resolve does subject classification (Weaviate
    # OntologyClass recall + ClassifyDomainIntent precision), then
    # /classify_predicate does the same for the verb side (predicate
    # Weaviate recall + ClassifyPredicate precision) with the resolved
    # subject as context. The yellow-zone band + VerifyVerbChoice gate
    # are gone — the LLM IS the classifier, not a second-guess gate over
    # BM25. The threshold below applies to the LLM's own confidence.
    routing_query = sub_query or config.user_query

    # Legacy single-domain hint. `entitled_domains[0]` is the prior
    # "first entitled wins" lock that funneled every multi-entitlement
    # user's query through the same domain regardless of query content
    # (Bug A confirmed 2026-06-28; full diagnosis in
    # [[ontology-class-pool-prov-contamination]]'s linked memory and
    # [[failure-mode-pluralism-in-fixes]]).
    #
    # The lock is now MITIGATED — _classify_route passes the full
    # `entitled_domains` list to Engine O via the new `domains` field,
    # and Engine O scopes the OntologyClass pool to the UNION of those.
    # The LLM picks the best match query-driven across them. We keep
    # `routing_domain` for the legacy /classify_predicate domain hint
    # (which has the same lock shape but is downstream of subject
    # resolution and a separate question — left for a follow-up if
    # the diagnosis surfaces it as material).
    routing_domain = (
        list(config.entitled_domains)[0]
        if config.entitled_domains else "MAINTENANCE"
    )

    status, predicate, telemetry = _classify_route(
        context,
        routing_query,
        list(config.entitled_domains),
        routing_domain=routing_domain,
        entity_refs=list(config.entity_refs) if config.entity_refs else None,
        user_email=config.user_email,
    )

    # ------------------------------------------------------------------
    # Phase 1 observability: log AssetMaterialization for the route
    # decision + the compat-walk so the gateway can project them into
    # typed `route_decision` and `graph_trace` SSE events for the
    # cortex-ui grounding panel. The events are derived from REAL
    # Dagster asset materializations — the supervisor remains the
    # audit trail, the gateway never bypasses Dagster to fabricate
    # routing data.
    #
    # Architect's principle (banked at code-site): surface what the
    # pipeline did; never synthesize. Each metadata field below is a
    # value from a real /resolve, /find_compatible_verbs, or
    # /classify_predicate response — projected, not invented.
    # ------------------------------------------------------------------
    # Acting-persona provenance (ADR-0009 / ADR-0025): the CALLER persona +
    # domain the decision was computed under. Persona-driven routing means
    # the same query can pick different verbs under different personas — so
    # this is the missing premise that makes a divergence self-explaining
    # ("describeAsset as DATA_STEWARD" vs "enumerateCatalog as
    # DATA_ENGINEER"). Distinct from owner_persona (the answerer-side).
    # Captured on the decision record, not just the live HUD.
    telemetry["acting_persona"] = config.user_persona or ""
    telemetry["acting_domains"] = list(config.entitled_domains or [])
    try:
        _log_subtask_route_assets(
            context,
            telemetry=telemetry,
            predicate=predicate,
            status=status,
            sub_query=sub_query,
        )
    except Exception as mat_err:  # pragma: no cover — best-effort
        # Observability failure must not break the routing decision —
        # log and continue so a malformed metadata write doesn't kill
        # the user's query.
        context.log.warning(
            "Failed to log subtask route asset materializations "
            "(non-fatal — routing continues): %s", mat_err,
        )

    # Routing decision table (simpler than the prior version: no
    # yellow-zone band):
    #   matched  + confidence ≥ threshold → specialist
    #   matched  + confidence < threshold → Engine A fallback (low_confidence)
    #   no_match                          → Engine A fallback (no_predicate_matched)
    #   infra_error                       → abort with INFRA_ERROR signal
    if status == _ROUTING_INFRA_ERROR:
        # Infrastructure outage — must surface, NOT mask via fallback.
        # Same reasoning that drove the ADR-0009 Cypher-fallback removal:
        # silent degradation hides the signal ops needs to fix the outage.
        context.log.error(
            f"Aborting subtask due to routing infrastructure error "
            f"(query={routing_query!r}). Engine O must recover before "
            f"this subtask can be retried. telemetry={telemetry}"
        )
        return {
            "persona": config.user_persona,
            "user_persona": config.user_persona,
            "answerer_persona": None,
            "sub_query": sub_query,
            "expert_response": {
                "status": "INFRA_ERROR",
                "summary": (
                    "Routing service is unavailable. The mesh cannot route "
                    "this request right now. Please retry shortly; if the "
                    "error persists, the operator should check Engine O, "
                    "the Weaviate Predicate collection, and the LLM "
                    "endpoint backing ClassifyPredicate."
                ),
            },
        }

    if status == _ROUTING_NO_MATCH:
        # Per ADR-0008: registry coverage gap → generalist fallback.
        return _call_engine_a_fallback(
            context,
            sub_query=sub_query,
            config=config,
            fallback_reason="no_predicate_matched",
            fallback_score=None,
            rejected_predicate=None,
        )

    # status == _ROUTING_MATCHED — apply the threshold against the LLM's
    # confidence (replaces the BM25 + yellow-zone gate machinery).
    assert predicate is not None
    score = predicate.get("score")
    threshold = config.predicate_fallback_score_threshold

    context.log.info(
        "predicate_routing_score score=%s threshold=%s verb_iri=%s "
        "subject_uri=%s subject_conf=%s",
        score if score is not None else "none",
        threshold,
        predicate.get("verb_iri"),
        telemetry.get("subject_uri"),
        telemetry.get("subject_confidence"),
    )

    if score is None or score < threshold:
        return _call_engine_a_fallback(
            context,
            sub_query=sub_query,
            config=config,
            fallback_reason="low_confidence",
            fallback_score=score,
            rejected_predicate=predicate,
        )

    endpoint = predicate["endpoint"]
    answerer_persona = predicate.get("owner_persona") or config.user_persona

    # Domain context is sourced from the predicate's declared scope (first
    # entry if multi-domain) so engines that still segregate data by domain
    # (Engine W, Engine E label filters) keep working.
    predicate_domains = predicate.get("domains") or []
    routing_domain = predicate_domains[0] if predicate_domains else "MAINTENANCE"

    # Engine DA needs a DataHub schema map injected; we ship it for any
    # data-engineering-scoped predicate so the engine doesn't have to
    # round-trip itself.
    dynamic_schema_map = ""
    if "DATA_ENGINEERING" in predicate_domains:
        dynamic_schema_map = get_datahub_context(DATAHUB_WRAPPER_URL)

    # ---------------------------------------------------------------------
    # THE CARRY. docs/plans/slots-are-extracted-then-dropped-at-dispatch.md
    #
    # This is the boundary the finding named: everything above resolves a verb, everything
    # below calls it, and until now no argument the SPEAKER named crossed. A question
    # saying "by initiative" reached a verb whose `group_by` defaulted to `org` and came
    # back with organisations - rendering cleanly, with clean provenance, and with no
    # surface on which a reader could notice.
    #
    # FILTERED against the verb's own declarations before it crosses, because this same
    # line is what would otherwise let a spoken value land on a ROUTE-SUPPLIED argument
    # (`ops`, `baseline_state`) - which is not parameterising a question but supplying the
    # evidence the answer is computed from. See iagent_pure/slot_acceptance.py.
    # THE SLOT-FILLER, called HERE because this is the first moment the phrase and the
    # verb are both known. /route_intent receives only the query (ADR-0009 Step F'.6
    # removed candidate_verb on purpose), so there is nothing to fill against at that hop.
    # See docs/plans/the-slot-filler-belongs-where-the-verb-is-known.md.
    #
    # `config.slots` still wins when present: a caller that supplies slots explicitly is
    # not overridden by a model. Extraction fills the gap, it does not take the wheel.
    spoken = dict(config.slots or {})
    declared = predicate.get("slots")
    resolution: Dict[str, Any] = {}

    # ── THE ANSWER TO AN ASK, ARRIVING BACK ─────────────────────────────────────────────
    # A pick is validated against a RECOMPUTED menu, never against one the client echoes
    # (self-certifying: a caller that can send the pick can send a menu permitting it) and
    # never against one this process held between turns (the lifetime the stateless re-route
    # exists to avoid). Recomputing also buys freshness: a pick against a menu that has since
    # changed is refused rather than honoured because a stale copy still permits it.
    #
    # It merges OVER `config.slots` because a person choosing from a menu outranks both an
    # extraction and a caller-supplied default — ADR-0033 #5's user-confirmed provenance,
    # applied at the only point that can check it.
    if config.bound_slots and declared:
        picked, refusals = validate_bound_slots(
            config.bound_slots,
            declared=declared,
            enumerate_class=_make_enumerator(context),
        )
        for refusal in refusals:
            # LOUD. A refused pick is the menu-integrity guard doing its job, and it is the
            # one refusal a user can actually see the consequence of.
            context.log.warning(
                "bound_slot_refused verb_iri=%s %s", predicate.get("verb_iri"), refusal
            )
        if picked:
            context.log.info(
                "bound_slots_accepted verb_iri=%s %s", predicate.get("verb_iri"), picked
            )
            spoken = {**spoken, **picked}

    if not spoken and declared:
        filled = _fill_slots_from_query(
            context,
            query=sub_query,
            verb_iri=predicate.get("verb_iri") or "",
            declarations=declared,
        )
        spoken, resolution = filled.slots, filled.resolution

    accepted = accept_slots(spoken, declared)
    for refusal in accepted.refusals:
        # LOUD, per the ruling. A dropped slot is a question the system did not answer as
        # asked, and the whole finding is that this used to happen in total silence.
        context.log.warning(
            "slot_refused verb_iri=%s %s", predicate.get("verb_iri"), refusal
        )

    # -----------------------------------------------------------------------------------
    # THE DISPOSITION POINT - ADR-0033's `route | ask | abstain`, decided here because this
    # is the only line where the phrase, the routed verb, the declarations and the accepted
    # slots are all in hand. Everything above resolves; everything below dispatches.
    #
    # WHAT THIS REPLACES, measured: `plan_dependency_neighborhood` without `project_id`
    # raised TypeError and the caller got
    #   400 bad params ... missing 1 required keyword-only argument: 'project_id'
    # - a Python signature error rendered to a person who asked about phases. The missing
    # thing was one sentence away from them and the system had no way to ask for it.
    #
    # THE TRIGGER CANNOT REACH AN OPTIONAL SLOT. `decide_disposition` walks only
    # spoken-mandatory declarations, so `E04` (misses `direction`) and `C04` (misses
    # `site_id`, `window`) still route on their defaults - both are genuine misses of
    # information the user supplied, and both MUST still route. ADR-0033 #4: a system that
    # asks when it knows is worse than one that guesses when it doesn't.
    # -----------------------------------------------------------------------------------
    disposition = decide_disposition(
        accepted=accepted.params,
        declared=declared,
        resolution=resolution,
        enumerate_class=_make_enumerator(context),
    )
    # ── subtask_slots_decision — THE HOP THAT WAS NEVER THERE ────────────────────────
    #
    # `resolved_intent` on the AnswerArtifact has always been populated from
    # /route_intent's ExtractIntent output — mode and entity_refs, captured before any
    # resolution happens — and never updated afterwards. A field named for resolution
    # holding extraction, written once at the start of the run.
    #
    # AND THE DATA COULD NOT HAVE REACHED IT. `_log_subtask_route_assets` fires ~150 lines
    # ABOVE this one, before /fill_slots has run, so the routing materialization carries
    # subject, verb, candidates and fallback_reason and no slots at all. The gateway had
    # nothing to write even if it had wanted to; the capture point preceded the data.
    #
    # THIS IS THE ONLY LINE WHERE THE WHOLE ANSWER TO "WHAT DID THE SYSTEM UNDERSTAND"
    # EXISTS: the phrase, the routed verb, the declarations, the accepted parameters, the
    # ones it REFUSED and why, the per-slot resolution outcomes, and the disposition. The
    # comment above says everything below dispatches — so this is also the last moment
    # before the understanding turns into an action.
    #
    # REFUSALS ARE CARRIED, not just acceptances. A dropped slot is a question the system
    # did not answer as asked, and an artifact recording only what it accepted would be the
    # silent-narrowing shape at the provenance layer: a record that reads as complete
    # because the omission left no trace in it.
    try:
        context.log_event(
            AssetMaterialization(
                asset_key=["subtask_slots_decision"],
                metadata={
                    "verb_iri": MetadataValue.text(str(predicate.get("verb_iri") or "")),
                    "disposition": MetadataValue.text(str(disposition.action or "")),
                    "accepted_slots": MetadataValue.text(
                        json.dumps(accepted.params, default=str)
                    ),
                    "refused_slots": MetadataValue.text(
                        json.dumps([str(r) for r in accepted.refusals])
                    ),
                    "slot_resolution": MetadataValue.text(
                        json.dumps(resolution, default=str)
                    ),
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        # NON-FATAL, matching every other capture on this path. Provenance that fails must
        # not take an answer down — a run that succeeded and recorded nothing is worse than
        # one that succeeded and recorded less, but both beat one that did not run.
        context.log.warning("subtask_slots_decision materialization failed: %s", exc)

    if disposition.action != "route":
        context.log.info(
            "slot_disposition=%s verb_iri=%s slot=%s reason=%s option_source=%s "
            "options=%d free_text_reason=%s",
            disposition.action, predicate.get("verb_iri"), disposition.slot,
            disposition.reason, disposition.option_source, len(disposition.options),
            disposition.free_text_reason,
        )
        # SEPARATE COUNTERS, because a shrinking ask population must be readable. An ask on
        # a slot the phrase DID carry is a filler regression surfacing as a question; folded
        # into one counter, a degrading filler looks like a feature getting more use. `E04`
        # was such a case two runs ago and is not one now, which is the success mode.
        try:
            context.add_output_metadata({
                "slot_disposition": disposition.action,
                "slot_disposition_slot": disposition.slot or "",
                "slot_disposition_reason": disposition.reason,
                "ask_on_present_in_phrase": bool(disposition.spoken),
                "ask_on_absent_from_phrase": not disposition.spoken,
            })
        except Exception:  # pragma: no cover - metadata must never break a dispatch
            pass
        return {
            "persona": answerer_persona,
            "user_persona": config.user_persona,
            "answerer_persona": answerer_persona,
            "predicate_verb_iri": predicate.get("verb_iri"),
            "sub_query": sub_query,
            # A DISTINCT typed status, never borrowed. The surface for this is deferred by
            # ADR-0033's archetype-unity constraint - it and ADR-0032's goal-shape card are
            # ONE card, designed once with cortex in the room - so until that lands the UI
            # renders `message`, which is written to stand on its own. Per the
            # registered-or-honest-fallback rule an unregistered kind must degrade VISIBLY
            # rather than borrow another species' affordances; that is how the triage card
            # came to offer Approve/Reject on a failure.
            "expert_response": ask_card(
                disposition,
                verb_iri=predicate.get("verb_iri") or "",
                sub_query=sub_query,
                accepted=accepted.params,
            ),
        }

    payload = {
        "user_query": sub_query,
        # ADR-0009 persona split: both fields surfaced explicitly.
        "user_persona": config.user_persona,
        "answerer_persona": answerer_persona,
        # Legacy aliases so engines that haven't migrated still work; both
        # point to answerer_persona, which is what the old `persona` field
        # was driving (response shape) in practice.
        "persona": answerer_persona,
        "domain": routing_domain,
        # 2026-07-03 SECURITY-CORRECTNESS: thread the caller's REAL
        # entitled_domains on the SPECIALIST dispatch too. The stopgap
        # (2026-07-02) added this to _call_engine_a_fallback but MISSED
        # this specialist path — so an ENTITLED caller (alice picking
        # DATA_ENGINEER·DATA_ENGINEERING) whose ownership query routes
        # to Engine A via the lookupOwnership verb had her scope
        # dropped, Engine A's search_datahub sent empty entitled_domains
        # to query_metadata, and the gate denied her (empty = fail-
        # closed). Failed CLOSED (no leak) but wrongly denies the
        # entitled. Engines that call the catalog (Engine A's
        # search_datahub) read this to forward the caller's real scope
        # to query_metadata's gate.
        "entitled_domains": list(config.entitled_domains),
        # ADR-0025 hop 2: the caller's ENTITLEMENT KEY travels WITH
        # entitled_domains on the SPECIALIST path too — the EXACT twin of
        # the miss the comment above documents. The email was first added
        # only to the generalist fallback (_call_engine_a_fallback); this
        # specialist dispatch (alice's DATA_ENGINEER ownership queries route
        # here) MUST carry it as well or Engine A's search_datahub sends an
        # empty caller_email to query_metadata's Topaz ask and the entitled
        # caller is fail-CLOSED denied. Caught by the flag-on seal: bob
        # (fallback path) threaded, alice (this path) came through empty.
        "user_email": config.user_email,
        "dynamic_schema_map": dynamic_schema_map,
        "user_id": config.user_id,
        # Hand the matched predicate to the engine for observability /
        # provenance — engines can log which verb_iri served the call.
        "predicate_verb_iri": predicate.get("verb_iri"),
        # ADR-0017: Engine A (post-decomposition) selects a per-verb
        # prompt block keyed on routed_verb_iri. Same value as
        # predicate_verb_iri; surfaced under the name the engine's
        # handler reads. Engines that don't read it ignore it.
        "routed_verb_iri": predicate.get("verb_iri"),
        # THE SLOTS, accepted. Engine P splats this into the measure
        # (`func(state, **params)`); engines that do not read it ignore it, which is why
        # this is additive rather than a version bump on the dispatch contract.
        "params": accepted.params,
        # Tier-3 fix (2026-06-16): the resolved instance URN from
        # /resolve.provenance.instance_id. Threaded through so
        # execution-layer engines (specifically Engine DA's data
        # fetch) query the SAME URN that /resolve produced rather
        # than fabricating one from training data or
        # `dynamic_schema_map` context.
        #
        # Empty string when no instance matched upstream
        # (provenance.instance_resolved=false). Engines reading this
        # field must treat empty string as "no URN was resolved —
        # honestly admit not-found rather than invent one."
        #
        # **General observation (banked architectural finding, not
        # fixed in the Tier-3 scope):** the dispatch payload drops
        # the resolved instance_id GENERALLY — Engine A's /analyze
        # handler also reads `request["dataset_id"]`, which the
        # supervisor does not pass. **Engines compensate by
        # re-discovery: Engine A via `search_datahub`, Engine DA via
        # fabrication.** DA was the sharp edge because DA had no
        # search fallback so the re-discovery became invention; A is
        # in the same architectural shape, just with a less-loud
        # mitigation — A *re-resolves* something that was already
        # resolved upstream (wasted work at best; at worst a path
        # where A's search lands on a DIFFERENT asset than
        # resolution picked).
        #
        # **The general fix is to propagate the resolved identifier
        # to all instance-consuming engines and stop the re-discovery
        # pattern.** This Tier-3 fix is the FIRST INSTANCE of that
        # class-fix — the same way the first legacy-DNS source
        # default fix was the first instance of the DNS class-fix
        # closed by the writer-hunt sweep, and the way the first
        # compact-form canonicalization was the first instance of
        # the compact→full-IRI class-fix. The next-session class-fix
        # extends this `resolved_instance_id` consumption to Engine
        # A (and any future instance-consuming engine), retires the
        # search-then-paper-over pattern, and bakes a guard that
        # catches an engine handler reading an identifier-shaped
        # field from request that the supervisor doesn't pass.
        # Banked here so a future engineer reads the elevated
        # framing in the same place they read the dispatch payload
        # code. See state doc 2026-06-16 "Tier-3 four-layer fix" and
        # deploy checklist §4 Tier-3 entry for the full trace.
        "resolved_instance_id": telemetry.get("subject_instance_id", ""),
        # 2026-06-26 — the next-session class-fix the comment above
        # banked: also thread ``resolved_subject_uri`` (the idp:*
        # class URI the router resolved) so engines stop re-resolving
        # what's already known. Engine A's analyze handler historically
        # called Engine O's /resolve again with just task_description,
        # discarding the supervisor's already-resolved class — a
        # textbook [[resolution-discard-pattern]] instance. With this
        # field the engine can skip the redundant call AND surface the
        # deterministic class→entity_type mapping in the smolagent
        # prompt, eliminating the entity_type-selection variance the
        # 2026-06-26 "who owns customer 360" investigation exposed.
        # Engines that don't read this field ignore it (forward-
        # compatible introduction).
        "resolved_subject_uri": telemetry.get("subject_uri", ""),
        # 2026-07-21 — also thread the resolved instance's DISPLAY LABEL
        # alongside its id. `subject_instance_id` is the URN (e.g. a superset
        # dashboard whose URN key is a numeric id); an engine that humanizes the
        # URN for prose then titles the card with that number. The label is the
        # human display name the phone-book already matched. Forward it so
        # Engine A's traceLineage can title the answer with the real name
        # instead of the URN key. Empty when no instance resolved; engines that
        # don't read it ignore it (forward-compatible).
        "resolved_instance_label": telemetry.get("subject_instance_label", ""),
        # ADR-0038 — the DIRECT specialist leg of the E join. When a graph question
        # routes cleanly to its predicate provider, the supervisor dispatches HERE,
        # not via Engine A, so the analyst's discovery tool (which sends X-Trace-Id
        # as a header) never runs — this leg had no trace threading at all and E's
        # graph work orphaned. Carry the id in the BODY instead: Engine E's proxy
        # forwards it to the durable handler, whose observed_trace joins the caller's
        # trace and drops its join:pending-proxy tag. Additive and forward-compatible
        # in the same spirit as resolved_subject_uri above — only Engine E reads this
        # field today; every other specialist ignores it (their own direct-leg join is
        # a separate ledger item, deliberately not entangled with this one).
        "trace_id": config.trace_id or "",
    }

    context.log.info(
        f"Routing subtask via predicate {predicate.get('verb_iri')!r} "
        f"(owner_persona={answerer_persona}, domains={predicate_domains}) → {endpoint}"
    )

    # Engine handlers run an LLM agent loop, and slow Ollama backends can
    # take many minutes per multi-step query. Bumped from 300s to 900s for
    # the initial sandbox runs; then to 1800s after ADR-0017's per-verb
    # narrowing pushed Q3 lineage_src and Q8 catalog_superset into deeper
    # recursive walks that exceeded 900s. The cortex-bff polling loop's
    # 300-iteration timeout still prevents this from being truly infinite.
    # Must move in lockstep with restate_analyst/main.py's /analyze
    # proxy timeout, or the inner 900s ceiling defeats this one.
    # ADR-0038 — the DIRECT specialist leg's join for HTTP engines. The body already
    # carried `trace_id` (above) for Engine E, which reads the BODY because a Restate
    # handler never sees HTTP headers. But W, O and F join in FastAPI middleware that
    # reads the X-Trace-Id HEADER — and this POST sent none, so the id was on the wire
    # in a form none of them reads and all three orphaned on the direct leg. One seam,
    # three consumers: the same headers the Engine A leg already sends.
    # A DEAD ENGINE MUST STILL PRODUCE A UI PAYLOAD (2026-08-15).
    #
    # Witnessed, Dagster run a62ab191 (2026-08-14 20:12): routing was perfect, then the DA pod
    # died mid-request and this POST raised `RemoteDisconnected`. The op failed, so
    # `.collect()` never produced, so `generate_ui_payload` and `synthesize_stateful` were both
    # skipped as failed dependencies — and the user got a CARD WITH THEIR QUESTION AND NOTHING
    # ELSE. The failure was loud in Dagster, fully diagnosed in a stack trace, and communicated
    # nothing to the person who asked.
    #
    # So the transport failure becomes a RESULT rather than an exception, exactly as
    # `synthesize_stateful` below already does for Engine B ("a failure here must not poison an
    # otherwise-successful pipeline"). The same argument applies with more force here: this op
    # is fanned out, so one dead engine currently takes down the payload for every OTHER
    # subtask that succeeded.
    #
    # THE TRADE, STATED RATHER THAN HIDDEN: the Dagster run now goes GREEN where it used to go
    # red. That is a real loss of signal and it is the shape this repo distrusts most. It is
    # accepted because the redness was being paid for by rendering NOTHING, and a red run
    # nobody is watching is worth less than an honest card the user is already looking at. The
    # compensating controls are deliberate and all three are load-bearing: an ERROR log, output
    # metadata on the op, and a TYPED `status` in the result that flows to the UI and can be
    # counted. If a run-level red is wanted back, it belongs in a final op that reads the
    # collected results and fails when all of them are `engine_unreachable` — after the payload
    # has been produced, never instead of it.
    # ── REDEEM THE CALLER'S IDENTITY, for the verbs that require it ────────────────
    # This runs BEFORE the POST so a redemption failure never reaches the engine as an
    # under-privileged call. The seed's five inner asks each re-check the caller's Topaz
    # cell, so dispatching without alice's token does not fail open — it fails as five
    # 403s and an empty canvas, which is a WORSE failure than not dispatching, because it
    # looks like an entitlement problem.
    _caller_token = ""
    if _verb_needs_caller_identity(predicate):
        try:
            _caller_token = _redeem_caller_token(context, config)
            context.log.info(
                "execute_subtask: redeemed the caller's identity for %s — dispatching as "
                "the ORIGINAL caller, exactly as the button path does.",
                predicate.get("verb_iri"),
            )
        except Exception as _ident_exc:  # noqa: BLE001
            # THE CARD GETS THE DISPOSITION; THE LOG GETS THE EXCEPTION. A raw traceback
            # string on an answer card is the same species as leaking a function signature
            # into a 400 — it tells the person who asked nothing they can act on, and tells
            # anyone else more than they should see.
            _icause = getattr(_ident_exc, "cause", "") or "caller_identity_unavailable"
            _idetail = getattr(_ident_exc, "detail", "") or (
                f"{type(_ident_exc).__name__}: {_ident_exc}"
            )
            context.log.error(
                "execute_subtask: could not obtain the caller's identity for %s "
                "[cause=%s] (%s). REFUSING to dispatch under the service identity — that "
                "would reproduce the original 403 cell_not_entitled with a second cause "
                "hidden behind it.",
                predicate.get("verb_iri"), _icause, _idetail,
            )
            try:
                context.add_output_metadata({
                    "caller_identity_unavailable": True,
                    "endpoint": str(endpoint),
                    "cause": _icause,
                    # Dagster metadata is an OPERATOR surface, not a user one, so the raw
                    # exception belongs here as well as in the log.
                    "error": _idetail,
                })
            except Exception:  # pragma: no cover
                pass
            return {
                "persona": answerer_persona,
                "user_persona": config.user_persona,
                "answerer_persona": answerer_persona,
                "predicate_verb_iri": predicate.get("verb_iri"),
                "sub_query": sub_query,
                "expert_response": {
                    # A DISTINCT status, never `engine_unreachable`: the engine is fine.
                    # This is an identity fault, and naming it as one is what keeps the
                    # next diagnosis from starting at the wrong pod.
                    "status": "caller_identity_unavailable",
                    # THE REASON NAMES WHICH STEP FAILED. "vault_redemption_failed" was
                    # wrong for the most common case: when the supervisor cannot
                    # authenticate itself, the vault is never contacted at all.
                    "reason": _icause,
                    "message": _CALLER_IDENTITY_MESSAGES.get(
                        _icause, _CALLER_IDENTITY_DEFAULT_MESSAGE
                    ),
                    "data": "",
                    "sources": [],
                    # NO RAW EXCEPTION ON THE CARD. `_idetail` is in the log and in the
                    # op metadata above, which is where an operator looks; a person who
                    # asked a planning question is not that audience.
                    "error": _icause,
                },
            }

    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers=_telemetry_headers(config, caller_token=_caller_token) or None,
            timeout=1800,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as exc:
        # ValueError covers a 200 with an unparseable body — the engine answered with
        # something that is not JSON, which is a failure to answer, not a successful answer.
        _detail = f"{type(exc).__name__}: {exc}"
        context.log.error(
            "execute_subtask: engine at %s did not answer (%s). Returning a TYPED failure so "
            "generate_ui_payload still runs — the user gets a card that says what broke "
            "instead of a blank one.",
            endpoint, _detail,
        )
        try:
            context.add_output_metadata({
                "engine_unreachable": True,
                "endpoint": str(endpoint),
                "error": _detail,
            })
        except Exception:  # pragma: no cover — metadata must never mask the real failure
            pass
        return {
            "persona": answerer_persona,
            "user_persona": config.user_persona,
            "answerer_persona": answerer_persona,
            "predicate_verb_iri": predicate.get("verb_iri"),
            "sub_query": sub_query,
            "expert_response": {
                # Same vocabulary discipline as Engine DA's envelope: a distinct status, never
                # `success` carrying an explanation. `ungrounded` would be WRONG here — nothing
                # was attempted, so this is not an honest non-answer, it is an outage.
                "status": "engine_unreachable",
                "reason": "transport_failure",
                "message": (
                    "The engine that answers this kind of question could not be reached, so "
                    "no answer was produced. This is a system fault, not a result."
                ),
                "data": "",
                "sources": [],
                "error": _detail,
            },
        }

    trace = data.get("execution_trace")
    if trace:
        context.log.info(f"🧠 Agent Reasoning Trajectory:\n{trace}")

    # Phase 3 source attribution: if the engine returned a `sources`
    # list, materialize it as a Dagster asset so the gateway can
    # project it into the typed `sources` SSE event. The asset name
    # `subtask_sources` mirrors the subtask_routing_decision /
    # subtask_graph_trace pattern. Engines that haven't been updated
    # yet (E and A, until follow-up) return responses without a
    # `sources` key — the supervisor just doesn't materialize the
    # asset, gateway doesn't emit, UI shows the empty SourcesTrail
    # state. Safe per-engine rollout.
    try:
        _log_subtask_sources_asset(
            context,
            engine_response=data,
            verb_iri=predicate.get("verb_iri"),
            sub_query=sub_query,
        )
    except Exception as src_err:  # pragma: no cover — best-effort
        context.log.warning(
            "Failed to log subtask_sources materialization "
            "(non-fatal — routing/answer continue): %s", src_err,
        )

    # Bug 2: if the engine reported a STRUCTURED access denial, materialize
    # it so the gateway projects a typed access_denied SSE event → the UI's
    # request-access flow. No-op for any other status.
    try:
        _log_subtask_access_denied_asset(
            context, engine_response=data, sub_query=sub_query,
        )
    except Exception as ad_err:  # pragma: no cover — best-effort
        context.log.warning(
            "Failed to log subtask_access_denied materialization "
            "(non-fatal): %s", ad_err,
        )

    _inject_predicate_output_uri(data, predicate)

    return {
        "persona": answerer_persona,
        "user_persona": config.user_persona,
        "answerer_persona": answerer_persona,
        "predicate_verb_iri": predicate.get("verb_iri"),
        "sub_query": sub_query,
        "expert_response": data,
    }


@op(ins={"results": In(List[Dict[str, Any]])}, out=Out(Dict[str, Any]))
def synthesize_stateful(context, config: SupervisorQueryConfig, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Fans-in the results from all parallel sub-tasks and forwards them to
    Engine B (LangGraph Support) to maintain conversational memory.

    Engine B is optional in some deployments (e.g. sandbox runs with
    engineB.enabled=false). A failure here must not poison an otherwise-
    successful pipeline — execute_subtask + generate_ui_payload have
    already produced the user-visible payload. Log and return a stub.
    """
    try:
        response = requests.post(
            f"{LANGGRAPH_SUPPORT_SVC_URL}/support",
            json={
                "thread_id": config.thread_id,
                "user_id": config.user_id,
                "user_query": config.user_query,
                "dagster_context": results,
            },
            timeout=300,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError as exc:
        context.log.warning(
            f"Engine B (LangGraph Support) unreachable at {LANGGRAPH_SUPPORT_SVC_URL}: {exc}. "
            "Skipping conversational-memory synthesis."
        )
        return {"status": "skipped", "reason": "engine_b_unreachable"}
    except requests.exceptions.HTTPError as exc:
        context.log.warning(
            f"Engine B returned {exc.response.status_code if exc.response else '?'}. "
            "Skipping conversational-memory synthesis."
        )
        return {"status": "skipped", "reason": "engine_b_error"}


@op(ins={"results": In(List[Dict[str, Any]])}, out=Out(Any))
def generate_ui_payload(context, results, config: SupervisorQueryConfig) -> Any:
    """
    Takes the aggregated results array from the Domain Agents and calls
    Engine F (Presentation Agent) to map the structured data to a Server-Driven UI
    Component layout. Returns the result as a raw JSON string to avoid truncation.
    """
    # Extract referenced URIs from all experts to send back for the Data Bindings HUD
    all_uris = []
    for res in results:
        expert_res = res.get("expert_response", {})
        all_uris.extend(expert_res.get("referenced_uris", []))
    
    # Deduplicate URIs
    unique_uris = list(set(all_uris))
    
    # 1. Check if the graph experts failed to find any data
    data_str = json.dumps(results)
    if "EMPTY_RESULT_SET" in data_str or "No hazards related to" in data_str:
        context.log.warning("Empty graph results detected. Short-circuiting UI generation.")
        
        # Immediately return the grounded Null State payload to the UI
        # Wrapped in DashboardUI format: { components: [...] }
        ui_payload_dict = {
            "components": [{
                "archetype": "KNOWLEDGE_DOCUMENT",
                "subject_concept": "system://mesh/alert",
                "markdown_content": "# ⚠️ SYSTEM ALERT\nNo relevant records or hazards found in the Graph Database for this query. Do not proceed without manual verification."
            }]
        }
        yield Output(
            value=ui_payload_dict,
            metadata={
                "ui_json_payload": MetadataValue.json(ui_payload_dict),
                "referenced_uris": MetadataValue.json(unique_uris)
            }
        )
        return

    # 2. If data exists, proceed with calling Engine F (Presentation Agent).
    # Per ADR-0009: Engine F's UI archetype is driven by the *user* persona
    # (what chrome should I render?) — distinct from the *answerer* persona
    # carried inside each subtask's response (what response shape did the
    # engine produce?). We surface both so Engine F can choose.
    #
    # ADR-0017: extract the agent's declared output_uri (echoed in
    # final_answer per the per-verb prompt block) and forward it so
    # Engine F can do a deterministic predicate-graph lookup instead of
    # asking the BAML LLM to classify the data shape. For multi-engine
    # composite responses we take the first non-empty output_uri; full
    # multi-archetype composition is an ADR-0017 open item. When no
    # subtask declared an output_uri (engines pre-ADR-0017), Engine F
    # falls back to legacy BAML DesignUI automatically.
    agent_output_uri = None
    for res in results:
        expert_res = res.get("expert_response", {})
        if isinstance(expert_res, dict) and expert_res.get("output_uri"):
            agent_output_uri = expert_res["output_uri"]
            break

    response = requests.post(
        f"{PRESENTATION_AGENT_SVC_URL}/render_ui",
        json={
            "raw_data": results,
            "user_persona": config.user_persona,
            # Legacy alias: keep `persona` set to user_persona for engines
            # that haven't migrated. Engine F's current implementation reads
            # `persona` to pick a chrome archetype, which is the user-side
            # concern.
            "persona": config.user_persona,
            "output_uri": agent_output_uri,
            # Names the caller so Engine F can select from ITS registered menu rather than
            # from a global table that answers on behalf of clients which never advertised
            # those capabilities.
            "frontend_id": config.frontend_id or None,
        },
        timeout=300,
    )
    response.raise_for_status()
    ui_payload_dict = response.json()

    # ADR-0017 follow-up: Engine F emits X-Presentation-Path naming
    # which of the four paths served the request — deterministic-
    # document, archetype-hardened, fallback-designui, or
    # fallback-no-output-uri. Surface it in Dagster metadata now so
    # operators can see the path per request, and so the ADR-0015
    # routing_decisions audit table (when it lands) has a single field
    # to record. Alerting target: fallback-* exceeding a threshold
    # indicates capability-coverage drift (engines emitting output URIs
    # Engine F doesn't have a capability triple for).
    presentation_path = response.headers.get("X-Presentation-Path", "unknown")
    context.log.info(
        f"Generated UI Payload for user_persona {config.user_persona} "
        f"via presentation_path={presentation_path}"
    )
    yield Output(
        value=ui_payload_dict,
        metadata={
            "ui_json_payload": MetadataValue.json(ui_payload_dict),
            "referenced_uris": MetadataValue.json(unique_uris),
            "presentation_path": MetadataValue.text(presentation_path),
        }
    )


# Check Dagster's built-in dev flag. 
# Defaults to False in production (where dagster dev is not used).
IS_DEV = os.getenv("DAGSTER_IS_DEV_CLI") == "1"

# Use in_process locally to save RAM. Use multiprocess in Prod for parallel speed.
# We limit max_concurrent to 5 to protect cloud resources from fork-bombing.
mesh_executor = in_process_executor if IS_DEV else multiprocess_executor.configured({"max_concurrent": 5})

@op(
    ins={"results": In(List[Dict[str, Any]]), "ui_payload": In(Any)},
    out=Out(Nothing),
)
def assert_every_engine_answered(context, results: List[Dict[str, Any]], ui_payload) -> None:
    """TAKE THE RED — fail the run when an engine did not answer, AFTER the card exists.

    `execute_subtask` now returns a typed `engine_unreachable` result instead of raising, so
    `generate_ui_payload` still runs and the user gets a card saying what broke rather than a
    blank one. That repair, on its own, bought the honest card by making the RUN GREEN — and a
    green run over a crashed subtask is the first-failure-direction lie (effects claimed, not
    landed) relocated to the orchestration layer. Exactly the thing the rest of this work
    exists to remove.

    So both, in the only order that yields both:

        execute_subtask returns a typed failure   -> the payload is produced
        generate_ui_payload records its output    -> the user has a card
        THIS op reads the results and fails       -> the run is RED

    THE ORDERING IS THE WHOLE DESIGN, and `ui_payload` is an input for that reason alone — it
    is never read. Taking it as an input is what makes Dagster schedule this op strictly after
    `generate_ui_payload` has emitted and recorded its output, so the gateway (which fetches
    that step's output value from run metadata) still finds the card on a failed run. Fail
    earlier, or in parallel, and you are back to red-with-a-blank-card, which is where this
    started.

    Red-with-honest-card is loud and correct. Green-with-blank-card was the defect.
    """
    unreachable = [
        r for r in results
        if isinstance(r, dict)
        and (r.get("expert_response") or {}).get("status") == "engine_unreachable"
    ]
    if not unreachable:
        return
    detail = "; ".join(
        f"{(r.get('predicate_verb_iri') or 'unknown-verb')}: "
        f"{(r.get('expert_response') or {}).get('error', 'no detail')}"
        for r in unreachable
    )
    context.log.error(
        "%d of %d subtask(s) did not reach their engine. The UI payload WAS produced and the "
        "user has an honest card; this failure exists so the run is not reported as clean.",
        len(unreachable), len(results),
    )
    raise Failure(
        description=(
            f"{len(unreachable)} of {len(results)} subtask(s) could not reach their engine. "
            f"The UI payload was still produced (see generate_ui_payload) — this op fails "
            f"AFTER it so the run is honest without costing the user their card. {detail}"
        ),
        metadata={
            "unreachable_subtasks": MetadataValue.int(len(unreachable)),
            "total_subtasks": MetadataValue.int(len(results)),
            "detail": MetadataValue.text(detail),
        },
    )


@job(executor_def=mesh_executor)
def supervisor_query_job():
    """
    Dynamic Fan-Out/Fan-In Workflow:
    1. Engine O decomposes the complex query into persona-specific tasks.
    2. Engine E executes each task in parallel.
    3. Results are collected and synthesized.
    """
    # Create the dynamic fan-out paths
    dynamic_tasks = create_task_plan()
    
    # Map each dynamic task to the execution op
    # .map() will spawn N concurrent execute_subtask ops
    executed_results = dynamic_tasks.map(execute_subtask)
    
    # Collect the results
    collected_results = executed_results.collect()
    
    # 1. Statefully save the results into the thread history using Engine B
    synthesize_stateful(results=collected_results)
    
    # 2. Map the domain results to the React UI Component using Engine F
    ui_payload = generate_ui_payload(results=collected_results)

    # 3. THEN, and only then, fail the run if an engine never answered. The dependency on
    #    `ui_payload` is the ordering guarantee, not a data flow — see the op's docstring.
    assert_every_engine_answered(results=collected_results, ui_payload=ui_payload)
