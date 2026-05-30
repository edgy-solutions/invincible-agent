"""
Engine O — Ontology Reasoner Microservice

A lightweight FastAPI service that translates natural language into standard
IOF/MIMOSA sustainment terms using an RDF graph and BAML-based LLM
classification.

This service does NO compute or orchestration. It strictly:
1. Loads the IOF MRO ontology (.ttl) into an rdflib graph on startup.
2. Queries the graph for active ontology classes and their definitions.
3. Passes the user query + ontology context to BAML ClassifyDomainIntent.
4. Returns a SemanticResolution response.

Run: uvicorn agent_fleet.ontology_service.main:app --host 0.0.0.0 --port 8084
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import rdflib
import weaviate
import weaviate.classes as wvc
from neo4j import GraphDatabase
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Add baml_shared to the Python path so we can import the generated client.
# In CNB containers, baml_client is copied locally — this is only for dev.
# ---------------------------------------------------------------------------
try:
    _REPO_ROOT = Path(__file__).resolve().parents[2]
    _BAML_CLIENT_PATH = _REPO_ROOT / "baml_shared" / "baml_client"
    if str(_BAML_CLIENT_PATH) not in sys.path:
        sys.path.insert(0, str(_BAML_CLIENT_PATH))
except IndexError:
    pass  # Running in CNB container — baml_client is already in /workspace/

from baml_client import b  # noqa: E402  — BAML async client
from baml_client.types import SemanticResolution as BamlSemanticResolution  # noqa: E402
from baml_client.type_builder import TypeBuilder

# Initialize runtime BAML configuration logic
try:
    from llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    try:
        from agent_fleet.llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Fleet-standard utilities
# ---------------------------------------------------------------------------
try:
    from utils.weaviate_utils import create_weaviate_client
except ImportError:
    try:
        from agent_fleet.utils.weaviate_utils import create_weaviate_client
    except ImportError:
        # Fallback for flat layout in container
        from weaviate_utils import create_weaviate_client

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
_JENA_USERNAME = os.getenv("JENA_USERNAME", "admin")
_JENA_PASSWORD = os.getenv("FUSEKI_PASSWORD", "Admin123!")
_LOCAL_GRAPH = None

# Weaviate Configuration
_WEAVIATE_CLIENT = None

# Neo4j Configuration
_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j.default.svc.cluster.local:7687")
_NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
_NEO4J_DRIVER = None

# ---------------------------------------------------------------------------
# Persona / Domain registry (ADR-0009 Step E')
# ---------------------------------------------------------------------------
# Per ADR-0009 the active personas and domains are derived from the predicate
# graph — every engine self-declares its `owner_persona` and `domains` at
# registration; doc-tools projects those into Neo4j relationship properties;
# Engine O reads them via the view-functions in registry_views.py. There is
# no MASTER_INTENTS replacement — intent collapses into the binary `mode`
# discriminator decided by ExtractIntent (Step F').
#
# The view-functions live in a sibling module so they can be unit-tested
# without pulling in this file's heavy import chain (rdflib, weaviate,
# baml_client).
from agent_fleet.ontology_service.registry_views import (  # noqa: E402
    PERSONA_UI_METADATA as _PERSONA_UI_METADATA,
    DEFAULT_PERSONA_UI as _DEFAULT_PERSONA_UI,
    LEGACY_PERSONA_PROMPTS as _LEGACY_PERSONA_PROMPTS,
    LEGACY_DOMAIN_PROMPTS as _LEGACY_DOMAIN_PROMPTS,
    LEGACY_INTENT_PROMPTS as _LEGACY_INTENT_PROMPTS,
    fetch_active_personas as _fetch_personas_with_driver,
    fetch_active_domains as _fetch_domains_with_driver,
    get_baml_persona_string as _persona_string_with_driver,
    get_baml_domain_string as _domain_string_with_driver,
)


async def fetch_active_personas() -> list[str]:
    return await _fetch_personas_with_driver(_NEO4J_DRIVER)


async def fetch_active_domains() -> list[str]:
    return await _fetch_domains_with_driver(_NEO4J_DRIVER)


async def get_baml_persona_string() -> str:
    return await _persona_string_with_driver(_NEO4J_DRIVER)


async def get_baml_domain_string() -> str:
    return await _domain_string_with_driver(_NEO4J_DRIVER)

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
    # Both Maintenance and Manufacturing use the core MRO/IOF ontology graph
    if domain in ["MAINTENANCE", "MANUFACTURING"]:
        named_graph = "<http://internal/mro>"
    elif domain == "SUSTAINMENT":
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
            last_brace_idx = scoped_query.rfind("}")
            if last_brace_idx != -1:
                scoped_query = scoped_query[:last_brace_idx] + "} }" + scoped_query[last_brace_idx+1:]
        elif "WHERE {" in query.upper():
            # Handle case-insensitive WHERE
            import re
            scoped_query = re.sub(r"WHERE\s*\{", f"WHERE {{ GRAPH {named_graph} {{", query, flags=re.IGNORECASE, count=1)
            last_brace_idx = scoped_query.rfind("}")
            if last_brace_idx != -1:
                scoped_query = scoped_query[:last_brace_idx] + "} }" + scoped_query[last_brace_idx+1:]

    # 🚀 PATH A: Apache Jena Fuseki via HTTP
    if _JENA_ENDPOINT:
        try:
            async with httpx.AsyncClient(timeout=5.0, auth=(_JENA_USERNAME, _JENA_PASSWORD), verify=False) as client:
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
            # Safely convert rdflib result row, preserving None types to avoid 'None' strings
            row_dict = {
                str(k): str(v) if v is not None else None 
                for k, v in row.asdict().items()
            }
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


async def _check_jena_populated():
    """Check if Apache Jena has data in the named graphs."""
    if not _JENA_ENDPOINT:
        return
        
    try:
        # Check if empty (attempt to select 1 triple from any named graph)
        rows = await execute_sparql("SELECT * WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 1")
        if rows:
            print("[ontology-service] Jena dataset is populated.")
        else:
            print("[ontology-service] WARNING: Jena dataset appears empty. Please run the setup script.")
    except Exception as e:
        print(f"[ontology-service] Error checking Jena dataset: {e}")


# ---------------------------------------------------------------------------
# FastAPI lifespan — verify connectivity on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _WEAVIATE_CLIENT, _NEO4J_DRIVER
    
    # Initialize Weaviate with Fleet-Standard Custom Connection
    try:
        _WEAVIATE_CLIENT = create_weaviate_client()
    except Exception as e:
        print(f"[ontology-service] FAILED to connect to Weaviate: {e}")

    # Initialize Neo4j
    try:
        _NEO4J_DRIVER = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        _NEO4J_DRIVER.verify_connectivity()
        print(f"[ontology-service] Connected to Neo4j at {_NEO4J_URI}")
    except Exception as e:
        print(f"[ontology-service] FAILED to connect to Neo4j: {e}")

    await _check_jena_populated()
    yield
    if _WEAVIATE_CLIENT:
        _WEAVIATE_CLIENT.close()
    if _NEO4J_DRIVER:
        _NEO4J_DRIVER.close()


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


class RouteIntentRequest(BaseModel):
    """Incoming request to the /route_intent endpoint (ADR-0009 Step F').

    Carries the user's natural-language query and (optionally) the caller's
    entitled domains so the supervisor can scope the downstream /find_tool
    match. ``user_persona`` is informational — the predicate's
    ``owner_persona`` drives answerer-persona selection; user_persona is
    the fallback when the matched predicate is persona-agnostic.
    """
    query: str
    user_persona: str | None = None
    entitled_domains: list[str] = []


class RouteIntentResponse(BaseModel):
    """Output of /route_intent — what the gateway uses to route.

    Per ADR-0009 Step F'.6 ``candidate_verb`` is gone — Engine O's
    /search_predicates runs Weaviate hybrid over the raw user query
    directly, so an LLM-extracted verb is a lossy intermediate step. The
    remaining LLM-derived fields are:

      * ``mode`` — binary routing discriminator (conversational vs
        one-shot). Real LLM judgment about intent shape.
      * ``entity_refs`` — concrete nouns for the supervisor's /resolve
        call when grounding subjects/objects to ontology URIs.

    ``user_persona`` and ``entitled_domains`` are echoed back so the
    gateway can thread them to the supervisor without re-decoding the JWT.
    """
    mode: str  # "ONE_SHOT" | "CONVERSATIONAL"
    entity_refs: list[str]
    confidence: float
    reasoning: str
    user_persona: str | None = None
    entitled_domains: list[str] = []


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
    reasoning: str | None = None

class LegacyTableDossier(BaseModel):
    table_name: str
    columns_schema: str = "Unknown"
    dba_comments: str = "None provided"
    orm_class_name: str = "None provided"
    sample_data: str = "None provided"
    domain: str = "DATA_ENGINEERING"

class TableClassificationResponse(BaseModel):
    resolved_uri: str | None
    confidence_score: float
    reasoning: str


# ---------------------------------------------------------------------------
# Predicate-graph routing (iagent ADR-0004 Step C)
# ---------------------------------------------------------------------------
# These models describe the single-step and multi-step routing queries the
# supervisor calls. ``/find_tool`` resolves an (input, verb) -> tool edge
# directly; ``/find_path`` resolves an (input, output) composition over up
# to ``max_hops`` predicate edges. Neither endpoint touches the LLM -- the
# NLP-side (/route_and_plan, /resolve) calls these *after* it has resolved
# NL into a (verb_label, subject_uri) pair.
_VALID_COST_CLASSES = ("fast", "medium", "slow")


class FindToolRequest(BaseModel):
    """Single-step routing query.

    The ``verb_label`` field accepts any of:
      - the relationship type itself, e.g. ``"applyDiagnostics"``
      - the full namespaced IRI, e.g. ``"mro:applyDiagnostics"``
      - any registered synonym from ``r.synonyms``
    """
    subject_uri: str = Field(..., description="OntologyClass URI of the operation's input")
    verb_label: str = Field(..., description="Verb to invoke -- relationship type, IRI, or synonym")


class FindToolStep(BaseModel):
    """One predicate edge in a routing result."""
    verb_type: str
    verb_iri: str
    endpoint: str
    output_uri: str
    owner_persona: str | None = None
    cost_class: str | None = None
    requires_human_approval: bool = False
    openapi_schema: str | None = None


class SearchPredicatesRequest(BaseModel):
    """ADR-0009 Step F'.6: NL-driven predicate lookup with domain scoping.

    ``query`` is the user's NL text. Engine O runs Weaviate hybrid search
    (BM25 + vector) over the ``Predicate.search_text`` blob (humanized verb
    form + synonyms + description) and returns ranked candidates. This is
    the only routing path — exact verb-token matching belongs on
    ``/find_tool`` (which takes ``(subject_uri, verb_label)``).

    ``entitled_domains`` filters at the Weaviate layer: callers see
    predicates whose ``r.domains`` shares an entry with their scope OR is
    empty (domain-agnostic). An empty entitled_domains list means "no
    scope filter applied" (admin / system caller).
    """
    query: str = Field(..., description="NL phrasing — drives Weaviate hybrid search")
    entitled_domains: list[str] = Field(default_factory=list, description="Caller's entitled domain scopes")
    limit: int = Field(10, ge=1, le=50)


class PredicateCandidate(BaseModel):
    """One row of a /search_predicates result — includes subject_uri so the
    supervisor knows what concept this predicate operates over.

    ``score`` is the Weaviate hybrid score (0..1+). Always present since
    Weaviate is the only routing path.
    """
    subject_uri: str
    verb_type: str
    verb_iri: str
    endpoint: str
    output_uri: str
    owner_persona: str | None = None
    domains: list[str] = Field(default_factory=list)
    cost_class: str | None = None
    requires_human_approval: bool = False
    openapi_schema: str | None = None
    score: float | None = Field(None, description="Weaviate hybrid score")


class SearchPredicatesResponse(BaseModel):
    found: bool
    candidates: list[PredicateCandidate] = Field(default_factory=list)
    reason: str | None = None


class FindToolResponse(BaseModel):
    found: bool
    step: FindToolStep | None = None
    reason: str | None = None


class FindPathRequest(BaseModel):
    """Multi-step composition query."""
    start_uri: str = Field(..., description="OntologyClass URI to start from")
    end_uri: str = Field(..., description="OntologyClass URI to terminate in")
    max_hops: int = Field(4, ge=1, le=8, description="Maximum predicate edges to traverse")
    allowed_cost_classes: list[str] = Field(
        default_factory=lambda: list(_VALID_COST_CLASSES),
        description="Filter edges by cost class; empty means all classes allowed",
    )
    exclude_human_approval: bool = Field(
        False,
        description="If true, skip edges where requires_human_approval=true",
    )


class FindPathResponse(BaseModel):
    found: bool
    hops: int | None = None
    total_latency_budget_ms: int | None = None
    steps: list[FindToolStep] = Field(default_factory=list)
    reason: str | None = None


def _weaviate_hybrid_search_sync(query: str, domain: str, limit: int = 10) -> list[dict]:
    """Synchronous hybrid search implementation. gRPC blocks here.

    Always invoke via ``await asyncio.to_thread(...)`` from async paths so
    the event loop stays free and /health keeps responding.
    """
    if not _WEAVIATE_CLIENT:
        return []
    try:
        collection = _WEAVIATE_CLIENT.collections.get("OntologyClass")
        # Using hybrid search (BM25 + Vector)
        # Filter by domain if provided
        filters = wvc.query.Filter.by_property("domain").equal(domain.upper()) if domain else None

        response = collection.query.hybrid(
            query=query,
            limit=limit,
            filters=filters
        )
        return [{"uri": obj.properties["uri"], "label": obj.properties["label"], "description": obj.properties.get("definition", "")} for obj in response.objects]
    except Exception as e:
        print(f"Weaviate search failed: {e}")
        return []


async def weaviate_hybrid_search(query: str, domain: str, limit: int = 10) -> list[dict]:
    """Async wrapper that runs the blocking hybrid search on a worker thread."""
    return await asyncio.to_thread(_weaviate_hybrid_search_sync, query, domain, limit)


# ---------------------------------------------------------------------------
# Predicate hybrid search (ADR-0009 Step F'.6)
# ---------------------------------------------------------------------------
#: Name of the Weaviate collection where doc-tools mirrors registered
#: predicates. Created by doc-tools' AITool sync on first registration.
_PREDICATE_COLLECTION = "Predicate"


def _predicate_hybrid_search_sync(
    query: str,
    entitled_domains: list[str],
    limit: int,
) -> list[dict]:
    """Blocking Weaviate hybrid search over the Predicate collection.

    Returns one dict per candidate with the routing fields the supervisor
    needs (verb_iri, endpoint, owner_persona, domains, ...) plus the
    Weaviate hybrid ``score`` so the caller can rank or threshold. Empty
    list means the collection is empty, missing, or unreachable — caller
    should fall back to Cypher exact-match.

    Domain scoping is done as a Weaviate filter when the caller supplied
    entitled_domains AND we want to keep domain-agnostic predicates too
    (r.domains == []). We express that as an OR of two filters; if neither
    branch matches, the candidate is dropped.
    """
    if not _WEAVIATE_CLIENT:
        return []
    try:
        if not _WEAVIATE_CLIENT.collections.exists(_PREDICATE_COLLECTION):
            return []
        collection = _WEAVIATE_CLIENT.collections.get(_PREDICATE_COLLECTION)

        # Build domain filter: pass through everything when entitled_domains
        # is empty (unscoped caller); otherwise keep predicates that either
        # declare a domain we're entitled to OR declare no domains at all
        # (domain-agnostic engines, e.g. Engine A's fallback path).
        filters = None
        if entitled_domains:
            # Weaviate v4 Filter: contains_any over domains list, OR
            # is_null=True (the collection writes empty lists, not nulls,
            # so we use len == 0 by checking against an empty-array equal).
            filters = wvc.query.Filter.any_of([
                wvc.query.Filter.by_property("domains").contains_any(entitled_domains),
                # Match domain-agnostic predicates (empty domains array).
                wvc.query.Filter.by_property("domains").equal([]),
            ])

        response = collection.query.hybrid(
            query=query,
            limit=limit,
            filters=filters,
            return_metadata=wvc.query.MetadataQuery(score=True),
        )

        out: list[dict] = []
        for obj in response.objects:
            p = obj.properties
            score = None
            if obj.metadata and obj.metadata.score is not None:
                try:
                    score = float(obj.metadata.score)
                except (TypeError, ValueError):
                    score = None
            out.append({
                "verb_iri": p.get("verb_iri", ""),
                "verb_type": p.get("verb_local", ""),
                "input_uri": p.get("input_uri", ""),
                "output_uri": p.get("output_uri", ""),
                "endpoint": p.get("endpoint_url", ""),
                "owner_persona": p.get("owner_persona") or None,
                "domains": list(p.get("domains") or []),
                "cost_class": p.get("cost_class") or None,
                "requires_human_approval": bool(p.get("requires_human_approval", False)),
                "score": score,
            })
        return out
    except Exception as e:
        # Routing accelerator — failures degrade the system, not crash it.
        print(f"[ontology-service] Predicate hybrid search failed: {e}")
        return []


async def predicate_hybrid_search(
    query: str, entitled_domains: list[str], limit: int = 10
) -> list[dict]:
    """Async wrapper for the predicate hybrid search."""
    return await asyncio.to_thread(
        _predicate_hybrid_search_sync, query, entitled_domains, limit
    )


# ---------------------------------------------------------------------------
# POST /resolve
# ---------------------------------------------------------------------------
@app.post("/resolve", response_model=SemanticResolutionResponse)
async def resolve(request: ResolveRequest) -> SemanticResolutionResponse:
    """Resolve a natural-language query to a canonical ontology URI using Late Binding.

    Steps:
    1. Hybrid Search in Weaviate for the Top 10 most relevant classes.
    2. Inject these candidates into BAML TypeBuilder as a dynamic enum.
    3. Call BAML ClassifyDomainIntent to strictly select the best match.
    """
    # Step 1: Hybrid Search for candidates in Weaviate
    candidates = await weaviate_hybrid_search(query=request.query, domain=request.domain, limit=10)
    
    # Step 1.5: COLD START FALLBACK -> If Weaviate is empty, read the RDF graph
    if not candidates:
        print("="*60)
        print(f"⚠️ [WARNING] WEAVIATE COLD START DETECTED: {request.domain}")
        print("⚠️ No vectors found. Falling back to raw SPARQL/RDF Graph.")
        print("⚠️ Action Required: doc-tools pipeline must sync ontologies into Weaviate.")
        print("="*60)
        
        rows = await execute_sparql(_SPARQL_MAINTENANCE_CLASSES, domain=request.domain)
        for row in rows:
            candidates.append({
                "uri": row.get("cls"),
                "label": row.get("label"),
                "description": row.get("definition") or "No definition provided."
            })
            
    # Step 1.6: Ultimate Fallback (Prevents Restate infinite loops)
    if not candidates:
        return SemanticResolutionResponse(
            resolved_uri="UNKNOWN",
            confidence_score=0.0,
            reasoning=f"No ontology classes found in Weaviate OR the RDF graph for domain {request.domain}."
        )

    # Step 2: Build BAML TypeBuilder
    tb = TypeBuilder()
    for cls in candidates:
        tb.OntologyClass.add_value(cls["uri"]).description(f"{cls['label']}: {cls['description']}")

    # Step 3: Call BAML function with strictly constrained enum
    try:
        result = await b.ClassifyDomainIntent(
            query=request.query,
            domain=request.domain,
            baml_options={"tb": tb}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"BAML classification failed: {exc}",
        ) from exc

    # Step 4: Return structured response
    return SemanticResolutionResponse(
        resolved_uri=str(result.resolved_uri),
        confidence_score=result.confidence_score,
        reasoning=result.reasoning
    )


# ---------------------------------------------------------------------------
# GET /get_physical_assets
# ---------------------------------------------------------------------------
@app.get("/get_physical_assets")
async def get_physical_assets(uri: str = Query(..., description="The Ontology URI to resolve to physical assets")) -> dict:
    """Query Neo4j for physical DataAsset URNs linked to an Ontology URI via [:HAS_DATA]."""
    if not _NEO4J_DRIVER:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized.")
        
    try:
        with _NEO4J_DRIVER.session() as session:
            # Execute the live Cypher query
            result = session.run(
                "MATCH (o:OntologyClass {uri: $uri})-[:HAS_DATA]->(d:DataAsset) RETURN d.urn as urn",
                uri=uri
            )
            urns = [record["urn"] for record in result]
            return {
                "ontology_uri": uri,
                "physical_assets": urns,
                "count": len(urns)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j query failed: {e}")


# ---------------------------------------------------------------------------
# Predicate-graph routing (iagent ADR-0004 Step C)
# ---------------------------------------------------------------------------
# Two pure-Cypher endpoints over the predicate graph that doc-tools' AITool
# binding plane materializes. No LLM, no Weaviate -- deterministic graph
# queries the supervisor and the NLP-side endpoints call to make routing
# decisions.
#
# ``/find_tool`` resolves a single (subject_uri, verb_label) -> tool edge.
# ``/find_path`` resolves a multi-step (start_uri, end_uri) composition.
#
# The supervisor walks ``steps`` in order, threading each step's output as
# the next step's input.

# Single-step Cypher. We match on three possible "verb_label" forms so the
# caller can pass either a resolved IRI (from BAML / TypeBuilder) or a
# user-facing synonym (rare; usually post-resolution it's the IRI).
_FIND_TOOL_CYPHER = """
MATCH (s:OntologyClass {uri: $subject_uri})-[r]->(o:OntologyClass)
WHERE type(r) = $verb_label
   OR r.iri  = $verb_label
   OR $verb_label IN coalesce(r.synonyms, [])
RETURN type(r)                  AS verb_type,
       r.iri                    AS verb_iri,
       r.endpoint_url           AS endpoint,
       o.uri                    AS output_uri,
       r.owner_persona          AS owner_persona,
       r.cost_class             AS cost_class,
       r.requires_human_approval AS requires_human_approval,
       r.openapi_schema         AS openapi_schema
ORDER BY CASE coalesce(r.cost_class, 'slow')
              WHEN 'fast' THEN 0
              WHEN 'medium' THEN 1
              ELSE 2
         END
LIMIT 1
"""




def _build_find_path_cypher(max_hops: int) -> str:
    """Build the variable-length-path Cypher with the validated ``max_hops``
    interpolated. Cypher does not let the hop range be a parameter; we
    template it after bounding the value via Pydantic (1..8)."""
    return f"""
    MATCH path = (start:OntologyClass {{uri: $start_uri}})
                 -[rs*1..{max_hops}]->
                 (end:OntologyClass {{uri: $end_uri}})
    WHERE all(r IN relationships(path)
              WHERE coalesce(r.cost_class, 'slow') IN $allowed_cost_classes
                AND (NOT $exclude_human_approval
                     OR coalesce(r.requires_human_approval, false) = false))
    WITH path, relationships(path) AS rels, length(path) AS hops
    RETURN [
        r IN rels |
        {{
            verb_type:               type(r),
            verb_iri:                r.iri,
            endpoint:                r.endpoint_url,
            output_uri:              endNode(r).uri,
            owner_persona:           r.owner_persona,
            cost_class:              r.cost_class,
            requires_human_approval: coalesce(r.requires_human_approval, false),
            openapi_schema:          r.openapi_schema
        }}
    ] AS steps,
    hops,
    reduce(t = 0, r IN rels | t + coalesce(r.latency_budget_ms, 0)) AS total_latency_budget_ms
    ORDER BY hops ASC, total_latency_budget_ms ASC
    LIMIT 1
    """


@app.post("/find_tool", response_model=FindToolResponse)
async def find_tool(request: FindToolRequest) -> FindToolResponse:
    """Resolve a single predicate edge from ``(subject_uri, verb_label)``.

    Returns the cheapest matching edge (by ``cost_class``) -- the supervisor
    can call this from a request handler without paying any LLM cost.
    """
    if not _NEO4J_DRIVER:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized.")

    def _run() -> dict | None:
        with _NEO4J_DRIVER.session() as session:
            record = session.run(
                _FIND_TOOL_CYPHER,
                subject_uri=request.subject_uri,
                verb_label=request.verb_label,
            ).single()
            if not record:
                return None
            return dict(record)

    try:
        record = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j query failed: {e}")

    if not record:
        return FindToolResponse(
            found=False,
            reason=(
                f"No predicate edge from subject_uri={request.subject_uri!r} "
                f"matches verb_label={request.verb_label!r}. "
                f"Either the verb is not registered, the subject concept is not "
                f"in the graph, or the SDK registration has not yet synced."
            ),
        )

    return FindToolResponse(
        found=True,
        step=FindToolStep(
            verb_type=record["verb_type"],
            verb_iri=record["verb_iri"] or "",
            endpoint=record["endpoint"] or "",
            output_uri=record["output_uri"],
            owner_persona=record["owner_persona"],
            cost_class=record["cost_class"],
            requires_human_approval=bool(record["requires_human_approval"]),
            openapi_schema=record["openapi_schema"],
        ),
    )


@app.post("/search_predicates", response_model=SearchPredicatesResponse)
async def search_predicates(request: SearchPredicatesRequest) -> SearchPredicatesResponse:
    """ADR-0009 Step F'.6: NL → predicate routing via Weaviate hybrid search.

    Weaviate is the only routing path. If the client is unreachable or
    the Predicate collection doesn't exist, this returns 503 so callers
    (gateway, supervisor) see a hard routing failure rather than a silent
    degradation. Engine startup-time concerns are doc-tools' problem —
    once an engine has registered to DataHub, the AITool sensor mirrors
    it into both Neo4j and Weaviate within seconds, so Weaviate being
    "cold" is a brand-new-cluster transient that self-heals.

    Scope semantics:
      * Empty entitled_domains → no scope filter (unscoped / admin).
      * Domain-agnostic predicates (``r.domains == []``) are always kept.
      * Domain-scoped predicates require at least one shared entry.

    Exact ``(subject_uri, verb_label)`` lookups belong on ``/find_tool``;
    this endpoint is exclusively NL-driven.
    """
    if not _WEAVIATE_CLIENT or not _WEAVIATE_CLIENT.collections.exists(
        _PREDICATE_COLLECTION
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Weaviate Predicate collection is unavailable. Routing "
                "cannot proceed until doc-tools has synced at least one "
                "registered engine. Use /find_tool for exact "
                "(subject_uri, verb_label) lookups while this is being "
                "investigated."
            ),
        )

    # Defensive: domains arrive uppercase from the auth layer but a
    # mis-cased POST still scopes correctly.
    entitled = [d.upper() for d in (request.entitled_domains or [])]

    hits = await predicate_hybrid_search(
        query=request.query,
        entitled_domains=entitled,
        limit=request.limit,
    )

    if not hits:
        return SearchPredicatesResponse(
            found=False,
            reason=(
                f"No predicate matched query={request.query!r} under "
                f"entitled_domains={entitled}. Either no engine is "
                f"registered for what this NL describes, or no "
                f"domain-scoped engine serves it for this caller."
            ),
        )

    candidates = [
        PredicateCandidate(
            subject_uri=h["input_uri"],  # SPO: input concept = subject
            verb_type=h["verb_type"],
            verb_iri=h["verb_iri"],
            endpoint=h["endpoint"],
            output_uri=h["output_uri"],
            owner_persona=h["owner_persona"],
            domains=h["domains"],
            cost_class=h["cost_class"],
            requires_human_approval=h["requires_human_approval"],
            openapi_schema=None,  # not stored in Weaviate; retrieve from Neo4j when needed
            score=h["score"],
        )
        for h in hits
    ]

    return SearchPredicatesResponse(found=True, candidates=candidates)


@app.post("/find_path", response_model=FindPathResponse)
async def find_path(request: FindPathRequest) -> FindPathResponse:
    """Resolve a multi-step composition from ``start_uri`` to ``end_uri``.

    Returns the shortest path that respects the ``allowed_cost_classes`` and
    ``exclude_human_approval`` filters, breaking ties by total latency budget.
    The supervisor walks ``steps`` in order, threading each step's output as
    the next step's input.
    """
    if not _NEO4J_DRIVER:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized.")

    # Validate ``allowed_cost_classes`` to keep the Cypher parameter clean.
    invalid = [c for c in request.allowed_cost_classes if c not in _VALID_COST_CLASSES]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid cost class(es) {invalid!r}; "
                f"allowed: {list(_VALID_COST_CLASSES)}"
            ),
        )

    cypher = _build_find_path_cypher(request.max_hops)

    def _run() -> dict | None:
        with _NEO4J_DRIVER.session() as session:
            record = session.run(
                cypher,
                start_uri=request.start_uri,
                end_uri=request.end_uri,
                allowed_cost_classes=request.allowed_cost_classes or list(_VALID_COST_CLASSES),
                exclude_human_approval=request.exclude_human_approval,
            ).single()
            if not record:
                return None
            return dict(record)

    try:
        record = await asyncio.to_thread(_run)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j query failed: {e}")

    if not record:
        return FindPathResponse(
            found=False,
            reason=(
                f"No path from {request.start_uri!r} to {request.end_uri!r} "
                f"within max_hops={request.max_hops} that respects the "
                f"cost_class / human_approval filters. Either no composition "
                f"exists, or the relevant predicate edges have not yet synced."
            ),
        )

    steps = [
        FindToolStep(
            verb_type=s["verb_type"],
            verb_iri=s.get("verb_iri") or "",
            endpoint=s.get("endpoint") or "",
            output_uri=s["output_uri"],
            owner_persona=s.get("owner_persona"),
            cost_class=s.get("cost_class"),
            requires_human_approval=bool(s.get("requires_human_approval", False)),
            openapi_schema=s.get("openapi_schema"),
        )
        for s in record["steps"]
    ]
    return FindPathResponse(
        found=True,
        hops=record["hops"],
        total_latency_budget_ms=record["total_latency_budget_ms"],
        steps=steps,
    )


# ---------------------------------------------------------------------------
# POST /classify_legacy_table
# ---------------------------------------------------------------------------
@app.post("/classify_legacy_table", response_model=TableClassificationResponse)
async def classify_legacy_table(request: LegacyTableDossier) -> TableClassificationResponse:
    """
    Ingests a Rich Context Dossier from Dagster and semantically maps 
    the legacy table to an IOF Ontology URI using Late Binding.
    """
    # 1. Search for candidates in Weaviate using the table name/metadata
    query_text = f"{request.table_name} {request.dba_comments}"
    candidates = await weaviate_hybrid_search(query=query_text, domain=request.domain, limit=15)
    
    # 1.5. COLD START FALLBACK -> If Weaviate is empty, read the RDF graph
    if not candidates:
        print("="*60)
        print(f"⚠️ [WARNING] WEAVIATE COLD START DETECTED: {request.domain}")
        print("⚠️ No vectors found. Falling back to raw SPARQL/RDF Graph.")
        print("⚠️ Action Required: doc-tools pipeline must sync ontologies into Weaviate.")
        print("="*60)
        
        rows = await execute_sparql(_SPARQL_MAINTENANCE_CLASSES, domain=request.domain)
        for row in rows:
            candidates.append({
                "uri": row.get("cls"),
                "label": row.get("label"),
                "description": row.get("definition") or "No definition provided."
            })
            
    # 1.6. Ultimate Fallback
    if not candidates:
        return TableClassificationResponse(
            resolved_uri=None,
            confidence_score=0.0,
            reasoning=f"No active ontology classes found in Weaviate OR the RDF graph for domain {request.domain}."
        )

    # 2. Build BAML TypeBuilder
    tb = TypeBuilder()
    for cls in candidates:
        # Use the URI as the enum value for zero-hallucination selection
        tb.OntologyClass.add_value(cls["uri"]).description(f"{cls['label']}: {cls['description']}")

    # 3. Ask the LLM to reason over the dossier with strict constraints
    try:
        result = await b.ClassifyLegacyTable(
            table_name=request.table_name,
            columns_schema=request.columns_schema,
            dba_comments=request.dba_comments,
            orm_class_name=request.orm_class_name,
            sample_data=request.sample_data,
            domain=request.domain,
            baml_options={"tb": tb}
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BAML Table Classification failed: {exc}") from exc

    # 4. Return the structured decision
    return TableClassificationResponse(
        resolved_uri=str(result.resolved_uri) if result.resolved_uri else None,
        confidence_score=result.confidence_score,
        reasoning=result.reasoning
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
        # INJECT active_personas HERE (view-function — see ADR-0009 Step E')
        plan = await b.DecomposeQuery(
            raw_query=request.query,
            active_personas=await get_baml_persona_string()
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
@app.post("/route_intent", response_model=RouteIntentResponse)
async def route_intent(request: RouteIntentRequest) -> RouteIntentResponse:
    """ADR-0009 Step F': verb-extractor + mode discriminator.

    Replaces /route_and_plan's 3-axis classifier. No hardcoded enums beyond
    the binary ``mode``; the candidate_verb feeds the supervisor's
    predicate-graph lookup against r.iri and r.synonyms; entity_refs feed
    /resolve when the supervisor needs to ground them to ontology URIs.

    Behavior is deliberately stateless and side-effect-free — the gateway
    can call this on every request without worrying about ordering.
    """
    try:
        intent = await b.ExtractIntent(user_query=request.query)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"BAML ExtractIntent failed: {exc}",
        ) from exc

    return RouteIntentResponse(
        mode=intent.mode.value if hasattr(intent.mode, "value") else str(intent.mode),
        entity_refs=list(intent.entity_refs or []),
        confidence=float(intent.confidence),
        reasoning=intent.reasoning,
        user_persona=request.user_persona,
        entitled_domains=request.entitled_domains,
    )


@app.post("/route_and_plan")
async def route_and_plan(request: RouteAndPlanRequest) -> dict:
    """
    Legacy 3-axis BAML classifier — kept temporarily so the gateway keeps
    working through the ADR-0009 migration. Step F' replaces this endpoint
    with ExtractIntent (mode + verb extraction); when that lands this body
    becomes ``raise HTTPException(410, "use /route_intent")`` until callers
    migrate.
    """
    try:
        # Per ADR-0009 view-functions: persona/domain lists come from the
        # predicate graph (graceful fallback to the local legacy keys when
        # Neo4j is empty/unreachable). Intent has no graph source — kept as
        # the legacy hardcoded set until Step F' deletes the whole classifier.
        active_personas = await fetch_active_personas()
        active_domains = await fetch_active_domains()

        tb = TypeBuilder()

        for intent_name, description in _LEGACY_INTENT_PROMPTS.items():
            tb.Intent.add_value(intent_name).description(description)

        for domain_name in active_domains:
            tb.Domain.add_value(domain_name).description(
                _LEGACY_DOMAIN_PROMPTS.get(domain_name, "Domain scope.")
            )

        for persona_name in active_personas:
            tb.PersonaTarget.add_value(persona_name).description(
                _LEGACY_PERSONA_PROMPTS.get(persona_name, "Persona-specific specialist.")
            )

        # Execute BAML, passing the TypeBuilder via baml_options
        decision = await b.RouteAndPlan(
            user_query=request.query,
            baml_options={"tb": tb}
        )
        res = decision.model_dump()

        # 🛡️ Guardhouse intercept: short-circuit out-of-scope queries
        if res.get("intent") == "SYSTEM_META_AND_REJECTION":
            res["reasoning"] = "I am the routing interface for a grounded military technical data mesh. I can assist with Graph part lookups, Diagnostic troubleshooting, and Policy retrieval. I cannot engage in general conversation or process out-of-scope requests."
            res["task_plan"] = None

        # Inject domain into tasks for downstream consumers
        if res.get("task_plan") and res["task_plan"].get("tasks"):
            for task in res["task_plan"]["tasks"]:
                task["domain"] = res.get("domain")

        return res
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BAML routing failed: {exc}") from exc


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

@app.get("/personas")
async def list_personas() -> dict:
    """List active answerer-personas (ADR-0009 view-function).

    Each persona is the distinct ``r.owner_persona`` value across every
    predicate edge in the runtime substrate, dressed with UI metadata for
    the frontend. Unknown personas (engines registering a new one) get a
    default UI treatment until the frontend adds chrome for them.
    """
    personas = await fetch_active_personas()
    return {
        "personas": [
            {
                "name": p,
                "ui": _PERSONA_UI_METADATA.get(p, _DEFAULT_PERSONA_UI),
            }
            for p in personas
        ]
    }


@app.get("/domains")
async def list_domains() -> dict:
    """List active domain scopes (ADR-0009 view-function).

    Each domain is the distinct entry across every predicate edge's
    ``r.domains`` JSON array. /find_tool filters predicate matches against
    the caller's ``user.entitled_domains``; this endpoint is the source of
    truth the UI uses to populate scope pickers.
    """
    domains = await fetch_active_domains()
    return {"domains": domains}


@app.get("/mesh/config")
async def get_mesh_config():
    """Serves the UI configuration derived from the predicate registry.

    Backward-compatible response shape — ``personas`` is still a dict keyed
    by persona name with UI metadata as the value, for callers that haven't
    moved to the new ``/personas`` listing endpoint.
    """
    personas = await fetch_active_personas()
    ui_personas = {
        p: _PERSONA_UI_METADATA.get(p, _DEFAULT_PERSONA_UI)
        for p in personas
    }
    return {"personas": ui_personas, "status": "ONLINE"}


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8084)
