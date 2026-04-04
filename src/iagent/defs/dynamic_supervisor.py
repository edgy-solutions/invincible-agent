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
RESTATE_ANALYST_SVC_URL = os.getenv("RESTATE_ANALYST_SVC_URL", "http://restate-agent-svc.default.svc.cluster.local:8081")

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
    """Configuration for the supervisor job."""
    user_query: str
    thread_id: str
    persona: str
    domain: str = "MAINTENANCE"
    task_plan_json: str = ""  # Optional pre-computed plan from BFF
    user_id: str = "default_testing_user"


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

@op(ins={"task_def": In(Dict[str, Any])}, out=Out(Dict[str, Any]))
def execute_subtask(context, config: SupervisorQueryConfig, task_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes a single decomposed sub-task by calling Engine E (Neo4j Graph Expert).
    This op runs in parallel for each dynamically generated task.
    """
    persona = task_def.get("target_persona", "MECHANIC")
    sub_query = task_def.get("sub_query", "")
    domain = task_def.get("domain", "MAINTENANCE") # Expected to be passed from create_task_plan if plan is domain-aware

    # 🔗 ROUTING LOGIC: Fan-out to the correct domain-specific engine
    if domain == "DATA_ENGINEERING":
        # DATA_ENGINEERING tasks are routed to Engine A (Restate Analyst)
        engine_url = f"{RESTATE_ANALYST_SVC_URL}/analyze"
    else:
        # Default to Engine E (Neo4j Graph Expert) for MAINTENANCE and SUSTAINMENT
        engine_url = f"{NEO4J_EXPERT_SVC_URL}/query_graph"

    # Fetch dynamic schema map if domain is DATA_ENGINEERING
    dynamic_schema_map = ""
    if domain == "DATA_ENGINEERING":
        dynamic_schema_map = get_datahub_context(DATAHUB_WRAPPER_URL)

    if domain == "DATA_ENGINEERING":
        payload = {
            "task_description": sub_query,
            "dataset_id": "dynamic_datahub_search",
            "dynamic_schema_map": dynamic_schema_map,
            "persona": persona,
            "domain": domain,
            "user_id": config.user_id
        }
    else:
        payload = {
            "user_query": sub_query,
            "persona": persona,
            "domain": domain, # Pass domain for strict node labeling in Cypher
            "dynamic_schema_map": dynamic_schema_map,
            "user_id": config.user_id
        }

    response = requests.post(
        engine_url,
        json=payload,
        timeout=300,
    )
    response.raise_for_status()
    
    data = response.json()
    
    # Write the agent's internal monologue to the Dagster UI!
    trace = data.get("execution_trace")
    if trace:
        context.log.info(f"🧠 Agent Reasoning Trajectory:\n{trace}")
    
    return {
        "persona": persona,
        "domain": domain,
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

    # 2. If data exists, proceed with calling Engine F (Presentation Agent)
    response = requests.post(
        f"{PRESENTATION_AGENT_SVC_URL}/render_ui",
        json={
            "raw_data": results,
            "persona": config.persona,
        },
        timeout=300,
    )
    response.raise_for_status()
    ui_payload_dict = response.json()
    
    context.log.info(f"Generated UI Payload for persona {config.persona}")
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
