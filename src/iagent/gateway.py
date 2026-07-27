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
from typing import AsyncGenerator, Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from neo4j import GraphDatabase
from pydantic import BaseModel, Field
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
    logger.info("access_request created: task_id=%s subject=%s asset=%s approvers=%d",
                task_id, current_user.authz_id, req.asset, len(result.get("recipients", [])))
    return {"request_id": task_id, "status": "pending",
            "approvers": len(result.get("recipients", []))}


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
    domain: str = "SUSTAINMENT"          # selects the review audience pcn_disposition:<domain>
    audience: Optional[str] = None        # override; defaults to pcn_disposition:<domain>


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
    user. Honest outcomes pass through: STARTED / NO_RESIDUE / NO_ENTITLED_ACTION are
    200; a bad/unsourced request or corrupt ruleset is 422 (never a silent success)."""
    raw_token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    body = {
        "notice_id": req.notice_id,
        "doc_type": req.doc_type,
        "categories": req.categories,
        "impacted_parts": req.impacted_parts,     # extraction pass-through (tripwire source)
        "in_scope_mpns": req.in_scope_mpns,
        "doc_needs_review": req.doc_needs_review,
        "approver": current_user.authz_id,        # identity from the token — NOT client-supplied
        "audience": req.audience or f"pcn_disposition:{req.domain}",
        "user_jwt": raw_token,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            rr = await client.post(
                f"{_RESTATE_INGRESS_URL}/ReviewStarter/start_review", json=body,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "review_start_unreachable", "message": str(exc)})
    if rr.status_code != 200:
        raise HTTPException(status_code=502, detail={"error": "review_start_failed", "code": rr.status_code})
    out = rr.json()
    logger.info("pcn review start: notice=%s approver=%s status=%s",
                req.notice_id, current_user.authz_id, out.get("status"))
    if out.get("status") in _PCN_REVIEW_BAD_REQUEST:
        raise HTTPException(status_code=422, detail=out)
    return out


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
                f"{_RESTATE_INGRESS_URL}/GroupedReview/{workflow_id}/get_batch",
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
    }


# ── PCN notice PROVENANCE feeder (evidence card) ──────────────────────────────
# Read-side join at DISPLAY time (NOT batch payload): where a review value came
# from in the source document. Extraction stays the authority; the graph's lossy
# projection isn't widened. TEMPORARY FIXTURE — real doc-tools `review.json`
# (field_path/source_snippet/bboxes/page_dims/match_method/region/needs_review +
# page image + S3 crop) replaces `_PROV_FIXTURE` when a notice has a source PDF.
# The demo notices are synthetic (no PDF), so this serves shaped placeholder
# provenance so the evidence-card INTERACTION + not_found path are demonstrable;
# the box rendering itself is sealed by the overlay-drift unit test in cortex-ui.
_PAGE_DIMS = {"width": 1700, "height": 2200}  # 200 DPI US-letter
_PROV_FIXTURE = {
    "NSR01L30NXT5G": {"bboxes": [[170, 440, 1530, 640]], "region": "table",
                      "match_method": "unique", "match_confidence": 1.0, "needs_review": False},
    "NSR02F30NXT5G": {"bboxes": [[170, 640, 1530, 840]], "region": "table",
                      "match_method": "unique", "match_confidence": 1.0, "needs_review": False},
    # The unverified part — the extractor could not anchor it (this is why the
    # override ceremony fires): no box, needs_review, verify against the crop.
    "NSR05F20NXT5G": {"bboxes": [], "region": "table",
                      "match_method": "not_found", "match_confidence": 0.0, "needs_review": True},
}


# notice_id -> the doc-tools output prefix in MinIO. INTERIM index (the outputs
# key off the upload path, not the notice id; they coincide only when the PDF was
# uploaded under a path carrying the id). Follow-up: store the S3 pointer on the
# SustainmentNotice Neo4j node so this map isn't hand-maintained.
_ARTIFACT_BUCKET = "processing-artifacts"
_NOTICE_ARTIFACT_PREFIX = {
    "IPCN25300X": "sustainment/inbound/onsemi_ipcn/generated/onsemi_Generic_IPCN25300X_pdf",
    "ADI_PDN_23_0120": "sustainment/inbound/adi_23_0120/generated/ADI_PDN_23_0120_pdf",
}


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
    """Serve a notice's extraction provenance for the evidence card. Reads the
    REAL doc-tools review.json + table crops from MinIO for a mapped notice;
    falls back to the shaped fixture for synthetic notices with no source PDF."""
    from starlette.concurrency import run_in_threadpool
    prefix = _NOTICE_ARTIFACT_PREFIX.get(notice_id)
    if prefix:
        try:
            items = await run_in_threadpool(lambda: _read_notice_provenance_from_store(prefix))
            return {"notice_id": notice_id, "page_image_url": None, "items": items, "source": "doc-tools"}
        except Exception as exc:  # noqa: BLE001 — fall back to fixture on any store error
            logger.warning("notice provenance read failed for %s: %s", notice_id, exc)

    items = []
    for mpn, p in _PROV_FIXTURE.items():
        items.append({
            "field_path": f"parts[].affected_mpn ({mpn})",
            "mpn": mpn,
            "value": mpn,
            "source_snippet": "" if p["match_method"] == "not_found" else mpn,
            "page_number": 1,
            "bboxes": p["bboxes"],
            "page_dims": _PAGE_DIMS,
            "region": p["region"],
            "match_method": p["match_method"],
            "match_confidence": p["match_confidence"],
            "needs_review": p["needs_review"],
            "review_reason": "MPN not located in document" if p["needs_review"] else None,
            "crop_url": None,
            "page_image_url": None,
        })
    return {"notice_id": notice_id, "page_image_url": None, "items": items, "fixture": True}


# ── PCN parts-by-state dashboard FEEDER ───────────────────────────────────────
# The ONE pcn-aware presentation surface (grep-able; the M2 deletion test covers it). It hand-assembles
# an INSTANCES_BY_PROPERTY archetype payload (docs/plans/pcn-dashboard-payload-schema.md) from engine-o's
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


# ── ADR-0028 canvas persistence ──────────────────────────────────────────────
class CanvasesBody(_BaseModel):
    """The user's full custom-canvas set (CustomCanvas[]), stored verbatim as
    jsonb. The GLOBAL canvas is derived and never sent."""
    canvases: list = []


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
    if req.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail={"error": "bad_decision"})
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
        # Not in the caller's queue at all — deny-by-default, existence-oracle
        # safe: don't reveal whether the task exists for someone else.
        raise HTTPException(status_code=404, detail={"error": "task_not_found"})
    audience = match["audience"]
    allowed = await run_in_threadpool(lambda: human_tasks.check_can_act(audience, current_user.authz_id))
    if not allowed:
        raise HTTPException(status_code=403, detail={"error": "not_authorized_to_act", "audience": audience})

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
        decision = {"overrides": req.overrides or {}}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                rr = await client.post(
                    f"{_RESTATE_INGRESS_URL}/GroupedReview/{wf}/submit_decision",
                    json={"decision": decision},
                )
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": "review_submit_unreachable", "message": str(exc)})
        if rr.status_code != 200:
            raise HTTPException(status_code=502, detail={"error": "review_submit_failed", "code": rr.status_code})
        sub = rr.json()
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
                    f"{_RESTATE_INGRESS_URL}/BPMNWorkflowRunner/{match['workflow_id']}/approve",
                    json={"task_id": task_id, "status": status, "comments": req.comment},
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


# Engine-name resolution for the routing HUD "Handled by" label lives in a
# dep-free sibling (engine_names.py) so it unit-tests without importing gateway
# (whose import connects to Postgres). Release-agnostic: anchored on the chart
# component name, not a release-prefixed / bare-vs-FQDN service name. Kept under
# the original underscore aliases so the call sites below are unchanged.
from .engine_names import (  # noqa: E402
    engine_name_from_endpoint as _engine_name_from_endpoint,
    engine_name_from_provider as _engine_name_from_provider,
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
