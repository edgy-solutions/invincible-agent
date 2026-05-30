"""
Engine W — Restate + Smolagents Durable Weaviate Semantic Expert Microservice

A FastAPI server backed by the Restate SDK for durable execution.
It exposes a `/query_knowledge` endpoint that uses a smolagents CodeAgent
with a custom Weaviate Semantic Search tool to extract knowledge and policies
from a military technical manual database. BAML strictly types the output.

Run locally: uvicorn agent_fleet.weaviate_expert.main:app --host 0.0.0.0 --port 8088
"""

import os
from contextlib import asynccontextmanager

import httpx
import restate
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Engine self-registration for the predicate-graph routing layer
# (iagent ADR-0004 Step D.1). Opt-in via MESH_REGISTER_ON_STARTUP.
try:
    from utils.mesh_registration import register_engine_to_mesh
except ImportError:
    from agent_fleet.utils.mesh_registration import register_engine_to_mesh

try:
    # Standalone microservice mode (Workspace Root)
    from service import service as expert_service
except ImportError:
    # Local dev mode (Imported as submodule)
    try:
        from .service import service as expert_service
    except ImportError:
        # Fallback for parent-dir execution
        from agent_fleet.weaviate_expert.service import service as expert_service

# Engine W's lifespan registers it as a predicate in the mesh routing graph.
# Engine W does Weaviate hybrid search over technical manuals for pure
# knowledge retrieval (no graph traversal); returns a structured markdown
# summary with citations.
@asynccontextmanager
async def lifespan(app: FastAPI):
    register_engine_to_mesh(
        name="engine_w_weaviate_expert",
        description=(
            "Knowledge retrieval engine. Weaviate v4 hybrid search "
            "(near_text + BM25) with strict domain segregation; returns "
            "Markdown summaries and citations from technical manuals."
        ),
        verb="mesh:retrieveKnowledge",
        input_uri="mesh:KnowledgeQuery",
        output_uri="mesh:KnowledgeRetrievalResponse",
        verb_synonyms=[
            "search docs", "find in manuals", "semantic search",
            "look up policy", "consult manual",
        ],
        endpoint_url=os.getenv(
            "ENGINE_W_PUBLIC_URL",
            "http://weaviate-expert-svc.default.svc.cluster.local:8088/query_knowledge",
        ),
        owner_persona="TECH_WRITER",
        # Per ADR-0009: Engine W's strict per-collection segregation
        # already partitioned by domain; making it explicit here so the
        # scope filter in /find_tool can match.
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="medium",  # Weaviate is fast; embedding + smolagents = medium overall
    )
    yield


# Initialize FastAPI
app = FastAPI(title="Engine W: Weaviate Semantic Expert", lifespan=lifespan)

# Restate App Binding
app.mount("/restate", restate.app(services=[expert_service]))

# Read the Restate URL from env, default to the Docker Compose service name
RESTATE_INGRESS_URL = os.getenv("RESTATE_INGRESS_URL", "http://restate:8080")

@app.post("/query_knowledge")
async def query_knowledge_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate WeaviateExpertService."""
    try:
        payload = await request.json()
        target_url = f"{RESTATE_INGRESS_URL}/WeaviateExpertService/query_knowledge"
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                target_url,
                json=payload,
            )
            # Bubble up the exact response and status code from Restate
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.text else {}
            )
    except httpx.ConnectError as exc:
        print(f"DEBUG: Failed to connect to Restate Server at {RESTATE_INGRESS_URL}: {exc}")
        return JSONResponse(
            status_code=502,
            content={"status": "FAILED", "summary": f"Failed to connect to Restate Server at {RESTATE_INGRESS_URL}"}
        )
    except Exception as exc:
        print(f"DEBUG: Unexpected error in proxy: {exc}")
        return JSONResponse(
            status_code=500,
            content={"status": "FAILED", "summary": str(exc)}
        )

@app.get("/health")
def health_check():
    """Liveness probe endoint for Kubernetes."""
    return {"status": "ok", "engine": "W"}
