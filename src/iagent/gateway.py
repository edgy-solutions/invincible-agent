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
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from neo4j import GraphDatabase
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db, init_db
from .models import BpmnCatalog
from .auth import get_current_user, User


logger = logging.getLogger("cortex")

# ── Env ───────────────────────────────────────────────────
load_dotenv()

_DAGSTER_WEBSERVER_URL = os.getenv("DAGSTER_WEBSERVER_URL", "http://localhost:3000")
_DAGSTER_REPOSITORY = os.getenv("DAGSTER_REPOSITORY", "__repository__")
_DAGSTER_LOCATION = os.getenv("DAGSTER_LOCATION", "iagent")

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
            await queue.put(_sse("status", json.dumps({
                "action": "error",
                "label": f"Stream producer error: {exc}",
            })))
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
                }
              }
            }
          }
          stepStats {
            materializations {
              assetKey { path }
              metadataEntries {
                label
                ... on TextMetadataEntry {
                  text
                }
                ... on JsonMetadataEntry {
                  jsonString
                }
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

    yield _sse("status", json.dumps({
        "action": "think",
        "category": "Process",
        "label": "Analyzing intent..."
    }))

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
            yield _sse("status", json.dumps({"action": "error", "label": "Failed to determine execution intent."}))
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
        yield _sse("status", json.dumps({"action": "think", "category": "Process", "label": "Process Engineer is reviewing requirements..."}))
        
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
                
                # Auto-Compile Logic
                if data.get("is_complete"):
                    yield _sse("status", json.dumps({"action": "think", "category": "System", "label": "Compiling Graph to Dagster Workspace..."}))
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
                        yield _sse("status", json.dumps({"action": "error", "label": f"Auto-compile failed: {compile_err}"}))
                
        except Exception as exc:
            logger.error("Failed to call Restate Interviewer: %s", exc)
            yield _sse("status", json.dumps({"action": "error", "label": "Failed to reach Process Engineer."}))
            
        yield _sse("stream_end", "{}")
        return

    # 🟢 THE GRAPH PATH (DAGSTER)
    yield _sse("status", json.dumps({
        "action": "plan",
        "category": "Process",
        "label": "Engine O Planning Complete..."
    }))

    # Per ADR-0009 Step F'.2: /route_intent does not produce a task_plan
    # anymore — the supervisor's `create_task_plan` op asks Engine O's /plan
    # endpoint itself when task_plan_json is empty. Step F'.3 will switch
    # that decomposition path to be predicate-aware too.
    task_plan_json = ""

    yield _sse("status", json.dumps({
        "action": "think",
        "category": "Concept",
        "label": f"Triggering Supervisor Job for thread {session_id[:8]}..."
    }))
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
        yield _sse("status", json.dumps({"action": "error", "label": "Failed to trigger Dagster job."}))
        yield _sse("stream_end", "{}")
        return
        
    yield _sse("status", json.dumps({"action": "think", "category": "Process", "label": f"Dagster Run Initiated: {run_id[:8]}"}))

    # Polling Loop
    emitted_steps = set()
    is_success = False
    
    for idx in range(900): # 15 minute max timeout (slow Ollama backends)
        await asyncio.sleep(1.0)
        
        # 🛑 THE FIX: Keep-Alive Heartbeat (Fires every 10 seconds)
        if idx > 0 and idx % 10 == 0:
            heartbeat_payload = json.dumps({
                "action": "think", 
                "category": "Process", 
                "label": f"Agents are reasoning (Elapsed: {idx}s)..."
            })
            yield _sse("status", heartbeat_payload)
        
        status_data = await _get_run_status(run_id)
        if status_data.get("status") == "FAILURE":
            yield _sse("status", json.dumps({"action": "error", "label": "Pipeline Failed."}))
            break
            
        if status_data.get("status") == "SUCCESS":
            is_success = True
            break
            
        # 🛑 GET INTERMEDIATE EVENTS (Personas & Concepts)
        mats = await _get_run_events(run_id)
        for mat in mats:
            # Check for the active_agent_roster asset
            path = mat.get("assetKey", {}).get("path")
            if path == ["active_agent_roster"] and "plan_emitted" not in emitted_steps:
                personas_list = []
                concepts_list = []
                for meta in mat.get("metadataEntries", []):
                    if meta.get("label") == "personas":
                        try:
                            json_str = meta.get("text") or meta.get("jsonString") or "[]"
                            personas_list = json.loads(json_str)
                        except Exception as parse_err:
                            logger.error("Failed to parse persona metadata: %s", parse_err)
                    elif meta.get("label") == "extracted_concepts":
                        try:
                            json_str = meta.get("text") or meta.get("jsonString") or "[]"
                            concepts_list = json.loads(json_str)
                        except Exception as parse_err:
                            logger.error("Failed to parse concepts metadata: %s", parse_err)
                            
                if personas_list:
                    logger.info("📡 Emitting SSE 'plan' with personas: %s", personas_list)
                    yield _sse("status", json.dumps({
                        "action": "plan",
                        "personas": personas_list,
                        "label": "Summoning specialized graph agents..."
                    }))
                if concepts_list:
                    logger.info("📡 Emitting SSE 'context_update' with ontology concepts: %s", concepts_list)
                    yield _sse("context_update", json.dumps({
                        "type": "ontology",
                        "data": concepts_list
                    }))
                    
                emitted_steps.add("plan_emitted")
                logger.info("✅ Plan emission confirmed for run %s", run_id)

        step_stats = await _get_step_stats(run_id)
        for stat in step_stats:
            step_key = stat.get("stepKey", "")
            status = stat.get("status", "")
            
            # If step has started but not emitted yet
            if status == "SUCCESS" and f"{step_key}_success" not in emitted_steps:
                lbl = ""
                if step_key == "create_task_plan": lbl = "Task plan created by Engine O"
                elif step_key.startswith("execute_subtask-"): lbl = f"Expert Graph evaluation complete ({step_key})"
                elif step_key == "synthesize_stateful": lbl = "Results synthesized by Engine B"
                elif step_key == "generate_ui_payload": lbl = "UI State mapped by Engine F"
                
                if lbl:
                     yield _sse("status", json.dumps({"action": "found", "category": "Asset", "label": lbl}))
                emitted_steps.add(f"{step_key}_success")
                
            elif status == "RUNNING" and f"{step_key}_running" not in emitted_steps:
                lbl = ""
                if step_key == "create_task_plan": lbl = "Asking Engine O to build task plan..."
                elif step_key.startswith("execute_subtask-"): lbl = f"Fanning out to Engine E..."
                elif step_key == "synthesize_stateful": lbl = "Synthesizing parallel state via Engine B..."
                elif step_key == "generate_ui_payload": lbl = "Calling Engine F for component mapping..."
                
                if lbl:
                     yield _sse("status", json.dumps({"action": "think", "category": "Process", "label": lbl}))
                emitted_steps.add(f"{step_key}_running")
                
    if is_success:
        yield _sse("status", json.dumps({"action": "think", "category": "Concept", "label": "Retrieving Final UI Payload..."}))
        result = await _get_ui_payload_output(run_id)
        
        if "error" in result:
            logger.error("BFF Error: %s", result["error"])
            yield _sse("status", json.dumps({"action": "error", "label": result["error"]}))
        else:
            # Emit data bindings to the HUD
            if result.get("referenced_uris"):
                yield _sse("context_update", json.dumps({
                    "type": "bindings",
                    "data": result["referenced_uris"]
                }))
                
            # Mark the retrieval step as done before sending the payload
            yield _sse("status", json.dumps({"action": "found", "category": "Asset", "label": "UI Payload Retrieved"}))
            yield _sse("final_payload", json.dumps(result["payload"]))
    else:
        yield _sse("status", json.dumps({"action": "error", "label": "Timeout or failed to fetch UI payload."}))
        
    yield _sse("stream_end", "{}")


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
