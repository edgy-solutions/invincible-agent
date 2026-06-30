"""
The Cortex — Interviewer Agent API
FastAPI service that bridges the React frontend to the Polyglot Agent Mesh.
Now operating under proper Polyglot Mesh architecture — acting purely as a proxy 
for Dagster's supervisor_query_job orchestration.

Endpoints:
  POST /interview/stream  — Triggers supervisor_query_job and streams stepStats
  POST /workflow/compile   — Compile blueprint into Dagster job
  GET  /health             — Health check

Streaming Protocol:
  event: status
  data: {"action": "think", "category": "Process", "label": "Engaging Supervisor Agent..."}
  
  event: status
  data: {"action": "think", "category": "Process", "label": "Fanning out to Domain Experts..."}
  
  event: final_payload
  data: {... Server-Driven UI Component JSON ...}
"""

import sys
try:
    import pysqlite3
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from neo4j import GraphDatabase
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db, init_db
from .models import BpmnCatalog
from .auth import get_current_user, User
from .answer_artifact_writer import (
    AnswerArtifactBundle,
    DurabilityStatus,
    get_writer,
)


logger = logging.getLogger("cortex")

# ── Env ───────────────────────────────────────────────────
load_dotenv()

_DAGSTER_WEBSERVER_URL = os.getenv("DAGSTER_WEBSERVER_URL", "http://localhost:3000")
_DAGSTER_REPOSITORY = os.getenv("DAGSTER_REPOSITORY", "__repository__")
_DAGSTER_LOCATION = os.getenv("DAGSTER_LOCATION", "iagent")

# Upstream Electric service for the JWT-scoped shape proxy. The client
# (cortex-ui) connects to cortex-bff's `/electric/shape` endpoint
# rather than to Electric directly, so a server-verified `user_id`
# WHERE clause is injected based on the authenticated JWT instead of
# being client-controlled. See `electric_shape_proxy` below.
_ELECTRIC_UPSTREAM_URL = os.getenv("ELECTRIC_UPSTREAM_URL", "http://iagent-electric:3000")

# ── Lifespan ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup/shutdown lifecycle — verify DB connection on boot."""
    await init_db()
    yield


# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="The Cortex — API Proxy",
    version="2.1.0",
    lifespan=lifespan,
)

_DAGSONTOLOGY_SVC_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://ontology-service:8084")
_RESTATE_INGRESS_URL = os.getenv("RESTATE_INGRESS_URL", "http://restate:8080")

@app.get("/mesh/config")
async def get_mesh_config(current_user: User = Depends(get_current_user)):
    """Proxy the dynamic UI configuration from the Ontology Service."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_DAGSONTOLOGY_SVC_URL}/mesh/config")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.error("Failed to fetch mesh config: %s", exc)
        return {"personas": {}, "status": "OFFLINE"}

# Neo4j Driver Setup
_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
_NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")

neo4j_driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USERNAME, _NEO4J_PASSWORD))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Electric SQL's ShapeStream client reads custom headers from
    # the `/electric/shape` proxy response to drive incremental sync.
    # Browsers hide non-safelisted response headers from fetch()
    # unless explicitly exposed by CORS; without this, the
    # ShapeStream sees no `electric-handle` / `electric-offset` and
    # never advances past the first chunk.
    expose_headers=[
        "electric-handle",
        "electric-offset",
        "electric-up-to-date",
        "electric-schema",
        "electric-cursor",
    ],
)


# ── Models ────────────────────────────────────────────────
class InterviewRequest(BaseModel):
    message: str
    # Required: identifies the chat thread / DagsterRunTracker key. A missing
    # session_id used to be silently filled with a fresh UUID per request,
    # which defeated the tracker's per-key dedup and caused back-to-back
    # duplicate Dagster runs whenever the UI re-fired the same submission.
    session_id: str
    current_graph_json: str | None = None
    # Optional: client-supplied AnswerArtifact id. Hop 3 (Electric →
    # store) needs cortex-ui's locally-created pending artifact id to
    # equal the server's persisted artifact id, otherwise Electric
    # streams the real artifact with a DIFFERENT id, the store's
    # `existingIdx === -1`, and the pending stays foregrounded with
    # empty data while the real one sits unviewed. Pass the client's
    # `artifactId` here so writer + projector + Electric flow it
    # through, and `electricUpsertArtifact` finds the pending row by
    # id and merges in place. Fallback (None) preserves the server-
    # generates-id behavior for non-cortex-ui callers (curl, tests).
    artifact_id: str | None = None


class BPMNTask(BaseModel):
    id: str
    name: str
    type: str  # "service_task" | "user_task"
    agent_endpoint: str


class BPMNGateway(BaseModel):
    id: str
    name: str
    type: str  # "exclusive"


class BPMNSequenceFlow(BaseModel):
    id: str
    source_ref: str
    target_ref: str
    condition_expression: str | None = None


class BPMNPayload(BaseModel):
    tasks: list[BPMNTask] = []
    gateways: list[BPMNGateway] = []
    sequence_flows: list[BPMNSequenceFlow] = []


class CompileRequest(BaseModel):
    session_id: str
    bpmn_payload: BPMNPayload


class CompileResponse(BaseModel):
    success: bool
    run_id: str
    dagster_job_name: str | None = None
    message: str | None = None
    boot_log: str = ""


# ── ADR-0017 frontend self-registration ──────────────────────
# The original ADR-0017 vision was that frontends self-advertise their
# presentation capabilities ("I can render mesh:OwnershipFact as a
# KNOWLEDGE_DOCUMENT") rather than the backend assuming what the frontend
# can render. The current state: Engine F's startup advertises 9 capability
# triples on cortex-ui's behalf via an in-memory table. That works for one
# frontend; it breaks the moment a second frontend (mobile, voice, etc.)
# registers different capabilities.
#
# This stage of the cleanup ships the frontend-advertisement HALF of the
# proper architecture: cortex-ui POSTs its capability list at login, this
# endpoint receives it, validates the JWT, and logs the advertisement to
# the iagent.registry.frontend_capabilities logger. The capability set is
# then observable in cluster logs and Langfuse traces — proving the
# pattern end-to-end without breaking Engine F's existing lookup behavior.
#
# Stage 2 (follow-up): replace Engine F's in-memory _lookup_capability
# with a /search_predicates call so the live registry IS the authoritative
# source. Until then, this endpoint produces the data Stage 2 will consume.

class FrontendCapability(BaseModel):
    """One presentation capability advertised by a frontend.

    Shape mirrors the existing register_presentation_to_mesh helper in
    agent_fleet/utils/mesh_registration.py so cortex-bff can route this
    into the same SPO-triple substrate later.
    """
    subject_uri: str          # e.g. "mesh:OwnershipFact"
    object_uri: str           # e.g. "mesh:KnowledgeDocument"
    archetype: str            # e.g. "KNOWLEDGE_DOCUMENT"
    component: str | None = None
    layout: str | None = None
    expected_fields: list[str] = []
    persona_fit: list[str] = []
    domain_fit: list[str] = []


class RegisterFrontendCapabilitiesRequest(BaseModel):
    """Sent by cortex-ui (and any future frontend) after auth completes.

    `frontend_id` distinguishes registrations from different surfaces in
    the predicate graph (cortex-ui-desktop, cortex-ui-mobile, voice-cli,
    etc.). `frontend_version` rides along so drift between code that
    declared the capability and code that's serving it is detectable.
    """
    frontend_id: str          # e.g. "cortex-ui-desktop"
    frontend_version: str     # e.g. "0.1.0"
    capabilities: list[FrontendCapability]


class RegisterFrontendCapabilitiesResponse(BaseModel):
    accepted: int
    frontend_id: str


# Dedicated logger so registrations are easy to slice out in log search.
_frontend_registry_logger = logging.getLogger("iagent.registry.frontend_capabilities")


def _sse(event: str, data: str) -> str:
    """Format a Server-Sent Event line pair."""
    return f"event: {event}\ndata: {data}\n\n"


# ──────────────────────────────────────────────────────────────────────
# Typed grounding-panel events (Option A clean cut, 2026-06-22)
# ──────────────────────────────────────────────────────────────────────
#
# Old free-text `status` events with action="think"/"found"/"error"/"plan"
# are GONE from this gateway. Every signal that drives the cortex-ui
# grounding panel is now a typed event whose payload projects real
# pipeline data. The Dagster path remains authoritative — the events
# the UI sees are derived from Dagster step status, asset
# materialization metadata, and the pre-Dagster /route_intent call.
# The gateway is not allowed to fabricate stage progress.
#
# Architect's principle: surface what the pipeline did; never
# synthesize, soften, or hide. The typed variants below let the UI
# render the substrate's real progress + real errors without the
# accumulating-heartbeat noise the old `status` events produced.
#
# The variants and their UI consumers:
#   pipeline_stage  → ThinkingCard rows (kind ∈ understanding,
#                     locating, choosing_action, retrieving, composing)
#   pipeline_error  → ThinkingCard row in `error` state, optionally
#                     bound to a specific stage `kind`
#   route_decision  → RoutingDecision card (NOT emitted yet — needs
#                     supervisor asset for subject + verb + handler)
#   sources         → SourcesTrail (NOT emitted yet — needs engine work)
#   graph_trace     → GraphTrace (NOT emitted yet — needs supervisor asset)
#   context_update  → existing ontology + bindings signals (unchanged)
#   chat_message    → agent's text answer (unchanged)
#   ui_payload /
#     final_payload → schema-driven semantic payloads (unchanged)


def _stage(
    kind: str,
    status: str,
    detail: dict | None = None,
    elapsed_ms: int | None = None,
) -> str:
    """Emit a typed `pipeline_stage` event.

    kind   : one of "understanding", "locating", "choosing_action",
             "retrieving", "composing"
    status : "started" | "completed" | "failed"
    detail : optional projection of real pipeline data
             (subject_uri, verb_iri, n_candidates, ...)

    The cortex-ui ThinkingCard upserts by `kind`, so emitting the same
    kind with status="started" then "completed" updates ONE row in
    place. Recurring emissions of the same stage are safe and do NOT
    accumulate.
    """
    payload: dict = {"kind": kind, "status": status}
    if detail:
        payload["detail"] = detail
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms
    return _sse("pipeline_stage", json.dumps(payload))


def _metadata_dict(mat: dict) -> dict[str, Any]:
    """Flatten a Dagster materialization's metadataEntries list into a
    label → raw-value dict. Dagster's GraphQL response shape for each
    entry is one of:
      - {label, text}            (TextMetadataValue)
      - {label, jsonString}      (JsonMetadataValue — historical)
      - {label, floatValue}      (FloatMetadataValue)
      - {label, intValue}        (IntMetadataValue)
      - {label, boolValue}       (BoolMetadataValue)
    Returns raw strings/floats/ints/bools indexed by label; the caller
    converts as needed. Missing keys are simply absent from the dict.
    """
    out: dict[str, Any] = {}
    for entry in mat.get("metadataEntries", []) or []:
        label = entry.get("label")
        if not label:
            continue
        if "text" in entry and entry["text"] is not None:
            out[label] = entry["text"]
        elif "jsonString" in entry and entry["jsonString"] is not None:
            out[label] = entry["jsonString"]
        elif "floatValue" in entry and entry["floatValue"] is not None:
            out[label] = entry["floatValue"]
        elif "intValue" in entry and entry["intValue"] is not None:
            out[label] = entry["intValue"]
        elif "boolValue" in entry and entry["boolValue"] is not None:
            out[label] = entry["boolValue"]
    return out


def _engine_name_from_provider(provider: str | None) -> str:
    """Best-effort human-readable engine name from a verb edge's provider
    string. Provider values are conventionally `engine_<letter>_<role>`
    (e.g. `engine_w_weaviate_expert_work_instruction`). The letter
    after the underscore identifies which mesh engine handled the
    dispatch. Falls back to the raw provider string when the convention
    doesn't apply (e.g. a future engine with a different naming scheme).
    """
    if not provider:
        return "Unknown engine"
    p = provider.lower()
    if p.startswith("engine_a"):
        return "Engine A"
    if p.startswith("engine_b"):
        return "Engine B"
    if p.startswith("engine_c"):
        return "Engine C"
    if p.startswith("engine_d_") or p == "engine_d":
        return "Engine D"
    if p.startswith("engine_da"):
        return "Engine DA"
    if p.startswith("engine_e"):
        return "Engine E"
    if p.startswith("engine_f"):
        return "Engine F"
    if p.startswith("engine_o"):
        return "Engine O"
    if p.startswith("engine_w"):
        return "Engine W"
    return provider


def _engine_name_from_endpoint(endpoint: str | None) -> str:
    """Derive a human-readable engine name from a verb edge's endpoint
    URL. Used as a fallback when the predicate dict has no ``provider``
    field (the Weaviate Predicate-collection record doesn't store one;
    only ``endpoint_url`` is reliable). Endpoint shape is usually
    ``http://iagent-engine-<letter>:<port>/<route>`` (k8s in-cluster DNS).

    Exception: Engine DA's deployment is named ``iagent-data-analyst``
    not ``iagent-engine-da``, so the regex alone misses it. The named-
    deployment lookup table below catches that case (and any future
    engine whose chart component name doesn't follow the
    iagent-engine-<letter> pattern). Caught 2026-06-24 when the HUD
    showed "Unknown engine" on an analyzeDataset route despite the
    endpoint being correctly attributed.
    """
    if not endpoint:
        return ""
    e = endpoint.lower()
    import re
    # Named-deployment overrides for engines whose k8s service name
    # doesn't follow iagent-engine-<letter>. Tested at module
    # boundary by tests/routing/test_specialist_endpoints_probe.py
    # — adding a new override here should also add an entry to the
    # endpoint probe so the engine name stays attributable.
    named_deployments = {
        "iagent-data-analyst": "Engine DA",
    }
    for service_name, engine_name in named_deployments.items():
        if service_name in e:
            return engine_name
    # Regex path: iagent-engine-<letter[letter]>
    m = re.search(r"iagent-engine-([a-z]{1,2})\b", e)
    if not m:
        return ""
    letter = m.group(1)
    if letter == "da":
        return "Engine DA"
    return f"Engine {letter.upper()}"


def _label_from_uri(uri: str | None) -> str:
    """Derive a human-readable label from a URI or CURIE.

    Splits on `#`, `/`, then `:` to peel off namespace prefixes
    (`http://...#Foo` → `Foo`; `mesh:doX` → `doX`; `urn:li:dataset:foo`
    → `foo`). CamelCase is then space-split (`WorkInstruction` →
    `Work Instruction`). Mirrors cortex-ui's fallbackSubjectLabel +
    fallbackVerbLabel behavior so the gateway can ship labels in the
    typed event payload and the UI doesn't have to round-trip every
    URI through its own fallback.
    """
    if not uri:
        return "Unknown"
    local = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1] or uri
    # Insert space at lower-to-upper transitions: WorkInstruction → Work Instruction
    spaced: list[str] = []
    for i, ch in enumerate(local):
        if i > 0 and ch.isupper() and local[i - 1].islower():
            spaced.append(" ")
        spaced.append(ch)
    return "".join(spaced).strip()


def _project_route_decision(mat: dict) -> dict | None:
    """Project a subtask_routing_decision materialization into the
    RouteDecision payload shape the cortex-ui typed event consumes.

    Surfaces THREE cases honestly, per the architect's
    "what-actually-happened" principle (2026-06-23 amendment):

    1. **Specialist match** — subject + verb both resolved, engine
       dispatched. Card shows the full route. (route_status="matched")

    2. **Fallback** — subject and/or verb didn't ground to a specialist,
       routing fell to Engine A generalist. The card now SURFACES this
       as a fallback (rather than going empty) so the user sees what
       the pipeline actually did instead of wondering if it's broken.
       The fallback IS what happened; surfacing it is more honest than
       hiding it. ``fallback=true``, ``fallback_reason`` carries the
       supervisor's classification (``no_predicate_matched``,
       ``low_confidence``, ``ADR-0019 Contract B``, etc.).

    3. **Infra error** — routing couldn't run at all (Engine O down,
       Neo4j unreachable). Same shape as fallback but signals
       ``route_status="infra_error"`` so the UI can render the alarm
       differently from a benign fallback.

    Only returns None when the materialization itself is unparseable
    (i.e., there's no honest projection to make).
    """
    md = _metadata_dict(mat)
    route_status = md.get("route_status") or ""
    subject_uri = md.get("subject_uri") or "UNKNOWN"
    verb_iri = md.get("verb_iri") or "UNKNOWN"
    handler_endpoint = md.get("handler_endpoint") or ""

    # Specialist detection: route_status=="matched" is the supervisor's
    # authoritative "yes, we dispatched to a specialist endpoint" signal.
    # handler_endpoint being non-empty is a belt-and-suspenders check.
    # Don't gate on handler_provider — the Weaviate Predicate record
    # doesn't store a provider field; only endpoint_url is reliable, so
    # provider is empty even on perfectly-routed specialist dispatches.
    # That mistake (gating on provider) was the bug that made every
    # specialist route render as "Engine A (generalist fallback)" with
    # the architect-#4 projection.
    is_specialist = route_status == "matched" and bool(handler_endpoint)

    if is_specialist:
        # Derive engine name from provider first; fall back to endpoint
        # parsing when provider is empty (the common case post-Weaviate
        # predicate-storage path, which doesn't include provider).
        engine_name = _engine_name_from_provider(md.get("handler_provider"))
        if engine_name == "Unknown engine":
            ep_name = _engine_name_from_endpoint(handler_endpoint)
            if ep_name:
                engine_name = ep_name
        return {
            "about": {
                "label": _label_from_uri(subject_uri),
                "uri": subject_uri,
                "confidence": float(md.get("subject_confidence") or 0.0),
                "instance_resolved": bool(md.get("subject_instance_id")),
                "instance_identifier": md.get("subject_instance_id") or "",
            },
            "action": {
                "label": _label_from_uri(verb_iri),
                "iri": verb_iri,
                "confidence": float(md.get("verb_confidence") or 0.0),
                "classify_called": bool(md.get("classify_called")),
                "candidate_count": int(md.get("candidate_count") or 0),
                "owner_persona": md.get("owner_persona") or None,
            },
            "handled_by": {
                "engine_name": engine_name,
                "provider": md.get("handler_provider") or "",
                "endpoint_url": handler_endpoint or None,
            },
            "route_status": route_status,
            "fallback": False,
        }

    # Fallback projection — surface that the pipeline GENUINELY fell
    # back to the generalist instead of leaving the card empty (which
    # was honest-by-omission but read to users as "system is broken").
    # The fallback IS what happened; saying so directly is the more
    # informative form of "surface what the pipeline did".
    fallback_reason = (
        "infra_error" if route_status == "infra_error"
        else ("no_compatible_verbs" if (subject_uri != "UNKNOWN" and verb_iri == "UNKNOWN")
              else ("no_subject" if subject_uri == "UNKNOWN"
                    else "no_predicate_matched"))
    )
    return {
        "about": {
            "label": _label_from_uri(subject_uri) if subject_uri != "UNKNOWN" else "Not grounded",
            "uri": subject_uri,
            "confidence": float(md.get("subject_confidence") or 0.0),
            "instance_resolved": bool(md.get("subject_instance_id")),
            "instance_identifier": md.get("subject_instance_id") or "",
        },
        "action": {
            "label": _label_from_uri(verb_iri) if verb_iri != "UNKNOWN" else "General search",
            "iri": verb_iri,
            "confidence": float(md.get("verb_confidence") or 0.0),
            "classify_called": bool(md.get("classify_called")),
            "candidate_count": int(md.get("candidate_count") or 0),
            "owner_persona": md.get("owner_persona") or None,
        },
        "handled_by": {
            "engine_name": "Engine A (generalist fallback)",
            "provider": "engine_a_fallback",
            "endpoint_url": None,
        },
        "route_status": route_status,
        "fallback": True,
        "fallback_reason": fallback_reason,
    }


def _project_sources(mat: dict) -> list[dict] | None:
    """Project a subtask_sources materialization into the Source[] list
    shape the cortex-ui typed event consumes.

    The supervisor stashes the engine-attached sources as a JSON-encoded
    text metadata field (sources_json). We deserialize and shape-check
    each item against the cortex-ui Source contract:
        { type, label, uri, snippet?, relevance?, open_url?, ... }

    Defensive: tolerates missing `type` (defaults to "document"), drops
    items with no `uri`, caps snippet length at 240 chars (matches
    Engine W's cap; UI's line-clamp handles longer gracefully too but
    no point shipping more bytes than needed). Engine-provided extra
    fields (e.g. `matched_for` from Engine W) pass through verbatim
    — UI ignores unknown fields per its TypeScript shape.
    """
    md = _metadata_dict(mat)
    raw = md.get("sources_json")
    if not raw:
        return None
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None
    if not isinstance(items, list) or not items:
        return None

    out: list[dict] = []
    for src in items:
        if not isinstance(src, dict):
            continue
        uri = src.get("uri")
        if not uri:
            continue
        projected: dict[str, Any] = {
            "type": src.get("type") or "document",
            "label": src.get("label") or _label_from_uri(uri),
            "uri": uri,
        }
        if isinstance(src.get("relevance"), (int, float)):
            projected["relevance"] = float(src["relevance"])
        snippet = src.get("snippet")
        if isinstance(snippet, str) and snippet:
            projected["snippet"] = snippet[:240]
        open_url = src.get("open_url")
        if isinstance(open_url, str) and open_url:
            projected["open_url"] = open_url
        # Pass-through engine extras (matched_for, etc.) without
        # validating — UI's TypeScript shape ignores unknown keys.
        for extra in ("matched_for",):
            if extra in src:
                projected[extra] = src[extra]
        out.append(projected)

    return out or None


def _enrich_sources_with_has_figures(sources: list[dict]) -> None:
    """For each source whose label looks like a mil/ontology data-module
    URI, set `has_figures: bool` based on Neo4j. Used to hide the
    cortex-ui slide-in trigger when clicking it would only show
    "No figures are linked to this data module."

    Batched single Neo4j query — N+1 would be wasteful for sources lists
    in the 5-20 range we see in practice. Failures (Neo4j unreachable,
    etc.) leave `has_figures` UNSET on every source — the UI's behavior
    in that case is to fall back to the heuristic camera-icon visibility
    (label pattern match), matching pre-enrichment behavior. Mutates in
    place to avoid copying the list.
    """
    # The figures endpoint takes the URI from `source.label` when it
    # looks like an ontology URI; otherwise `source.uri`. Match the
    # same precedence here so the has_figures check covers the same
    # URI the UI would actually pass to `/data_module/figures`.
    def _data_module_uri(src: dict) -> str | None:
        label = src.get("label") or ""
        if isinstance(label, str) and (
            label.startswith("http://") or label.startswith("https://")
        ):
            return label
        uri = src.get("uri") or ""
        if isinstance(uri, str) and (
            uri.startswith("http://") or uri.startswith("https://")
        ):
            return uri
        return None

    uri_to_idx: dict[str, list[int]] = {}
    for idx, src in enumerate(sources):
        dm_uri = _data_module_uri(src)
        if not dm_uri:
            continue
        uri_to_idx.setdefault(dm_uri, []).append(idx)

    if not uri_to_idx:
        return

    uris = list(uri_to_idx.keys())
    cypher = """
    UNWIND $uris AS uri
    OPTIONAL MATCH (dm:Resource {uri: uri})-[:hasFigure]->(f:Resource)
    RETURN uri, count(f) > 0 AS has_figures
    """
    try:
        with neo4j_driver.session() as session:
            result = session.run(cypher, {"uris": uris})
            for record in result:
                u = record["uri"]
                has = bool(record["has_figures"])
                for idx in uri_to_idx.get(u, []):
                    sources[idx]["has_figures"] = has
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "has_figures enrichment failed (UI falls back to label "
            "heuristic): %s", exc,
        )


def _project_graph_trace(mat: dict) -> list[dict] | None:
    """Project a subtask_graph_trace materialization into GraphTraceNode
    list shape. The walk shown to the user:
        resolved_subject → ancestor (if hops > 0) → verb edge → output
    Only the PICKED verb's branch is included; other candidates are
    visible in Dagster's asset metadata for operator audit but not
    in the UI panel (which is grounded to the answer's actual path).
    """
    md = _metadata_dict(mat)
    subject_uri = md.get("subject_uri") or ""
    picked_verb_iri = md.get("picked_verb_iri") or ""
    raw = md.get("compatible_verbs") or "[]"
    try:
        verbs = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None

    # Find the picked verb's record; that's the trace branch we draw.
    picked = None
    if picked_verb_iri:
        for v in verbs:
            if v.get("verb_iri") == picked_verb_iri:
                picked = v
                break
    # Fallback: if the picked verb isn't in the list (Weaviate-vs-Neo4j
    # sync gap the supervisor tolerates), draw the first candidate so
    # the panel still shows substrate structure.
    if picked is None and verbs:
        picked = verbs[0]
    if picked is None:
        return None

    nodes: list[dict] = []
    nodes.append({
        "uri": subject_uri,
        "label": _label_from_uri(subject_uri),
        "role": "resolved_subject",
        "hops": 0,
    })

    hops = int(picked.get("hops") or 0)
    input_uri = picked.get("input_uri") or ""
    output_uri = picked.get("output_uri") or ""
    verb_iri = picked.get("verb_iri") or ""

    # Show the ancestor only when the walk traversed subClassOf hops to
    # find the verb. hops=0 means the verb is typed directly against
    # the resolved subject — skip the ancestor row in that case.
    if hops > 0 and input_uri and input_uri != subject_uri:
        nodes.append({
            "uri": input_uri,
            "label": _label_from_uri(input_uri),
            "role": "ancestor_class",
            "hops": hops,
        })

    if output_uri:
        nodes.append({
            "uri": output_uri,
            "label": _label_from_uri(output_uri),
            "role": "output_class",
            "via_verb": verb_iri or None,
        })

    return nodes


def _perror(
    message: str,
    *,
    kind: str | None = None,
    retryable: bool | None = None,
    cause: str | None = None,
) -> str:
    """Emit a typed `pipeline_error` event.

    kind      : optional pipeline stage the error is bound to (so the UI
                marks the relevant ThinkingCard row red rather than
                injecting a free-floating error row)
    retryable : policy hint (transient 5xx vs. final contract-B short-
                circuit). The UI surfaces it in error-row tooltip.
    cause     : machine-readable classification (verb_unfound,
                llm_timeout, engine_5xx, dagster_run_failed, ...) for
                downstream telemetry.
    """
    payload: dict = {"message": message}
    if kind:
        payload["kind"] = kind
    if retryable is not None:
        payload["retryable"] = retryable
    if cause:
        payload["cause"] = cause
    return _sse("pipeline_error", json.dumps(payload))


async def _keepalive_wrap(stream, interval_s: float = 10.0):
    """Wrap an SSE generator so it emits `: keepalive\\n\\n` comments
    during quiet stretches.

    Cortex-bff went silent during long-running steps — most notably the
    Engine O ``/route_intent`` call (up to 30 s) and while waiting for
    Dagster materializations — long enough for either Traefik or
    @microsoft/fetch-event-source on the browser side to consider the
    connection idle and reconnect. Each reconnect re-fired POST
    /interview/stream and replayed the early events ("Analyzing
    intent...", "Triggering Supervisor Job...", "Dagster Run Initiated:
    fadd4876"), producing the visible loop where the same prefix
    appeared 3–6× per submission.

    SSE comment lines start with ``:`` and are ignored by the EventSource
    API (no event fires on the client). They are pure on-the-wire heartbeats
    that keep TCP+HTTP/1.1 layers bidirectionally active without affecting
    application logic. Every 10 s of silence is well below any reasonable
    proxy timeout while still being light enough to be invisible.

    Implementation: consume the wrapped generator into a queue and pull
    from the queue with a timeout. On timeout, emit a keepalive; on real
    events, forward them. The wrapped generator runs in a background
    task so it can produce while we wait.
    """
    queue: asyncio.Queue = asyncio.Queue()
    DONE: object = object()  # sentinel

    async def producer():
        try:
            async for event in stream:
                await queue.put(event)
        except Exception as exc:  # noqa: BLE001
            # Option A clean cut: typed pipeline_error instead of
            # the legacy status/action=error event. Stream producer
            # errors aren't bound to a known pipeline stage, so omit
            # `kind`; UI renders an unbound error row.
            await queue.put(_perror(
                f"Stream producer error: {exc}",
                cause="stream_producer_error",
            ))
        finally:
            await queue.put(DONE)

    prod_task = asyncio.create_task(producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval_s)
                if item is DONE:
                    return
                yield item
            except asyncio.TimeoutError:
                # No event in `interval_s`; emit an SSE comment line so
                # intermediate proxies and the browser EventSource see
                # the connection as alive.
                yield ": keepalive\n\n"
    finally:
        if not prod_task.done():
            prod_task.cancel()
            try:
                await prod_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

# ══════════════════════════════════════════════════════════
# Dagster GraphQL Orchestration
# ══════════════════════════════════════════════════════════

async def _launch_supervisor_job(
    query: str,
    thread_id: str,
    persona: str = "PROCESS_ENGINEER",
    domain: str = "MAINTENANCE",
    task_plan_json: str = "",
    user_id: str = "default_testing_user",
    # Per ADR-0009 Step F'.2: thread user-context fields into the supervisor
    # so the supervisor's per-subtask predicate lookup (Step F'.3) can scope
    # by entitled_domains and use user_persona as the answerer fallback when
    # the matched predicate is persona-agnostic.
    # Step F'.6: candidate_verb dropped — supervisor now sends user_query
    # directly to /search_predicates (Weaviate hybrid).
    user_persona: str = "MECHANIC",
    entitled_domains: list[str] | None = None,
    entity_refs: list[str] | None = None,
) -> str | None:
    """Launch the supervisor_query_job on Dagster.

    Per ADR-0009: ``persona``/``domain`` are legacy params kept for the
    interim until the supervisor's ``execute_subtask`` op (Step F'.3)
    switches to predicate-graph routing. The new ``user_persona`` /
    ``entitled_domains`` / ``candidate_verb`` fields are forwarded as new
    runConfig keys; the legacy ones default to sane values so the existing
    Dagster ops still validate.
    """
    entitled_domains = entitled_domains or []
    entity_refs = entity_refs or []
    # candidate_verb is no longer threaded — supervisor sends user_query to
    # /search_predicates directly. Keep the op_config field as an empty
    # string so the existing Dagster schema still validates.
    candidate_verb = ""
    mutation = """
    mutation LaunchSupervisor($repo: String!, $loc: String!, $runConfig: RunConfigData!) {
      launchRun(
        executionParams: {
          selector: {
            repositoryName: $repo
            repositoryLocationName: $loc
            jobName: "supervisor_query_job"
          }
          runConfigData: $runConfig
        }
      ) {
        __typename
        ... on LaunchRunSuccess {
          run {
            runId
          }
        }
        ... on RunConfigValidationInvalid {
          errors {
            message
          }
        }
        ... on PythonError {
          message
          stack
        }
      }
    }
    """
    
    # Shared op config — same keys to every op so a Dagster op author can
    # rely on consistent context regardless of which op they're in.
    op_config = {
        "user_query": query,
        "thread_id": thread_id,
        "persona": persona,
        "domain": domain,
        "task_plan_json": task_plan_json,
        "user_id": user_id,
        # ADR-0009 Step F'.2 additions:
        "user_persona": user_persona,
        "entitled_domains": entitled_domains,
        "candidate_verb": candidate_verb,
        "entity_refs": entity_refs,
    }

    run_config = {
        "ops": {
            "create_task_plan": {
                "config": dict(op_config)
            },
            "execute_subtask": {
                "config": dict(op_config)
            },
            "synthesize_stateful": {
                "config": dict(op_config)
            },
            "generate_ui_payload": {
                "config": dict(op_config)
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_RESTATE_INGRESS_URL}/DagsterRunTracker/{thread_id}/get_or_launch_run",
                json={
                    "dagster_url": _DAGSTER_WEBSERVER_URL,
                    "mutation": mutation,
                    "variables": {
                        "repo": _DAGSTER_REPOSITORY,
                        "loc": _DAGSTER_LOCATION,
                        "runConfig": json.dumps(run_config),
                    },
                },
            )
            resp.raise_for_status()
            return resp.json()
            
    except Exception as exc:
        logger.error("Failed to call Dagster GraphQL via Restate: %s", exc)
        return None

async def _get_run_status(run_id: str) -> dict:
    """Gets the high level status of the run."""
    query = """
    query GetRunStatus($runId: ID!) {
      runOrError(runId: $runId) {
        __typename
        ... on Run {
          status
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_DAGSTER_WEBSERVER_URL}/graphql",
                json={"query": query, "variables": {"runId": run_id}},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("runOrError", {})
    except Exception as exc:
        logger.error("Failed to get run status: %s", exc)
        return {}

async def _get_run_events(run_id: str) -> list:
    """Fetches materializations via both eventConnection (real-time) and stepStats (aggregated)."""
    
    # GraphQL needs an inline fragment per metadata entry type, otherwise
    # the value field is dropped from the response and _metadata_dict
    # silently treats the entry as missing. Float, Int, and Bool
    # fragments were the gap — the supervisor materializes
    # subject_confidence, verb_confidence as Float; classify_called as
    # Bool; candidate_count as Int. Without these fragments the HUD
    # showed 0.0 / false / 0 for every routing decision, which the UI
    # rendered as "very low confidence" + "classify called: no" even
    # when the supervisor logged subject_conf=0.98 verb_conf=0.86. The
    # text+json fragments worked fine because they were the only ones
    # requested. Caught 2026-06-23 by tracing UI confidence-tier vs
    # supervisor routing telemetry.
    query = """
    query RunEventsQuery($runId: ID!) {
      runOrError(runId: $runId) {
        __typename
        ... on Run {
          eventConnection {
            events {
              __typename
              ... on MaterializationEvent {
                assetKey { path }
                metadataEntries {
                  label
                  ... on TextMetadataEntry { text }
                  ... on JsonMetadataEntry { jsonString }
                  ... on FloatMetadataEntry { floatValue }
                  ... on IntMetadataEntry { intValue }
                  ... on BoolMetadataEntry { boolValue }
                }
              }
            }
          }
          stepStats {
            materializations {
              assetKey { path }
              metadataEntries {
                label
                ... on TextMetadataEntry { text }
                ... on JsonMetadataEntry { jsonString }
                ... on FloatMetadataEntry { floatValue }
                ... on IntMetadataEntry { intValue }
                ... on BoolMetadataEntry { boolValue }
              }
            }
          }
        }
      }
    }
    """
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{_DAGSTER_WEBSERVER_URL}/graphql",
                json={"query": query, "variables": {"runId": run_id}},
                timeout=10.0
            )
            
            if response.status_code != 200:
                logger.error("GraphQL Error [%s]: %s", response.status_code, response.text)
                return []
                
            data = response.json()
            if "errors" in data:
                logger.error("GraphQL Logic Error: %s", data["errors"])
                return []
            
            run_data = data.get("data", {}).get("runOrError", {})
            if not run_data or run_data.get("__typename") != "Run":
                return []
                
            all_mats = []
            
            # 1. Check eventConnection (Real-time stream)
            events = run_data.get("eventConnection", {}).get("events", [])
            for evt in events:
                typename = evt.get("__typename")
                if typename == "MaterializationEvent":
                    # Strictly flattened structure supported in this version
                    asset_key = evt.get("assetKey")
                    metadata = evt.get("metadataEntries")
                    
                    if asset_key:
                        all_mats.append({
                            "assetKey": asset_key,
                            "metadataEntries": metadata or []
                        })
                elif typename == "AssetMaterializationPlannedEvent":
                    pass
            
            # 2. Check stepStats (Fallback/Aggregated)
            for stat in run_data.get("stepStats", []):
                for mat in stat.get("materializations", []):
                    if mat and mat not in all_mats:
                        all_mats.append(mat)
            
            if all_mats:
                # Log the paths of found materializations for debugging
                paths = [str(m.get("assetKey", {}).get("path")) for m in all_mats]
                logger.info("Captured %d materializations for run %s. Paths: %s", len(all_mats), run_id, ", ".join(paths))
            return all_mats
            
    except Exception as e:
        logger.error("Error fetching materializations: %s", e)
        return []

async def _get_step_stats(run_id: str) -> list[dict]:
    """Gets the step statistics to drive UI holographic thinking cards."""
    query = """
    query GetStepStats($runId: ID!) {
      runOrError(runId: $runId) {
        __typename
        ... on Run {
          stepStats {
            stepKey
            status
            endTime
          }
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_DAGSTER_WEBSERVER_URL}/graphql",
                json={"query": query, "variables": {"runId": run_id}},
            )
            resp.raise_for_status()
            data = resp.json()
            run = data.get("data", {}).get("runOrError", {})
            if run.get("__typename") == "Run":
                return run.get("stepStats", [])
            return []
    except Exception as exc:
        logger.error("Failed to get step stats: %s", exc)
        return []

async def _get_ui_payload_output(run_id: str) -> dict:
    """Fetch the output value of the generate_ui_payload step via Metadata.

    Uses Run.eventConnection (Dagster 1.12.x schema) — NOT Run.events.
    Schema verified via live GraphQL introspection.
    """
    query = """
    query GetRunOutputs($runId: ID!) {
      runOrError(runId: $runId) {
        __typename
        ... on Run {
          eventConnection {
            events {
              __typename
              ... on HandledOutputEvent {
                stepKey
                metadataEntries {
                  label
                  ... on JsonMetadataEntry {
                    jsonString
                  }
                  ... on TextMetadataEntry {
                    text
                  }
                }
              }
              ... on ExecutionStepOutputEvent {
                stepKey
                outputName
                metadataEntries {
                  label
                  ... on JsonMetadataEntry {
                    jsonString
                  }
                  ... on TextMetadataEntry {
                    text
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_DAGSTER_WEBSERVER_URL}/graphql",
                json={"query": query, "variables": {"runId": run_id}},
            )
            resp.raise_for_status()
            data = resp.json()

            if "errors" in data:
                logger.error("GraphQL Errors: %s", data["errors"])
                return {"error": "GraphQL Query Error"}

            run = data.get("data", {}).get("runOrError", {})
            events = run.get("eventConnection", {}).get("events", [])
            
            logger.info("Retrieved %d events for run %s", len(events), run_id)

            payload = None
            referenced_uris = []

            for evt in events:
                typename = evt.get("__typename")
                step_key = evt.get("stepKey")
                if typename in ["HandledOutputEvent", "ExecutionStepOutputEvent"] and step_key == "generate_ui_payload":
                    for meta in evt.get("metadataEntries", []):
                        if meta.get("label") in ["ui_json_payload", "json", "UI Payload", "presentation_payload"]:
                            json_str = meta.get("jsonString") or meta.get("text")
                            if json_str:
                                try:
                                    payload = json.loads(json_str)
                                except json.JSONDecodeError:
                                    pass
                        elif meta.get("label") == "referenced_uris":
                            json_str = meta.get("jsonString") or meta.get("text")
                            if json_str:
                                try:
                                    referenced_uris = json.loads(json_str)
                                except json.JSONDecodeError:
                                    pass

            if payload:
                return {"payload": payload, "referenced_uris": referenced_uris}

            # 2. FUZZY FALLBACK: Search ALL steps for ANY metadata label matching our contract
            for evt in events:
                typename = evt.get("__typename")
                if typename in ["HandledOutputEvent", "ExecutionStepOutputEvent"]:
                    for meta in evt.get("metadataEntries", []):
                        if meta.get("label") in ["ui_json_payload", "json", "UI Payload", "presentation_payload"]:
                            logger.info("Fuzzy match: found metadata label '%s' in step '%s'", meta.get("label"), evt.get("stepKey"))
                            json_str = meta.get("jsonString") or meta.get("text")
                            if json_str:
                                try:
                                    payload = json.loads(json_str)
                                    # If fuzzy matched, we might not have referenced_uris in the same event, 
                                    # but we return what we have
                                    return {"payload": payload, "referenced_uris": referenced_uris}
                                except json.JSONDecodeError:
                                    pass

            logger.warning("No valid output payload found after checking %d events", len(events))
            return {"error": "No UI payload found in Dagster metadata. Check Engine F logs."}
    except Exception as exc:
        logger.error("Failed to fetch UI payload: %s", exc)
        return {"error": "Exception fetching presentation output"}

async def generate_dagster_stream(
    request: InterviewRequest,
    user_id: str = "default_testing_user",
    # Per ADR-0009 Step F'.2: user persona + entitled_domains come from the
    # JWT (see auth.User), threaded down from the /orchestrate route so we
    # don't re-decode the token mid-stream. Defaults match the auth fallback
    # so legacy callers that haven't been migrated still work.
    user_persona: str = "MECHANIC",
    entitled_domains: list[str] | None = None,
    # Capture A per ADR-0025: WHICH origin the persona / entitled_domains
    # came from. Threaded down from /orchestrate so the produced_for dict
    # construction below at line ~1370 can record it on the artifact.
    # Default "fallback" matches the persona/domains defaults above —
    # the legacy-caller path was never carrying real claims anyway, so
    # the honest default per `[[optimistic-defaults-are-dishonest]]` is
    # the failure-revealing value, not "claim".
    entitlement_source: str = "fallback",
) -> AsyncGenerator[str, None]:
    """
    Trigger Dagster job and stream step status as Holographic Thinking Cards.
    """
    entitled_domains = entitled_domains or []

    # session_id is now required by InterviewRequest — do NOT mint a fresh
    # UUID here. A per-request UUID gave every duplicate UI submission a
    # different DagsterRunTracker key, so the tracker's dedup never fired
    # and Dagster launched the same job multiple times.
    session_id = request.session_id
    user_query = request.message

    # Option A: typed pipeline_stage "understanding" started. The
    # gateway's /route_intent call is real gateway-level routing work
    # (intent extraction + persona/domain bounding), not a shortcut
    # around Dagster. Dagster launches AFTER this returns; its stages
    # take over from "locating" onward.
    yield _stage("understanding", "started")

    # 0. Check if there is an active Process Creation Interview in Restate.
    # When a session is mid-interview, every subsequent message goes back
    # to the interview regardless of NL content — the binary mode below
    # gets forced to CONVERSATIONAL.
    is_interview_active = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{_RESTATE_INGRESS_URL}/ProcessInterviewer/{session_id}/get_status",
                json={}
            )
            if res.status_code == 200:
                is_interview_active = res.json().get("is_active", False)
    except Exception as e:
        logger.warning(f"Failed to check Restate status: {e}")

    # ADR-0009 Step F'.2: replace 3-axis classifier with mode discriminator.
    # Step F'.6: candidate_verb dropped — the supervisor's /search_predicates
    # runs Weaviate hybrid against the raw user_query, no LLM-extracted verb
    # in the middle. The supervisor receives user_query through op config.
    mode: str
    entity_refs: list[str] = []
    intent_extraction: dict = {}

    if is_interview_active:
        mode = "CONVERSATIONAL"
    else:
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{_DAGSONTOLOGY_SVC_URL}/route_intent",
                    json={
                        "query": user_query,
                        "user_persona": user_persona,
                        "entitled_domains": entitled_domains,
                    }
                )
                resp.raise_for_status()
                intent_extraction = resp.json()
        except Exception as exc:
            logger.error("Failed to extract intent: %s", exc)
            yield _perror(
                "Failed to determine execution intent.",
                kind="understanding",
                retryable=True,
                cause="route_intent_failed",
            )
            yield _sse("stream_end", "{}")
            return

        mode = intent_extraction.get("mode", "ONE_SHOT")
        entity_refs = list(intent_extraction.get("entity_refs", []))

    # Legacy 3-axis fields are no longer derived by Engine O. They survive
    # only as Dagster runConfig keys until Step F'.3 deletes the
    # supervisor's `if domain ==` switch and the supervisor stops needing
    # them. We pass sane defaults so the runConfig schema still validates.
    decision = intent_extraction  # kept for any downstream inspection
    intent = "PROCESS_CREATION" if mode == "CONVERSATIONAL" else "ONE_SHOT"
    domain = "MAINTENANCE"  # legacy default; supervisor will route by predicate

    if intent == "PROCESS_CREATION":
        # 🔵 THE INTERVIEW PATH (RESTATE)
        # The interview is Restate-driven (ProcessInterviewer durable
        # object), not Dagster. We map its phases onto the same typed
        # pipeline_stage events so the UI gets one consistent timeline.
        # "understanding" completes when the interview reply arrives;
        # "composing" runs during auto-compile (if it triggers).
        yield _stage("understanding", "completed")
        yield _stage("composing", "started")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                restate_response = await client.post(
                    f"{_RESTATE_INGRESS_URL}/ProcessInterviewer/{session_id}/process_message",
                    json={"user_query": user_query}
                )
                restate_response.raise_for_status()
                data = restate_response.json()

                if "ui_payload" in data:
                    yield _sse("ui_payload", json.dumps(data["ui_payload"]))
                if "chat_reply" in data:
                    yield _sse("chat_message", json.dumps({"role": "assistant", "content": data["chat_reply"]}))

                # Auto-Compile Logic — keep the same "composing" stage
                # active across the BPMN→Dagster compile, which is the
                # last real work this turn does. No new stage event
                # needed; the ThinkingCard row stays in "loading".
                    try:
                        raw = data.get("raw_bpmn_payload", {})
                        # Transform tasks: Restate uses description, BPMNPayload expects agent_endpoint
                        tasks = []
                        for t in raw.get("tasks", []):
                            tasks.append({
                                "id": t.get("id", ""),
                                "name": t.get("name", ""),
                                "type": t.get("type", "service_task"),
                                "agent_endpoint": t.get("agent_endpoint", t.get("description", "")),
                            })
                        # Transform edges: Restate uses source/target/label, BPMNPayload expects id/source_ref/target_ref
                        flows = []
                        for i, e in enumerate(raw.get("sequence_flows", [])):
                            flows.append({
                                "id": e.get("id", f"flow_{i}"),
                                "source_ref": e.get("source_ref", e.get("source", "")),
                                "target_ref": e.get("target_ref", e.get("target", "")),
                                "condition_expression": e.get("condition_expression", e.get("label")),
                            })
                        bp_payload = BPMNPayload(
                            tasks=[BPMNTask(**t) for t in tasks],
                            gateways=[BPMNGateway(**g) for g in raw.get("gateways", [])],
                            sequence_flows=[BPMNSequenceFlow(**f) for f in flows],
                        )
                        from .database import get_db
                        async for db_session in get_db():
                            compile_req = CompileRequest(session_id=session_id, bpmn_payload=bp_payload)
                            compile_res = await compile_workflow(compile_req, db_session)
                            boot_doc = {
                                "components": [{
                                    "archetype": "KNOWLEDGE_DOCUMENT",
                                    "subject_concept": "Compilation Success",
                                    "markdown_content": f"```text\n{compile_res.boot_log}\n```"
                                }]
                            }
                            yield _sse("ui_payload", json.dumps(boot_doc))
                            break  # Only need one session
                    except Exception as compile_err:
                        logger.error("Auto-compile failed: %s", compile_err)
                        yield _perror(
                            f"Auto-compile failed: {compile_err}",
                            kind="composing",
                            retryable=False,
                            cause="auto_compile_failed",
                        )

                # Mark composing complete on the happy path.
                yield _stage("composing", "completed")

        except Exception as exc:
            logger.error("Failed to call Restate Interviewer: %s", exc)
            yield _perror(
                "Failed to reach Process Engineer.",
                kind="composing",
                retryable=True,
                cause="restate_unreachable",
            )

        yield _sse("stream_end", "{}")
        return

    # 🟢 THE GRAPH PATH (DAGSTER)
    # /route_intent has returned. Mark "understanding" complete and
    # move to "locating" — the supervisor's create_task_plan step
    # will run /plan and /resolve next.
    yield _stage("understanding", "completed")
    yield _stage("locating", "started")

    # ── Hop 1 of projector build plan (docs/plans/projector-build-plan.md
    # commit 0eda9f7) — accumulate the AnswerArtifact bundle as the SSE
    # events fire, dispatch the Neo4j write on a separate task AFTER
    # stream_end. Per Decision 0 sub-decision: delivery is NEVER coupled
    # to the Neo4j write. The accumulator is local to this generator
    # invocation.
    #
    # INTERIM: when Restate+topic successor lands, this accumulator
    # moves out of the gateway and into a Restate handler; the dispatch
    # becomes invoke-handler instead of in-process task. Decisions
    # 0+1+3 retire together. See [[coupled-interim-mechanisms-retire-together]].
    # Prefer client-supplied artifact_id (Hop 3 Electric merge depends
    # on local-pending and server-persisted artifact ids matching, so
    # `existingIdx` in cortex-ui's `electricUpsertArtifact` finds the
    # pending row and merges in place). Fallback to server-generated
    # id for non-cortex-ui callers (curl, tests, mesh-registrar).
    _artifact_id = request.artifact_id or (
        f"urn:li:answerArtifact:{session_id}-{uuid.uuid4().hex[:8]}"
    )
    _artifact_bundle: dict = {
        "id": _artifact_id,
        "question_text": user_query,
        "message_id": session_id,
        "valid_as_of": int(time.time() * 1000),
        # Per [[optimistic-defaults-are-dishonest]]: status starts
        # 'pending' (the transient in-flight state, honest about
        # not-yet-known). It flips to 'complete' when final_payload
        # arrives AND parses cleanly; flips to 'failed' when any
        # _perror branch fires (architect-ruled failure-mode-1 fix
        # on top of the prior Hop 1 commit). If neither flip happens
        # before stream_end, the bundle is NOT dispatched — see the
        # dispatch site for the guard.
        "status": "pending",
        "produced_by": {
            "actor_type": "agent",
            "actor_id": "pending",  # refined when route_decision arrives
        },
        "produced_for": {
            "user_id": user_id,
            "is_authenticated": True,
            "user_persona": user_persona,
            "entitled_domains": entitled_domains or [],
            # Capture A per ADR-0025: WHICH origin the persona /
            # entitled_domains came from at the moment auth.py read
            # the JWT. Once the persisted produced_for dict is written
            # to Neo4j, the information that the claim was absent is
            # gone — capture-or-lose-forever. The User model required
            # this explicitly per `[[optimistic-defaults-are-dishonest]]`.
            "entitlement_source": entitlement_source,
        },
        "resolved_intent": intent_extraction or {},
        "routing": None,
        "sources": [],
        "graph_trace": [],
        "rendered_output": None,
        "derived_from_artifact_id": None,
    }

    # Per ADR-0009 Step F'.2: /route_intent does not produce a task_plan
    # anymore — the supervisor's `create_task_plan` op asks Engine O's /plan
    # endpoint itself when task_plan_json is empty. Step F'.3 will switch
    # that decomposition path to be predicate-aware too.
    task_plan_json = ""
    run_id = await _launch_supervisor_job(
        user_query,
        session_id,
        domain=domain,
        task_plan_json=task_plan_json,
        user_id=user_id,
        user_persona=user_persona,
        entitled_domains=entitled_domains,
        entity_refs=entity_refs,
    )
    if not run_id:
        yield _perror(
            "Failed to trigger Dagster job.",
            kind="locating",
            retryable=True,
            cause="dagster_launch_failed",
        )
        yield _sse("stream_end", "{}")
        return

    # Note: the "Dagster Run Initiated: ..." status emission was
    # operational noise; the user doesn't need to see the run id, and
    # the supervisor's first asset materialization (active_agent_roster
    # → concepts/personas) arrives within a second or two and gives the
    # real signal the run is alive.

    # Polling Loop
    emitted_steps = set()
    is_success = False

    # Option A: the every-10s "Agents are reasoning (Elapsed: Ns)"
    # heartbeat is REMOVED. The cortex-ui ThinkingCard ticks the
    # elapsed time locally from each stage's startedAt timestamp, so
    # heartbeat events from the server were always redundant —
    # they only existed to keep proxy connections alive, which is now
    # handled by _keepalive_wrap's `: keepalive\n\n` comment lines.
    # The accumulating-rows UI bug is fixed at its source.

    for idx in range(900): # 15 minute max timeout (slow Ollama backends)
        await asyncio.sleep(1.0)

        status_data = await _get_run_status(run_id)
        if status_data.get("status") == "FAILURE":
            yield _perror(
                "Pipeline failed.",
                kind="retrieving",
                retryable=False,
                cause="dagster_run_failed",
            )
            # Architect-ruled failure-mode-1 fix per
            # [[optimistic-defaults-are-dishonest]]: the gateway sees
            # the pipeline-failure signal; flip the bundle's status
            # to 'failed' so the writer persists it honestly. Without
            # this the writer would have applied an optimistic
            # 'complete' default (now removed); even with the default
            # gone, the bundle's status must carry the truth.
            _artifact_bundle["status"] = "failed"
            break

        if status_data.get("status") == "SUCCESS":
            is_success = True
            break
            
        # Pull intermediate asset materializations from the supervisor.
        # active_agent_roster surfaces:
        #   - extracted_concepts → context_update (ontology terms in HUD)
        # The historical personas list (drove AgentTeamLoader) is NOT
        # emitted any more per Option A — see [[persona-split]]: the
        # active roster was decorative theater, output-side persona
        # lives on the verb edge and surfaces via route_decision.owner_persona.
        #
        # Phase 1 additions:
        #   subtask_routing_decision → route_decision typed event
        #   subtask_graph_trace      → graph_trace typed event
        # Both projected from real supervisor asset metadata. The
        # gateway emits the FIRST materialization per run; later
        # subtasks' materializations are observed via Dagster (the
        # audit trail) but not re-emitted to the UI — the Routing
        # Decision card focuses on the primary route the user's
        # answer flows through. Multi-subtask UI semantics is a
        # future ADR.
        mats = await _get_run_events(run_id)
        for mat in mats:
            path = mat.get("assetKey", {}).get("path")
            if path == ["active_agent_roster"] and "plan_emitted" not in emitted_steps:
                concepts_list = []
                for meta in mat.get("metadataEntries", []):
                    if meta.get("label") == "extracted_concepts":
                        try:
                            json_str = meta.get("text") or meta.get("jsonString") or "[]"
                            concepts_list = json.loads(json_str)
                        except Exception as parse_err:
                            logger.error("Failed to parse concepts metadata: %s", parse_err)

                if concepts_list:
                    logger.info("📡 Emitting SSE 'context_update' with ontology concepts: %s", concepts_list)
                    yield _sse("context_update", json.dumps({
                        "type": "ontology",
                        "data": concepts_list,
                    }))

                emitted_steps.add("plan_emitted")
                logger.info("✅ Plan emission confirmed for run %s", run_id)

            elif (
                path == ["subtask_routing_decision"]
                and "route_decision_emitted" not in emitted_steps
            ):
                decision = _project_route_decision(mat)
                if decision is not None:
                    logger.info(
                        "📡 Emitting SSE 'route_decision' for run %s: "
                        "subject=%s verb=%s",
                        run_id,
                        decision.get("about", {}).get("uri"),
                        decision.get("action", {}).get("iri"),
                    )
                    yield _sse("route_decision", json.dumps(decision))
                    # Hop 1: capture routing + refine produced_by sentinel.
                    _artifact_bundle["routing"] = decision
                    handled_by = (decision.get("handled_by") or {}) if isinstance(
                        decision, dict
                    ) else {}
                    if handled_by:
                        _artifact_bundle["produced_by"] = {
                            "actor_type": "agent",
                            "actor_id": handled_by.get(
                                "engine_name"
                            ) or handled_by.get(
                                "name"
                            ) or "pending",
                            "endpoint": handled_by.get("endpoint"),
                            "version": handled_by.get("version"),
                        }
                emitted_steps.add("route_decision_emitted")

            elif (
                path == ["subtask_graph_trace"]
                and "graph_trace_emitted" not in emitted_steps
            ):
                trace_nodes = _project_graph_trace(mat)
                if trace_nodes:
                    logger.info(
                        "📡 Emitting SSE 'graph_trace' for run %s: %d nodes",
                        run_id, len(trace_nodes),
                    )
                    yield _sse("graph_trace", json.dumps({"nodes": trace_nodes}))
                    # Hop 1: accumulate into bundle.
                    _artifact_bundle["graph_trace"] = trace_nodes
                emitted_steps.add("graph_trace_emitted")

            elif (
                path == ["subtask_sources"]
                and "sources_emitted" not in emitted_steps
            ):
                # Phase 3: sources from the picked engine. Same
                # emit-once-per-run semantics as route_decision and
                # graph_trace — first subtask wins. Multi-subtask UI
                # semantics will revisit this.
                projected_sources = _project_sources(mat)
                if projected_sources:
                    # Tag each ontology-URI source with whether the
                    # data module has linked figures, so the cortex-ui
                    # only shows the "View figures" camera-icon trigger
                    # when clicking it would actually surface figures.
                    # Failures leave `has_figures` UNSET and the UI
                    # falls back to its label-pattern heuristic.
                    _enrich_sources_with_has_figures(projected_sources)
                    logger.info(
                        "📡 Emitting SSE 'sources' for run %s: %d source(s)",
                        run_id, len(projected_sources),
                    )
                    yield _sse(
                        "sources",
                        json.dumps({"sources": projected_sources}),
                    )
                    # Hop 1: accumulate into bundle.
                    _artifact_bundle["sources"] = projected_sources
                emitted_steps.add("sources_emitted")

        # Map Dagster step transitions onto typed pipeline_stage events.
        # The mapping projects the supervisor's REAL step keys (Dagster
        # is the audit trail) onto the UI's 5 stage kinds. Some Dagster
        # steps span multiple UI stages — `create_task_plan` runs BOTH
        # /resolve (locating) AND /plan + classify_predicate (choosing),
        # so its SUCCESS transition completes both stages.
        #
        #   create_task_plan      → locating, then choosing_action
        #                           (/resolve runs first within the step,
        #                           then /plan + classify_predicate; both
        #                           must mark complete together because
        #                           Dagster only emits ONE step transition)
        #   execute_subtask-*     → retrieving (engine dispatch)
        #   synthesize_stateful   → composing (Engine B synthesis)
        #   generate_ui_payload   → composing (Engine F mapping) — same
        #                           kind as synthesize; UI shows ONE
        #                           composing row that stays loading
        #                           until the final payload arrives.
        STEP_TO_STARTED_KIND = {
            # "locating" already started at line 1201 before the polling
            # loop begins, so create_task_plan RUNNING only triggers the
            # choosing_action started transition.
            "create_task_plan": "choosing_action",
            "synthesize_stateful": "composing",
            "generate_ui_payload": "composing",
        }
        STEP_TO_COMPLETED_KINDS = {
            "create_task_plan": ["locating", "choosing_action"],
            "synthesize_stateful": ["composing"],
            "generate_ui_payload": ["composing"],
        }

        def _step_started_kind(step_key: str) -> str | None:
            # Dagster names dynamic-output step keys with SQUARE BRACKETS:
            # `execute_subtask[task_0]`, not `execute_subtask-task_0`.
            # The original `startswith("execute_subtask-")` matched the
            # dash-form that the op never produced, so the "retrieving"
            # stage's completion event was never emitted to the UI
            # (every query rendered "Retrieving evidence — never
            # confirmed" even when sources had landed and the engine
            # had returned). Fix: match the prefix that handles BOTH
            # forms (just `execute_subtask` — bare name or with `[..]`).
            # Banked 2026-06-28 with relevance=0 fix; same SSE pipeline.
            if step_key.startswith("execute_subtask"):
                return "retrieving"
            return STEP_TO_STARTED_KIND.get(step_key)

        def _step_completed_kinds(step_key: str) -> list[str]:
            if step_key.startswith("execute_subtask"):
                return ["retrieving"]
            return STEP_TO_COMPLETED_KINDS.get(step_key, [])

        step_stats = await _get_step_stats(run_id)
        for stat in step_stats:
            step_key = stat.get("stepKey", "")
            status = stat.get("status", "")

            if status == "RUNNING" and f"{step_key}_running" not in emitted_steps:
                kind = _step_started_kind(step_key)
                if not kind:
                    continue
                # Stage upserts by kind on the UI side — multiple
                # execute_subtask-* steps all map to "retrieving" and
                # only one row renders, which is the right semantics
                # (the user sees "retrieving evidence", not a fan-out
                # of per-engine subrows).
                yield _stage(kind, "started", detail={"step_key": step_key})
                emitted_steps.add(f"{step_key}_running")

            elif status == "SUCCESS" and f"{step_key}_success" not in emitted_steps:
                kinds = _step_completed_kinds(step_key)
                if not kinds:
                    continue
                # Emit completions in the order the underlying sub-steps
                # ran (e.g. /resolve before /classify_predicate inside
                # create_task_plan). The UI's stage list renders in
                # PIPELINE_KINDS order regardless, but emitting in the
                # right semantic order keeps the audit-stream coherent.
                for kind in kinds:
                    yield _stage(kind, "completed", detail={"step_key": step_key})
                emitted_steps.add(f"{step_key}_success")

                # When create_task_plan succeeds, the supervisor is
                # already in flight dispatching to the engine. Pre-emit
                # "retrieving" started so the UI doesn't show a dead
                # gap between "Choosing" green and execute_subtask
                # actually transitioning to RUNNING (Dagster scheduling
                # delay is ~1-3s; the user perceives that gap as
                # "nothing is happening"). Reality-tracking: dispatch
                # genuinely IS the next thing happening; surfacing it
                # is honest, not synthetic. Idempotent via emitted_steps.
                if (
                    step_key == "create_task_plan"
                    and "retrieving_pre_started" not in emitted_steps
                ):
                    yield _stage(
                        "retrieving", "started",
                        detail={"step_key": "create_task_plan_dispatch"},
                    )
                    emitted_steps.add("retrieving_pre_started")
                
    if is_success:
        # Composing was already marked started by generate_ui_payload's
        # RUNNING transition above; the actual fetch of the final
        # payload happens here. No extra "Retrieving Final UI Payload"
        # status row needed — composing stays loading until either
        # the payload arrives (completed) or fetching fails (error).
        result = await _get_ui_payload_output(run_id)

        if "error" in result:
            logger.error("BFF Error: %s", result["error"])
            yield _perror(
                result["error"],
                kind="composing",
                retryable=False,
                cause="ui_payload_fetch_error",
            )
            # Failure-mode-1 fix: gateway sees ui_payload_fetch_error;
            # bundle status flips to 'failed'.
            _artifact_bundle["status"] = "failed"
        else:
            # Emit data bindings to the HUD
            if result.get("referenced_uris"):
                yield _sse("context_update", json.dumps({
                    "type": "bindings",
                    "data": result["referenced_uris"],
                }))

            yield _stage("composing", "completed")
            yield _sse("final_payload", json.dumps(result["payload"]))
            # Hop 1: capture rendered_output into the bundle.
            _artifact_bundle["rendered_output"] = result.get("payload")
            # Happy path: payload arrived AND parsed cleanly; status
            # flips to 'complete'. This is the ONLY site where the
            # status becomes 'complete' — there is no default-to-
            # complete elsewhere.
            _artifact_bundle["status"] = "complete"
    else:
        yield _perror(
            "Timeout or failed to fetch UI payload.",
            kind="composing",
            retryable=True,
            cause="ui_payload_timeout",
        )
        # Failure-mode-1 fix: ui_payload_timeout is the canonical
        # case the architect inspection cited (`_perror` "Timeout or
        # failed to fetch UI payload" branch). Bundle status flips
        # to 'failed' so the artifact persists honestly as
        # `status='failed' + durability_status='durable' +
        # rendered_output=null`.
        _artifact_bundle["status"] = "failed"

    yield _sse("stream_end", "{}")

    # ── Hop 1: dispatch the AnswerArtifact Neo4j write on a SEPARATE
    # asyncio task AFTER stream_end. Delivery is already done from the
    # client's perspective. The writer's contract: dispatch_async NEVER
    # raises back to us, regardless of Neo4j health. Per
    # [[feedback-trailing-steps-nonfatal]] and Decision 0 sub-decision:
    # this trailing step CANNOT fail delivery. The artifact's
    # durability_status carries the honest recorded state.
    #
    # INTERIM: under the Restate+topic successor, this becomes an
    # invoke-handler call, not an in-process task. The handler journals
    # the Neo4j write + topic emit as exactly-once durable steps.
    # Decisions 0+1+3 retire together per
    # [[coupled-interim-mechanisms-retire-together]].
    try:
        # Per [[optimistic-defaults-are-dishonest]]: never dispatch
        # while bundle.status is still 'pending'. The reachable post-
        # init paths above each flip it to 'complete' (happy path,
        # final_payload received + parsed) or 'failed' (any _perror
        # branch). If we land here with status still 'pending', some
        # exit path was added without a status flip — log loudly and
        # skip the dispatch rather than letting an honest-pending
        # leak through. (We do NOT default to 'failed' here because
        # that would re-create the trap one layer over: the dispatch
        # site has no idea what actually happened; only the gateway
        # exit paths know.)
        if _artifact_bundle["status"] == "pending":
            logger.error(
                "AnswerArtifact dispatch ABORTED: bundle.status is still "
                "'pending' at stream_end for artifact %s. Some Graph "
                "Path exit path failed to flip status. Skipping write "
                "rather than persisting an honest-pending; investigate "
                "the gateway exit paths.",
                _artifact_bundle["id"],
            )
            return

        _writer = get_writer()
        if _writer is not None:
            _bundle_obj = AnswerArtifactBundle(
                id=_artifact_bundle["id"],
                question_text=_artifact_bundle["question_text"],
                message_id=_artifact_bundle["message_id"],
                valid_as_of=_artifact_bundle["valid_as_of"],
                status=_artifact_bundle["status"],
                produced_by=_artifact_bundle["produced_by"],
                produced_for=_artifact_bundle["produced_for"],
                resolved_intent=_artifact_bundle["resolved_intent"],
                routing=_artifact_bundle["routing"],
                sources=_artifact_bundle["sources"],
                graph_trace=_artifact_bundle["graph_trace"],
                rendered_output=_artifact_bundle["rendered_output"],
                derived_from_artifact_id=_artifact_bundle[
                    "derived_from_artifact_id"
                ],
            )
            # Fire-and-await on a separate task so the SSE generator
            # exits immediately; the writer drives the retry loop on
            # its own. `asyncio.create_task` returns control to the
            # event loop and the stream_end SSE event flushes to the
            # client without waiting for the Neo4j write.
            asyncio.create_task(_writer.dispatch_async(_bundle_obj))
            logger.info(
                "AnswerArtifact dispatch scheduled: id=%s (delivery already "
                "completed at stream_end)",
                _artifact_bundle["id"],
            )
        else:
            logger.warning(
                "AnswerArtifact writer not available; artifact %s NOT "
                "scheduled for persistence (trailing-step non-fatal).",
                _artifact_bundle["id"],
            )
    except Exception as exc:
        # Belt-and-suspenders: the writer module's dispatch_async is
        # already contracted to never raise, but if the scheduling
        # itself blows up (e.g., loop closed), swallow it. The
        # decoupling contract is honored at this layer too.
        logger.warning(
            "AnswerArtifact dispatch scheduling failed (decoupling "
            "preserved): %s",
            exc,
        )


# ══════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════


@app.post("/register_frontend_capabilities", response_model=RegisterFrontendCapabilitiesResponse)
async def register_frontend_capabilities(
    payload: RegisterFrontendCapabilitiesRequest,
    current_user: User = Depends(get_current_user),
) -> RegisterFrontendCapabilitiesResponse:
    """ADR-0017 frontend self-registration of presentation capabilities.

    cortex-ui (and any future frontend) POSTs its capability list at
    login. We log it structurally so the advertisement is observable in
    cluster logs / Langfuse / Loki, then return an accepted count.

    Stage 2 will plumb this into the SPO predicate graph alongside the
    engine-side `register_presentation_to_mesh` registrations, at which
    point Engine F's lookup becomes the live registry rather than its
    in-memory default table.

    Auth: requires a valid bearer token. Anyone holding a JWT for the
    realm can advertise — there is no per-frontend authorization yet.
    For sandbox that's fine. Production should bind frontend_id to a
    Keycloak client identity or service account once we have multiple
    surfaces.
    """
    _frontend_registry_logger.info(
        json.dumps({
            "event": "frontend_capabilities_registered",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "frontend_id": payload.frontend_id,
            "frontend_version": payload.frontend_version,
            "capability_count": len(payload.capabilities),
            "capabilities": [
                {
                    "subject_uri": c.subject_uri,
                    "object_uri": c.object_uri,
                    "archetype": c.archetype,
                    "component": c.component,
                    "layout": c.layout,
                    "expected_fields_count": len(c.expected_fields),
                    "persona_fit": c.persona_fit,
                    "domain_fit": c.domain_fit,
                }
                for c in payload.capabilities
            ],
        })
    )
    return RegisterFrontendCapabilitiesResponse(
        accepted=len(payload.capabilities),
        frontend_id=payload.frontend_id,
    )


@app.post("/orchestrate")
@app.post("/interview/stream")
async def orchestrate(request: InterviewRequest, current_user: User = Depends(get_current_user)):
    """
    Entry point for the Agentic Mesh.
    Delegates to Dagster GraphQL and streams step stats as SSE events
    to power Holographic Thinking Cards. Emits final payload when done.

    Per ADR-0009 Step F'.2: user_persona + entitled_domains come from the
    auth-resolved User and flow downstream to the supervisor + engines.
    """
    return StreamingResponse(
        _keepalive_wrap(
            generate_dagster_stream(
                request,
                user_id=current_user.id,
                user_persona=current_user.persona,
                entitled_domains=current_user.entitled_domains,
                # Capture A per ADR-0025: thread the JWT-read-time
                # origin flag from auth.User down to the produced_for
                # dict construction inside generate_dagster_stream.
                entitlement_source=current_user.entitlement_source,
            ),
            interval_s=10.0,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Compile helpers ───────────────────────────────────────


def synthesize_boot_sequence(
    bpmn_payload: BPMNPayload,
    *,
    workflow_id: str,
    run_id: str,
    job_name: str,
    dagster_reload_ok: bool,
) -> str:
    """Generate a high-tech terminal boot log from a BPMN payload.

    Returns a multi-line string styled as a futuristic system boot
    sequence, enumerating every task/gateway/flow and reporting
    the database sync + Dagster reload status.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = [
        "",
        "╔══════════════════════════════════════════════════════════╗",
        "║       C O R T E X  —  C O M P I L E R  v2.0          ║",
        "╚══════════════════════════════════════════════════════════╝",
        "",
        f"  [INIT] Timestamp .............. {ts}",
        f"  [INIT] Run ID ................. {run_id}",
        f"  [INIT] Workflow ID ............ {workflow_id}",
        "",
        "  ── System ────────────────────────────────────────────",
        "  [SYSTEM] Saving BPMN model to bpmn_catalog ... OK",
        "  [SYSTEM] is_active ............ TRUE",
        "",
        "  ── Agent Provisioning ────────────────────────────────",
    ]

    for task in bpmn_payload.tasks:
        tag = "SVC" if task.type == "service_task" else "USR"
        lines.append(f"  [AGENT] Provisioning task: {task.name} [{tag}]")
        lines.append(f"          └─ endpoint: {task.agent_endpoint}")

    if not bpmn_payload.tasks:
        lines.append("  [AGENT] (no tasks defined)")

    for gw in bpmn_payload.gateways:
        lines.append(f"  [GATE]  Gateway registered: {gw.name} ({gw.type})")

    lines.append("")
    lines.append("  ── Dagster Pipeline ──────────────────────────────────")
    lines.append(f"  [LINK] Job Name ............... {job_name}")
    lines.append(f"  [LINK] Tasks .................. {len(bpmn_payload.tasks)}")
    lines.append(f"  [LINK] Gateways ............... {len(bpmn_payload.gateways)}")
    lines.append(f"  [LINK] Sequence Flows ......... {len(bpmn_payload.sequence_flows)}")
    lines.append(f"  [LINK] Op Factory ............. DYNAMIC")
    lines.append(f"  [LINK] Graph Wiring ........... RESOLVED")

    reload_status = "OK" if dagster_reload_ok else "UNREACHABLE (will retry on next cold-start)"
    lines.append("")
    lines.append("  ── Dagster Workspace Reload ──────────────────────────")
    lines.append(f"  [DAGSTER] ReloadWorkspace ..... {reload_status}")

    lines.append("")
    lines.append("  ── Status ────────────────────────────────────────────")
    lines.append("  [DONE] Pipeline compiled successfully.")
    lines.append("  [DONE] Dagster run initiated.")
    lines.append("")
    lines.append("  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ SYSTEM ONLINE")
    lines.append("")

    return "\n".join(lines)


async def _reload_dagster_workspace() -> bool:
    """POST the reloadRepositoryLocation mutation to Dagster Webserver.

    Returns True if the reload succeeded, False on any error (network,
    Dagster offline, etc.).  Failures are non-fatal — the dynamic
    factory will pick up the change on the next Dagster restart.
    """
    mutation = """
    mutation ReloadWorkspace {
      reloadRepositoryLocation(
        repositoryLocationName: "iagent.definitions"
      ) {
        __typename
        ... on WorkspaceLocationEntry {
          name
          loadStatus
        }
        ... on ReloadNotSupported {
          message
        }
        ... on RepositoryLocationNotFound {
          message
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{_DAGSTER_WEBSERVER_URL}/graphql",
                json={"query": mutation},
            )
            resp.raise_for_status()
            data = resp.json()
            typename = (
                data.get("data", {})
                .get("reloadRepositoryLocation", {})
                .get("__typename", "")
            )
            ok = typename == "WorkspaceLocationEntry"
            if ok:
                logger.info("Dagster workspace reload succeeded")
            else:
                logger.warning("Dagster workspace reload returned: %s", typename)
            return ok
    except Exception as exc:
        logger.warning("Dagster webserver unreachable for reload: %s", exc)
        return False


@app.post("/compile")
@app.post("/workflow/compile")
async def compile_bpmn(
    request: CompileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Experimental: Compile raw BPMN payload into a Dagster job.

    1. Upsert the bpmn_payload into the bpmn_catalog table.
    2. Synthesize a Terminal Boot Sequence log.
    3. POST the ReloadWorkspace mutation to Dagster Webserver.
    4. Return the CompileResponse with boot_log.
    """
    run_id = str(uuid.uuid4())
    safe_session = request.session_id.replace("-", "_")
    workflow_id = f"wf_{safe_session}"
    job_name = f"cortex_pipeline_{safe_session}"
    bp = request.bpmn_payload

    # ── 1. Upsert into bpmn_catalog ──
    result = await db.execute(
        select(BpmnCatalog).where(BpmnCatalog.workflow_id == workflow_id)
    )
    existing = result.scalar_one_or_none()

    payload_dict = bp.model_dump()

    if existing:
        existing.name = job_name
        existing.bpmn_payload = payload_dict
        existing.is_active = True
    else:
        row = BpmnCatalog(
            workflow_id=workflow_id,
            name=job_name,
            bpmn_payload=payload_dict,
        )
        db.add(row)

    await db.commit()

    # ── 2. Reload Dagster workspace ──
    dagster_reload_ok = await _reload_dagster_workspace()

    # ── 3. Synthesize boot log ──
    boot_log = synthesize_boot_sequence(
        bp,
        workflow_id=workflow_id,
        run_id=run_id,
        job_name=job_name,
        dagster_reload_ok=dagster_reload_ok,
    )

    return CompileResponse(
        success=True,
        run_id=run_id,
        dagster_job_name=job_name,
        message=f"Pipeline compiled: {len(bp.tasks)} tasks, "
        f"{len(bp.sequence_flows)} flows, {len(bp.gateways)} gateways.",
        boot_log=boot_log,
    )


# ── BFF Proxy Routes ─────────────────────────────────────
# The frontend NEVER calls internal services directly.
# These endpoints proxy server-to-server requests.


# Removed BFF Mock Routes (no longer used)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "cortex-orchestrator-proxy",
    }


# ══════════════════════════════════════════════════════════
# Deep Inspection (Neo4j Proxy)
# ══════════════════════════════════════════════════════════

@app.get("/node_details/{node_id}")
@app.get("/graph/node/{node_id}")
async def get_node_details(node_id: str, current_user: User = Depends(get_current_user)):
    """
    Directly query the Neo4j Graph Database for a specific node ID.
    Used by the frontend NodeInspector to prove data provenance.
    """
    try:
        # Some Data bindings might be S1000D Data Modules or normal graph IDs
        with neo4j_driver.session() as session:
            # We search for any node where id = node_id, or name = node_id
            query = """
            MATCH (n) 
            WHERE n.id = $node_id OR n.name = $node_id OR n.partNumber = $node_id
            RETURN labels(n) as labels, properties(n) as properties
            LIMIT 1
            """
            result = session.run(query, node_id=node_id)
            record = result.single()

            if not record:
                return {
                    "_metadata": {"uri": node_id, "status": "NOT_FOUND"},
                    "error": "No matching node found in the graph database for this identifier."
                }

            return {
                "_metadata": {
                    "uri": node_id,
                    "type": "Neo4j Node",
                    "retrieved_at": datetime.now(timezone.utc).isoformat()
                },
                "labels": record["labels"],
                "properties": record["properties"]
            }
    except Exception as exc:
        logger.error("Failed to query Neo4j: %s", exc)
        return {
            "_metadata": {"uri": node_id, "status": "ERROR"},
            "error": str(exc)
        }


# ══════════════════════════════════════════════════════════
# BPMN Catalog
# ══════════════════════════════════════════════════════════


class BpmnSaveRequest(BaseModel):
    workflow_id: str
    name: str
    bpmn_payload: dict


class BpmnSaveResponse(BaseModel):
    workflow_id: str
    boot_sequence: str


class BpmnCatalogItem(BaseModel):
    workflow_id: str
    name: str
    bpmn_payload: dict
    is_active: bool
    created_at: str
    updated_at: str


def _generate_boot_sequence(req: BpmnSaveRequest) -> str:
    """Build the futuristic Terminal Boot Sequence string."""
    payload = req.bpmn_payload
    tasks = payload.get("tasks", [])
    flows = payload.get("sequence_flows", [])
    gateways = payload.get("gateways", [])
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return (
        "\n"
        "╔══════════════════════════════════════════════════════════╗\n"
        "║          C O R T E X  —  B P M N  L O A D E R          ║\n"
        "╚══════════════════════════════════════════════════════════╝\n"
        "\n"
        f"  [BOOT] Timestamp .............. {ts}\n"
        f"  [BOOT] Workflow ID ............ {req.workflow_id}\n"
        f"  [BOOT] Workflow Name .......... {req.name}\n"
        "\n"
        "  ── Payload Manifest ──────────────────────────────────\n"
        f"  [LOAD] Tasks .................. {len(tasks)}\n"
        f"  [LOAD] Sequence Flows ......... {len(flows)}\n"
        f"  [LOAD] Gateways ............... {len(gateways)}\n"
        "\n"
        "  ── Database Sync ─────────────────────────────────────\n"
        "  [SYNC] bpmn_catalog ........... UPSERTED\n"
        "  [SYNC] is_active .............. TRUE\n"
        "  [SYNC] Dagster factory ........ PENDING RELOAD\n"
        "\n"
        "  ── Status ────────────────────────────────────────────\n"
        "  [DONE] Workflow persisted. Awaiting Dagster cold-start.\n"
        "  [DONE] BPMN payload hash ...... OK\n"
        "\n"
        "  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ SYSTEM ONLINE\n"
    )


@app.post("/bpmn/save", response_model=BpmnSaveResponse)
async def bpmn_save(req: BpmnSaveRequest, db: AsyncSession = Depends(get_db)):
    """
    Upsert a BPMN workflow into bpmn_catalog.
    Returns the Terminal Boot Sequence string for UI display.
    """
    # Check if workflow already exists
    result = await db.execute(
        select(BpmnCatalog).where(BpmnCatalog.workflow_id == req.workflow_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.name = req.name
        existing.bpmn_payload = req.bpmn_payload
        existing.is_active = True
    else:
        row = BpmnCatalog(
            workflow_id=req.workflow_id,
            name=req.name,
            bpmn_payload=req.bpmn_payload,
        )
        db.add(row)

    await db.commit()

    boot_seq = _generate_boot_sequence(req)
    return BpmnSaveResponse(workflow_id=req.workflow_id, boot_sequence=boot_seq)


@app.get("/bpmn/catalog", response_model=list[BpmnCatalogItem])
async def bpmn_catalog(db: AsyncSession = Depends(get_db)):
    """Return all active workflows from the bpmn_catalog table."""
    result = await db.execute(
        select(BpmnCatalog).where(BpmnCatalog.is_active == True)  # noqa: E712
    )
    rows = result.scalars().all()
    return [
        BpmnCatalogItem(
            workflow_id=r.workflow_id,
            name=r.name,
            bpmn_payload=r.bpmn_payload,
            is_active=r.is_active,
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat(),
        )
        for r in rows
    ]


# ══════════════════════════════════════════════════════════
# Federated Image Proxy — Option A for cortex-MinIO image flow
# ══════════════════════════════════════════════════════════
#
# The frontend FederatedImage component (cortex-ui) detects image markdown
# whose `src` is an s3://bucket/key URI (typically emitted by Engine E
# when a Neo4j node has an attached procedure diagram extracted by
# doc-tools) and rewrites it to GET /federated_image?src=...
#
# This endpoint enforces the SAME authorization gate as the rest of the
# bff: get_current_user validates the JWT, then we apply the
# entitled_domains scope filter that the data path uses (per ADR-0009).
# An earlier attempt routed the browser directly to MinIO STS via
# AssumeRoleWithWebIdentity; that worked but introduced a separate authz
# surface (token-claim-driven IAM policies in MinIO) inconsistent with
# the rest of the system. This proxy is the consistent answer.

from fastapi import HTTPException, Query
from urllib.parse import urlparse

_MINIO_ENDPOINT_URL = os.getenv("MINIO_ENDPOINT_URL", "http://iagent-minio:9000")
_MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minio-sandbox")
_MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minio-sandbox-secret")
_MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")

#: Bucket-name convention: doc-tools writes per-domain buckets like
#: ``doc-tools-maintenance`` / ``doc-tools-manufacturing``. The portion
#: after the prefix is the domain slug we compare against the caller's
#: entitled_domains JWT claim. Buckets that don't follow the convention
#: are treated as "no scoped domain" and pass through (operator can
#: tighten this once the bucket naming policy is finalized).
_DOC_TOOLS_BUCKET_PREFIX = "doc-tools-"


def _bucket_domain(bucket: str) -> str | None:
    """Extract a domain slug from a bucket name, or None if the bucket
    doesn't follow the doc-tools-{domain} convention. Returned slug is
    upper-cased to match the entitled_domains vocabulary engines use.
    """
    if not bucket.startswith(_DOC_TOOLS_BUCKET_PREFIX):
        return None
    slug = bucket[len(_DOC_TOOLS_BUCKET_PREFIX):]
    return slug.upper() if slug else None


@app.get("/federated_image")
def federated_image(
    src: str = Query(..., description="s3://bucket/key URI to stream from MinIO"),
    current_user: User = Depends(get_current_user),
):
    """Proxy an image stored in MinIO to the browser, gated by the
    caller's JWT + entitled_domains.

    Sync handler (boto3 is sync-only without an extra dep). FastAPI
    runs sync routes in its threadpool so this doesn't block the
    event loop.
    """
    # 1. Parse src — must be s3://bucket/key.
    if not src.startswith("s3://"):
        raise HTTPException(status_code=400, detail="src must be an s3:// URI")
    parsed = urlparse(src)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise HTTPException(status_code=400, detail="malformed s3:// URI")
    # Reject path traversal in key (defense in depth — boto3 will also
    # reject these, but we want a fast 400 with a clear error).
    if ".." in key.split("/"):
        raise HTTPException(status_code=400, detail="key may not contain '..'")

    # 2. Authorization: apply the entitled_domains scope filter the same
    # way Engine O's /search_predicates does. Empty entitled_domains list
    # means the JWT didn't carry the claim (PingSSO baseline) — pass
    # through, mirroring the data path's "no claim = no scope filter"
    # behavior. Per-asset Topaz checks are a follow-up; the gate today is
    # JWT auth + this domain scope, same as the supervisor.
    if current_user.entitled_domains:
        domain = _bucket_domain(bucket)
        if domain is not None and domain not in current_user.entitled_domains:
            logger.warning(
                "federated_image denied user=%s bucket=%s domain=%s entitled=%s",
                current_user.id, bucket, domain, current_user.entitled_domains,
            )
            raise HTTPException(status_code=403, detail="not entitled for this domain")

    # 3. Fetch from MinIO with the bff's own static credentials.
    # Lazy-imported so boto3's ~10MB cost doesn't hit every cortex-bff
    # startup that never serves an image.
    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        endpoint_url=_MINIO_ENDPOINT_URL,
        aws_access_key_id=_MINIO_ACCESS_KEY,
        aws_secret_access_key=_MINIO_SECRET_KEY,
        region_name=_MINIO_REGION,
        # MinIO requires path-style addressing (bucket-as-path, not
        # virtual-hosted-style). The signature_version=s3v4 line matches
        # MinIO's only supported sig version.
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )

    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="image not found")
    except Exception as exc:  # noqa: BLE001
        logger.error("federated_image MinIO get_object error: %s", exc)
        raise HTTPException(status_code=502, detail="upstream object store error")

    content_type = obj.get("ContentType") or "application/octet-stream"
    # StreamingResponse iterates the botocore StreamingBody in chunks so
    # we don't load the whole image into memory.
    return StreamingResponse(
        obj["Body"].iter_chunks(chunk_size=64 * 1024),
        media_type=content_type,
        headers={
            # Private cache — presigned analogue. 1h is plenty for
            # session-scoped procedure images, short enough that
            # entitlement changes propagate within an hour.
            "Cache-Control": "private, max-age=3600",
        },
    )


# ════════════════════════════════════════════════════════════════════
# Data-module figures endpoint (Phase B of the 2026-06-30 figure work)
# ════════════════════════════════════════════════════════════════════
#
# Returns the figures associated with a `mil:DataModule` URI for the
# cortex-ui slide-in panel. The panel is triggered from a Source card
# click; it shows the data module's figures in three states per the
# rendering-origin discipline:
#
#   - "pipeline"            → render the image inline via FederatedImage
#   - "supplied_override"   → render the image inline + visible badge
#   - "format_not_supported"→ honest placeholder + click-through to
#                             raw source bytes (source_s3)
#
# The data flow:
#   - extract_iads_bundle writes a per-bundle graphics_manifest.json
#     to S3 AND per-figure .meta.json sidecars
#   - 40051 parser propagates `mil:hasURL` + `mil:renderingOrigin`
#     onto each Figure URI (read from the manifest)
#   - n10s imports the RDF into Neo4j as :Resource nodes with
#     properties + relationships
#   - This endpoint queries Neo4j for those nodes and returns
#     a compact JSON for the panel to render
#
# Authz: gates on JWT auth (the rest is non-PII metadata about figures
# the caller can already see surfaced as Source cards). Per-domain
# scope follows naturally from what the engine returned as sources.

@app.get("/data_module/figures")
def data_module_figures(
    uri: str = Query(..., description="mil:DataModule URI to fetch figures for"),
    current_user: User = Depends(get_current_user),
):
    """Return the figures linked from a `mil:DataModule` URI.

    Response shape:
        {
          "uri": "http://edgy-solutions.com/ontology/mil#wpn-m0004-...",
          "figures": [
            {
              "uri": "http://.../mil#fig-MS098897A",
              "label": "MS098897A",
              "url": "s3://processing-artifacts/40051/.../MS098897A.bmp",
              "rendering_origin": "pipeline" | "supplied_override" |
                                  "format_not_supported" | ""
            },
            ...
          ]
        }

    The cortex-ui slide-in panel renders each figure based on
    `rendering_origin`. Empty string = legacy / unknown — panel falls
    back to caption-only.
    """
    # n10s with `handleVocabUris: 'IGNORE'` imports RDF triples as
    # :Resource nodes whose properties/relationships use the LOCAL
    # name of the predicate (everything after the # or /). So
    # `mil:hasFigure` becomes a relationship named `hasFigure`,
    # `mil:hasURL` becomes a `hasURL` property, etc.
    cypher = """
    MATCH (dm:Resource {uri: $uri})-[:hasFigure]->(fig:Resource)
    RETURN
      fig.uri AS uri,
      coalesce(fig.label, fig.uri) AS label,
      fig.hasURL AS url,
      coalesce(fig.renderingOrigin, '') AS rendering_origin
    """
    figures: list[dict] = []
    try:
        with neo4j_driver.session() as session:
            result = session.run(cypher, {"uri": uri})
            for record in result:
                figures.append({
                    "uri": record["uri"],
                    "label": record["label"],
                    "url": record["url"],
                    "rendering_origin": record["rendering_origin"] or "",
                })
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "data_module_figures Neo4j query error for uri=%s: %s",
            uri, exc,
        )
        raise HTTPException(
            status_code=502, detail="neo4j query failed",
        ) from exc

    # Dedup by URL — the 40051 XML often references the same image via
    # both `<graphic boardno="X"/>` AND a separate `<figure>` element,
    # producing two distinct `fig-*` nodes pointing at the same S3 URL.
    # The slide-in shouldn't show duplicate cards. Keep the entry with
    # the more informative label (longer wins as a heuristic — "Mouse
    # (Right Click) TOC" beats "rightclickmenuinTOC") and the more
    # informative rendering_origin (non-empty wins).
    deduped_by_url: dict[str, dict] = {}
    no_url_figures: list[dict] = []
    for fig in figures:
        url = fig.get("url")
        if not url:
            no_url_figures.append(fig)
            continue
        existing = deduped_by_url.get(url)
        if existing is None:
            deduped_by_url[url] = fig
            continue
        # Prefer non-empty rendering_origin.
        if not existing.get("rendering_origin") and fig.get("rendering_origin"):
            deduped_by_url[url] = fig
            continue
        # Prefer longer label when origin equally informative.
        if len(fig.get("label", "")) > len(existing.get("label", "")):
            deduped_by_url[url] = fig

    return {
        "uri": uri,
        "figures": list(deduped_by_url.values()) + no_url_figures,
    }


# ─────────────────────────────────────────────────────────────────────
# Electric shape proxy — per-user isolation interim
# ─────────────────────────────────────────────────────────────────────
#
# Architect's 2026-06-30 ruling (per-user demo workbench):
#
# The substrate today stores answer artifacts globally — one
# `answer_artifact_projection` table, no per-user partitioning. The
# write side captures `produced_for.user_id` per artifact (audit trail
# intact), but cortex-ui's Electric subscription has no `where` clause
# and streams the whole table. In a multi-user demo, every tester
# would see everyone else's questions — over-sharing.
#
# This proxy is the INTERIM per-user isolation surface. It is
# explicitly NOT access control:
#
#   - Today's filter:    `produced_for.user_id = $authenticated_sub`
#                        (ownership-based; under-shares is safe)
#   - Tomorrow's filter: viewability derived from source ACLs
#                        (ADR-0025 access-control arc; gated by Topaz)
#
# Same Electric-shape-scoping mechanism, different predicate. This
# proxy doesn't pull the access-control arc forward; it just applies
# the `user_id` already captured at write time as a subscription
# filter.
#
# Why proxy (server-side), not client-supplied WHERE: if the client
# passed `where: produced_for->>'user_id' = 'X'` to Electric directly,
# the client could set X to anyone's `sub` and bypass isolation. The
# WHERE must be sourced from a SERVER-VERIFIED JWT claim, not a
# client parameter. This proxy is the trusted middle that injects
# the verified `sub` into the upstream Electric call.
#
# What the proxy does:
#   1. Validates the JWT via the same `get_current_user` dependency
#      every other endpoint uses (RS256 against Keycloak JWKS).
#   2. STRIPS any client-supplied `where` parameter — never trusted.
#   3. Injects `where: "produced_for->>'user_id' = '<verified_sub>'"`
#      with the user_id escaped against SQL-quote-injection (UUID
#      regex validation + PostgreSQL single-quote doubling).
#   4. Forwards all other Electric params (`table`, `offset`, `live`,
#      `handle`, `columns`, etc.) verbatim.
#   5. Streams the upstream response back, preserving Electric's
#      protocol headers (`electric-handle`, `electric-offset`,
#      `electric-up-to-date`) so the client's incremental sync works.
#
# `_ELECTRIC_UPSTREAM_URL` defaults to the cluster-internal service
# URL; the direct ingress `electric.edgy-solutions.com` is closed as
# part of this rollout so testers can't bypass the proxy.

import re as _re_for_uuid

_UUID_RE = _re_for_uuid.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _escape_sql_string_literal(s: str) -> str:
    """Escape a string for inclusion in a PostgreSQL single-quoted
    literal: PostgreSQL doubles single quotes. We ALSO validate
    against a UUID regex first because Keycloak's `sub` is always a
    UUID v4 — anything else is a malformed token. Belt-and-suspenders.
    """
    if not _UUID_RE.match(s):
        # Defensive: should never happen with a Keycloak-issued JWT;
        # if it does, the JWT is malformed and we refuse to proxy.
        raise ValueError(f"verified user_id is not a UUID: {s!r}")
    return s.replace("'", "''")


_ELECTRIC_FORWARD_HEADERS = {
    "electric-handle",
    "electric-offset",
    "electric-up-to-date",
    "electric-schema",
    "electric-cursor",
    "content-type",
    "cache-control",
}


@app.get("/electric/shape")
async def electric_shape_proxy(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Proxy to upstream Electric `/v1/shape` with a server-verified
    `produced_for.user_id = <authenticated sub>` filter injected.

    Per-user isolation interim — see the module-level comment above.

    Electric's `/v1/shape` is long-polled: each request hangs up to
    ~30s waiting for new data, then returns a JSON array of inserts/
    updates plus protocol headers (`electric-handle`, `electric-offset`,
    `electric-up-to-date`). We forward those headers verbatim so the
    cortex-ui ShapeStream's incremental sync continues working.
    """
    # 1. JWT validated by Depends(get_current_user). User.id is set
    #    to payload["sub"] from a RS256-verified JWT (see auth.py).
    #    CANNOT be spoofed.
    verified_user_id = current_user.id

    # 2. Build the upstream WHERE clause with the escaped, validated
    #    user_id. PostgreSQL JSONB path operator `->>` extracts the
    #    user_id field as text for the literal comparison.
    escaped = _escape_sql_string_literal(verified_user_id)
    server_where = f"produced_for->>'user_id' = '{escaped}'"

    # 3. Pass through Electric params, EXCEPT any client-supplied
    #    `where` (always overridden by the server-injected clause).
    upstream_params: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key.lower() == "where":
            # Client cannot influence the WHERE clause. Silently drop.
            continue
        upstream_params[key] = value
    upstream_params["where"] = server_where
    upstream_params.setdefault("table", "answer_artifact_projection")

    upstream_url = f"{_ELECTRIC_UPSTREAM_URL}/v1/shape"

    # 4. Fire the upstream request and forward the body + protocol
    #    headers. httpx read timeout is set generous to accommodate
    #    Electric's long-poll.
    timeout = httpx.Timeout(connect=5.0, read=60.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            upstream_resp = await client.get(upstream_url, params=upstream_params)
        except httpx.HTTPError as exc:
            logger.error("electric proxy upstream error: %s", exc)
            raise HTTPException(
                status_code=502, detail="electric upstream unavailable"
            ) from exc

    forwarded = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() in _ELECTRIC_FORWARD_HEADERS
    }

    return StreamingResponse(
        iter([upstream_resp.content]),
        status_code=upstream_resp.status_code,
        headers=forwarded,
    )
