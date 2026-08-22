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

import json
import logging
import os
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from neo4j import GraphDatabase
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://iagent-neo4j:7687")
NEO4J_USERNAME = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "changeme-neo4j-sandbox")

# Normalize the (overloaded) DATAHUB_GMS_URL for the REST emitter — the
# SAME shape collision fixed in the engines' direct-emit fallback: the
# shared agentFleet.env value is the GraphQL form (…/api/graphql, which
# the GraphQL readers need verbatim) while DatahubRestEmitter wants the
# bare GMS base and appends /aspects. Unnormalized, every governance
# emit 404'd at /api/graphql/aspects — fail-soft (saga already
# succeeded, routing unaffected) but the DataHub record never landed.
# One definition of the normalizer, imported with the same in-image/
# repo-root duality as utils.embed in v2_substrate.
try:
    from utils.mesh_registration import _gms_server_base
except ImportError:
    from agent_fleet.utils.mesh_registration import _gms_server_base

DATAHUB_GMS_URL = _gms_server_base(
    os.environ.get("DATAHUB_GMS_URL", "http://datahub-datahub-gms:8080")
)
DATAHUB_TOKEN = os.environ.get("DATAHUB_TOKEN", "")

REGISTRAR_VERSION = "0.1.0"

logger = logging.getLogger("mesh-registrar")
logging.basicConfig(level=logging.INFO)

from fastapi import Depends
# TRANSPORT AUTH (OBSERVE). One implementation, from the mesh membership package: validate
# whatever arrives, log the caller posture per request, REFUSE NOTHING until
# REQUIRE_TRANSPORT_AUTH flips. The announcement is the pre-positioned string the contract
# phase's fresh-deploy test asserts against — an engine that takes the dependency but loses
# the announcement has a real posture the gauge cannot read.
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import app_docs_kwargs as _docs_kwargs
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth
_announce_transport_auth(component="mesh-registrar")
app = FastAPI(
    **_docs_kwargs(),  # /docs,/redoc,/openapi.json OFF in deployment (Starlette-bypass class)
    dependencies=[Depends(_transport_auth("mesh-registrar"))],
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
    # Defaulted to "" so a PRESENTATION may omit them -- it supplies the triple
    # form instead and the model validator normalises it onto these three. The
    # validator still REQUIRES all three for tool_kind='Engine', so the default
    # is not a relaxation of engine validation: omit them on an engine and the
    # registration is refused with a named reason.
    verb_iri: str = Field(
        default="",
        description="The verb's canonical IRI — e.g. 'mesh:queryKnowledgeGraph' "
                    "or 'http://invincible-agent/mesh#queryKnowledgeGraph'. "
                    "Engine only; presentations supply predicate_iri."
    )
    input_uri: str = Field(
        default="",
        description="OntologyClass URI for the verb's input. MUST resolve to an "
                    "existing :OntologyClass node in Neo4j (Contract D). "
                    "Engine only; presentations supply subject_uri."
    )
    output_uri: str = Field(
        default="",
        description="OntologyClass URI for the verb's output. MUST resolve to an "
                    "existing :OntologyClass node in Neo4j (Contract D). "
                    "Engine only; presentations supply object_uri."
    )
    endpoint_url: Optional[str] = Field(
        default=None,
        description="Engine's HTTP endpoint that serves this verb. REQUIRED for "
                    "tool_kind='Engine'; MUST BE ABSENT for 'Presentation'."
    )

    # ── SECOND SPECIES: presentations are triples, not verb edges ────────────
    # Per ADR-0017 a presentation advertises (subject, mesh:rendersAs, archetype).
    # Before this, the manifest modelled verb edges only, so presentations could
    # not go through the gateway at all -- they emitted direct-to-DataHub while
    # the DataHub->Weaviate materialiser was RETIRED (ADR-0006 Addendum), making
    # those emissions audit records that reached nothing. Measured 2026-08-21:
    # 11 presentation URNs in DataHub, 0 rendersAs rows in Weaviate.
    #
    # `tool_kind` DEFAULTS to "Engine" so every existing caller is byte-identical
    # -- no engine manifest changes, no version negotiation, no coordinated deploy.
    tool_kind: Literal["Engine", "Presentation"] = Field(
        default="Engine",
        description="Registration species. 'Engine' = verb edge (reached by "
                    "CALLING endpoint_url). 'Presentation' = rendersAs triple "
                    "(reached by REPLYING, identified by frontend_id).",
    )
    frontend_id: Optional[str] = Field(
        default=None,
        description="Which frontend advertises this presentation (e.g. 'cortex', "
                    "'openddil'). The reached-by-REPLYING counterpart of "
                    "endpoint_url. REQUIRED for tool_kind='Presentation'.",
    )
    subject_uri: Optional[str] = Field(
        default=None,
        description="Presentation only: the output-shape IRI this renders. FULL "
                    "form. Contract-D checked as the edge's input side.",
    )
    predicate_iri: Optional[str] = Field(
        default=None,
        description="Presentation only: constant 'mesh:rendersAs' (ADR-0017). "
                    "COMPACT form -- see the per-position convention below.",
    )
    object_uri: Optional[str] = Field(
        default=None,
        description="Presentation only: the archetype class IRI. FULL form. "
                    "Contract-D checked as the edge's output side.",
    )
    archetype: Optional[str] = Field(
        default=None,
        description="Presentation only: BAML archetype enum string, e.g. "
                    "'KNOWLEDGE_DOCUMENT'.",
    )
    expected_fields: list[str] = Field(
        default_factory=list,
        description="Presentation only: fields the archetype expects in "
                    "structured_data.",
    )
    recomputes: Optional[bool] = Field(
        default=None,
        description="Presentation only: does this view RECOMPUTE against moving "
                    "state? (ADR-0042 Ruling 9.) Tri-state ON PURPOSE — None "
                    "means the component never declared it and is NOT read as "
                    "live. False-by-default and live-by-accident are both lies "
                    "about a component nobody asked. Matches _is_live_view() in "
                    "capability_registry.py (ab0bcfd), which must keep the same "
                    "default or the ruling means different things at each end.",
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
    # ADR argument-fit: argument KEYS this verb cannot run without (e.g.
    # ["tag"] for a filterByTag). The eligibility intersection's argument-fit
    # term drops the verb for a query that cannot supply these. Empty (default)
    # = unconstrained → never excluded (conservative, like a null `arity`). The
    # value→arg-key resolver (does the query supply arg X? — needs the arg's
    # vocabulary, e.g. DataHub tags) travels with the concrete verb, not here.
    required_args: list[str] = Field(default_factory=list)
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
        # Blank is permitted HERE only so presentations may omit these three;
        # the per-species model validator below rejects blanks for Engines. A
        # whitespace-only value is still normalised to "" rather than passed on.
        return (v or "").strip()

    @model_validator(mode="after")
    def _validate_species(self) -> "RegistrationManifest":
        """Per-species required fields, enforced at ADMISSION.

        The branch must not become a bypass: a Presentation missing its own
        fields is still rejected. That failure mode has already shipped once in
        this arc -- doc-tools' linker demanded verb-shaped fields of every row,
        so presentations were refused as "incomplete" at ERROR level with a
        remedy ("re-register") that could not work. A guard correct for its
        population and blind to a species it was never told about.

        Presentations are NORMALISED onto the verb-edge shape here, so Contract
        D, the saga, the Neo4j MERGE and the Weaviate upsert all run unchanged:
            subject_uri   -> input_uri
            predicate_iri -> verb_iri
            object_uri    -> output_uri

        IRI CONVENTION IS PER-POSITION and is INHERITED, not invented. Verified
        against the 24 live rows on 2026-08-21: the predicate/verb position is
        stored COMPACT ('mesh:rendersAs', 'mesh:queryKnowledgeGraph') while the
        subject/object positions are stored FULL
        ('http://invincible-agent/mesh#OwnershipFact'). Reading "compact = stale"
        and expanding the predicate would make presentations the only row type
        with a full verb_iri. No expansion happens here.
        """
        if self.tool_kind == "Presentation":
            missing = [
                f for f in ("subject_uri", "predicate_iri", "object_uri",
                            "archetype", "frontend_id")
                if not (getattr(self, f) or "").strip()
            ]
            if missing:
                raise ValueError(
                    f"tool_kind='Presentation' requires {missing}. A presentation "
                    f"missing its own fields is rejected, not waved through."
                )
            if self.endpoint_url:
                # REJECTED, not ignored. A presentation is not callable. Silently
                # accepting an endpoint would let a caller advertise one and
                # produce a row that dispatch might later try to invoke -- a
                # field nobody calls is a claim nobody audits.
                raise ValueError(
                    "tool_kind='Presentation' must NOT carry endpoint_url: a "
                    "presentation is reached by REPLYING (frontend_id), not by "
                    "calling. Use frontend_id."
                )
            # Normalise onto the verb-edge shape the write path already speaks.
            object.__setattr__(self, "verb_iri", self.predicate_iri.strip())
            object.__setattr__(self, "input_uri", self.subject_uri.strip())
            object.__setattr__(self, "output_uri", self.object_uri.strip())
        else:
            if not (self.endpoint_url or "").strip():
                raise ValueError(
                    "tool_kind='Engine' requires endpoint_url (the verb is "
                    "reached by CALLING it)."
                )
            for f in ("verb_iri", "input_uri", "output_uri"):
                if not (getattr(self, f) or "").strip():
                    raise ValueError(f"tool_kind='Engine' requires {f}.")
        return self


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


# The class whose presence means THE ONTOLOGY INGEST REACHED ITS TERMINAL STATE.
#
# "Is the class graph populated?" has three plausible definitions and only one is safe:
#
#   count(:OntologyClass) > 0   — WRONG. True the instant the FIRST class lands, so the
#                                 window just gets narrower: registrations arriving mid-ingest
#                                 are told the substrate is ready and get a permanent 422 for
#                                 a class that was three seconds from existing.
#   "all classes present"       — unknowable. The registrar cannot enumerate what the manifest
#                                 was supposed to produce; that set lives in prime_databases.py
#                                 and in whatever domain TTLs a given deployment adds.
#   a SENTINEL class            — RIGHT, and the pattern this codebase already uses. The
#                                 re-register hook waits on exactly this node for exactly this
#                                 reason (helm values: primeSubstrate.reregisterEngines.
#                                 sentinelUri). Presence means the ingest RAN TO COMPLETION,
#                                 not that it started.
#
# Keep this in step with the helm sentinel; they are answering the same question and a drift
# between them means the hook and the registrar disagree about when the substrate is ready.
# COMMA-SEPARATED, and EVERY entry must be present for the substrate to count as
# ready. A single sentinel proves only that ONE ontology landed: prime launches
# its ingests concurrently and out of order, so idp#Dataset (10th of 12) goes
# green while mesh_system (12th) is still QUEUED. Observed 2026-08-21 on the helm
# side, where the single-uri wait reported ready on its FIRST poll and the
# re-register job finished in 47s with the mesh ingest still queued.
_SUBSTRATE_SENTINEL_URI = os.getenv(
    "MESH_REGISTRAR_SUBSTRATE_SENTINEL",
    "http://invincible-agent/idp#Dataset,http://invincible-agent/mesh#ChartWidget",
)


def _contract_d_check(input_uri: str, output_uri: str) -> dict:
    """Verify both URIs exist as :OntologyClass nodes in Neo4j.

    Returns ``{"ok": bool, "missing": [..], "checked": [..], "substrate_ready": bool,
    "sentinel": str}``.

    ``substrate_ready`` is the DISCRIMINANT, and it exists because a bare "missing"
    answers two questions at once whose repairs are opposites:

      * the class graph is not populated YET (an engine booted ahead of the ontology
        ingest) — becomes true on its own, so the caller should RETRY;
      * these classes will NEVER exist (no TTL declares them) — a human must fix the
        ontology, so retrying is an infinite loop against a real defect.

    The ENGINE cannot tell these apart: from inside one rejection they are the same
    ``missing: [...]``. ADR-0006's addendum had to choose, and chose permanent — correct
    for the second case, and the reason a work cluster sat unrouted until someone
    restarted a pod by hand. The registrar CAN tell them apart, because it is the only
    party that sees both the requested URIs and the state of the graph. So it decides
    here and says which one it means in the status code (see the caller).

    Only probed when something is actually missing: the happy path keeps its single query.
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

        substrate_ready = True
        sentinels = [u.strip() for u in _SUBSTRATE_SENTINEL_URI.split(",") if u.strip()]
        if missing and sentinels:
            # ALL, not ANY. Answering "is the substrate ready" from one class is
            # what let the boot race survive a guard built specifically for it.
            srec = session.run(
                """
                UNWIND $sentinel_uris AS uri
                WITH uri WHERE NOT EXISTS { MATCH (:OntologyClass {uri: uri}) }
                RETURN collect(uri) AS absent
                """,
                sentinel_uris=sentinels,
            ).single()
            substrate_ready = not (srec["absent"] if srec else sentinels)

    return {
        "ok": not missing,
        "missing": missing,
        "checked": [input_uri, output_uri],
        # An EMPTY sentinel setting disables the discrimination and restores the
        # always-permanent behaviour — an announced escape hatch for a deployment whose
        # ontology legitimately has no idp layer, so it is never silently in force.
        "substrate_ready": substrate_ready,
        "sentinel": _SUBSTRATE_SENTINEL_URI,
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
    custom_props = _build_custom_properties(manifest)

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
        # WHICH MANIFEST SPECIES THIS BUILD ACCEPTS — a CHECKABLE FACT, so a
        # caller never has to infer capability from a rejection, and a
        # deploy-ordering fallback has an observable retirement condition
        # instead of a log line.
        #
        # The first version of engine-f's fallback keyed its retirement on
        # `kubectl logs | grep "VIA GATEWAY"`. That engine's logger was dropping
        # records, so the condition could never be observed even on success —
        # a condition that cannot be observed is not a condition. Reading it
        # from here cannot rot the same way: it is the server answering about
        # itself, and its absence is as meaningful as its content.
        "manifest_species": sorted(
            RegistrationManifest.model_fields["tool_kind"].annotation.__args__
        ),
    }



def _build_custom_properties(manifest: "RegistrationManifest") -> dict:
    """Build the DataHub ``customProperties`` bag for either species.

    Extracted so the two-species discrimination is testable without a DataHub,
    a Neo4j or a Weaviate. The alternative was two skipped tests, and a skipped
    arm proves nothing -- these cover the discriminator riding in the data and
    the popped endpoint, which are the design's load-bearing calls.
    """
    provider = manifest.provider or _derive_provider(manifest.name, manifest.verb_iri)
    custom_props = {
        "mesh_is_registration":         "true",
        "mesh_verb_iri":                manifest.verb_iri,
        "mesh_input_uri":               manifest.input_uri,
        "mesh_output_uri":              manifest.output_uri,
        "mesh_endpoint_url":            manifest.endpoint_url or "",
        "mesh_owner_persona":           manifest.owner_persona,
        "mesh_domains":                 ",".join(manifest.domains),
        "mesh_cost_class":              manifest.cost_class,
        "mesh_requires_human_approval": str(manifest.requires_human_approval).lower(),
        "mesh_verb_synonyms":           ",".join(manifest.verb_synonyms),
        "mesh_verb_anti_synonyms":      ",".join(manifest.verb_anti_synonyms),
        "mesh_required_args":           ",".join(manifest.required_args),
        "mesh_version":                 manifest.version,
        "mesh_registrar_version":       REGISTRAR_VERSION,
        "mesh_provider":                provider,
    }
    # THE DISCRIMINATOR RIDES IN THE DATA. `mesh_tool_kind` is written for BOTH
    # species so a consumer never has to infer the shape from which fields
    # happen to be present. On the doc-tools side this key already existed and
    # nothing branched on it -- declared but unwired -- which is exactly how
    # presentations got rejected as malformed engines for weeks.
    custom_props["mesh_tool_kind"] = manifest.tool_kind

    if manifest.tool_kind == "Presentation":
        # The SPO triple, under the same key names the legacy direct-emit path
        # in agent_fleet/utils/mesh_registration.py writes, so a row emitted by
        # the gateway is byte-comparable with one emitted before the gateway
        # learned this species.
        custom_props["mesh_subject_uri"] = manifest.subject_uri or ""
        custom_props["mesh_predicate_iri"] = manifest.predicate_iri or ""
        custom_props["mesh_object_uri"] = manifest.object_uri or ""
        custom_props["mesh_archetype"] = manifest.archetype or ""
        custom_props["mesh_expected_fields"] = json.dumps(list(manifest.expected_fields))
        custom_props["mesh_frontend_id"] = manifest.frontend_id or ""
        # A presentation is not callable; there is no endpoint to advertise.
        # Popped rather than left blank so no consumer can read "" as a URL.
        custom_props.pop("mesh_endpoint_url", None)

    if manifest.timeout_s is not None:
        custom_props["mesh_timeout_s"] = str(manifest.timeout_s)
    if manifest.openapi_schema:
        custom_props["mesh_openapi_schema"] = manifest.openapi_schema
    return custom_props

@app.post("/v1/register", response_model=RegistrationResult)
def register(manifest: RegistrationManifest) -> RegistrationResult:
    """Register a verb in the mesh (v0.2 atomic-saga path).

    Per ADR-0006 §Addendum (2026-06-13):

      1. Contract D validation — input/output URIs MUST exist as
         :OntologyClass nodes in Neo4j. Rejected with 422 if not.
      2. v0.2 saga: bounded forward-retry on Neo4j MERGE → Weaviate
         upsert → dual-store read-back probe. On exhausted retries,
         compensate (DELETE whatever wrote) and return 503 against
         clean substrate. The conjunctive-read invariant
         (``/classify_predicate`` only sees verbs present in BOTH
         stores) makes any benignly-orphan'd half-write unrouted;
         compensation failure logs loudly but doesn't fail-the-fail.
      3. DataHub MCP emit is governance history, queued out-of-band
         AFTER the saga succeeds. Emit failure does NOT block the 200
         (per the priors: substrate writes are the gate; DataHub is
         the audit log). A failed emit logs loudly and the gateway
         continues; a future reconciler closes the gap.
    """
    tool_urn = (
        f"urn:li:mlModel:(urn:li:dataPlatform:mesh,{manifest.name},PROD)"
    )

    # Step 1: Contract D (unchanged — read-only check, runs before any write).
    cd = _contract_d_check(manifest.input_uri, manifest.output_uri)
    if not cd["ok"]:
        # THE SUBSTRATE IS NOT READY — this is a TIMING fact, not a contract violation.
        # The sentinel is absent, so the ontology ingest has not reached its terminal
        # state and these classes may be seconds from existing. 503 rather than 422 puts
        # it on the SDK's existing retry ladder (>=500 -> bounded exponential backoff),
        # so an engine that booted ahead of the ingest heals itself instead of serving
        # unregistered until a human notices. Bounded, so a sentinel that never arrives
        # still ends at the same loud named alarm rather than looping forever.
        if not cd["substrate_ready"]:
            logger.warning(
                "Contract D DEFERRED for %s: missing %s, but sentinel %s is absent — "
                "the ontology ingest has not completed. Returning 503 (retryable): this "
                "is an ordering race, not a contract violation.",
                tool_urn, cd["missing"], cd["sentinel"],
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "deferred",
                    "tool_urn": tool_urn,
                    "contract_d_check": cd,
                    "reason": (
                        f"Ontology substrate not ready: sentinel {cd['sentinel']} is "
                        "absent, so the class graph is not yet populated to its terminal "
                        "state. The requested URIs may exist once the ingest completes — "
                        "this is RETRYABLE and is NOT a Contract D violation."
                    ),
                },
            )

        # The substrate IS ready and these URIs still do not resolve. That is a real,
        # permanent contract violation: no source declares these classes, and no amount
        # of retrying or restarting will conjure them. Unchanged 422, unchanged alarm —
        # this is the case ADR-0006's ruling was written for.
        logger.warning(
            "Contract D rejection for %s: missing %s (substrate IS ready — sentinel %s "
            "present, so this is a genuine declaration gap, not a boot race)",
            tool_urn, cd["missing"], cd["sentinel"],
        )
        raise HTTPException(
            status_code=422,
            detail={
                "status": "rejected",
                "tool_urn": tool_urn,
                "contract_d_check": cd,
                "reason": (
                    "input_uri and/or output_uri don't resolve to any "
                    ":OntologyClass node in Neo4j, and the ontology ingest HAS "
                    "completed (sentinel present) — so no TTL declares them. "
                    "Declare the class in its ontology and re-ingest; retrying "
                    "cannot help. NB a seeder that MERGEs endpoint classes can mask "
                    "this locally while every fresh cluster fails (mesh#DispositionReview, "
                    "2026-08-14)."
                ),
            },
        )

    # Step 2: v0.2 atomic-saga path.
    # Derive provider here so it lands on the substrate edge, not just
    # the DataHub MCP — Engine O's discovery Cypher reads `r.provider`.
    provider = manifest.provider or _derive_provider(manifest.name, manifest.verb_iri)
    rel_props = _build_rel_props_for_saga(
        manifest=manifest,
        provider=provider,
        tool_urn=tool_urn,
    )
    try:
        saga_outcome = _run_saga(
            manifest=manifest,
            tool_urn=tool_urn,
            provider=provider,
            rel_props=rel_props,
        )
    except Exception as e:
        # Last-resort: saga itself crashed (not a step failure). Treat
        # as 503 with no compensation guaranteed.
        logger.exception("v0.2 saga crashed for %s", tool_urn)
        raise HTTPException(
            status_code=503,
            detail={
                "status": "rejected",
                "tool_urn": tool_urn,
                "contract_d_check": cd,
                "reason": (
                    f"v0.2 saga crashed (not a step failure): "
                    f"{type(e).__name__}: {str(e)[:200]}. "
                    f"Substrate state is undefined; retry will converge."
                ),
            },
        )

    if saga_outcome.http_code != 200:
        # Saga ran but compensated. The conjunctive-read invariant
        # guarantees the half-write (if any survived compensation) is
        # unroutable; caller can retry safely.
        raise HTTPException(
            status_code=saga_outcome.http_code,
            detail={
                "status": saga_outcome.status,
                "tool_urn": tool_urn,
                "contract_d_check": cd,
                "reason": saga_outcome.reason,
                "saga": {
                    "neo4j_written": saga_outcome.neo4j_written,
                    "weaviate_written": saga_outcome.weaviate_written,
                    "forward_retry_attempts": saga_outcome.forward_retry_attempts,
                    "elapsed_s": round(saga_outcome.elapsed_s, 3),
                },
            },
        )

    # Step 3: DataHub MCP emit (governance history, out-of-band — failure
    # does NOT block the 200 because the substrate is already consistent
    # via the saga). v0.2.1 will move this into a background queue with
    # retry + dead-letter; for now we attempt it inline and log on
    # failure.
    datahub_resp: Optional[dict] = None
    try:
        datahub_resp = _emit_to_datahub(manifest, tool_urn)
    except Exception as e:
        logger.warning(
            "DataHub emit failed AFTER saga succeeded for %s: %s. "
            "Substrate is consistent; governance record will be "
            "reconciled by a future tick. Not blocking the 200.",
            tool_urn, e,
        )

    logger.info(
        "Registered %s (verb=%s) via v0.2 saga: retries=%d elapsed=%.2fs",
        tool_urn, manifest.verb_iri,
        saga_outcome.forward_retry_attempts, saga_outcome.elapsed_s,
    )
    return RegistrationResult(
        status="registered",
        tool_urn=tool_urn,
        contract_d_check=cd,
        datahub_response=datahub_resp,
    )


# ---------------------------------------------------------------------------
# v0.2 saga wiring — lifts the substrate writers into the request path.
# ---------------------------------------------------------------------------

# Dual import: dev uses the full package path; the container ships
# main.py at /app/main.py with v2_saga/v2_substrate as sibling modules
# (no package context), so the relative form fails on boot. Same shape
# as engine-o's instance_resolution import (commit 75a8011).
try:
    from agent_fleet.mesh_registrar import v2_saga
    from agent_fleet.mesh_registrar import v2_substrate as _v2substrate  # noqa: F401 — used by tests
except ImportError:
    import v2_saga  # type: ignore[no-redef]
    import v2_substrate as _v2substrate  # type: ignore[no-redef] # noqa: F401

_WEAVIATE_CLIENT_SINGLETON = None  # lazy-init via _get_weaviate_client()


def _get_weaviate_client():
    """Lazy-init the Weaviate client via the fleet-shared factory.

    Critically uses ``agent_fleet/utils/weaviate_utils.create_weaviate_client``
    which parses the ``host:port`` form ``WEAVIATE_HTTP_HOST`` is published
    as in the configmap (``iagent-weaviate:8080``). A naive
    ``http_host=os.getenv("WEAVIATE_HTTP_HOST")`` + ``http_port=8080``
    pair would try to dial ``iagent-weaviate:8080:8080`` — caught at
    cutover.
    """
    global _WEAVIATE_CLIENT_SINGLETON
    if _WEAVIATE_CLIENT_SINGLETON is not None:
        try:
            if _WEAVIATE_CLIENT_SINGLETON.is_connected():
                return _WEAVIATE_CLIENT_SINGLETON
        except Exception:
            _WEAVIATE_CLIENT_SINGLETON = None

    # Dual import — container has utils as a top-level path; dev uses
    # the full package path.
    try:
        from agent_fleet.utils.weaviate_utils import create_weaviate_client
    except ImportError:
        from utils.weaviate_utils import create_weaviate_client  # type: ignore[no-redef]

    _WEAVIATE_CLIENT_SINGLETON = create_weaviate_client()
    return _WEAVIATE_CLIENT_SINGLETON


def _build_rel_props_for_saga(
    *, manifest: RegistrationManifest, provider: str, tool_urn: str
) -> dict:
    """Build the property bag that lands on the Neo4j relationship.

    Mirrors what ``aitool_linker._build_relationship_properties`` produced
    from the customProperties — but constructed directly from the
    manifest so v0.2's path doesn't pass through the sensor's allowlist
    drift bug class (doc-tools 540fbd5 family).
    """
    return {
        # Identity is also set inside merge_neo4j_predicate_edge via
        # the match_key; we duplicate it here so a CREATE has the props.
        "iri": manifest.verb_iri,
        "_tool_urn": tool_urn,
        # Discoverable properties Engine O reads.
        "endpoint_url": manifest.endpoint_url,
        "owner_persona": manifest.owner_persona or "",
        "domains": list(manifest.domains or []),
        "cost_class": manifest.cost_class,
        "requires_human_approval": bool(manifest.requires_human_approval),
        "synonyms": list(manifest.verb_synonyms or []),
        "anti_synonyms": list(manifest.verb_anti_synonyms or []),
        "version": manifest.version,
        "provider": provider,
        # timeout_s is optional — only set when the engine declared it.
        **(
            {"timeout_s": float(manifest.timeout_s)}
            if manifest.timeout_s is not None
            else {}
        ),
    }


def _run_saga(
    *,
    manifest: RegistrationManifest,
    tool_urn: str,
    provider: str,
    rel_props: dict,
) -> "v2_saga.SagaOutcome":
    """Invoke the v0.2 saga with the shared driver + weaviate client."""
    driver = _get_neo4j_driver()
    weaviate_client = _get_weaviate_client()
    return v2_saga.run_registration_saga(
        driver=driver,
        weaviate_client=weaviate_client,
        verb_iri=manifest.verb_iri,
        input_uri=manifest.input_uri,
        output_uri=manifest.output_uri,
        tool_urn=tool_urn,
        rel_props=rel_props,
        description=manifest.description or "",
        endpoint_url=manifest.endpoint_url,
        owner_persona=manifest.owner_persona or "",
        domains=list(manifest.domains or []),
        cost_class=manifest.cost_class,
        requires_human_approval=bool(manifest.requires_human_approval),
        synonyms=list(manifest.verb_synonyms or []),
        anti_synonyms=list(manifest.verb_anti_synonyms or []),
        # The species and its payload reach the ROW, not just the DataHub aspect.
        # They were already assembled for the audit record; a reader of the graph
        # could not see them, so `menu_for()` could not scope, `_satisfies()`
        # could not evaluate fit, and ADR-0042 Ruling 9 would have been silently
        # vacuous -- always-False `recomputes` reads as "no live views exist".
        tool_kind=manifest.tool_kind,
        frontend_id=manifest.frontend_id or "",
        archetype=manifest.archetype or "",
        expected_fields=list(manifest.expected_fields or []),
        recomputes=manifest.recomputes,
    )


@app.get("/v1/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": REGISTRAR_VERSION}


# ---------------------------------------------------------------------------
# v0.2.1 — Restate VirtualObject mount (architect's A1, 2026-06-12).
#
# The VirtualObject wraps the same saga `/v1/register` calls inline. The
# in-process path stays as the active write path for single-replica
# deployments (no race window); the VirtualObject is the durability +
# serialization wire for future multi-replica deployments and crash
# recovery. Per ADR-0006 §Addendum and v2_restate.py's docstring, the
# safety class is unchanged — the conjunctive-read invariant covers
# both paths.
#
# The mount is import-protected so the gateway still boots if
# restate-sdk isn't installed (CI, isolated test clusters), in which
# case only the in-process path is available.
# ---------------------------------------------------------------------------
try:
    try:
        from agent_fleet.mesh_registrar import v2_restate
    except ImportError:
        import v2_restate  # type: ignore[no-redef]
    import restate

    app.mount(
        "/restate",
        restate.app(services=[v2_restate.registration_saga_object]),
    )
    logger.info(
        "Mounted Restate VirtualObject %r at /restate (handler %r, key shape "
        "verb_iri::tool_urn)",
        v2_restate.SAGA_OBJECT_NAME, v2_restate.SAGA_HANDLER_NAME,
    )
except Exception as exc:  # noqa: BLE001
    logger.warning(
        "Restate mount skipped: %s: %s. The in-process saga path "
        "(/v1/register) remains the active write path. Install "
        "restate-sdk and set RESTATE_INGRESS_URL to enable the "
        "VirtualObject.",
        type(exc).__name__, exc,
    )
