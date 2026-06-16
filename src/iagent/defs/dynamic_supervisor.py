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
from typing import List, Dict, Any

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
    In,
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
    # ADR-0009 Step F'.2 / F'.3 additions:
    user_persona: str = "MECHANIC"
    entitled_domains: List[str] = []
    entity_refs: List[str] = []
    # Accepted for legacy-config compatibility (Step F'.6 stopped using it).
    candidate_verb: str = ""
    # ADR-0008 fallback policy (ADR-0018 simplified: single threshold
    # against the LLM's confidence from /classify_predicate, replacing the
    # BM25-era yellow-zone band + VerifyVerbChoice gate).
    predicate_fallback_score_threshold: float = _FALLBACK_SCORE_THRESHOLD_DEFAULT


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
        response = requests.post(
            f"{ONTOLOGY_SVC_URL}/plan",
            json={
                "query": config.user_query,
                "domain": config.domain
            },
            timeout=300,
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
) -> tuple[str, float, str]:
    """Ask Engine O's /resolve for the subject ontology class.

    /resolve does vector-recall (Weaviate hybrid over OntologyClass) +
    LLM-precision (ClassifyDomainIntent via TypeBuilder dynamic enum).
    Returns ``(subject_uri, confidence, reasoning, instance_id)``. On
    failure or UNKNOWN return ``("UNKNOWN", 0.0, "<reason>", "")`` so
    the downstream predicate classifier still runs against the raw query.

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
        resp = requests.post(
            f"{ONTOLOGY_SVC_URL}/resolve",
            json={"query": user_query, "domain": domain or "MAINTENANCE"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        context.log.warning(
            "resolve_subject failed for query=%r: %s — predicate classifier "
            "will see subject_uri=UNKNOWN",
            user_query, exc,
        )
        return ("UNKNOWN", 0.0, f"/resolve unreachable: {exc}", "")

    provenance = data.get("provenance") or {}
    return (
        str(data.get("resolved_uri") or "UNKNOWN"),
        float(data.get("confidence_score") or 0.0),
        str(data.get("reasoning") or ""),
        str(provenance.get("instance_id") or ""),
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


def _classify_route(
    context,
    user_query: str,
    entitled_domains: List[str],
    routing_domain: str,
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
    subject_uri, subject_conf, subject_reason, subject_instance_id = _resolve_subject(
        context, user_query, routing_domain,
    )

    # ADR-0019 Contract B — UNKNOWN-subject short-circuit. No
    # /find_compatible_verbs (would be empty), no /classify_predicate
    # (would be unconstrained and could emit a confident wrong verb).
    # The honest answer is the generalist; route there directly.
    if subject_uri == "UNKNOWN":
        context.log.info(
            "routing_decision subject_uri=UNKNOWN subject_conf=%s "
            "→ generalist fallback (ADR-0019 Contract B: no LLM call "
            "without subject grounding)",
            subject_conf,
        )
        return _ROUTING_NO_MATCH, None, {
            "subject_uri": "UNKNOWN",
            "subject_confidence": subject_conf,
            "subject_reasoning": subject_reason,
            "verb_iri": "UNKNOWN",
            "verb_confidence": 0.0,
            "verb_reasoning": (
                "ADR-0019 Contract B: /resolve returned UNKNOWN, so the "
                "router short-circuits to the generalist without asking "
                "the LLM to pick a verb. Confident specialist routing "
                "without subject grounding is the regression shape "
                "ADR-0019 deletes."
            ),
            "candidate_verbs": [],
            "compatible_verb_iris": [],
        }

    compatible_verbs, find_err = _find_compatible_verbs(
        context, subject_uri, entitled_domains,
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
        context.log.info(
            "routing_decision subject_uri=%s subject_conf=%s "
            "no_compatible_verbs_in_neo4j → generalist fallback",
            subject_uri, subject_conf,
        )
        return _ROUTING_NO_MATCH, None, {
            "subject_uri": subject_uri,
            "subject_confidence": subject_conf,
            "subject_reasoning": subject_reason,
            "verb_iri": "UNKNOWN",
            "verb_confidence": 0.0,
            "verb_reasoning": "Neo4j marks zero verbs as compatible with this subject.",
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
            "compatible_verb_iris": compatible_verb_iris,
            "error": str(exc),
        }

    verb_iri = str(data.get("resolved_verb_iri") or "UNKNOWN")
    verb_conf = float(data.get("confidence_score") or 0.0)
    verb_reason = str(data.get("reasoning") or "")
    predicate = data.get("predicate")
    candidates = list(data.get("candidate_verb_iris") or [])

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
                }
                break

    telemetry = {
        "subject_uri": subject_uri,
        "subject_confidence": subject_conf,
        "subject_reasoning": subject_reason,
        # Resolved instance URN (e.g. urn:li:dataset:... for catalog
        # assets, urn:instance:... for maintenance instances) from
        # /resolve.provenance.instance_id. Empty string when no
        # instance matched. Propagated to dispatch payload as
        # `resolved_instance_id` so execution-layer engines (Engine DA)
        # query the SAME URN that /resolve produced rather than
        # fabricating one. See Tier-3 fix (state doc 2026-06-16).
        "subject_instance_id": subject_instance_id,
        "compatible_verb_iris": compatible_verb_iris,
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

    response = requests.post(
        f"{RESTATE_ANALYST_URL}/analyze",
        json=payload,
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

    # Domain used for the BAML domain field on /resolve. Same value used
    # for the /classify_predicate domain hint. First entitled domain
    # wins; falls back to MAINTENANCE if no scope (preserves
    # backward-compatible behavior with the prior router).
    routing_domain = (
        list(config.entitled_domains)[0]
        if config.entitled_domains else "MAINTENANCE"
    )

    status, predicate, telemetry = _classify_route(
        context,
        routing_query,
        list(config.entitled_domains),
        routing_domain=routing_domain,
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
    response = requests.post(endpoint, json=payload, timeout=1800)
    response.raise_for_status()

    data = response.json()

    trace = data.get("execution_trace")
    if trace:
        context.log.info(f"🧠 Agent Reasoning Trajectory:\n{trace}")

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
    generate_ui_payload(results=collected_results)
