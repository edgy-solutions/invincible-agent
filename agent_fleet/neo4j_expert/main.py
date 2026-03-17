"""
Engine E — Restate + Smolagents Durable Neo4j Graph Expert Microservice

A FastAPI server backed by the Restate SDK for durable execution.
It exposes a `/query_graph` endpoint that uses a smolagents CodeAgent
with custom Neo4j Cypher and Schema tools to extract structural data
from a military technical manual graph database. BAML strictly types
the output per Persona.

Run locally: uvicorn agent_fleet.neo4j_expert.main:app --host 0.0.0.0 --port 8086
"""

from fastapi import FastAPI
import restate

# Import from the local service definition
from .service import service as expert_service

# Initialize FastAPI
app = FastAPI(title="Engine E: Neo4j Graph Expert")

# Restate App Binding
# This binds the previously defined expert_service (Neo4jExpertService)
# to handle durable executions incoming from the `/restate` base path
restate_app = restate.app(services=[expert_service])

@app.post("/restate/{path:path}")
async def restate_handler(path: str, req: restate.fastapi.Request) -> restate.fastapi.Response:
    """
    Reverse proxy connecting Restate Ingress to our local Restate services.
    The Restate server makes HTTP requests here to drive the durable executions.
    """
    return await restate_app.handle_fastapi(req)

@app.get("/health")
def health_check():
    """Liveness probe endoint for Kubernetes."""
    return {"status": "ok", "engine": "E"}
