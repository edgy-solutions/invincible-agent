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
from fastapi import FastAPI, HTTPException, Query, Request
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

# Telemetry (ADR-0038): join Engine O's work to the caller's trace. telemetry.py sits at /app
# in the fleet image; guarded so the engine runs identically when the shim/leaf is absent.
try:
    from telemetry import observed_trace, MAPPING, build_trace_values  # noqa: E402
except Exception:  # pragma: no cover — telemetry never load-bearing
    from contextlib import contextmanager as _cm

    @_cm
    def observed_trace(*_a, **_k):  # type: ignore[misc]
        yield

    def build_trace_values(**_k):  # type: ignore[misc]
        return {}

    MAPPING = None

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


# ---------------------------------------------------------------------------
# EFFECT-WRITE GATE — can_invoke on the SINGLE DECIDER (undeclared-routes residual)
# ---------------------------------------------------------------------------
# The manifest classed `/write_item_state` and `/write_decision_record` as
# `ungated_by_accident`: transport auth is app-wide, so an UNAUTHENTICATED caller is
# refused once REQUIRE flips — but nothing checked WHICH authenticated caller may
# perform the effect. Any minted service could stamp disposition state or append to the
# decision corpus. Gate-class-follows-the-effect: an effect write earns an authorization
# decision, not merely an identity.
#
# SAME DECIDER, SAME CONTRACT as `spo_step_executor.check_can_invoke` — capability object
# namespace, `can_invoke` relation, subject is the mint-contract `authz_id`. Deliberately
# NOT engine-o's `authz/is` rego path (used by `_can_view_class`): that one answers a
# visibility question about ontology classes. Two questions, two policies.
TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "")

# ENV IS WIRED — verified in the running pod 2026-08-13: engine-o resolves
# TOPAZ_DIRECTORY_URL=http://topaz-svc:9393 via the shared `iagent-config` configMap, and
# ENABLE_AGENTIC_AUTH=false. An earlier note here claimed the env was MISSING and called it
# an unmet precondition of the flip. That was WRONG, and the error is worth keeping visible:
# it came from reading `.spec.template.spec.containers[0].env[*]` only, which does not show
# `envFrom` configMap/secret refs. **Read the running pod, not the deployment's env array.**
#
# The fail-closed-on-unset behaviour below is therefore a DEFENSIVE property with a test, not
# an outstanding task. What remains genuinely coordinated is the FLIP itself: the caller's
# `outbound_auth_headers` is log-and-proceed, so a mint failure sends the call token-less, and
# `_fail_terminal_on_4xx` classes 403 as TERMINAL — a gate live before the caller is reliably
# minting would make disposition writes fail PERMANENTLY rather than retry.
CAP_WRITE_ITEM_STATE = "mesh:writeItemState"
CAP_WRITE_DECISION_RECORD = "mesh:writeDecisionRecord"


def _can_invoke_capability(caller_authz_id: str, capability: str) -> bool:
    """Ask the single decider whether ``caller_authz_id`` may invoke ``capability``.

    NO-OP (True) while ``ENABLE_AGENTIC_AUTH`` is off — the same phase discipline
    ``_can_view_class`` uses, and the reason this gate lands before the flip without
    breaking a write that works today. Fail-CLOSED (deny) on empty identity, empty
    capability, unset directory URL, or any error: a security gate must not fail open.
    """
    if not ENABLE_AGENTIC_AUTH:
        return True
    if not caller_authz_id or not capability or not TOPAZ_DIRECTORY_URL:
        return False
    try:
        r = httpx.post(
            f"{TOPAZ_DIRECTORY_URL}/api/v3/directory/check",
            json={
                "object_type": "capability",
                "object_id": capability,
                "relation": "can_invoke",
                "subject_type": "user",
                "subject_id": caller_authz_id,
            },
            timeout=5.0,
        )
        r.raise_for_status()
        return bool(r.json().get("check"))
    except Exception as e:  # noqa: BLE001 — fail-closed on any error
        logging.warning("can_invoke check failed capability=%s caller=%s (fail-closed deny): %s",
                        capability, caller_authz_id, e)
        return False


def _require_capability(caller, capability: str, what: str) -> str:
    """Refuse an effect write the caller may not perform, and RECORD the caller either way.

    The log line is the audit half of the approval-bypass precedent: identity threaded to
    the gate AND written down, so a future reader can tell which service produced an effect.
    Recording the caller INSIDE the graph write is a schema change — the decision record's
    ``admitted_by`` is the trust authority, not the caller — and is left as its own decision
    rather than smuggled in here.
    """
    who = getattr(caller, "authz_id", None) or ""
    if not _can_invoke_capability(who, capability):
        logging.warning("effect write REFUSED: %s caller=%s capability=%s",
                        what, who or "none", capability)
        raise HTTPException(
            status_code=403,
            detail=f"caller {who or 'none'!r} is not authorized (can_invoke) for {capability!r}",
        )
    logging.info("effect write allowed: %s caller=%s capability=%s", what, who or "none", capability)
    return who or "none"


_JENA_ENDPOINT = os.getenv("JENA_SPARQL_ENDPOINT", "")
_JENA_USERNAME = os.getenv("JENA_USERNAME", "admin")
_JENA_PASSWORD = os.getenv("FUSEKI_PASSWORD", "Admin123!")
# The SPARQL UPDATE endpoint (writes) — engine-o's ONE write path, used only by the pcn
# disposition-state stamp. Derived from the read endpoint (…/ds/sparql -> …/ds/update).
_JENA_UPDATE_ENDPOINT = os.getenv("JENA_UPDATE_ENDPOINT", "") or (_JENA_ENDPOINT.replace("/sparql", "/update") if _JENA_ENDPOINT else "")
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
    # Scope to the named graph the reproducible ingest actually writes:
    # doc-tools ontology_assets.py PUTs each domain's ontology to
    # http://internal/{DOMAIN} (uppercase, from the prime manifest's domain tag).
    # The old lowercase-semantic map (mro / sustainment / idp) matched NO graph the
    # ingest produced — a silent producer/consumer mismatch (the "core MRO/IOF graph"
    # it named no longer exists; the ingest folds core into MAINTENANCE). Only
    # /classes exercises this scoped path, so nothing broke until the SPO subject
    # menu read it (found 2026-07-22). Derive the graph from the REQUEST domain — the
    # consumer follows the producer's layout (source-authority), never a hardcoded
    # guess that goes stale silently. [[feedback_path_vs_semantic_domain]].
    #
    # CAVEAT (must land together): this is correct ONLY once the ingest's PUT-overwrite
    # bug is fixed. Today each domain's multiple TTLs all PUT to one graph and collapse
    # to the LAST file (MAINTENANCE = mil_extension alone, IOF core/MRO destroyed), so
    # {domain} points at a real-but-THIN graph until the producer switches to
    # append/merge. Shipping the name fix alone yields a thin menu, not a full one.
    _dom = "".join(c for c in (domain or "") if c.isalnum() or c == "_") or "MAINTENANCE"
    # READ-SIDE UNION mirroring the write-side split (2026-07-23). A domain's triples live in TWO
    # graphs: its manifest-reproducible VOCABULARY graph <http://internal/{DOMAIN}> and its
    # non-reproducible runtime INSTANCE graph <http://internal/{DOMAIN}_INSTANCES> (doc-tools writes
    # instances there so prime's DROP-first never wipes them — producers with different
    # reproducibility must not share a graph). Scope reads to the UNION of both so ANY consumer on
    # this path sees vocab + instances without knowing the split — the convention lives in the
    # consumer's single derivation, not each provider's memory ([[feedback_path_vs_semantic_domain]]).
    # A domain with no instance graph (e.g. MAINTENANCE_INSTANCES absent) simply contributes nothing.
    # NOTE: this is why the split did NOT re-hide instances the way the default graph did — the
    # domain-scoped read now spans both graphs by construction.
    _graph_scope = (f"VALUES ?__mesh_g {{ <http://internal/{_dom}> "
                    f"<http://internal/{_dom}_INSTANCES> }} GRAPH ?__mesh_g")

    # 🛑 Strictly enforce data segregation by wrapping the query in the graph context.
    # This assumes the input query uses standard triple patterns that we want to scope.
    # For complex queries, we might need a more robust parser, but for our Agentic Mesh
    # standard patterns, this wrapping is effective.
    scoped_query = query
    if "GRAPH" not in query.upper() and "SELECT" in query.upper():
        # Simple injection: replace WHERE { with WHERE { VALUES ?g {vocab inst} GRAPH ?g {
        if "WHERE {" in query:
            scoped_query = query.replace("WHERE {", f"WHERE {{ {_graph_scope} {{", 1)
            last_brace_idx = scoped_query.rfind("}")
            if last_brace_idx != -1:
                scoped_query = scoped_query[:last_brace_idx] + "} }" + scoped_query[last_brace_idx+1:]
        elif "WHERE {" in query.upper():
            # Handle case-insensitive WHERE
            import re
            scoped_query = re.sub(r"WHERE\s*\{", f"WHERE {{ {_graph_scope} {{", query, flags=re.IGNORECASE, count=1)
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
        # Absent definitions render as NOTHING, not a filler sentence —
        # 'No definition available.' repeated across hundreds of classes
        # is pure token noise in the BAML prompt and teaches the model
        # to pattern-match the filler instead of the names.
        definition_text = row.get("definition")
        definition = f": {definition_text}" if definition_text else ""
        example_text = row.get("example")
        example = f" Examples: {example_text}" if example_text else ""
        lines.append(f"{uri} — {label}{definition}{example}")
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

    # Register engine-o as the SUSTAINMENT mesh:resolveInstance provider (Recipe v2 pattern, mirrors
    # Engine D). engine-o owns the SUSTAINMENT_INSTANCES graph, so it self-hosts /resolve_instance
    # and self-registers here — REPRODUCIBLE: runs every boot, survives re-prime, NOT a hand-run Cypher
    # (bootstrap-state-debt). The /resolve fan-out then discovers it like any other provider.
    try:
        try:
            from utils.mesh_registration import engine_mint, register_engine_to_mesh  # type: ignore[no-redef]
        except ImportError:
            from agent_fleet.utils.mesh_registration import engine_mint, register_engine_to_mesh
        _pcn_endpoint = os.getenv(
            "ONTOLOGY_SVC_SELF_URL", "http://iagent-engine-o:8084"
        ).rstrip("/") + "/resolve_instance"
        register_engine_to_mesh(
        mint=engine_mint(client_id="iagent-engine-o", secret_env="ENGINE_O_CLIENT_SECRET"),
            name="engine_o_sustainment_resolve_instance",
            description=(
                "Resolves a PCN/PDN identifier — a manufacturer part number (e.g. NSR01L30NXT5G) or a "
                "notice id (e.g. PCN IPCN25300X) — to its pcn: instance node in the SUSTAINMENT graph, "
                "by deterministic-IRI exact match then descriptor-strip fuzzy match. Returns candidates "
                "with class URI, label, IRI identity, and score sorted descending. An empty list is a "
                "first-class answer — abstains below its floor rather than returning least-bad matches. "
                "pcn/pdn are identifier fragments, never stripped; MPNs are matched verbatim."
            ),
            verb="mesh:resolveInstance",
            input_uri="http://invincible-agent/mesh#InstanceIdentifier",
            output_uri="http://invincible-agent/mesh#InstanceResolution",
            verb_synonyms=["resolve part", "look up MPN", "which component", "identify notice", "resolve PCN"],
            endpoint_url=_pcn_endpoint,
            owner_persona="OPS_OPERATOR",
            domains=["SUSTAINMENT"],
            cost_class="fast",
            requires_human_approval=False,
            provider="engine_o_sustainment",
            timeout_s=5.0,
        )
        print(f"[ontology-service] registered SUSTAINMENT mesh:resolveInstance provider -> {_pcn_endpoint}")
    except Exception as e:  # noqa: BLE001
        print(f"[ontology-service] pcn mesh:resolveInstance registration failed: {e}")

    await _check_jena_populated()
    yield
    if _WEAVIATE_CLIENT:
        _WEAVIATE_CLIENT.close()
    if _NEO4J_DRIVER:
        _NEO4J_DRIVER.close()


from fastapi import Depends
# TRANSPORT AUTH (OBSERVE). One implementation, from the mesh membership package: validate
# whatever arrives, log the caller posture per request, REFUSE NOTHING until
# REQUIRE_TRANSPORT_AUTH flips. The announcement is the pre-positioned string the contract
# phase's fresh-deploy test asserts against — an engine that takes the dependency but loses
# the announcement has a real posture the gauge cannot read.
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth
_announce_transport_auth(component="engine-o")
app = FastAPI(
    **_docs_kwargs(),  # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    dependencies=[Depends(_transport_auth("engine-o"))],
    title="Engine O — Ontology Reasoner",
    description=(
        "Translates natural language into IOF/MIMOSA sustainment terms. "
        "No compute or orchestration — pure semantic resolution."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def _telemetry_join(request: Request, call_next):
    # ADR-0038: join this engine's work to the CALLER's trace. The analyst forwards its trace
    # id as X-Trace-Id (discovery.py); observed_trace seeds create_trace_id on it, so every
    # endpoint nests under the caller's trace. Fail-soft; no-op without a trace id / when off.
    tid = request.headers.get("X-Trace-Id")
    if not tid:
        return await call_next(request)
    with observed_trace(MAPPING, build_trace_values(
        trace_id=tid, engine="ontology_service", verb=request.url.path,
    ), name="engine-o " + request.url.path):
        return await call_next(request)


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
    # THE SLOTS THE SPEAKER NAMED - {"group_by": "initiative"} for "where is funding short
    # by initiative". Distinct from `entity_refs`, which are untyped VALUES with no
    # argument name attached; these are argument NAME -> value, which is what a verb can
    # actually be called with.
    #
    # EMPTY TODAY, ON EVERY REQUEST, AND THAT IS THE POINT. Nothing fills it yet: BAML's
    # `RouteIntent` - the function that returns typed slot classes - has zero callers, and
    # this endpoint calls `ExtractIntent`, which decides MODE and pulls entity refs and was
    # never designed to do slot work. The field lands first so the three deterministic
    # joins downstream can be built and TESTED against fixtures before a model is put in
    # the loop, and so the last join becomes a call rather than a refactor.
    #
    # Additive and defaulted: a caller that never sets it is unchanged, and a consumer that
    # never reads it is unchanged.
    # See docs/plans/slots-are-extracted-then-dropped-at-dispatch.md.
    slots: dict[str, object] = {}


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

        # Hybrid: compute the query vector via embed_query() and hand it to
        # Weaviate explicitly. No text2vec module on the cluster — code owns
        # the contract. If the embedding gateway fails, Weaviate hybrid()
        # degrades gracefully: BM25 still scores normally; the vector
        # contribution is just zero / no-op.
        #
        # THIS COMMENT USED TO SAY the Predicate collection "has no vectors
        # stored yet (current state — only re-ingest will backfill them)".
        # That was TRUE, and it stayed true for months, because LLM_BASE_URL
        # was never set in sandbox: every embed raised, the registrar's write
        # path caught it and stored the row without a vector, and this
        # graceful degradation ran as the ONLY path. Verb nomination was
        # BM25-only for the entire life of the deployment, and an
        # architecture bake-off was measured on it.
        #
        # The comment is the whole lesson. A KNOWN defect written down as
        # "current state" reads to every later reader as a description of how
        # things are rather than a bug with an owner. Prose cannot hold a
        # temporary condition — it has no expiry and nothing re-reads it. If
        # a degraded state matters, it needs a COUNTER somewhere a human
        # looks (the registrar now reports predicate_rows_vectorized on
        # /health), because that is the only form of the fact that can go
        # from true to false and have anyone notice.
        #
        # Fixed 2026-08-24; coverage verified non-zero on the running pod.
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
        identifier_name_and_qualifiers as _ir_split_identifier,
        decide_instance_abstention as _ir_abstention,
        instance_not_found_message as _ir_not_found_msg,
        DEFAULT_EXACT_THRESHOLD as _IR_DEFAULT_EXACT,
        DEFAULT_MIN_SCORE as _IR_DEFAULT_MIN,
    )
except ImportError:
    from instance_resolution import (  # noqa: E402
        InstanceCandidate as _IRCandidate,
        decide as _ir_decide,
        identifier_name_and_qualifiers as _ir_split_identifier,
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
    # NORMALIZE AT THE FAN-OUT, NOT AT SCORING (2026-08-20). The specificity gate scores
    # candidates and was correct; it was STARVED. A qualified identifier (`publog.p_cage`)
    # was sent to the providers verbatim, they matched nothing on the literal string, and
    # the gate then rejected an empty set — reported as `not_specific`, which read as "the
    # token is not a name" when the truth was "nobody was asked a question they could
    # answer". Measured: n=0, rejected_n=0.
    #
    # So the qualifier is stripped BEFORE the phone book is asked. The ORIGINAL identifier
    # still goes to `decide`, because specificity must be judged on what the user said —
    # stripping for the lookup must not also loosen the check.
    _name, _quals = _ir_split_identifier(identifier)
    _lookup_terms = [identifier]
    if _name and _name != identifier.strip().lower():
        _lookup_terms.append(_name)

    tasks = [_call_resolver(r, term, query)
             for r in resolvers for term in _lookup_terms]
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
        # The identifier reaches the decision table for the first time (2026-08-17).
        # Without it the table could only rank candidates; it could not ask whether the
        # token NAMES any of them, which is what let `cage` win. See the segment
        # specificity gate in instance_resolution.py.
        identifier=identifier,
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


# Honest-degradation guard for subject resolution (recall-override). Pure logic
# in a dep-free sibling so it unit-tests without the engine-o import chain;
# flatten-aware import, same shape as registry_views above.
try:
    from recall_guard import recall_override_guard as _recall_override_guard  # type: ignore[no-redef]
except ImportError:
    from agent_fleet.ontology_service.recall_guard import recall_override_guard as _recall_override_guard

try:
    from sustainment_instance_provider import resolve_sustainment_candidates as _resolve_sustainment_candidates, SUSTAINMENT_INSTANCES_QUERY as _SUSTAINMENT_INSTANCES_QUERY  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.ontology_service.sustainment_instance_provider import resolve_sustainment_candidates as _resolve_sustainment_candidates, SUSTAINMENT_INSTANCES_QUERY as _SUSTAINMENT_INSTANCES_QUERY

try:
    from state_sparql import build_item_state_update as _build_state_update, build_instances_by_property_query as _build_parts_query  # type: ignore[no-redef]
    from state_sparql import sparql_lit as _sparql_lit  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.ontology_service.state_sparql import build_item_state_update as _build_state_update, build_instances_by_property_query as _build_parts_query
    from agent_fleet.ontology_service.state_sparql import sparql_lit as _sparql_lit

try:
    from policy_rules_sparql import build_rules_construct, build_graph_probe_ask  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.ontology_service.policy_rules_sparql import build_rules_construct, build_graph_probe_ask


#: EVERY OPTION IN THE POOL MUST BE PRODUCTIVE — menu integrity, applied to grounding.
#:
#: A class nothing serves is not a useful answer to subject resolution. It grounds at high
#: confidence, `/find_compatible_verbs` returns nothing, and the supervisor falls to the
#: generalist — which answers from the catalog wearing the CALLER's persona, and is
#: indistinguishable from a real answer until a human reads the card. Measured across three
#: engines in one week: cost#CostCategory, idp#Job, idp#Pipeline, fin#EarnedValueTechnique.
#:
#: AND IT IS WHY WINNER-INSTABILITY LOOKED LIKE NOISE. The row "show me SPI over time"
#: flipped between PerformanceMeasurementBaseline and EarnedValueTechnique across draws and
#: was recorded as an unstable sampler. One of those winners routes and the other cannot be
#: answered at all, so half its draws were a different KIND of event — and a run scored on
#: class names cannot see the difference, because both produce a class name.
#:
#: DOMAIN-RELATIVE BY CONSTRUCTION, which is the half a global check gets wrong. idp:Dashboard
#: carries nine verbs under DATA_ENGINEERING and none under PORTFOLIO_PLANNING; that is the
#: domain filter working, not a gap. Restricting per the caller's own domains keeps it
#: available to the caller who can use it and absent from the one who cannot.
#:
#: The `*0..5` walk mirrors `/find_compatible_verbs` exactly: a class is served when IT or an
#: ANCESTOR carries a verb, because that is the walk the router will perform next. A filter
#: with a different reach than the consumer it feeds would drop classes that do route.
_SERVED_CLASSES_CYPHER = """
MATCH (c:OntologyClass)-[:subClassOf*0..5]->(anc:OntologyClass)
MATCH (anc)-[r]->(:OntologyClass)
WHERE r.iri IS NOT NULL
  AND (
    size($domains) = 0
    OR coalesce(r.domains, []) = []
    OR any(d IN r.domains WHERE d IN $domains)
  )
RETURN DISTINCT c.uri AS uri
UNION
MATCH (c:OntologyClass)-[:subClassOf*1..5]->(m:OntologyClass)
WHERE m.uri = $referent_root
RETURN DISTINCT c.uri AS uri
"""

#: Declared exemption: groundable on purpose, served by no verb. See mesh:ResolvableReferent
#: in mesh_system.ttl for why the marker is a subClassOf edge rather than an annotation.
_RESOLVABLE_REFERENT_ROOT = "http://invincible-agent/mesh#ResolvableReferent"

#: (domains-key) -> (expiry, frozenset). Verb edges change only at registration, so a short
#: TTL is ample and keeps a per-request graph walk off the hot path.
_SERVED_CACHE: dict = {}
_SERVED_TTL_S = float(os.getenv("SERVED_CLASSES_TTL_S", "120"))


async def _served_class_uris(domains: list, include_referents: bool = True) -> frozenset:
    """Classes carrying a verb in these domains, plus (by default) declared referents.

    RETURNS AN EMPTY SET ON ANY FAILURE, AND THE CALLER MUST READ THAT AS "DO NOT FILTER".
    That direction is not a detail: an empty served-set applied as a filter would empty the
    candidate pool and take routing down globally, turning a Neo4j hiccup into a total
    outage. Degrading OPEN restores exactly the pre-filter behaviour — a dead end reachable
    again — which is the failure this filter reduces rather than one it creates.

    ``include_referents`` SELECTS BETWEEN TWO DIFFERENT QUESTIONS, and conflating them is a
    live trap rather than a nicety:

      * ``True``  -- *may the resolver OFFER this class?* A declared `mesh:ResolvableReferent`
        is groundable on purpose ("lot 4" is a real thing a caller names), so it belongs in
        the candidate pool. That is the productive-option gate's question.
      * ``False`` -- *can this class be ANSWERED?* A referent is precisely a class that
        grounds and cannot be answered, so it must NOT count as served here. That is the
        post-preemption check's question.

    THE TRAP IS DELAYED, WHICH IS WHY THIS IS PARAMETERISED RATHER THAN LEFT TO THE CALLER.
    Measured 2026-09-04: the referent set is EMPTY in the live graph, so today both questions
    return the same answer for `fin:WBSElement` and one shared predicate would look correct.
    The day someone declares WBSElement a referent -- which the ruling says is the RIGHT thing
    to do -- a shared predicate would silently stop abstaining on it. Doing the correct thing
    would disable the protection, with nothing going red.

    ONE Cypher for both, with the referent UNION switched off by a null root, so the two
    reaches cannot drift the way two copies would.
    """
    key = f"{','.join(sorted(domains or []))}|ref={int(include_referents)}"
    now = time.time()
    hit = _SERVED_CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    if not _NEO4J_DRIVER:
        return frozenset()

    def _run() -> set:
        with _NEO4J_DRIVER.session() as session:
            rows = session.run(
                _SERVED_CLASSES_CYPHER,
                domains=list(domains or []),
                # None matches no node, so the UNION contributes nothing -- the reach
                # changes without a second query to keep in step.
                referent_root=_RESOLVABLE_REFERENT_ROOT if include_referents else None,
            )
            return {str(r["uri"]) for r in rows if r["uri"]}

    try:
        served = frozenset(await asyncio.to_thread(_run))
    except Exception as exc:  # noqa: BLE001
        print(f"[Engine O] productive-option gate: served-class lookup failed "
              f"({type(exc).__name__}) — NOT filtering this request")
        return frozenset()
    _SERVED_CACHE[key] = (now + _SERVED_TTL_S, served)
    return served


def _unserved_subject_msg(identifier: str, resolved_uri: str) -> str:
    """An abstention that KEEPS the resolution it just made.

    The instance lookup succeeded — saying so is strictly more useful than a bare refusal,
    and it is the difference between "I don't know what you mean" and "I know what you mean
    and cannot answer that about it". The caller can act on the second.
    """
    label = resolved_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] or resolved_uri
    return (
        f"I found {identifier!r} — it resolves to {label} — but nothing in your current "
        f"scope answers questions about a {label} directly. Try asking about the larger "
        f"thing it belongs to, or name what you want to know."
    )


async def _preempted_subject_is_unanswerable(resolved_uri: str, domains: list) -> bool:
    """THE POST-PREEMPTION PRODUCTIVITY CHECK (ruled 2026-09-04).

    There are two paths into `resolved_uri` and until now only one was gated. The
    productive-option gate restricts what the resolver may CHOOSE; instance preemption then
    OVERRIDES that choice with a unanimous provider answer, unchecked — so a phone-book match
    can install a class no verb serves. Measured by the engine-cost lane: 10 of 18 draws had a
    winner outside the candidate pool, every one of them `fin:WBSElement`, which carries no
    verb in any domain. The DOMINANT dead end, reached by the one path the gate cannot see.

    THE OVERRIDE IS NOT THE DEFECT and this does not block it. A caller named "lot 4", a
    provider resolved it, and that resolution is correct. What was missing is that nothing
    then noticed the resolved subject cannot be answered, so the router fell through to the
    generalist — which answers from the catalog wearing the caller's own persona and is
    indistinguishable from a real answer until a human reads the card.

    ``include_referents=False`` IS THE LOAD-BEARING ARGUMENT, not a default worth skimming.
    The gate asks "may we offer this?", where a declared referent belongs. This asks "can this
    be answered?", where a referent is exactly the thing that cannot. See `_served_class_uris`.

    DEGRADES OPEN, on the same discipline as the gate: an empty served-set means the lookup
    failed, and the override then stands. That restores today's behaviour rather than
    converting a Neo4j hiccup into a refusal storm.
    """
    if not resolved_uri or resolved_uri == "UNKNOWN":
        return False
    answerable = await _served_class_uris(domains, include_referents=False)
    if not answerable:
        return False
    return resolved_uri not in answerable


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
                "description": row.get("definition") or ""
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

    # ── Step 1.56: THE PRODUCTIVE-OPTION GATE (ruled 2026-09-04) ──────────────────
    #
    # Every option the resolver may pick must be one the router can then serve, for the
    # caller's own domains. See _served_class_uris for the measured defect and why this is
    # domain-relative.
    #
    # DEGRADES OPEN, DELIBERATELY, AND THE ORDER OF THESE TWO CHECKS IS THE SAFETY. An empty
    # `served` means the lookup failed or the graph is cold, and filtering against it would
    # empty the pool and take routing down for every caller — a far worse outcome than the
    # dead end this gate exists to remove. Likewise a filter that would remove EVERYTHING is
    # refused: that is the signature of a served-set computed against the wrong domains, and
    # answering from a dead end beats answering nothing while the cause is found.
    if candidates:
        _served = await _served_class_uris(request.domains or ([request.domain] if request.domain else []))
        if _served:
            _productive = [c for c in candidates if c.get("uri") in _served]
            _unproductive = len(candidates) - len(_productive)
            if _productive and _unproductive:
                print(f"[Engine O] productive-option gate DROPPED {_unproductive} "
                      f"unserved class(es) from the pool "
                      f"(domains={request.domains or request.domain!r})")
                candidates = _productive
            elif not _productive:
                print("[Engine O] productive-option gate would have emptied the pool "
                      f"({len(candidates)} candidate(s), 0 served) — NOT filtering. "
                      "Suspect a served-set computed against the wrong domains.")

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
                # POST-PREEMPTION PRODUCTIVITY CHECK — site 1 of 2. BOTH preemption
                # returns need it: a check on one is silent by construction on the other,
                # and this branch is the one that fires when class recall found NOTHING,
                # so it is the LEAST likely to have a servable subject.
                if await _preempted_subject_is_unanswerable(
                    instance_subject, request.domains or ([request.domain] if request.domain else [])
                ):
                    instance_provenance["abstention_reason"] = "no_compatible_verbs"
                    instance_provenance["unanswerable_subject"] = instance_subject
                    print(f"[Engine O] post-preemption check ABSTAINED: "
                          f"{entity_ref!r} resolved to {instance_subject} which carries "
                          f"no verb in request.domains or ([request.domain] if request.domain else [])")
                    return SemanticResolutionResponse(
                        resolved_uri="UNKNOWN",
                        confidence_score=0.0,
                        reasoning=_unserved_subject_msg(entity_ref, instance_subject),
                        provenance=instance_provenance,
                    )
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
            # POST-PREEMPTION PRODUCTIVITY CHECK — site 2 of 2. This is the path the
            # engine-cost lane measured: 10 of 18 draws overridden onto fin:WBSElement.
            # `candidates` is carried into the abstention too, so the decision path can
            # still show the class contest that ran before the override.
            if await _preempted_subject_is_unanswerable(
                instance_subject, request.domains or ([request.domain] if request.domain else [])
            ):
                instance_provenance["abstention_reason"] = "no_compatible_verbs"
                instance_provenance["unanswerable_subject"] = instance_subject
                print(f"[Engine O] post-preemption check ABSTAINED: "
                      f"{identifier!r} resolved to {instance_subject} which carries "
                      f"no verb in request.domains or ([request.domain] if request.domain else [])")
                return SemanticResolutionResponse(
                    resolved_uri="UNKNOWN",
                    confidence_score=0.0,
                    reasoning=_unserved_subject_msg(identifier, instance_subject),
                    provenance=instance_provenance,
                    candidates=candidates,
                )
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
        # tell the user "no provider knows it"). Keep the LLM's class guess,
        # but the phone-book did NOT confirm it — apply the recall-override
        # honesty guard so an override of strong recall reads as weak.
        _conf, _reason, _prov = _recall_override_guard(
            str(result.resolved_uri), result.confidence_score,
            candidates, result.reasoning, instance_provenance,
        )
        return SemanticResolutionResponse(
            resolved_uri=str(result.resolved_uri),
            confidence_score=_conf,
            reasoning=_reason,
            provenance=_prov,
            candidates=candidates,
        )

    # Step 5: Return structured response (no identifier extracted).
    # This is the common class-contest path — the LLM picked
    # result.resolved_uri from `candidates`. Carry the full pool with
    # scores so the decision-path resolver stage can show the winner
    # AND the losers (the PROV-contamination diagnosis lived exactly
    # here: the winner was prov#Bundle at 0.66, and the losers-with-
    # scores are what made "contaminated pool" a glance).
    #
    # No phone-book ran (no identifier), so this is the LLM standing alone —
    # apply the recall-override honesty guard: if the LLM overrode a strong
    # vector-recall winner, discount + flag so it reads as the weak path.
    _conf, _reason, _prov = _recall_override_guard(
        str(result.resolved_uri), result.confidence_score,
        candidates, result.reasoning, None,
    )
    return SemanticResolutionResponse(
        resolved_uri=str(result.resolved_uri),
        confidence_score=_conf,
        reasoning=_reason,
        provenance=_prov,
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
                "description": row.get("definition") or ""
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
        # INJECT active_personas HERE (view-function — see ADR-0009 Step E'), TWICE:
        # once as the ROSTER PROSE the prompt reads, and once as the VALUES of the
        # `PersonaTarget` dynamic enum the ANSWER IS PARSED AGAINST. Only the first
        # was supplied, and the second is not optional.
        #
        # `PersonaTarget` is declared `@@dynamic` with NO static members
        # (baml_shared/baml_src/contracts.baml). A call that ships no TypeBuilder hands
        # BAML an EMPTY enum, so `AgentTaskDefinition.target_persona` has no legal value
        # and EVERY task fails to parse. The model answers correctly — a live sandbox
        # trace shows it returning one well-formed `{"target_persona": "PORTFOLIO_LEAD"}`
        # task — and the parser then drops it, leaving `tasks: []` with `reasoning` and
        # `extracted_concepts` fully populated. The passthrough below fires and stamps
        # DATA_STEWARD on it.
        #
        # WHY IT SURVIVED: the shape is indistinguishable from a small model declining to
        # decompose, and the comment on that passthrough said exactly that. A wrong
        # explanation that fits is stickier than no explanation. The tell is in the
        # RENDERED PROMPT, not the response — `target_persona: ,` with nothing after the
        # colon, where the enum members should be listed.
        #
        # `/route_and_plan` further down builds this TypeBuilder correctly. This endpoint
        # is the one the supervisor actually calls, and it did not. Both reads come from
        # `fetch_active_personas` so the enum and the prose cannot disagree.
        tb = TypeBuilder()
        for persona_name in await fetch_active_personas():
            tb.PersonaTarget.add_value(persona_name).description(
                _LEGACY_PERSONA_PROMPTS.get(persona_name, "Persona-specific specialist.")
            )
        plan = await b.DecomposeQuery(
            raw_query=request.query,
            active_personas=await get_baml_persona_string(),
            baml_options={"tb": tb},
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
        # ⚠️ THIS COMMENT USED TO BLAME THE MODEL, AND THAT WAS WRONG. It read:
        # "gpt-oss via Ollama (and similar reasoning-heavy small models) sometimes
        # populates reasoning + extracted_concepts but leaves tasks=[]". Measured on
        # the sandbox cluster 2026-08-31, that never happened: the model returned a
        # well-formed task every time and the EMPTY `PersonaTarget` enum above discarded
        # it. `tasks=[]` was deterministic, not occasional, and this branch fired on
        # 100% of calls — stamping DATA_STEWARD on every query the fleet ever planned.
        #
        # The branch is KEPT, because a genuinely task-less response is still possible
        # and spawning nothing is still worse. But it is now a fallback rather than the
        # only path, and `degraded` in a response is now real signal about the model
        # instead of a constant. If you see it on every call again, suspect the
        # TypeBuilder before you suspect the LLM.
        #
        # STILL OPEN: DATA_STEWARD is a hardcoded guess and a wrong one for most
        # domains. Left as-is deliberately — changing it is a routing change and wants
        # its own ruling, not a ride-along on a wiring fix.
        #
        # Synthesizing a single passthrough task keeps the
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
# POST /fill_slots — what the SPEAKER named, once the verb is known
# ---------------------------------------------------------------------------
#
# THE LAST JOIN of the slot pipeline. Routing decides WHICH verb; this decides what
# that verb was asked to be called WITH. Before it existed every verb ran on its
# signature defaults, and the seeded question "where is funding short by initiative"
# returned eleven ORGANISATIONS — rendering cleanly, with clean provenance, and with no
# surface on which a reader could notice.
# See docs/plans/slots-are-extracted-then-dropped-at-dispatch.md.
#
# WHY HERE AND NOT IN /route_intent, which is where the original ruling put it: that
# endpoint receives ONLY the query. ADR-0009 Step F'.6 deliberately removed
# `candidate_verb` — an LLM-extracted verb is a lossy intermediate when
# /search_predicates runs hybrid over the raw query — so at /route_intent time there is
# no verb, no declarations, and nothing to fill against. The supervisor calls this AFTER
# it has resolved a predicate, which is the first moment the phrase and the verb are
# both in hand. See docs/plans/the-slot-filler-belongs-where-the-verb-is-known.md.


class FillSlotsRequest(BaseModel):
    query: str
    verb_iri: str
    #: The verb's own declarations, as `mesh_slots` carries them: either the JSON string
    #: the graph holds or an already-decoded list. The CALLER supplies them rather than
    #: this service re-reading the graph, because the supervisor already holds the
    #: predicate it resolved and a second read could disagree with the first.
    #: `object`, not `Any`: this module uses `from __future__ import annotations` and
    #: imports nothing from `typing`, because Pydantic v2 cannot resolve those names as
    #: forward refs — the same reason the model further down documents using `str = ""`
    #: over `Optional[str]`. The first draft used `Any` and every request raised
    #: PydanticUserError at model-build time. Builtin generics (`list[str]`, `dict`) are
    #: fine; names imported from `typing` are not.
    declarations: object = None


class FillSlotsResponse(BaseModel):
    #: Parameter name -> value. `{}` is the common and honest case.
    slots: dict = {}
    confidence: float = 0.0
    reasoning: str = ""
    #: Names the model offered that were NOT accepted, with the reason. Surfaced rather
    #: than swallowed: a dropped slot is a question the system did not answer as asked,
    #: and the whole finding this endpoint closes was about that happening in silence.
    refused: list[str] = []
    #: PER-SLOT RESOLUTION OUTCOME for slots that name a referent, keyed by slot name:
    #: `{"outcome": exact|fuzzy|mixed|not_specific|empty|not-attempted,
    #:   "spoken": "Aurora", "instance_id": "S1", "candidates": [...]}`.
    #:
    #: THREE-VALUED, NEVER PASS-THROUGH-ON-FAILURE. An unresolvable name left in `slots`
    #: as the raw string is INDISTINGUISHABLE at the dispatch point from a successful
    #: fill: the supervisor sees a value, dispatches, and the engine 422s. The `ask`
    #: disposition — whose trigger is a spoken-mandatory slot ABSENT after filling —
    #: cannot fire on a slot that is present and wrong. So an unresolved referent is
    #: removed from `slots` and reported here instead.
    #:
    #: CANDIDATES ARE KEPT even though nothing consumes them yet. A `fuzzy` or `mixed`
    #: outcome is holding exactly the options a disambiguation ask would offer, and
    #: `resolveInstance` is the only source of such a menu that exists today (enumeration
    #: does not). Discarding them at this boundary would leave the elicitation lane with
    #: no option source for the one case it can otherwise answer.
    resolution: dict = {}


#: Kinds the ROUTE supplies. Never shown to the model — see `_slot_spec`.
_ROUTE_SUPPLIED_KINDS = frozenset({"handle", "ceremony"})

#: This module has no module-level `logger`; the first draft of /fill_slots used one and
#: would have raised NameError inside its own failure branches — the ones that exist so a
#: bad model reply degrades to defaults rather than 500-ing the route. Caught by AST scope
#: check, not by a test, because no test enters those branches.
_slots_logger = logging.getLogger("iagent.slots")


def _decode_declarations(raw: Any) -> list[dict]:
    """Mirror of iagent_pure.slot_acceptance.decode_declarations.

    Mirrored rather than imported because this service does not ship `iagent_pure`, and
    it is stdlib-only by that package's rule anyway. `list()` on the JSON string the
    graph holds would yield one entry PER CHARACTER — the same container-traded-for-
    elements defect that produced "422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4".
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, list):
        return []
    return [d for d in raw if isinstance(d, dict) and d.get("name")]


def _anchor_period(declarations: list[dict], today: str = "") -> str:
    """Which fiscal period contains today — the ANCHOR that makes "this quarter" answerable.

    DERIVED FROM THE DECLARATION'S OWN CALENDAR, never from a copy. `period_end` rides on
    every period slot precisely so this can be computed without a second fiscal table, which
    would be the two-registries shape and would drift the first time a fiscal year moved.

    The anchor is the EARLIEST period whose end date is not before today. Returns "" when no
    period slot is declared, when the calendar is absent, or when today falls outside it —
    and "" is an honest answer that the prompt is told to treat as "resolve nothing", rather
    than a nearest-period guess. A wrong anchor silently rescopes every relative question.
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    boundaries: dict[str, str] = {}
    for d in declarations:
        if d.get("period_end"):
            boundaries = dict(d["period_end"])
            break
    if not boundaries:
        return ""
    for label, end in sorted(boundaries.items(), key=lambda kv: kv[1]):
        if end >= today:
            return label
    return ""


def _slot_spec(declarations: list[dict]) -> tuple[str, dict[str, dict]]:
    """Render the SPOKEN slots as a prompt spec, and return the lookup for validation.

    ROUTE-SUPPLIED SLOTS ARE NOT SHOWN. `baseline_state`, `ops`, `scenario_name` and
    friends are resolved by the dispatcher from the store; a caller who can name them is
    not parameterising a question, they are supplying the evidence the answer is computed
    from. The guard downstream refuses them regardless — not offering them means they
    cannot be offered back, which is defence in depth rather than a substitute for it.
    """
    spoken = [d for d in declarations if d.get("kind") not in _ROUTE_SUPPLIED_KINDS]
    lines = []
    for d in spoken:
        bits = [f"- {d['name']} ({d.get('type') or 'str'})"]
        if d.get("required"):
            bits.append("REQUIRED")
        if d.get("values"):
            # The verb's OWN vocabulary, read out of its signature's Literal — so the
            # model is choosing from what the code accepts, not from what it can imagine.
            bits.append("one of: " + ", ".join(str(v) for v in d["values"]))
        if d.get("referent"):
            # NAME IT AS THE SPEAKER SAID IT. This slot holds an opaque id and the model has
            # no way to know which id; a separate resolver does. Left unsaid, the model
            # renders an id-SHAPE from the name — `order_to_cash` for "Order to Cash" — which
            # is neither the id nor the words anyone said, and which cost a live regression:
            # the resolver scored it 0.0 against its own label and the slot came back
            # unresolved. Passing the words through is what lets the resolver do its job.
            bits.append("give the NAME exactly as the speaker said it, not an id or an "
                        "id-like rendering of it; the system resolves names to ids")
        if d.get("default") is not None:
            bits.append(f"defaults to {d['default']!r} if the speaker says nothing")
        lines.append("  ".join(bits))
    return ("\n".join(lines) or "(this operation takes no parameters)"), {
        d["name"]: d for d in spoken
    }


@app.post("/fill_slots", response_model=FillSlotsResponse)
async def fill_slots(request: FillSlotsRequest) -> FillSlotsResponse:
    """Extract the parameters the speaker named, for an already-routed verb.

    HONEST-EMPTY ON EVERY FAILURE. No declarations, an unparseable model reply, or a
    model error all return `{}` — which is exactly the pre-slot behaviour (the verb runs
    on its defaults). This endpoint must never be able to make routing worse than it was
    before it existed, so it degrades to the old behaviour rather than to an exception.
    """
    declarations = _decode_declarations(request.declarations)
    spec, by_name = _slot_spec(declarations)
    if not by_name:
        # Nothing spoken is fillable — every declared slot is route-supplied, or the verb
        # was never projected. Do not spend a model call to be told nothing.
        return FillSlotsResponse(reasoning="verb declares no spoken parameters")

    try:
        # THE ANCHOR. Empty when nothing declares a calendar, and the prompt treats empty as
        # "resolve no relative period" — so a verb with no period slot is unaffected and a
        # missing calendar degrades to the pre-anchor behaviour rather than to a guess.
        anchor = _anchor_period(declarations)
        filled = await b.FillVerbSlots(
            question=request.query,
            verb=request.verb_iri,
            slot_spec=spec,
            today=anchor or "unknown",
        )
    except Exception as exc:  # noqa: BLE001 — degrade to defaults, never 500 the route
        _slots_logger.warning("fill_slots: model call failed for %s: %s", request.verb_iri, exc)
        return FillSlotsResponse(reasoning=f"slot extraction unavailable: {exc}")

    try:
        raw = json.loads(filled.slots_json or "{}")
    except (ValueError, TypeError):
        _slots_logger.warning(
            "fill_slots: %s returned unparseable slots_json %r",
            request.verb_iri, (filled.slots_json or "")[:200],
        )
        return FillSlotsResponse(confidence=filled.confidence,
                                 reasoning="model returned unparseable slots")
    if not isinstance(raw, dict):
        return FillSlotsResponse(confidence=filled.confidence,
                                 reasoning="model returned a non-object")

    # ACCEPTANCE, here as well as at the supervisor. Not redundant: this is the layer
    # that can say WHICH name the model invented, and saying so is the point — the
    # finding this endpoint closes was a parameter vanishing without a word anywhere.
    accepted: dict[str, Any] = {}
    refused: list[str] = []
    for name, value in raw.items():
        decl = by_name.get(name)
        if decl is None:
            refused.append(f"{name} (not declared by {request.verb_iri})")
            continue
        values = decl.get("values")
        if values:
            offered = value if isinstance(value, list) else [value]
            if any(v not in values for v in offered):
                refused.append(f"{name}={value!r} (not one of {values})")
                continue
        declared_type = str(decl.get("type") or "")
        if declared_type.startswith(("list[", "set[", "tuple[")) and isinstance(value, str):
            # Refused, not coerced: wrapping as [value] is a guess, and the guess is
            # wrong the moment a speaker names two periods.
            refused.append(f"{name}={value!r} (needs {declared_type}, got a bare string)")
            continue
        accepted[name] = value

    if refused:
        _slots_logger.warning("fill_slots: %s refused %s", request.verb_iri, "; ".join(refused))

    # ── RESOLVE REFERENTS ────────────────────────────────────────────────────────
    # A slot declaring `referent` holds an opaque id, and a speaker says "the Aurora
    # site". The model has no way to know that is `S1`; `mesh:resolveInstance` does, and
    # has since before this endpoint existed — four providers, a fan-out and a scoring
    # gate. Engine P was simply not one of the providers until now.
    resolution: dict[str, Any] = {}
    for name in list(accepted):
        decl = by_name.get(name) or {}
        referent = decl.get("referent")
        if not referent:
            continue
        spoken_value = accepted[name]
        if not isinstance(spoken_value, str):
            continue

        _subject, prov = await _resolve_instance(spoken_value, request.query)
        outcome = str(prov.get("instance_match") or "empty")
        # ALL candidates, UNFILTERED, and deliberately so. The first draft filtered them
        # by the slot's referent class — which would have emptied the list for exactly the
        # case that most needs a menu: "the ERP Modernization project" resolves to an
        # Initiative, so a Project-filtered list is empty and the disambiguation ask has
        # nothing to offer. `resolveInstance` resolves but does not enumerate, so these
        # are the ONLY menu source that exists today; discarding them here would leave the
        # elicitation lane with none. The class rides on each candidate, so a consumer that
        # wants only same-class options can filter — a consumer cannot un-discard.
        cands = list(prov.get("instance_top_candidates") or [])
        # `decide()` only populates `instance_top_candidates` on the `mixed` branch — an
        # exact or fuzzy match reports the winner in flat provenance fields instead. So the
        # menu was empty in exactly the case that most needs one: "the ERP Modernization
        # project" resolves cleanly to I1 and is then type-rejected, and a disambiguation
        # ask offering nothing is an elicitation with no options. Synthesised from the
        # winner so every non-empty outcome carries at least the candidate it found.
        if not cands and prov.get("instance_id"):
            cands = [{
                "instance_id": prov.get("instance_id"),
                "class_uri": _subject or "",
                "label": prov.get("instance_label", ""),
                "score": prov.get("instance_score", 0.0),
            }]

        # TYPE-CHECKED AGAINST THE SLOT'S DECLARED CLASS. A name can resolve perfectly and
        # still be the wrong KIND of thing: "the ERP Modernization project" resolves to
        # initiative I1, and `project_id` wants a Project. Filling it would be a resolution
        # success and a dispatch failure — the worst combination, because everything
        # upstream looks healthy.
        resolved_id = prov.get("instance_id") if prov.get("instance_resolved") else None
        resolved_class = prov.get("instance_class_uri") or _subject
        if resolved_id and referent and resolved_class and resolved_class != referent:
            _slots_logger.warning(
                "fill_slots: %s.%s resolved %r to %s, which is a %s and not a %s",
                request.verb_iri, name, spoken_value, resolved_id, resolved_class, referent,
            )
            resolved_id = None
            # EXTENDS the instance_match vocabulary rather than reusing a value that does
            # not mean this. `mixed` means candidates of DIFFERENT classes; here there is
            # one class and it is the wrong one. `not_specific` means the identifier was
            # too vague; this one was perfectly specific and named something real. Calling
            # either of those "wrong class" would make the vocabulary lie to keep its size.
            # Flagged to the elicitation lane as an addition, not smuggled in.
            outcome = "wrong_class"

        if resolved_id:
            accepted[name] = resolved_id
            resolution[name] = {"outcome": outcome, "spoken": spoken_value,
                                "instance_id": resolved_id,
                                "instance_label": prov.get("instance_label", ""),
                                "candidates": cands}
        else:
            # REMOVED, not left as the raw string. See FillSlotsResponse.resolution.
            accepted.pop(name, None)
            resolution[name] = {"outcome": outcome, "spoken": spoken_value,
                                "instance_id": None, "candidates": cands}
            refused.append(f"{name}={spoken_value!r} (unresolved: {outcome})")
            _slots_logger.warning(
                "fill_slots: %s.%s could not resolve %r (%s), %d candidate(s)",
                request.verb_iri, name, spoken_value, outcome, len(cands),
            )

    return FillSlotsResponse(
        slots=accepted,
        confidence=filled.confidence,
        reasoning=filled.reasoning,
        refused=refused,
        resolution=resolution,
    )


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
    """Return active ontology classes for the requested domain, FILTERED to what the
    caller may SEE (Topaz ``can_view`` — the sealed ontology-visibility gate).

    This is the SPO interview's authorized SUBJECT source (ADR-0029 Slice 2, design §7):
    the menu an author sees is bounded by their compartment grants, so the interview can
    only author over vocabulary the author can view (Ruling A — self-gating via threaded
    identity). It reuses ``_can_view_class`` EXACTLY like ``/resolve`` (same single decider,
    same rego), so the two seams cannot disagree. No-op when ``ENABLE_AGENTIC_AUTH`` is off
    (dark-launch), so plain discovery / UI-dropdown use is unchanged until the flag flips.

    Identity reaches this seam via ``ResolveRequest.user_email`` (threaded by the interview's
    ``authorized_subjects``); empty caller → ungranted → deny-by-default on compartmented
    classes when the gate is on. [[feedback_identity_reaches_enforcement_point]].
    """
    rows = await execute_sparql(_SPARQL_MAINTENANCE_CLASSES, domain=request.domain)
    results = []
    dropped = 0
    for row in rows:
        uri = row.get("cls")
        # Per-IRI can_view — same gate /resolve applies to the candidate pool.
        if not _can_view_class(request.user_email, uri):
            dropped += 1
            continue
        results.append({
            "uri": uri,
            "label": row.get("label"),
            "definition": row.get("definition"),
            "example": row.get("example"),
        })
    if dropped:
        logging.info(
            "/classes: %d class(es) hidden from %r by can_view (compartment gate)",
            dropped, request.user_email or "anonymous",
        )
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

# ---------------------------------------------------------------------------
# POST /operable_subjects — the CAPABILITY-GRAPH subject menu (ADR-0029 Slice 2,
# Decision D — docs/reference/slice-2-spo-interview.md §8). The INVERSE of
# /find_compatible_verbs: "which subjects have ANY verb?" instead of "which verbs
# for this subject?". This is the source for the SPO interview's OPERATION-subject
# question — the subjects the mesh can ACT on (OntologyClass nodes carrying >=1
# registered verb edge), domain-scoped + can_view-filtered. Distinct from /classes
# (the full ontology VOCABULARY, used for nameable roles like a human_await
# subject_ref / participant): /classes is what EXISTS, this is what's ACTIONABLE.
# Sourcing the operation menu HERE (not filtering /classes) means it GROWS
# automatically as verbs are registered on new classes — consumer-derives-from-
# producer, the same rule the graph-name fix taught.
# ---------------------------------------------------------------------------
class OperableSubjectsRequest(BaseModel):
    domain: str | None = None
    # Author's entitlement key (email) — same per-IRI can_view gate /classes and
    # /resolve apply. Empty → ungranted → deny-by-default on compartmented subjects
    # once ENABLE_AGENTIC_AUTH flips.
    user_email: str = ""


class OperableSubject(BaseModel):
    uri: str
    label: str | None = None


class OperableSubjectsResponse(BaseModel):
    subjects: list[OperableSubject] = Field(default_factory=list)
    count: int = 0
    domain: str | None = None


_OPERABLE_SUBJECTS_CYPHER = """
MATCH (s:OntologyClass)-[r]->()
WHERE r.iri IS NOT NULL
  AND ($domain IS NULL OR s.domain = $domain)
RETURN DISTINCT s.uri AS uri, s.label AS label
ORDER BY label
"""


@app.post("/operable_subjects", response_model=OperableSubjectsResponse)
async def operable_subjects(request: OperableSubjectsRequest) -> OperableSubjectsResponse:
    """The subjects an SPO workflow step can be built on — OntologyClass nodes that
    carry at least one registered verb edge — domain-scoped and can_view-filtered
    (Decision D). The interview offers THESE for the operation-subject question, so
    every offered subject leads to >=1 compatible verb (no 94%-dead-end menu)."""
    if not _NEO4J_DRIVER:
        raise HTTPException(status_code=503, detail="Neo4j driver not initialized.")

    def _run() -> list[dict]:
        with _NEO4J_DRIVER.session() as session:
            return [
                dict(r)
                for r in session.run(_OPERABLE_SUBJECTS_CYPHER, domain=request.domain)
            ]

    try:
        rows = await asyncio.to_thread(_run)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"operable_subjects query failed: {exc}") from exc

    out: list[OperableSubject] = []
    dropped = 0
    for row in rows:
        uri = row.get("uri")
        if not uri:
            continue
        # Same sealed ontology-visibility gate /resolve + /classes apply.
        if not _can_view_class(request.user_email, uri):
            dropped += 1
            continue
        out.append(OperableSubject(uri=uri, label=row.get("label")))
    if dropped:
        logging.info(
            "/operable_subjects: %d verb-bearing subject(s) hidden from %r by can_view",
            dropped, request.user_email or "anonymous",
        )
    return OperableSubjectsResponse(subjects=out, count=len(out), domain=request.domain)


# ---------------------------------------------------------------------------
# POST /resolve_instance — the pcn mesh:resolveInstance provider endpoint.
# engine-o self-hosts it (it owns the SUSTAINMENT_INSTANCES graph) and registers
# itself in the capability graph as a provider for SUSTAINMENT; the /resolve
# fan-out then discovers + calls it like any other provider. Registry-discovered,
# not hardcoded (ADR-0031). NB: engine-o is here both router AND a provider — a
# mild smell accepted because engine-o owns the Jena instances; if a dedicated
# sustainment engine appears, move this route to it and re-point the registration.
# ---------------------------------------------------------------------------
class ResolveInstanceRequest(BaseModel):
    identifier: str
    query: str = ""


@app.post("/resolve_instance")
async def resolve_instance(request: ResolveInstanceRequest) -> dict:
    """Resolve an identifier to pcn instance candidates (matcher: agent_fleet/ontology_service/
    sustainment_instance_provider.py). Contract matches _call_resolver's expectation: returns
    ``{candidates: [{instance_id, class_uri, label, score}]}``; an empty list is a first-class
    ABSTAIN. The async Jena fetch lives here; the matching is the pure, unit-tested core."""
    try:
        rows = await execute_sparql(_SUSTAINMENT_INSTANCES_QUERY, domain="SUSTAINMENT")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"pcn instance query failed: {exc}") from exc
    candidates = _resolve_sustainment_candidates(request.identifier, rows=rows)
    return {"candidates": candidates}


# ---------------------------------------------------------------------------
# Disposition state — the dispatch effect's graph write + the step-5 read query.
# State lives in SUSTAINMENT_INSTANCES (DECIDED: runtime state with the instances);
# the write is idempotent (delete-then-insert) so the two-write convergence can
# re-stamp safely, and the read rides the deployed read-union.
# ---------------------------------------------------------------------------
async def _execute_sparql_update(update: str) -> None:
    if not _JENA_UPDATE_ENDPOINT:
        raise HTTPException(status_code=503, detail="Jena update endpoint not configured")
    async with httpx.AsyncClient(timeout=5.0, auth=(_JENA_USERNAME, _JENA_PASSWORD), verify=False) as client:
        resp = await client.post(_JENA_UPDATE_ENDPOINT, data={"update": update})
        resp.raise_for_status()


class WriteItemStateRequest(BaseModel):
    subject_iri: str
    disposition_state: str
    disposition_ref: str
    # str = "" not Optional[str]: this module uses `from __future__ import annotations`, and Pydantic
    # v2 can't resolve `Optional` as a forward-ref (same reason list[str] is used over List[str], §657).
    proposed_by_ruleset: str = ""


@app.post("/write_item_state")
async def write_item_state(
    request: WriteItemStateRequest,
    caller=Depends(_transport_auth("engine-o")),
) -> dict:
    """Stamp disposition state onto a component node in SUSTAINMENT_INSTANCES — the dispatch effect's
    graph write. IDEMPOTENT: deletes any prior state for the subject then inserts, so the two-write
    convergence can re-stamp on resume without duplicating. subject_iri must be a controlled component
    IRI; values are escaped."""
    _require_capability(caller, CAP_WRITE_ITEM_STATE, "write_item_state")
    s = request.subject_iri
    if not s.startswith("http://internal/"):
        raise HTTPException(status_code=400, detail="subject_iri must be an internal component/notice IRI")
    update = _build_state_update(s, request.disposition_state, request.disposition_ref, request.proposed_by_ruleset)
    await _execute_sparql_update(update)
    return {"ok": True, "subject_iri": s, "disposition_state": request.disposition_state}


class WriteDecisionRecordRequest(BaseModel):
    """ADR-0034 Phase 1: one notice's decision record, appended to the domain's DECISIONS graph.

    GENERIC AT BIRTH: the route carries no domain name — `domain` selects the graph
    (`<DOMAIN>_DECISIONS`), exactly as it does for the instance graphs. A second domain
    emitting records needs no new surface."""
    record_id: str
    domain: str = "SUSTAINMENT"
    # The record as built by iagent's decision_record.build_decision_record — already
    # schema-validated there and re-validated at emit. Stored as one canonical JSON literal:
    # the record is EVIDENCE, and evidence is read back whole, never partially re-assembled
    # from triples that might have drifted. The indexed fields below are projections FOR
    # querying, not the record itself.
    canonical: str
    # Projections that make the corpus queryable by property — the shape every named consumer
    # has (promotion: "corrections across the last N records for format F"; the demotion
    # tripwire: a standing query over recent records). Indexing these is the whole reason the
    # store is the graph rather than a blob.
    format_fingerprint: str
    pipeline_version: str
    outcome: str
    admitted_by: str
    trust_rung: str
    # WHICH RECORDS THE CORPUS COUNTS. Indexed as its own triple, not left inside the
    # canonical blob: the whole point of the era flag is that promotion queries EXCLUDE the
    # commissioning period, and an exclusion that requires parsing a JSON literal in every row
    # is not a filter anyone will write. A declaration that cannot be queried is a comment.
    era: str = "commissioning"
    ruleset_ref: str
    trust_table_ref: str
    emitted_at_ms: int


_DECISION_NS = "http://internal/decision#"


def _decisions_graph(domain: str) -> str:
    """`<http://internal/{DOMAIN}_DECISIONS>` — a DEDICATED RUNTIME graph.

    NEVER a vocabulary graph and NEVER prime: decision records are non-reproducible runtime
    output with a different reproducibility class than the ontologies, and mixing producers of
    different reproducibility into one graph is what the collision incident wrote in blood.
    Separate graph, separate lifecycle, separate blast radius."""
    return f"http://internal/{(domain or 'SUSTAINMENT').strip().upper()}_DECISIONS"


@app.post("/write_decision_record")
async def write_decision_record(
    request: WriteDecisionRecordRequest,
    caller=Depends(_transport_auth("engine-o")),
) -> dict:
    """APPEND a decision record. Append-only, with IMMUTABILITY ENFORCED HERE at the writer.

    A record already present is REFUSED (409), never overwritten. Corrections JOIN to a record;
    they do not rewrite it — an audit trail that can be edited in place is not one, and the
    whole point of the corpus is that a promotion decision can be re-examined against what was
    actually recorded at the time. Convention is not enough for this: "append-only by
    convention" is a comment, and a comment is not a gate, so the refusal is executable.

    Idempotent-safe for the caller: a re-emitted IDENTICAL record returns ok with
    `already_present`, so a retry after a transport failure is not an error — only a DIFFERENT
    record under an existing id is a conflict."""
    _require_capability(caller, CAP_WRITE_DECISION_RECORD, "write_decision_record")
    rid = (request.record_id or "").strip()
    if not rid or not rid.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="record_id must be a simple slug")
    graph = _decisions_graph(request.domain)
    subject = f"{_DECISION_NS}{rid}"

    exists = await _run_ask(
        f"ASK {{ GRAPH <{graph}> {{ <{subject}> ?p ?o }} }}"
    )
    if exists:
        same = await _run_ask(
            f"ASK {{ GRAPH <{graph}> {{ <{subject}> <{_DECISION_NS}canonical> "
            f'"{_sparql_lit(request.canonical)}" }} }}'
        )
        if same:
            return {"ok": True, "record_id": rid, "status": "already_present", "graph": graph}
        raise HTTPException(status_code=409, detail={
            "error": "decision_record_immutable",
            "record_id": rid,
            "message": "a DIFFERENT record already exists under this id — records are "
                       "append-only; corrections join, they do not overwrite",
        })

    def lit(v):
        return f'"{_sparql_lit(str(v))}"'

    triples = "\n".join([
        f"<{subject}> a <{_DECISION_NS}DecisionRecord> .",
        f"<{subject}> <{_DECISION_NS}canonical> {lit(request.canonical)} .",
        f"<{subject}> <{_DECISION_NS}formatFingerprint> {lit(request.format_fingerprint)} .",
        f"<{subject}> <{_DECISION_NS}pipelineVersion> {lit(request.pipeline_version)} .",
        f"<{subject}> <{_DECISION_NS}outcome> {lit(request.outcome)} .",
        f"<{subject}> <{_DECISION_NS}admittedBy> {lit(request.admitted_by)} .",
        f"<{subject}> <{_DECISION_NS}trustRung> {lit(request.trust_rung)} .",
        f"<{subject}> <{_DECISION_NS}era> {lit(request.era)} .",
        f"<{subject}> <{_DECISION_NS}rulesetRef> {lit(request.ruleset_ref)} .",
        f"<{subject}> <{_DECISION_NS}trustTableRef> {lit(request.trust_table_ref)} .",
        f"<{subject}> <{_DECISION_NS}emittedAtMs> {lit(request.emitted_at_ms)} .",
    ])
    await _execute_sparql_update(f"INSERT DATA {{ GRAPH <{graph}> {{\n{triples}\n}} }}")
    return {"ok": True, "record_id": rid, "status": "appended", "graph": graph}


class InstancesByPropertyRequest(BaseModel):
    disposition_state: str
    domain: str = "SUSTAINMENT"


@app.post("/instances_by_property")
async def instances_by_property(request: InstancesByPropertyRequest) -> dict:
    """Step-5 query: all parts in a disposition state, via the read-union (which spans
    SUSTAINMENT_INSTANCES) — the disposition dashboard's source. No dashboard store; the UI queries
    the same graph the policy lives in."""
    query = _build_parts_query(request.disposition_state)
    rows = await execute_sparql(query, domain=request.domain)
    return {"disposition_state": request.disposition_state, "parts": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# POST /policy_rules — GENERIC policy-rules reader (born generic per the birth rule).
# engine-o is a thin typed-triples WINDOW onto a named graph: it CONSTRUCTs the rule
# subgraph and returns Turtle (types intact — CONSTRUCT, not SELECT, because the SELECT
# path stringifies RDF terms and `bool("false")` is truthy). It makes NO rules-judgment:
# whether the graph holds valid rules, an empty ruleset, or garbage is the CONSUMER's call
# (restate_analyst's loader/validator, which is the only thing that interprets rulesets).
# Raw /policy_rules Turtle is NOT a rules API — consumers go through the loader/validator.
# ---------------------------------------------------------------------------
async def _run_construct_turtle(query: str) -> str:
    if not _JENA_ENDPOINT:
        raise HTTPException(status_code=503, detail="Jena query endpoint not configured")
    async with httpx.AsyncClient(timeout=5.0, auth=(_JENA_USERNAME, _JENA_PASSWORD), verify=False) as client:
        resp = await client.post(_JENA_ENDPOINT, data={"query": query}, headers={"Accept": "text/turtle"})
        resp.raise_for_status()
        return resp.text


async def _run_ask(query: str) -> bool:
    if not _JENA_ENDPOINT:
        raise HTTPException(status_code=503, detail="Jena query endpoint not configured")
    async with httpx.AsyncClient(timeout=5.0, auth=(_JENA_USERNAME, _JENA_PASSWORD), verify=False) as client:
        resp = await client.post(_JENA_ENDPOINT, data={"query": query},
                                 headers={"Accept": "application/sparql-results+json"})
        resp.raise_for_status()
        return bool(resp.json().get("boolean", False))


# Rule vocabulary config (v1: the one ingested ruleset). This is DATA/config, not surface — the route
# name is domain-free; when a second policy vocabulary lands it becomes a request parameter (the vocab
# is already a parameter of the pure builders). Sorted for M2 in docs/plans/pcn-extraction-sort.md.
_RULE_TYPE_IRI = os.getenv("POLICY_RULE_TYPE_IRI", "http://internal/sustainment/pcn#DispositionRule")
_CHANGE_CLASS_PRED = os.getenv("POLICY_CHANGE_CLASS_PRED", "http://internal/sustainment/pcn#changeClass")


class PolicyRulesRequest(BaseModel):
    graph: str                       # the named graph / domain to read (e.g. "SUSTAINMENT")
    ruleset_label: str = ""          # advisory (v1: one ruleset per graph); echoed for traceability


@app.post("/policy_rules")
async def policy_rules(request: PolicyRulesRequest) -> dict:
    """Return the rule subgraph of a named graph as Turtle, plus whether the graph holds any triples.
    engine-o interprets NOTHING: the consumer (restate_analyst's loader+validator) parses the Turtle,
    loads the ruleset, and decides not_found / empty / invalid / ok. Turtle preserves RDF term types so
    boolean rule conditions survive (a SELECT would not)."""
    construct = build_rules_construct(request.graph, rule_type_iri=_RULE_TYPE_IRI, change_class_pred=_CHANGE_CLASS_PRED)
    turtle = await _run_construct_turtle(construct)
    graph_nonempty = await _run_ask(build_graph_probe_ask(request.graph))
    return {"turtle": turtle, "graph_nonempty": graph_nonempty,
            "graph": request.graph, "ruleset_label": request.ruleset_label}


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
    """One candidate verb from the compat walk.

    A FIELD HERE IS THE SIXTH OF SEVEN SITES a registration property must be named at,
    and the Cypher RETURN (5) and the constructor below (7) are the neighbours most often
    forgotten with it. See
    docs/plans/a-registration-property-must-be-enumerated-seven-times.md.
    """
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
    # WHAT THE VERB TAKES — the same family as `arity` and `required_args` below: a
    # DECLARED fact asserted at registration and never inferred. Carried as the JSON
    # STRING the graph holds, because a Neo4j property cannot hold a list of maps;
    # decoded by the supervisor through slot_acceptance.decode_declarations.
    #
    # DEFAULTED so an unregistered or older verb is unchanged, and "[]" is what the
    # guard reads as declare-nothing-accept-nothing.
    #
    # This model is the SIXTH place in the chain that enumerates properties by name, and
    # every earlier one dropped the key in silence when it was not listed. A field
    # missing here is indistinguishable from a verb that declares nothing.
    slots: str = "[]"
    # ARITY (query-shape eligibility, ADR-0008 follow-up). A DECLARED fact
    # about the verb's input cardinality: "set" (operates on the collection
    # — enumerateCatalog), "single" (operates on one asset — describeAsset),
    # or "any"/null (neutral). Asserted at registration, NEVER inferred from
    # definition prose. The supervisor gates verb eligibility on
    # (query-arity from instance_resolved) so a set-query never resolves to
    # a single-asset verb. null → treated as "any" (never excluded).
    arity: str | None = None
    # ARGUMENT-FIT (eligibility intersection's 4th term). DECLARED argument
    # keys the verb cannot run without (e.g. ["tag"]); the supervisor drops the
    # verb for a query that cannot supply them. Asserted at registration, never
    # inferred. Empty/absent → unconstrained (never excluded — like null arity).
    required_args: list[str] = Field(default_factory=list)


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
    r.required_args               AS required_args,
    // WHAT THE VERB TAKES. A JSON STRING (a Neo4j property cannot hold a list of maps),
    // decoded by the supervisor via iagent_pure.slot_acceptance.decode_declarations.
    //
    // COMMENT SYNTAX IS `//`, NOT `--`. The first version of this block used SQL-style
    // `--`; Neo4j rejected the ENTIRE query with a SyntaxError and /find_compatible_verbs
    // returned 500 — routing down, from a comment. Verified on the live graph:
    // `RETURN 1 -- c` raises CypherSyntaxError, `RETURN 1 // c` returns normally.
    //
    // THE FIFTH ENUMERATION IN THIS CHAIN, and every earlier one dropped a key in
    // silence: the doc-tools allowlist (retired), the registrar's rel_props builder,
    // the registration manifest, the DataHub custom props, and now this RETURN. A
    // property that exists on the relationship still reaches nobody unless it is named
    // HERE, and the failure looks exactly like "the verb declared nothing".
    coalesce(r.slots, '[]')       AS slots,
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
        # required_args: robust to native list (Neo4j array) OR comma-joined
        # string (some registrars serialize lists as CSV for parity).
        _raw_req = row.get("required_args")
        if isinstance(_raw_req, str):
            verb_required_args = [a.strip() for a in _raw_req.split(",") if a.strip()]
        else:
            verb_required_args = [str(a).strip() for a in (_raw_req or []) if str(a).strip()]
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
            required_args=verb_required_args,
            # THE SEVENTH AND LAST ENUMERATION on this key's journey. The Cypher must
            # RETURN it, the model must declare it, and this constructor must pass it —
            # miss any one and the verb reports declaring nothing, with no error anywhere.
            slots=str(row.get("slots") or "[]"),
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
    # REFUSAL IS A FIRST-CLASS LINEUP MEMBER, and it needs the same kind of
    # discriminating text every other option gets. Measured 2026-08-23: "what is
    # the ROI on ERP Modernization" flipped between UNKNOWN and a plausible-
    # looking verb (planDiff, "effects of a scenario against a baseline"),
    # STABLE-refusing on a cold call and STABLE-choosing planDiff across five
    # rapid ones. A near-tie, and it was near-tied because UNKNOWN said only
    # "nothing fits" while its rivals described what they compute.
    #
    # An option that cannot say what it OWNS loses to any option that can.
    #
    # Stated domain-neutrally on purpose: this enum serves every domain, so the
    # rule is the CLASS of question ("a quantity this system does not compute"),
    # never one domain's vocabulary list. The examples are illustrative of the
    # class, not an enumeration to be matched.
    tb.Predicate.add_value("UNKNOWN").description(
        "No registered predicate in the candidate set is a sensible fit "
        "for this query given the resolved subject. Use this when every "
        "candidate would be the wrong substrate or wrong intent. "
        "USE THIS ESPECIALLY when the question asks for a QUANTITY OR JUDGEMENT "
        "THIS SYSTEM DOES NOT COMPUTE, even though it names real entities and "
        "sounds like it belongs — return on investment, payback, NPV, valuation, "
        "benefit, headcount or staffing, risk ownership. Naming a real subject "
        "does not make a question answerable: a candidate that merely operates on "
        "the same subject is the WRONG ANSWER, not the nearest one. Prefer this "
        "over a verb whose output would not actually answer what was asked."
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
