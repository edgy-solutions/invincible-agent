"""
Engine A — Restate + Smolagents Durable Analyst Microservice

A FastAPI server backed by the Restate SDK for durable execution.
Before running the smolagents CodeAgent, the handler calls Engine O
(the ontology reasoner) to resolve the user's intent into a canonical
IOF/MIMOSA URI and suggested dbt models. This semantic context is then
passed into the agent so it knows which database tables to query.

Run: uvicorn agent_fleet.restate_analyst.main:app --host 0.0.0.0 --port 8081
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import requests
import restate
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from restate import Context, Service

# ---------------------------------------------------------------------------
# Add baml_shared to the Python path for the generated BAML types.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
if str(_BAML_CLIENT_PATH) not in sys.path:
    sys.path.insert(0, str(_BAML_CLIENT_PATH))

from baml_client.types import AgentResponse, AgentStatus, AgentTask  # noqa: E402

# ---------------------------------------------------------------------------
# Smolagents imports — only used inside the Restate handler.
# ---------------------------------------------------------------------------
from smolagents import CodeAgent, HfApiModel  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ONTOLOGY_RESOLVE_URL = (
    "http://ontology-agent-svc.default.svc.cluster.local:8084/resolve"
)
ONTOLOGY_TIMEOUT = 30  # seconds — ontology resolution is fast

# ---------------------------------------------------------------------------
# Restate Service
# ---------------------------------------------------------------------------
analyst_service = Service("AnalystService")


def _resolve_ontology(task_description: str) -> dict:
    """Call Engine O to resolve the task description into semantic context.

    This function is executed inside ``ctx.run()`` for durable execution —
    if the pod crashes mid-flight, Restate will replay and skip this step
    if it already completed successfully.
    """
    resp = requests.post(
        ONTOLOGY_RESOLVE_URL,
        json={"query": task_description},
        timeout=ONTOLOGY_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def _run_smolagent(task_description: str, dataset_id: str, semantic_ctx: dict) -> dict:
    """Execute the HuggingFace smolagents CodeAgent with semantic context.

    The agent receives the resolved ontology URI and suggested dbt models
    so it knows exactly which database tables to query.
    """
    suggested_models = semantic_ctx.get("suggested_dbt_models", [])
    resolved_uri = semantic_ctx.get("resolved_uri", "unknown")
    confidence = semantic_ctx.get("confidence_score", 0.0)

    # Build a context-rich prompt for the code agent
    agent_prompt = (
        f"You are a sustainment data analyst. Analyze the following task.\n\n"
        f"Task: {task_description}\n"
        f"Dataset ID: {dataset_id}\n\n"
        f"Semantic Context (from IOF/MIMOSA ontology):\n"
        f"  Resolved URI: {resolved_uri}\n"
        f"  Confidence: {confidence}\n"
        f"  Relevant dbt models / tables: {', '.join(suggested_models)}\n\n"
        f"Use ONLY the tables listed above. Produce a brief summary of your "
        f"analysis and any key metrics you extract."
    )

    model = HfApiModel()
    agent = CodeAgent(tools=[], model=model)
    result = agent.run(agent_prompt)

    return {
        "status": AgentStatus.SUCCESS.value,
        "summary": str(result),
        "extracted_metrics": {
            "ontology_confidence": confidence,
        },
    }


@analyst_service.handler()
async def analyze(ctx: Context, request: dict) -> dict:
    """Durable handler: resolve ontology → run smolagent → return AgentResponse.

    Every side-effectful operation is wrapped in ``ctx.run()`` so Restate
    can guarantee exactly-once execution even across pod restarts.
    """
    # Parse the incoming AgentTask
    task = AgentTask(**request)

    # Step 1: Resolve semantic context via Engine O (durable HTTP call)
    semantic_ctx = await ctx.run(
        "resolve_ontology",
        lambda: _resolve_ontology(task.task_description),
    )

    # Step 2: Run the smolagents CodeAgent (durable execution)
    agent_result = await ctx.run(
        "run_smolagent",
        lambda: _run_smolagent(
            task_description=task.task_description,
            dataset_id=task.dataset_id,
            semantic_ctx=semantic_ctx,
        ),
    )

    # Validate against our BAML schema before returning
    response = AgentResponse(**agent_result)
    return response.model_dump()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Engine A — Restate Analyst",
    description=(
        "Durable analyst agent powered by Restate + HuggingFace Smolagents. "
        "Resolves ontology context via Engine O before analysis."
    ),
    version="0.1.0",
)

# Mount the Restate SDK so it handles /restate/* routes
app.mount("/restate", restate.app(services=[analyst_service]))


# ---------------------------------------------------------------------------
# Request model for the proxy endpoint
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    """Proxy request model — mirrors AgentTask."""
    task_description: str
    dataset_id: str
    semantic_context: dict | None = None


# ---------------------------------------------------------------------------
# POST /analyze — proxy route for Dagster
# ---------------------------------------------------------------------------
@app.post("/analyze")
async def analyze_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate AnalystService.

    Dagster (and other external callers) POST to ``/analyze`` with an
    ``AgentTask`` JSON body. This route forwards the payload to the mounted
    Restate service at ``/restate/AnalystService/analyze`` so the call
    benefits from Restate's durable execution guarantees.
    """
    body = await request.body()

    try:
        resp = requests.post(
            "http://localhost:8081/restate/AnalystService/analyze",
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
        resp.raise_for_status()
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except requests.RequestException as exc:
        return JSONResponse(
            content={
                "status": AgentStatus.FAILED.value,
                "summary": f"Restate proxy call failed: {exc}",
                "extracted_metrics": {},
            },
            status_code=502,
        )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Simple liveness probe."""
    return {"status": "ok", "engine": "restate_analyst"}


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
