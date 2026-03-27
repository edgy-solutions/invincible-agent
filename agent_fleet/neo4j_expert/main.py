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
import httpx
import restate
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

try:
    from .service import service as expert_service
except ImportError:
    from service import service as expert_service

# Initialize FastAPI
app = FastAPI(title="Engine E: Neo4j Graph Expert")

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
