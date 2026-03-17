"""
Phase 2: Dynamic Supervisor & Fan-Out

Dagster job that takes a complex multi-domain query, asks Engine O to decompose
it into Persona-specific sub-tasks, fans those out concurrently to Engine E 
(Neo4j Graph Expert), and synthesizes the results.
"""

import requests
from typing import List, Dict, Any

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


@op(in_={"results": In(List[Dict[str, Any]])}, out=Out(Dict[str, Any]))
def synthesize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Fans-in the results from all parallel sub-tasks.
    Currently returns the combined results dictionary (LLM synthesis to be added later).
    """
    return {
        "status": "success",
        "total_subtasks": len(results),
        "results": results,
    }


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
    synthesize_results(executed_results.collect())
