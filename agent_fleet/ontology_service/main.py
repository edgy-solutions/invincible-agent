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
# Global graph — populated on startup
# ---------------------------------------------------------------------------
_graph: rdflib.Graph | None = None

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


def _load_graph() -> rdflib.Graph:
    """Parse IOF MRO ontology files into an rdflib Graph.

    Loads the real IOF Maintenance.rdf first, then falls back to the
    dummy iof_mro.ttl if not present.
    """
    service_dir = Path(__file__).parent
    g = rdflib.Graph()

    # Prefer the real IOF MRO (RDF/XML format)
    real_rdf = service_dir / "Maintenance.rdf"
    if real_rdf.exists():
        g.parse(str(real_rdf), format="xml")
        return g

    # Fall back to dummy Turtle file
    ttl_path = service_dir / "iof_mro.ttl"
    if not ttl_path.exists():
        raise FileNotFoundError(
            f"No ontology file found in {service_dir}. "
            "Expected Maintenance.rdf or iof_mro.ttl."
        )
    g.parse(str(ttl_path), format="turtle")
    return g


def _get_active_ontology_classes(g: rdflib.Graph) -> str:
    """Query the graph for maintenance-domain classes and format them as a
    newline-delimited string of ``URI — Label: Definition`` entries suitable
    for injection into the BAML prompt."""
    rows = g.query(_SPARQL_MAINTENANCE_CLASSES)
    lines: list[str] = []
    for row in rows:
        uri = str(row.cls)
        label = str(row.label)
        definition = str(row.definition) if row.definition else "No definition available."
        example = f" Examples: {row.example}" if row.example else ""
        lines.append(f"{uri} — {label}: {definition}{example}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# FastAPI lifespan — load graph once on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    _graph = _load_graph()
    triple_count = len(_graph)
    classes = _get_active_ontology_classes(_graph)
    class_count = len(classes.strip().splitlines()) if classes.strip() else 0
    print(f"[ontology-service] Loaded {triple_count} triples, {class_count} maintenance classes")
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
# GET /classes — list active ontology classes
# ---------------------------------------------------------------------------
@app.get("/classes")
async def classes() -> dict:
    """Return all active sustainment-domain ontology classes.

    Useful for discovery and for populating UI dropdowns or LLM context.
    """
    if _graph is None:
        raise HTTPException(status_code=503, detail="Ontology graph not loaded.")

    rows = _graph.query(_SPARQL_MAINTENANCE_CLASSES)
    results = []
    for row in rows:
        results.append({
            "uri": str(row.cls),
            "label": str(row.label),
            "definition": str(row.definition) if row.definition else None,
            "example": str(row.example) if row.example else None,
        })
    return {"classes": results, "count": len(results)}


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
