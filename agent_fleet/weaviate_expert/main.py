"""
Engine W — Restate + Smolagents Durable Weaviate Semantic Expert Microservice

A FastAPI server backed by the Restate SDK for durable execution.
It exposes a `/query_knowledge` endpoint that uses a smolagents CodeAgent
with a custom Weaviate Semantic Search tool to extract knowledge and policies
from a military technical manual database. BAML strictly types the output.

Run locally: uvicorn agent_fleet.weaviate_expert.main:app --host 0.0.0.0 --port 8088
"""

import os
from contextlib import asynccontextmanager

import httpx
import restate
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Engine self-registration for the predicate-graph routing layer
# (iagent ADR-0004 Step D.1). Opt-in via MESH_REGISTER_ON_STARTUP.
try:
    from utils.mesh_registration import register_engine_to_mesh
except ImportError:
    from agent_fleet.utils.mesh_registration import register_engine_to_mesh

try:
    # Standalone microservice mode (Workspace Root)
    from service import service as expert_service
except ImportError:
    # Local dev mode (Imported as submodule)
    try:
        from .service import service as expert_service
    except ImportError:
        # Fallback for parent-dir execution
        from agent_fleet.weaviate_expert.service import service as expert_service

# Engine W's lifespan registers it as a predicate in the mesh routing graph.
# Engine W does Weaviate hybrid search over technical manuals for pure
# knowledge retrieval (no graph traversal); returns a structured markdown
# summary with citations.
@asynccontextmanager
async def lifespan(app: FastAPI):
    register_engine_to_mesh(
        name="engine_w_weaviate_expert",
        description=(
            "Knowledge retrieval engine. Weaviate v4 hybrid search "
            "(near_text + BM25) with strict domain segregation; returns "
            "Markdown summaries and citations from technical manuals."
        ),
        verb="mesh:retrieveKnowledge",
        input_uri="https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/TechnicalManual",
        output_uri="http://invincible-agent/mesh#KnowledgeRetrievalResponse",
        verb_synonyms=[
            "search docs", "find in manuals", "semantic search",
            "look up policy", "consult manual",
        ],
        endpoint_url=os.getenv(
            "ENGINE_W_PUBLIC_URL",
            "http://iagent-engine-w:8088/query_knowledge",
        ),
        owner_persona="TECH_WRITER",
        # Per ADR-0009: Engine W's strict per-collection segregation
        # already partitioned by domain; making it explicit here so the
        # scope filter in /find_tool can match.
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="medium",  # Weaviate is fast; embedding + smolagents = medium overall
    )

    # Second registration: mesh:retrieveKnowledge against
    # mil:FaultIsolationDataModule (B4 verb 1, 2026-06-15).
    # IMPORTANT: same description as the primary registration above —
    # BAML's TypeBuilder dedupes enum values by name and the last
    # add_value's description wins (see Engine E's note at line 126).
    # Engine W is the right owner for fault-isolation queries: tswp
    # content (helmet TM and future 40051 troubleshooting work-packages)
    # is text-search-shaped, not graph-traversal-shaped, so manual
    # search is the action verb. Pairs with the existing
    # retrieveKnowledge-against-TechnicalManual registration; the same
    # capability typed against a different subject path.
    register_engine_to_mesh(
        name="engine_w_weaviate_expert_fault_isolation",
        description=(
            "Knowledge retrieval engine. Weaviate v4 hybrid search "
            "(near_text + BM25) with strict domain segregation; returns "
            "Markdown summaries and citations from technical manuals."
        ),
        verb="mesh:retrieveKnowledge",
        input_uri="http://edgy-solutions.com/ontology/mil#FaultIsolationDataModule",
        output_uri="http://invincible-agent/mesh#KnowledgeRetrievalResponse",
        verb_synonyms=[
            "search docs", "find in manuals", "semantic search",
            "look up policy", "consult manual",
            "fault isolation", "troubleshoot", "diagnose",
            "why is it broken", "find the fault",
            "diagnostic procedure", "troubleshooting procedure",
        ],
        endpoint_url=os.getenv(
            "ENGINE_W_PUBLIC_URL",
            "http://iagent-engine-w:8088/query_knowledge",
        ),
        owner_persona="TECH_WRITER",
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="medium",
    )

    # Third registration: mesh:retrieveKnowledge against
    # mil:IllustratedPartsDataModule (B4 verb 3, 2026-06-15).
    # Engine W is the right owner for IPD queries: parts catalogs
    # (DMC info code 9xx, exploded views + part lists) are
    # text-search-shaped in practice — "what parts make up X",
    # "show me the parts breakdown" land in Weaviate's hybrid
    # search over the IPD chunks rather than a graph walk.
    #
    # Multi-phrasing probe observation (the new acceptance gate
    # introduced this verb, per architect 2026-06-15):
    #   P1 "What parts make up the microphone boom?" -> IPD @ 0.97
    #   P2 "Show me the illustrated parts breakdown ..."  -> IPD @ 0.98
    #   P3 "What is the part number for the boom cable?"  -> mil:Part @ 0.92
    #     (kind-vs-instance distinction: part NUMBER asks about a
    #      Part instance, not the parts breakdown DOCUMENT)
    #   P4 "Describe the parts data module for the boom"  -> IPD @ 0.96
    #     (the verb-2 "describe -> DescriptiveDataModule" cue did NOT
    #      replicate here — "parts data module" is a strong enough
    #      cohesive trigger to override the generic "describe" cue.
    #      Asymmetric with verb 2's probe 1, where "procedure data
    #      module" did NOT beat "describe".)
    #   P5 "What is the IPD for part number 12345?" -> IPD @ 0.97
    #     (instance-resolution layer also fired on "12345" -> all
    #      three providers abstained cleanly; class fallback held.)
    #
    # Matrix row picks P2 — exact "illustrated parts breakdown"
    # trigger, highest confidence, no instance-resolution noise.
    #
    # Lexical-boundary observation banked for the widened ADR
    # (the full procedural-content disambiguation design pass):
    # IPD's "parts"-anchored vocabulary is strong enough that
    # "describe" doesn't poach to DescriptiveDataModule the way
    # it does for "procedure" — the boundary between IPD and DDM
    # is sharper than between ProcedureDataModule and DDM. Worth
    # recording so the ADR's class-definition tuning targets the
    # weak boundaries.
    register_engine_to_mesh(
        # Same description as the primary registrations above —
        # BAML TypeBuilder dedupes enum values by name; last
        # add_value's description wins. Same capability, different
        # subject path.
        name="engine_w_weaviate_expert_illustrated_parts",
        description=(
            "Knowledge retrieval engine. Weaviate v4 hybrid search "
            "(near_text + BM25) with strict domain segregation; returns "
            "Markdown summaries and citations from technical manuals."
        ),
        verb="mesh:retrieveKnowledge",
        input_uri="http://edgy-solutions.com/ontology/mil#IllustratedPartsDataModule",
        output_uri="http://invincible-agent/mesh#KnowledgeRetrievalResponse",
        verb_synonyms=[
            "search docs", "find in manuals", "semantic search",
            "look up policy", "consult manual",
            "parts breakdown", "illustrated parts", "IPD",
            "what parts", "part number", "parts catalog",
            "parts list", "part lookup",
        ],
        endpoint_url=os.getenv(
            "ENGINE_W_PUBLIC_URL",
            "http://iagent-engine-w:8088/query_knowledge",
        ),
        owner_persona="TECH_WRITER",
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="medium",
    )

    # Fourth registration: mesh:retrieveKnowledge against
    # mil:DescriptiveDataModule (B4 verb 4, 2026-06-16).
    # Engine W is the right owner for descriptive-content queries:
    # DDM (DMC info code 0xx, "what it is") modules are narrative
    # text — system overviews, equipment descriptions, theory of
    # operation. Hybrid search over the DDM chunks is the natural
    # capability; same retrieveKnowledge verb as TechnicalManual /
    # FaultIsolation / IPD.
    #
    # **Two-purpose probe scan** (the new acceptance gate's
    # sharpened form per architect 2026-06-15: this verb's scan
    # was designed to also measure DDM over-attraction, because
    # "describe" is the most common query verb and DDM's anchor is
    # weak-and-over-broad in a way IPD's wasn't):
    #
    # Genuine-DDM probes (matrix-row candidates):
    #   D1 "What is the helmet display unit?"
    #        -> DDM @ 0.86  (pure "what is" + named system)
    #   D2 "Tell me about the helmet HMD architecture"
    #        -> DDM @ 0.86-0.95 (descriptive framing; some variance)
    #
    # Leak-test probes (correct target is NOT DDM; measure
    # whether "describe" steals to DDM):
    #   L3 "Describe how to install the boom"
    #        -> mro:WorkInstruction @ 0.85  (HELD — WorkInstruction's
    #         "describe" + "install" + "steps" hand-tuning beats
    #         DDM's generic "describe" cue)
    #   L4 "Describe the parts of the boom assembly"
    #        -> mil:IllustratedPartsDataModule @ 0.95  (HELD —
    #         IPD's "parts" anchor is so strong it wins even
    #         on "describe" framing; tighter version of verb 3 P4)
    #   L5 "Describe the troubleshooting procedure for the helmet"
    #        -> mro:WorkInstruction @ 0.85  (HELD against DDM, but
    #         "leaked" *across* WorkInstruction <-> FaultIsolation
    #         boundary — should arguably be FaultIsolation;
    #         WorkInstruction's "procedure" hand-tuning catches it.
    #         Separate finding, not DDM's fault.)
    #
    # **DDM over-attraction sizing — BOUNDED.** All three leak
    # probes held their correct boundaries against DDM. DDM wins
    # only on genuinely-descriptive queries. The pre-registered
    # BEFORE/AFTER comparison also confirmed: /resolve is verb-
    # edge-independent, so adding the DDM edge didn't move any
    # other class's resolution.
    #
    # **Existing matrix row safety** (the keystone over-attraction
    # risk pre-registration): "Describe procedure TEST-1234 and
    # show me its diagram" resolves via mesh:resolveInstance
    # (engine_e finds TEST-1234 as a Test Procedure 1234 instance
    # exact-match at score 1.0). Instance resolution PREEMPTS the
    # class-vocabulary contest entirely. Named-identifier queries
    # are insulated from DDM's "describe" pull — a structural
    # observation worth banking for the ADR.
    #
    # Matrix row picks D1 -- pure "what is" framing, stable
    # 0.85 confidence, cleanest DDM ownership.
    #
    # Banked findings for the widened ADR design pass (the
    # procedural-content disambiguation):
    #   1. DDM's over-attraction is BOUNDED. Strong-anchor classes
    #      (IPD with "parts", WorkInstruction with hand-tuned
    #      "procedure" hints) hold against "describe" cue alone.
    #      The structural fix is not URGENT for DDM-vs-others.
    #   2. The remaining weak boundary is FaultIsolation <-> WorkInstruction
    #      (L5's leak across this boundary, not DDM's fault). Verb 1
    #      ships demo-clean for "fault" + "diagnose" phrasings; if
    #      "describe the troubleshooting procedure" became a real
    #      user query, the FI/WI boundary would need either FI hand-
    #      tuning or structural disambiguation.
    #   3. Instance resolution is a load-bearing disambiguator —
    #      it preempts class-vocabulary contests for any query with
    #      a named identifier. This is a general pattern across the
    #      manuals ontology (P3's mil:Part finding from verb 3 +
    #      TEST-1234 instance routing here): the document<->content/
    #      instance duality is structurally encoded via the instance-
    #      resolution layer's fan-out, not just via class definitions.
    register_engine_to_mesh(
        name="engine_w_weaviate_expert_descriptive",
        description=(
            "Knowledge retrieval engine. Weaviate v4 hybrid search "
            "(near_text + BM25) with strict domain segregation; returns "
            "Markdown summaries and citations from technical manuals."
        ),
        verb="mesh:retrieveKnowledge",
        input_uri="http://edgy-solutions.com/ontology/mil#DescriptiveDataModule",
        output_uri="http://invincible-agent/mesh#KnowledgeRetrievalResponse",
        verb_synonyms=[
            "search docs", "find in manuals", "semantic search",
            "look up policy", "consult manual",
            "what is", "tell me about", "describe",
            "description of", "overview of", "explanation of",
        ],
        endpoint_url=os.getenv(
            "ENGINE_W_PUBLIC_URL",
            "http://iagent-engine-w:8088/query_knowledge",
        ),
        owner_persona="TECH_WRITER",
        domains=["MAINTENANCE", "MANUFACTURING"],
        cost_class="medium",
    )

    # WorkInstruction registration — manufacturing assembly-procedure
    # routing. The matrix's M67 grenade case (post-ADR-0021 phrasing-
    # probe scan) resolves to ``mfg:WorkInstruction`` as its subject
    # and expects ``mesh:retrieveKnowledge`` as its routed verb. The
    # canonical answer is "Engine W handles WorkInstruction-shaped
    # content the same way it handles other manual content-kinds" —
    # so it goes here alongside the other four kind-specific
    # registrations, not as an out-of-band manual migration.
    #
    # History: this verb edge was originally created by a one-shot
    # manual migration on 2026-06-20 (per docs/adr/ADR-0021 + the
    # comment block in test_no_legacy_residue.py:54-57 that documents
    # the substrate-side migration of the placeholder
    # MunitionsAssemblyStep row to mfg:WorkInstruction). Promoting it
    # into Engine W's lifespan converts the one-time manual writer
    # into a tracked source writer — re-seed + bounce regenerates the
    # row, no manual step needed.
    register_engine_to_mesh(
        name="engine_w_weaviate_expert_work_instruction",
        description=(
            "Knowledge retrieval engine. Weaviate v4 hybrid search "
            "over manufacturing WorkInstructions (assembly procedures, "
            "production steps, kitting instructions); returns Markdown "
            "summaries and citations."
        ),
        verb="mesh:retrieveKnowledge",
        input_uri="http://edgy-solutions.com/ontology/mfg#WorkInstruction",
        output_uri="http://invincible-agent/mesh#KnowledgeRetrievalResponse",
        verb_synonyms=[
            "assembly steps", "assembly procedure",
            "production steps", "build instructions",
            "how to assemble", "step-by-step",
            "work instruction", "kitting steps",
        ],
        endpoint_url=os.getenv(
            "ENGINE_W_PUBLIC_URL",
            "http://iagent-engine-w:8088/query_knowledge",
        ),
        owner_persona="TECH_WRITER",
        domains=["MANUFACTURING"],
        cost_class="medium",
    )
    yield


# Initialize FastAPI
# Telemetry (ADR-0038): join Engine W's work to the caller's trace. telemetry.py is at /app
# in the fleet image; guarded so the engine runs identically when the shim/leaf is absent.
try:
    from telemetry import observed_trace, MAPPING, build_trace_values
except Exception:  # pragma: no cover — telemetry never load-bearing
    from contextlib import contextmanager as _cm

    @_cm
    def observed_trace(*_a, **_k):
        yield

    def build_trace_values(**_k):
        return {}

    MAPPING = None

app = FastAPI(title="Engine W: Weaviate Semantic Expert", lifespan=lifespan)


@app.middleware("http")
async def _telemetry_join(request: Request, call_next):
    # ADR-0038: join this engine to the CALLER's trace (X-Trace-Id from discovery.py) so every
    # endpoint nests under it. Fail-soft; no-op without a trace id / when disabled.
    tid = request.headers.get("X-Trace-Id")
    if not tid:
        return await call_next(request)
    with observed_trace(MAPPING, build_trace_values(
        trace_id=tid, engine="weaviate_expert", verb=request.url.path,
    ), name="engine-w " + request.url.path):
        return await call_next(request)

# Restate App Binding
app.mount("/restate", restate.app(services=[expert_service]))

# Read the Restate URL from env, default to the Docker Compose service name
RESTATE_INGRESS_URL = os.getenv("RESTATE_INGRESS_URL", "http://restate:8080")

@app.post("/query_knowledge")
async def query_knowledge_proxy(request: Request) -> JSONResponse:
    """Proxy that forwards incoming requests to the Restate WeaviateExpertService."""
    try:
        payload = await request.json()
        target_url = f"{RESTATE_INGRESS_URL}/WeaviateExpertService/query_knowledge"
        
        async with httpx.AsyncClient(timeout=300.0) as client:
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
    return {"status": "ok", "engine": "W"}
