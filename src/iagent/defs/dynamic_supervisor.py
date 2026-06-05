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
ONTOLOGY_SVC_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://ontology-svc.default.svc.cluster.local:8084")
NEO4J_EXPERT_SVC_URL = os.getenv("NEO4J_EXPERT_SVC_URL", "http://neo4j-expert-svc.default.svc.cluster.local:8086")
DATAHUB_WRAPPER_URL = os.getenv("DATAHUB_WRAPPER_URL", "http://datahub-wrapper-svc.default.svc.cluster.local:8085")
LANGGRAPH_SUPPORT_SVC_URL = os.getenv("LANGGRAPH_SUPPORT_SVC_URL", "http://langgraph-agent-svc.default.svc.cluster.local:8082")
PRESENTATION_AGENT_SVC_URL = os.getenv("PRESENTATION_AGENT_SVC_URL", "http://presentation-agent-svc.default.svc.cluster.local:8087")
RESTATE_ANALYST_URL = os.getenv("RESTATE_ANALYST_URL", "http://restate-agent-svc.default.svc.cluster.local:8081")
DATA_ANALYST_URL = os.getenv("DATA_ANALYST_URL", "http://data-analyst-svc.default.svc.cluster.local:8089")

# ---------------------------------------------------------------------------
# Add baml_shared to Python path so we can import the generated client
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
if str(_BAML_CLIENT_PATH) not in sys.path:
    sys.path.insert(0, str(_BAML_CLIENT_PATH))

from baml_client import b

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

#: ADR-0008 follow-up — yellow-zone upper bound. Top-1 candidates with score
#: between THRESHOLD (low) and THRESHOLD_HIGH (high) trigger a BAML
#: VerifyVerbChoice call: an LLM with the verb's description in hand decides
#: whether the BM25 winner is actually right. Above THRESHOLD_HIGH the
#: supervisor trusts the score and skips the verifier. Below THRESHOLD it
#: routes straight to the generalist fallback (existing behavior).
#:
#: The default 0.85 means the verifier runs on roughly the middle of the
#: confidence distribution; tune via PREDICATE_FALLBACK_SCORE_THRESHOLD_HIGH
#: against the actual score distribution your registry produces.
_FALLBACK_SCORE_THRESHOLD_HIGH_DEFAULT = float(
    os.getenv("PREDICATE_FALLBACK_SCORE_THRESHOLD_HIGH", "0.85")
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
    # ADR-0008 fallback policy:
    predicate_fallback_score_threshold: float = _FALLBACK_SCORE_THRESHOLD_DEFAULT
    # ADR-0008 follow-up — yellow-zone upper bound (see env-var docs above).
    predicate_fallback_score_threshold_high: float = _FALLBACK_SCORE_THRESHOLD_HIGH_DEFAULT


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


def _resolve_predicate_endpoint(
    context,
    user_query: str,
    entitled_domains: List[str],
) -> tuple[str, Dict[str, Any] | None]:
    """Ask Engine O's /search_predicates for the best-matching predicate.

    Returns ``(status, predicate_or_none)``:

      * ``("matched", predicate_dict)`` — Engine O found a candidate. The
        caller applies the score threshold (ADR-0008) to decide whether
        to use the specialist or fall back to Engine A.
      * ``("no_match", None)`` — Engine O returned ``found=false``. The
        registry has no predicate for this NL; ADR-0008 says fall back
        to Engine A as a generalist.
      * ``("infra_error", None)`` — could not reach Engine O, Engine O
        returned 5xx, or the response was malformed. ADR-0008 says
        **do not** fall back; abort the subtask so the infrastructure
        signal is loud.

    Per ADR-0009 Step F'.6, Weaviate hybrid search is the only routing
    path: ``user_query`` goes straight to the vector store, which scores
    against the registered predicates' humanized verb + synonyms +
    description.
    """
    try:
        resp = requests.post(
            f"{ONTOLOGY_SVC_URL}/search_predicates",
            json={
                "query": user_query,
                "entitled_domains": entitled_domains,
                "limit": 5,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        # Per ADR-0008: infrastructure failure must surface, not be masked
        # by the LLM fallback. Return infra_error so execute_subtask aborts.
        context.log.error(
            f"search_predicates infrastructure error for query={user_query!r}: "
            f"{exc}"
        )
        return _ROUTING_INFRA_ERROR, None

    if not data.get("found"):
        context.log.warning(
            f"search_predicates no_match query={user_query!r} "
            f"reason={data.get('reason')!r}"
        )
        return _ROUTING_NO_MATCH, None

    candidates = data.get("candidates", [])
    if not candidates:
        # found=true with no candidates would be an Engine-O bug; treat as
        # no_match (still a registry-shape failure the LLM might handle).
        context.log.warning(
            f"search_predicates returned found=true with no candidates "
            f"for query={user_query!r} — treating as no_match"
        )
        return _ROUTING_NO_MATCH, None

    head = candidates[0]
    context.log.info(
        f"search_predicates matched query={user_query!r} "
        f"verb_iri={head.get('verb_iri')!r} score={head.get('score')}"
    )
    return _ROUTING_MATCHED, head


def _verify_verb_choice_with_baml(
    context,
    query: str,
    predicate: Dict[str, Any],
) -> tuple[bool, str]:
    """ADR-0008 follow-up — yellow-zone LLM verifier.

    Returns ``(primary_is_correct, reasoning)``. On any BAML failure
    (network, schema, etc.) returns ``(True, "verifier_unavailable")`` so
    we degrade to the existing trust-the-BM25-winner behavior rather than
    masking calibration outages as systematic verb rejections. Same logic
    as ADR-0008's bias against silent degradation: the supervisor should
    distinguish "the LLM said no" from "the LLM never answered."
    """
    import asyncio  # local import — the supervisor is sync-by-default
    try:
        coro = b.VerifyVerbChoice(
            query=query,
            verb_iri=str(predicate.get("verb_iri") or ""),
            verb_description=str(predicate.get("description") or ""),
            verb_synonyms_json=json.dumps(list(predicate.get("verb_synonyms") or [])),
        )
        result = asyncio.run(coro) if asyncio.iscoroutine(coro) else coro
        return (bool(result.primary_is_correct), str(result.reasoning or ""))
    except Exception as exc:  # noqa: BLE001
        context.log.warning(
            "VerifyVerbChoice failed verb_iri=%s err=%s — degrading to trust-primary",
            predicate.get("verb_iri"),
            exc,
        )
        return (True, "verifier_unavailable")


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

    # Per ADR-0009 Step F'.6: routing is NL → Weaviate hybrid. The
    # supervisor passes the subtask's natural-language sub_query straight
    # to /search_predicates; Engine O matches against humanized verb +
    # synonyms + description.
    routing_query = sub_query or config.user_query

    status, predicate = _resolve_predicate_endpoint(
        context,
        routing_query,
        list(config.entitled_domains),
    )

    # ADR-0008 routing decision table:
    #   matched + score ≥ threshold  → specialist
    #   matched + score <  threshold → Engine A fallback (low_confidence)
    #   no_match                      → Engine A fallback (no_predicate_matched)
    #   infra_error                   → abort with INFRA_ERROR signal
    if status == _ROUTING_INFRA_ERROR:
        # Infrastructure outage — must surface, NOT mask via fallback.
        # Same reasoning that drove the ADR-0009 Cypher-fallback removal:
        # silent degradation hides the signal ops needs to fix the outage.
        context.log.error(
            f"Aborting subtask due to routing infrastructure error "
            f"(query={routing_query!r}). Engine O / Weaviate must recover "
            f"before this subtask can be retried."
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
                    "error persists, the operator should check Engine O and "
                    "the Weaviate Predicate collection."
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

    # status == _ROUTING_MATCHED — apply the threshold per ADR-0008.
    assert predicate is not None
    score = predicate.get("score")
    threshold = config.predicate_fallback_score_threshold
    threshold_high = config.predicate_fallback_score_threshold_high

    # ADR-0008 telemetry: emit the score for histogram/aggregation.
    context.log.info(
        "predicate_routing_score score=%s threshold=%s threshold_high=%s verb_iri=%s",
        score if score is not None else "none",
        threshold,
        threshold_high,
        predicate.get("verb_iri"),
    )

    if score is None or score < threshold:
        # Routing is guessing; Engine A as a generalist may do better than
        # a low-confidence specialist whose synonyms only weakly matched.
        return _call_engine_a_fallback(
            context,
            sub_query=sub_query,
            config=config,
            fallback_reason="low_confidence",
            fallback_score=score,
            rejected_predicate=predicate,
        )

    # ADR-0008 follow-up — yellow-zone LLM verifier.
    #
    # Between THRESHOLD and THRESHOLD_HIGH the BM25 + anti-synonym score is
    # "good but not certain". Ask a BAML LLM with the verb's description
    # in hand whether the proposed verb actually answers the query. If
    # not, fall back to Engine A as a generalist. Catches the
    # confidently-wrong-routing failure mode (e.g. the 5fee663d run
    # where mesh:traceLineage scored 0.71 for "what tables do you have?").
    if score < threshold_high:
        primary_is_correct, reasoning = _verify_verb_choice_with_baml(
            context, routing_query, predicate,
        )
        context.log.info(
            "yellow_zone_verify primary_is_correct=%s score=%s verb_iri=%s reasoning=%r",
            primary_is_correct,
            score,
            predicate.get("verb_iri"),
            reasoning,
        )
        if not primary_is_correct:
            return _call_engine_a_fallback(
                context,
                sub_query=sub_query,
                config=config,
                fallback_reason="llm_rejected_in_yellow_zone",
                fallback_score=score,
                rejected_predicate=predicate,
            )
        # Verifier said yes; fall through to specialist dispatch.

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
