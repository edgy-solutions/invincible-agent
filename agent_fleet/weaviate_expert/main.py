"""
Engine W — Restate + Smolagents Durable Weaviate Semantic Expert Microservice

A FastAPI server backed by the Restate SDK for durable execution.
It exposes a `/query_knowledge` endpoint that uses a smolagents CodeAgent
with a custom Weaviate Semantic Search tool to extract knowledge and policies
from a military technical manual database. BAML strictly types the output.

Run locally: uvicorn agent_fleet.weaviate_expert.main:app --host 0.0.0.0 --port 8088
"""

import os
import httpx
import restate
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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

# Initialize FastAPI
app = FastAPI(title="Engine W: Weaviate Semantic Expert")

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
