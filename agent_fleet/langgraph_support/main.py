"""
Engine B — LangGraph Support Microservice

A FastAPI server that exposes a LangGraph StateGraph with durable
conversational memory backed by AsyncPostgresSaver (PostgreSQL).

The graph has two nodes:
  1. triage  — classifies the incoming task
  2. respond — generates the agent response

This service is an entirely isolated K8s pod. Do NOT import Restate,
Dagster, or any Engine A dependencies here.

Run: uvicorn agent_fleet.langgraph_support.main:app --host 0.0.0.0 --port 8082
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Add baml_shared to the Python path for the generated BAML types.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
if str(_BAML_CLIENT_PATH) not in sys.path:
    sys.path.insert(0, str(_BAML_CLIENT_PATH))

from baml_client.types import AgentResponse, AgentStatus, AgentTask  # noqa: E402

# ---------------------------------------------------------------------------
# PostgreSQL connection string for the checkpointer.
# In production this comes from a Kubernetes Secret / env var.
# ---------------------------------------------------------------------------
POSTGRES_URI = os.environ.get(
    "LANGGRAPH_POSTGRES_URI",
    "postgresql://langgraph:langgraph@localhost:5432/langgraph",
)

# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------


class SupportState(TypedDict):
    """State that flows through the support graph."""
    task_description: str
    dataset_id: str
    triage_category: str
    response_summary: str
    extracted_metrics: dict[str, float]


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------


def triage(state: SupportState) -> dict[str, Any]:
    """Classify the incoming support task into a triage category.

    In production this would call an LLM or a rules engine. For now it
    applies a simple keyword heuristic as a placeholder.
    """
    description = state["task_description"].lower()

    if any(kw in description for kw in ("urgent", "critical", "down", "outage")):
        category = "critical"
    elif any(kw in description for kw in ("question", "how", "help", "what")):
        category = "inquiry"
    else:
        category = "general"

    return {"triage_category": category}


def respond(state: SupportState) -> dict[str, Any]:
    """Generate a support response based on the triage category.

    In production this would invoke an LLM chain. For now it returns a
    templated summary so the wiring is testable end-to-end.
    """
    category = state["triage_category"]
    dataset_id = state["dataset_id"]

    summary = (
        f"[{category.upper()}] Support response for dataset '{dataset_id}': "
        f"Task has been triaged as '{category}' and processed. "
        f"Original request: {state['task_description']}"
    )

    return {
        "response_summary": summary,
        "extracted_metrics": {
            "triage_confidence": 1.0,
            "is_critical": float(category == "critical"),
        },
    }


# ---------------------------------------------------------------------------
# Build the StateGraph
# ---------------------------------------------------------------------------


def _build_graph() -> StateGraph:
    """Construct the two-node support graph: triage → respond → END."""
    builder = StateGraph(SupportState)
    builder.add_node("triage", triage)
    builder.add_node("respond", respond)

    builder.set_entry_point("triage")
    builder.add_edge("triage", "respond")
    builder.add_edge("respond", END)

    return builder


# ---------------------------------------------------------------------------
# Global compiled graph — set during lifespan with the checkpointer.
# ---------------------------------------------------------------------------
_compiled_graph = None
_checkpointer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect the AsyncPostgresSaver and compile the graph."""
    global _compiled_graph, _checkpointer

    _checkpointer = AsyncPostgresSaver.from_conn_string(POSTGRES_URI)
    await _checkpointer.setup()

    builder = _build_graph()
    _compiled_graph = builder.compile(checkpointer=_checkpointer)

    print("[langgraph-support] Graph compiled with AsyncPostgresSaver checkpointer")
    yield

    # Cleanup
    _compiled_graph = None
    if _checkpointer is not None:
        await _checkpointer.conn.close()
        _checkpointer = None


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Engine B — LangGraph Support",
    description=(
        "Stateful support agent powered by LangGraph with PostgreSQL-backed "
        "conversational memory. Entirely isolated from Engine A / Restate."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class SupportRequest(BaseModel):
    """Incoming request to the /support endpoint."""
    task_description: str
    dataset_id: str
    thread_id: str
    semantic_context: dict | None = None


# ---------------------------------------------------------------------------
# POST /support
# ---------------------------------------------------------------------------
@app.post("/support")
async def support(request: SupportRequest) -> dict:
    """Invoke the LangGraph support graph with conversational memory.

    The ``thread_id`` is used as the checkpoint key so the graph remembers
    prior interactions within the same conversation thread.
    """
    if _compiled_graph is None:
        raise HTTPException(status_code=503, detail="Graph not compiled yet.")

    # Build initial state from the AgentTask fields
    initial_state: SupportState = {
        "task_description": request.task_description,
        "dataset_id": request.dataset_id,
        "triage_category": "",
        "response_summary": "",
        "extracted_metrics": {},
    }

    # Invoke with thread config for checkpointer memory
    config = {"configurable": {"thread_id": request.thread_id}}

    try:
        final_state = await _compiled_graph.ainvoke(initial_state, config=config)
    except Exception as exc:
        return AgentResponse(
            status=AgentStatus.FAILED,
            summary=f"Graph execution failed: {exc}",
            extracted_metrics={},
        ).model_dump()

    # Build and validate the AgentResponse
    response = AgentResponse(
        status=AgentStatus.SUCCESS,
        summary=final_state["response_summary"],
        extracted_metrics=final_state.get("extracted_metrics", {}),
    )
    return response.model_dump()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Simple liveness probe."""
    return {
        "status": "ok",
        "engine": "langgraph_support",
        "graph_compiled": _compiled_graph is not None,
    }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8082)
