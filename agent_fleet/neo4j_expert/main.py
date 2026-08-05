"""
Engine E — Restate + Smolagents Durable Neo4j Graph Expert Microservice

A FastAPI server backed by the Restate SDK for durable execution.
It exposes a `/query_graph` endpoint that uses a smolagents CodeAgent
with custom Neo4j Cypher and Schema tools to extract structural data
from a military technical manual graph database. BAML strictly types
the output per Persona.

Also exposes `/resolve_instance` — Engine E's Recipe v2 phone-book
endpoint that resolves named individuals (equipment serials, procedure
codes, tail numbers) to their canonical class via direct Cypher
lookup. Registered through the gateway as the second
mesh:resolveInstance provider; the router discovers it via the
predicate graph and the architecture's acceptance test is that no
Engine O code changed to make it work.

Run locally: uvicorn agent_fleet.neo4j_expert.main:app --host 0.0.0.0 --port 8086
"""

import os
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
import restate
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Engine self-registration for the predicate-graph routing layer
# (iagent ADR-0004 Step D.1). Opt-in via MESH_REGISTER_ON_STARTUP.
try:
    from utils.mesh_registration import register_engine_to_mesh
except ImportError:
    from agent_fleet.utils.mesh_registration import register_engine_to_mesh

# B3 — shared DMC canonicalizer. Same code as the B2 ingest writer
# (doc-tools' doc_tools/parsers/dmc_canonicalizer.py); a
# test_b3_canonicalizer_drift.py asserts SHA256 equality between the
# two copies. A canonicalizer bug fails the B2 ingest tests AND
# Engine E's /resolve_dmc probe identically.
try:
    from utils.dmc_canonicalizer import canonicalize_dmc
except ImportError:
    from agent_fleet.utils.dmc_canonicalizer import canonicalize_dmc

try:
    # Standalone microservice mode (Workspace Root)
    from service import service as expert_service
except ImportError:
    # Local dev mode (Imported as submodule)
    try:
        from .service import service as expert_service
    except ImportError:
        # Fallback for parent-dir execution
        from agent_fleet.neo4j_expert.service import service as expert_service

# Engine E's lifespan registers it as a predicate in the mesh routing graph.
# Engine E queries a Neo4j military-technical-manual graph using Cypher +
# smolagents CodeAgent with semantic-search tools; takes a structured graph
# query and returns a persona-typed GraphExpertResponse.
@asynccontextmanager
async def lifespan(app: FastAPI):
    register_engine_to_mesh(
        name="engine_e_neo4j_expert",
        description=(
            "Knowledge graph expert. Runs a smolagents CodeAgent over Neo4j "
            "(execute_cypher, get_graph_schema, search_manual_text) with "
            "Restate-durable execution and mem0 long-term memory."
        ),
        verb="mesh:queryKnowledgeGraph",
        input_uri="https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
        output_uri="http://invincible-agent/mesh#GraphExpertResponse",
        # Synonyms drive Engine O's BM25 ranking of this verb against the
        # user's query. The pre-v0.2 list ("query graph", "graph lookup",
        # ...) covered the verb's own vocabulary but not the natural
        # vocabulary of the questions users actually ask the maintenance
        # graph. Cutover surfaced this when the fabrication-fallback
        # was removed (ADR-0006 §Addendum 2026-06-13): a Neo4j-compat
        # verb that isn't BM25-surfaced in Weaviate fails the
        # conjunctive-read invariant by design. Expanded to cover the
        # standing matrix's MAINTENANCE rows: procedure / work
        # instruction / maintenance steps / diagram / TEST-N codes. The
        # routing question grammar drives the synonym set, not the
        # verb's internal naming.
        verb_synonyms=[
            # Verb-vocabulary (original)
            "query graph", "graph lookup", "cypher query",
            "find in graph", "knowledge graph search",
            # Maintenance-domain query vocabulary
            "procedure", "describe procedure", "find procedure",
            "tell me about procedure", "look up procedure",
            "work instruction", "what is the work instruction",
            "maintenance steps", "maintenance procedure",
            "diagram", "schematic", "figure", "show me the diagram",
            "rotor assembly", "equipment", "assembly",
        ],
        endpoint_url=os.getenv(
            "ENGINE_E_PUBLIC_URL",
            "http://iagent-engine-e:8086/query_graph",
        ),
        owner_persona="AUDITOR",
        # Per ADR-0009: Engine E queries the maintenance-manual knowledge
        # graph; its domain scopes follow the manual corpus it serves.
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="slow",
    )

    # Second registration of mesh:queryKnowledgeGraph against
    # mro:ProcedureStep. The matrix surfaces a real ontology coverage
    # gap (2026-06-13): "Show me the maintenance steps for the rotor
    # assembly" → resolver picks mro:ProcedureStep (a defensible
    # semantic match for "steps"); ProcedureStep has no subClassOf
    # ancestors in Neo4j, so compat-walk returns empty and Contract B
    # short-circuits to UNKNOWN. The architect's "verbs follow
    # questions" framing applied: Engine E *can* answer ProcedureStep
    # queries (the knowledge graph contains ProcedureStep nodes), so
    # the engine declares it via a second registration. NOT a TTL
    # change — that would require subclassing ProcedureStep under
    # mesh:GraphQuery which is semantically wrong (one is a domain
    # concept, the other is a Request shape). The clean fix is to
    # surface the verb against the second subject it serves; identity
    # via (verb_iri, _tool_urn) keeps it as its own edge from a44b9fb.
    register_engine_to_mesh(
        # IMPORTANT: same description as the primary registration above.
        # BAML's TypeBuilder dedupes enum values by name; when two
        # candidate rows share verb_iri but disagree on description, the
        # last add_value's description wins and the others are silently
        # lost. The first attempt at this registration used a
        # ProcedureStep-specific description and the LLM then refused
        # for WorkInstruction subjects ("operates on ProcedureStep, but
        # subject is WorkInstruction"). The fix is the same description
        # on every registration of the same verb — they're the same
        # capability typed against different subjects; the description
        # is about WHAT the verb does, not which subject path reached
        # it.
        name="engine_e_neo4j_expert_procedure_step",
        description=(
            "Knowledge graph expert. Runs a smolagents CodeAgent over Neo4j "
            "(execute_cypher, get_graph_schema, search_manual_text) with "
            "Restate-durable execution and mem0 long-term memory."
        ),
        verb="mesh:queryKnowledgeGraph",
        # 2026-06-15: canonicalized from compact mro:ProcedureStep to full-IRI.
        # Source-resident regression caught by widened class guard during the
        # mesh:Thing investigation's writer-hunt. Same form sync_jena_ontologies_to_neo4j
        # materializes from mro_extension.ttl; using compact-form here would create
        # duplicate :OntologyClass nodes alongside the canonical and reproduce the
        # Phase-5-prophecy class on next substrate cache invalidation.
        input_uri="https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/ProcedureStep",
        output_uri="http://invincible-agent/mesh#GraphExpertResponse",
        verb_synonyms=[
            "query graph", "graph lookup", "cypher query",
            "find in graph", "knowledge graph search",
            "procedure", "describe procedure", "find procedure",
            "tell me about procedure", "look up procedure",
            "work instruction", "what is the work instruction",
            "maintenance steps", "maintenance procedure",
            "diagram", "schematic", "figure", "show me the diagram",
            "rotor assembly", "equipment", "assembly",
        ],
        endpoint_url=os.getenv(
            "ENGINE_E_PUBLIC_URL",
            "http://iagent-engine-e:8086/query_graph",
        ),
        owner_persona="AUDITOR",
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="slow",
    )

    # B4 verb 2 (2026-06-16): third queryKnowledgeGraph registration
    # for the document-side of procedural content. mil:ProcedureDataModule
    # is the DOCUMENT (S1000D/40051 data module — what tech writers
    # author and manage), while mro:WorkInstruction is the CONTENT
    # (the actual steps maintainers execute). The two layers are
    # container/content, not flat siblings: maintainer-framed queries
    # ("steps to install X") correctly resolve to WorkInstruction;
    # tech-writer-framed queries ("describe the procedure data module
    # for X") correctly resolve to ProcedureDataModule. Both route to
    # Engine E's knowledge-graph endpoint via queryKnowledgeGraph
    # because both questions are answered by the same graph traversal
    # (find procedure → steps → tool refs → diagrams).
    #
    # The containment relationship between ProcedureDataModule and
    # WorkInstruction is currently UNMODELED in mil_extension.ttl —
    # they live in different namespaces with no declared connection.
    # Banked as an ADR-shaped design decision: model the
    # contains/hasContent relationship so the two layers disambiguate
    # by question framing structurally rather than via hint-priming
    # similarity contest. See STATE_GATEWAY_V02.md "2026-06-16 verb 2
    # halt + reframe" for the trace.
    register_engine_to_mesh(
        # Same description as the primary queryKnowledgeGraph
        # registration above — BAML TypeBuilder dedupes enum values by
        # name; last add_value's description wins. Same capability typed
        # against different subjects; the description is about WHAT the
        # verb does, not which subject path reached it.
        name="engine_e_neo4j_expert_procedure_data_module",
        description=(
            "Knowledge graph expert. Runs a smolagents CodeAgent over Neo4j "
            "(execute_cypher, get_graph_schema, search_manual_text) with "
            "Restate-durable execution and mem0 long-term memory."
        ),
        verb="mesh:queryKnowledgeGraph",
        input_uri="http://edgy-solutions.com/ontology/mil#ProcedureDataModule",
        output_uri="http://invincible-agent/mesh#GraphExpertResponse",
        verb_synonyms=[
            "query graph", "graph lookup", "cypher query",
            "find in graph", "knowledge graph search",
            "procedure", "describe procedure", "find procedure",
            "tell me about procedure", "look up procedure",
            "work instruction", "what is the work instruction",
            "maintenance steps", "maintenance procedure",
            "how do I", "steps to install", "install procedure",
            "removal installation", "removal and installation",
            "data module", "procedure data module",
            "S1000D", "TM procedure", "data module covers",
            "diagram", "schematic", "figure",
        ],
        endpoint_url=os.getenv(
            "ENGINE_E_PUBLIC_URL",
            "http://iagent-engine-e:8086/query_graph",
        ),
        owner_persona="AUDITOR",
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="slow",
    )

    # Recipe v2 — second mesh:resolveInstance provider (Gate 6
    # generality acceptance test). Engine E owns the
    # urn:instance:* / WorkInstruction / Equipment node side of the
    # instance layer, parallel to Engine D's catalog side. The router
    # discovers this registration through the predicate graph alone;
    # if Engine O had to learn anything Engine-E-specific to make it
    # work, the architecture would have failed its own test — the
    # standing-guard ``test_engine_d_url_is_not_hardcoded_in_engine_o``
    # would turn red on the next CI run.
    _engine_e_resolve_instance_url = os.getenv(
        "ENGINE_E_RESOLVE_INSTANCE_URL",
        "http://iagent-engine-e:8086/resolve_instance",
    )
    register_engine_to_mesh(
        name="engine_e_resolve_instance",
        description=(
            "Resolves a named individual (equipment serial, part number, "
            "tail number, procedure code, work-instruction title, or any "
            "identifier-shaped token) to its canonical class via direct "
            "Cypher lookup against the maintenance knowledge graph. "
            "Returns candidates with class URI (mro:Equipment, "
            "mro:WorkInstruction, ...), label, the instance's URN, and a "
            "relevance score. Empty list when nothing in the graph "
            "matches above the relevance floor — abstention is the "
            "contract, the LLM's class guess stands on miss."
        ),
        verb="mesh:resolveInstance",
        input_uri="http://invincible-agent/mesh#InstanceIdentifier",
        output_uri="http://invincible-agent/mesh#InstanceResolution",
        verb_synonyms=[
            "look up equipment by serial",
            "find procedure by code",
            "identify tail number",
            "resolve part number",
            "classify equipment identifier",
        ],
        endpoint_url=_engine_e_resolve_instance_url,
        owner_persona="AUDITOR",
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="fast",
        requires_human_approval=False,
        provider="engine_e",
        # Cypher CONTAINS / equality matching against a small instance set
        # is sub-second; 2s gives 10x headroom over the typical query.
        # Critically: declaring it here, instead of inheriting Engine D's
        # 8s ceiling, means an actual Cypher pathology surfaces in the
        # router's timeout log instead of hiding behind a budget sized
        # for a different stack.
        timeout_s=2.0,
    )

    # B3 — DMC resolution capability. Per the architect's
    # "phone book lives where its data lives" framing (2026-06-13):
    # B2's ingest writes :DataModule instances into THIS engine's
    # Neo4j graph (indexed by `dmc_uri_unique`), so DMC resolution
    # is a second capability of Engine E, not a separate service.
    # Three registrations, two engines:
    #   - engine_d (catalog, in DataHub wrapper)
    #   - engine_e (above: equipment, here on Engine E)
    #   - engine_e_dmc (this: DMC, also on Engine E)
    # The router fans out to all three providers under the same
    # canonical mesh#InstanceIdentifier subject; each provider does
    # its own narrow lookup; each abstains honestly when its
    # identifier shape doesn't match.
    _engine_e_resolve_dmc_url = os.getenv(
        "ENGINE_E_RESOLVE_DMC_URL",
        "http://iagent-engine-e:8086/resolve_dmc",
    )
    register_engine_to_mesh(
        name="engine_e_dmc_resolve_instance",
        description=(
            "Resolves a Data Module Code (DMC) — the S1000D identity "
            "of a technical-manual data module — to its canonical "
            "mil:* content kind (ProcedureDataModule, "
            "FaultIsolationDataModule, IllustratedPartsDataModule, "
            "DescriptiveDataModule, Diagram). Looks up the canonical "
            "DMC string form against the same maintenance knowledge "
            "graph Engine E's equipment resolver uses; returns the "
            "matching content kind with provenance. Empty list when "
            "the input isn't a DMC or no module matches — abstention "
            "is the contract. Same engine, second capability."
        ),
        verb="mesh:resolveInstance",
        input_uri="http://invincible-agent/mesh#InstanceIdentifier",
        output_uri="http://invincible-agent/mesh#InstanceResolution",
        verb_synonyms=[
            "resolve dmc",
            "look up data module",
            "what kind of data module",
            "classify dmc",
            "identify data module code",
        ],
        endpoint_url=_engine_e_resolve_dmc_url,
        owner_persona="TECH_WRITER",
        domains=["MAINTENANCE"],
        cost_class="fast",
        requires_human_approval=False,
        provider="engine_e_dmc",
        # Direct primary-key Cypher lookup via dmc_uri_unique index.
        # Sub-millisecond; 2s is plenty.
        timeout_s=2.0,
    )

    yield


# Initialize FastAPI
app = FastAPI(title="Engine E: Neo4j Graph Expert", lifespan=lifespan)

# Restate App Binding
# This binds the previously defined expert_service (Neo4jExpertService)
# to handle durable executions incoming from the `/restate` base path.
# Using app.mount is the standard way to integrate Restate with FastAPI.
app.mount("/restate", restate.app(services=[expert_service]))

# Read the Restate URL from env, default to the Docker Compose service name
RESTATE_INGRESS_URL = os.getenv("RESTATE_INGRESS_URL", "http://restate:8080")

@app.post("/query_graph")
async def query_graph_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate Neo4jExpertService.
    
    Dagster POSTs directly to this endpoint. We forward it to the Restate Ingress
    at /{ServiceName}/{MethodName} for durable execution.
    """
    try:
        payload = await request.json()

        # ADR-0038 — close the analyst→E JOIN at the one seam it was open. Restate
        # handlers read the BODY, not HTTP headers, so a trace id must ride in the
        # payload for Neo4jExpertService.observed_trace to seed on it (and E's graph
        # spans nest under the caller's trace instead of orphaning). E has two caller
        # shapes, unified on ONE field here:
        #   - the supervisor's specialist dispatch puts `trace_id` directly in the body;
        #   - the analyst's discovery tool sends it as the X-Trace-Id HEADER.
        # Prefer an id already in the body; else adopt the header; else mint a root id
        # (a fresh standalone trace — never a crash). This is the same header→body
        # translation Engine D's /analyze_data proxy does, same field name, so the two
        # restate engines share one convention rather than forking it. A trace id is a
        # non-secret correlation identifier, so persisting it in Restate's durable
        # journal carries no credential concern.
        import uuid as _uuid
        if not payload.get("trace_id"):
            payload["trace_id"] = request.headers.get("X-Trace-Id") or str(_uuid.uuid4())

        target_url = f"{RESTATE_INGRESS_URL}/Neo4jExpertService/query_graph"

        # Match the supervisor's per-engine call timeout. The Cypher-writing
        # smolagent loop can take several minutes per multi-step query on
        # slow Ollama backends; 300s reliably timed out mid-loop.
        async with httpx.AsyncClient(timeout=900.0) as client:
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
    return {"status": "ok", "engine": "E"}


# ---------------------------------------------------------------------------
# Recipe v2 — instance resolution for the maintenance knowledge graph.
# ---------------------------------------------------------------------------
class ResolveInstanceRequest(BaseModel):
    identifier: str
    query: Optional[str] = None  # full user query, advisory only


class InstanceCandidate(BaseModel):
    instance_id: str   # the node's authoritative URN / IRI / synthetic key
    class_uri: str     # canonical ontology class — what the router consumes
    label: str
    score: float       # provider relevance, 0.0–1.0


class ResolveInstanceResponse(BaseModel):
    candidates: List[InstanceCandidate]


# Map Neo4j node labels → canonical ontology class URIs the router knows.
# All entries MUST be canonical full-IRI to match what
# sync_jena_ontologies_to_neo4j materializes; compact-form here would
# emit duplicate :OntologyClass references at runtime via
# /resolve_instance responses (same Phase-5-prophecy class the widened
# class guard catches).
# 2026-06-15: canonicalized Instance/Procedure entries during the
# mesh:Thing writer-hunt's source scan. Part is BANKED — mro:Part has
# no canonical declaration in mro_extension.ttl yet; sandbox substrate
# does not contain the full-IRI form. Until the TBox declaration lands
# (or the row is removed if Engine E no longer emits Part candidates),
# Part stays compact and the widened substrate guard correctly flags
# it for resolution. See STATE_GATEWAY_V02.md "2026-06-15 Step-2
# source-side regressions" for the trace.
_LABEL_TO_CLASS_URI = {
    "WorkInstruction": "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
    "Instance":        "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Equipment",
    "Procedure":       "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/Procedure",
    "Part":            "mro:Part",  # banked TBox-decision item, see docstring above
}

# Fields on the node that PLAUSIBLY carry the kind of identifier a user
# would type. Order matters for scoring: an exact hit on a serial number
# beats a fuzzy hit on a free-text title. Adding a new identifier field
# is one row here.
_IDENTIFIER_FIELDS_EXACT = [
    "iri",
    "uri",
    "partNumber",
    "procedureId",
    "serialNumber",
    "tailNumber",
]
_IDENTIFIER_FIELDS_FUZZY = [
    "name",
    "title",
    "label",
]

_RESOLVE_INSTANCE_MIN_SCORE = float(
    os.getenv("RESOLVE_INSTANCE_MIN_SCORE", "0.7")
)
_RESOLVE_INSTANCE_LIMIT = int(os.getenv("RESOLVE_INSTANCE_LIMIT", "10"))


_INSTANCE_CYPHER = """
// Exact identifier hits — partNumber, procedureId, serialNumber,
// tailNumber, iri, uri. Each scored 1.0 (authoritative match) per
// the architect's note: a hit on a unique field is identity, not
// proximity.
CALL {
    WITH $identifier AS ident
    MATCH (n)
    WHERE any(label IN labels(n) WHERE label IN $accepted_labels)
      AND any(field IN $exact_fields WHERE n[field] = ident)
    RETURN n, 1.0 AS score, 'exact' AS match_kind
}
RETURN labels(n) AS labels, properties(n) AS props, score, match_kind
UNION
// Fuzzy hits — case-insensitive CONTAINS on name/title/label.
// Scored 0.8 (good evidence) so they survive the router's 0.7 floor
// but lose to exact hits in the unanimous-class branch.
CALL {
    WITH $identifier AS ident, toLower($identifier) AS lid
    MATCH (n)
    WHERE any(label IN labels(n) WHERE label IN $accepted_labels)
      AND any(field IN $fuzzy_fields
              WHERE n[field] IS NOT NULL
                AND toLower(toString(n[field])) CONTAINS lid)
      AND NOT any(field IN $exact_fields WHERE n[field] = ident)
    RETURN n, 0.8 AS score, 'fuzzy' AS match_kind
}
RETURN labels(n) AS labels, properties(n) AS props, score, match_kind
LIMIT $limit
"""


def _pick_instance_id(props: dict) -> str:
    """Best identity to return downstream — IRI > URN > unique field."""
    for key in ("iri", "uri", "urn"):
        if props.get(key):
            return str(props[key])
    for key in _IDENTIFIER_FIELDS_EXACT:
        if props.get(key):
            return str(props[key])
    return ""


def _pick_label(props: dict, fallback: str) -> str:
    """Human-readable label to return downstream."""
    for key in ("name", "title", "label", "iri", "partNumber", "procedureId"):
        if props.get(key):
            return str(props[key])
    return fallback


def _pick_class_uri(labels: list[str]) -> Optional[str]:
    """Map node labels to the canonical ontology class URI."""
    for lbl in labels:
        if lbl in _LABEL_TO_CLASS_URI:
            return _LABEL_TO_CLASS_URI[lbl]
    return None


@app.post("/resolve_instance", response_model=ResolveInstanceResponse)
async def resolve_instance(request: ResolveInstanceRequest) -> ResolveInstanceResponse:
    """Instance-resolution endpoint for the mesh:resolveInstance predicate.

    Implementation strategy: a single Cypher query that UNIONs exact
    hits (identifier matches a unique-field property like partNumber,
    procedureId, iri) with fuzzy hits (CONTAINS on title/name/label).
    Per the recipe's contract: empty list is a first-class answer —
    a Cypher hit below the relevance floor IS suppressed rather than
    returned as least-bad-match. Same disease prevention as the
    DataHub side.

    LOUD-ERROR PATH (same family as Engine D's GraphQL errors log):
    Cypher exceptions are logged with the identifier and the
    statement excerpt, never silently swallowed into an empty
    response. A future schema drift in the graph announces itself in
    Engine E's pod logs instead of riding as a polite miss into a
    fall-through.
    """
    try:
        from tools import get_neo4j_driver
    except ImportError:
        from agent_fleet.neo4j_expert.tools import get_neo4j_driver

    try:
        driver = get_neo4j_driver()
        with driver.session() as session:
            records = list(session.run(
                _INSTANCE_CYPHER,
                identifier=request.identifier,
                accepted_labels=list(_LABEL_TO_CLASS_URI.keys()),
                exact_fields=_IDENTIFIER_FIELDS_EXACT,
                fuzzy_fields=_IDENTIFIER_FIELDS_FUZZY,
                limit=_RESOLVE_INSTANCE_LIMIT,
            ))
    except Exception as exc:  # noqa: BLE001 — empty answer is first-class, but we LOG it
        print(
            f"[Engine E] /resolve_instance Cypher FAILED for identifier="
            f"{request.identifier!r}: {type(exc).__name__}: {exc}"
        )
        return ResolveInstanceResponse(candidates=[])

    candidates: list[InstanceCandidate] = []
    seen_ids: set[str] = set()
    for rec in records:
        labels = rec.get("labels") or []
        props = dict(rec.get("props") or {})
        score = float(rec.get("score") or 0.0)

        if score < _RESOLVE_INSTANCE_MIN_SCORE:
            continue

        class_uri = _pick_class_uri(labels)
        if not class_uri:
            # Node matched but its label has no canonical class mapping
            # yet — skip. The architect's rule: never invent a class.
            continue

        instance_id = _pick_instance_id(props)
        if not instance_id:
            continue
        if instance_id in seen_ids:
            continue
        seen_ids.add(instance_id)

        candidates.append(InstanceCandidate(
            instance_id=instance_id,
            class_uri=class_uri,
            label=_pick_label(props, fallback=instance_id),
            score=round(score, 3),
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return ResolveInstanceResponse(candidates=candidates)


# ---------------------------------------------------------------------------
# B3 — DMC resolution capability (Engine E's second resolveInstance entry).
#
# Per the architect's "capability lives with data owner" framing
# (2026-06-13): B2's ingest writes :DataModule instances into this
# engine's Neo4j graph indexed by `dmc_uri_unique`. The DMC phone book
# is therefore a second capability of Engine E, not a separate service.
# Same engine, same Neo4j driver, separate endpoint + separate
# registration so the router fans out cleanly and provenance names
# exactly which capability resolved.
#
# Architectural invariants:
#   - The canonicalizer is the SHARED `dmc_canonicalizer` module —
#     same code as B2's ingest writer; SHA256 drift detector
#     (test_b3_canonicalizer_drift) catches divergence in CI.
#   - The lookup is a direct primary-key MATCH on `dm.dmc = $canonical`
#     against B2's `:DataModule` substrate — NO LLM, NO fuzziness.
#     DMCs are precise identifiers; either the canonical form exists
#     in the graph or it doesn't.
#   - Score is 1.0 on exact match, no candidates emitted otherwise.
#     Empty list is a first-class answer (ADR-0019 Contract A) —
#     abstain honestly when the input isn't a DMC or no module matches.
# ---------------------------------------------------------------------------

_DMC_CYPHER = """
MATCH (dm:DataModule {dmc: $canonical})-[:INSTANCE_OF]->(kind:OntologyClass)
RETURN dm.dmc AS dmc,
       kind.uri AS class_uri,
       coalesce(dm.techName, dm.dmc) AS label
LIMIT 5
"""


@app.post("/resolve_dmc", response_model=ResolveInstanceResponse)
async def resolve_dmc(request: ResolveInstanceRequest) -> ResolveInstanceResponse:
    """DMC instance-resolution endpoint (Engine E's second capability).

    Normalize the incoming identifier via the shared canonicalizer,
    look up the matching :DataModule in Neo4j by `dmc_uri_unique`,
    return the canonical mil:* content kind the substrate's
    INSTANCE_OF edge points at. Abstain honestly on non-DMC input
    (canonicalizer returns None) and on lookup miss.

    Per Recipe v2 + ADR-0019 Contract A: empty list is a first-class
    answer; the router will fall through to the other providers
    (engine_d, engine_e equipment) and ultimately to the LLM's guess
    if none of them speak.
    """
    raw = (request.identifier or "").strip()
    canonical = canonicalize_dmc(raw)
    if canonical is None:
        # Not a DMC shape — Engine E's equipment resolver (above) or
        # Engine D may speak. Honest abstain.
        return ResolveInstanceResponse(candidates=[])

    try:
        try:
            from tools import get_neo4j_driver
        except ImportError:
            from agent_fleet.neo4j_expert.tools import get_neo4j_driver

        driver = get_neo4j_driver()
        with driver.session() as session:
            records = list(session.run(_DMC_CYPHER, canonical=canonical))
    except Exception as exc:  # noqa: BLE001 — LOG, return empty
        print(
            f"[Engine E] /resolve_dmc Cypher FAILED for canonical="
            f"{canonical!r}: {type(exc).__name__}: {exc}"
        )
        return ResolveInstanceResponse(candidates=[])

    candidates = [
        InstanceCandidate(
            instance_id=rec["dmc"],
            class_uri=rec["class_uri"],
            label=rec["label"] or rec["dmc"],
            score=1.0,
        )
        for rec in records
        if rec.get("dmc") and rec.get("class_uri")
    ]
    return ResolveInstanceResponse(candidates=candidates)
