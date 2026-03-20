"""
Phase 2: Dynamic Supervisor & Fan-Out

Dagster job that takes a complex multi-domain query, asks Engine O to decompose
it into Persona-specific sub-tasks, fans those out concurrently to Engine E 
(Neo4j Graph Expert), and synthesizes the results.
"""

import json
import requests
import sys
import os
from pathlib import Path
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Service Discovery — defaults to K8s internal DNS, overridden via env
# ---------------------------------------------------------------------------
ONTOLOGY_SVC_URL = os.getenv("ONTOLOGY_SVC_URL", "http://ontology-svc.default.svc.cluster.local:8084")
NEO4J_EXPERT_SVC_URL = os.getenv("NEO4J_EXPERT_SVC_URL", "http://neo4j-expert-svc.default.svc.cluster.local:8086")
LANGGRAPH_SUPPORT_SVC_URL = os.getenv("LANGGRAPH_SUPPORT_SVC_URL", "http://langgraph-agent-svc.default.svc.cluster.local:8082")
PRESENTATION_AGENT_SVC_URL = os.getenv("PRESENTATION_AGENT_SVC_URL", "http://presentation-agent-svc.default.svc.cluster.local:8087")

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
)


class SupervisorQueryConfig(Config):
    """Configuration for the supervisor job."""
    user_query: str
    thread_id: str
    persona: str


@op(out=DynamicOut(Dict[str, Any]))
def create_task_plan(config: SupervisorQueryConfig):
    """
    Calls Engine O (Ontology Reasoner) to decompose a complex query into a
    SupervisorTaskPlan containing persona-specific sub-tasks.
    Yields each sub-task as a DynamicOutput for downstream fan-out.
    """
    # 1. Ask Engine O for the plan
    response = requests.post(
        f"{ONTOLOGY_SVC_URL}/plan",
        json={"query": config.user_query},
        timeout=30,
    )
    response.raise_for_status()
    plan = response.json()

    # 2. Extract personas and broadcast intermediate roster
    tasks = plan.get("tasks", [])
    personas = [task.get("target_persona") for task in tasks if task.get("target_persona")]
    
    yield AssetMaterialization(
        asset_key=["active_agent_roster"],
        metadata={
            "personas": MetadataValue.text(json.dumps(personas))
        }
    )

    # 3. Fan-out: yield each task dynamically
    for idx, task in enumerate(tasks):
        # We must provide a valid mapping_key for each dynamic output
        yield DynamicOutput(
            value=task,
            mapping_key=f"task_{idx}"
        )


@op(ins={"task_def": In(Dict[str, Any])}, out=Out(Dict[str, Any]))
def execute_subtask(task_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes a single decomposed sub-task by calling Engine E (Neo4j Graph Expert).
    This op runs in parallel for each dynamically generated task.
    """
    persona = task_def.get("target_persona", "MECHANIC")
    sub_query = task_def.get("sub_query", "")

    # Call Engine E (durable execution via Restate + smolagents)
    response = requests.post(
        f"{NEO4J_EXPERT_SVC_URL}/query_graph",
        json={
            "user_query": sub_query,
            "persona": persona,
        },
        timeout=300, # 5 minutes to allow complex agent reasoning/looping
    )
    response.raise_for_status()
    
    # Return the BAML-formatted GraphExpertResponse JSON
    return {
        "persona": persona,
        "sub_query": sub_query,
        "expert_response": response.json(),
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
    # 1. Check if the graph experts failed to find any data
    data_str = json.dumps(results)
    if "EMPTY_RESULT_SET" in data_str or "No hazards related to" in data_str:
        context.log.warning("Empty graph results detected. Short-circuiting UI generation.")
        
        # Immediately return the grounded Null State payload to the UI
        # This matches the KNOWLEDGE_DOCUMENT archetype used for Markdown alerts
        ui_payload_dict = {
            "archetype": "KNOWLEDGE_DOCUMENT",
            "subject_concept": "system://mesh/alert",
            "severity": "WARNING",
            "entities": "# ⚠️ SYSTEM ALERT\nNo relevant records or hazards found in the Graph Database for this query. Do not proceed without manual verification.",
            "relationships": "[]"
        }
        ui_payload_str = json.dumps(ui_payload_dict)
        yield Output(
            value=ui_payload_dict,
            metadata={"ui_json_payload": ui_payload_str}
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
    
    # Force stringification to bypass Dagster's valueRepr length limit for dicts
    ui_payload_str = json.dumps(ui_payload_dict)
    
    context.log.info(f"Generated UI Payload for persona {config.persona}")
    yield Output(
        value=ui_payload_dict,
        metadata={"ui_json_payload": ui_payload_str}
    )


@job
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
