"""mesh-registrar — Contract D enforcement at registration time.

Per the deferred build plan in ``c:/tmp/plans/mesh_registrar_gateway.md``,
this service is the architecturally-correct registration mechanism for the
mesh: it accepts a tiny manifest from each engine, validates
``input_uri``/``output_uri`` against Neo4j (ADR-0019 Contract D), then
emits the DataHub MetadataChangeProposal that the doc-tools sensor
materializes into the predicate graph. The agent doesn't ship
``acryl-datahub``; this gateway does, once.

The standing guards in ``tests/routing/test_substrate_invariants.py``
catch Contract D regressions at CI time — that's the second-best version
of what this service does. The real revisit-trigger for shipping the
gateway was "non-CI registrants" (third-party engines, manual ops,
dynamic registration). Tonight ships the architecture; engines migrate
to it incrementally.

Companion components:
  - iagent-mesh-sdk/iagent_mesh/core.py: replaces ``_emit_to_datahub``
    with ``_emit_to_registrar`` (thin HTTP POST to this service).
  - helm/invincible-agent/templates/mesh-registrar.yaml: Deployment +
    Service + ConfigMap.
  - tests/routing/test_substrate_invariants.py: invariants stay; they
    cover regressions that slip past the gateway.

This first version focuses on Contract D enforcement + DataHub emit
+ idempotency. Contract C dual-store verification (wait for Neo4j +
Weaviate Predicate to confirm) and audit-log persistence to Postgres
are stubbed for a v0.2 follow-up.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from neo4j import GraphDatabase
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://iagent-neo4j:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "changeme-neo4j-sandbox")

DATAHUB_GMS_URL = os.environ.get("DATAHUB_GMS_URL", "http://datahub-datahub-gms:8080")
DATAHUB_TOKEN = os.environ.get("DATAHUB_TOKEN", "")

REGISTRAR_VERSION = "0.1.0"

logger = logging.getLogger("mesh-registrar")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="mesh-registrar",
    description="Contract D registration gateway for the agentic data mesh.",
    version=REGISTRAR_VERSION,
)

# Lazy-init the Neo4j driver so /health works even when Neo4j is briefly
# unreachable. /v1/register requires it.
_NEO4J_DRIVER: Optional[Any] = None


def _get_neo4j_driver():
    global _NEO4J_DRIVER
    if _NEO4J_DRIVER is None:
        _NEO4J_DRIVER = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
        )
    return _NEO4J_DRIVER


# ---------------------------------------------------------------------------
# Manifest model
# ---------------------------------------------------------------------------

class RegistrationManifest(BaseModel):
    """The body engines POST to ``/v1/register``.

    Mirrors the doc-tools sensor's `mlModel.customProperties` shape so the
    gateway can emit the DataHub MCP without the engine knowing DataHub
    exists.
    """

    name: str = Field(
        description="Stable engine+verb identifier — e.g. 'engine_e_neo4j_expert'. "
                    "Used to derive the DataHub tool_urn; idempotent on this field."
    )
    verb_iri: str = Field(
        description="The verb's canonical IRI — e.g. 'mesh:queryKnowledgeGraph' "
                    "or 'http://invincible-agent/mesh#queryKnowledgeGraph'."
    )
    input_uri: str = Field(
        description="OntologyClass URI for the verb's input. MUST resolve to an "
                    "existing :OntologyClass node in Neo4j (Contract D)."
    )
    output_uri: str = Field(
        description="OntologyClass URI for the verb's output. MUST resolve to an "
                    "existing :OntologyClass node in Neo4j (Contract D)."
    )
    endpoint_url: str = Field(
        description="Engine's HTTP endpoint that serves this verb."
    )
    owner_persona: str = Field(
        description="Persona for routing decisions — e.g. 'AUDITOR', 'TECH_WRITER'."
    )
    domains: list[str] = Field(
        default_factory=list,
        description="Routable domains this verb applies to — e.g. ['MAINTENANCE']."
    )
    description: Optional[str] = Field(
        default=None, description="Short verb description for hybrid search."
    )
    verb_synonyms: list[str] = Field(default_factory=list)
    verb_anti_synonyms: list[str] = Field(default_factory=list)
    cost_class: str = Field(default="medium")
    requires_human_approval: bool = Field(default=False)
    version: str = Field(default="0.1.0")
    openapi_schema: Optional[str] = Field(default=None)
    # Symbolic provider name used by the router's provenance — e.g.
    # 'engine_d' or 'engine_e'. The field exists so /resolve's
    # provenance can answer "which phone book said this?" with the
    # registration's identity instead of the verb's relationship-type
    # (which is what coalesce(r.provider, type(r)) was falling back to
    # before this field landed — and which would make every override
    # say provider=resolveInstance regardless of source the moment a
    # second provider joins). When omitted, the gateway derives it
    # from `name` by stripping the trailing snake_case verb local
    # name (e.g. 'engine_d_resolve_instance' → 'engine_d').
    provider: Optional[str] = Field(
        default=None,
        description=(
            "Symbolic provider name shown in /resolve provenance "
            "(e.g. 'engine_d'). Auto-derived from `name` if omitted."
        ),
    )
    # Per-provider fan-out timeout budget in seconds, advertised to the
    # router so providers can declare their own SLO instead of inheriting
    # the slowest provider's ceiling. Engine D (DataHub GraphQL) is
    # multi-second; Engine E (Neo4j Cypher) is sub-second. When omitted,
    # the router uses its global default (INSTANCE_RESOLVER_TIMEOUT_S).
    timeout_s: Optional[float] = Field(
        default=None,
        description=(
            "Provider-declared fan-out budget in seconds. Defaults to "
            "Engine O's INSTANCE_RESOLVER_TIMEOUT_S when omitted."
        ),
    )

    @field_validator("verb_iri", "input_uri", "output_uri")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v.strip()


class RegistrationResult(BaseModel):
    status: str = Field(description="'registered', 'updated', or 'rejected'.")
    tool_urn: str
    contract_d_check: dict
    datahub_response: Optional[dict] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Contract D — validate input/output URIs resolve to real OntologyClass nodes
# ---------------------------------------------------------------------------

def _derive_provider(name: str, verb_iri: str) -> str:
    """Derive a symbolic provider name from a registration ``name`` by
    stripping the verb's snake_case local-name suffix.

    Examples:
      ('engine_d_resolve_instance',  'mesh:resolveInstance') -> 'engine_d'
      ('engine_e_neo4j_expert',       'mesh:queryKnowledgeGraph') -> 'engine_e_neo4j_expert'
      ('engine_a_lookup_ownership',   'mesh:lookupOwnership')    -> 'engine_a'

    Falls back to ``name`` unchanged when the suffix doesn't match — at
    worst the provenance shows the full registration name, which is
    still more diagnostic than the relationship-type fallback the
    discovery Cypher would otherwise hit.
    """
    import re

    if ":" in verb_iri:
        verb_local = verb_iri.split(":", 1)[1]
    else:
        verb_local = verb_iri.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    # camelCase → snake_case
    verb_snake = re.sub(r"(?<!^)(?=[A-Z])", "_", verb_local).lower()
    suffix = f"_{verb_snake}"
    if name.endswith(suffix):
        return name[: -len(suffix)] or name
    return name


def _contract_d_check(input_uri: str, output_uri: str) -> dict:
    """Verify both URIs exist as :OntologyClass nodes in Neo4j.

    Returns ``{"ok": bool, "missing": [..], "checked": [..]}``.
    """
    driver = _get_neo4j_driver()
    with driver.session() as session:
        rec = session.run(
            """
            UNWIND $uris AS uri
            WITH uri WHERE NOT EXISTS { MATCH (:OntologyClass {uri: uri}) }
            RETURN collect(uri) AS missing
            """,
            uris=[input_uri, output_uri],
        ).single()
    missing = rec["missing"] if rec else [input_uri, output_uri]
    return {
        "ok": not missing,
        "missing": missing,
        "checked": [input_uri, output_uri],
    }


# ---------------------------------------------------------------------------
# DataHub MCP emission
# ---------------------------------------------------------------------------

def _emit_to_datahub(manifest: RegistrationManifest, tool_urn: str) -> dict:
    """Build + emit the MetadataChangeProposalWrapper for this registration.

    Lazy-imported so the rest of the service starts even if acryl-datahub
    is mis-configured (only /v1/register exercises the path).
    """
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.emitter.rest_emitter import DatahubRestEmitter
    from datahub.metadata.schema_classes import MLModelPropertiesClass

    # IMPORTANT: keys MUST use the ``mesh_`` prefix to match the
    # doc-tools aitool sensor's expected property names — it reads
    # ``mesh_verb_iri`` / ``mesh_input_uri`` / ``mesh_output_uri`` and
    # rejects with ``incomplete`` props otherwise. Bare names without the
    # prefix were the first real gateway↔sensor protocol bug, discovered
    # when engine-d/e/w opted in and silently failed materialization.
    # Mirror exactly the legacy direct-emit path in
    # ``agent_fleet/utils/mesh_registration.py``.
    provider = manifest.provider or _derive_provider(manifest.name, manifest.verb_iri)
    custom_props = {
        "mesh_is_registration":         "true",
        "mesh_verb_iri":                manifest.verb_iri,
        "mesh_input_uri":               manifest.input_uri,
        "mesh_output_uri":              manifest.output_uri,
        "mesh_endpoint_url":            manifest.endpoint_url,
        "mesh_owner_persona":           manifest.owner_persona,
        "mesh_domains":                 ",".join(manifest.domains),
        "mesh_cost_class":              manifest.cost_class,
        "mesh_requires_human_approval": str(manifest.requires_human_approval).lower(),
        "mesh_verb_synonyms":           ",".join(manifest.verb_synonyms),
        "mesh_verb_anti_synonyms":      ",".join(manifest.verb_anti_synonyms),
        "mesh_version":                 manifest.version,
        "mesh_registrar_version":       REGISTRAR_VERSION,
        "mesh_provider":                provider,
    }
    if manifest.timeout_s is not None:
        custom_props["mesh_timeout_s"] = str(manifest.timeout_s)
    if manifest.openapi_schema:
        custom_props["mesh_openapi_schema"] = manifest.openapi_schema

    props = MLModelPropertiesClass(
        description=manifest.description or "",
        customProperties=custom_props,
    )
    mcp = MetadataChangeProposalWrapper(
        entityType="mlModel",
        entityUrn=tool_urn,
        aspectName="mlModelProperties",
        aspect=props,
        changeType="UPSERT",
    )

    emitter = DatahubRestEmitter(
        gms_server=DATAHUB_GMS_URL,
        token=DATAHUB_TOKEN if DATAHUB_TOKEN else None,
    )
    emitter.emit(mcp)
    return {"tool_urn": tool_urn, "aspect": "mlModelProperties", "ok": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Liveness + DB-reachability check."""
    db_ok = False
    db_error = None
    try:
        driver = _get_neo4j_driver()
        driver.verify_connectivity()
        db_ok = True
    except Exception as e:
        db_error = str(e)[:200]
    return {
        "status": "ok",
        "neo4j_reachable": db_ok,
        "neo4j_error": db_error,
        "version": REGISTRAR_VERSION,
    }


@app.post("/v1/register", response_model=RegistrationResult)
def register(manifest: RegistrationManifest) -> RegistrationResult:
    """Register a verb in the mesh.

    Steps:
      1. Contract D validation — input/output URIs exist as :OntologyClass
         nodes in Neo4j. **If not, reject with 422** (the gateway's central
         purpose vs the SDK shipping its own validation).
      2. Derive the DataHub tool_urn from manifest.name.
      3. Emit the MCP to DataHub. doc-tools' aitool_registration_sensor
         materializes it into the Neo4j predicate edge + Weaviate
         Predicate collection on its next tick (sub-30s).
      4. Return the result. v0.1 doesn't wait for Contract C
         dual-store verification — that's v0.2 + a webhook from the
         sensor.
    """
    tool_urn = (
        f"urn:li:mlModel:(urn:li:dataPlatform:mesh,{manifest.name},PROD)"
    )

    # Step 1: Contract D
    cd = _contract_d_check(manifest.input_uri, manifest.output_uri)
    if not cd["ok"]:
        logger.warning(
            "Contract D rejection for %s: missing %s", tool_urn, cd["missing"]
        )
        # 422 Unprocessable Entity — the manifest is syntactically valid
        # but the URIs it references don't exist in the substrate.
        raise HTTPException(
            status_code=422,
            detail={
                "status": "rejected",
                "tool_urn": tool_urn,
                "contract_d_check": cd,
                "reason": (
                    "input_uri and/or output_uri don't resolve to any "
                    ":OntologyClass node in Neo4j. Run the canonical "
                    "ontology ingest before registering."
                ),
            },
        )

    # Step 2 + 3: emit
    try:
        datahub_resp = _emit_to_datahub(manifest, tool_urn)
    except Exception as e:
        logger.exception("DataHub emit failed for %s", tool_urn)
        raise HTTPException(
            status_code=502,
            detail={
                "status": "rejected",
                "tool_urn": tool_urn,
                "contract_d_check": cd,
                "reason": f"DataHub emit failed: {type(e).__name__}: {str(e)[:200]}",
            },
        )

    logger.info("Registered %s (verb=%s)", tool_urn, manifest.verb_iri)
    return RegistrationResult(
        status="registered",
        tool_urn=tool_urn,
        contract_d_check=cd,
        datahub_response=datahub_resp,
    )


@app.get("/v1/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": REGISTRAR_VERSION}
