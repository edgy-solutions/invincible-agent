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

def _resolve_predicate_endpoint(
    context,
    user_query: str,
    entitled_domains: List[str],
) -> Dict[str, Any] | None:
    """Ask Engine O's /search_predicates for the best-matching predicate.

    Per ADR-0009 Step F'.6, Weaviate hybrid search is the only routing
    path: ``user_query`` goes straight to the vector store, which scores
    against the registered predicates' humanized verb + synonyms +
    description. No exact-match fallback — if Engine O returns 503
    (Weaviate unreachable) or ``found=false``, the caller must fail loud.
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
        context.log.error(
            f"search_predicates failed for query={user_query!r}: {exc}"
        )
        return None

    if not data.get("found"):
        context.log.warning(
            f"No predicate found for query={user_query!r}; "
            f"reason={data.get('reason')}"
        )
        return None

    candidates = data.get("candidates", [])
    if not candidates:
        return None
    head = candidates[0]
    context.log.info(
        f"search_predicates picked {head.get('verb_iri')!r} "
        f"(score={head.get('score')})"
    )
    return head


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
    # synonyms + description. No exact-match fallback in Engine O — a
    # routing miss surfaces here as ``predicate is None`` and the subtask
    # aborts loud.
    routing_query = sub_query or config.user_query

    predicate = _resolve_predicate_endpoint(
        context,
        routing_query,
        list(config.entitled_domains),
    )

    if predicate is None:
        # No fallback — per ADR-0009 the predicate graph IS the routing
        # mechanism. A miss here means: engine not registered, no matching
        # synonyms/description, or the user is not entitled to any engine
        # that serves this verb. All three are operator-visible failure
        # modes.
        context.log.error(
            f"No predicate matched query={routing_query!r} for entitled_domains="
            f"{list(config.entitled_domains)}; aborting subtask."
        )
        return {
            "persona": config.user_persona,
            "user_persona": config.user_persona,
            "answerer_persona": None,
            "sub_query": sub_query,
            "expert_response": {
                "status": "FAILED",
                "summary": (
                    f"No registered predicate matches '{verb_label}' under "
                    f"your entitled domains. Either the verb is unsupported "
                    f"or you lack scope to any engine that serves it."
                ),
            },
        }

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
    }

    context.log.info(
        f"Routing subtask via predicate {predicate.get('verb_iri')!r} "
        f"(owner_persona={answerer_persona}, domains={predicate_domains}) → {endpoint}"
    )

    response = requests.post(endpoint, json=payload, timeout=300)
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
def synthesize_stateful(config: SupervisorQueryConfig, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Fans-in the results from all parallel sub-tasks and forwards them to
    Engine B (LangGraph Support) to maintain conversational memory.
    """
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
        },
        timeout=300,
    )
    response.raise_for_status()
    ui_payload_dict = response.json()

    context.log.info(f"Generated UI Payload for user_persona {config.user_persona}")
    yield Output(
        value=ui_payload_dict,
        metadata={
            "ui_json_payload": MetadataValue.json(ui_payload_dict),
            "referenced_uris": MetadataValue.json(unique_uris)
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
