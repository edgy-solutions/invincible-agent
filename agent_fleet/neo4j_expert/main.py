"""
Engine E — Restate + Smolagents Durable Neo4j Graph Expert Microservice

A FastAPI server backed by the Restate SDK for durable execution.
It exposes a `/query_graph` endpoint that uses a smolagents CodeAgent
with custom Neo4j Cypher and Schema tools to extract structural data
from a military technical manual graph database. BAML strictly types
the output per Persona.

Run locally: uvicorn agent_fleet.neo4j_expert.main:app --host 0.0.0.0 --port 8086
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
        from agent_fleet.neo4j_expert.service import service as expert_service

# Engine E's lifespan registers it as a predicate in the mesh routing graph.
# Engine E queries a Neo4j military-technical-manual graph using Cypher +
# smolagents CodeAgent with semantic-search tools; takes a structured graph
# query and returns a persona-typed GraphExpertResponse.
@asynccontextmanager
async def lifespan(app: FastAPI):
    register_engine_to_mesh(
        name="engine_e_neo4j_expert",
        description=(
            "Knowledge graph expert. Runs a smolagents CodeAgent over Neo4j "
            "(execute_cypher, get_graph_schema, search_manual_text) with "
            "Restate-durable execution and mem0 long-term memory."
        ),
        verb="mesh:queryKnowledgeGraph",
        input_uri="mesh:GraphQuery",
        output_uri="mesh:GraphExpertResponse",
        verb_synonyms=[
            "query graph", "graph lookup", "cypher query",
            "find in graph", "knowledge graph search",
        ],
        endpoint_url=os.getenv(
            "ENGINE_E_PUBLIC_URL",
            "http://neo4j-expert-svc.default.svc.cluster.local:8086/query_graph",
        ),
        owner_persona="AUDITOR",
        # Per ADR-0009: Engine E queries the maintenance-manual knowledge
        # graph; its domain scopes follow the manual corpus it serves.
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="slow",
    )
    yield


# Initialize FastAPI
app = FastAPI(title="Engine E: Neo4j Graph Expert", lifespan=lifespan)

# Restate App Binding
# This binds the previously defined expert_service (Neo4jExpertService)
# to handle durable executions incoming from the `/restate` base path.
# Using app.mount is the standard way to integrate Restate with FastAPI.
app.mount("/restate", restate.app(services=[expert_service]))

# Read the Restate URL from env, default to the Docker Compose service name
RESTATE_INGRESS_URL = os.getenv("RESTATE_INGRESS_URL", "http://restate:8080")

@app.post("/query_graph")
async def query_graph_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate Neo4jExpertService.
    
    Dagster POSTs directly to this endpoint. We forward it to the Restate Ingress
    at /{ServiceName}/{MethodName} for durable execution.
    """
    try:
        payload = await request.json()
        target_url = f"{RESTATE_INGRESS_URL}/Neo4jExpertService/query_graph"
        
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
    return {"status": "ok", "engine": "E"}
