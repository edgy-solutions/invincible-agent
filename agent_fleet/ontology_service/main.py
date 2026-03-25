"""
Engine O — Ontology Reasoner Microservice

A lightweight FastAPI service that translates natural language into standard
IOF/MIMOSA sustainment terms using an RDF graph and BAML-based LLM
classification.

This service does NO compute or orchestration. It strictly:
1. Loads the IOF MRO ontology (.ttl) into an rdflib graph on startup.
2. Queries the graph for active ontology classes and their definitions.
3. Passes the user query + ontology context to BAML ClassifySustainmentIntent.
4. Returns a SemanticResolution response.

Run: uvicorn agent_fleet.ontology_service.main:app --host 0.0.0.0 --port 8084
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import rdflib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Add baml_shared to the Python path so we can import the generated client.
# In a containerised deployment this would be handled by the Docker build or
# a proper package install; here we do it explicitly for local dev.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
if str(_BAML_CLIENT_PATH) not in sys.path:
    sys.path.insert(0, str(_BAML_CLIENT_PATH))

from baml_client import b  # noqa: E402  — BAML async client
from baml_client.types import SemanticResolution as BamlSemanticResolution  # noqa: E402

# ---------------------------------------------------------------------------
# RDF namespace constants
# ---------------------------------------------------------------------------
OWL = rdflib.Namespace("http://www.w3.org/2002/07/owl#")
RDFS = rdflib.Namespace("http://www.w3.org/2000/01/rdf-schema#")
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")
IOF_ANN = rdflib.Namespace(
    "https://spec.industrialontologies.org/ontology/annotation/"
)
IOF_CONSTRUCT = rdflib.Namespace(
    "https://spec.industrialontologies.org/ontology/construct/"
)

# ---------------------------------------------------------------------------
# Global graph and Hybrid Setup
# ---------------------------------------------------------------------------
import os
import httpx

_JENA_ENDPOINT = os.getenv("JENA_SPARQL_ENDPOINT", "")
_LOCAL_GRAPH = None

# ---------------------------------------------------------------------------
# Master Agent & Domain Registry (Single Source of Truth)
# ---------------------------------------------------------------------------
MASTER_PERSONAS = {
    "MECHANIC": {
        "ui": {"label": "Line Mechanic", "icon": "Wrench", "color": "text-amber-500", "bg": "bg-amber-500/10 border-amber-500/30"},
        "llm_prompt": "Wrench-turning, physical repairs, safety hazards, hardware component failures."
    },
    "TECH_WRITER": {
        "ui": {"label": "Tech Writer", "icon": "BookOpen", "color": "text-blue-400", "bg": "bg-blue-400/10 border-blue-400/30"},
        "llm_prompt": "Formatting manuals, procedures, standard Markdown text. DO NOT use XML."
    },
    "LOGISTICS": {
        "ui": {"label": "Logistics", "icon": "Truck", "color": "text-emerald-500", "bg": "bg-emerald-500/10 border-emerald-500/30"},
        "llm_prompt": "Supply chain, procurement, lifecycle management, inventory."
    },
    "AUDITOR": {
        "ui": {"label": "Auditor", "icon": "ShieldCheck", "color": "text-red-400", "bg": "bg-red-400/10 border-red-400/30"},
        "llm_prompt": "Safety compliance, rules, identifying non-compliant nodes."
    },
    "PROCESS_ENGINEER": {
        "ui": {"label": "Process Eng", "icon": "Network", "color": "text-purple-500", "bg": "bg-purple-500/10 border-purple-500/30"},
        "llm_prompt": "Workflows, sequential steps, BPMN routing."
    },
    "DATA_STEWARD": {
        "ui": {"label": "Data Steward", "icon": "Database", "color": "text-cyan-400", "bg": "bg-cyan-400/10 border-cyan-400/30"},
        "llm_prompt": "Databases, dbt models, Postgres schemas, telemetry data pipelines, and metadata. Any data engineering query MUST go to the DATA_STEWARD."
    }
}

MASTER_DOMAINS = {
    "MAINTENANCE": "Wrench-turning, physical repairs, safety hazards, component failures.",
    "SUSTAINMENT": "Supply chain, logistics, procurement, lifecycle management, inventory.",
    "DATA_ENGINEERING": "dbt models, Postgres, React, Kafka, data pipelines, software architecture.",
    "UNKNOWN": "Use if the query is unrelated to the above domains."
}

def get_baml_persona_string() -> str:
    return "\n".join([f"- {k}: {v['llm_prompt']}" for k, v in MASTER_PERSONAS.items()])

def get_baml_domain_string() -> str:
    return "\n".join([f"- {k}: {v}" for k, v in MASTER_DOMAINS.items()])

# SPARQL: find all named OWL classes defined in the IOF maintenance namespace
# along with their labels and natural-language definitions.
_SPARQL_MAINTENANCE_CLASSES = """
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX iof-ann: <https://spec.industrialontologies.org/ontology/annotation/>

SELECT ?cls ?label ?definition ?example
WHERE {
    ?cls a owl:Class ;
         rdfs:label ?label .
    FILTER (isURI(?cls))
    OPTIONAL { ?cls iof-ann:naturalLanguageDefinition ?definition . }
    OPTIONAL { ?cls skos:example ?example . }
}
ORDER BY ?label
"""


def _get_local_graph() -> rdflib.Graph:
    """Lazy-load the local rdflib fallback only when needed."""
    global _LOCAL_GRAPH
    if _LOCAL_GRAPH is None:
        print("Initializing local rdflib fallback graph...")
        _LOCAL_GRAPH = rdflib.Graph()
        service_dir = Path(__file__).parent
        real_rdf = service_dir / "Maintenance.rdf"
        ttl_path = service_dir / "iof_mro.ttl"
        
        if real_rdf.exists():
            _LOCAL_GRAPH.parse(str(real_rdf), format="xml")
        elif ttl_path.exists():
            _LOCAL_GRAPH.parse(str(ttl_path), format="turtle")
    return _LOCAL_GRAPH


async def execute_sparql(query: str, domain: str = "MAINTENANCE") -> list[dict]:
    """
    Execute SPARQL query using the Hybrid Strategy:
    1. Try Apache Jena Fuseki (Fast/Enterprise)
    2. Fallback to local rdflib (Safe/Development)
    """
    # Determine the correct Named Graph based on the routed domain
    named_graph = "<http://internal/mro>"
    if domain == "SUSTAINMENT":
        named_graph = "<http://internal/sustainment>"
    elif domain == "DATA_ENGINEERING":
        named_graph = "<http://internal/idp>"

    # 🛑 Strictly enforce data segregation by wrapping the query in the graph context.
    # This assumes the input query uses standard triple patterns that we want to scope.
    # For complex queries, we might need a more robust parser, but for our Agentic Mesh
    # standard patterns, this wrapping is effective.
    scoped_query = query
    if "GRAPH" not in query.upper() and "SELECT" in query.upper():
        # Simple injection: replace WHERE { with WHERE { GRAPH <named_graph> {
        if "WHERE {" in query:
            scoped_query = query.replace("WHERE {", f"WHERE {{ GRAPH {named_graph} {{", 1)
            scoped_query += " } }"
        elif "WHERE {" in query.upper():
            # Handle case-insensitive WHERE
            import re
            scoped_query = re.sub(r"WHERE\s*\{", f"WHERE {{ GRAPH {named_graph} {{", query, flags=re.IGNORECASE, count=1)
            scoped_query += " } }"

    # 🚀 PATH A: Apache Jena Fuseki via HTTP
    if _JENA_ENDPOINT:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    _JENA_ENDPOINT,
                    data={"query": scoped_query},
                    headers={"Accept": "application/sparql-results+json"}
                )
                if resp.status_code == 200:
                    data = resp.json()
                    bindings = data.get("results", {}).get("bindings", [])
                    results = []
                    for b in bindings:
                        row_dict = {k: v["value"] for k, v in b.items()}
                        results.append(row_dict)
                    return results
        except Exception as e:
            print(f"Jena cluster unreachable or failed ({e}), triggering fallback...")

    # 🐢 PATH B: Local rdflib Fallback
    try:
        g = _get_local_graph()
        rows = g.query(scoped_query)
        results = []
        for row in rows:
            # Safely convert rdflib result row to dictionary of strings
            row_dict = {str(k): str(v) for k, v in row.asdict().items()}
            results.append(row_dict)
        return results
    except Exception as e:
        print(f"Local rdflib fallback failed: {e}")
        return []


async def _get_active_ontology_classes(domain: str = "MAINTENANCE") -> str:
    """Query the graph for domain-specific classes and format them as a
    newline-delimited string of ``URI — Label: Definition`` entries suitable
    for injection into the BAML prompt."""
    rows = await execute_sparql(_SPARQL_MAINTENANCE_CLASSES, domain=domain)
    lines: list[str] = []
    for row in rows:
        uri = row.get("cls")
        label = row.get("label")
        definition = row.get("definition") or "No definition available."
        example_text = row.get("example")
        example = f" Examples: {example_text}" if example_text else ""
        lines.append(f"{uri} — {label}: {definition}{example}")
    return "\n".join(lines)


async def _seed_jena_if_empty():
    """Check if Apache Jena is empty, and seed it with the RDF if needed."""
    if not _JENA_ENDPOINT:
        return
        
    try:
        # Check if empty (attempt to select 1 triple)
        rows = await execute_sparql("SELECT * WHERE { ?s ?p ?o } LIMIT 1")
        if rows:
            print("[ontology-service] Jena dataset is already populated.")
            return
            
        print("[ontology-service] Jena dataset is empty. Seeding...")
        service_dir = Path(__file__).parent
        real_rdf = service_dir / "Maintenance.rdf"
        ttl_path = service_dir / "iof_mro.ttl"
        
        file_path = real_rdf if real_rdf.exists() else ttl_path
        content_type = "application/rdf+xml" if real_rdf.exists() else "text/turtle"
        
        if not file_path.exists():
            print("[ontology-service] No ontology file found to seed.")
            return
            
        update_ep = _JENA_ENDPOINT.replace("/query", "/data")
        with open(file_path, "rb") as f:
            file_data = f.read()
            
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                update_ep,
                content=file_data,
                headers={"Content-Type": content_type}
            )
            if resp.status_code in (200, 201, 204):
                print(f"[ontology-service] Successfully seeded Jena with {file_path.name}")
            else:
                print(f"[ontology-service] Failed to seed Jena: {resp.status_code} {resp.text}")
                
    except Exception as e:
        print(f"[ontology-service] Error during Jena seeding: {e}")


# ---------------------------------------------------------------------------
# FastAPI lifespan — verify connectivity on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _seed_jena_if_empty()
    classes = await _get_active_ontology_classes()
    class_count = len(classes.strip().splitlines()) if classes.strip() else 0
    backend = "Jena Fuseki" if _JENA_ENDPOINT else "Local rdflib"
    print(f"[ontology-service] Loaded {class_count} maintenance classes (Backend: {backend})")
    yield


app = FastAPI(
    title="Engine O — Ontology Reasoner",
    description=(
        "Translates natural language into IOF/MIMOSA sustainment terms. "
        "No compute or orchestration — pure semantic resolution."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class RouteAndPlanRequest(BaseModel):
    """Incoming request to the /route_and_plan endpoint."""
    query: str
    domain: str | None = None


class PlanRequest(BaseModel):
    """Incoming request to the /plan endpoint."""
    query: str
    domain: str = "MAINTENANCE"


class ResolveRequest(BaseModel):
    """Incoming request to the /resolve endpoint."""
    query: str
    domain: str = "MAINTENANCE"


class SemanticResolutionResponse(BaseModel):
    """Mirrors the BAML SemanticResolution schema for the HTTP response."""
    resolved_uri: str
    confidence_score: float
    suggested_dbt_models: list[str]


# ---------------------------------------------------------------------------
# POST /resolve
# ---------------------------------------------------------------------------
@app.post("/resolve", response_model=SemanticResolutionResponse)
async def resolve(request: ResolveRequest) -> SemanticResolutionResponse:
    """Resolve a natural-language query to a canonical ontology URI.

    Steps:
    1. Query the loaded RDF graph for all active domain classes.
    2. Format the results into a string for the LLM prompt.
    3. Call BAML ``ClassifySustainmentIntent`` with the query + ontology context.
    4. Return the ``SemanticResolution`` response.
    """
    # Step 1-2: Extract and format ontology classes from the RDF graph
    active_classes = await _get_active_ontology_classes(domain=request.domain)
    if not active_classes:
        raise HTTPException(
            status_code=404,  # Changed from 500 to 404 for missing domain data
            detail=f"No ontology classes found for domain {request.domain} in the graph database.",
        )

    # Step 3: Call BAML function — LLM classifies intent against live ontology
    try:
        result: BamlSemanticResolution = await b.ClassifySustainmentIntent(
            query=request.query,
            active_ontology_classes=active_classes,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"BAML classification failed: {exc}",
        ) from exc

    # Step 4: Return structured response
    return SemanticResolutionResponse(
        resolved_uri=result.resolved_uri,
        confidence_score=result.confidence_score,
        suggested_dbt_models=result.suggested_dbt_models,
    )


# ---------------------------------------------------------------------------
# POST /plan
# ---------------------------------------------------------------------------
@app.post("/plan")
async def plan_query(request: PlanRequest) -> dict:
    """
    Decompose a complex user query into a list of specific sub-tasks
    assigned to different personas using the LLM.
    """
    try:
        # INJECT active_personas HERE
        plan = await b.DecomposeQuery(
            raw_query=request.query,
            active_personas=get_baml_persona_string()
        )
        return {**plan.model_dump(), "domain": request.domain}
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"BAML decomposition failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# POST /route_and_plan
# ---------------------------------------------------------------------------
@app.post("/route_and_plan")
async def route_and_plan(request: RouteAndPlanRequest) -> dict:
    """
    Act as the Kernel Scheduler. Decide whether the query is a ONE_SHOT_QUERY
    (requiring Graph DB) or a PROCESS_CREATION (requiring the Restate Interviewer),
    and determine the target domain.
    """
    try:
        # INJECT BOTH active_personas AND active_domains HERE
        decision = await b.RouteAndPlan(
            user_query=request.query,
            active_personas=get_baml_persona_string(),
            active_domains=get_baml_domain_string()
        )
        res = decision.model_dump()
        
        # Inject domain into tasks so downstream consumers (Dagster/etc.) always see it
        # This fixes the "Invisible Bug" where domain was lost in the decomposition.
        if res.get("task_plan") and res["task_plan"].get("tasks"):
            for task in res["task_plan"]["tasks"]:
                task["domain"] = res.get("domain")
        
        return res
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"BAML routing failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# POST /classes — list active ontology classes for a domain
# ---------------------------------------------------------------------------
@app.post("/classes")
async def classes(request: ResolveRequest) -> dict:
    """Return all active ontology classes for the requested domain.

    Useful for discovery and for populating UI dropdowns or LLM context.
    """
    rows = await execute_sparql(_SPARQL_MAINTENANCE_CLASSES, domain=request.domain)
    results = []
    for row in rows:
        results.append({
            "uri": row.get("cls"),
            "label": row.get("label"),
            "definition": row.get("definition"),
            "example": row.get("example"),
        })
    return {"classes": results, "count": len(results), "domain": request.domain}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Simple liveness probe."""
    return {"status": "ok", "jena_reachable": _JENA_ENDPOINT != ""}

@app.get("/mesh/config")
async def get_mesh_config():
    """Serves the UI configuration derived from the Master Registry."""
    ui_personas = {k: v["ui"] for k, v in MASTER_PERSONAS.items()}
    return {"personas": ui_personas, "status": "ONLINE"}


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8084)
