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
IOF = rdflib.Namespace(
    "https://spec.industrialontologies.org/ontology/core/Core/"
)
MRO = rdflib.Namespace(
    "https://spec.industrialontologies.org/ontology/maintenance/"
    "MaintenanceReferenceOntology/"
)

# ---------------------------------------------------------------------------
# Global graph — populated on startup
# ---------------------------------------------------------------------------
_graph: rdflib.Graph | None = None

# SPARQL: find all named OWL classes that are a subclass of iof:Process or
# iof:MaterialEntity (i.e. the sustainment-domain classes, not the top anchors
# themselves) along with their human-readable labels and definitions.
_SPARQL_TOP_LEVEL_CLASSES = """
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX iof:  <https://spec.industrialontologies.org/ontology/core/Core/>

SELECT ?cls ?label ?definition
WHERE {
    ?cls a owl:Class ;
         rdfs:subClassOf+ ?parent ;
         rdfs:label ?label .
    OPTIONAL { ?cls skos:definition ?definition . }
    FILTER (?parent IN (iof:Process, iof:MaterialEntity))
}
ORDER BY ?label
"""


def _load_graph() -> rdflib.Graph:
    """Parse the IOF MRO .ttl file into an rdflib Graph."""
    ttl_path = Path(__file__).with_name("iof_mro.ttl")
    if not ttl_path.exists():
        raise FileNotFoundError(f"Ontology file not found: {ttl_path}")
    g = rdflib.Graph()
    g.parse(str(ttl_path), format="turtle")
    return g


def _get_active_ontology_classes(g: rdflib.Graph) -> str:
    """Query the graph for sustainment-domain classes and format them as a
    newline-delimited string of ``URI — Label: Definition`` entries suitable
    for injection into the BAML prompt."""
    rows = g.query(_SPARQL_TOP_LEVEL_CLASSES)
    lines: list[str] = []
    for row in rows:
        uri = str(row.cls)
        label = str(row.label)
        definition = str(row.definition) if row.definition else "No definition available."
        lines.append(f"{uri} — {label}: {definition}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FastAPI lifespan — load graph once on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    _graph = _load_graph()
    triple_count = len(_graph)
    print(f"[ontology-service] Loaded {triple_count} triples from iof_mro.ttl")
    yield
    _graph = None


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
class ResolveRequest(BaseModel):
    """Incoming request to the /resolve endpoint."""
    query: str


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
    1. Query the loaded RDF graph for all active sustainment-domain classes.
    2. Format the results into a string for the LLM prompt.
    3. Call BAML ``ClassifySustainmentIntent`` with the query + ontology context.
    4. Return the ``SemanticResolution`` response.
    """
    if _graph is None:
        raise HTTPException(status_code=503, detail="Ontology graph not loaded.")

    # Step 1-2: Extract and format ontology classes from the RDF graph
    active_classes = _get_active_ontology_classes(_graph)
    if not active_classes:
        raise HTTPException(
            status_code=500,
            detail="No ontology classes found in the loaded graph.",
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
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    """Simple liveness probe."""
    return {
        "status": "ok",
        "graph_loaded": _graph is not None,
        "triple_count": len(_graph) if _graph else 0,
    }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8084)
