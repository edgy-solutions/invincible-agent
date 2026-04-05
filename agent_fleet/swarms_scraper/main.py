"""
Engine C — Swarms.ai Heavy Compute Scraper Microservice

A stateless, highly concurrent FastAPI server that runs a Swarms.ai
SequentialWorkflow for data extraction and scraping tasks.

This service is a pure compute node. Do NOT import Restate, LangGraph,
Dagster, or database checkpointers here. It must be completely isolated.

Run: uvicorn agent_fleet.swarms_scraper.main:app --host 0.0.0.0 --port 8083
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel
from swarms import Agent, SequentialWorkflow

# ---------------------------------------------------------------------------
# Add baml_shared to the Python path for the generated BAML types.
# In CNB containers, baml_client is copied locally — this is only for dev.
# ---------------------------------------------------------------------------
try:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
    if str(_BAML_CLIENT_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_CLIENT_PATH))
    _BAML_SHARED_PATH = _REPO_ROOT / "baml_shared"
    if str(_BAML_SHARED_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_SHARED_PATH))
except IndexError:
    pass  # Running in CNB container — baml_client is already in /workspace/

try:
    from telemetry import safe_observe
except ImportError:
    def safe_observe(**kwargs):
        def decorator(func):
            return func
        return decorator

from baml_client.types import AgentResponse, AgentStatus, AgentTask  # noqa: E402

# ---------------------------------------------------------------------------
# Swarms Agent configuration
# ---------------------------------------------------------------------------
SCRAPER_MODEL = os.environ.get("SWARMS_MODEL", "gpt-4o-mini")

scraper_agent = Agent(
    agent_name="DataExtractor",
    system_prompt=(
        "You are a highly capable data extraction and scraping specialist. "
        "Given a task description and dataset identifier, extract the "
        "requested data and return a structured summary with key metrics. "
        "Be concise and precise."
    ),
    model_name=SCRAPER_MODEL,
    max_loops=1,
    verbose=False,
)

# Build a SequentialWorkflow with the single extraction agent.
# Additional agents (e.g. a cleaner, validator) can be appended later.
scrape_workflow = SequentialWorkflow(
    name="ScrapeWorkflow",
    agents=[scraper_agent],
)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Engine C — Swarms Scraper",
    description=(
        "Stateless, highly concurrent compute node powered by Swarms.ai "
        "SequentialWorkflow for data extraction and scraping. "
        "Completely isolated — no Restate, LangGraph, or checkpointers."
    ),
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class ScrapeRequest(BaseModel):
    """Incoming request to the /scrape endpoint."""
    task_description: str
    dataset_id: str
    semantic_context: dict | None = None


@safe_observe(name="swarms_extraction_execution")
def execute_swarms_workflow(prompt: str):
    return scrape_workflow.run(prompt)

# ---------------------------------------------------------------------------
# POST /scrape
# ---------------------------------------------------------------------------
@app.post("/scrape")
async def scrape(request: ScrapeRequest) -> dict:
    """Run the Swarms.ai extraction workflow and return an AgentResponse.

    The task description and dataset ID are formatted into a prompt and
    passed through the SequentialWorkflow.
    """
    prompt = (
        f"Extract data for the following task.\n\n"
        f"Task: {request.task_description}\n"
        f"Dataset ID: {request.dataset_id}\n"
    )

    # Append semantic context if provided
    if request.semantic_context:
        resolved_uri = request.semantic_context.get("resolved_uri", "")
        prompt += (
            f"\nSemantic Context:\n"
            f"  Resolved URI: {resolved_uri}\n"
        )

    prompt += "\nReturn a concise summary and any numeric metrics you extract."

    try:
        result = execute_swarms_workflow(prompt)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            summary=str(result),
            extracted_metrics={},
        ).model_dump()

    except Exception as exc:
        return AgentResponse(
            status=AgentStatus.FAILED,
            summary=f"Swarm workflow failed: {exc}",
            extracted_metrics={},
        ).model_dump()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Simple liveness probe."""
    return {
        "status": "ok",
        "engine": "swarms_scraper",
        "agents": [scraper_agent.agent_name],
    }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8083)
