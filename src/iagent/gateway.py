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
import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from neo4j import GraphDatabase
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db, init_db
from .models import BpmnCatalog
from .auth import get_current_user, User
from .identity_vault import (
    VAULT,
    RedemptionOutcome,
    vault_ttl_seconds,
    logger as _vault_audit_log,   # the ONE logger whose level the vault owns
)
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
    # HITL substrate: ensure the human_task_projection table exists in the
    # Electric-replicated Postgres. Non-fatal when PROJECTOR_POSTGRES_DSN is
    # unset (local/dev boot) — the substrate is dormant, never a boot blocker.
    try:
        from starlette.concurrency import run_in_threadpool
        from . import human_tasks
        await run_in_threadpool(human_tasks.apply_migration)
        logger.info("human_task_projection migration applied")
    except human_tasks.HumanTaskConfigError as exc:
        logger.info("HITL substrate dormant (no PG DSN): %s", exc)
    except Exception as exc:
        logger.warning("human_task migration failed (HITL dormant): %s", exc)
    # ADR-0028 canvas persistence: ensure the user_canvas table exists (same
    # Postgres, non-fatal when the DSN is unset).
    try:
        from starlette.concurrency import run_in_threadpool
        from . import user_canvas
        await run_in_threadpool(user_canvas.apply_migration)
        logger.info("user_canvas migration applied")
    except user_canvas.CanvasConfigError as exc:
        logger.info("canvas persistence dormant (no PG DSN): %s", exc)
    except Exception as exc:
        logger.warning("user_canvas migration failed (persistence dormant): %s", exc)
    # ── THE BFF REGISTERS ITS ONE ORCHESTRATION INTENT ──────────────────────
    #
    # RULED 2026-08-28: the owner of the behaviour is the only honest source of
    # its declaration. cortex-ui registers what cortex-ui can render; the BFF
    # owns /canvas/seed — its auth gate, its sequential orchestration, its
    # partial-seed refusal, its manifest row — so the BFF declares it. Any other
    # registrant (Engine P, a manifest job, a hand-seeded row) separates the
    # declaration from the thing declared, and the first change to the route's
    # contract silently strands the registration.
    #
    # THE PRECEDENT IS NOT NEW. The registry's population was never
    # "engines only" — cortex-ui registers presentation capabilities on page
    # load. This is the same pattern with a server-side trigger: register on
    # startup, idempotent, offered every boot. It inherits the fleet's staleness
    # properties for free — a stale BFF image advertises the capabilities it
    # actually has, and "which era is this" stays answerable by the digest.
    #
    # SCOPE GUARD, so this does not become a category error. The BFF registers
    # ORCHESTRATION INTENTS IT OWNS. Today that is exactly one. It does NOT
    # become a general registrant for things it proxies: /plan/* stays
    # unregistered because those are a write seam invoked by components, not a
    # phrase-routable capability. If a second orchestration intent appears it
    # rides this same startup path; if someone proposes registering a PROXIED
    # capability here, this paragraph is the refusal.
    #
    # COST-OF-GUESSING ENUMERATION (required whenever a registration makes a
    # verb reachable from natural language — state what becomes reachable and
    # whether it mutates):
    #
    #   reachable : seed_portfolio_canvas, typed against idp:Portfolio, no slots
    #   mutates   : YES, but ADDITIVELY ONLY — it mints new artifacts and the
    #               client composes a new canvas. Nothing is modified, nothing
    #               destroyed, no plan state is touched.
    #   authority : the caller's own. Each of the five asks re-authenticates and
    #               re-checks the caller's Topaz entitlement cell via
    #               /interview/stream; a non-entitled cell 403s there exactly as
    #               it would for a typed question.
    #   amplifies : one request -> five sequential Dagster runs (~18 min). A
    #               resource cost an entitled caller can repeat, not a privilege
    #               they can exceed. Declared in the manifest row as `delegates`.
    #
    # The dispatcher needs nothing: it already reads `endpoint = predicate[
    # "endpoint"]` and POSTs. Registration is the whole missing hop.
    try:
        from utils.mesh_registration import register_engine_to_mesh as _register_verb

        # THE URL BAKED HERE IS THE ONE THE SUPERVISOR WILL POST TO, FOREVER —
        # `endpoint_url` is written into the verb edge at registration and the
        # dispatcher reads it from the GRAPH, never from its own environment. So a
        # wrong value here is not a config bug the next restart fixes; it is a wrong
        # fact in the substrate until a re-registration overwrites it.
        #
        # This line previously read an INVENTED env name with a BARE, SANDBOX-PREFIXED
        # default, which under a corporate proxy produced a ProxyError against a host
        # nobody had configured. See src/iagent/service_urls.py for the full account.
        from .service_urls import cortex_bff_base_url

        _bff_base = cortex_bff_base_url()
        _register_verb(
            name="cortex_bff_orchestration",
            description=(
                "Compose a portfolio planning canvas by asking the five standing planning "
                "questions through the governed interview path and returning their artifact "
                "ids in template-slot order. This BUILDS A BOARD; it does not answer a "
                "planning question. A request for ONE measure - the schedule, the cost "
                "curve, the funding gap - is that measure's verb, not this one. Choose this "
                "only when the ask is for the whole board rather than a number on it."
            ),
            verb="mesh:seedPortfolioCanvas",
            input_uri="http://invincible-agent/idp#Portfolio",
            output_uri="http://invincible-agent/mesh#CanvasSeedResult",
            endpoint_url=f"{_bff_base}/canvas/seed",
            verb_synonyms=[
                "make me a portfolio canvas",
                "build me a portfolio review canvas",
                "set up the planning canvas",
                "give me the standard portfolio view",
                "build the portfolio canvas",
                "set up my planning board",
            ],
            owner_persona="PORTFOLIO_LEAD",
            domains=["PORTFOLIO_PLANNING"],
            # Not "fast": five sequential governed asks, ~18 minutes. Declaring
            # it fast would invite a caller to treat it as interactive, which is
            # the one thing this verb is not.
            cost_class="slow",
        )
    except Exception as _exc:  # pragma: no cover
        # Best-effort, matching the fleet's posture: a failed registration means
        # the phrase is not routable yet, NOT that the BFF is down. Every other
        # route keeps serving.
        logger.warning(
            "cortex-bff: seedPortfolioCanvas registration failed (%s: %s). The "
            "/canvas/seed route still works; the PHRASE will not route until a "
            "successful registration.",
            type(_exc).__name__, _exc,
        )

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


# ADR-0026 step 3: expose the current user's entitlement matrix to
# cortex-ui. The picker (landing in step 5) fetches this once on
# login, populates its persona/domain dropdowns from the cells, and
# starts on `default` (or falls back to the first cell if no default
# is seeded).
#
# Response shape:
#   {
#     "cells": [{"persona": "DATA_ENGINEER", "domain": "AVIATION"}, ...],
#     "default": {"persona": "DATA_ENGINEER", "domain": "AVIATION"} | null,
#     "source": "topaz" | "cache" | "jwt-legacy" | "fallback",
#     "user_id": "<sub>",
#     "email": "<email>"
#   }
#
# `source` records provenance for observability — cortex-ui shows
# `(from cache | from topaz | ...)` on the "Acting as" badge so
# operators know whether they're seeing a live or stale matrix,
# per ADR-0026's `[[optimistic-defaults-are-dishonest]]` posture
# applied to the entitlement display.
#
# When `TOPAZ_DIRECTORY_URL` is unset (legacy cluster without ADR-0026
# step 3 wired), `cells` is empty and `source` reflects the JWT-legacy
# path. The picker (step 5) treats an empty cells list as "no picker
# — the caller is on the legacy persona-in-JWT posture."
@app.get("/me/entitlements")
async def get_me_entitlements(current_user: User = Depends(get_current_user)):
    """Return the current user's (persona, domain) entitlement matrix."""
    ent = current_user.entitlements
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "cells": [
            {"persona": c.persona, "domain": c.domain} for c in ent.cells
        ],
        "default": (
            {"persona": ent.default.persona, "domain": ent.default.domain}
            if ent.default is not None
            else None
        ),
        "source": ent.source,
    }


# ── HITL HumanTask queue (the enforcement model's FIFTH namespace) ───────────
# The queue is access-controlled by the SAME Topaz single-decider as the four
# content namespaces: who may VIEW/ACT on a task is `can_act` on the task's
# `task_audience` (policy/task_grants.yaml). Two viewability layers derive from
# ONE truth: the Electric /electric/shape proxy filters human_task_projection by
# recipient_id=<verified caller authz_id> (replication layer), and /act re-checks
# Topaz can_act (application layer) — the projection rows exist BECAUSE Topaz
# authorized them, so the two cannot diverge. Keyed on authz_id end-to-end (email
# in sandbox, employee-ID at work-deploy) — display uses .email, authz uses authz_id.

from pydantic import BaseModel as _BaseModel  # noqa: E402


class HumanTaskRegisterRequest(_BaseModel):
    """Register a HumanTask. Called by a suspending workflow (Slice 1b) — or, at
    the foundation checkpoint, directly — to fan a task out to its audience's
    authorized actors. Fields are CLEARANCE-SAFE (reference + summary, never
    compartmented content)."""
    kind: str = "workflow_ack"
    task_id: str
    audience: str
    title: str
    summary: str
    requested_by: str
    workflow_id: Optional[str] = None
    subject_ref: Optional[str] = None
    payload: Optional[dict] = None


class HumanTaskActRequest(_BaseModel):
    decision: str  # "approved" | "rejected"
    comment: str = ""
    # PCN grouped review only: optional per-part disposition overrides the reviewer
    # changed from the proposal, {mpn: {disposition, reason}}. Absent/empty = accept-all
    # (every part takes its proposed disposition). Ignored for non-grouped-review kinds.
    overrides: Optional[dict] = None


class AccessRequestRequest(_BaseModel):
    """Case-1 access request: a caller DENIED read on an asset asks for it. This
    is ASYNC — it creates a request HumanTask and returns immediately; it does NOT
    suspend anything (the DoS ruling: query denials deny-and-stop + offer an async
    request, never park state). `asset` is the dataset URN; `domain` selects the
    approver audience (access_grant:<domain>)."""
    asset: str
    reason: str = ""
    domain: str = "DATA_ENGINEERING"


@app.post("/internal/human_tasks/register")
async def register_human_task(
    req: HumanTaskRegisterRequest,
    current_user: User = Depends(get_current_user),
):
    """Register a task and materialize one queue row per Topaz-authorized actor.
    INTERNAL seam — Slice 1b restricts callers to the workflow/service identity;
    at the foundation checkpoint it is exercised directly to prove the identity
    bridge. Returns the resolved recipient set (the Topaz decision)."""
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks
    try:
        result = await run_in_threadpool(
            lambda: human_tasks.register_task(
                kind=req.kind, task_id=req.task_id, audience=req.audience,
                title=req.title, summary=req.summary, requested_by=req.requested_by,
                workflow_id=req.workflow_id, subject_ref=req.subject_ref,
                payload=req.payload,
            )
        )
    except human_tasks.HumanTaskConfigError as exc:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured", "message": str(exc)})
    except human_tasks.NoEntitledRecipients as exc:
        # TERMINAL 4xx (not 5xx): a task with zero entitled actors is a permanent misconfiguration, not
        # a transient outage — the caller's workflow must fail-and-release (never park or retry-forever).
        raise HTTPException(status_code=422, detail={"error": "no_entitled_recipients", "message": str(exc)})
    logger.info("human_task registered: task_id=%s audience=%s recipients=%d",
                req.task_id, req.audience, len(result.get("recipients", [])))
    return result


@app.post("/access_requests")
async def create_access_request(
    req: AccessRequestRequest,
    current_user: User = Depends(get_current_user),
):
    """Case-1: a caller denied read on an asset requests access. ASYNC — creates a
    request HumanTask routed to the domain's access-grant approvers and RETURNS
    IMMEDIATELY. Nothing suspends (no Restate workflow, no held state) — the DoS
    ruling for query denials. The grant SUBJECT is the caller's authz_id (recorded
    in the payload for the fulfillment); an approver later writes the grant."""
    import uuid as _uuid
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks
    audience = f"access_grant:{req.domain}"
    task_id = "access-" + _uuid.uuid4().hex[:10]
    try:
        result = await run_in_threadpool(
            lambda: human_tasks.register_task(
                kind="access_request", task_id=task_id, audience=audience,
                title=f"Grant read access to {current_user.email}",
                summary=(f"{current_user.email} requests READ access to {req.asset}. "
                         f"Reason: {req.reason or '(none given)'}"),
                requested_by=current_user.email,        # display: who asked
                subject_ref=req.asset,                  # the resource
                # fulfillment reads these: the grant SUBJECT (authz_id, Topaz's key)
                # and the ASSET. Clearance-safe (a URN + a request, not content).
                payload={"subject": current_user.authz_id, "asset": req.asset,
                         "domain": req.domain},
            )
        )
    except human_tasks.HumanTaskConfigError as exc:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured", "message": str(exc)})
    except human_tasks.NoEntitledRecipients as exc:
        # TERMINAL 4xx (not 5xx): a task with zero entitled actors is a permanent misconfiguration, not
        # a transient outage — the caller's workflow must fail-and-release (never park or retry-forever).
        raise HTTPException(status_code=422, detail={"error": "no_entitled_recipients", "message": str(exc)})
    logger.info("access_request created: task_id=%s subject=%s asset=%s approvers=%d",
                task_id, current_user.authz_id, req.asset, len(result.get("recipients", [])))
    return {"request_id": task_id, "status": "pending",
            "approvers": len(result.get("recipients", []))}


class TriageTaskRequest(_BaseModel):
    """File a TRIAGE task: an input that could not be prepared for review, routed to
    the humans who own the answer about it.

    WHY THIS EXISTS. A content refusal (the extraction produced nothing reviewable,
    the review-state was unsourced) used to surface ONLY as a failed Dagster run —
    pipeline vocabulary, in a tool the reviewer does not open. The notice then ceased
    to exist for everyone whose job is processing notices: the invisible-dead-notice
    failure the sensor design rejected polling to avoid, reintroduced through the
    ERROR path. Three live notices died this way.

    Deliberately GENERIC (no domain in the route, the kind, or this model): `domain`
    selects the audience and `subject_ref` names the artifact. A refused ANYTHING can
    be filed here; sustainment notices are simply the first caller.
    """
    subject_ref: str                      # the artifact that could not be prepared (s3 key / URN)
    title: str
    summary: str
    reason_code: str = ""                 # the refusal status, e.g. REVIEW_STATE_UNSOURCED
    task_id: Optional[str] = None         # caller-supplied dedup key; derived from subject_ref if absent
    domain: str = "SUSTAINMENT"           # selects the audience
    audience: Optional[str] = None        # override; defaults to the domain's review audience
    payload: Optional[dict] = None


# The capability a caller must be able to INVOKE to file a triage task. Filing one is an
# EFFECT (it materializes rows in humans' queues), so it is gated in the capability
# namespace like every other effect — deny-by-default, git-asserted in
# policy/capability_grants.yaml. DISTINCT from who may ACT on the resulting task (the
# task_audience gate, enforced at /act): a service files, humans act.
_MESH_FILE_TRIAGE = "mesh:fileTriageTask"


@app.post("/triage_tasks")
async def file_triage_task(
    req: TriageTaskRequest,
    current_user: User = Depends(get_current_user),
):
    """Route an unprocessable input to the audience that owns the answer about it.

    IDEMPOTENT on `task_id`: a notice refused twice must not mint two tasks, so a
    re-drive returns ALREADY_FILED (200) rather than duplicating. The caller supplies
    a task_id derived from the ARTIFACT's identity — never from an extracted field
    (that is what made `doc_id` collide across documents).

    The requester is stamped from the authenticated identity, so the queue records
    which identity filed it (a service, honestly, when a service did).
    """
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks
    allowed = await run_in_threadpool(
        lambda: human_tasks.check_can_invoke(_MESH_FILE_TRIAGE, current_user.authz_id)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail={
            "error": "not_entitled_to_file_triage",
            "capability": _MESH_FILE_TRIAGE,
            "message": (f"{current_user.authz_id} lacks can_invoke({_MESH_FILE_TRIAGE}); "
                        f"grant it in capability_grants.yaml"),
        })
    import hashlib
    task_id = req.task_id or ("triage-" + hashlib.sha1(req.subject_ref.encode()).hexdigest()[:12])
    audience = req.audience or f"disposition_review:{req.domain}"
    try:
        if await run_in_threadpool(lambda: human_tasks.task_exists(task_id)):
            logger.info("triage_task already filed: task_id=%s subject=%s", task_id, req.subject_ref)
            return {"task_id": task_id, "status": "ALREADY_FILED", "audience": audience}
        result = await run_in_threadpool(
            lambda: human_tasks.register_task(
                kind="extraction_refusal", task_id=task_id, audience=audience,
                title=req.title, summary=req.summary,
                requested_by=current_user.authz_id,   # species-honest: a service says so
                subject_ref=req.subject_ref,
                payload={**(req.payload or {}), "reason_code": req.reason_code,
                         "domain": req.domain},
            )
        )
    except human_tasks.HumanTaskConfigError as exc:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured", "message": str(exc)})
    except human_tasks.NoEntitledRecipients as exc:
        # TERMINAL 4xx: an audience with zero actors cannot receive the refusal, and a triage task
        # nobody sees is the very failure this route exists to end. The caller must surface it.
        raise HTTPException(status_code=422, detail={"error": "no_entitled_recipients", "message": str(exc)})
    logger.info("triage_task filed: task_id=%s reason=%s audience=%s recipients=%d",
                task_id, req.reason_code, audience, len(result.get("recipients", [])))
    return {"task_id": task_id, "status": "FILED", "audience": audience,
            "recipients": len(result.get("recipients", []))}


@app.get("/me/human_tasks")
async def get_my_human_tasks(current_user: User = Depends(get_current_user)):
    """The caller's pending queue (REST initial-load; the live path is the
    Electric subscription). Filtered by recipient_id=caller.authz_id — the SAME key
    the Electric proxy injects, so REST and streaming agree by construction."""
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks
    try:
        tasks = await run_in_threadpool(lambda: human_tasks.list_tasks_for(current_user.authz_id))
    except human_tasks.HumanTaskConfigError:
        tasks = []
    # `email` is DISPLAY only; the queue was filtered on authz_id above.
    return {"email": current_user.email, "tasks": tasks}


# ── PCN/PDN disposition review — start ────────────────────────────────────────
class ReviewStartRequest(_BaseModel):
    """Start a grouped disposition review for a notice. The extraction-sourced fields
    (`impacted_parts`, `doc_needs_review`, etc.) are PASSED THROUGH from the caller — the
    BFF MUST NOT reconstruct `impacted_parts` from a graph projection: per-part
    `needs_review` lives only in the doc-tools extraction, both graphs drop it, and
    start_review's `review_state_is_unsourced` tripwire fails a request built from the
    lossy graph. So the BFF forwards the extraction payload verbatim and adds only the
    authenticated identity (`approver`) — never trusting a client-supplied approver."""
    notice_id: str
    impacted_parts: list  # extraction-sourced [{affected_mpn, replacement_mpn, needs_review}]
    doc_type: str = "PCN"
    categories: Optional[list] = None
    in_scope_mpns: Optional[list] = None
    doc_needs_review: bool = False
    # PROVENANCE ATTESTATION — "extraction" when the caller read the parts + their
    # per-part needs_review straight from review.json. start_review's tripwire fires when
    # this is ABSENT (a graph-built request cannot honestly set it). MUST be forwarded:
    # dropping it here silently re-armed the tripwire against every honest sensor request
    # and refused whole notices (live regression 2026-07-30).
    review_state_source: Optional[str] = None
    # Extraction-quality warnings that must reach the reviewer ("PARTS MAY BE MISSING:
    # 2/5 table crops failed"). Dropping it here severed the warning thread at its FIRST
    # hop, so a degraded extraction would have reviewed as though complete.
    extraction_warnings: Optional[list] = None
    domain: str = "SUSTAINMENT"          # selects the review audience disposition_review:<domain>
    audience: Optional[str] = None        # override; defaults to disposition_review:<domain>
    # ARTIFACT IDENTITY for ingress idempotency: content-hash + location of the extraction
    # this request was built from (ETag+key, exactly what the sensor's run_key uses). It is
    # NOT the notice id — see _ingress_idempotency_key. Absent for hand-driven ops calls,
    # which are then honestly non-idempotent rather than falsely deduplicated.
    request_key: Optional[str] = None
    # ARTIFACT LOCATION — a full `s3://bucket/key`, and the ONE client-suppliable input to the
    # admission posture. A SEPARATE field from `request_key` on purpose: that one is the artifact's
    # IDENTITY (`{epoch}{ETag}-{key}`) and exists for ingress idempotency. They were conflated for a
    # day and it refused every derive — the starter fetched the identity string and asked S3 for a
    # key with an ETag glued to the front. Identity and location are different jobs; one string
    # cannot hold both. Full URI rather than a bare key so this service and engine-a cannot disagree
    # about which bucket the artifact lives in (bare-key tolerance WAS that coupling).
    artifact_uri: Optional[str] = None
    # The doc-tools extraction trace id (review.json.trace_id), forwarded so the review
    # composition nests under the SAME Langfuse trace as the extraction (ADR-0038).
    trace_id: Optional[str] = None
    # ── ADMISSION FACTS: REMOVED FROM THE CONTRACT (ADR-0034 phase 1.3, consumer half) ────────
    # `format_fingerprint` / `pipeline_version` were briefly accepted here as caller-supplied
    # facts. They are gone: ReviewStarter DERIVES both from the artifact `artifact_uri` names.
    #
    # Removing them from the MODEL (not merely ignoring them) is the point — Pydantic drops
    # undeclared keys, so an old caller still sending them is silently and correctly ignored
    # rather than half-honoured. The admission posture now has exactly one client-suppliable
    # input: the pointer.


def _ingress_idempotency_key(request_key: Optional[str], approver: str) -> Optional[str]:
    """The Restate ingress idempotency key, or None to send no key at all.

    WHAT IT FIXES. `start_review` composes per-part (resolve subject, entitlement, ruleset
    evaluation), so a hundreds-of-parts notice can outrun the caller's HTTP budget. Restate
    keeps composing after the client gives up — the invocation is durable — but the caller
    sees a ReadTimeout, the Dagster run fails, and a re-drive starts a SECOND composition
    racing the first. Durability was never the gap; the gap was that the front door had no
    way to say "this is the same attempt". With a key, a retry ATTACHES to the in-flight
    invocation and returns its real outcome. Exactly-once is already sealed INSIDE the
    workflow; this closes the same property at ingress.

    KEYED ON THE ARTIFACT, NEVER ON `notice_id`. notice_id is `doc_id` — LLM-extracted, and
    it degrades to a shared fallback exactly when extraction is failing ("inbound" for every
    PDF in one inbox, live 2026-07-30). Keying here on it would make two DIFFERENT documents
    attach to each other's composition, so one notice would silently receive the other's
    review. That is the same hazard the sensor's run_key and the triage task_id already
    refused; this is its third enforcement point.

    The distinction the key must preserve is SUPERSEDE vs DUPLICATE: a RE-EXTRACTION (new
    content at the same location) is new work and must get a NEW invocation, while a RETRY
    (same content) must attach. ETag+key gives exactly that, because it moves when the
    content moves and holds still when it doesn't.

    APPROVER IS STAMPED SERVER-SIDE into the key, because the composed workflow_id is
    `pcn-review-{notice_id}-{approver}`: two initiators on one artifact are two different
    outcomes, and sharing a key would hand the second caller the first's workflow. Adding
    it from the authenticated identity (not the body) also stops a caller from aiming at
    someone else's invocation slot.

    NO KEY WHEN THE CALLER CANNOT NAME AN ARTIFACT (the hand-driven ops/re-drive path).
    Returning None sends NO header, which is honestly non-idempotent — the alternative,
    inventing a key from whatever fields happen to be present, is an optimistic default
    that would look safe while silently deduplicating unrelated requests. A human
    re-driving a notice generally WANTS a fresh attempt anyway.

    NAMED WAKE — this synchronous shape is transitional. When workflow selection lands
    (ADR-0034 Phase 2 / the autonomous trust path) the ingress goes async: the BFF `send`s
    and returns 202, and the sensor's refusal routing moves INTO the Restate handler,
    because there will be no synchronous response left to classify. Until then the 300s
    hold is a bounded wait on a DEDUPLICATED invocation — ugly, honest, safe. See
    docs/reference/refusal-routing-design.md ("NAMED WAKE") for why converting early would mean
    designing the ingress contract twice.
    """
    rk = (request_key or "").strip()
    if not rk:
        return None
    return hashlib.sha1(f"{rk}|{approver}".encode()).hexdigest()


# start_review outcomes that mean "the request/ruleset was bad", surfaced as 422 (not 200).
_PCN_REVIEW_BAD_REQUEST = {"REVIEW_STATE_UNSOURCED", "RULESET_INVALID", "RULES_NOT_FOUND"}


@app.post("/reviews")
async def start_review(
    req: ReviewStartRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Compose a notice into a grouped disposition review (proxies engine-a's durable
    ReviewStarter.start_review). The APPROVER is stamped from the authenticated
    identity (`authz_id` — the Topaz key engine-a's can_act checks), never from the body,
    so a caller cannot start a review as someone else. The raw bearer is forwarded as
    `user_jwt` because the downstream grouped-task register + dispatch mint act as this
    user. Honest outcomes pass through: STARTED / NO_RESIDUE are 200; an initiator not
    entitled to invoke mesh:startReview is NOT_ENTITLED_TO_INITIATE -> 403 (authz deny); a
    bad/unsourced request or corrupt ruleset is 422 (never a silent success).

    TRIGGER STATUS: this endpoint is the OPS / RE-DRIVE path, NOT the primary trigger.
    The CANONICAL trigger is the extraction->review Dagster sensor
    (`iagent.defs.extraction_review_sensor`), which fires this same start_review flow
    automatically when a doc-tools extraction lands its review.json — one review per
    notice (idempotent on the fingerprint), impacted_parts sourced from review.json.
    Call this route by hand only to re-drive a specific notice (e.g. after fixing a
    ruleset / grant) — same status as re-running a Dagster partition."""
    raw_token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    body = {
        "notice_id": req.notice_id,
        "doc_type": req.doc_type,
        "categories": req.categories,
        "impacted_parts": req.impacted_parts,     # extraction pass-through (tripwire source)
        "in_scope_mpns": req.in_scope_mpns,
        "doc_needs_review": req.doc_needs_review,
        "review_state_source": req.review_state_source,   # attestation — arms/disarms the tripwire
        "extraction_warnings": req.extraction_warnings,   # degradation warnings -> the reviewer
        "approver": current_user.authz_id,        # identity from the token — NOT client-supplied
        "audience": req.audience or f"disposition_review:{req.domain}",
        "user_jwt": raw_token,
    }
    # `request_key` IS forwarded now — it was originally withheld as "transport-level identity
    # for the ingress, not an input to composition", and review IDENTITY turned out to be
    # exactly what needed it. The composed workflow key derived from `notice_id` (the
    # LLM-extracted doc_id), which made two documents sharing a doc_id collapse into ONE
    # review and — because Restate workflow keys are SINGLE-USE — left a notice whose first
    # attempt died unable to ever produce a review again. Live at work 2026-07-31: eleven
    # notices, eleven `STARTED` logs, one review.
    body["request_key"] = req.request_key or ""
    body["trace_id"] = req.trace_id or ""       # extraction trace id -> ReviewStarter adopts it (ADR-0038)
    # THE ARTIFACT'S LOCATION — a DIFFERENT field from the identity above, and the entire admission
    # contract. This is a REBUILDING HOP (the body is hand-enumerated twice over), which is exactly
    # where `review_state_source` and `extraction_warnings` were silently dropped in 2026-07-30; a
    # field that does not appear on this line does not exist downstream. Pinned by
    # tests/test_review_payload_passthrough.py.
    body["artifact_uri"] = req.artifact_uri or ""
    # ADMISSION FACTS ARE NO LONGER FORWARDED (ADR-0034 phase 1.3, consumer half). ReviewStarter
    # DERIVES `format_fingerprint` and `pipeline_version` from the artifact `artifact_uri` points at,
    # so a caller can no longer assert the trust key and thereby choose its own supervision level.
    # The pointer (forwarded above) is the entire admission contract now.
    try:
        # Sized to the PART COUNT, not to a nominal request. start_review resolves a
        # subject, checks entitlement and evaluates the ruleset PER PART, so a
        # hundreds-of-parts notice (routine now that extraction reads the text layer)
        # far outruns a 30s budget — and this ceiling sits INSIDE the caller's, so a
        # short value here makes the sensor's longer timeout meaningless. Env-tunable.
        _start_timeout = float(os.getenv("REVIEW_START_TIMEOUT", "300"))
        # Idempotency at the FRONT DOOR: a retry after a client timeout attaches to the
        # in-flight composition instead of racing a second one against it. Absent when the
        # caller named no artifact — no header, honestly non-idempotent.
        _idem = _ingress_idempotency_key(req.request_key, current_user.authz_id)
        _headers = {"idempotency-key": _idem} if _idem else {}
        async with httpx.AsyncClient(timeout=_start_timeout) as client:
            rr = await client.post(
                f"{_RESTATE_INGRESS_URL}/ReviewStarter/start_review", json=body,
                headers=_headers,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "review_start_unreachable", "message": str(exc)})
    if rr.status_code != 200:
        # THE ERROR PATH IS ITSELF AN ERROR SURFACE, and this line was the counterexample. It used to
        # raise a bare `502 {"error": "review_start_failed", "code": <n>}` and DISCARD the body — so
        # every refusal the starter can produce arrived at the caller IDENTICAL. Witnessed live
        # 2026-08-06: four deliberately different pointers (absent / an identity string / a bare key /
        # a well-formed URI to a nonexistent object) all returned the same opaque 502, while Restate
        # had answered `422` with the full reason each time. The classification was computed, correct,
        # and thrown away at the last hop — legibility that stops at the pod boundary is not
        # legibility, and this is why an earlier debugging session was sent to S3 for what was a
        # caller-side field mistake.
        #
        # A TERMINAL refusal is a STATEMENT about the request, not a transport failure, so it keeps
        # its own 4xx. Only a genuine 5xx stays a 502 — conflating them told every caller "the
        # gateway is broken" when the truth was "your pointer is malformed". Consistent with the
        # `_PCN_REVIEW_BAD_REQUEST` branch below, which already forwards the engine's own body.
        try:
            _rb = rr.json()
        except Exception:  # noqa: BLE001 — a non-JSON body must not become an unrelated 500
            _rb = {}
        _msg = (_rb.get("message") if isinstance(_rb, dict) else None) or rr.text[:1000]
        if 400 <= rr.status_code < 500:
            raise HTTPException(
                status_code=rr.status_code,
                detail={"error": "review_start_refused", "code": rr.status_code, "message": _msg},
            )
        raise HTTPException(
            status_code=502,
            detail={"error": "review_start_failed", "code": rr.status_code, "message": _msg},
        )
    out = rr.json()
    logger.info("pcn review start: notice=%s approver=%s status=%s",
                req.notice_id, current_user.authz_id, out.get("status"))
    if out.get("status") in _PCN_REVIEW_BAD_REQUEST:
        raise HTTPException(status_code=422, detail=out)
    if out.get("status") == "NOT_ENTITLED_TO_INITIATE":
        # The INITIATOR lacks can_invoke(mesh:startReview) — an authz DENY (403), distinct from a bad
        # request (422). The auto-starter service surfaces this as a failed Dagster run; a human caller
        # gets a clean 403. (Who may REVIEW is a separate gate, downstream at the task layer.)
        raise HTTPException(status_code=403, detail=out)
    return out


def _restate_key(k: str) -> str:
    """URL-encode a Restate virtual-object key for safe embedding in an ingress
    URL path. A key derived from a notice_id can carry spaces or '#' (messy
    extraction doc_ids, e.g. 'PCN # 23-002'); left raw, the '#' truncates the URL
    as a fragment and the Restate call fails — which is why the batch/submit/approve
    calls returned 502 (review_batch_unreachable) and the UI card rendered empty.
    Encoding is a no-op for already-clean keys, so it also recovers reviews that
    were STARTED under a messy key (the SDK keyed them fine; only the URL lookup
    broke)."""
    from urllib.parse import quote
    return quote(k or "", safe="")


def _restate_refusal_message(resp) -> str:
    """Best-effort reason out of a Restate handler's TerminalError body.

    Every fallback returns something a reader can act on rather than an empty string:
    a denial that arrives with no reason is only marginally better than a denial
    mislabelled as an outage, and the reporter must fail louder than what it reports."""
    try:
        body = resp.json()
    except Exception:
        return (getattr(resp, "text", "") or "").strip()[:500] or f"refused with {resp.status_code}"
    if isinstance(body, dict):
        for k in ("message", "detail", "error"):
            v = body.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(body)[:500]


@app.get("/reviews/{workflow_id}/batch")
async def get_review_batch(
    workflow_id: str,
    current_user: User = Depends(get_current_user),
):
    """Fetch the reviewer's grouped-review batch (parts + proposed dispositions + needs_review flags) so
    the UI can show it before deciding — a blind accept-all can't handle a needs_review row, which is a
    mandatory per-item exception. EXISTENCE-ORACLE-SAFE: the caller must hold THIS grouped task in their
    OWN pending queue (same authz_id filter as /act); a caller who isn't the approver gets 404, never a
    peek at another approver's batch. engine-a's get_batch serves only the per-approver-authored state."""
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks
    try:
        rows = await run_in_threadpool(
            lambda: human_tasks.list_tasks_for(current_user.authz_id, status="pending")
        )
    except human_tasks.HumanTaskConfigError:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured"})
    match = next((t for t in rows
                  if t.get("workflow_id") == workflow_id and t.get("kind") == "grouped_review"), None)
    if match is None:
        raise HTTPException(status_code=404, detail={"error": "review_not_found"})
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # get_batch takes NO input — send an EMPTY body. A JSON `{}` body is rejected 400 by Restate
            # (input supplied to a no-input handler); an empty POST is the correct invocation.
            rr = await client.post(
                f"{_RESTATE_INGRESS_URL}/GroupedReview/{_restate_key(workflow_id)}/get_batch",
            )
            rr.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "review_batch_unreachable", "message": str(exc)})
    b = rr.json()
    # Map engine-a state items -> the UI ReviewItem shape (mpn/subject/proposed_disposition/needs_review).
    items = [{"mpn": it.get("mpn"), "subject": it.get("subject"),
              "proposed_disposition": it.get("proposed_disposition"),
              "needs_review": bool(it.get("needs_review", False))} for it in b.get("items", [])]
    return {
        "batch_id": match["task_id"],        # the grouped HumanTask id — what /act is addressed on
        "notice_id": b.get("notice_id"),
        "notice_type": b.get("notice_type", "PCN"),
        "notice_fingerprint": b.get("notice_fingerprint"),
        "approver": current_user.authz_id,
        "items": items,
        # Extraction-quality warnings qualifying this batch — surfaced so the reviewer
        # knows how much to trust the list before dispositioning it. A degraded
        # extraction (timed-out vision crop, failed header pass) can yield a PARTIAL
        # parts list that is indistinguishable from a complete one; missing parts get
        # no disposition and nobody notices. Proceeding on degraded data is acceptable;
        # proceeding silently is not.
        "extraction_warnings": list(b.get("extraction_warnings") or []),
    }


# ── PCN notice PROVENANCE feeder (evidence card) ──────────────────────────────
# Read-side join at DISPLAY time (NOT batch payload): where a review value came
# from in the source document. Extraction stays the authority; the graph's lossy
# projection isn't widened. The REAL doc-tools artifacts (review.json + text.json
# + manifest.json + table crops + page renders) are read from MinIO, located by
# DERIVING the notice's prefix from its own review.json (_resolve_notice_prefix
# below). A notice with no extraction returns EMPTY provenance — an HONEST absence,
# never fabricated.
#
# REMOVED (2026-07-28): the _PROV_FIXTURE / _PAGE_DIMS demo placeholders that
# invented shaped MPNs (NSR…) for two synthetic notices. They served fake evidence
# for every UNMAPPED notice — i.e. every real extraction — so the evidence card
# looked green while showing another document's fabricated parts. Honest-empty
# beats fabricated-green; the real artifacts are what the card must show.
_ARTIFACT_BUCKET = "processing-artifacts"
# OPERATOR PIN OVERRIDES (notice_id -> prefix), EMPTY by default. The general case
# is DERIVED per review.json doc_id (_resolve_notice_prefix / the index below); add
# an entry here ONLY to force a specific notice to a specific prefix (e.g. to
# disambiguate a doc_id collision). A pin wins over derivation. The two hardcoded
# demo notices that used to live here were removed — the derived index resolves
# them like every other real extraction.
_NOTICE_ARTIFACT_PREFIX: dict = {}

# The review-artifacts root scanned to DERIVE the prefix for any notice not in the
# hand-maintained map above. The sensor writes each extraction's review.json under
# here; its doc_id IS the notice_id and the review.json's parent path IS the prefix.
_NOTICE_SCAN_ROOT = os.environ.get("REVIEW_WATCH_PREFIX", "sustainment/")
_NOTICE_PREFIX_INDEX: dict = {}            # doc_id -> prefix, lazily derived
_NOTICE_PREFIX_INDEX_AT: float = 0.0       # monotonic ts of the last full scan
_NOTICE_PREFIX_INDEX_MIN_INTERVAL = 30.0   # a miss re-scans at most this often


def _build_notice_prefix_index() -> dict:
    """DERIVE notice_id -> artifact-prefix by scanning the review-artifacts root
    for every '*/review.json' and reading its doc_id. This replaces the
    hand-maintained _NOTICE_ARTIFACT_PREFIX for the general case (the twice-flagged
    interim index): the doc_id INSIDE review.json is the notice_id, and the
    review.json's parent path is exactly the prefix
    _read_notice_provenance_from_store consumes — so evidence resolves for EVERY
    extracted notice, not two demos. A single unreadable review.json is skipped,
    never sinks the whole index."""
    import json as _json
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3", endpoint_url=_MINIO_ENDPOINT_URL, aws_access_key_id=_MINIO_ACCESS_KEY,
        aws_secret_access_key=_MINIO_SECRET_KEY, region_name=_MINIO_REGION,
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )
    index: dict = {}
    suffix = "/review.json"
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=_ARTIFACT_BUCKET, Prefix=_NOTICE_SCAN_ROOT
    ):
        for obj in (page.get("Contents") or []):
            key = obj["Key"]
            if not key.endswith(suffix):
                continue
            try:
                rj = _json.loads(s3.get_object(Bucket=_ARTIFACT_BUCKET, Key=key)["Body"].read())
            except Exception:  # noqa: BLE001
                continue
            doc_id = rj.get("doc_id")
            if doc_id:
                index[doc_id] = key[: -len(suffix)]
    return index


def _resolve_notice_prefix(notice_id: str) -> "Optional[str]":
    """notice_id -> MinIO artifact prefix. The explicit map wins (the demo notices
    / operator pins); otherwise the DERIVED index. On a miss the index is rebuilt
    at most once per _NOTICE_PREFIX_INDEX_MIN_INTERVAL, so a freshly-landed notice
    resolves without a restart while a genuinely-absent one can't thrash the scan."""
    pinned = _NOTICE_ARTIFACT_PREFIX.get(notice_id)
    if pinned:
        return pinned
    global _NOTICE_PREFIX_INDEX, _NOTICE_PREFIX_INDEX_AT
    hit = _NOTICE_PREFIX_INDEX.get(notice_id)
    if hit:
        return hit
    import time as _time
    now = _time.monotonic()
    if not _NOTICE_PREFIX_INDEX or (now - _NOTICE_PREFIX_INDEX_AT) >= _NOTICE_PREFIX_INDEX_MIN_INTERVAL:
        try:
            _NOTICE_PREFIX_INDEX = _build_notice_prefix_index()
        except Exception as exc:  # noqa: BLE001
            logger.warning("notice prefix index rebuild failed: %s", exc)
        _NOTICE_PREFIX_INDEX_AT = now
    return _NOTICE_PREFIX_INDEX.get(notice_id)


def _read_notice_provenance_from_store(prefix: str) -> list:
    """Read a notice's REAL provenance from MinIO: review.json (the extracted
    values + bboxes + match metadata) joined to its table CROPS. No full-page
    render exists (doc-tools defers the page rasterizer), so the crop IS the
    source-table region — highlight-on-crop, which is also the row-level check the
    element-granular bbox can't give. Crop join: text.json Table elements ->
    page -> image basename -> manifest embedded_images -> s3:// crop URL."""
    import os.path as _op
    import json as _json
    import boto3
    from botocore.config import Config
    s3 = boto3.client(
        "s3", endpoint_url=_MINIO_ENDPOINT_URL, aws_access_key_id=_MINIO_ACCESS_KEY,
        aws_secret_access_key=_MINIO_SECRET_KEY, region_name=_MINIO_REGION,
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )

    def _get_json(key: str):
        return _json.loads(s3.get_object(Bucket=_ARTIFACT_BUCKET, Key=key)["Body"].read())

    review = _get_json(f"{prefix}/review.json")
    manifest = _get_json(f"{prefix}/manifest.json")
    text = _get_json(f"{prefix}/text.json")
    embedded = manifest.get("embedded_images") or {}

    # Full-page renders — the CONTEXT half of the evidence (which table, where on
    # the page, what surrounds it) that the crop can't give. PAGE-COHERENCE SEAL:
    # key by the page each entry DECLARES, so a page image is served for page N
    # only if the manifest says it IS page N — a right-crop/wrong-page render
    # can't recreate the mismatch class one level up. Absent (notices ingested
    # before the rasterizer, or non-PDF) → no page image, honest degrade.
    page_url_by_num = {}
    for pe in (manifest.get("pages") or []):
        pn, url = pe.get("page"), pe.get("s3_url")
        if isinstance(pn, int) and url:
            page_url_by_num[pn] = url

    # Table elements with their bbox + text + crop — for a PRECISE, COHERENT join.
    # (An MPN can sit on a page with several tables; "first table on the page" is
    #  wrong. The value anchored to ONE element with a specific bbox.)
    def _bbox(md: dict):
        pts = ((md.get("coordinates") or {}).get("points")) or None
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return [min(xs), min(ys), max(xs), max(ys)]

    def _iou(a, b) -> float:
        if not a or not b:
            return 0.0
        ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
        ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        if inter <= 0:
            return 0.0
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        denom = area_a + area_b - inter
        return inter / denom if denom > 0 else 0.0

    tables = []
    for e in (text if isinstance(text, list) else []):
        md = e.get("metadata") or {}
        if e.get("type") == "Table" and md.get("image_path"):
            url = embedded.get(_op.basename(md["image_path"]))
            if url:
                tables.append({
                    "page": md.get("page_number"),
                    "bbox": _bbox(md),
                    "text": (e.get("text") or "") + " " + (md.get("text_as_html") or ""),
                    "crop": url,
                })

    items = []
    for it in review.get("review_items", []):
        fp = it.get("field_path", "")
        if not fp.endswith("affected_mpn"):
            continue  # the card keys parts by affected MPN
        pg = it.get("page_number")
        val = it.get("value") or ""
        ib = (it.get("bboxes") or [None])[0]
        review_reason = it.get("review_reason")

        # COHERENCE SEAL: only serve a crop whose element TEXT CONTAINS the matched
        # value — the evidence must attest provenance it actually has. Among the
        # page's tables that contain the value, pick the best bbox overlap (the
        # element the value anchored to). If none contain it, serve NO crop rather
        # than a mismatched table (the exact failure that made the instrument lie).
        cands = [t for t in tables if t["page"] == pg and val and val in t["text"]]
        best = max(cands, key=lambda t: _iou(ib, t["bbox"])) if cands else None
        crop_url = best["crop"] if best else None
        if not best and val:
            review_reason = review_reason or (
                f"value not located in any source table on page {pg} (coherence check failed)"
            )

        items.append({
            "field_path": fp,
            "mpn": val,
            "value": val,
            "source_snippet": it.get("source_snippet") or "",
            "page_number": pg,
            "bboxes": it.get("bboxes") or [],
            "page_dims": it.get("page_dims"),
            "region": it.get("region") or "table",
            "match_method": it.get("match_method") or "not_found",
            "match_confidence": it.get("match_confidence") or 0.0,
            "needs_review": bool(it.get("needs_review")),
            "review_reason": review_reason,
            "coherent": crop_url is not None,  # the served crop's text contains the value
            "crop_url": crop_url,  # s3:// — served via FederatedImage
            # The page render is served for EVERY item that has one — including
            # not_found (no crop): "here's the document, we couldn't anchor it,
            # you look" is the honest-degradation money shot the override fires on.
            "page_image_url": page_url_by_num.get(pg),  # s3:// full-page, page-coherent by construction
        })
    return items


@app.get("/notices/{notice_id}/provenance")
async def notice_provenance(
    notice_id: str,
    current_user: User = Depends(get_current_user),
):
    """Serve a notice's extraction provenance for the evidence card: the REAL
    doc-tools artifacts (review.json values + bboxes + table crops + page renders)
    from MinIO, located by DERIVING the notice's prefix from its own review.json
    (_resolve_notice_prefix). No fixture: a notice with no locatable extraction
    returns EMPTY provenance — an honest absence, never fabricated evidence."""
    from starlette.concurrency import run_in_threadpool
    prefix = await run_in_threadpool(lambda: _resolve_notice_prefix(notice_id))
    if not prefix:
        logger.info("no artifact prefix resolved for notice %r — empty provenance", notice_id)
        return {"notice_id": notice_id, "page_image_url": None, "items": [], "source": "none"}
    try:
        items = await run_in_threadpool(lambda: _read_notice_provenance_from_store(prefix))
        return {"notice_id": notice_id, "page_image_url": None, "items": items, "source": "doc-tools"}
    except Exception as exc:  # noqa: BLE001
        # HONEST degrade: a store/parse error returns empty (with the reason logged),
        # never fabricated placeholder evidence that masks the failure as green.
        logger.warning("notice provenance read failed for %s (prefix %s): %s", notice_id, prefix, exc)
        return {"notice_id": notice_id, "page_image_url": None, "items": [], "source": "error"}


# ── PCN parts-by-state dashboard FEEDER ───────────────────────────────────────
# The ONE pcn-aware presentation surface (grep-able; the M2 deletion test covers it). It hand-assembles
# an INSTANCES_BY_PROPERTY archetype payload (docs/reference/pcn-dashboard-payload-schema.md) from engine-o's
# /instances_by_property. Everything pcn lives in these VALUES; the cortex-ui renderer is generic and knows
# none of it. Each field is the hand-assembled projection of a `rendersAs` triple M3 will declare, so the
# M2 swap to a generic /instances endpoint touches ONLY this feeder — the renderer does not move.
_PCN_STATE_VOCABULARY = ["dispatchQualification", "dispatchLTB", "dispatchAltSourcing", "archive"]
_PCN_DASHBOARD_COLUMNS = [
    {"key": "instance", "label": "Part",       "from": "row_identity"},
    {"key": "state",    "label": "State",      "from": "pcn:dispositionState"},
    {"key": "ref",      "label": "Resolution", "from": "pcn:dispositionRef"},
    {"key": "ruleset",  "label": "Policy",     "from": "pcn:proposedByRuleset"},
]


@app.get("/instances_by_property")
async def instances_by_property_dashboard(
    state: str = "dispatchQualification",
    current_user: User = Depends(get_current_user),
):
    """FEEDER: assemble the INSTANCES_BY_PROPERTY payload for the parts-by-disposition-state dashboard.
    Pulls rows from engine-o /instances_by_property and wraps them in the archetype the generic renderer
    consumes. The pcn-specific columns/vocabulary/target are hand-set HERE (the temporary feeder); the
    renderer receives only the archetype shape."""
    if state not in _PCN_STATE_VOCABULARY:
        raise HTTPException(status_code=400, detail={"error": "unknown_state", "state_vocabulary": _PCN_STATE_VOCABULARY})
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            rr = await client.post(
                f"{_DAGSONTOLOGY_SVC_URL}/instances_by_property", json={"disposition_state": state},
            )
            rr.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "parts_by_state_unreachable", "message": str(exc)})
    parts = rr.json().get("parts", [])
    # Map engine-o's {part, ref, ruleset} rows to the archetype's column keys (state is the query filter).
    rows = [{"instance": p.get("part"), "state": state, "ref": p.get("ref"), "ruleset": p.get("ruleset")}
            for p in parts]
    return {
        "archetype": "INSTANCES_BY_PROPERTY",
        "title": "Parts by disposition state",
        "target": {"domain": "SUSTAINMENT", "class": "pcn:Component",
                   "filter_property": "pcn:dispositionState", "filter_value": state},
        "columns": _PCN_DASHBOARD_COLUMNS,
        "row_identity": {"key": "instance", "iri": True, "display_from_local_name": True},
        "state_vocabulary": _PCN_STATE_VOCABULARY,
        "rows": rows,
    }


# ── Engine P planning measures (ADR-0042) ────────────────────────────────────
#
# A THIN PASS-THROUGH, deliberately. This route carries `output_uri` and rows and NAMES NO
# ARCHETYPE — the archetype is `select_presentation`'s decision, made from the PAYLOAD against
# the CALLER'S registered menu. `/instances_by_property` above hand-sets its archetype and is
# a documented temporary feeder; copying that here would re-open `archetype-chosen-before-data`
# at the BFF, one hop from where it was closed.
#
# `frontend_id` is threaded from a header rather than assumed. Wiring it as None is the trap
# `docs/plans/render-request-carries-no-frontend-id.md` records: every caller resolves to the
# default menu and every answer becomes a KNOWLEDGE_DOCUMENT — a regression that reads as
# completion. Absent stays ABSENT; a plausible substitute would make an anonymous caller
# indistinguishable from a registered one, which is the distinction ADR-0042 Ruling 9 rests on.
# THE SERVICE IS `iagent-engine-p`. engines.yaml names services by COMPONENT (engine-p),
# while the IMAGE and the Keycloak client are named planning-agent — they differ for this
# engine and only for this engine. This default said `iagent-planning-agent`, which is a
# service that has never existed, so this route could not reach Engine P at all;
# ENGINE_P_URL is unset in the ConfigMap, so the wrong default was the live value.
#
# SECOND OCCURRENCE of one mistake. The same wrong name was fixed in Engine P's own
# ENGINE_P_PUBLIC_URL on 2026-08-22; that fix was applied where it was found and the other
# site was never enumerated. tests/test_service_urls_are_real.py now enumerates for us.
_ENGINE_P_URL = os.getenv("ENGINE_P_URL", "http://iagent-engine-p:8095")


class PlanMeasureBody(_BaseModel):
    """`state_ref` is what makes a diff expressible without a session (ADR-0042 OQ2):
    the same verb over two refs IS the diff. Defaults to baseline so a caller that does not
    care about scenarios never has to know they exist."""
    state_ref: str = "baseline"
    params: dict = {}


@app.post("/plan/measure/{fn}")
async def plan_measure(
    fn: str,
    body: PlanMeasureBody,
    x_frontend_id: Optional[str] = Header(default=None, alias="X-Frontend-Id"),
    current_user: User = Depends(get_current_user),
):
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            rr = await client.post(
                f"{_ENGINE_P_URL}/measure/{fn}",
                json={"state_ref": body.state_ref, "params": body.params},
            )
    except Exception as exc:
        # 502, never a 200 with empty rows. An unreachable engine and an empty result are
        # different facts and only one of them means "nothing is planned".
        raise HTTPException(status_code=502,
                            detail={"error": "planning_engine_unreachable", "message": str(exc)})

    if rr.status_code == 422:
        # The honest-refusal path, preserved across the hop. Collapsing `not_in_model` into a
        # 200 with [] would render as "none found" — a false statement about something that
        # does not exist.
        raise HTTPException(status_code=422, detail=rr.json().get("detail"))
    if rr.status_code >= 400:
        raise HTTPException(status_code=rr.status_code, detail=rr.json())

    out = rr.json()
    return {
        "measure": out.get("measure", fn),
        "output_uri": out.get("output_uri"),
        "state_ref": out.get("state_ref", body.state_ref),
        # The pull trigger's discriminant (ADR-0042 OQ1) and the live view's freshness stamp.
        "state_version": out.get("state_version"),
        "rows": out.get("rows"),
        "frontend_id": x_frontend_id,
    }


@app.get("/plan/state_version")
async def plan_state_version(
    state_ref: str = "baseline",
    current_user: User = Depends(get_current_user),
):
    """The refresh loop's cheap poll (ADR-0042 OQ1) — the server half cortex already calls.

    THE JOIN IS A RENAME, and that is the whole reason this route exists rather than the
    client calling engine-p's endpoint directly. Engine P answers `{state_ref, version}`;
    cortex's `fetchPlanStateVersion()` reads `{state_version}`. Two correct halves that do
    not meet, which is this week's recurring shape — the axis keys, the DashboardUI envelope,
    and now this.

    `state_ref` ECHOES BACK, and it is not decoration. The client's current signature takes no
    argument, so it polls `baseline` — whose version NEVER BUMPS, because ops apply to
    scenarios. A refresh loop polling baseline looks like it works and never fires. Echoing
    the ref is what lets a caller notice it asked about the wrong plan. Without it the failure
    is silent, and silent-wrong is the mode this repo keeps paying for.

    A card evaluated against a scenario MUST pass that scenario's ref. The projected component
    now carries `state_ref` for exactly this call.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            rr = await client.get(f"{_ENGINE_P_URL}/state/{state_ref}/version")
    except Exception as exc:
        # 502, never a 200 with version 0. An unreachable engine and a plan that has never
        # moved are different facts, and one of them would stop the refresh loop forever
        # while looking exactly like "nothing has changed".
        raise HTTPException(status_code=502,
                            detail={"error": "planning_engine_unreachable", "message": str(exc)})

    if rr.status_code == 404:
        # An unknown ref is a 404, not a 200 with 0 — see above. Same argument as the
        # not_in_model refusal on the measure route one function up.
        raise HTTPException(status_code=404, detail=rr.json().get("detail", state_ref))
    if rr.status_code >= 400:
        raise HTTPException(status_code=rr.status_code, detail=rr.json())

    out = rr.json()
    return {"state_ref": out.get("state_ref", state_ref), "state_version": out.get("version")}


# -- The plan WRITE seam (ADR-0042 section 3) ---------------------------------
#
# Engine P has had a complete write surface since Phase 1 -- fork, append op, baseline op,
# commit ceremony, reschedule -- and NONE of it was reachable from a browser. The BFF had two
# /plan/ routes, both reads. Both halves built, neither connected; the drag beat's commit
# callback resolved to `undefined` and would have had nowhere to send it.
#
# WHY THESE CANNOT COPY /plan/measure's JUSTIFICATION, which is the load-bearing constraint on
# this whole block. That route is classified releasable_by_design because "plan state is
# portfolio read-model, entitlement-scoped where the verb runs; the BFF adds no scoping of its
# own and must not." A WRITE cannot borrow either clause: reading an entitled read-model and
# CHANGING it are different acts, and "the engine will scope it" is not an authorization story
# for a mutation. So each route below carries its own gate, and each gets its own manifest row.

_PLAN_WRITE_DOMAIN = "PORTFOLIO_PLANNING"


def _require_plan_write(current_user: User, action: str) -> None:
    """The write gate. EMPTY ENTITLEMENTS DENY, deliberately.

    `User.entitled_domains` is documented as honest-empty -- "empty list = no entitled domains
    (honest-empty), not 'no filter'" -- and its own note says downstream gates treat empty as
    least-privilege: deny privileged, allow generalist. Changing portfolio plan state is
    privileged, so empty denies here rather than falling through to the engine.

    THIS IS A SECOND GATE, NOT THE ONLY ONE. Engine P still owns the decision about what a
    caller may touch, and it must -- the BFF cannot see plan contents. What the BFF owns is the
    IDENTITY, which the engine cannot see. Gating here on a domain the caller demonstrably
    lacks turns "the engine would have refused" into "this never reached the engine", and keeps
    an unentitled caller from mapping which scenario ids exist by reading refusal codes.
    """
    if _PLAN_WRITE_DOMAIN not in (current_user.entitled_domains or []):
        raise HTTPException(status_code=403, detail={
            "error": "not_entitled_to_change_the_plan",
            "action": action,
            "required_domain": _PLAN_WRITE_DOMAIN,
            "message": "Changing plan state requires the PORTFOLIO_PLANNING domain.",
        })


async def _engine_p_write(path: str, payload: dict) -> dict:
    """POST to Engine P and FORWARD ITS REFUSAL VERBATIM.

    The refusals this hop must not swallow, each built deliberately upstream:

        422  blank rationale, or a scenario with no ops ("a decision that disposed nothing is
             not a decision") -- the ceremony's gate, which runs BEFORE anything is applied
        400  an op naming something the model does not contain (never a silent no-op: the room
             would believe it made a change the diff cannot show)
        404  an unknown scenario
        409  a scenario id that already exists

    Collapsing any of these into a 200 would put the BFF exactly where a governance refusal
    goes to die. The BFF re-validates NONE of them: two places deciding whether a rationale is
    blank is how they come to disagree, and the engine's copy is the one that runs before the
    baseline moves.
    """
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            rr = await client.post(f"{_ENGINE_P_URL}{path}", json=payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "planning_engine_unreachable", "message": str(exc)})

    if rr.status_code >= 400:
        try:
            body = rr.json()
            detail = body.get("detail", body) if isinstance(body, dict) else body
        except Exception:
            detail = getattr(rr, "text", "engine refused")
        raise HTTPException(status_code=rr.status_code, detail=detail)
    return rr.json()


class PlanForkBody(_BaseModel):
    scenario_id: str
    name: str
    base: str = "baseline"
    created_at: str = ""


class PlanOpBody(_BaseModel):
    """The engine's wire shape for an op, passed through unchanged. Deliberately NOT re-typed
    per op-kind here: the closed union and its refusals live in Engine P, and a second
    definition would drift from that one silently."""
    op: str
    project_id: Optional[str] = None
    site_id: Optional[str] = None
    org_id: Optional[str] = None
    period: Optional[str] = None
    kind: Optional[str] = None
    amount: Optional[float] = None
    start: Optional[str] = None
    end: Optional[str] = None


class PlanRescheduleBody(_BaseModel):
    """A drag, as the client can honestly describe it: which bar moved, and where to.

    NOTE WHAT IS ABSENT -- anything about site impacts. cortex-ui holds no site-impact data at
    all, so a client sending impact ops would be INVENTING them. The policy derives both ops
    server-side, where the state is.
    """
    project_id: str
    start: str
    end: str


class PlanCommitBody(_BaseModel):
    """`actor` is ABSENT ON PURPOSE -- see the route."""
    rationale: str = ""
    alternatives: Optional[list] = None
    question_trail: Optional[list] = None


@app.post("/plan/scenario")
async def plan_fork(body: PlanForkBody, current_user: User = Depends(get_current_user)):
    """Fork a scenario -- the sandbox a drag happens in, so no drag ever edits baseline."""
    _require_plan_write(current_user, "fork a scenario")
    return await _engine_p_write("/scenario", body.model_dump())


@app.post("/plan/scenario/{scenario_id}/op")
async def plan_append_op(
    scenario_id: str, body: PlanOpBody, current_user: User = Depends(get_current_user),
):
    """Append one op to a scenario. Returns the new version -- which is exactly what the
    refresh loop's poll compares against."""
    _require_plan_write(current_user, "change a scenario")
    return await _engine_p_write(f"/scenario/{scenario_id}/op", body.model_dump())


@app.post("/plan/baseline/op")
async def plan_baseline_op(body: PlanOpBody, current_user: User = Depends(get_current_user)):
    """The "costs persist" exception -- FUNDING OPS ONLY, and the engine enforces that.

    This proxy stays thin for exactly that reason. Widening it into a generic passthrough that
    accepted a schedule op would defeat the anti-goal it exists to serve: no editing baseline
    directly from a drag.
    """
    _require_plan_write(current_user, "write baseline")
    return await _engine_p_write("/baseline/op", body.model_dump())


@app.post("/plan/scenario/{scenario_id}/reschedule")
async def plan_reschedule(
    scenario_id: str, body: PlanRescheduleBody,
    current_user: User = Depends(get_current_user),
):
    """THE DRAG. Two ops, not one -- and the derivation happens where the state is.

    `MoveProject` alone moves the BAR and not the LOAD, because site-impact windows are
    deliberately independent of project windows: a rollout's disruptive phase is narrower than
    the rollout. A client emitting only the project move would draw a schedule change with no
    site consequence -- a demo that lies about its own model. Engine P derives both,
    offset-preserved, and appends them as ordinary, individually-undoable ops.
    """
    _require_plan_write(current_user, "reschedule a project")
    return await _engine_p_write(f"/scenario/{scenario_id}/reschedule", body.model_dump())


@app.post("/plan/scenario/{scenario_id}/commit")
async def plan_commit(
    scenario_id: str, body: PlanCommitBody,
    current_user: User = Depends(get_current_user),
):
    """The commit ceremony -- THE ONE PATH THAT WRITES BASELINE.

    THE ACTOR IS THE AUTHENTICATED CALLER, NEVER THE REQUEST BODY. Engine P takes `actor` as a
    field because it cannot see who is calling; the BFF can, and it is the only layer that can.
    Forwarding a client-supplied actor would make the DecisionArtifact -- the governance record
    of who moved the portfolio and why -- FORGEABLE by anyone who can post JSON. So the body
    carries no `actor` at all and this route supplies it from the token: a field that cannot be
    sent cannot be spoofed.

    The rationale refusal is NOT re-implemented here. Engine P checks it FIRST, before the
    scenario resolves and before any op applies, precisely so a refused commit changes nothing.
    This hop's job is to not swallow the 422 on the way back.
    """
    _require_plan_write(current_user, "commit a scenario to baseline")
    payload = {**body.model_dump(), "actor": current_user.authz_id}
    return await _engine_p_write(f"/scenario/{scenario_id}/commit", payload)


# ── ADR-0028 canvas persistence ──────────────────────────────────────────────
class CanvasesBody(_BaseModel):
    """The user's full custom-canvas set (CustomCanvas[]), stored verbatim as
    jsonb. The GLOBAL canvas is derived and never sent."""
    canvases: list = []


# ── THE SEEDING INTENT, SERVER HALF (ADR-0042) ──────────────────────────────
#
# "make me a portfolio canvas" — the demo's opening beat. Five gold-tier
# questions asked through THE SAME INTERVIEW PATH any typed question takes, in
# template-slot order, returning the minted artifact ids for cortex's
# `seedPortfolioCanvas(orderedIds)`.
#
# ── RULING (a): IT ASKS QUESTIONS. IT DOES NOT INVOKE VERBS. ────────────────
# This route calls its own /interview/stream over localhost, once per question,
# rather than calling engine-p's /measure/* directly. That is not indirection
# for its own sake: a seeded card must carry a DECISION PATH or it is not an
# artifact. A browser-invisible measure call produces a picture with no
# provenance, no routing record and no entitlement check — governance bypass
# wearing a shortcut's clothes. Reusing the governed path literally is the only
# way "seeded exactly like a typed question" is a fact rather than a claim.
#
# ── RULING (b): SEQUENTIAL, NOT PARALLEL. ──────────────────────────────────
# Five concurrent runs against `max_concurrent_runs: 2` — with a reaper gap
# that deadlocked this queue twice in one day — is how the substrate dies at
# 3am with nobody awake. Sequential costs ~25 minutes for a full seed, which is
# FINE: seeding is a PRE-WARM operation, not an on-stage one.
#
# ── ORDER IS THE DECLARATION ───────────────────────────────────────────────
# PORTFOLIO_PLANNING_TEMPLATE (cortex-ui/src/lib/stageConstants.ts) declares
# five slots and names them in comments: an anchor spanning the top, then two
# pairs. This list is that order, so slot assignment lives HERE — in the
# seeder — and the receiver only places what it is handed, in the order it is
# handed. A template that chose which measure went where would be reaching into
# the seeder's job; a seeder that computed coordinates would be reaching into
# the template's.
#
# Every phrasing is from the resolver-verified set, re-checked against the live
# substrate. NOTE: subject resolution SHIFTS when the ontology or verb set
# changes — "where are we over budget" moved Portfolio 0.86 -> Site 0.75 across
# a single prime. Re-verify after any prime before trusting this list.
PORTFOLIO_CANVAS_QUESTIONS: list[dict] = [
    {"slot": 0, "measure": "plan_schedule", "question": "what is scheduled by initiative and phase"},
    {"slot": 1, "measure": "plan_cost_curve", "question": "what does spend look like per period"},
    {"slot": 2, "measure": "plan_site_load", "question": "which sites are overloaded"},
    # "BY ORGANIZATION", NOT "by initiative" — and the reason is a live defect, not taste.
    # Measured 2026-08-28 on the stored artifact: the by-initiative form returned ELEVEN
    # ORGANISATIONS (group_by=org, first row `O1 | Corporate Capital Committee`), because BAML
    # extracts the slot and the supervisor's dispatch payload does not carry it, so the verb ran
    # on its default. The card was a correct org-grouped view answering a question that said
    # something else, with NO disclosure surface — the strip renders routing, not verb params.
    # `org` IS the default, so this phrasing makes the seeded card TRUE.
    # Revert to the by-initiative form when the carry lands; the acceptance test for that build
    # is literally this question returning initiatives.
    # See [[slots-are-extracted-then-dropped-at-dispatch]] and runbook A6.
    {"slot": 3, "measure": "plan_funding_gap", "question": "where is funding short by organization"},
    {"slot": 4, "measure": "plan_maturity_grid", "question": "capability maturity by site versus target"},
]


class SeedPortfolioCanvasRequest(_BaseModel):
    """`session_id` groups the five asks into one thread, as a human's five
    questions would be. `frontend_id` decides WHICH render menu the archetypes
    are selected against — omit it and every answer resolves to the labelled
    default menu, which is a different and wrong presentation decision."""
    session_id: str
    frontend_id: Optional[str] = "cortex-ui-desktop"
    active_persona: Optional[str] = "PORTFOLIO_LEAD"
    active_domains: Optional[list] = None


@app.post("/seed/portfolio_canvas")
async def seed_portfolio_canvas(
    request: SeedPortfolioCanvasRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
):
    """Ask the five, in slot order, and return their artifact ids.

    Returns `artifact_ids` ALIGNED TO SLOT INDEX. A question that fails yields
    a null in its position rather than shifting the others up — a shifted list
    would silently put the cost curve in the anchor slot and still look like a
    working canvas.

    THE CANVAS ITSELF IS NOT WRITTEN HERE. cortex's `seedPortfolioCanvas`
    composes it from these ids using its own template, which is what keeps a
    seeded canvas and a hand-built one the same object. Writing it server-side
    would duplicate stageConstants' coordinates into Python, and the first
    divergence would be invisible.
    """
    domains = request.active_domains or ["PORTFOLIO_PLANNING"]
    auth = http_request.headers.get("Authorization", "")
    base = "http://localhost:8090"

    results: list = []
    artifact_ids: list = [None] * len(PORTFOLIO_CANVAS_QUESTIONS)

    for spec in PORTFOLIO_CANVAS_QUESTIONS:
        slot = spec["slot"]
        artifact_id = (
            "urn:li:answerArtifact:"
            + request.session_id
            + "-seed"
            + str(slot)
            + "-"
            + uuid.uuid4().hex[:8]
        )
        started = time.time()
        payload = {
            "message": spec["question"],
            "session_id": request.session_id + "-seed" + str(slot),
            "frontend_id": request.frontend_id,
            "artifact_id": artifact_id,
            "active_persona": request.active_persona,
            "active_domains": domains,
        }
        status = "failed"
        detail = None
        try:
            # SEQUENTIAL BY CONSTRUCTION: awaited inside the loop. Gathering
            # these would be one line and would deadlock the run queue.
            async with httpx.AsyncClient(timeout=900.0) as client:
                async with client.stream(
                    "POST",
                    base + "/interview/stream",
                    json=payload,
                    headers={"Authorization": auth} if auth else {},
                ) as resp:
                    if resp.status_code != 200:
                        detail = "HTTP " + str(resp.status_code)
                    else:
                        saw_final = False
                        saw_error = False
                        async for line in resp.aiter_lines():
                            if line.startswith("event: final_payload"):
                                saw_final = True
                            elif line.startswith("event: pipeline_error"):
                                saw_error = True
                        # A non-200 never reaches here; an error EVENT is a
                        # different failure and must not read as success.
                        status = "ok" if (saw_final and not saw_error) else "failed"
                        detail = None if status == "ok" else "pipeline_error"
        except Exception as exc:  # noqa: BLE001 - one bad ask must not lose the rest
            detail = (type(exc).__name__ + ": " + str(exc))[:160]

        if status == "ok":
            artifact_ids[slot] = artifact_id
        results.append({
            "slot": slot,
            "measure": spec["measure"],
            "question": spec["question"],
            "artifact_id": artifact_id if status == "ok" else None,
            "status": status,
            "detail": detail,
            "elapsed_s": round(time.time() - started, 1),
        })
        logger.info(
            "seed_portfolio_canvas: slot=%s measure=%s status=%s %.1fs",
            slot, spec["measure"], status, time.time() - started,
        )

    ok = sum(1 for r in results if r["status"] == "ok")
    return {
        "session_id": request.session_id,
        # Slot-aligned; nulls are HOLES, not omissions. The receiver decides
        # whether a partial canvas is worth composing — this route does not
        # decide that for it by quietly shrinking the list.
        "artifact_ids": artifact_ids,
        "ordered_artifact_ids": [a for a in artifact_ids if a],
        "seeded": ok,
        "total": len(PORTFOLIO_CANVAS_QUESTIONS),
        "results": results,
    }


class CanvasSeedRequest(_BaseModel):
    """What cortex's `requestPortfolioCanvasSeed()` posts: a canvas TYPE, and
    nothing else. It supplies no session id and no question list, which is the
    point — the questions and their slot order are the seeder's declaration."""
    canvas_type: str = "portfolio_planning"


@app.post("/canvas/seed")
async def canvas_seed(
    request: CanvasSeedRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
):
    """The path cortex calls. A thin alias over /seed/portfolio_canvas.

    RESPONSE CONTRACT IS FIXED: `{"artifact_ids": [...]}`, slot-ordered, and
    nothing else. cortex reads exactly that field and composes the canvas with
    its own template; the server does not write the canvas, because copying
    stageConstants' coordinates into Python is how the first divergence goes
    silent.

    NULLS ARE STRIPPED HERE, AND THAT IS A REAL TRADE — flagged, not hidden.
    The underlying route returns a SLOT-ALIGNED array where a failed ask leaves
    a null hole, so a partial seed cannot silently shift later cards up a slot.
    But the client does `for (const id of artifactIds) addItemAuto(...)`, so a
    null would become a broken item. Stripping is therefore required by the
    receiver's contract, and it reintroduces the shift for PARTIAL seeds only:
    if the cost curve fails, site load lands in the cost-curve slot, every card
    is real, and nothing reports it.

    A complete seed (the normal case, and the measured one — 5/5 in 17.7 min)
    is unaffected. A partial seed produces a board that is wrong in a way only a
    human notices. Whether a partial seed should compose at all or refuse
    outright is a PRODUCT ruling, not mine to make silently at this layer: the
    client already has a no-canvas path for an empty array. `seeded` vs `total`
    is logged on every run so a partial is visible in the record even though the
    response cannot carry it.
    """
    if request.canvas_type != "portfolio_planning":
        raise HTTPException(
            status_code=400,
            detail=(
                "unknown canvas_type "
                + repr(request.canvas_type)
                + "; only 'portfolio_planning' has a seeding template"
            ),
        )

    inner = SeedPortfolioCanvasRequest(
        session_id="canvas-seed-" + uuid.uuid4().hex[:8],
    )
    result = await seed_portfolio_canvas(inner, http_request, current_user)

    seeded, total = result.get("seeded"), result.get("total")

    # ── RULED: A PARTIAL SEED REFUSES. ──────────────────────────────────────
    # Three options existed and two of them lie.
    #
    #   compact  — strip the holes and return four ids. Every card is real,
    #              every card renders, nothing errors, and the cost curve sits
    #              in the anchor slot. A board that is wrong in a way only a
    #              human notices.
    #   holes    — return [id, null, id, id, id]. The receiver does
    #              `for (const id of ids) addItemAuto(...)`, so a null becomes a
    #              broken item. Honest shape, unrenderable.
    #   refuse   — return []. cortex already has a no-canvas path for an empty
    #              array, and it leaves NO litter: an empty named board in the
    #              rail would assert that a seeding ran and legitimately
    #              produced nothing, which is a different claim from "the
    #              seeding failed".
    #
    # Refusal is the only one that keeps ABSENCE REPRESENTATIONALLY DISTINCT,
    # which is the answer this system gives everywhere else — the third state
    # in _satisfies, the rowless planning card that degrades rather than drawing
    # a confident blank, `no_intent_match` over a plausible guess. A shifted
    # board is the confidently-wrong answer in layout form.
    #
    # `seeded`/`total` ride along so the partial is VISIBLE rather than merely
    # logged. cortex reads only `artifact_ids` and ignores the rest, so this
    # costs the receiver nothing and gives the next caller the fact the log
    # would otherwise be the only witness to.
    if seeded != total:
        logger.warning(
            "canvas_seed: PARTIAL seed %s/%s — REFUSING to compose. Compacting "
            "would shift every card after the failed slot up one and produce a "
            "board that looks plausible and is wrong.",
            seeded, total,
        )
        return {"artifact_ids": [], "seeded": seeded, "total": total}

    # NEITHER OPTIONAL FIELD IS SENT, AND THAT IS THE CORRECT STATE TODAY.
    #
    # `canvas_type` was dispatched for emission on the premise that the receiver reads
    # it. IT DOES NOT — checked, 2026-08-29: cortex's CanvasSeed.contract.ts declares
    # it `required: false`, and canvasSeedFromArtifact's return type is literally
    # `{ ids: string[]; name?: string }`. No reader exists anywhere in that repo.
    # Sending it would be a PRODUCER-side write with no consumer — the exact mirror of
    # the orphan species the dispatch set out to remove — and it would cost breaking
    # the seal directly above, whose stated purpose is keeping fields a future client
    # might start depending on OFF this response. The honest order is: cortex reads it
    # first (it matters only when a second canvas_type exists), then the producer
    # states it. The arm's passthrough already carries it the day that happens.
    #
    # `name` has a real reader, and still must not be sent: the phrase path has no
    # spoken name, so any value here would be invented. The receiver already defaults
    # honestly. When elicitation can ask "what should I call it?", that ask becomes
    # the name's producer.
    return {
        "artifact_ids": [a for a in (result.get("artifact_ids") or []) if a],
        "seeded": seeded,
        "total": total,
    }


# ══════════════════════════════════════════════════════════
# The identity vault's redemption surface
# ══════════════════════════════════════════════════════════
#
# A CREDENTIAL-DISPENSING ENDPOINT, named as such. The plan item
# (docs/plans/identity-propagation-must-not-cross-run-storage.md, 1f4d645) pins six
# invariants; five of them live here and the sixth is the vault module's in-memory-ness.
# A build that drops any one of them has reverted to the thing the vault replaced.
#
# WHY THIS EXISTS AT ALL: the supervisor is not a proxy in alice's request, it is a job
# launched by it, and the only channel across that boundary is durable run config. So the
# credential cannot ride along and must be fetched on the one hop that IS live.

# INVARIANT 1 — LOCKED TO THE SUPERVISOR'S SERVICE IDENTITY, specifically.
#
# Not "any authenticated service". A second service redeeming a reference is the vault
# leaking sideways, and a generic is-authenticated check would permit exactly that. The
# value is the supervisor client's hardcoded-claim mapper output (`svc:supervisor`), which
# Keycloak asserts — it is NOT caller-supplied and therefore not spoofable, which is the
# same property that made the payload-written subject unusable elsewhere in this codebase.
#
# Env-overridable ONLY so a differently-named realm can be configured, never to widen it:
# an empty value denies everyone rather than admitting everyone.
_VAULT_REDEEMER_AUTHZ_ID = os.getenv("IDENTITY_VAULT_REDEEMER", "svc:supervisor").strip()


class RedeemIdentityBody(BaseModel):
    run_id: str
    # INVARIANT 4's input: the launcher the redeeming run has recorded in its OWN config.
    # Checked against the subject of the token that was stashed. Optional so an older
    # supervisor image degrades to "no cross-check" rather than to a hard failure — but a
    # supervisor that sends it gets the stronger guarantee.
    claimed_launcher: Optional[str] = None


@app.post("/internal/identity/redeem")
async def redeem_caller_identity(
    body: RedeemIdentityBody,
    current_user: User = Depends(get_current_user),
):
    """Hand the supervisor the caller's own token, once, for one run.

    Returns 200 with the token on the single legitimate redemption. Every other outcome is
    a refusal with a NAMED cause, because "it didn't work" is the answer that cost this
    project a day of diagnosis more than once.
    """
    caller = (current_user.authz_id or "").strip()

    # INVARIANT 1.
    if not _VAULT_REDEEMER_AUTHZ_ID or caller != _VAULT_REDEEMER_AUTHZ_ID:
        # INVARIANT 6 — audited, including the refusals. An unlogged dispensing surface is
        # worse than the exchange it replaced; a refused redemption is the MOST interesting
        # line this endpoint can write, so it is logged at error.
        _vault_audit_log.error(
            "identity_vault: REFUSED redemption for run_id=%s — caller %r is not the "
            "supervisor identity (%r). A second service redeeming a reference is the vault "
            "leaking sideways.",
            body.run_id, caller or "<none>", _VAULT_REDEEMER_AUTHZ_ID,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "not_the_redeemer",
                "message": (
                    "The identity vault is redeemable only by the supervisor's service "
                    "identity."
                ),
            },
        )

    # INVARIANTS 2, 3, 4 are all enforced inside this one call, atomically.
    result = VAULT.redeem(body.run_id, claimed_launcher=body.claimed_launcher)

    # INVARIANT 6 — one line per redemption: run_id, subject, timestamp, outcome. The
    # timestamp is the log record's own. The vault's whole legitimacy is that the token's
    # journey is VISIBLE.
    _vault_audit_log.info(
        "identity_vault: redemption run_id=%s caller=%s subject=%s outcome=%s",
        body.run_id, caller, result.subject or "-", result.outcome,
    )

    if result.ok:
        return {"token": result.token, "subject": result.subject}

    # A replay is not a 404. Distinguishing them is the point of the tombstone, and
    # collapsing them here would throw away the discrimination the vault just made.
    _status = 409 if result.outcome == RedemptionOutcome.ALREADY_REDEEMED else 404
    raise HTTPException(
        status_code=_status,
        detail={
            "error": result.outcome,
            "run_id": body.run_id,
            "message": {
                RedemptionOutcome.ALREADY_REDEEMED: (
                    "This reference was already redeemed. It is single-use by design; a "
                    "second redemption is the compromise tell and is never re-issued."
                ),
                RedemptionOutcome.LAUNCHER_MISMATCH: (
                    "The run's recorded launcher does not match the stashed token's "
                    "subject. Refused, and the reference has been consumed."
                ),
                RedemptionOutcome.EXPIRED: (
                    "The reference expired. It is bounded to the dispatch window "
                    f"({vault_ttl_seconds()}s), not to the token's own lifetime."
                ),
            }.get(
                result.outcome,
                "No reference is held for this run. Four causes, in the order worth "
                "checking: cortex-bff RESTARTED (the vault is in-memory by design, so "
                "in-flight seeds do not survive one); cortex-bff is running MORE THAN "
                "ONE REPLICA, so the stash and this redemption landed on different "
                "pods; the dispatch window elapsed; or nothing was ever stashed for "
                "this run.",
            ),
        },
    )


@app.get("/me/canvases")
async def get_my_canvases(current_user: User = Depends(get_current_user)):
    """The caller's stored custom canvases (durable, cross-device). Empty when
    persistence is unconfigured — the client falls back to its localStorage."""
    from starlette.concurrency import run_in_threadpool
    from . import user_canvas
    try:
        canvases = await run_in_threadpool(
            lambda: user_canvas.get_canvases(current_user.authz_id)
        )
    except user_canvas.CanvasConfigError:
        canvases = []
    return {"canvases": canvases}


@app.put("/me/canvases")
async def put_my_canvases(
    body: CanvasesBody, current_user: User = Depends(get_current_user)
):
    """Upsert the caller's full canvas set (last-write-wins per user, keyed on
    authz_id). 503 when persistence is unconfigured so the client keeps its
    local copy rather than silently losing writes."""
    from starlette.concurrency import run_in_threadpool
    from . import user_canvas
    try:
        await run_in_threadpool(
            lambda: user_canvas.save_canvases(current_user.authz_id, body.canvases)
        )
    except user_canvas.CanvasConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "canvas_unconfigured", "message": str(exc)},
        )
    return {"ok": True}


# ── ADR-0028 canvas GRAPH lineage edges (proxy to Engine D's gated endpoint) ──
class LineageEdgesProxyBody(_BaseModel):
    """The current answers' resolved subjects: [{answer_id, urn}]."""
    subjects: list = []


@app.post("/canvas/lineage_edges")
async def canvas_lineage_edges(
    body: LineageEdgesProxyBody, current_user: User = Depends(get_current_user)
):
    """Directed 1-hop DataHub lineage edges among the caller's answered subjects,
    for canvas GRAPH mode. The gateway is deliberately NOT a DataHub client —
    DataHub access stays in Engine D (the wrapper), behind its catalog-metadata
    gate (single boundary, one gated path). We thread the caller's entitlement
    (domains + email) so that gate applies; lineage the caller isn't entitled to
    see is never returned. Honest-empty on any failure."""
    import httpx
    from urllib.parse import urlparse
    ent = current_user.entitlements
    entitled_domains = sorted({c.domain for c in ent.cells})
    u = urlparse(os.getenv("DATAHUB_WRAPPER_URL", "http://iagent-engine-d:8085"))
    target = f"{u.scheme}://{u.netloc}/lineage_edges"
    payload = {
        "subjects": body.subjects,
        "entitled_domains": entitled_domains,
        "caller_email": current_user.authz_id,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(target, json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        logger.warning("canvas lineage proxy → Engine D failed (honest-empty): %r", exc)
        return {"edges": []}


@app.post("/human_tasks/{task_id}/act")
async def act_on_human_task(
    task_id: str,
    req: HumanTaskActRequest,
    current_user: User = Depends(get_current_user),
):
    """Approve/reject a task. Application-layer gate: RE-CHECK Topaz `can_act` for
    this caller on the task's audience (deny-by-default) BEFORE acting. Slice 1b
    adds the Restate `approve` call that resumes the suspended workflow; the
    foundation validates the gate + resolution bookkeeping."""
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks
    # NB the verb is validated PER KIND below, once the task's kind is known — not against a
    # hardcoded pair here. A triage task ("this notice could not be prepared") accepts
    # acknowledge/re-drive and must REFUSE approve/reject, because storing "approved" on an
    # extraction failure writes a decision the task's semantics cannot represent, and
    # ADR-0034's decision records would archive it immutably as promotion evidence.
    # Look up the task's audience (from any of the caller's recipient rows) to
    # re-check. Keyed on authz_id — same as the replication filter.
    try:
        rows = await run_in_threadpool(
            lambda: human_tasks.list_tasks_for(current_user.authz_id, status="pending")
        )
    except human_tasks.HumanTaskConfigError:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured"})
    match = next((t for t in rows if t["task_id"] == task_id), None)
    if match is None:
        # Not PENDING for this caller. Two very different truths hide here, and
        # conflating them is a lie the multiplayer case makes routine: a TEAMMATE
        # already resolved it (any-one-of-the-audience acts for the team, so their
        # action flipped THIS caller's row too), versus the caller never held it.
        # Look up the caller's OWN row: if it carries a resolution, say so WITH its
        # provenance (409) so the reviewer learns who settled it instead of "not
        # found" — the settled-task story, reaching the concurrent case. The lookup
        # is scoped to recipient_id = caller, so it can never become an existence
        # oracle for another audience's queue; a non-recipient still gets 404.
        settled = await run_in_threadpool(
            lambda: human_tasks.get_task_resolution(task_id, caller_id=current_user.authz_id)
        )
        if settled and settled.get("status") != "pending":
            raise HTTPException(status_code=409, detail={
                "error": "task_already_resolved",
                "task_id": task_id,
                "status": settled.get("status"),
                "decision": settled.get("decision"),
                "acted_by": settled.get("acted_by"),
                "acted_at": settled.get("acted_at"),
                "message": "This task was already resolved by a member of its audience.",
            })
        raise HTTPException(status_code=404, detail={"error": "task_not_found"})
    audience = match["audience"]
    allowed = await run_in_threadpool(lambda: human_tasks.check_can_act(audience, current_user.authz_id))
    if not allowed:
        raise HTTPException(status_code=403, detail={"error": "not_authorized_to_act", "audience": audience})

    # VERB VALIDATION, per the task's OWN species — after authz (never leak a kind to an
    # unauthorized caller through a validation error) and before any write.
    try:
        human_tasks.validate_decision(match.get("kind") or "", req.decision, req.comment)
    except human_tasks.InvalidDecisionForKind as exc:
        raise HTTPException(status_code=422, detail={
            "error": "invalid_decision_for_kind",
            "kind": match.get("kind"),
            "allowed": sorted(human_tasks.verbs_for_kind(match.get("kind") or "")),
            "message": str(exc),
        })

    # FULFILLMENT (grouped_review): the decision must be VALIDATED by the workflow
    # (GroupedReview.submit_decision) BEFORE the projection is resolved. submit_decision
    # can REFUSE (an unverified row riding accept-all, a blank-reason override) — a policy
    # outcome, not a transient failure — and a refused submission must leave the task PENDING,
    # never falsely marked approved while the workflow stays suspended. So unlike workflow_ack
    # (mark-then-best-effort-resume), we validate FIRST and mark resolved ONLY on acceptance.
    if match.get("kind") == "grouped_review":
        wf = match.get("workflow_id")
        if not wf:
            # No workflow key on the row -> nothing to resume (engine-a must stamp workflow_id
            # on the grouped-task register). Fail loudly rather than mark-resolved-and-dangle.
            raise HTTPException(status_code=409, detail={"error": "grouped_review_unresumable",
                "message": "grouped-review task has no workflow_id; cannot resume the review"})
        if req.decision == "rejected":
            # A grouped-review rejection must CANCEL the durable workflow, else it dangles
            # suspended (the suspend-vs-fail DoS). Cancellation-on-reject is a filed follow-up;
            # refuse loudly here rather than mark-resolved-and-dangle. To change dispositions,
            # the reviewer sends per-part `overrides` and approves.
            raise HTTPException(status_code=501, detail={"error": "grouped_reject_not_wired",
                "message": "grouped-review rejection needs workflow cancellation (follow-up); "
                           "use per-part overrides to change dispositions, then approve"})
        # approved -> submit the (accept-all + optional per-part overrides) decision.
        #
        # `acted_by` RIDES THE DECISION AS DATA (2026-08-05). Until now nothing carried the
        # DECISION'S ACTOR past this point, so every row the resolution minted was attributed to
        # `requested_by` — which faithfully records who STARTED the review (the sensor's service
        # identity, in the canonical flow). `requested_by` was never lying about its own meaning;
        # readers inferred "who decided" from "who requested" because no field carried the decider.
        # Fixed ADDITIVELY: the actor becomes its own field and `requested_by` keeps its meaning,
        # so no consumer has to coordinate a semantics change.
        #
        # STAMPED SERVER-SIDE FROM THE AUTHENTICATED IDENTITY, never from the request body — the
        # same rule as `approver` at start_review. And it is the identity `check_can_act` just
        # authorized above, so the value is the one the gate actually admitted rather than a claim
        # travelling beside it.
        #
        # PROVENANCE, NOT AUTHORIZATION. This attributes; it does not authorize. The effect's
        # credential is minted at use under the pipeline's own identity — keeping those two facts
        # in separate fields is the notice-A ruling, and putting the actor here is what lets them
        # travel separately instead of being conflated back into one value.
        #
        # DO NOT COLLAPSE THIS WITH THE ENVELOPE `acted_by` SENT BELOW. They carry the same value
        # today and answer DIFFERENT QUESTIONS: this one is PROVENANCE (who decided — archived with
        # the decision record), the envelope one is the AUTHORIZATION SUBJECT the handler's own
        # can_act gate checks. Merging them would mean a future change to how decisions are
        # ATTRIBUTED silently re-aims the GATE — the two would move together with nothing to say
        # they should not. Same-value-different-question is the reason for the duplication, not an
        # oversight. See docs/plans/approval-bypass-bpmn-runner.md.
        decision = {"overrides": req.overrides or {}, "acted_by": current_user.authz_id}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                rr = await client.post(
                    f"{_RESTATE_INGRESS_URL}/GroupedReview/{_restate_key(wf)}/submit_decision",
                    # `acted_by` ALSO on the envelope, not only inside `decision`. The two
                    # are the same verified identity but they answer different questions:
                    # inside `decision` it is PROVENANCE (who decided, archived with the
                    # record), on the envelope it is the AUTHORIZATION SUBJECT the handler's
                    # own can_act gate checks. Keeping them as one field would mean a change
                    # to how decisions are attributed silently re-aimed the gate.
                    json={"decision": decision, "acted_by": current_user.authz_id},
                )
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": "review_submit_unreachable", "message": str(exc)})
        if rr.status_code in (401, 403):
            # THE HANDLER'S OWN GATE REFUSED. Report it as a refusal, not as a 502:
            # `review_submit_failed` would tell the reviewer the review service is broken
            # and send them to look for an outage instead of a missing grant. An error
            # surface that mislabels a denial as an outage is a failure this repo has
            # already paid for on the review surface once.
            raise HTTPException(status_code=403, detail={
                "error": "not_authorized_to_act",
                "code": rr.status_code,
                "message": _restate_refusal_message(rr),
            })
        if rr.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "review_submit_failed", "code": rr.status_code})
        sub = rr.json()
        if sub.get("status") == "already_resolved":
            # THE TIGHT RACE: this caller's row was still pending when we looked, but a
            # teammate's decision has since been consumed by the workflow. NOT
            # "still_pending" (it is settled) and NOT a hollow success — 409 with the
            # winner's provenance, joined from the projection (the workflow keeps only a
            # deterministic boolean). Same shape as the pre-submit 409 above, so the UI
            # has ONE conflict outcome to handle regardless of which path detected it.
            settled = await run_in_threadpool(
                lambda: human_tasks.get_task_resolution(task_id, caller_id=current_user.authz_id)
            ) or {}
            raise HTTPException(status_code=409, detail={
                "error": "task_already_resolved",
                "task_id": task_id,
                "status": settled.get("status") or "resolved",
                "decision": settled.get("decision"),
                "acted_by": settled.get("acted_by"),
                "acted_at": settled.get("acted_at"),
                "message": "This review was already resolved by a member of its audience.",
            })
        if not sub.get("accepted"):
            # POLICY refusal — the review stays PENDING (projection NOT marked). Surface the reason.
            return {"task_id": task_id, "decision": req.decision, "accepted": False,
                    "status": "still_pending", "reason": sub.get("reason", "")}
        # Accepted -> the workflow resumed + fanned out; NOW resolve the projection.
        n = await run_in_threadpool(
            lambda: human_tasks.mark_task_resolved(
                task_id, caller_id=current_user.authz_id, decision=req.decision, comment=req.comment
            )
        )
        logger.info("pcn grouped review approved: task_id=%s wf=%s by=%s resolved_count=%s",
                    task_id, wf, current_user.authz_id, sub.get("resolved_count"))
        return {"task_id": task_id, "decision": req.decision, "accepted": True,
                "rows_resolved": n, "review_dispatched": True,
                "resolved_count": sub.get("resolved_count")}

    n = await run_in_threadpool(
        lambda: human_tasks.mark_task_resolved(
            task_id, caller_id=current_user.authz_id, decision=req.decision, comment=req.comment
        )
    )
    logger.info("human_task acted: task_id=%s by=%s decision=%s rows=%d",
                task_id, current_user.authz_id, req.decision, n)

    # FULFILLMENT (workflow_ack): resolve the Restate promise the suspended
    # workflow is awaiting -> it RESUMES from exactly where it paused. Only an
    # AUTHORIZED caller reaches here (can_act passed above), so an unauthorized
    # /act NEVER resolves the promise — the workflow stays suspended, waiting for
    # the right approver (Situation B: unauthorized-act is a denied action, not a
    # teardown). Best-effort: the projection is already resolved; a resume failure
    # is logged, not surfaced as an act failure.
    resumed = False
    if match.get("kind") == "workflow_ack" and match.get("workflow_id"):
        status = "APPROVED" if req.decision == "approved" else "REJECTED"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                rr = await client.post(
                    f"{_RESTATE_INGRESS_URL}/BPMNWorkflowRunner/{_restate_key(match['workflow_id'])}/approve",
                    # `acted_by` is REQUIRED by the handler as of approval-bypass-bpmn-runner:
                    # it re-checks can_act itself rather than trusting that this gate ran.
                    # Threaded from `current_user.authz_id` — the identity can_act was just
                    # checked against above — so the handler re-asks the same question about
                    # the same subject and must reach the same answer. Omitting it here would
                    # turn the ONE correctly-gated path into the only refused one.
                    json={"task_id": task_id, "status": status, "comments": req.comment,
                          "acted_by": current_user.authz_id},
                )
                resumed = rr.status_code == 200
                if not resumed:
                    logger.warning("workflow resume non-200: task_id=%s wf=%s code=%s",
                                   task_id, match["workflow_id"], rr.status_code)
        except Exception as exc:
            logger.warning("workflow resume failed: task_id=%s wf=%s err=%s",
                           task_id, match["workflow_id"], exc)

    # FULFILLMENT (access_request — Case 1, ASYNC): approving writes a git-asserted
    # reader grant (asset_grants.yaml assertion, granted_by = THIS approver) and
    # flows it through the SEALED grant_sync -> Topaz -> the DA-read gate opens ->
    # the requester succeeds on a FRESH request (nothing suspended to resume). This
    # is the automation of the manual alice->reader->customers_gold rehearsal.
    granted = False
    grant_detail: dict = {}
    if match.get("kind") == "access_request" and req.decision == "approved":
        payload = match.get("payload") or {}
        subject = payload.get("subject")
        asset = payload.get("asset")
        if subject and asset:
            grant_detail = await run_in_threadpool(
                lambda: human_tasks.write_grant_and_sync(
                    subject=subject, asset=asset,
                    granted_by=current_user.authz_id,
                    reason=(req.comment or f"HITL access grant approved by {current_user.email}"),
                )
            )
            granted = bool(grant_detail.get("ok"))
            if not granted:
                logger.warning("access grant sync failed: task_id=%s exit=%s",
                               task_id, grant_detail.get("exit_code"))
    return {"task_id": task_id, "decision": req.decision, "rows_resolved": n,
            "workflow_resumed": resumed, "grant_written": granted}


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


@app.middleware("http")
async def _no_store_per_user_responses(request: Request, call_next):
    """Force `Cache-Control: no-store` on EVERY response (class fix).

    Every cortex-bff response is per-caller / dynamic, served at a URL that does
    NOT itself carry the caller identity (the JWT does, via Authorization). A
    shared or browser cache keyed by URL would serve one user's response to
    another in the same browser — the cross-user leak found on the Electric
    shape proxy (identical URL, per-user WHERE injected server-side) and equally
    latent on /me/human_tasks, /canvases, /federated_image, etc. (all per-user,
    none previously sending cache-control). no-store makes the whole class
    impossible; it also stops a cache from serving an authorized user's
    /federated_image to an unauthorized one. Correctness over cache-hit here.
    """
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


# ── Models ────────────────────────────────────────────────
class InterviewRequest(BaseModel):
    message: str
    # ADR-0017 amendment: WHICH FRONTEND is asking. The archetype decision is valid only
    # against the render menu of the client that will render it -- choose CHART_WIDGET
    # because cortex-ui registered it, hand it to an OpenDDIL session that never did, and
    # the result is a correct answer with an unrenderable presentation. Optional so
    # non-UI callers (curl, scripts) keep working; they resolve to the LABELLED default
    # menu rather than being special-cased.
    frontend_id: str | None = None
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
    # ADR-0026 step 4: per-prompt persona/domain override from the
    # cortex-ui picker. When present, cortex-bff validates the cell
    # is in the caller's Topaz-resolved entitlement matrix; entitled
    # → route with the override, not-entitled → 403 `cell_not_entitled`
    # with the entitled cells in the response body. When both are
    # None (legacy clients, or picker unpopulated), we fall back to
    # the caller's default cell (from entitlements.default) or,
    # failing that, to `current_user.persona` / `entitled_domains`
    # from the ADR-0009 JWT-claim path.
    active_persona: str | None = None
    active_domains: list[str] | None = None
    # THE ANSWER TO AN ASK (ADR-0033). `{slot_name: chosen_id}` for a pick the user made from
    # a menu this system offered. Optional and absent on every ordinary turn.
    #
    # SEPARATE FROM THE MESSAGE, not encoded into it, because a pick is not a phrase: routing
    # it through `message` would re-parse it, and re-parsing is the one thing the BIND path
    # exists to forbid — a menu whose selections get re-interpreted is a menu whose selections
    # are suggestions.
    #
    # NOT TRUSTED. The supervisor recomputes the menu for the verb and slot and refuses a pick
    # that is not on it, so this field is a claim the server checks rather than an instruction
    # it follows. A slot whose menu was `too_many` had nothing offered and is refused here by
    # design; that answer belongs on the free-text path instead.
    bound_slots: dict[str, str] | None = None


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
    # The component-exported typed contract (ADR-0017 amendment 2026-08-20). Absent on
    # legacy hand-authored rows, which stay admissible while migration is row-by-row.
    # This is the field `expected_fields` could never be: it carries ENCODINGS (chart_data
    # is a JSON-encoded STRING, not an array), cardinality, and the refusal vocabulary.
    contract: dict | None = None
    contract_source: str | None = None


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
    # Refused rows are RETURNED, never silently dropped. A drop would reproduce the very
    # defect admission validation exists to prevent, one layer earlier.
    rejected: list[dict] = []


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


def _primary_routing_mat(mats: list[dict]) -> dict | None:
    """The routing decision the user's ANSWER actually flowed through.

    MEASURED 2026-09-04, sandbox runs e82b3031 and 2a627ea7. A question decomposes into
    PARALLEL subtasks, each posting its own `/resolve`. Engine O's BAML calls run 8-30s against
    Ollama, two simultaneous posts contend, and one subtask times out at 30s while the other
    succeeds at ~44s. Both materialize `subtask_routing_decision`.

    THE OLD RULE WAS FIRST-TO-MATERIALIZE, AND IT PREFERS THE FAILURE BY CONSTRUCTION.
    A 30-second timeout completes SOONER than a 44-second resolve-then-classify chain, so
    whenever one subtask fails and another succeeds slowly, the failing one wins the race every
    time. Not a coin flip weighted toward failure — a rule that systematically records
    "not grounded" for a run that grounded.

    What that produced: at 21:55 the card was Engine F's VARIANCE_TREE, drawn from real EVM
    rows, inside a header reading NOT GROUNDED / General search / conf 0.00. The record was
    never stale and never stamped pre-override — it was ACCURATE about a subtask whose answer
    nobody saw, which is exactly why every reading of the capture path found nothing wrong.

    THE RULE HERE IS THE CARD'S RULE. `generate_ui_payload` picks the first result carrying an
    `output_uri` and skips the ones without — and only a MATCHED route can produce one, because
    ADR-0019 Contract B sends an ungrounded subject to the generalist, which declares none. So
    "first matched decision" is this side's expression of "the subtask the card came from".

    NOT `task_0`. That was inferred from two artifacts and it is not the card's key: at 21:47
    task_0 failed and at 21:55 task_1 did, and in both runs the card came from whichever subtask
    produced a typed output. Keying on the index would have been right twice by luck.

    Falls back to the first decision when NOTHING matched, so a genuinely ungrounded run still
    records the honest refusal it should.
    """
    routing = [
        m for m in mats
        if (m.get("assetKey", {}) or {}).get("path") == ["subtask_routing_decision"]
    ]
    if not routing:
        return None
    for m in routing:
        if str(_metadata_dict(m).get("route_status") or "") == "matched":
            return m
    return routing[0]


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


# Engine-name resolution for the routing HUD "Handled by" label lives in a
# dep-free sibling (engine_names.py) so it unit-tests without importing gateway
# (whose import connects to Postgres). Release-agnostic: anchored on the chart
# component name, not a release-prefixed / bare-vs-FQDN service name. Kept under
# the original underscore aliases so the call sites below are unchanged.
from .engine_names import (  # noqa: E402
    engine_name_from_endpoint as _engine_name_from_endpoint,
    engine_name_from_provider as _engine_name_from_provider,
    handler_name_from_endpoint as _handler_name_from_endpoint,
)


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


def _compose_answer_summary(routing: dict | None) -> str:
    """Compose the answer's factual S·P headline from the captured
    routing facts — the summary the answer-first left column leads with.

    THIS IS DETERMINISTIC FORMATTING OF ALREADY-CAPTURED FACTS, NOT an
    LLM summary. Per ADR-0028 Decision 4 and the codebase's own
    synthesis-is-theater principle (see the cortex-ui Artifact type's
    resolved_intent note): the summary is a CAPTURED FACT, composed once
    HERE at the write point (where `routing` is final), stored on the
    Neo4j node, projected to its own column, and read VERBATIM by the
    card — never re-derived on read, never LLM prose.

    Two branches, both reading fields already on `routing`:

    - **SPO-rich** → ``"{subject label} · {verb label}"`` (S·P). Both are
      display labels already namespace-stripped + CamelCase-spaced by
      `_label_from_uri` (`enumerateCatalog` → "enumerate Catalog"), so
      the headline reads clean, not leaky-internal. GUARANTEED-CORRECT:
      it's the captured routing facts formatted, archetype-blind, with
      no extraction logic to get wrong.

    - **fallback / thin-SPO** → ``"No direct match — {reason}"`` from the
      structured `fallback_reason` (subject_unknown | instance_not_found
      | no_compatible_verbs | domain_scope_excluded | no_verb_classified
      | infra_error), humanized. Fallback answers get an HONEST headline,
      not a blank.

    v1 ships S·P. Object-enrichment (S·P·O — e.g. "… · owned by Analytics
    team") is deferred to v1.1 as PER-ARCHETYPE key-fact extraction at
    THIS SAME point (rendered_output is available here too), each
    extractor individually verifiable — NOT rushed onto the v1 critical
    path where a wrong extractor would ship a LYING headline. A terse-
    but-true S·P beats a rich-but-possibly-wrong S·P·O for a headline you
    navigate by.
    """
    if not routing:
        return ""
    about = routing.get("about") or {}
    action = routing.get("action") or {}
    if routing.get("fallback"):
        reason = (routing.get("fallback_reason") or "").replace("_", " ").strip()
        return f"No direct match — {reason}" if reason else "No direct match"
    # Prefer the resolved INSTANCE label (the specific thing, e.g.
    # "Customer 360") over the CLASS label (the category, e.g.
    # "Dashboard") — the instance is what makes the headline a FINDABLE
    # identifier rather than a category label (many answers share a class).
    # Three-branch honesty:
    #   - instance resolved → instance · verb  ("Customer 360 · lookup Ownership")
    #   - type/set query (no instance)         → class · verb  ("Dataset · filter By Tag")
    #     (correct for a category query, NOT a degradation)
    #   - nothing resolved (fallback)          → handled above
    instance = (about.get("instance_label") or "").strip()
    subject = instance or (about.get("label") or "").strip()
    verb = (action.get("label") or "").strip()
    if subject and verb:
        return f"{subject} · {verb}"
    # One side missing (partial routing) — return whichever we have
    # rather than a misleading "X · " with a dangling separator.
    return subject or verb


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

    # Acting-persona provenance — the CALLER persona + domain this decision
    # was computed under (persona-driven routing). The framing that makes a
    # same-query-different-verb divergence self-explaining. Distinct from
    # action.owner_persona (the answerer-side "voice").
    acting = {
        "persona": md.get("acting_persona") or None,
        "domains": [d for d in (md.get("acting_domains") or "").split(",") if d],
    }

    # Decision-path visualizer (Part 1): the resolver candidate pool —
    # winner AND losers, each with a score — is captured by the supervisor
    # as a JSON-text metadata value. Carry it through the render seam so
    # the visualizer can render losers first-class. "Render only what was
    # captured" requires the capture to REACH the boundary; an absent pool
    # projects to [] (honestly "no losers recorded"), never a crash.
    try:
        candidates = json.loads(md.get("subject_candidates") or "[]")
        if not isinstance(candidates, list):
            candidates = []
    except (ValueError, TypeError):
        candidates = []

    # THE ELIGIBILITY TRACE — what the gates took OUT, beside what survived.
    #
    # `candidates` alone cannot distinguish "nothing else was ever there" from "the only
    # option that fit was deleted before the classifier saw it". Measured 2026-09-04:
    # `planCapabilityPath` was removed by the arity gate, leaving one verb that does not
    # answer the question, and the classifier honestly abstained — which rendered as "no
    # confident action", i.e. classifier uncertainty. Two failures, opposite remedies, and
    # the record could not tell them apart.
    #
    # Same honest-empty discipline as the pool above: absent projects to [], never a crash.
    try:
        excluded = json.loads(md.get("eligibility_excluded") or "[]")
        if not isinstance(excluded, list):
            excluded = []
    except (ValueError, TypeError):
        excluded = []

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
            # HANDLER, not engine. A BFF orchestration answers the seeding verb and
            # is not an engine at all; asking only for an engine name rendered
            # "Unknown engine" in the HUD for a handler that was perfectly well
            # known. The label the user reads is a captured fact, so it has to be a
            # true one — see engine_names._NON_ENGINE_HANDLERS for why this is a
            # category rather than an entry in the engine map.
            ep_name = _handler_name_from_endpoint(handler_endpoint)
            if ep_name:
                engine_name = ep_name
        return {
            "about": {
                "label": _label_from_uri(subject_uri),
                "uri": subject_uri,
                "confidence": float(md.get("subject_confidence") or 0.0),
                "instance_resolved": bool(md.get("subject_instance_id")),
                "instance_identifier": md.get("subject_instance_id") or "",
                # Friendly instance label ("Customer 360") — the summary
                # leads with this (instance · verb) when present; empty for
                # set/type-level queries. Threaded from the resolver's
                # provenance (previously discarded at the supervisor tuple).
                "instance_label": md.get("subject_instance_label") or "",
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
            "acting": acting,
            # The candidates the winner beat — the visualizer shows the
            # contest, not just the winner (losers first-class).
            "candidates": candidates,
            "excluded": excluded,
        }

    # Fallback projection — surface that the pipeline GENUINELY fell
    # back to the generalist instead of leaving the card empty (which
    # was honest-by-omission but read to users as "system is broken").
    # The fallback IS what happened; saying so directly is the more
    # informative form of "surface what the pipeline did".
    #
    # PREFER THE STRUCTURED REASON. The supervisor captured a closed-enum
    # fallback_reason (subject_unknown | instance_not_found |
    # no_compatible_verbs | domain_scope_excluded | no_verb_classified |
    # infra_error). Pass THAT through verbatim — re-deriving a coarser
    # vocabulary here is a [[resolution-discard-pattern]] instance at the
    # render seam: it flattened instance_not_found → "no_subject" and
    # domain_scope_excluded → "no_compatible_verbs", destroying exactly
    # the distinctions the abstention arc and the PII-exploit made
    # structural. The heuristic below is retained ONLY as backward-compat
    # for pre-Part-0 materializations that carry no structured reason.
    structured_reason = md.get("fallback_reason") or ""
    fallback_reason = structured_reason or (
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
            "instance_label": md.get("subject_instance_label") or "",
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
        "acting": acting,
        "fallback_reason": fallback_reason,
        # The resolver pool that failed to ground — losers first-class,
        # so "why did nothing win" is visible with scores.
        "candidates": candidates,
        "excluded": excluded,
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


def _project_access_denied(mat: dict) -> dict | None:
    """Project a subtask_access_denied materialization into the typed
    access_denied event the cortex-ui consumes to surface the request-
    access flow. Shape: { denied_assets: [urn], subject, message }.

    Returns None if the materialization carries no denied asset (so a
    malformed/empty materialization never triggers a spurious request-
    access prompt — the prompt fires ONLY on a real denial with an asset).
    """
    md = _metadata_dict(mat)
    raw = md.get("denied_assets_json")
    assets: list = []
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                assets = [str(a) for a in parsed if a]
        except Exception:
            assets = []
    if not assets:
        return None
    return {
        "denied_assets": assets,
        "subject": md.get("subject") or "",
        "message": md.get("message") or "Access denied. You can request access.",
    }


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


def _project_graph_trace_alternates(mat: dict) -> list[dict]:
    """Verb-leg alternates for the decision-path diagram — the Instance-4
    mirror on the verb leg.

    ``compatible_verbs`` holds the FULL conjunctive Cypher∩Weaviate set the
    walk surfaced; ``_project_graph_trace`` (above) draws only the PICKED
    branch — "the answer's actual path" — and deliberately dropped the
    rest. The decision-path diagram needs the UNTAKEN compatible verbs
    too: "alternates shown" is the whole reason it's worth drawing (the
    losing branch is where the debugging lives). The fact was captured
    upstream and discarded at the render seam — same shape as the subject
    candidate pool before Part 1, one leg over.

    Emits one ``alternate_verb`` node per non-picked compatible verb:
    where that verb WOULD have led (its output class). Render-only-what-
    was-captured — only verbs actually in the compatible set, never
    invented. Empty when there was no alternative (the honest "only one
    verb fit"), which the diagram draws as a single unbranched path.
    """
    md = _metadata_dict(mat)
    picked_verb_iri = md.get("picked_verb_iri") or ""
    raw = md.get("compatible_verbs") or "[]"
    try:
        verbs = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []

    alts: list[dict] = []
    for v in verbs:
        v_iri = v.get("verb_iri") or ""
        if not v_iri or v_iri == picked_verb_iri:
            continue
        v_out = v.get("output_uri") or ""
        alt = {
            "uri": v_out or v_iri,
            "label": _label_from_uri(v_out) if v_out else _label_from_uri(v_iri),
            "role": "alternate_verb",
            "via_verb": v_iri,
            "hops": int(v.get("hops") or 0),
        }
        # Per-alternate semantic score (Weaviate hybrid query→verb match),
        # threaded from classify so the map's alternate fan sorts + labels
        # by score instead of rendering anonymous dashed lines. Absent on
        # pre-thread materializations (the map falls back to compat order).
        if v.get("classify_score") is not None:
            alt["score"] = float(v["classify_score"])
        alts.append(alt)
    return alts


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
    # ADR-0017 amendment: which frontend will render the answer. Threaded to Engine F so
    # the archetype is chosen from THAT client's registered menu. Empty is not an error --
    # Engine F falls back to its global table, i.e. today's behaviour.
    frontend_id: str = "",
    # ADR-0025 hop 2: caller's entitlement key (email) forwarded as a
    # runConfig key so the generalist-fallback subtask can hand it to
    # Engine D's query_metadata for the Topaz can_view ask.
    user_email: str = "",
    # Per ADR-0009 Step F'.2: thread user-context fields into the supervisor
    # so the supervisor's per-subtask predicate lookup (Step F'.3) can scope
    # by entitled_domains and use user_persona as the answerer fallback when
    # the matched predicate is persona-agnostic.
    # Step F'.6: candidate_verb dropped — supervisor now sends user_query
    # directly to /search_predicates (Weaviate hybrid).
    user_persona: str | None = None,
    entitled_domains: list[str] | None = None,
    entity_refs: list[str] | None = None,
    # THE SPOKEN SLOTS from /route_intent, argument name -> value. Passed explicitly rather
    # than read off the caller's `intent_extraction`, which is a local of the streaming
    # handler and not in scope here - the first draft of this carry did exactly that and
    # would have raised NameError on every request in the cluster while every test stayed
    # green, because no test calls this function.
    slots: dict | None = None,
    # The user's pick from an ask, kept SEPARATE from `slots` all the way down so the
    # supervisor can tell a chosen value from an extracted one and validate only the
    # first against the menu it offered.
    bound_slots: dict | None = None,
    trace_id: str = "",
    session_id: str = "",
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
        "user_email": user_email,
        # ADR-0017 amendment: names the rendering client so Engine F resolves ITS menu.
        "frontend_id": frontend_id or "",
        # ADR-0009 Step F'.2 additions:
        "user_persona": user_persona,
        "entitled_domains": entitled_domains,
        "candidate_verb": candidate_verb,
        "entity_refs": entity_refs,
        # THE SPOKEN SLOTS, forwarded rather than dropped. `{}` on every request until the
        # slot-filler is called - see the finding. Threaded here, beside entity_refs,
        # because the two come from the same response and are constantly confused: refs are
        # untyped values, slots are argument name -> value.
        "slots": dict(slots or {}),
        "bound_slots": dict(bound_slots or {}),
        # Telemetry (ADR-0038): threaded into execute_subtask's config so it forwards them as
        # X-Trace-Id / X-Session-Id to Engine A's /analyze — the conversation lands one trace.
        "trace_id": trace_id,
        "session_id": session_id,
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
    trace_id: str = "",   # cortex-ui X-Trace-Id (ADR-0038); seeds the analyst trace via the supervisor
    user_id: str = "default_testing_user",
    # ADR-0025 hop 2: caller's entitlement key (email); threaded to Engine D
    # so query_metadata asks Topaz can_view. Parallels entitled_domains.
    user_email: str = "",
    # Per ADR-0009 Step F'.2: user persona + entitled_domains come from the
    # JWT (see auth.User), threaded down from the /orchestrate route so we
    # don't re-decode the token mid-stream. Defaults match the auth fallback
    # so legacy callers that haven't been migrated still work.
    user_persona: str | None = None,
    entitled_domains: list[str] | None = None,
    # Capture A per ADR-0025: WHICH origin the persona / entitled_domains
    # came from. Threaded down from /orchestrate so the produced_for dict
    # construction below at line ~1370 can record it on the artifact.
    # Default "fallback" matches the persona/domains defaults above —
    # the legacy-caller path was never carrying real claims anyway, so
    # the honest default per `[[optimistic-defaults-are-dishonest]]` is
    # the failure-revealing value, not "claim".
    entitlement_source: str = "fallback",
    # THE IDENTITY VAULT (ruled 2026-08-28, see src/iagent/identity_vault.py).
    # The caller's OWN bearer token, held only for as long as this request runs. It is
    # stashed against the Dagster run id the moment launchRun returns and is NEVER put
    # into run config, logged, or echoed. This is the last point at which the run id and
    # alice's credential exist in the same place; after this the boundary is crossed by a
    # reference alone.
    caller_token: str = "",
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
        user_email=user_email,
        # ADR-0017 amendment: read straight off the request -- the UI names itself, and an
        # absent value is a NON-UI caller (curl, script), not an error.
        frontend_id=(request.frontend_id or ""),
        user_persona=user_persona,
        entitled_domains=entitled_domains,
        entity_refs=entity_refs,
        # Forwarded rather than dropped - the carry. `{}` until the slot-filler is called.
        slots=dict(intent_extraction.get("slots") or {}),
        bound_slots=dict(request.bound_slots or {}),
        trace_id=trace_id,        # cortex-ui X-Trace-Id -> runConfig -> execute_subtask -> /analyze
        session_id=session_id,    # the conversation thread -> Langfuse session grouping
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

    # ── STASH THE REFERENCE ────────────────────────────────────────────────────
    # The run exists and we still hold alice's request, so this is the one instant at
    # which `run_id` and her token are both in hand. From here the process boundary is
    # crossed by the run id ALONE — which run config already carried and which was never
    # secret. If the supervisor later dispatches a verb that needs the caller's identity,
    # it redeems this over the live in-cluster hop.
    #
    # STASHED FOR EVERY RUN, not only seeding ones: at launch time nothing knows yet
    # whether this phrase will route to a verb that needs caller identity, and inventing a
    # guess here would be the optimistic-default shape. The footprint is bounded by TTL
    # (minutes) and by process lifetime, and it never becomes durable.
    #
    # A stash failure must NOT kill the run. Every non-seeding phrase is unaffected by it,
    # and a seeding phrase fails LOUDLY at redemption with a named cause — which is the
    # honest place for it to fail, not here where the cause would be guessed at.
    if caller_token:
        try:
            VAULT.stash(run_id, caller_token, subject=user_email)
        except Exception as _vault_exc:  # noqa: BLE001
            logger.warning(
                "identity_vault: could not stash the caller reference for run %s (%s: %s). "
                "Non-seeding phrases are unaffected; a seeding dispatch will refuse at "
                "redemption with not_found.",
                run_id, type(_vault_exc).__name__, _vault_exc,
            )

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

            elif path == ["subtask_slots_decision"]:
                # HOP 2: what the system UNDERSTOOD, as opposed to what it extracted.
                #
                # `resolved_intent` has always been written from /route_intent's
                # ExtractIntent output — mode and entity_refs, captured before any
                # resolution runs — and never updated. A field named for resolution
                # holding extraction. The supervisor now emits the real thing at its
                # disposition point, which is the only line where the accepted
                # parameters, the REFUSED ones, the per-slot resolution outcomes and the
                # route|ask|abstain decision all exist at once.
                #
                # OVERWRITES RATHER THAN MERGES, deliberately. Keeping the extraction
                # under the same key beside the resolution would leave two answers to
                # "what did the system understand" in one field, and the older one reads
                # as current. The extraction is not lost — it is what /route_intent
                # returned and it is recorded on that hop.
                #
                # NOT emitted as SSE: this is provenance for the artifact, not a step for
                # the HUD, and inventing a UI event with no reader is the orphan-field
                # shape this codebase has removed twice.
                _slots_md = _metadata_dict(mat)

                def _j(key: str, fallback):
                    try:
                        return json.loads(_slots_md.get(key) or "null") or fallback
                    except (ValueError, TypeError):
                        return fallback

                _artifact_bundle["resolved_intent"] = {
                    "verb_iri": _slots_md.get("verb_iri") or "",
                    "disposition": _slots_md.get("disposition") or "",
                    "accepted_slots": _j("accepted_slots", {}),
                    "refused_slots": _j("refused_slots", []),
                    "slot_resolution": _j("slot_resolution", {}),
                }
                logger.info(
                    "resolved_intent captured for run %s: verb=%s disposition=%s "
                    "accepted=%d refused=%d",
                    run_id,
                    _slots_md.get("verb_iri") or "-",
                    _slots_md.get("disposition") or "-",
                    len(_artifact_bundle["resolved_intent"]["accepted_slots"] or {}),
                    len(_artifact_bundle["resolved_intent"]["refused_slots"] or []),
                )

            elif (
                path == ["subtask_routing_decision"]
                and "route_decision_emitted" not in emitted_steps
                # THE SUBTASK THE ANSWER CAME FROM, not the first to materialize.
                # See _primary_routing_mat: a 30s timeout beats a 44s success to
                # the finish line, so first-arrival systematically records the
                # failing subtask for a run that grounded.
                and mat is _primary_routing_mat(mats)
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
                    # Verb-leg alternates (the untaken compatible verbs) —
                    # carried as a SIBLING field so the existing text-trail
                    # panel (reads `.nodes`) is untouched while the
                    # decision-path diagram can draw the branches not taken.
                    alternates = _project_graph_trace_alternates(mat)
                    logger.info(
                        "📡 Emitting SSE 'graph_trace' for run %s: %d nodes, "
                        "%d verb-alternates",
                        run_id, len(trace_nodes), len(alternates),
                    )
                    yield _sse("graph_trace", json.dumps({
                        "nodes": trace_nodes,
                        "alternates": alternates,
                    }))
                    # Hop 1: accumulate into bundle (nodes unchanged;
                    # alternates as a sibling so the durable write stays
                    # backward-compatible).
                    _artifact_bundle["graph_trace"] = trace_nodes
                    _artifact_bundle["graph_trace_alternates"] = alternates
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

            elif (
                path == ["subtask_access_denied"]
                and "access_denied_emitted" not in emitted_steps
            ):
                # Bug 2: the data-plane can_read gate denied THIS user for
                # the asset (the specific 403 signal, not an empty result or
                # a code fumble). Emit a TYPED access_denied event so the UI
                # surfaces the request-access flow (→ /access_requests)
                # instead of an empty chart that hides the denial.
                denial = _project_access_denied(mat)
                if denial:
                    # Attach the acting DOMAIN (from the routing already
                    # projected this run — route_decision arrives before the
                    # engine denial) so the UI's access-request routes to the
                    # right approver audience (access_grant:<domain>).
                    _routing = _artifact_bundle.get("routing") or {}
                    _acting = (_routing.get("acting") or {}) if isinstance(_routing, dict) else {}
                    _domains = _acting.get("domains") or []
                    denial["domain"] = _domains[0] if _domains else ""
                    logger.info(
                        "📡 Emitting SSE 'access_denied' for run %s: %s domain=%s",
                        run_id, denial.get("denied_assets"), denial.get("domain"),
                    )
                    yield _sse("access_denied", json.dumps(denial))
                emitted_steps.add("access_denied_emitted")

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
            # HOW LONG THE ANSWER TOOK — stamped HERE, adjacent to the flip it
            # measures, and nowhere else. The operands are fixed on purpose:
            # this bundle's OWN `valid_as_of` (set once at construction) to now.
            # A future "simplification" that reads a request timestamp or a
            # step-start time would change what the number MEANS while keeping
            # its name — birth-to-complete for THIS bundle is the definition.
            #
            # Deliberately NOT set on the `failed` branches above: a failed
            # artifact has a wall-clock lifetime, but that is not an answer's
            # duration, and merging the two poisons any later aggregate.
            _artifact_bundle["duration_ms"] = max(
                0, int(time.time() * 1000) - _artifact_bundle["valid_as_of"]
            )
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
            # Compose the factual S·P headline HERE — the single write
            # point where `routing` (SPO + fallback_reason) is final and
            # the artifact is about to persist. Captured on the bundle,
            # written to the node, projected, read verbatim. See
            # `_compose_answer_summary`.
            _bundle_obj = AnswerArtifactBundle(
                id=_artifact_bundle["id"],
                question_text=_artifact_bundle["question_text"],
                summary=_compose_answer_summary(_artifact_bundle["routing"]),
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
    # ── ADMISSION VALIDATION (ADR-0017 amendment 2026-08-20) ──────────────────────
    # Was: accept everything, log it, return len(). A frontend could advertise an unknown
    # archetype or a contract with no fields and the first sign of trouble was a render
    # that produced nothing -- the failure discovered at the far end of the pipeline.
    # Now refused AT THE DOOR, per-capability, with the reason returned to the caller.
    # This is the analog of the registrar's Contract-D check on engine registrations.
    # It validates WELL-FORMEDNESS AND VOCABULARY ONLY, never authority: a UI's render
    # menu is a client describing itself, so there is deliberately no entitlement gate.
    # A BLANK STAMP IS NOT AN IDENTITY. `frontend_id: str` makes the field
    # required, but "" satisfies that and would mint a presentation row belonging
    # to nobody's menu -- precisely the payload-less orphan shape the graph reader
    # skips structurally. Refused here so it is never written, rather than
    # tolerated downstream forever.
    if not (payload.frontend_id or "").strip():
        raise HTTPException(
            status_code=422,
            detail="frontend_id must be a non-empty identity (e.g. 'cortex-ui-desktop'). "
                   "A registration with no scope belongs to no menu and cannot be served "
                   "to any caller.",
        )

    from agent_fleet.presentation_agent.capability_admission import validate_registration
    from agent_fleet.presentation_agent.capabilities import capability_slug as _capability_slug

    _admitted, _rejected = validate_registration(
        [c.model_dump() for c in payload.capabilities]
    )
    if _rejected:
        _frontend_registry_logger.warning(
            json.dumps({
                "event": "frontend_capabilities_rejected",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "frontend_id": payload.frontend_id,
                "frontend_version": payload.frontend_version,
                "rejected_count": len(_rejected),
                "rejected": _rejected,
            })
        )

    # STORE the admitted rows so decision-time lookup can consult THIS caller's menu.
    # Only admitted rows are stored: a refused capability that still influenced a decision
    # would make the refusal decorative. Replaces rather than merges -- a capability
    # dropped in a redeploy must not survive as a ghost the backend keeps choosing.
    from agent_fleet.presentation_agent import capability_registry as _cap_registry

    _stored = _cap_registry.register(
        payload.frontend_id, payload.frontend_version, _admitted
    )

    # ── THE CONVERSION: the menu becomes ROWS, via the sole writer ───────────
    #
    # Storing in `_cap_registry` alone was the packet's core defect: that registry
    # is a MODULE-LOCAL DICT and this handler runs in cortex-bff while /render_ui
    # runs in presentation-agent, so the menu could never reach the selector. The
    # in-process store stays as the single-process fallback; the GRAPH is what the
    # selector actually reads.
    #
    # THE STAMP IS THE CALLER'S DECLARED IDENTITY, never this process's. Defaulting
    # it to anything cortex-bff knows about itself would re-mint the
    # provider-is-not-a-frontend defect one hop up, with "cortex-bff" wearing the
    # field the way "engine-f" did -- and every UI behind this bff would then share
    # one menu. There is deliberately no default: absent is refused above.
    _graph_registered, _graph_failed = 0, []
    _registrar_url = os.getenv("MESH_REGISTRAR_URL")
    if _registrar_url:
        from agent_fleet.utils.mesh_registration import _emit_presentation_to_registrar

        for _c in _admitted:
            _contract = _c.get("contract") if isinstance(_c, dict) else None
            _recomputes = None
            if isinstance(_contract, dict) and "recomputes" in _contract:
                # Tri-state preserved end to end: only a DECLARED value travels.
                _recomputes = bool(_contract.get("recomputes"))
            _outcome = _emit_presentation_to_registrar(
                registrar_url=_registrar_url,
                # ⛔ SLUG VIA THE SHARED HELPER, NOT A SECOND rsplit. This read
                # `.rsplit('#', 1)[-1].lower()`, which is correct for a FULL IRI and wrong for
                # the COMPACT curie a frontend actually sends: `fin:BurnRateSeries` has no
                # `#`, so the whole thing survived and the name became
                #   presentation_multi_series_for_fin:burnrateseries__cortex-ui-desktop
                # — a URN DELIMITER inside a URN component. Measured on the live substrate
                # 2026-09-02: the __system_default__ rows written by the presentation agent
                # were clean and the cortex-ui-desktop rows written HERE carried the colon,
                # which is what identified this as the second site.
                #
                # THE SAME DEFECT WAS FIXED IN presentation_agent.capability_slug AND ONLY
                # THERE, in the same week the five-registries lesson was written up. Fixing
                # the instance you found is what stops you looking for the sibling. Imported
                # rather than re-implemented so there is no third copy to diverge.
                #
                # ⚠️ THIS CHANGES THE tool_urn, and a presentation rebind INSERTS rather than
                # replaces (see [[a-rebind-does-not-replace]]). So the next registration after
                # this ships leaves the colon-bearing rows standing and double-binds every
                # subject. It must ride the same migration as the archetype-out-of-the-name
                # ruling, which moves every presentation urn anyway.
                name=(
                    f"presentation_{str(_c.get('archetype') or '').lower()}"
                    f"_for_{_capability_slug(str(_c.get('subject_uri') or ''))}"
                    f"__{payload.frontend_id}"
                ),
                description=(
                    f"{payload.frontend_id} renders {_c.get('subject_uri')} "
                    f"as {_c.get('archetype')}"
                ),
                subject_uri=str(_c.get("subject_uri") or ""),
                object_uri=str(_c.get("object_uri") or ""),
                archetype=str(_c.get("archetype") or ""),
                expected_fields=list(_c.get("expected_fields") or []),
                persona_fit=list(_c.get("persona_fit") or []),
                domain_fit=list(_c.get("domain_fit") or []),
                version=payload.frontend_version,
                frontend_id=payload.frontend_id,
                recomputes=_recomputes,
            )
            if _outcome is True:
                _graph_registered += 1
            else:
                _graph_failed.append({"subject_uri": _c.get("subject_uri"),
                                      "reason_class": _outcome[0], "detail": _outcome[1][:200]})
        if _graph_failed:
            # LOUD, and per-capability: a menu that is half in the graph renders
            # inconsistently depending on which shape an answer takes, which is far
            # harder to read than a named failure at registration time.
            _frontend_registry_logger.warning(
                json.dumps({
                    "event": "frontend_capabilities_graph_registration_failed",
                    "frontend_id": payload.frontend_id,
                    "failed_count": len(_graph_failed),
                    "failures": _graph_failed,
                })
            )

    _frontend_registry_logger.info(
        json.dumps({
            "event": "frontend_capabilities_registered",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "user_id": current_user.id,
            "frontend_id": payload.frontend_id,
            "frontend_version": payload.frontend_version,
            "capability_count": len(payload.capabilities),
            "admitted_count": len(_admitted),
            "rejected_count": len(_rejected),
            "stored_count": _stored,
            "graph_registered_count": _graph_registered,
            "graph_failed_count": len(_graph_failed),
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
        # ADMITTED, not submitted. Reporting len(payload.capabilities) would call a
        # refused row accepted, which is the lie this endpoint used to tell.
        accepted=len(_admitted),
        rejected=_rejected,
        frontend_id=payload.frontend_id,
    )


@app.post("/orchestrate")
@app.post("/interview/stream")
async def orchestrate(request: InterviewRequest, http_request: Request,
                      current_user: User = Depends(get_current_user)):
    """
    Entry point for the Agentic Mesh.
    Delegates to Dagster GraphQL and streams step stats as SSE events
    to power Holographic Thinking Cards. Emits final payload when done.

    Per ADR-0009 Step F'.2: user_persona + entitled_domains come from the
    auth-resolved User and flow downstream to the supervisor + engines.

    ADR-0026 step 4: when the request carries `active_persona` /
    `active_domains` (the cortex-ui picker's per-prompt selection), we
    validate the cell is in the caller's Topaz-resolved entitlement
    matrix. Non-entitled → 403 `cell_not_entitled` with the caller's
    entitled cells in the body — the client knows what would work
    (honest denial per ADR-0026, not a silent downgrade). Cell entitled
    → the picker values override the JWT-claim defaults, and downstream
    routing sees the picked persona/domains.

    Precedence when a field is absent:
      1. Explicit picker override (`active_persona` / `active_domains`)
      2. User's default cell (`entitlements.default`)
      3. First cell from `entitlements.cells`
      4. Legacy JWT-claim path (`current_user.persona` /
         `current_user.entitled_domains`) — kept as a safety net for
         clients that don't set the picker AND users without seeded
         entitlements.
    """
    ent = current_user.entitlements
    # Telemetry (ADR-0038): cortex-ui mints X-Trace-Id per request; thread it so the whole
    # conversation (BFF -> supervisor -> Engine A) lands ONE Langfuse trace. Session grouping
    # uses request.session_id (the conversation thread) downstream.
    _trace_id = http_request.headers.get("X-Trace-Id", "")
    entitled_cells = [
        {"persona": c.persona, "domain": c.domain} for c in ent.cells
    ]

    # Validate per-prompt override if the caller sent one.
    if request.active_persona is not None or request.active_domains is not None:
        p = request.active_persona
        ds = request.active_domains or []
        if p is None or not ds:
            # Structured 400 body — client + logs get the same shape.
            # `denied_at` is the capture-or-lose-forever timestamp
            # the ADR-0026 morning review flagged: any denial that
            # doesn't record when-it-fired is one that a later
            # HITL-access-request flow can't sequence correctly.
            body_400 = {
                "error": "incomplete_override",
                "denied_at": datetime.now(timezone.utc).isoformat(),
                "subject": current_user.id,
                "subject_email": current_user.email,
                "session_id": request.session_id,
                "requested": {"persona": p, "domains": ds},
                "message": (
                    "active_persona and active_domains must be "
                    "supplied together — send both or neither."
                ),
            }
            logger.warning("chat_override_incomplete: %s", body_400)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=body_400,
            )
        # Every requested domain must be entitled under the requested
        # persona. Any one non-entitled cell → hard 403; we don't
        # silently drop non-entitled domains from the list.
        missing = [d for d in ds if not ent.contains(p, d)]
        if missing:
            # Capture-or-lose-forever context per the ADR-0026 morning
            # review: every denial names the subject, the exact cell
            # requested, the cells they DO have, when the decision
            # fired, and (importantly) which layer served the
            # entitlement matrix that produced the denial. If Topaz
            # says one thing but a stale cache says another, `entitlement_source`
            # + `entitlements_provenance` together are how ops
            # tells them apart when a user reports "I should have
            # access but I'm denied".
            #
            # The HITL access-request feature hangs off this exact
            # denial event — the request payload the user will
            # eventually submit ("give me DATA_STEWARD for DEFENSE")
            # is derived directly from `requested` + `subject` here.
            # Provisioning the fields now avoids retrofitting them
            # when that flow lands.
            body_403 = {
                "error": "cell_not_entitled",
                "denied_at": datetime.now(timezone.utc).isoformat(),
                "subject": current_user.id,
                "subject_email": current_user.email,
                "session_id": request.session_id,
                "requested": {"persona": p, "domains": ds},
                "requested_missing": missing,
                "entitled_cells": entitled_cells,
                "entitlement_source": current_user.entitlement_source,
                "entitlements_provenance": ent.source,
                "message": (
                    f"user {current_user.id!r} is not entitled to "
                    f"persona={p!r} for domains={missing}"
                ),
            }
            # WARN level so denials aggregate to the ops dashboard
            # without needing to be pulled out of DEBUG noise.
            logger.warning("chat_cell_not_entitled: %s", body_403)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=body_403,
            )
        effective_persona = p
        effective_domains = ds
        effective_source = "picker"
    else:
        # No override — pick the default cell, then the first cell, then
        # HONEST-EMPTY (ADR-0026 step 6): a caller with zero entitlements
        # gets persona=None + no domains — NOT a fabricated fallback.
        # `current_user.persona` is itself None here (Topaz-derived), so
        # the None flows through honestly; nothing coalesces it. The
        # generalist handles the query without a persona; any privileged
        # path hits the real gate and denies with an actionable message.
        if ent.default is not None:
            effective_persona = ent.default.persona
            effective_domains = [ent.default.domain]
            effective_source = "default"
        elif ent.cells:
            effective_persona = ent.cells[0].persona
            effective_domains = ent.domains_for(ent.cells[0].persona)
            effective_source = "first-cell"
        else:
            # honest-empty — persona is None (current_user.persona is
            # None post step-6), domains empty. Least privilege.
            effective_persona = current_user.persona  # None
            effective_domains = current_user.entitled_domains  # []
            effective_source = "none"

    logger.info(
        "orchestrate: user=%s persona=%s domains=%s source=%s "
        "entitlement_source=%s",
        current_user.id,
        effective_persona,
        effective_domains,
        effective_source,
        current_user.entitlement_source,
    )

    return StreamingResponse(
        _keepalive_wrap(
            generate_dagster_stream(
                request,
                trace_id=_trace_id,
                user_id=current_user.id,
                # ADR-0025 hop 2 + identity consolidation (2026-07-09): the
                # caller's AUTHORIZATION IDENTITY (authz_id — the
                # USER_ENTITLEMENT_CLAIM key policy/users.yaml + the seeded Topaz
                # `user` objects key on; NOT the sub in user_id, NOT necessarily
                # email). In sandbox authz_id == email (transparent); at
                # work-deploy USER_ENTITLEMENT_CLAIM=<employee-id claim> re-keys
                # this and the entitlement lookup TOGETHER with one knob. Threaded
                # so Engine D's query_metadata + Engine O's resolve ASK Topaz
                # about the SAME subject the matrix was looked up by (no
                # email-vs-employee-id divergence). The downstream param name is
                # still `user_email` but it CARRIES authz_id — a full param rename
                # (user_email→authz_id through supervisor/Engine D/Engine O) is the
                # honesty follow-up; the VALUE is the load-bearing fix. "" when
                # absent → Topaz denies (least-privileged).
                user_email=current_user.authz_id,
                user_persona=effective_persona,
                entitled_domains=effective_domains,
                # The caller's own credential, for the vault only. Read from the header
                # rather than re-minted: the whole point of the ruled design is that what
                # reaches /canvas/seed is ALICE'S OWN Ping-rooted token — the same one the
                # browser sends on the button path — never a new one minted on some
                # broker's authority.
                caller_token=(
                    (http_request.headers.get("authorization") or "")
                    .removeprefix("Bearer ")
                    .strip()
                ),
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
# Decision subgraph — the two-layer diff map's data foundation.
#
# The decision-path MAP (not the summary card) draws the decision's
# neighborhood as a spatial graph and OVERLAYS the captured decision on
# the LIVE graph, rendering their DIVERGENCE honestly:
#   captured ∩ live  → solid, on-path
#   captured − live  → ghosted (the decision traversed a node that has
#                      since changed — the staleness/defeasibility signal;
#                      the spatial form of valid_as_of)
#   live − captured  → dim context (present now, not part of the decision)
#
# This endpoint supplies the BASE layer: a BOUNDED live read of the
# decision's neighborhood — the captured class nodes plus their immediate
# (1-hop) structural context. NOT the whole graph, NOT click-to-expand
# (that's the deferred interactive explorer). The frontend already holds
# the captured decision (routing.candidates, graph_trace, alternates) and
# computes the diff against what this returns.
#
# HONESTY RULE — three states, never two. `available=true` means the live
# read succeeded and the diff is trustworthy. `available=false` is the
# COULDN'T-CHECK state (Neo4j unreachable): the frontend must show the
# captured decision LABELED "current graph state unavailable — cannot
# verify what changed", NEVER silently present captured-as-current. "I
# diffed and nothing changed" and "I couldn't diff" are different facts.
# ══════════════════════════════════════════════════════════


class DecisionSubgraphRequest(BaseModel):
    """The captured decision's node identities, sent by the frontend. The
    match key is IDENTITY (uri/iri) — strict; a renamed/re-URI'd node is a
    DIFFERENT node and must read as gone, never fuzzy-matched to a
    successor (that would conceal a divergence)."""
    class_uris: list[str] = Field(default_factory=list)
    verb_iris: list[str] = Field(default_factory=list)
    # The resolved subject — the anchor for the FULL subClassOf ancestor
    # walk. The captured decision (from _project_graph_trace) caps the
    # ancestor chain at ONE node + a "+N hops" count; for the summary
    # panels that's fine, but the MAP is a spatial render of the STRUCTURE,
    # where the intermediate hops ARE the structure. So the map's base-
    # layer read walks the real chain from here rather than inheriting the
    # projection's cap. Empty → no ancestor walk (falls back to 1-hop).
    subject_uri: str = ""


class DecisionSubgraphResponse(BaseModel):
    available: bool                       # False = couldn't-check (live read failed)
    reason: str = ""                      # why unavailable (couldn't-check detail)
    live_nodes: list[dict] = Field(default_factory=list)   # {uri, labels} existing NOW
    live_edges: list[dict] = Field(default_factory=list)   # {source, target, type}
    context_nodes: list[dict] = Field(default_factory=list)  # 1-hop, not in captured set
    # The FULL subClassOf ancestor chain from the subject up, ordered
    # (subject first). The map draws this as the vertical structural spine
    # — every intermediate class a REAL node, not a "+N hops" badge. Empty
    # when no subject_uri was given or the subject has no ancestors.
    ancestor_chain: list[str] = Field(default_factory=list)


def _parse_decision_subgraph(
    records: list[dict], captured_uris: set[str]
) -> dict:
    """PURE: fold flat (node, relationship, neighbor) rows into the base-
    layer shape. One row per (captured node × its relationship); a node
    with no relationships still appears (OPTIONAL MATCH → null rel).

    Returns {live_nodes, live_edges, context_nodes}. Bounded to 1 hop:
    context_nodes are the immediate neighbors NOT in the captured set
    (drawn dim). Edges are de-duped by (source, target, type). The diff
    (matched/diverged) is the frontend's job — this only reports what the
    live graph actually holds, faithfully.
    """
    live_uris: dict[str, list[str]] = {}
    edges: dict[tuple[str, str, str], None] = {}
    context: dict[str, None] = {}

    for row in records:
        uri = row.get("uri")
        if not uri:
            continue
        live_uris.setdefault(uri, row.get("labels") or [])

        rel_type = row.get("rel_type")
        neighbor = row.get("neighbor_uri")
        if not rel_type or not neighbor:
            continue
        # Orient the edge by direction so the drawn arrow matches the graph.
        if row.get("outgoing"):
            src, tgt = uri, neighbor
        else:
            src, tgt = neighbor, uri
        edges[(src, tgt, rel_type)] = None
        # A neighbor outside the captured set is 1-hop context (dim).
        if neighbor not in captured_uris:
            context[neighbor] = None

    return {
        "live_nodes": [{"uri": u, "labels": lbls} for u, lbls in live_uris.items()],
        "live_edges": [
            {"source": s, "target": t, "type": ty} for (s, t, ty) in edges
        ],
        "context_nodes": [{"uri": u} for u in context],
    }


def _parse_ancestor_chain(path_rows: list[dict]) -> dict:
    """PURE: fold subClassOf-path rows into the ordered ancestor spine +
    its nodes/edges. Each row is one path from the subject:
    {nodes: [{uri, labels}, ...], edges: [{source, target}, ...]}, ordered
    subject→…→ancestor. Multiple rows = a branching hierarchy.

    Returns {chain_nodes, chain_edges, ordered_chain}. `ordered_chain` is
    the LONGEST path's uris in order (subject first) — the spine the map
    draws vertically. nodes/edges are the union across all paths (a class
    with two parents contributes both edges). This is what makes the
    intermediate hops REAL nodes instead of a "+N hops" badge."""
    nodes: dict[str, list[str]] = {}
    edges: dict[tuple[str, str], None] = {}
    ordered: list[str] = []

    for row in path_rows:
        row_nodes = row.get("nodes") or []
        for n in row_nodes:
            uri = n.get("uri")
            if uri:
                nodes.setdefault(uri, n.get("labels") or [])
        for e in (row.get("edges") or []):
            s, t = e.get("source"), e.get("target")
            if s and t:
                edges[(s, t)] = None
        # Track the longest path as the canonical ordered spine.
        row_uris = [n.get("uri") for n in row_nodes if n.get("uri")]
        if len(row_uris) > len(ordered):
            ordered = row_uris

    return {
        "chain_nodes": [{"uri": u, "labels": lbls} for u, lbls in nodes.items()],
        "chain_edges": [
            {"source": s, "target": t, "type": "subClassOf"} for (s, t) in edges
        ],
        "ordered_chain": ordered,
    }


@app.post("/decision_subgraph", response_model=DecisionSubgraphResponse)
async def decision_subgraph(
    req: DecisionSubgraphRequest,
    current_user: User = Depends(get_current_user),
) -> DecisionSubgraphResponse:
    """Base layer for the decision-path map: a BOUNDED live Neo4j read of
    the decision's neighborhood. See the section header for the honesty
    contract (three states; couldn't-check must not degrade to captured-
    as-current)."""
    captured = {u for u in req.class_uris if u}
    if not captured:
        # Nothing to diff against — honestly empty, but the read DID
        # succeed (available=true; there's just no neighborhood).
        return DecisionSubgraphResponse(available=True)

    # Bounded: only the captured class nodes and their 1-hop OntologyClass
    # neighbors (subClassOf + verb edges). No unbounded expansion.
    cypher = """
    MATCH (n:OntologyClass)
    WHERE n.uri IN $uris
    OPTIONAL MATCH (n)-[r]-(m:OntologyClass)
    RETURN n.uri AS uri,
           labels(n) AS labels,
           type(r) AS rel_type,
           m.uri AS neighbor_uri,
           (startNode(r).uri = n.uri) AS outgoing
    """
    # The FULL subClassOf ancestor walk from the subject (variable-length,
    # bounded *0..8). This is the fix for the projection's one-ancestor
    # cap: the map needs every intermediate class as a real node, because
    # for a spatial render of the structure the intermediate hops ARE the
    # structure. `subClassOf` is the substrate's relationship type (same as
    # the compat-walk's [:subClassOf*0..N]).
    chain_cypher = """
    MATCH p = (s:OntologyClass {uri: $subject})-[:subClassOf*0..8]->(a:OntologyClass)
    RETURN [n IN nodes(p) | {uri: n.uri, labels: labels(n)}] AS nodes,
           [r IN relationships(p) | {source: startNode(r).uri, target: endNode(r).uri}] AS edges
    """
    try:
        with neo4j_driver.session() as session:
            result = session.run(cypher, uris=list(captured))
            records = [
                {
                    "uri": rec.get("uri"),
                    "labels": rec.get("labels"),
                    "rel_type": rec.get("rel_type"),
                    "neighbor_uri": rec.get("neighbor_uri"),
                    "outgoing": rec.get("outgoing"),
                }
                for rec in result
            ]
            chain_rows: list[dict] = []
            if req.subject_uri:
                chain_result = session.run(chain_cypher, subject=req.subject_uri)
                chain_rows = [
                    {"nodes": rec.get("nodes"), "edges": rec.get("edges")}
                    for rec in chain_result
                ]
        parsed = _parse_decision_subgraph(records, captured)
        chain = _parse_ancestor_chain(chain_rows)

        # Merge the ancestor spine into the live layer — the intermediate
        # ancestors become REAL live nodes/edges (not a badge). De-dupe
        # against the 1-hop nodes/edges already present.
        seen_nodes = {n["uri"] for n in parsed["live_nodes"]}
        for n in chain["chain_nodes"]:
            if n["uri"] not in seen_nodes:
                parsed["live_nodes"].append(n)
                seen_nodes.add(n["uri"])
        seen_edges = {(e["source"], e["target"], e["type"]) for e in parsed["live_edges"]}
        for e in chain["chain_edges"]:
            key = (e["source"], e["target"], e["type"])
            if key not in seen_edges:
                parsed["live_edges"].append(e)
                seen_edges.add(key)

        return DecisionSubgraphResponse(
            available=True,
            ancestor_chain=chain["ordered_chain"],
            **parsed,
        )
    except Exception as exc:  # noqa: BLE001
        # COULDN'T-CHECK. Do NOT fabricate a base layer. Report the live
        # read failed so the frontend labels the map "captured-only,
        # cannot verify what changed" rather than presenting historical
        # structure as current.
        logger.error("decision_subgraph live read failed: %s", exc)
        return DecisionSubgraphResponse(
            available=False,
            reason=f"live graph read failed: {exc}",
        )


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


# ── RETIRED (ADR-0029, Slice 2) ────────────────────────────────────────────
# The BPMN interrogator's catalog write/read path is superseded by git-asserted
# SPO WorkflowDefinition files (policy/workflows/*.yaml — authored via the SPO
# interview, committed by a human; there is no endpoint write, Ruling C). These two
# routes were ALSO unauthenticated (an anonymous workflow-definition write + an
# anonymous enumerate — endpoint-gating audit HIGH findings on a public host), so they
# are CLOSED NOW as a standalone security fix (a security fix and the refactor are
# different commits on different clocks). They are DELETED later, coupled to the
# Slice-2 replacement being sealed — together with BpmnSaveRequest/BpmnSaveResponse/
# BpmnCatalogItem, _generate_boot_sequence, and the BpmnCatalog auto-compile path.
# Kept PRESENT (not commented out) so they return a self-documenting 410 and remain a
# declared `retired` row in the endpoint-gating manifest until that cleanup removes them.
# NOTE: the unauthenticated workflow-APPROVE path (BPMNWorkflowRunner/approve) is a
# SEPARATE finding on the KEPT runner — it is NOT addressed here and must not be
# assumed-closed by this retirement.
_BPMN_RETIRED_DETAIL = (
    "This endpoint is retired (ADR-0029). BPMN workflow definitions are superseded by "
    "git-asserted SPO WorkflowDefinition files (policy/workflows/*.yaml), authored via "
    "the SPO interview and committed by a human. It was also unauthenticated; closed as a "
    "security fix. Deletion is tracked in the Slice-2 cleanup."
)


@app.post("/bpmn/save")
async def bpmn_save_retired():
    raise HTTPException(status_code=410, detail=_BPMN_RETIRED_DETAIL)


@app.get("/bpmn/catalog")
async def bpmn_catalog_retired():
    raise HTTPException(status_code=410, detail=_BPMN_RETIRED_DETAIL)


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


# HITL: the human_task_projection viewability column is recipient_id — the caller's
# AUTHZ IDENTITY (authz_id = the USER_ENTITLEMENT_CLAIM key: email in sandbox,
# employee-ID at work-deploy), a server-verified JWT-derived claim — NOT the UUID
# sub, NOT necessarily an email. Validate against a CONSERVATIVE identity allowlist
# (alphanumerics + the chars real emails/employee-IDs use) that REJECTS every SQL-
# breaking character (quotes, whitespace, semicolons, backslash), then PostgreSQL-
# escape as a backstop. Validate-then-escape, two layers — same trusted-middle
# discipline as the sub filter (a server-verified value, never a client param).
# The allowlist is the strong layer: a filter-breaking value is rejected before it
# reaches the query; the quote-doubling is belt-and-suspenders.
_IDENTITY_RE = _re_for_uuid.compile(r"^[A-Za-z0-9._%+@-]{1,254}$")


def _escape_identity_literal(s: str) -> str:
    if not _IDENTITY_RE.match(s):
        raise ValueError(f"verified authz identity has illegal characters: {s!r}")
    return s.replace("'", "''")


_ELECTRIC_FORWARD_HEADERS = {
    "electric-handle",
    "electric-offset",
    "electric-up-to-date",
    "electric-schema",
    "electric-cursor",
    "content-type",
    # NB: Electric's own `cache-control` is DELIBERATELY NOT forwarded. Electric
    # marks shape responses publicly cacheable (built for CDN caching), but behind
    # this per-user proxy the client URL is IDENTICAL across users (the
    # discriminating WHERE is injected server-side from the JWT), so a public/
    # shared cache would serve one user's shape response to another in the same
    # browser — the cross-user "flash" of a prior user's answers/tasks. We force
    # `no-store` on the response below instead.
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

    # 2. Pass through Electric params, EXCEPT any client-supplied `where`
    #    (always overridden by the server-injected clause). Read the requested
    #    table first — the WHERE column is per-table.
    upstream_params: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key.lower() == "where":
            # Client cannot influence the WHERE clause. Silently drop.
            continue
        upstream_params[key] = value
    table = upstream_params.get("table") or "answer_artifact_projection"
    upstream_params["table"] = table

    # 3. Build the server-verified WHERE clause, per table. Electric's WHERE
    #    parser supports a subset of PostgreSQL and does NOT accept the `->>`
    #    JSONB operator, so each filter references a plain column populated at
    #    write time.
    #      - human_task_projection: recipient_id = <verified caller AUTHZ_ID>.
    #        The HITL queue is keyed on the authz identity (Topaz's key) end-to-end,
    #        so the replication filter and the Topaz can_act gate derive from ONE
    #        truth and there is no sub<->email bridge to mis-route. authz_id == email
    #        in sandbox; at work-deploy it becomes the employee-ID claim, and this
    #        filter re-keys with the knob (no code change here).
    #      - answer_artifact_projection (default): produced_for_user_id = <sub>
    #        (interim per-user ownership isolation, NOT Topaz authz — unchanged).
    # NOTE the `else` catches EVERY non-task table -> every table gets a
    # server-side WHERE; there is no branch that serves a table UNFILTERED.
    if table == "human_task_projection":
        escaped_id = _escape_identity_literal(current_user.authz_id)
        # Scope the inbox stream to PENDING rows only, so it agrees with the REST
        # snapshot (/me/human_tasks filters status='pending'). Without this the shape
        # streamed EVERY row for the recipient incl. resolved ones; a resolved task
        # could linger client-side as a stale 'pending' (the badge showing N, then
        # dropping to the real count when the inbox opened and replacePending ran the
        # REST reconcile). With status in the WHERE, resolving a task moves it OUT of
        # the shape -> Electric emits a delete -> it drops cleanly, no flicker. status
        # is a plain column (Electric's WHERE subset handles column = literal + AND).
        server_where = f"recipient_id = '{escaped_id}' AND status = 'pending'"
    else:
        escaped = _escape_sql_string_literal(verified_user_id)
        server_where = f"produced_for_user_id = '{escaped}'"
    upstream_params["where"] = server_where

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
    # These shape responses are PER-USER (identical URL, WHERE injected from the
    # caller's JWT) — they must NEVER be cached and served to another user in the
    # same browser (or by any shared/CDN cache). no-store prevents the cross-user
    # flash; vary:authorization documents that the content depends on the caller.
    # (App-level incremental sync uses electric-handle/offset, not HTTP caching,
    # so disabling the HTTP cache does not affect correctness of the stream.)
    forwarded["cache-control"] = "no-store"
    forwarded["vary"] = "Authorization"

    return StreamingResponse(
        iter([upstream_resp.content]),
        status_code=upstream_resp.status_code,
        headers=forwarded,
    )
