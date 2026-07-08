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
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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

# Shared embedding helper (agent_fleet/utils/embed.py). Container flat-layout
# and source-layout both supported. embed_query is for READ paths — it
# applies the nomic-embed-text task prefix that pairs with embed_document's
# write-side prefix. NEVER call embed_document from a query path or vice
# versa; the prefixes split the embedding space.
try:
    from utils.embed import embed_query  # container flat layout
except ImportError:
    from agent_fleet.utils.embed import embed_query  # source layout

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
# ADR-0015 Phase 1: routing-decisions audit (structured-log substrate).
# ---------------------------------------------------------------------------
# The ADR proposes a Postgres `routing_decisions` table. Phase 1 emits the
# same row shape as a single-line JSON log, so:
#   (a) every /search_predicates decision is queryable via existing log
#       aggregation (Loki/Datadog/Langfuse — no new infra),
#   (b) ADR-0016 §5's revisit trigger has the per-decision substrate it
#       needs without waiting for Postgres ops,
#   (c) ADR-0017's X-Presentation-Path field gets a destination (cortex-bff
#       reads the header and emits its own routing_decision log with
#       presentation_path populated; Engine O writes the engine-routing
#       half).
# Phase 2 (deferred): swap the print() for an async INSERT into a
# bounded asyncio queue draining to Postgres. The row shape is intentionally
# isomorphic to the ADR §3 SQL DDL so the swap is mechanical.
_routing_audit_logger = logging.getLogger("iagent.routing.audit")
# Always emit to stdout so kubectl logs / fluentbit pick it up.
if not _routing_audit_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    _routing_audit_logger.addHandler(_h)
    _routing_audit_logger.setLevel(logging.INFO)
    _routing_audit_logger.propagate = False


def _emit_routing_decision(
    *,
    source: str,
    request_id: str | None,
    user_id: str | None,
    sub_query: str,
    entitled_domains: list[str],
    candidates_raw: list[dict],
    picked_engine: str | None,
    picked_verb: str | None,
    pick_score: float | None,
    pick_margin: float | None,
    fallback_reason: str | None,
    search_ms: int,
    total_ms: int,
) -> None:
    """Emit one routing-decision row as a single-line JSON log.

    The schema mirrors the ADR-0015 §3 SQL DDL exactly so the eventual
    Phase 2 INSERT is a column-for-column copy. ``candidates_filt`` is
    omitted here because the current ``predicate_hybrid_search`` returns
    the post-filter list directly; if we later split raw vs filtered the
    field gets added without breaking consumers.
    """
    try:
        record = {
            "event": "routing_decision",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "request_id": request_id,
            "user_id": user_id,
            "sub_query": sub_query,
            "entitled_domains": entitled_domains,
            "candidates_raw": candidates_raw,
            "picked_engine": picked_engine,
            "picked_verb": picked_verb,
            "pick_score": pick_score,
            "pick_margin": pick_margin,
            "fallback_reason": fallback_reason,
            "search_ms": search_ms,
            "total_ms": total_ms,
        }
        _routing_audit_logger.info(json.dumps(record, default=str))
    except Exception:  # noqa: BLE001 — never let audit emit kill a request
        pass


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

# ─── ADR-0025 ontology-IRI visibility gate ──────────────────────────────────
# Filters the OntologyClass candidate pool through Topaz can_view BEFORE BAML
# classifies (select-from-authorized-set). Single-decider: Topaz decides via the
# ontology_can_view rego; this only ASKS. Flag-gated (dark-launch OFF); when off,
# _can_view_class returns True (no filtering) so behavior is unchanged.
ENABLE_AGENTIC_AUTH = os.getenv("ENABLE_AGENTIC_AUTH", "false").lower() in ("true", "1", "yes")
# Authorizer (Is API) — same endpoint the DA-read gate uses (central_gateway).
TOPAZ_AUTHORIZER_URL = os.getenv("TOPAZ_AUTHORIZER_URL") or os.getenv("TOPAZ_URL") or "http://topaz-svc:8383"
# The per-deployment default for classes with NO compartment assignment. Passed
# to the rego as a POLICY INPUT (not hardcoded): "releasable" (demo/unclassified
# — ordinary vocabulary visible to all) or "deny" (classified — unassigned class
# invisible, fail-CLOSED; assign everything to compartments → whole ontology
# secret). THIS is the configurable-default the compartment ruling requires.
ONTOLOGY_DEFAULT_VISIBILITY = os.getenv("ONTOLOGY_DEFAULT_VISIBILITY", "releasable").lower()


def _can_view_class(caller_email: str, iri: str) -> bool:
    """Ask Topaz whether ``caller_email`` may SEE ontology class ``iri``.

    Single-decider: evaluates the ``invincible_agent.ontology.can_view`` rego
    (compartment grant OR unassigned+releasable). Fail-CLOSED (deny) on any
    error — a security gate must not fail open. No-op (True) when the flag is
    off, so /resolve is unaffected until ENABLE_AGENTIC_AUTH flips.
    """
    if not ENABLE_AGENTIC_AUTH:
        return True
    if not iri:
        return False
    try:
        resp = httpx.post(
            f"{TOPAZ_AUTHORIZER_URL}/api/v2/authz/is",
            headers={"Content-Type": "application/json"},
            json={
                # identity_context is required by the authorizer's request
                # validation even though the decision reads resource_context
                # (input.user.id is empty — no identity→user objects seeded).
                "identity_context": {"identity": caller_email or "anonymous",
                                     "type": "IDENTITY_TYPE_MANUAL"},
                "policy_context": {"path": "invincible_agent.ontology.can_view",
                                   "decisions": ["allowed"]},
                "resource_context": {
                    "iri": iri,
                    "user_id": caller_email,
                    "default_visibility": ONTOLOGY_DEFAULT_VISIBILITY,
                },
            },
            timeout=5.0,
        )
        resp.raise_for_status()
        decisions = resp.json().get("decisions") or []
        return bool(next((d.get("is") for d in decisions
                          if d.get("decision") == "allowed"), False))
    except Exception as e:  # noqa: BLE001 — fail-closed on any error
        logging.warning("ontology can_view check failed for iri=%s (fail-closed deny): %s", iri, e)
        return False


_JENA_ENDPOINT = os.getenv("JENA_SPARQL_ENDPOINT", "")
_JENA_USERNAME = os.getenv("JENA_USERNAME", "admin")
_JENA_PASSWORD = os.getenv("FUSEKI_PASSWORD", "Admin123!")
_LOCAL_GRAPH = None

# Weaviate Configuration
_WEAVIATE_CLIENT = None

# Neo4j Configuration
_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://iagent-neo4j:7687")
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
# baml_client). Try/except needed because the container Dockerfile flattens
# this directory into /app/ (so the sibling is at /app/registry_views.py
# without the `agent_fleet.ontology_service.` prefix), while dev runs
# import via the full package path.
try:
    from registry_views import (  # noqa: E402  — container path
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
except ImportError:
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
    # ADR-0025 ontology-IRI namespace (2026-07-08): the caller's ENTITLEMENT KEY
    # (email) — the subject of the per-IRI can_view gate that filters the
    # OntologyClass candidate pool BEFORE BAML classifies it (select-from-
    # authorized-set: the LLM can't pick a class it was never shown). Threaded
    # from the supervisor's JWT, same as the smolagents engines thread user_email.
    # Empty when absent → the gate (when ENABLE_AGENTIC_AUTH is on) treats the
    # caller as ungranted → deny-by-default on compartmented classes. Identity
    # MUST reach this seam before the gate can discriminate on the subject.
    user_email: str = ""
    # Legacy single-domain field — kept for backward compat with any
    # direct callers (curl tests, /classes endpoint, etc.). The
    # supervisor's `_resolve_subject` was the only production caller
    # that hit this with a SINGLE domain, and it was picking
    # `entitled_domains[0]` — the routing_domain lock bug confirmed
    # 2026-06-28. New callers should populate `domains` instead.
    domain: str = "MAINTENANCE"
    # NEW (2026-06-28): list of entitled domains to scope the
    # candidate pool. When provided (non-empty), supersedes `domain`.
    # The Weaviate hybrid search filters candidates by
    # `domain IN domains` so the LLM picks the best match ACROSS the
    # union — query-driven, not entitlement-order-driven. This fixes
    # the routing_domain lock at `dynamic_supervisor.py:895`.
    # Per `[[failure-mode-pluralism-in-fixes]]`: this lands as a
    # SEPARATE diagnosable change from the PROV-contamination cleanup.
    # The symptom should shift after this fix; the shift's direction
    # tells us which mechanism was load-bearing.
    domains: list[str] = []
    # Optional list of named-entity references the caller already
    # extracted (typically by /route_intent's BAML ExtractIntent step).
    # When class-recall (Weaviate hybrid + SPARQL fallback) returns no
    # candidates, /resolve fans these out to mesh:resolveInstance
    # providers BEFORE returning UNKNOWN — the original Recipe v2
    # intent: named entities preempt the class contest. Without this,
    # a query like "who owns customer 360" (no literal class token in
    # the query) sees Weaviate find 0 candidates and short-circuits to
    # UNKNOWN, even though engine_d's phone book would have returned
    # Customer 360 at score 1.0 if asked. The entity_refs gate is the
    # over-fire guard: instance fan-out fires ONLY when intent
    # extraction surfaced a named entity to resolve, never on raw query
    # text and never on every class-recall miss.
    #
    # ``list[str] = []`` (PEP 585) rather than ``List[str]`` because
    # this module uses ``from __future__ import annotations`` and
    # never imports ``List`` from typing — Pydantic v2's
    # forward-reference resolution at model build time would fail
    # with PydanticUserError otherwise. The builtin generic is
    # available natively on the project's Python 3.12 floor.
    entity_refs: list[str] = []


class SemanticResolutionResponse(BaseModel):
    """Mirrors the BAML SemanticResolution schema for the HTTP response.

    Carries optional instance-resolution provenance (Recipe v2) when the
    router's pre-step overrode the LLM's class guess with a phone-book
    answer. The provenance dict is what makes "LLM guessed Column,
    DataHub said Table, Table won" come for free in downstream traces;
    keys include instance_match (exact|fuzzy|mixed|empty), instance_id,
    instance_label, instance_provider, instance_score, and llm_guess.
    """
    resolved_uri: str
    confidence_score: float
    reasoning: str | None = None
    provenance: dict | None = None
    # 2026-07-02 (decision-path visualizer Part 0): the FULL subject-
    # class candidate pool the resolver considered, each with its
    # Weaviate match score — winner AND losers. Previously computed and
    # discarded; this is the capture-or-lose-forever data the
    # PROV-contamination class of bug needs (see the resolver stage of
    # the decision-path panel). Empty when resolution came from the
    # instance-preemption path (no class contest) or the UNKNOWN
    # fallback (no candidates at all). Shape: [{uri, label, score}].
    candidates: list[dict] = Field(default_factory=list)

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
    # ADR-0015 Phase 1: optional audit context. Callers that want trace
    # correlation pass request_id; cron canaries set audit_source to
    # distinguish synthetic traffic from real (default user_request).
    # All three are optional so existing callers don't have to migrate.
    request_id: str | None = Field(default=None, description="Trace correlation ID")
    user_id: str | None = Field(default=None, description="Caller user_id for slicing the audit log; null for canary")
    audit_source: str | None = Field(
        default=None,
        description="ADR-0015 audit source label: 'user_request' | 'canary' | 'registration_validation'. Defaults to user_request when unset.",
    )
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


def _weaviate_hybrid_search_sync(
    query: str,
    domain: str | None = None,
    domains: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Synchronous hybrid search implementation. gRPC blocks here.

    Always invoke via ``await asyncio.to_thread(...)`` from async paths so
    the event loop stays free and /health keeps responding.

    Hybrid (BM25 + vector) — we compute the query vector explicitly via
    embed_text() (agent_fleet/utils/embed.py → LiteLLM /embeddings) and
    pass it as `vector=` to Weaviate. Weaviate is dumb storage: NO
    text2vec module is involved on the cluster side. See the embed.py
    docstring for the rationale (code owns the contract, not infra).

    Domain scoping (2026-06-28): `domains` (list) supersedes `domain`
    (single string) when provided non-empty. The filter is OR across
    the listed domains — entitlement-list scoping where the candidate
    pool spans every domain the user IS entitled to, and the LLM picks
    the best across the union (query-driven). When `domains` is empty
    or None, falls back to `domain` for backward compat. When BOTH are
    empty, no filter is applied.

    If the OntologyClass collection has no vectors stored (e.g. the
    ingest pipeline hasn't been re-run since this change), Weaviate's
    hybrid path effectively becomes BM25-only — same observable behavior
    as the old fallback, but the code path is identical regardless of
    cluster state.
    """
    if not _WEAVIATE_CLIENT:
        return []
    if not _WEAVIATE_CLIENT.collections.exists("OntologyClass"):
        return []
    try:
        collection = _WEAVIATE_CLIENT.collections.get("OntologyClass")
        # Resolve which domains the filter spans. List supersedes
        # single-string per the routing_domain lock fix (2026-06-28).
        scope_domains: list[str] = []
        if domains:
            scope_domains = [d.upper() for d in domains if d]
        elif domain:
            scope_domains = [domain.upper()]

        if len(scope_domains) == 0:
            filters = None
        elif len(scope_domains) == 1:
            filters = wvc.query.Filter.by_property("domain").equal(scope_domains[0])
        else:
            filters = wvc.query.Filter.by_property("domain").contains_any(scope_domains)

        try:
            query_vector = embed_query(query)
        except Exception as e:
            # Embedding gateway is down or misconfigured — fall back to
            # BM25 so /resolve stays available. Surfaces as reduced
            # routing accuracy in observability, not a hard failure.
            print(f"embed_query failed, falling back to BM25 for OntologyClass: {e}")
            response = collection.query.bm25(
                query=query, limit=limit, filters=filters,
                # 2026-07-02 (decision-path visualizer Part 0): extract
                # the match score so the LOSING candidates carry their
                # scores out of /resolve. Previously discarded — which
                # is exactly the data the PROV-contamination diagnosis
                # needed (prov#Bundle at 0.66 beating idp#Pipeline) and
                # had to fish out of a manual Weaviate query because the
                # pipeline threw it away. Same MetadataQuery(score=True)
                # pattern the predicate search already uses.
                return_metadata=wvc.query.MetadataQuery(score=True),
            )
        else:
            response = collection.query.hybrid(
                query=query, vector=query_vector, limit=limit, filters=filters,
                return_metadata=wvc.query.MetadataQuery(score=True),
            )
        return [
            {
                "uri": obj.properties["uri"],
                "label": obj.properties["label"],
                "description": obj.properties.get("definition", ""),
                # score may be None if Weaviate didn't populate it (e.g.
                # a pure-BM25 path on a scoreless config); keep the key
                # present so downstream capture is uniform.
                "score": (
                    float(obj.metadata.score)
                    if obj.metadata is not None and obj.metadata.score is not None
                    else None
                ),
            }
            for obj in response.objects
        ]
    except Exception as e:
        print(f"Weaviate OntologyClass search failed: {e}")
        return []


async def weaviate_hybrid_search(
    query: str,
    domain: str | None = None,
    domains: list[str] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Async wrapper that runs the blocking hybrid search on a worker thread.

    `domains` (list) supersedes `domain` (single string) when provided
    non-empty — query-driven cross-domain pool scoping per the
    routing_domain lock fix (2026-06-28). Backward-compatible with
    callers passing only `domain`.
    """
    return await asyncio.to_thread(
        _weaviate_hybrid_search_sync, query, domain, domains, limit
    )


# ---------------------------------------------------------------------------
# Predicate hybrid search (ADR-0009 Step F'.6)
# ---------------------------------------------------------------------------
#: Name of the Weaviate collection where doc-tools mirrors registered
#: predicates. Created by doc-tools' AITool sync on first registration.
_PREDICATE_COLLECTION = "Predicate"

#: ADR-0008 follow-up — anti-synonym penalty. Each candidate's BM25 score
#: from Weaviate gets reduced by ``ANTI_SYN_PENALTY_ALPHA * overlap`` where
#: ``overlap`` is the Jaccard similarity between the query's lowercased
#: token n-grams and the candidate's verb_anti_synonyms. Tunable via env
#: var so operators can dial penalty strength without a redeploy.
#:
#: The penalty is computed in Python (not Weaviate) because the
#: Predicate collection's vectorizer-less BM25 setup can't easily express
#: a "score against this field, subtract from primary score" query in
#: one round trip. A Python-side overlap check after the candidate list
#: lands is simpler and observable.
_ANTI_SYN_PENALTY_ALPHA = float(os.getenv("PREDICATE_ANTI_SYNONYM_ALPHA", "0.50"))


def _anti_synonym_overlap(query: str, anti_synonyms: list[str]) -> float:
    """Return a 0..1 lexical-overlap score between ``query`` and the union
    of ``anti_synonyms``.

    Lowercases both sides, tokenizes on whitespace, computes Jaccard
    similarity between the query's token set and the union of all
    anti-synonym phrase token sets. Cheap, deterministic, and works
    without a vectorizer.

    Returns 0.0 if anti_synonyms is empty or there is no overlap — the
    common case until doc-tools propagation lands.
    """
    if not anti_synonyms:
        return 0.0
    q_tokens = set(query.lower().split())
    if not q_tokens:
        return 0.0
    anti_tokens: set[str] = set()
    for phrase in anti_synonyms:
        if isinstance(phrase, str):
            anti_tokens.update(phrase.lower().split())
    if not anti_tokens:
        return 0.0
    inter = q_tokens & anti_tokens
    union = q_tokens | anti_tokens
    return len(inter) / len(union) if union else 0.0


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
                # Weaviate v4 rejects `.equal([])` ("Filtering on empty lists
                # is not supported") — use length filter instead.
                wvc.query.Filter.by_property("domains", length=True).equal(0),
            ])

        # Hybrid: compute the query vector via embed_text() (LiteLLM
        # /embeddings) and hand it to Weaviate explicitly. No text2vec
        # module on the cluster — code owns the contract. If the embedding
        # gateway fails OR the Predicate collection has no vectors stored
        # yet (current state — only re-ingest will backfill them), Weaviate
        # hybrid() degrades gracefully: BM25 still scores normally; the
        # vector contribution is just zero / no-op.
        try:
            query_vector = embed_query(query)
        except Exception as e:
            print(f"embed_query failed, falling back to BM25 for Predicate: {e}")
            response = collection.query.bm25(
                query=query,
                limit=limit,
                filters=filters,
                return_metadata=wvc.query.MetadataQuery(score=True),
            )
        else:
            response = collection.query.hybrid(
                query=query,
                vector=query_vector,
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
            # Read verb_anti_synonyms if doc-tools has propagated them to
            # the Predicate collection. Missing/empty → penalty is 0; this
            # path is the graceful-degradation phase before doc-tools
            # ships its propagation update. See ADR-0008 follow-up.
            raw_anti = p.get("verb_anti_synonyms") or []
            if isinstance(raw_anti, str):
                # doc-tools may serialize as JSON string for parity with
                # mesh_verb_anti_synonyms; tolerate either shape.
                try:
                    parsed = json.loads(raw_anti)
                    raw_anti = parsed if isinstance(parsed, list) else []
                except (ValueError, TypeError):
                    raw_anti = []
            anti_overlap = _anti_synonym_overlap(query, list(raw_anti))
            adjusted_score = score
            if score is not None and anti_overlap > 0.0:
                # Penalize by alpha * overlap. Floor at 0.0 — a candidate
                # never gets a negative score even if its anti-synonyms
                # tokenize-overlap the query completely.
                adjusted_score = max(0.0, score - _ANTI_SYN_PENALTY_ALPHA * anti_overlap)
            # verb_synonyms may be stored as a JSON-string (older sync) or
            # a list (newer sync). Tolerate either.
            raw_syn = p.get("verb_synonyms") or []
            if isinstance(raw_syn, str):
                try:
                    parsed = json.loads(raw_syn)
                    raw_syn = parsed if isinstance(parsed, list) else []
                except (ValueError, TypeError):
                    raw_syn = []
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
                "score": adjusted_score,
                # Diagnostic fields — let the supervisor / structured log
                # see exactly how much the anti-synonym pass shifted things.
                "raw_score": score,
                "anti_synonym_overlap": anti_overlap,
                # ADR-0008 yellow-zone verifier needs these so the BAML LLM
                # has the verb's documentation in hand when judging the
                # match. Empty strings fall through cleanly when doc-tools
                # hasn't propagated the field.
                "description": p.get("description") or "",
                "verb_synonyms": list(raw_syn),
            })
        # Re-rank by adjusted score so the supervisor's top-1 reflects the
        # penalty. Without this the order would still be Weaviate's BM25
        # ranking and a penalty on the top-1 wouldn't change selection.
        out.sort(key=lambda r: (r["score"] if r["score"] is not None else -1.0), reverse=True)
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
# Instance-resolution pre-step (Recipe v2) — registry-discovered providers.
# ---------------------------------------------------------------------------
# When ClassifyDomainIntent extracts a `instance_identifier`, /resolve fans
# the token out to every engine that has registered as a mesh:resolveInstance
# provider and applies the pure decision table from instance_resolution.py.
# NO backend names live in this code path; providers are discovered from
# Neo4j like any other capability in the system. Adding a new instance
# registry (Engine E, the docs pipeline, etc.) is a REGISTRATION, not a
# router code change — that's the generality acceptance test.

# Dual import for dev (full repo path) vs container (main.py and
# instance_resolution.py colocated at /app/). The standing guard
# ``test_engine_o_imports_decision_table_from_pure_module`` still
# matches against the dev path.
try:
    from agent_fleet.ontology_service.instance_resolution import (  # noqa: E402
        InstanceCandidate as _IRCandidate,
        decide as _ir_decide,
        decide_instance_abstention as _ir_abstention,
        instance_not_found_message as _ir_not_found_msg,
        DEFAULT_EXACT_THRESHOLD as _IR_DEFAULT_EXACT,
        DEFAULT_MIN_SCORE as _IR_DEFAULT_MIN,
    )
except ImportError:
    from instance_resolution import (  # noqa: E402
        InstanceCandidate as _IRCandidate,
        decide as _ir_decide,
        decide_instance_abstention as _ir_abstention,
        instance_not_found_message as _ir_not_found_msg,
        DEFAULT_EXACT_THRESHOLD as _IR_DEFAULT_EXACT,
        DEFAULT_MIN_SCORE as _IR_DEFAULT_MIN,
    )

# Canonical full-IRI form for the InstanceIdentifier subject. Session 2's
# A3 sweep migrated every resolveInstance edge from the compact form
# (`mesh:InstanceIdentifier`) to the canonical full IRI; this query
# missed that migration and survived only because the in-memory
# _INSTANCE_RESOLVERS_CACHE held provider entries discovered pre-A3.
# B3 (third resolveInstance provider) restarted Engine O and exposed
# the stale URI — third Phase-5-prophecy occurrence (the masks rule
# one more time: cache was the mask, restart closed it, latent
# A3-miss surfaced where it actually lived).
# Provider-agnostic by construction — walks ALL edges from this node,
# names no specific provider. The B3 guard pin
# (test_b3_engine_o_provider_agnostic) asserts this property.
_INSTANCE_RESOLVERS_CYPHER = """
MATCH (i:OntologyClass {uri: 'http://invincible-agent/mesh#InstanceIdentifier'})-[r]->(o:OntologyClass)
WHERE r.iri = 'mesh:resolveInstance' AND r.endpoint_url IS NOT NULL
RETURN DISTINCT
  r.endpoint_url   AS endpoint_url,
  coalesce(r.provider, type(r)) AS provider,
  r.timeout_s      AS timeout_s,
  r.domains        AS domains
"""

_INSTANCE_RESOLVERS_CACHE: list[dict] | None = None
# Monotonic timestamp of last cache fill. Paired with _INSTANCE_RESOLVERS_TTL_S
# to give the cache a bounded staleness window — see _discover_instance_resolvers.
# Set to 0.0 means "never filled yet" (the cache is None in that case anyway).
_INSTANCE_RESOLVERS_CACHE_TS: float = 0.0
# Cache TTL: how long the resolver list can be stale before the next
# /resolve call triggers a re-read of Neo4j. Default 30s — fast enough
# that a newly-registered provider becomes visible within half a minute
# (which is well under the typical "user reports the wrong route was
# taken" feedback loop), and slow enough that the steady-state /resolve
# overhead is one Neo4j read per minute, not per call.
#
# This closes the latent-staleness window the never-refresh cache had:
# the docstring banked an /admin/refresh endpoint as "not built here",
# which meant any new provider registration (e.g. engine_d on a fresh
# bootstrap when engine-o started before engine_d's MESH_REGISTER_ON_STARTUP
# completed) was silently invisible to /resolve forever. The failure
# mode was the Recipe v2 preemption fan-out returning empty for catalog
# assets, /resolve falling through to the LLM class guess, and the
# router routing to fallback when it should have routed to engine_d.
# Caught 2026-06-23 by the first end-to-end UI smoke test of Phase 1+3;
# the matrix didn't catch it because matrix conditions made the LLM
# pick the right class directly.
_INSTANCE_RESOLVERS_TTL_S = float(os.getenv("INSTANCE_RESOLVERS_TTL_S", "30"))
# Router-level FLOOR for the fan-out budget — used when a provider
# hasn't declared its own ``timeout_s`` at registration time. The recipe's
# "~2s" was sized for an in-memory phone book; real catalog providers
# (Engine D → DataHub GraphQL) routinely take 3-5s. A timeout below the
# provider's p95 silently kills lookups and the abstention contract
# masks the kill as a miss — so the default has to clear the slowest
# UNDECLARED provider. Once every provider declares its own budget,
# this floor stops being load-bearing.
_INSTANCE_RESOLVER_FANOUT_TIMEOUT_S = float(
    os.getenv("INSTANCE_RESOLVER_TIMEOUT_S", "8.0")
)
_INSTANCE_RESOLVE_EXACT = float(
    os.getenv("INSTANCE_RESOLVE_EXACT_THRESHOLD", str(_IR_DEFAULT_EXACT))
)
_INSTANCE_RESOLVE_MIN_SCORE = float(
    os.getenv("INSTANCE_RESOLVE_MIN_SCORE", str(_IR_DEFAULT_MIN))
)

# Per-provider call outcome. Carrying this through the fan-out is what
# lets the router distinguish "provider declined" (empty) from
# "provider exceeded its budget" (timeout) at the provenance layer —
# the fold that hid Engine D's 2s strangle bug last night.
class _ResolverOutcome:
    __slots__ = ("status", "candidates", "provider", "endpoint_url", "elapsed_s")
    def __init__(self, *, status: str, candidates: list, provider: str,
                 endpoint_url: str, elapsed_s: float) -> None:
        self.status = status              # "ok" | "timeout" | "error"
        self.candidates = candidates
        self.provider = provider
        self.endpoint_url = endpoint_url
        self.elapsed_s = elapsed_s


def _discover_instance_resolvers(refresh: bool = False) -> list[dict]:
    """Read the registry for engines registered as mesh:resolveInstance.

    Returns a list of ``{endpoint_url, provider, timeout_s, domains}``
    dicts. ``timeout_s`` is the provider's declared SLO from registration
    when present, else None (falls back to the router floor in
    ``_call_resolver``).

    Cache discipline: ``_INSTANCE_RESOLVERS_CACHE`` is reused for up to
    ``_INSTANCE_RESOLVERS_TTL_S`` seconds since the last fill, then
    re-read from Neo4j. The TTL closes the never-refresh window that
    silently dropped engine_d when engine-o booted before engine_d's
    mesh-registrar registration completed; see the cache constants
    above for the full failure-mode write-up. ``refresh=True`` forces
    a re-read regardless of TTL (kept for explicit-refresh code paths;
    no /admin/refresh endpoint built yet).
    """
    global _INSTANCE_RESOLVERS_CACHE, _INSTANCE_RESOLVERS_CACHE_TS
    now = time.monotonic()
    if (
        _INSTANCE_RESOLVERS_CACHE is not None
        and not refresh
        and (now - _INSTANCE_RESOLVERS_CACHE_TS) < _INSTANCE_RESOLVERS_TTL_S
    ):
        return _INSTANCE_RESOLVERS_CACHE
    if not _NEO4J_DRIVER:
        return []
    with _NEO4J_DRIVER.session() as session:
        rows = session.run(_INSTANCE_RESOLVERS_CYPHER).data()
    discovered = []
    for r in rows:
        if not r.get("endpoint_url"):
            continue
        # timeout_s comes through as either a Cypher number, a stringified
        # float (the sensor pipes everything through as strings), or None.
        raw_timeout = r.get("timeout_s")
        try:
            timeout_s = float(raw_timeout) if raw_timeout not in (None, "") else None
        except (TypeError, ValueError):
            timeout_s = None
        discovered.append({
            "endpoint_url": r["endpoint_url"],
            "provider": r.get("provider") or "unknown",
            "timeout_s": timeout_s,
            "domains": r.get("domains") or [],
        })
    _INSTANCE_RESOLVERS_CACHE = discovered
    _INSTANCE_RESOLVERS_CACHE_TS = now
    print(
        f"Discovered {len(_INSTANCE_RESOLVERS_CACHE)} mesh:resolveInstance "
        f"providers (TTL={_INSTANCE_RESOLVERS_TTL_S}s): "
        f"{[(r['provider'], r['endpoint_url'], r['timeout_s']) for r in _INSTANCE_RESOLVERS_CACHE]}"
    )
    return _INSTANCE_RESOLVERS_CACHE


async def _call_resolver(
    resolver: dict, identifier: str, query: str
) -> _ResolverOutcome:
    """Call one mesh:resolveInstance provider with the provider's own
    declared timeout budget (falling back to the router floor).

    Returns a ``_ResolverOutcome`` whose ``status`` distinguishes
    ``ok`` from ``timeout`` from ``error`` — the fold that hid the
    2s-strangle bug. Candidates are always returned (possibly empty);
    the caller decides whether the empty list represents abstention
    or a kill upstream.
    """
    import time
    provider = resolver.get("provider") or ""
    endpoint_url = resolver.get("endpoint_url", "")
    # Provider-declared budget wins. Router floor only applies when the
    # provider hasn't told us its SLO.
    budget_s = resolver.get("timeout_s") or _INSTANCE_RESOLVER_FANOUT_TIMEOUT_S
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=budget_s) as client:
            resp = await client.post(
                endpoint_url,
                json={"identifier": identifier, "query": query},
            )
            resp.raise_for_status()
            data = resp.json() or {}
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        elapsed = time.monotonic() - started
        print(
            f"mesh:resolveInstance provider {provider!r} ({endpoint_url}) "
            f"EXCEEDED its budget of {budget_s}s on identifier="
            f"{identifier!r}: {type(exc).__name__} after {elapsed:.2f}s"
        )
        return _ResolverOutcome(
            status="timeout", candidates=[], provider=provider,
            endpoint_url=endpoint_url, elapsed_s=elapsed,
        )
    except Exception as exc:  # noqa: BLE001 — non-timeout failures stay distinct from kept-empty
        elapsed = time.monotonic() - started
        print(
            f"mesh:resolveInstance provider {provider!r} ({endpoint_url}) "
            f"ERRORED on identifier={identifier!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        return _ResolverOutcome(
            status="error", candidates=[], provider=provider,
            endpoint_url=endpoint_url, elapsed_s=elapsed,
        )
    elapsed = time.monotonic() - started
    out: list[_IRCandidate] = []
    for c in data.get("candidates") or []:
        try:
            out.append(
                _IRCandidate(
                    instance_id=str(c.get("instance_id") or ""),
                    class_uri=str(c.get("class_uri") or ""),
                    label=str(c.get("label") or ""),
                    score=float(c.get("score") or 0.0),
                    provider=provider,
                )
            )
        except Exception:  # noqa: BLE001 — skip malformed candidate
            continue
    return _ResolverOutcome(
        status="ok", candidates=out, provider=provider,
        endpoint_url=endpoint_url, elapsed_s=elapsed,
    )


async def _resolve_instance(
    identifier: str, query: str
) -> tuple[str | None, dict]:
    """Run the instance-resolution pre-step.

    Returns ``(subject_uri or None, provenance)``. ``None`` means
    abstain → the caller keeps the LLM's class guess. Provenance
    distinguishes ``empty`` (every provider returned ok with zero
    candidates — registry genuinely doesn't know) from ``timeout``
    (one or more providers ran out of budget — the failure mode that
    used to hide as ``empty`` until the 2s strangle bug was caught).
    """
    resolvers = _discover_instance_resolvers()
    if not resolvers:
        return None, {
            "instance_resolved": False,
            "instance_match": "no_providers",
            "instance_n": 0,
        }
    tasks = [_call_resolver(r, identifier, query) for r in resolvers]
    outcomes: list[_ResolverOutcome] = await asyncio.gather(
        *tasks, return_exceptions=False
    )

    candidates: list[_IRCandidate] = []
    for o in outcomes:
        candidates.extend(o.candidates)

    decision = _ir_decide(
        candidates,
        exact_threshold=_INSTANCE_RESOLVE_EXACT,
        min_score=_INSTANCE_RESOLVE_MIN_SCORE,
    )
    provenance = dict(decision.provenance)

    # Per-provider audit so the trace shows which phone book said what.
    provenance["instance_provider_outcomes"] = [
        {
            "provider": o.provider,
            "status": o.status,
            "n_candidates": len(o.candidates),
            "elapsed_s": round(o.elapsed_s, 3),
        }
        for o in outcomes
    ]

    # If the decision was abstain-via-empty AND any provider actually
    # timed out, promote the provenance marker to ``timeout`` so the
    # router operator can tell "we don't know" from "we didn't ask in
    # time." The architect's note on the 2s-strangle bug: a folded
    # timeout/empty log is exactly the ambiguity you don't want with
    # Engine E's millisecond budget sitting next to DataHub's seconds.
    if decision.subject_uri is None and provenance.get("instance_match") == "empty":
        any_timeout = any(o.status == "timeout" for o in outcomes)
        any_error = any(o.status == "error" for o in outcomes)
        if any_timeout:
            provenance["instance_match"] = "timeout"
        elif any_error:
            provenance["instance_match"] = "error"

    return decision.subject_uri, provenance


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
    # Step 1: Hybrid Search for candidates in Weaviate. The `domains`
    # field (when non-empty) supersedes `domain` — the supervisor's
    # entitled_domains list spans the candidate pool query-driven,
    # rather than locking to entitled_domains[0]. See ResolveRequest
    # docstring + [[failure-mode-pluralism-in-fixes]] for the
    # diagnose-each-mechanism rationale.
    candidates = await weaviate_hybrid_search(
        query=request.query,
        domain=request.domain,
        domains=request.domains,
        limit=10,
    )
    
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

    # ── Step 1.55: ONTOLOGY-IRI VISIBILITY GATE (ADR-0025, select-from-
    # authorized-set). Filter the candidate pool to the classes the caller may
    # SEE, BEFORE BAML classifies — so the LLM cannot pick (and /resolve cannot
    # return) a class the caller isn't granted. Single-decider: Topaz's
    # ontology_can_view rego decides (compartment grant OR unassigned+releasable);
    # deny-by-default; fail-CLOSED. No-op when ENABLE_AGENTIC_AUTH is off. Covers
    # BOTH recall paths (Weaviate + SPARQL fallback). This is the ontology-namespace
    # sibling of Engine W's before-synthesis chunk filter.
    if ENABLE_AGENTIC_AUTH and candidates:
        _visible = [c for c in candidates if _can_view_class(request.user_email, c.get("uri", ""))]
        _dropped = len(candidates) - len(_visible)
        if _dropped:
            print(f"[Engine O] ontology-visibility gate DROPPED {_dropped} ungated "
                  f"class(es) BEFORE classification (caller={request.user_email!r})")
        candidates = _visible

    # Step 1.6: Class-recall failed (both Weaviate hybrid and SPARQL
    # fallback returned zero candidates). Before declaring UNKNOWN,
    # try the phone book — when the caller supplied entity_refs from
    # /route_intent, fan them out to registered mesh:resolveInstance
    # providers. This is the precedence-fix from the 2026-06-25
    # "who owns customer 360" surface: the original Recipe v2 intent
    # was "named entities preempt the class contest," but the code
    # had it wired as a sub-step that ran only AFTER class recall
    # succeeded — meaning when class recall failed (exactly when the
    # phone book is most needed), it never fired.
    #
    # Tight over-fire guard: this branch fires ONLY when entity_refs
    # is non-empty AND class recall was zero. A genuinely
    # unrecognizable query (no entity_refs, no class) STILL goes to
    # UNKNOWN below — Engine A generalist, the safe fallback. The
    # instance fan-out is the safety net for "Weaviate missed the
    # class but intent extraction found a real named entity," not a
    # blanket "try the phone book on any query."
    #
    # Per [[feedback-integration-probe-per-contract]]:
    # tests/routing/test_resolve_instance_preemption_probe.py asserts
    # BOTH directions — named-instance query with entity_refs
    # resolves via preemption; genuinely-unknown query with no
    # entity_refs (or with entity_refs that all return 0) still
    # abstains to UNKNOWN. The probe is the property guard against
    # this branch over-firing or being silently removed.
    if not candidates and request.entity_refs:
        for entity_ref in request.entity_refs:
            instance_subject, instance_provenance = await _resolve_instance(
                identifier=entity_ref, query=request.query
            )
            instance_provenance["instance_identifier"] = entity_ref
            instance_provenance["llm_guess"] = None
            instance_provenance["preemption_path"] = "class_recall_empty_fallback"
            if instance_subject is not None:
                return SemanticResolutionResponse(
                    resolved_uri=instance_subject,
                    confidence_score=0.9,
                    reasoning=(
                        f"Routed via mesh:resolveInstance preemption "
                        f"(no class-recall candidates for query in domain "
                        f"{request.domain!r}; entity_ref={entity_ref!r} "
                        f"resolved by "
                        f"{instance_provenance.get('instance_provider')}, "
                        f"match={instance_provenance.get('instance_match')})."
                    ),
                    provenance=instance_provenance,
                )
        # All entity_refs returned no candidates — fall through.

    # Step 1.7: Ultimate Fallback (Prevents Restate infinite loops)
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

    # Step 4: Instance-resolution pre-step (Recipe v2).
    # If the LLM extracted a named-individual identifier, fan it out to
    # registered mesh:resolveInstance providers. A unanimous-class
    # answer OVERRIDES the LLM's guess; mixed/empty → LLM guess stands.
    identifier = getattr(result, "instance_identifier", None)
    if identifier:
        instance_subject, instance_provenance = await _resolve_instance(
            identifier=identifier,
            query=request.query,
        )
        instance_provenance["instance_identifier"] = identifier
        instance_provenance["llm_guess"] = str(result.resolved_uri)
        if instance_subject is not None:
            return SemanticResolutionResponse(
                resolved_uri=instance_subject,
                confidence_score=max(result.confidence_score, 0.9),
                reasoning=(
                    f"Routed via mesh:resolveInstance "
                    f"(match={instance_provenance.get('instance_match')}, "
                    f"provider={instance_provenance.get('instance_provider')}). "
                    f"LLM guess: {result.resolved_uri}."
                ),
                provenance=instance_provenance,
                # The class contest DID run before instance preemption
                # overrode it — carry the pool so the decision path can
                # show "LLM guessed X from these candidates; instance
                # resolution then overrode to Y".
                candidates=candidates,
            )

        # STRUCTURAL ABSTENTION GATE (ADR-0026 abstention-gate arc).
        # The instance didn't resolve. Before this gate, we fell straight
        # through to the LLM's class guess (`result.resolved_uri`) — so
        # whether a query naming a NON-EXISTENT specific individual
        # (foo.bar.zzz_nope) abstained or got a confident-wrong class
        # answer rode on the LLM's sampling. The gate replaces that
        # LLM-mediated abstention with a deterministic decision over two
        # recorded facts: the identifier's FORM and the resolution
        # ``instance_match``. When it fires, we emit UNKNOWN (the router's
        # honest short-circuit) with an ACTIONABLE message — NOT another
        # LLM re-judgment. See [[project_abstention_gate_llm_mediated]].
        if _ir_abstention(
            identifier=identifier,
            instance_subject=instance_subject,   # None on this branch
            instance_match=str(instance_provenance.get("instance_match") or ""),
        ) == "instance_not_found":
            instance_provenance["abstention_reason"] = "instance_not_found"
            return SemanticResolutionResponse(
                resolved_uri="UNKNOWN",
                confidence_score=0.0,
                reasoning=_ir_not_found_msg(identifier),
                provenance=instance_provenance,
                candidates=candidates,
            )

        # Gate did NOT fire: either a generic term the extractor
        # over-eagerly flagged (not instance-shaped → the class contest is
        # the right answer) or an infra non-answer (timeout/error/
        # no_providers — we didn't get a trustworthy "no", so we must not
        # tell the user "no provider knows it"). Keep the LLM's class guess.
        return SemanticResolutionResponse(
            resolved_uri=str(result.resolved_uri),
            confidence_score=result.confidence_score,
            reasoning=result.reasoning,
            provenance=instance_provenance,
            candidates=candidates,
        )

    # Step 5: Return structured response (no identifier extracted).
    # This is the common class-contest path — the LLM picked
    # result.resolved_uri from `candidates`. Carry the full pool with
    # scores so the decision-path resolver stage can show the winner
    # AND the losers (the PROV-contamination diagnosis lived exactly
    # here: the winner was prov#Bundle at 0.66, and the losers-with-
    # scores are what made "contaminated pool" a glance).
    return SemanticResolutionResponse(
        resolved_uri=str(result.resolved_uri),
        confidence_score=result.confidence_score,
        reasoning=result.reasoning,
        candidates=candidates,
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
    # ADR-0015 Phase 1: capture timings + decision context for the
    # routing-decision audit log emit at the end of the handler.
    _total_t0 = time.perf_counter()
    _request_id = request.request_id or str(uuid.uuid4())
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

    _search_t0 = time.perf_counter()
    hits = await predicate_hybrid_search(
        query=request.query,
        entitled_domains=entitled,
        limit=request.limit,
    )
    _search_ms = int((time.perf_counter() - _search_t0) * 1000)

    if not hits:
        _emit_routing_decision(
            source=(request.audit_source or "user_request"),
            request_id=_request_id,
            user_id=request.user_id,
            sub_query=request.query,
            entitled_domains=entitled,
            candidates_raw=[],
            picked_engine=None,
            picked_verb=None,
            pick_score=None,
            pick_margin=None,
            fallback_reason="no_predicate_matched",
            search_ms=_search_ms,
            total_ms=int((time.perf_counter() - _total_t0) * 1000),
        )
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

    # ADR-0015 Phase 1: emit the routing decision row. pick_margin is
    # top-1 minus top-2 absolute score; useful for the confidence-gating
    # follow-up but already valuable as drift telemetry.
    _top = hits[0]
    _second_score = hits[1]["score"] if len(hits) > 1 and hits[1].get("score") is not None else None
    _pick_score = _top.get("score")
    _pick_margin = (
        _pick_score - _second_score
        if _pick_score is not None and _second_score is not None
        else None
    )
    _emit_routing_decision(
        source=(request.audit_source or "user_request"),
        request_id=_request_id,
        user_id=request.user_id,
        sub_query=request.query,
        entitled_domains=entitled,
        candidates_raw=[
            {
                "verb_iri": h["verb_iri"],
                "endpoint": h["endpoint"],
                "score": h.get("score"),
                "domains": h.get("domains"),
                "cost_class": h.get("cost_class"),
            }
            for h in hits
        ],
        picked_engine=_top.get("endpoint"),
        picked_verb=_top.get("verb_iri"),
        pick_score=_pick_score,
        pick_margin=_pick_margin,
        fallback_reason=None,
        search_ms=_search_ms,
        total_ms=int((time.perf_counter() - _total_t0) * 1000),
    )

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
        result = {**plan.model_dump(), "domain": request.domain}

        # ── Silent-degrade detection ────────────────────────────────────
        # Reject BAML responses that have NO content at all — empty
        # tasks AND empty extracted_concepts AND empty reasoning. That
        # combination doesn't occur on a working LLM: even a legitimate
        # gpt-oss reasoning-only response populates reasoning and
        # extracted_concepts when tasks=[]. All-three-empty indicates
        # the LLM was unreachable / misconfigured (LiteLLM returned 200
        # with malformed body, or the configured model produced
        # degenerate output) and BAML coerced the result into a
        # zero-valued model rather than raising.
        #
        # Without this check, the passthrough-synthesis below masks the
        # outage: empty tasks → synthesized passthrough → supervisor
        # fans out a vacuous task → Engine A fallback produces an
        # apologetic empty answer → final_payload arrives → UI marks
        # every stage green. The user sees "success" when nothing
        # actually happened. This is the silent-degrade composition
        # class (2026-06-25); the standing rule
        # [[feedback-verification-must-fail]] mandates positive-signal
        # detection of degradation, not success-by-default.
        if (
            not result.get("tasks")
            and not result.get("extracted_concepts")
            and not (result.get("reasoning") or "").strip()
        ):
            raise HTTPException(
                status_code=502,
                detail=(
                    "BAML DecomposeQuery returned an empty model "
                    "(tasks=[], extracted_concepts=[], reasoning=''). "
                    "The LLM appears unreachable or misconfigured — "
                    "the configured backend produced no usable output."
                ),
            )

        # ── Legitimate degraded passthrough ─────────────────────────────
        # gpt-oss via Ollama (and similar reasoning-heavy small models)
        # sometimes populates reasoning + extracted_concepts but leaves
        # tasks=[]. Synthesizing a single passthrough task keeps the
        # supervisor's dynamic_tasks.map() from spawning nothing. The
        # `degraded` flag lets downstream callers (supervisor, gateway)
        # know this is the degraded path rather than a normal plan —
        # callers can surface a "partial confidence" signal in the
        # final UI rather than rendering an empty answer as full
        # success. The flag is the architectural-follow-up hook for
        # the gateway's banked `pipeline_warn` (see
        # [[silent-degrade-composition]]); for now it rides through
        # the response unused, but the contract is in place.
        if not result.get("tasks"):
            result["tasks"] = [{
                "sub_query": request.query,
                "target_persona": "DATA_STEWARD",
                "tools_needed": [],
                "expected_output": "Direct response to the user's query.",
            }]
            result["degraded"] = "synthesized_passthrough_zero_tasks"
        return result
    except HTTPException:
        # Pass through our deliberate 502 (silent-degrade detection)
        # without rewrapping it.
        raise
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

    # Silent-degrade detection (paired with /plan above). All-empty
    # ExtractIntent result indicates the LLM produced no usable output
    # — see /plan's detection block for the full rationale. Without
    # this, the gateway treats the empty intent as ONE_SHOT and
    # proceeds to launch a Dagster job that ultimately produces a
    # green-with-empty-answer false-positive (silent-degrade
    # composition class, [[silent-degrade-composition]]).
    extracted_refs = list(intent.entity_refs or [])
    extracted_reasoning = (intent.reasoning or "").strip()
    extracted_mode = intent.mode.value if hasattr(intent.mode, "value") else str(intent.mode)
    if (
        not extracted_refs
        and not extracted_reasoning
        and not extracted_mode
    ):
        raise HTTPException(
            status_code=502,
            detail=(
                "BAML ExtractIntent returned an empty model "
                "(mode='', entity_refs=[], reasoning=''). "
                "The LLM appears unreachable or misconfigured."
            ),
        )

    return RouteIntentResponse(
        mode=extracted_mode,
        entity_refs=extracted_refs,
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


# ---------------------------------------------------------------------------
# POST /find_compatible_verbs — Neo4j IS the (S,P) compatibility reasoner
# ---------------------------------------------------------------------------
#
# ADR-0018 addendum (proper SPO). Given a resolved subject_uri, return the
# verbs that Neo4j marks as edges originating at that subject — directly
# OR via subClassOf traversal up to N hops. This is the constraint that
# makes (S, P) pair routing correct by construction: the LLM never sees
# verbs whose graph edges don't include the subject's class, so it
# cannot pick an incompatible pair.
#
# This is the Cypher leg ADR-0004 originally proposed for routing. The
# /classify_predicate step that ADR-0018 added on top of it is the LLM
# precision step that picks among the compatible set when there are
# multiple choices.

class FindCompatibleVerbsRequest(BaseModel):
    subject_uri: str
    # How many subClassOf hops to walk. 0 = direct edges only;
    # 5 is a sensible default for most ontologies. Set higher when the
    # class hierarchy is deep.
    max_hops: int = 5
    # When set, only return verbs whose domains overlap with these
    # (or are domain-agnostic). Mirrors the entitled_domains filter on
    # /search_predicates.
    entitled_domains: list[str] = Field(default_factory=list)


class CompatibleVerb(BaseModel):
    verb_iri: str
    verb_local: str
    input_uri: str
    output_uri: str
    endpoint_url: str | None = None
    owner_persona: str | None = None
    domains: list[str] = Field(default_factory=list)
    cost_class: str | None = None
    requires_human_approval: bool = False
    hops: int = 0
    # ARITY (query-shape eligibility, ADR-0008 follow-up). A DECLARED fact
    # about the verb's input cardinality: "set" (operates on the collection
    # — enumerateCatalog), "single" (operates on one asset — describeAsset),
    # or "any"/null (neutral). Asserted at registration, NEVER inferred from
    # definition prose. The supervisor gates verb eligibility on
    # (query-arity from instance_resolved) so a set-query never resolves to
    # a single-asset verb. null → treated as "any" (never excluded).
    arity: str | None = None


class FindCompatibleVerbsResponse(BaseModel):
    subject_uri: str
    verbs: list[CompatibleVerb] = Field(default_factory=list)
    # Diagnostic: how Neo4j answered. Helps when the answer is empty.
    cypher_executed: str | None = None


# NB on the shape of this query: the `*0..N` form is the trick that
# unifies "the subject's own class" with "any registered ancestor"
# under a single MATCH — at hop=0, `scope` rebinds to `start`. We
# initially tried an OPTIONAL MATCH variant that mixed
# `collect(DISTINCT ancestor) + [start]` in a single WITH clause; Neo4j
# rejects it on implicit-grouping grounds. The form below is the one
# that passes cypher-shell validation against the live graph.
_FIND_COMPAT_VERBS_CYPHER = """
MATCH (start:OntologyClass {uri: $subject_uri})
MATCH (start)-[:subClassOf*0..$MAXHOPS$]->(scope:OntologyClass)
WITH start, collect(DISTINCT scope) AS scopes
UNWIND scopes AS scope
MATCH (scope)-[r]->(o:OntologyClass)
WHERE r.iri IS NOT NULL
RETURN DISTINCT
    r.iri                         AS verb_iri,
    type(r)                       AS verb_local,
    scope.uri                     AS input_uri,
    o.uri                         AS output_uri,
    r.endpoint_url                AS endpoint_url,
    r.owner_persona               AS owner_persona,
    coalesce(r.domains, [])       AS domains,
    r.cost_class                  AS cost_class,
    coalesce(r.requires_human_approval, false) AS requires_human_approval,
    r.arity                       AS arity,
    length(shortestPath((start)-[:subClassOf*0..$MAXHOPS$]->(scope))) AS hops
ORDER BY hops ASC, verb_iri ASC
"""


@app.post("/find_compatible_verbs", response_model=FindCompatibleVerbsResponse)
async def find_compatible_verbs(
    request: FindCompatibleVerbsRequest,
) -> FindCompatibleVerbsResponse:
    """Cypher-only: which predicates can operate on this subject?

    The Cypher walks ``(subject)-[:subClassOf*0..max_hops]->(ancestor)``
    then collects every ``(ancestor)-[r]->(_)`` where ``r.iri`` is set
    (i.e., the edge is a registered predicate). The result is the set
    of verbs whose registered ``input_uri`` covers the resolved subject
    via the class hierarchy. Returns an empty list when:

      - The subject_uri isn't in the OntologyClass graph (cold ontology
        load, typo, or a UNKNOWN subject from /resolve).
      - No verb has a registered edge that the subject's class chain
        reaches in max_hops hops.

    Empty list → the supervisor's caller routes to the generalist
    fallback. Non-empty list → caller passes the verb_iris into
    /classify_predicate as compatible_verb_iris.
    """
    if not _NEO4J_DRIVER:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized.")

    max_hops = max(0, min(10, int(request.max_hops or 5)))
    cypher = _FIND_COMPAT_VERBS_CYPHER.replace("$MAXHOPS$", str(max_hops))

    def _run() -> list[dict]:
        with _NEO4J_DRIVER.session() as session:
            return [
                dict(r)
                for r in session.run(
                    cypher,
                    subject_uri=request.subject_uri,
                )
            ]

    try:
        rows = await asyncio.to_thread(_run)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Neo4j compatibility query failed: {exc}",
        ) from exc

    entitled = {d.upper() for d in (request.entitled_domains or [])}
    verbs: list[CompatibleVerb] = []
    for row in rows:
        verb_domains = [d.upper() for d in (row.get("domains") or [])]
        # Scope filter: same semantics as /search_predicates. Empty entitled
        # = pass through; empty verb domains = domain-agnostic (always
        # keep); intersection > 0 = compatible.
        if entitled and verb_domains:
            if not entitled.intersection(verb_domains):
                continue
        verbs.append(CompatibleVerb(
            verb_iri=str(row["verb_iri"]),
            verb_local=str(row["verb_local"]),
            input_uri=str(row["input_uri"]),
            output_uri=str(row["output_uri"]),
            endpoint_url=row.get("endpoint_url"),
            owner_persona=row.get("owner_persona"),
            domains=verb_domains,
            cost_class=row.get("cost_class"),
            requires_human_approval=bool(row.get("requires_human_approval", False)),
            arity=row.get("arity"),
            hops=int(row.get("hops") or 0),
        ))

    return FindCompatibleVerbsResponse(
        subject_uri=request.subject_uri,
        verbs=verbs,
        cypher_executed=cypher.strip(),
    )


# ---------------------------------------------------------------------------
# POST /classify_predicate  (symmetric of /resolve)
# ---------------------------------------------------------------------------
#
# /resolve does vector-recall + LLM-precision for OntologyClass subjects.
# /classify_predicate does the same for predicates (verbs). The pair restores
# the symmetry ADR-0004 originally proposed and ADR-0009 Step F'.6 simplified
# away. The supervisor now calls /resolve then /classify_predicate as the
# two-step routing decision; VerifyVerbChoice + the yellow-zone gate are
# obsolete because the LLM IS the classifier, not a second-guess gate.

class ClassifyPredicateRequest(BaseModel):
    """Incoming request to the /classify_predicate endpoint."""
    query: str
    # Resolved subject from a prior /resolve call. Pass "UNKNOWN" when the
    # subject classifier returned UNKNOWN; the LLM falls back to judging
    # the predicate against the raw query alone.
    subject_uri: str = "UNKNOWN"
    subject_reasoning: str = ""
    # Domain scope from the JWT entitled_domains claim. The Weaviate
    # candidate set is filtered to predicates this caller is entitled to.
    entitled_domains: list[str] = Field(default_factory=list)
    # Primary domain used as the BAML domain field. Match what /resolve
    # was called with for consistency.
    domain: str = "MAINTENANCE"
    # How many Weaviate candidates to put in front of the LLM. Higher =
    # better recall, more tokens. 10 mirrors /resolve's default.
    candidate_limit: int = 10
    # ADR-0018 addendum (proper SPO): when populated, the LLM is
    # constrained to picking among ONLY these verb_iris — sourced from
    # the supervisor's prior call to /find_compatible_verbs (Cypher walk
    # of (subject)-[:subClassOf*]->()-[verb]->(o) over the predicate
    # graph). Bad (subject, verb) pairs become impossible because they
    # never enter the candidate enum. When empty list / None, the
    # endpoint falls back to the prior behavior of using Weaviate hybrid
    # as the recall step (subject is reasoning context only).
    compatible_verb_iris: list[str] = Field(default_factory=list)


class ClassifyPredicateResponse(BaseModel):
    """Response shape: the LLM's chosen verb + confidence + reasoning.

    The ``predicate`` field carries the full Weaviate record for the chosen
    verb (endpoint URL, owner_persona, domains, etc.) so the supervisor can
    dispatch without a second lookup. None when verb_iri == "UNKNOWN".
    """
    resolved_verb_iri: str
    confidence_score: float
    reasoning: str | None = None
    # The full predicate record the supervisor needs to dispatch the
    # subtask: endpoint URL, owner_persona, domains, cost_class, etc.
    # Sourced from the Weaviate candidate that matched the LLM's pick.
    predicate: dict | None = None
    # For audit: the candidate verbs the LLM was permitted to choose from.
    candidate_verb_iris: list[str] = Field(default_factory=list)
    # Per-candidate semantic scores (Weaviate hybrid query→verb match) —
    # the "how close was each runner-up predicate" signal the decision-path
    # map draws as the alternate fan. Shape: [{verb_iri, score}]. Same axis
    # as the chosen verb's confidence context; captured so the map can sort
    # and label the alternates instead of showing anonymous dashed lines.
    candidate_scores: list[dict] = Field(default_factory=list)
    # Contract B observability: True when the LLM was actually invoked,
    # False when /classify_predicate short-circuited (subject resolved +
    # zero compatible verbs → NO_MATCH without burning an LLM call). The
    # standing-guard tests assert classify_called=False for known
    # zero-verb subjects so a future regression where the LLM gets
    # invoked anyway turns red immediately, before the cost or
    # confidently-wrong dispatch leaks downstream.
    classify_called: bool = True


_SUBJECT_ANCESTOR_CHAIN_CYPHER = """
MATCH (start:OntologyClass {uri: $subject_uri})
MATCH path = (start)-[:subClassOf*0..$MAXHOPS$]->(scope:OntologyClass)
WITH scope, length(path) AS hops
ORDER BY hops ASC
RETURN scope.uri AS uri, scope.label AS label, hops
"""


async def _get_subject_ancestor_chain(subject_uri: str, max_hops: int = 5) -> list[dict]:
    """Walk the subClassOf chain from ``subject_uri`` up to ``max_hops``.

    Returns ordered list of ``{uri, label, hops}`` dicts, where hops=0 is
    the subject itself. The chain is what the LLM in /classify_predicate
    needs to see in order to validate a verb's compatibility against
    inheritance rather than against the raw input_uri string —
    addresses the subClassOf-LLM-gap ADR-0018 amendment from 2026-06-11.

    Empty list when subject doesn't exist as :OntologyClass (or Neo4j
    is unreachable; we degrade silently rather than fail the route).
    """
    if not _NEO4J_DRIVER or not subject_uri or subject_uri == "UNKNOWN":
        return []
    cypher = _SUBJECT_ANCESTOR_CHAIN_CYPHER.replace("$MAXHOPS$", str(max_hops))

    def _run() -> list[dict]:
        with _NEO4J_DRIVER.session() as session:
            return [dict(r) for r in session.run(cypher, subject_uri=subject_uri)]

    try:
        return await asyncio.to_thread(_run)
    except Exception:
        return []


@app.post("/classify_predicate", response_model=ClassifyPredicateResponse)
async def classify_predicate(request: ClassifyPredicateRequest) -> ClassifyPredicateResponse:
    """Two-stage predicate classification: Weaviate recall + BAML precision.

    Mirrors /resolve's flow so the supervisor's routing decision is
    symmetric across subject and predicate:

      1. predicate_hybrid_search → top-N predicate candidates filtered by
         entitled_domains.
      2. TypeBuilder dynamic enum populated from those N candidates
         (each value's description is the verb description so the LLM
         can reason about substrate fit, not just verb names).
      3. ClassifyPredicate BAML call. Constrained-enum return guarantees
         a valid verb_iri or UNKNOWN.

    Confidence is the LLM's own assessment; the supervisor thresholds
    against it the same way ADR-0008 thresholded against the BM25 score.
    """
    entitled = [d.upper() for d in (request.entitled_domains or [])]
    compatible = set(request.compatible_verb_iris or [])

    # ADR-0019 Contract B — subject valid + zero compatible verbs →
    # hard NO_MATCH → generalist, WITHOUT burning an LLM call. The
    # caller resolved a real subject (not "UNKNOWN") and queried
    # /find_compatible_verbs, which returned []. That means Neo4j
    # already authoritatively answered "no verb in the predicate
    # graph operates on this subject (or any ancestor)." Calling the
    # LLM at this point lets it pick anything from the open
    # vocabulary — exactly the confidently-wrong dispatch this
    # contract was specified to prevent. R4 (2026-06-12) was the
    # first matrix row to surface this hole: idp:Column has zero
    # verbs typed against it until Wave-3, and "what feeds X.amount"
    # was getting routed to mesh:traceLineage from the unconstrained
    # Weaviate pool.
    #
    # The conjunction is load-bearing: an UNKNOWN subject + empty
    # compat list is the LEGACY unconstrained path (the resolver
    # couldn't place the subject so the LLM judges the predicate
    # against the raw query alone). Only "subject resolved AND zero
    # compatible verbs" short-circuits.
    if (
        request.subject_uri
        and request.subject_uri != "UNKNOWN"
        and request.compatible_verb_iris is not None
        and len(request.compatible_verb_iris) == 0
    ):
        return ClassifyPredicateResponse(
            resolved_verb_iri="UNKNOWN",
            confidence_score=0.0,
            reasoning=(
                f"Contract B short-circuit: subject {request.subject_uri!r} "
                f"resolved but Neo4j's compat-walk returned zero verbs "
                f"typed against it (or any ancestor via subClassOf). "
                f"Routing to generalist fallback without invoking the "
                f"LLM — the predicate graph already authoritatively "
                f"said no registered verb operates on this kind."
            ),
            candidate_verb_iris=[],
            classify_called=False,
        )

    candidates = await predicate_hybrid_search(
        query=request.query,
        entitled_domains=entitled,
        limit=max(request.candidate_limit, 25),  # widen so the filter survives
    )

    # ADR-0018 addendum + ADR-0006 §Addendum conjunctive-read invariant
    # (2026-06-13): when the caller has resolved the subject and asked
    # /find_compatible_verbs which predicates Neo4j says can operate on
    # it, filter the Weaviate candidate set to that subset BEFORE the
    # LLM sees anything. The LLM cannot then pick an incompatible
    # (subject, verb) pair because the offending verb never enters the
    # constrained enum.
    #
    # If the intersection is empty — the subject's compatible verbs
    # aren't present in Weaviate — the verb DOES NOT enter the LLM's
    # enum. The earlier fabrication-fallback that synthesized candidate
    # dicts from the bare IRIs was removed 2026-06-13 because it broke
    # the conjunctive-read invariant the rollback decision in ADR-0006
    # §Addendum rests on: a half-registered verb (Neo4j edge present,
    # Weaviate row missing) was getting fabricated into the enum and
    # the LLM could pick it. That defeated the safety argument for
    # gateway v0.2's rollback path.
    #
    # The "predicate-registry-vs-Weaviate sync gap" the fabrication was
    # working around is what v0.2 closes structurally: the gateway
    # writes both stores atomically in the request path, so a "Neo4j
    # has it but Weaviate doesn't" steady state is no longer reachable
    # through the normal registration path. If it ever IS reachable
    # (e.g., a partial restore from backup), the routing correctly
    # treats the verb as unregistered until the substrate is
    # reconciled — which is the truthful state.
    if compatible:
        candidates = [c for c in candidates if c.get("verb_iri") in compatible]

        # ADR-0019 Contract A — cardinality is not fit. The previous
        # "N=1 Neo4j-decisive shortcut" returned the lone candidate at
        # 0.99 confidence without consulting the LLM, which made
        # off-topic queries against valid subjects return confidently
        # wrong (e.g. "what color was Napoleon's horse?" against a
        # WorkInstruction returned mesh:queryKnowledgeGraph at 0.99).
        # The graph constraint supplies the candidate *set*; the LLM
        # validates *fit*. At N=1 the general path below builds a
        # two-value enum ({the_verb, UNKNOWN}) and calls BAML — that
        # preserves the Cypher-decisive shape while keeping the
        # "or none fit" escape. Removing the shortcut entirely is the
        # implementation: the general path already handles N≥1.
        #
        # The only sound way to skip the LLM at N=1 is an explicit
        # ``is_default: true`` flag on the registered predicate (ADR-
        # 0019 open item — not authored today, so no skip applies).

    if not candidates:
        # No registered predicate this caller is entitled to. Caller
        # routes to the generalist fallback (ADR-0008 no_match path).
        # Two distinct failure paths land here (both are forms of
        # "no predicate available"); the reason names which.
        reason = (
            f"No registered predicate matched query={request.query!r} "
            f"under entitled_domains={entitled}."
        )
        if compatible:
            # ADR-0006 §Addendum conjunctive-read invariant: a verb in
            # the Cypher compat list that's missing from Weaviate is
            # treated as unregistered until both stores agree. Pre-v0.2
            # this branch would also fire because of allowlist drift +
            # sensor dedup leaving stale Weaviate rows; v0.2 closes
            # those bug classes by writing both stores atomically.
            reason = (
                f"Conjunctive-read invariant: Neo4j marks "
                f"{list(compatible)} as compatible with the resolved "
                f"subject, but none of those verbs survived the "
                f"Weaviate intersection (registered in Cypher but not "
                f"in the predicate search index). Routes to generalist "
                f"until the substrate is reconciled."
            )
        return ClassifyPredicateResponse(
            resolved_verb_iri="UNKNOWN",
            confidence_score=0.0,
            reasoning=reason,
            candidate_verb_iris=[],
            classify_called=False,
        )

    # Walk the subject's subClassOf chain from Neo4j so the LLM can see
    # WHY a verb is compatible via inheritance, not just the raw
    # input_uri string. Without this annotation the LLM (correctly,
    # per Contract A) refuses a Dataset-typed verb against a Table
    # subject as a "substrate mismatch" — the graph's subClassOf walk
    # found the match, but its reasoning never reached the prompt.
    # See STATE_2026_06_11.md "subClassOf doesn't reach the LLM" and
    # the ADR-0018 amendment it cites.
    ancestor_chain = await _get_subject_ancestor_chain(request.subject_uri or "")
    # Quick-lookup map: ancestor_uri -> hops (0 = subject itself).
    ancestor_hops: dict[str, int] = {a["uri"]: a["hops"] for a in ancestor_chain}
    # Pretty-printed chain like "idp:Table ⊆ idp:Dataset", used when
    # annotating a candidate whose input_uri matches an ancestor at hops>0.
    def _inheritance_phrase(input_uri: str) -> str | None:
        if not input_uri or input_uri not in ancestor_hops:
            return None
        h = ancestor_hops[input_uri]
        if h == 0:
            return None  # subject IS the verb's input — no inheritance hint needed
        # Build the chain text. We have the linear order from the Cypher
        # (sorted by hops). Include only the steps from subject up to the
        # matched ancestor.
        chain_uris = [a["uri"] for a in ancestor_chain if a["hops"] <= h]
        return " ⊆ ".join(chain_uris)

    # Deduplicate candidates by verb_iri before building the enum.
    # When an engine registers the same verb against multiple input
    # subjects (engine_e_neo4j_expert + engine_e_neo4j_expert_procedure_step
    # both ship mesh:queryKnowledgeGraph), Weaviate returns one row per
    # registration. BAML's TypeBuilder.add_value(name) dedupes by enum
    # value name, so calling add_value(verb_iri) twice keeps only the
    # LAST description — and the last description's "operates on X"
    # clause may be incompatible with the resolved subject. The LLM
    # then refuses on substrate grounds even though a compatible
    # registration exists.
    #
    # The right pick per (verb_iri) is the candidate whose input_uri is
    # most-specifically compatible with the resolved subject:
    #   1. exact match on subject_uri (hops=0)
    #   2. ancestor in the subClassOf chain (hops > 0, prefer SMALLER
    #      hops as the more specific compatibility)
    #   3. fall back to ANY candidate if none are in the ancestor chain
    #      — preserves the existing behavior of letting the LLM see and
    #      refuse on substrate (Contract A) when the registration is
    #      genuinely incompatible.
    def _pick_best_per_verb(rows: list[dict]) -> list[dict]:
        # First pass: pick the best candidate per verb_iri (most specific
        # ancestor match). UNREACHABLE sentinel keeps non-ancestor
        # candidates as the fallback.
        best: dict[str, dict] = {}
        best_hops: dict[str, int] = {}
        first_seen_index: dict[str, int] = {}
        UNREACHABLE = 10**6
        for i, cand in enumerate(rows):
            v = cand.get("verb_iri") or ""
            if not v:
                continue
            if v not in first_seen_index:
                first_seen_index[v] = i
            in_uri = cand.get("input_uri") or ""
            hops = ancestor_hops.get(in_uri, UNREACHABLE)
            if v not in best or hops < best_hops[v]:
                best[v] = cand
                best_hops[v] = hops
        # Emit one entry per verb, preserving the order of the
        # first time the verb was seen in the BM25-ranked input.
        ordered: list[dict] = []
        for v in sorted(first_seen_index, key=first_seen_index.get):
            ordered.append(best[v])
        return ordered

    candidates = _pick_best_per_verb(candidates)

    # Build TypeBuilder dynamic enum from the Weaviate candidates. Each
    # enum value's description is the verb's description string — the LLM
    # sees that when picking, which lets it judge substrate fit
    # ("operates on WorkInstruction" vs "operates on catalog assets"
    # rather than just the verb name's lexical proximity).
    candidate_iris: list[str] = []
    tb = TypeBuilder()
    for cand in candidates:
        verb_iri = cand.get("verb_iri") or ""
        if not verb_iri:
            continue
        candidate_iris.append(verb_iri)
        desc_bits = []
        if cand.get("description"):
            desc_bits.append(cand["description"])
        if cand.get("verb_type") and cand["verb_type"] not in desc_bits:
            desc_bits.append(f"verb_type={cand['verb_type']}")
        input_uri = cand.get("input_uri") or ""
        if input_uri:
            inh = _inheritance_phrase(input_uri)
            if inh:
                # The graph walked subClassOf* and confirmed the subject
                # is a subclass of this verb's typed input. Tell the LLM
                # that explicitly so it doesn't treat the input_uri
                # string mismatch as a fit failure.
                desc_bits.append(
                    f"operates on {input_uri} — compatible with subject "
                    f"via inheritance ({inh})"
                )
            else:
                desc_bits.append(f"operates on {input_uri}")
        if cand.get("owner_persona"):
            desc_bits.append(f"owner persona {cand['owner_persona']}")
        enum_desc = "; ".join(desc_bits) if desc_bits else verb_iri
        tb.Predicate.add_value(verb_iri).description(enum_desc)
    # Always offer UNKNOWN so the LLM can decline without inventing a
    # poor match — same pattern as ClassifyDomainIntent's UNKNOWN.
    tb.Predicate.add_value("UNKNOWN").description(
        "No registered predicate in the candidate set is a sensible fit "
        "for this query given the resolved subject. Use this when every "
        "candidate would be the wrong substrate or wrong intent."
    )

    try:
        result = await b.ClassifyPredicate(
            query=request.query,
            subject_uri=request.subject_uri or "UNKNOWN",
            subject_reasoning=request.subject_reasoning or "",
            domain=request.domain,
            baml_options={"tb": tb},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"BAML ClassifyPredicate failed: {exc}",
        ) from exc

    resolved_verb_iri = str(result.resolved_verb_iri)
    # Find the full predicate record for the chosen verb so the supervisor
    # can dispatch without a second Weaviate hit. UNKNOWN → None.
    matched_predicate: dict | None = None
    if resolved_verb_iri and resolved_verb_iri != "UNKNOWN":
        for cand in candidates:
            if cand.get("verb_iri") == resolved_verb_iri:
                matched_predicate = cand
                break

    return ClassifyPredicateResponse(
        resolved_verb_iri=resolved_verb_iri,
        confidence_score=result.confidence_score,
        reasoning=result.reasoning,
        predicate=matched_predicate,
        candidate_verb_iris=candidate_iris,
        # Per-candidate semantic scores (Weaviate hybrid), for the map's
        # alternate fan. One entry per candidate verb, in ranked order.
        candidate_scores=[
            {"verb_iri": c.get("verb_iri"), "score": c.get("score")}
            for c in candidates
            if c.get("verb_iri")
        ],
    )


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
