"""
Phase 2: Dynamic Supervisor & Fan-Out

Dagster job that takes a complex multi-domain query, asks Engine O to decompose
it into Persona-specific sub-tasks, fans those out concurrently to Engine E 
(Neo4j Graph Expert), and synthesizes the results.
"""

import json
import requests
import sys
from pathlib import Path
from typing import List, Dict, Any

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
)


class SupervisorQueryConfig(Config):
    """Configuration for the supervisor job."""
    user_query: str


@op(out=DynamicOut(Dict[str, Any]))
def create_task_plan(config: SupervisorQueryConfig):
    """
    Calls Engine O (Ontology Reasoner) to decompose a complex query into a
    SupervisorTaskPlan containing persona-specific sub-tasks.
    Yields each sub-task as a DynamicOutput for downstream fan-out.
    """
    # 1. Ask Engine O for the plan
    response = requests.post(
        "http://ontology-svc.default.svc.cluster.local:8084/plan",
        json={"query": config.user_query},
        timeout=30,
    )
    response.raise_for_status()
    plan = response.json()

    # 2. Fan-out: yield each task dynamically
    tasks = plan.get("tasks", [])
    for idx, task in enumerate(tasks):
        # We must provide a valid mapping_key for each dynamic output
        yield DynamicOutput(
            value=task,
            mapping_key=f"task_{idx}"
        )


@op(in_={"task_def": In(Dict[str, Any])}, out=Out(Dict[str, Any]))
def execute_subtask(task_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes a single decomposed sub-task by calling Engine E (Neo4j Graph Expert).
    This op runs in parallel for each dynamically generated task.
    """
    persona = task_def.get("target_persona", "MECHANIC")
    sub_query = task_def.get("sub_query", "")

    # Call Engine E (durable execution via Restate + smolagents)
    response = requests.post(
        "http://neo4j-expert-svc.default.svc.cluster.local:8086/query_graph",
        json={
            "user_query": sub_query,
            "persona": persona,
        },
        timeout=120, # 2 minutes to allow agent looping
    )
    response.raise_for_status()
    
    # Return the BAML-formatted GraphExpertResponse JSON
    return {
        "persona": persona,
        "sub_query": sub_query,
        "expert_response": response.json(),
    }


@op(in_={"results": In(List[Dict[str, Any]])}, out=Out(str))
async def synthesize_stateless(config: SupervisorQueryConfig, results: List[Dict[str, Any]]) -> str:
    """
    Fans-in the results from all parallel sub-tasks and synthesizes them
    using the LLM (via BAML) to generate a cohesive Markdown report directly
    inside Dagster.
    """
    # Dump the results list to a JSON string for the LLM
    json_string = json.dumps(results)
    
    # Call the async BAML client
    synthesis = await b.SynthesizeReports(config.user_query, json_string)
    
    return synthesis.markdown_report


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
    
    # Collect the results and synthesize
    synthesize_stateless(executed_results.collect())
