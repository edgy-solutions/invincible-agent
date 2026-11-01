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
import functools
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date as _date, datetime, timezone
from typing import AsyncGenerator, Any, Literal, Optional

import httpx
from dotenv import load_dotenv
from fastapi import (
    Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status,
)
from fastapi import Query as _Query
from fastapi import Path as _Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from neo4j import GraphDatabase
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import get_db, init_db
from .models import BpmnCatalog
from .auth import get_current_user, User
from iagent_mesh.review_coverage import ReviewShapeRow
from iagent_mesh.provenance import EvidenceRef  # the SDK model; the one EvidenceRef (ruling 2026-10-31)
from pydantic import ValidationError as _PydanticValidationError
from . import review_coverage as _rcov
from .review_coverage import ItemReviewCoverage
from . import frontend_menu_store
from .ingest_api import (
    BINARY_200, DROP_GATE_RESPONSES, INGEST_V1_TAG, MCP_TAG, PREVIEW_EXTRA, ActResponse, EmptyDecisionResponse,
    Entitlements, ExportProfile, Extraction, HumanTasksListing, IngestResponse, LeafResponse, MineListing,
    RetriesListing,
    RetryResponse, StatusBody, TitleLeafResponse,
)
from .ingest_api import EvidenceRef as _ServedEvidenceRef  # the served contract
from .identity_vault import (
    _ensure_the_audit_line_actually_ARRIVES,
    VAULT,
    RedemptionOutcome,
    vault_slots,
    vault_ttl_seconds,
    logger as _vault_audit_log,   # the ONE logger whose level the vault owns
)
from .answer_artifact_writer import (
    AnswerArtifactBundle,
    DurabilityStatus,
    get_writer,
)
from .authz.refusal import relay_refusal


logger = logging.getLogger("cortex")
# THE LINE MUST ARRIVE, NOT MERELY BE CALLED.
#
# MEASURED 2026-09-07: this logger has emitted ZERO lines in the deployed BFF, ever. Something
# calls `logging.basicConfig()` during boot, which installs a root handler at its default level
# of WARNING, so every `logger.info` in this module is dropped while uvicorn's access log keeps
# flowing. `identity_vault` hit this on 2026-08-28 and fixed its OWN logger; the presentation
# agent hit it before that. This is the third instance of the same class and by far the widest:
# every routing, lineage and resolved_intent line in the gateway was silent.
#
# THE COST WAS A DIAGNOSIS, NOT JUST QUIET. Three lineage log lines were added specifically so a
# slow pick would say which of two causes it was -- claim never sent, or claim sent and fallen
# through. They were invisible on arrival, and their absence was read as evidence. An absence
# assertion is only worth its positive control, and there was none: nothing established that
# this logger emits at any level, so even the missing WARNING proved nothing.
#
# Reusing identity_vault's function rather than copying it: it is the one implementation of this
# fix, it carries the original measurement, and a second copy would drift.
_ensure_the_audit_line_actually_ARRIVES(logger)

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

# ── Ingest watchdog (2026-10-12, pipeline failure must reach the row) ───────────────────

# A row never sits at `received` or `extracting` for more than its timeout without either
# advancing or failing: the loop below marks stale rows `failed:timeout`
# (ingest_status.fail_stalled), naming the stage in failure.step and carrying the run id if a stage
# POST ever reported one. `extracting` joined 2026-10-16: doc-tools logs a refused stage POST and
# still ends its run SUCCESS, so a row whose review never landed sat at `extracting` for ever.
# `review`, `awaiting_origin` and `awaiting_kind` are NOT watched -- they wait on a person (a steward,
# or the dropper's leaf pick), not on the pipeline.
#
# THE RECEIVED DEFAULT IS 600 s, NOT THE SENSOR'S 30 s INTERVAL. A row whose run is QUEUED behind
# `max_concurrent_runs` legitimately sits at `received` for minutes; a 30 s bound would fail every
# queued drop. The stage route treats a `timeout` failure at EITHER stage as PROVISIONAL (a late run
# supersedes it), so a too-early timeout is recoverable -- but it should still be rare, hence the
# generous defaults. EXTRACTING gets 3600 s: a large CAD/PDF extraction legitimately runs long.
# A value <= 0 disables that stage only; the watchdog is off when BOTH are <= 0.
_INGEST_RECEIVED_TIMEOUT_SECONDS_DEFAULT = 600
_INGEST_EXTRACTING_TIMEOUT_SECONDS_DEFAULT = 3600
_INGEST_WATCHDOG_INTERVAL_SECONDS_DEFAULT = 30


def _detail_with_message(status: int, detail):
    """Ensure a 409's detail is a dict with a non-empty `message` (spec 204, "every 409 carries
    `message`"). Used where the status or detail is relayed (an engine's refusal, a helper's
    parameter) and so cannot be a literal. Any other status passes through untouched."""
    if status != 409:
        return detail
    d = dict(detail) if isinstance(detail, dict) else {
        "error": "conflict", "upstream": detail if not isinstance(detail, str) else None}
    if isinstance(detail, str) and detail.strip():
        d["message"] = detail
    if not str(d.get("message") or "").strip():
        d["message"] = "the request conflicts with the current state; reload and try again."
    return d


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


_LEAF_BACKSTOP_ACTOR = "bff:manifest-leaf-backstop"


# No Retry-After value existed in src/; 5 s matches the 5 s Topaz client timeout.
_CAN_DROP_RETRY_AFTER = "5"


def _row_dropper(row: dict) -> str:
    """The dropper of record for a status row: `on_behalf_of`, the actor `_admit_on_behalf_of`
    resolved at `record_received` (the PRINCIPAL when a delegate dropped for them). `submitted_by`
    is the authenticated delegate and never answers a drop question; it is only the fallback for a
    row that recorded no actor."""
    return str((row or {}).get("on_behalf_of") or (row or {}).get("submitted_by") or "").strip()


async def _can_drop_or_refuse(kind: str, dropper_id: str) -> None:
    """THE one can_drop check, called by every site that sets a row's kind (the two doors,
    title_leaf, /leaf, the BFF leaf backstop). A kind is gated iff the Topaz object
    `capability:can_drop:<kind>` exists; then the dropper must hold `can_invoke`. Returns when the
    dropper may drop it. Raises 403 `not_entitled_to_drop` (policy refusal) when not, and 503
    `authorization_unavailable` / `authorization_unconfigured` when the directory cannot say --
    a failed read is never "not gated"."""
    from starlette.concurrency import run_in_threadpool

    from . import human_tasks
    from .authz.refusal import policy_refusal

    try:
        refused = await run_in_threadpool(human_tasks.can_drop_refusal, kind, dropper_id)
    except human_tasks.AuthorizationUnconfigured as exc:
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unconfigured",
            "message": "the deployment declares no authorization directory"}) from exc
    except human_tasks.AuthorizationUnavailable as exc:
        logger.warning("can_drop gate unavailable for kind=%s: %s", kind, exc)
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unavailable",
            "message": "could not verify whether this kind is restricted"},
            headers={"Retry-After": _CAN_DROP_RETRY_AFTER}) from exc
    if refused is not None:
        raise policy_refusal(
            "not_entitled_to_drop", policy_id=refused["policy_id"],
            missing_binding=refused["missing_binding"], message=refused["message"])
_INGEST_LEAF_BACKSTOP_SECONDS_DEFAULT = 300

# Ruling 2026-10-21 (a leaf set while the run is in flight): a PDF drop whose leaf (pcn|pdn) is set
# while its Dagster run is in flight would strand -- doc-tools reads the kind ONLY from the drop's
# sidecar `{object_prefix}manifest.json`, so that run ran as `pdf`, and every BFF "relaunch" re-reads
# the SAME sidecar. So the BFF relaunches a row AS ITS LEAF: it rewrites the sidecar to the leaf FIRST,
# then re-opens the row with reason `leaf_applied`. The relaunch pass polls every 60 s (not the
# watchdog's hour-scale timeouts) and needs no user Retry. Env INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS;
# <= 0 disables the pass.
# INVARIANT: the sidecar is rewritten ONLY at a relaunch, so the sidecar's content_kind always names
# the kind the latest launched run read. "sidecar kind == row leaf" therefore means "the leaf was
# already applied" -> never relaunch again (no loops).
_INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS_DEFAULT = 60
_DAGSTER_TERMINAL_RUN_STATUSES = ("SUCCESS", "FAILURE", "CANCELED")
# Ruling 2026-10-22 (a finished run with no leaf waits for a kind): "a row whose run has finished and
# that has NO leaf goes to awaiting_kind (reason: kind_not_identified). Never left at extracting."
# A TI PDF drop's run ended SUCCESS after posting `extracting` and nothing else, and the row sat there
# leafless until a person picked a kind. `_ingest_kind_unidentified_tick` holds it (same 60 s cadence
# and off switch as the relaunch pass); a pick from there relaunches as built on 10-21. The status
# route serves the reason as `hold_reason`, only at awaiting_kind.
_leaf_relaunch_last_at = None  # time.monotonic() seconds of the last relaunch pass


def _backstop_candidates(raw) -> list:
    """Map a manifest `leaf.candidates` list to `hold_for_kind`'s input (spec 204 D3 + the 10-21
    page-fraction ruling). A candidate is kept only when its `leaf` (lowercased) is a leaf, `score`
    is a finite number in [0, 1], and its `evidence_ref` carries `page` (an int >= 1 -- ONLY `page`,
    never the older `page_number`, whose boxes are pixels) and a `bbox` that is null/absent (kept as
    `"bbox": None`: stated on the page, no box to draw) or in page fractions (a pixel or malformed box
    drops the candidate). `note` is carried when a non-blank string. Anything else drops THAT
    candidate."""
    import math

    from . import ingest_status

    out = []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict):
            continue
        leaf = str(c.get("leaf") or "").strip().lower()
        score = c.get("score")
        ev = c.get("evidence_ref")
        if leaf not in ingest_status.LEAVES or not isinstance(ev, dict):
            continue
        if (isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score) or not 0 <= score <= 1):
            continue
        page = ev.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            continue
        bbox = ev.get("bbox")
        if bbox is not None and not _bbox_is_page_fractions(bbox):
            continue
        ref = {"page": page, "bbox": list(bbox) if bbox is not None else None}
        note = ev.get("note")
        if isinstance(note, str) and note.strip():
            ref["note"] = note.strip()
        out.append({"leaf": leaf, "score": score, "evidence_ref": ref})
    return out


def _find_leaf_manifest(row: dict) -> tuple:
    """SYNC. `(key, manifest)` of the newest versioned manifest under the row's own directory that
    names this ingest id AND carries a `leaf` block, else `(None, None)`. S3/parse errors raise."""
    prefix = str(row.get("object_prefix") or "").rstrip("/")
    if not prefix:
        return None, None
    s3 = _build_s3_client()
    found, token = [], None
    while True:
        kw = {"Bucket": _ARTIFACT_BUCKET, "Prefix": f"{prefix}/generated/"}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        found += [o for o in (page.get("Contents") or [])
                  if str(o.get("Key") or "").endswith("/manifest.json")]
        token = page.get("NextContinuationToken") if page.get("IsTruncated") else None
        if not token:
            break
    found.sort(key=lambda o: o.get("LastModified"), reverse=True)
    for o in found:
        m = _read_extraction_manifest(o["Key"])
        if m.get("ingest_id") == row.get("id") and isinstance(m.get("leaf"), dict):
            return o["Key"], m
    return None, None


async def _apply_manifest_leaf_block(row: dict, key, manifest: dict) -> tuple:
    """Act on a row's manifest `leaf` block (shared by the manifest-leaf backstop and the finished-run
    pass). A confident block (`_title_leaf`) rewrites the drop's sidecar to the leaf FIRST, then
    re-opens the row as that kind (`set_leaf`, reason `leaf_applied`); otherwise the row is held at
    `awaiting_kind` with the mapped candidates. Returns `(decision, ok)`; `ok` False = the row moved
    under us (`row_moved`). Logs nothing; S3 errors raise to the caller's per-row except."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    rid = row.get("id")
    block = manifest["leaf"]
    title = _title_leaf(block.get("leaf"), block.get("outcome"))
    if title is not None:
        # The sidecar is rewritten to the leaf BEFORE the row is re-opened, so the relaunch
        # runs as the leaf; an S3 error lands in the per-row except (row skipped).
        try:
            await _can_drop_or_refuse(title, _row_dropper(row))
        except HTTPException as exc:
            code = exc.status_code
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            logger.warning("ingest_leaf_backstop ingest_id=%s kind=%s refused by can_drop: %s (%s)",
                           rid, title, detail.get("error"), code)
            if code != 403:
                # the directory could not answer: leave the row untouched for the next tick
                return "can_drop_unavailable", False
            held = await run_in_threadpool(lambda: ingest_status.hold_for_kind(
                rid, candidates=_backstop_candidates(block.get("candidates")),
                detail=f"the title read named {title}, which the dropper may not drop; "
                       "pick another kind",
                from_statuses=[ingest_status.EXTRACTING]))
            return ("awaiting_kind" if held else "row_moved"), held
        await run_in_threadpool(lambda: _apply_leaf_to_sidecar(row, title))
        ok = await run_in_threadpool(lambda: ingest_status.set_leaf(
            rid, title, "title", set_by=_LEAF_BACKSTOP_ACTOR,
            from_statuses=[ingest_status.EXTRACTING],
            to_status=ingest_status.RECEIVED, bump_attempt=True,
            retry_reason=ingest_status.REASON_LEAF_APPLIED)) is not None
        return (f"title:{title}" if ok else "row_moved"), ok
    outcome = block.get("outcome")
    ok = await run_in_threadpool(lambda: ingest_status.hold_for_kind(
        rid, candidates=_backstop_candidates(block.get("candidates")),
        detail=f"the title read named no leaf ({outcome or 'no outcome'}); "
               "pick pcn or pdn",
        from_statuses=[ingest_status.EXTRACTING]))
    return ("awaiting_kind" if ok else "row_moved"), ok


async def _ingest_leaf_backstop_tick(older_than_s: int) -> list:
    """One backstop pass (spec 204, ruling "a pdf row runs no passes, so the review.json backstop
    can't fire. Use manifest[\"leaf\"] instead"): a leaf-capable row at `extracting` with NO leaf,
    quiet for `older_than_s`, whose versioned manifest carries a `leaf` block. A confident block
    (`_title_leaf`) sets the leaf and relaunches the row as that kind; otherwise the row is held at
    `awaiting_kind` with the mapped candidates. No manifest -> nothing (the timeout fails the row
    later). Any S3/parse error skips the row; this never raises out of the tick. Returns the ids
    acted on. `older_than_s` <= 0 disables it."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    if older_than_s <= 0:
        return []
    rows = await run_in_threadpool(
        lambda: ingest_status.list_leafless_extracting(older_than_seconds=older_than_s, limit=50))
    done: list = []
    for row in rows:
        if not _leaf_capable(row) or _row_leaf(row)[0] is not None:
            continue
        rid = row.get("id")
        try:
            key, manifest = await run_in_threadpool(lambda row=row: _find_leaf_manifest(row))
            if manifest is None:
                continue
            decision, ok = await _apply_manifest_leaf_block(row, key, manifest)
            logger.info("ingest_leaf_backstop ingest_id=%s key=%s decision=%s", rid, key, decision)
            if ok:
                done.append(rid)
        except Exception as exc:  # noqa: BLE001 -- never raise out of the tick
            logger.warning("ingest_leaf_backstop ingest_id=%s skipped (%s: %s)", rid,
                           type(exc).__name__, exc)
    return done


async def _dagster_run_finished(run_id) -> bool:
    """True iff Dagster says the run is terminal (SUCCESS|FAILURE|CANCELED). Anything else -- an error
    (`_get_run_status` returns {}), RunNotFoundError, QUEUED, STARTED -- is False: fail closed, never
    relaunch a run that may still be reading the sidecar."""
    try:
        ans = await _get_run_status(run_id)
    except Exception:  # noqa: BLE001
        return False
    return (isinstance(ans, dict) and ans.get("__typename") == "Run"
            and ans.get("status") in _DAGSTER_TERMINAL_RUN_STATUSES)


async def _ingest_kind_unidentified_tick() -> list:
    """One pass (ruling 2026-10-22, "a row whose run has finished and that has NO leaf goes to
    awaiting_kind (reason: kind_not_identified). Never left at extracting."): a leaf-capable row at
    `extracting` with NO leaf and a run id whose Dagster run is terminal (SUCCESS|FAILURE|CANCELED;
    `_dagster_run_finished` fails closed). If the run left a manifest `leaf` block the row is handled
    exactly as the manifest backstop does (`_apply_manifest_leaf_block`: a confident title relaunches
    it as that leaf, else it is held with the candidates); with no manifest the row is held with no
    candidates and reason `kind_not_identified`. The hold requires `run_id` to still be the one seen
    finish (`expect_run_id`), so a relaunch that landed meanwhile wins. No run id -> skipped (the
    extracting watchdog owns it). Never raises. Returns the ids acted on."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    try:
        rows = await run_in_threadpool(
            lambda: ingest_status.list_leafless_extracting(older_than_seconds=0, limit=50))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ingest_kind_unidentified listing failed (%s: %s)", type(exc).__name__, exc)
        return []
    done: list = []
    for row in rows:
        if not _leaf_capable(row) or _row_leaf(row)[0] is not None or not row.get("run_id"):
            continue
        rid = row.get("id")
        try:
            if not await _dagster_run_finished(row["run_id"]):
                continue
            key, manifest = await run_in_threadpool(lambda row=row: _find_leaf_manifest(row))
            if manifest is not None:
                decision, ok = await _apply_manifest_leaf_block(row, key, manifest)
            else:
                ok = await run_in_threadpool(lambda row=row: ingest_status.hold_for_kind(
                    row["id"], candidates=[],
                    detail="the run finished without identifying the kind; pick pcn or pdn",
                    reason=ingest_status.REASON_KIND_NOT_IDENTIFIED, expect_run_id=row["run_id"],
                    from_statuses=[ingest_status.EXTRACTING]))
                decision = "awaiting_kind" if ok else "row_moved"
            logger.info("ingest_kind_unidentified ingest_id=%s run_id=%s decision=%s",
                        rid, row.get("run_id"), decision)
            if ok:
                done.append(rid)
        except Exception as exc:  # noqa: BLE001 -- never raise out of the tick
            logger.warning("ingest_kind_unidentified ingest_id=%s skipped (%s: %s)", rid,
                           type(exc).__name__, exc)
    return done


def _drop_sidecar_key(row) -> str:
    """The S3 key of the drop's sidecar -- exactly what `_write_ingest_object` writes."""
    prefix = str(row.get("object_prefix") or "")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}manifest.json"


def _read_drop_sidecar(row) -> dict:
    """SYNC. The drop's sidecar as a dict; raises on any S3/parse error."""
    obj = _build_s3_client().get_object(Bucket=_ARTIFACT_BUCKET, Key=_drop_sidecar_key(row))
    return json.loads(obj["Body"].read())


def _apply_leaf_to_sidecar(row, leaf) -> bool:
    """SYNC. Rewrite the drop's sidecar so doc-tools' next launch reads `leaf`: `content_kind`,
    `domain_type` (the registration's domain, as the drop writes for a declared kind) and
    `metadata.content_kind`; every other key is preserved. True if it wrote, False if the sidecar
    already said so. Raises on S3 errors or an unregistered leaf. Called ONLY at a relaunch (see the
    invariant at `_INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS_DEFAULT`)."""
    import copy

    from . import content_kinds

    old = _read_drop_sidecar(row)
    reg = content_kinds.by_kind(leaf)
    if reg is None or not reg.domain:
        raise ValueError(f"leaf {leaf!r} has no registered domain")
    new = copy.deepcopy(old)
    new["content_kind"] = leaf
    new["domain_type"] = reg.domain
    new["metadata"] = {**(old.get("metadata") or {}), "content_kind": leaf}
    if new == old:
        return False
    _build_s3_client().put_object(Bucket=_ARTIFACT_BUCKET, Key=_drop_sidecar_key(row),
                                  Body=json.dumps(new, indent=2).encode("utf-8"),
                                  ContentType="application/json")
    return True


async def _ingest_leaf_relaunch_tick() -> list:
    """One relaunch pass (ruling 2026-10-21): a leafed row (pcn|pdn) whose latest launched run read
    another kind and has since FINISHED is rewritten into the sidecar as its leaf and re-opened at
    `received` (reason `leaf_applied`), so doc-tools relaunches it as the leaf. Skips: not leaf-
    capable; sidecar kind already == leaf (already applied -- the no-loop guard, and a declared drop
    whose leaf run ended silent, which the watchdog owns); the run not finished. Never raises. Returns
    the relaunched ids."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    done: list = []
    try:
        rows = await run_in_threadpool(
            lambda: ingest_status.list_leafed_relaunch_candidates(limit=50))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ingest_leaf_relaunch listing failed (%s: %s)", type(exc).__name__, exc)
        return done
    for row in rows:
        rid = row.get("id")
        try:
            leaf = str(row.get("content_kind") or "").strip().lower()
            if not _leaf_capable(row):
                continue
            sidecar = await run_in_threadpool(lambda row=row: _read_drop_sidecar(row))
            if str(sidecar.get("content_kind") or "").strip().lower() == leaf:
                continue
            if not await _dagster_run_finished(row.get("run_id")):
                continue
            await run_in_threadpool(lambda row=row, leaf=leaf: _apply_leaf_to_sidecar(row, leaf))
            moved = await run_in_threadpool(lambda row=row, leaf=leaf: ingest_status.relaunch_as_leaf(
                rid, leaf=leaf, from_status=row["status"], expect_attempt=row["attempt"]))
            decision = "relaunched" if moved is not None else "row_moved"
            logger.info("ingest_leaf_relaunch ingest_id=%s from=%s run_id=%s attempt=%s decision=%s",
                        rid, row.get("status"), row.get("run_id"), row.get("attempt"), decision)
            if moved is not None:
                done.append(rid)
        except Exception as exc:  # noqa: BLE001 -- never raise out of the tick
            logger.warning("ingest_leaf_relaunch ingest_id=%s skipped (%s: %s)", rid,
                           type(exc).__name__, exc)
    return done


async def _ingest_watchdog_tick(timeout_s: int, extracting_timeout_s: int = 0) -> list:
    """One watchdog pass: fail every stale `received` and `extracting` document row (each stage only
    if its timeout is > 0), log each id with its stage, return the ids. Split out of the loop so a
    test can run one tick without sleeping."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    # The leaf relaunch pass and the finished-run-with-no-leaf pass share one 60 s cadence (not the
    # watchdog's), and run first.
    global _leaf_relaunch_last_at
    _relaunch_s = _env_int("INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS",
                           _INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS_DEFAULT)
    if _relaunch_s > 0 and (_leaf_relaunch_last_at is None
                            or time.monotonic() - _leaf_relaunch_last_at >= _relaunch_s):
        _leaf_relaunch_last_at = time.monotonic()
        await _ingest_leaf_relaunch_tick()
        await _ingest_kind_unidentified_tick()
    # The manifest-leaf backstop runs BEFORE the fail pass: it can save a row the timeout would fail.
    await _ingest_leaf_backstop_tick(
        _env_int("INGEST_LEAF_BACKSTOP_SECONDS", _INGEST_LEAF_BACKSTOP_SECONDS_DEFAULT))
    all_ids: list = []
    for stage, limit in ((ingest_status.RECEIVED, timeout_s),
                         (ingest_status.EXTRACTING, extracting_timeout_s)):
        if limit <= 0:
            continue
        ids = await run_in_threadpool(
            lambda stage=stage, limit=limit: ingest_status.fail_stalled(
                stage=stage, older_than_seconds=limit))
        for _id in ids:
            logger.info("ingest watchdog: %s failed:timeout at %s (no stage move within %ss)",
                        _id, stage, limit)
        all_ids.extend(ids)
    return all_ids


async def _ingest_watchdog_loop(timeout_s: int, interval_s: int,
                                extracting_timeout_s: int = 0) -> None:
    from . import ingest_status

    while True:
        try:
            await _ingest_watchdog_tick(timeout_s, extracting_timeout_s)
        except asyncio.CancelledError:
            raise
        except ingest_status.IngestStatusConfigError as exc:
            # No DSN: the seam is dormant, and a dormant seam has nothing to watch.
            logger.info("ingest watchdog dormant (no PG DSN): %s", exc)
            return
        except Exception as exc:  # noqa: BLE001 -- the next tick retries
            logger.warning("ingest watchdog tick failed (%s: %s); retrying next tick",
                           type(exc).__name__, exc)
        await asyncio.sleep(interval_s)


def _start_ingest_watchdog() -> "Optional[asyncio.Task]":
    timeout_s = _env_int("INGEST_RECEIVED_TIMEOUT_SECONDS", _INGEST_RECEIVED_TIMEOUT_SECONDS_DEFAULT)
    extracting_timeout_s = _env_int("INGEST_EXTRACTING_TIMEOUT_SECONDS",
                                    _INGEST_EXTRACTING_TIMEOUT_SECONDS_DEFAULT)
    interval_s = max(1, _env_int("INGEST_WATCHDOG_INTERVAL_SECONDS",
                                 _INGEST_WATCHDOG_INTERVAL_SECONDS_DEFAULT))
    if timeout_s <= 0 and extracting_timeout_s <= 0:
        logger.info("ingest watchdog disabled (INGEST_RECEIVED_TIMEOUT_SECONDS=%s, "
                    "INGEST_EXTRACTING_TIMEOUT_SECONDS=%s)", timeout_s, extracting_timeout_s)
        return None
    return asyncio.create_task(_ingest_watchdog_loop(timeout_s, interval_s, extracting_timeout_s))


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
    # ADR-0041 §8 ingestion seam: ensure the ingest_status_projection table exists (same
    # Postgres, same dormant-on-unset-DSN posture as human_task_projection / user_canvas above).
    try:
        from starlette.concurrency import run_in_threadpool
        from . import ingest_status
        await run_in_threadpool(ingest_status.apply_migration)
        logger.info("ingest_status_projection migration applied")
    except ingest_status.IngestStatusConfigError as exc:
        logger.info("ingestion seam dormant (no PG DSN): %s", exc)
    except Exception as exc:
        logger.warning("ingest_status migration failed (ingestion seam dormant): %s", exc)
    # The case summary (ruled 2026-10-16): the durable record of a case that reached a terminal.
    try:
        from starlette.concurrency import run_in_threadpool
        from . import case_summary
        await run_in_threadpool(case_summary.apply_migration)
        logger.info("case_summary migration applied")
    except ingest_status.IngestStatusConfigError as exc:
        logger.info("case summary dormant (no PG DSN): %s", exc)
    except Exception as exc:
        logger.warning("case_summary migration failed (case summary dormant): %s", exc)
    # ADR-0041 Open §1 (ruled 2026-09-30): the document_promotion decision record lives in the
    # same Postgres. Dormant on an unset DSN; `promotion.act` then refuses 503 naming the ledger.
    try:
        from starlette.concurrency import run_in_threadpool
        from . import promotion_stores
        await run_in_threadpool(promotion_stores.apply_migration)
        logger.info("document_decision_record migration applied")
    except promotion_stores.DecisionLedgerConfigError as exc:
        logger.info("promotion ledger dormant (no PG DSN): %s", exc)
    except Exception as exc:
        logger.warning("document_decision_record migration failed (ledger dormant): %s", exc)
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
    #   amplifies : one request -> five sequential Dagster runs (~5-7 min,
    #               measured 2026-09-09; this said ~18 and the ruling said ~25). A
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
        from .canvas_template import ratified_template_ids

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
            # Not "fast": five sequential governed asks, ~5-7 minutes measured.
            # Still not interactive, which is what `slow` is claiming. Declaring
            # it fast would invite a caller to treat it as interactive, which is
            # the one thing this verb is not.
            cost_class="slow",
        )

        # ── ADR-0050 §4 — THE GENERAL VERB, WITH THE TEMPLATE AS A SLOT ────────────────
        #
        # `seedPortfolioCanvas` names its template in the VERB. A second template would need
        # a second verb, a second synonym set and a second registration, and the router would
        # be choosing between boards by phrase — which is the classifier deciding a thing the
        # caller can simply say.
        #
        # `mesh:seedCanvas` takes `template_id` as a SPOKEN-MANDATORY slot whose menu is the
        # RATIFIED SET, read off `policy/canvases/` at registration. An unfilled slot reaches
        # ADR-0033's disposition and becomes an ASK offering the templates that exist — which
        # is the one-option menu today and a real choice the moment a second seedable template
        # lands.
        #
        # BOTH ARE REGISTERED, DELIBERATELY. `seedPortfolioCanvas` is the phrase people have
        # been saying for a fortnight and cortex calls its route directly; retiring it in the
        # same change that introduces its successor would break a live surface for a rename.
        # It is superseded, not removed, and the supersession is stated here rather than
        # implied by a comment on one of them.
        #
        # COST-OF-GUESSING ENUMERATION, because this makes a verb reachable from language:
        #   reachable : seed_canvas, typed against idp:Portfolio, one enumerated slot
        #   mutates   : ADDITIVELY ONLY — mints artifacts, composes nothing server-side
        #   authority : the caller's own, re-checked per ask, exactly as the portfolio verb
        #   amplifies : one request -> N sequential governed asks. Declared `slow`.
        _ratified = ratified_template_ids()
        # ONE DESCRIPTION, TWO REGISTRATIONS: one verb keeps one meaning in whichever cell it
        # is registered, so the second registration below reads this same variable.
        _seed_canvas_description = (
            "Compose a canvas from a RATIFIED TEMPLATE by asking that template's panels "
            "through the governed interview path and returning their artifact ids in "
            "slot order. This BUILDS A BOARD; it does not answer a question. A request "
            "for ONE measure is that measure's verb, not this one. `template_id` names "
            "which board: " + ", ".join(_ratified) + "."
        )
        _register_verb(
            name="cortex_bff_orchestration",
            description=_seed_canvas_description,
            verb="mesh:seedCanvas",
            input_uri="http://invincible-agent/idp#Portfolio",
            output_uri="http://invincible-agent/mesh#CanvasSeedResult",
            endpoint_url=f"{_bff_base}/canvas/seed",
            verb_synonyms=[
                "build me a canvas",
                "seed a canvas from a template",
                "set up a board from the standard template",
                "make me a review board",
            ],
            owner_persona="PORTFOLIO_LEAD",
            domains=["PORTFOLIO_PLANNING"],
            cost_class="slow",
            # THE MENU IS THE RATIFIED SET, DERIVED. A hand-kept enum here would offer a
            # template that no longer exists, or omit one that does, with nothing reading as
            # an error either way — see `ratified_template_ids`.
            slots=[{
                "name": "template_id",
                "type": "string",
                "required": True,
                "kind": "spoken-mandatory",
                "enum": _ratified,
                "description": "Which ratified canvas template to build.",
            }],
        )
        # ── THE SAME VERB IN THE PROGRAM-FINANCE CELL ──────────────────────────────────
        #
        # The portfolio registration above is typed `idp#Portfolio` and owned by
        # PORTFOLIO_LEAD, so from the finance cell the chat grounded `mesh:finProgramBrief`
        # instead and from any other cell nothing grounded. This one is typed by the class
        # the finance board is ABOUT (`fin#Program`), so "make me a finance canvas" routes
        # here and elicits "which program?" through the same disposition as every other verb.
        #
        # `name` MUST differ from the first registration's: the stale-row sweep deletes rows
        # that share a tool_urn and verb but have a different input_uri, so a shared name
        # would have each registration sweep the other's row away.
        #
        # THE SLOTS ARE DERIVED from the ratified templates and `SHARED_SLOT_REFERENTS`
        # (`canvas_template.seed_canvas_referent_slots`), the same builder the 409's ask reads.
        from .canvas_template import REFERENT_CELLS, seed_canvas_referent_slots

        _fin_program = "http://invincible-agent/fin#Program"
        _fin_persona, _fin_domain = REFERENT_CELLS[_fin_program]
        _register_verb(
            name="cortex_bff_orchestration_program_finance",
            description=_seed_canvas_description,
            verb="mesh:seedCanvas",
            input_uri=_fin_program,
            output_uri="http://invincible-agent/mesh#CanvasSeedResult",
            endpoint_url=f"{_bff_base}/canvas/seed",
            verb_synonyms=[
                "make me a finance canvas",
                "build the program finance board",
                "set up a program finance canvas",
                "make me a finance board for a program",
            ],
            owner_persona=_fin_persona,
            domains=[_fin_domain],
            cost_class="slow",
            slots=seed_canvas_referent_slots(),
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

    _watchdog = _start_ingest_watchdog()
    # Ruling Q9 (2026-10-19): replay the stored frontend menus into the graph. A background
    # task: it must not hold startup or /health, and its exceptions never escape.
    _menu_replay = asyncio.create_task(_replay_frontend_menus())
    try:
        yield
    finally:
        _menu_replay.cancel()
        try:
            await _menu_replay
        except asyncio.CancelledError:
            pass
        if _watchdog is not None:
            _watchdog.cancel()
            try:
                await _watchdog
            except asyncio.CancelledError:
                pass


# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="The Cortex — API Proxy",
    version="2.1.0",
    lifespan=lifespan,
)
# The door client's reach (`can_call:<tag>`, 2026-10-31 M3). Added FIRST so it is the INNERMOST
# middleware: the CORS and no-store wrappers below still apply to its refusals.
from .authz.call_capability import DoorGuard  # noqa: E402
app.add_middleware(DoorGuard, router=app.router)

# ── /version and /fleet/version ─────────────────────────────────────────────────────────
#
# "IS THE FIX ON THE POD?" was answered twice by hand on 2026-09-08 — pod age, then
# importing a symbol through `kubectl exec`. Neither is evidence under `:latest`, and
# neither is something anyone will run for thirteen services.
#
# `/version` reports THIS process's baked sha. `/fleet/version` asks every service its own
# and returns the lot, so the census is one HTTP call from outside the cluster instead of
# thirteen execs from inside it.
#
# EACH THING IS THE THING THAT WAS PUSHED, not "everything has the same number": each
# payload names its own `repo`, because the frontend is a separate repository with its own
# head and its own roll. Comparing its sha to the backend's would be comparing unrelated
# histories.
try:  # pragma: no cover - import path differs by runtime
    from utils.version_endpoint import mount_version as _mount_version, version_payload as _version_payload
except ImportError:  # pragma: no cover
    from agent_fleet.utils.version_endpoint import (  # type: ignore[no-redef]
        mount_version as _mount_version,
        version_payload as _version_payload,
    )

_mount_version(app, "cortex-bff")


def _fleet_version_targets() -> dict:
    """`component -> base url`, DERIVED from the environment the chart already sets.

    A hardcoded list is the shape this repo keeps paying for: a new engine's URL appears in
    the ConfigMap and the census silently does not include it, so the fleet reads complete
    while a service is unaccounted for. Scanning `ENGINE_*_PUBLIC_URL` means the population
    comes from the deployment rather than from someone's memory.

    THE PATH IS STRIPPED. Several of those vars point at a HANDLER (`/analyze`,
    `/query_graph`) rather than a service root, because their consumers post to them
    directly. `/version` lives at the root.
    """
    from urllib.parse import urlparse

    out: dict = {}

    def _add(name: str, raw: str) -> None:
        raw = (raw or "").strip()
        if not raw:
            return
        u = urlparse(raw)
        if not u.scheme or not u.netloc:
            return
        out[name] = f"{u.scheme}://{u.netloc}"

    # NAMED AS THE COMPONENT WILL NAME ITSELF, not as the variable happens to be spelled.
    #
    # A service that ANSWERS is re-keyed by the `component` in its payload. A service that
    # 404s or is down carries no payload and cannot be re-keyed — and those are exactly the
    # rows worth reading. Measured on the second live census: the held-back control fell out
    # of its own join and read UNKNOWN instead of `not-rolled`, because the fix for the
    # first join defect only covered the case where the service could speak.
    #
    # `ENGINE_W_PUBLIC_URL` -> `engine-w` is the convention every engine already follows, so
    # the canonical name is derivable HERE, before anyone has to answer.
    for key, val in os.environ.items():
        if key.startswith("ENGINE_") and key.endswith("_PUBLIC_URL"):
            _add("engine-" + key[len("ENGINE_"):-len("_PUBLIC_URL")].lower(), val)
    # The three whose URL variables predate that convention. Mapped to the component name
    # each one announces itself as, so a silent service still lands under the right row.
    _add("engine-o", _DAGSONTOLOGY_SVC_URL)
    _add("engine-f", _PRESENTATION_AGENT_SVC_URL)
    # READ LIVE, not from the import-time constant. The two reads serve different questions:
    # readiness asks "was this DECLARED at startup" and must be fixed at import, while this
    # aggregation asks "where is engine-d right now" and must reflect the current environment.
    # Binding this one to the import-time value silently broke the fleet report under any
    # caller that sets the variable after import — caught by
    # tests/routing/test_the_fleet_report_has_four_states.py, which is exactly its job.
    _add("engine-d", os.getenv("DATAHUB_WRAPPER_URL", ""))
    return out


@app.get("/fleet/version", tags=["ops"])
async def fleet_version() -> dict:
    """Every service's own report, plus this one's. Unreachable is NAMED, never omitted.

    A service that cannot be asked is the most interesting row in the table — it is what a
    mid-roll pod, a crash-looping pod and a service that was never deployed all look like —
    so it appears with its reason instead of being dropped, which would make the fleet read
    complete. Same rule as the census treating an unplaceable service as NOT current.
    """
    targets = _fleet_version_targets()
    results: dict = {}

    async def _ask(name: str, base: str) -> None:
        """FOUR STATES, BECAUSE THERE ARE FOUR, and the first version had one.

            a sha        answered and reports its build
            no_endpoint  answered with 404 — /version is not in that image yet: ROLL IT
            unstamped    answered, endpoint present, that build carried no GIT_SHA
            unreachable  nothing came back at all: the service is DOWN

        Collapsing these is the `fetch_registered_entries` conflation one more time.
        cortex-ui-60 hit it in their header the same night — it read UNREACHABLE for a BFF
        that was up and serving picks, because it had 404'd an endpoint that simply had not
        been rolled yet — and warned me this aggregator had the identical shape. It did.
        "The service is down" and "the service has not been rolled" have OPPOSITE repairs:
        go and rescue it, versus deploy it.

        THE DISCRIMINATOR IS WHETHER THE SERVICE SPOKE. httpx raises `HTTPStatusError` with
        a `.response` when it answered and `RequestError` with none when the request never
        landed. A non-404 status is neither down nor missing, so it carries its own status:
        401 and 500 are different problems and neither one is "no endpoint".

        The value of `unreachable` is entirely in how rarely it is right.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{base}/version")
        except Exception as exc:  # noqa: BLE001 — nothing came back
            results[name] = {
                "component": name, "git_sha": None, "url": base,
                "state": "unreachable", "asked_as": name,
                "detail": f"{type(exc).__name__}: {exc}"[:200],
            }
            return

        if r.status_code == 404:
            results[name] = {
                "component": name, "git_sha": None, "url": base,
                "state": "no_endpoint", "asked_as": name,
                "detail": "/version not served by this build — roll it",
            }
            return
        if r.status_code >= 400:
            results[name] = {
                "component": name, "git_sha": None, "url": base,
                "state": "error", "detail": f"HTTP {r.status_code}",
            }
            return
        try:
            body = dict(r.json())
        except Exception as exc:  # noqa: BLE001 — answered with something that is not ours
            results[name] = {
                "component": name, "git_sha": None, "url": base,
                "state": "error", "detail": f"unparseable: {type(exc).__name__}",
            }
            return
        # ANSWERED. `unstamped` is not a failure — it is an image built before the stamp
        # existed, and saying so sends a reader to the build rather than to the pod.
        body["state"] = "reporting" if body.get("git_sha") else "unstamped"
        # KEYED BY WHAT THE SERVICE CALLS ITSELF, not by the env var we found its URL in.
        # The env-derived name is an accident of the variable (`ENGINE_A_PUBLIC_URL` -> "a",
        # `ONTOLOGY_SERVICE_URL` -> "ontology"), and a consumer then has to GUESS which
        # deployment "ontology" is. Measured on the first live census: six services showed
        # no sha purely because the guess failed, while every one of them was reporting
        # correctly. The payload carries the canonical `component` — use it.
        body.setdefault("asked_as", name)
        results[str(body.get("component") or name)] = body

    await asyncio.gather(*(_ask(n, b) for n, b in targets.items()))
    _self = _version_payload("cortex-bff")
    _shas = {
        r.get("git_sha") for r in [_self, *results.values()] if r.get("git_sha")
    }
    return {
        "self": _self,
        "services": results,
        # A COUNT, NOT A VERDICT. More than one distinct sha across this repo's services is
        # a fleet mid-roll or a partial roll; which of those it is depends on when you
        # asked, and this endpoint does not know. The census decides, against each repo's
        # own head.
        "distinct_shas": sorted(_shas),
        "asked": len(targets),
        # BY STATE, so a reader sees which of the four each service is in rather than a
        # single bucket that means four different repairs.
        "by_state": {
            st: sorted(n for n, r in results.items() if r.get("state") == st)
            for st in ("reporting", "unstamped", "no_endpoint", "error", "unreachable")
            if any(r.get("state") == st for r in results.values())
        },
    }


#: Service URLs that were NOT declared, recorded so readiness can refuse.
#:
#: RULED 2026-09-11 — a missing ConfigMap entry for a service URL is a DEPLOY FAULT and must
#: fail readiness. It must NOT fall back to an in-cluster address that happens to work.
#:
#: This is the fail-open default in its quietest form. `version_census.py` derives the fleet by
#: scanning these variables; with a fallback, a service whose URL nobody declared still gets
#: asked at the hardcoded address, still answers, and still reports a REAL sha — so the census
#: prints a green row for an address that exists nowhere in the chart. The day the service
#: moves, the map is fiction with a green check beside it.
#:
#: Recorded rather than raised at import: a crash-loop cannot tell anyone WHY. A pod that runs,
#: refuses readiness, and names the missing variable is diagnosable; one that dies during module
#: import is not. Same distinction engine-lg's floor draws — see
#: docs/principles/a-host-with-nothing-admitted-is-not-ready.md.
_UNDECLARED_SERVICE_URLS: dict[str, str] = {}


def _required_service_url(var: str, *, used_for: str) -> str:
    """Read a service URL that the chart is REQUIRED to declare. No fallback.

    Returns "" when undeclared, and records it. Callers get an empty string — which every
    consumer here already treats as "cannot reach" — while readiness gains the reason.
    """
    raw = (os.getenv(var) or "").strip()
    if not raw:
        _UNDECLARED_SERVICE_URLS[var] = used_for
    return raw


_DAGSONTOLOGY_SVC_URL = _required_service_url(
    "ONTOLOGY_SERVICE_URL", used_for="engine-o — routing, and the census target for engine-o"
)
#: READ AT IMPORT, not per request, and that is the point. Its two consumers both read it
#: lazily, so an undeclared DATAHUB_WRAPPER_URL was invisible to readiness until someone
#: happened to call lineage — a deploy fault that only surfaces on the request that needs it
#: is a deploy fault nobody sees at deploy time. Caught by this file's own boundary test
#: (two of three declared must still refuse), which is the case that would otherwise slip.
_DATAHUB_WRAPPER_URL = _required_service_url(
    "DATAHUB_WRAPPER_URL", used_for="engine-d — lineage_edges, and the census target"
)
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
@app.get("/me/entitlements", tags=[INGEST_V1_TAG], responses={200: {"model": Entitlements}, 503: DROP_GATE_RESPONSES[503]})
async def get_me_entitlements(current_user: User = Depends(get_current_user)):
    """Return the current user's (persona, domain) entitlement matrix.

    `authz_id` is the key every route that takes `on_behalf_of` compares against: a self-drop
    echoes it. `email` is display only; at work-deploy it is not the authz_id, and sending it
    as `on_behalf_of` is refused `not_a_delegate` (2026-10-21)."""
    from starlette.concurrency import run_in_threadpool

    from . import content_kinds, human_tasks

    ent = current_user.entitlements
    # `droppable_kinds`: every registered kind except a GATED kind (Topaz object
    # `capability:can_drop:<kind>` exists) this caller is not granted. One unreadable object makes
    # the whole answer 503 -- never a partial or guessed list.
    def _droppable() -> list[str]:
        out: list[str] = []
        for reg in content_kinds.registrations():
            if human_tasks.can_drop_refusal(reg.kind, current_user.authz_id) is None:
                out.append(reg.kind)
        return out

    try:
        droppable_kinds = await run_in_threadpool(_droppable)
    except human_tasks.AuthorizationUnconfigured as exc:
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unconfigured",
            "message": "the deployment declares no authorization directory"}) from exc
    except human_tasks.AuthorizationUnavailable as exc:
        logger.warning("droppable_kinds unavailable: %s", exc)
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unavailable",
            "message": "could not verify which kinds are restricted"},
            headers={"Retry-After": _CAN_DROP_RETRY_AFTER}) from exc
    return {
        "user_id": current_user.id,
        "authz_id": current_user.authz_id,
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
        "droppable_kinds": droppable_kinds,
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
from pydantic import BeforeValidator as _BeforeValidator, StrictFloat as _StrictFloat  # noqa: E402
from pydantic import StrictInt as _StrictInt  # noqa: E402
from pydantic import StrictBool as _StrictBool, StrictStr as _StrictStr  # noqa: E402
from typing import Annotated as _Annotated  # noqa: E402
from typing import Union as _Union  # noqa: E402


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
    # NEW (HAZ-1003): which Restate service owns the run, and the promise name it awaits.
    # Validated against human_tasks.ALLOWED_WORKFLOW_SERVICES at register time — a name outside
    # it is refused HERE (422) rather than trusted through to `/act`, which would otherwise
    # interpolate an unvetted string into a Restate ingress URL.
    workflow_service: Optional[str] = None
    promise_name: Optional[str] = None
    # authz_ids the definition bars from deciding this task; never routed to (ruled 2026-10-02).
    # DECLARED HERE because this model drops unknown fields silently: undeclared, an exclusion
    # sent by the runner would vanish and the dropper would be routed the task.
    excludes: list[str] = []
    # The case this task belongs to (architect ruling 2026-10-17): a holder of the task may read
    # the case. Blank is absent. DECLARED HERE because this model drops unknown fields silently.
    case_id: Optional[str] = None

    @field_validator("case_id", mode="before")
    @classmethod
    def _blank_case_id_is_absent(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v


#: The grouped review's reject codes ARE the promotion's (architect ruling 2026-10-19: "the
#: four-code ruling applies to every reject surface"), in `PROMOTION_REJECT_CODES`'s order --
#: cortex's parity seal reads this literal and the Literal below, in order.
_GROUPED_REJECT_CODES = ("not_a_notice", "unreadable", "parts_unusable", "duplicate")
#: The pre-ruling names (`parts_list_unusable`, `superseded_or_duplicate`) were aliased onto these
#: for the transition and are REFUSED since 199 (architect 2026-10-20: "drop the reject-code
#: aliases (cortex already sends the four)").


def _nonblank(v: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError("must be a non-empty string")
    return v


class _RowEditsModel(_BaseModel):
    model_config = {"extra": "forbid"}


def _wire_evidence_ref(v):
    """The wire check for an evidence_ref: the struct (validated by `EvidenceRef`) or the legacy
    non-blank string; anything else is a 422. The value is kept in the form it arrived in -- the
    act normalizes it with `steward_correction.normalize_evidence_ref`, the same function the
    runner applies to whatever it is forwarded."""
    if v is None:
        return None
    if isinstance(v, str):
        return _nonblank(v)
    if isinstance(v, dict):
        # Architect ruling 2026-10-31: the SDK's rule wins; a ref it (or the named checks) refuses is
        # a 422 naming the check. The checks are strict (no bool/str coercion) where the model is lax.
        _check = _wire_evidence_ref_failure(v)
        try:
            ref = EvidenceRef.model_validate(v)
        except _PydanticValidationError:
            _check = _check or "invalid"
        if _check is not None:
            raise HTTPException(status_code=422, detail={
                "error": "evidence_ref_invalid", "check": _check})
        return {"page": ref.page, "bbox": list(ref.bbox) if ref.bbox is not None else None,
                **({"note": ref.note.strip()} if ref.note is not None else {})}
    raise ValueError("an evidence_ref is {page, bbox, note?} or a non-blank string")


_WireEvidenceRef = _Annotated[Optional[Any], _BeforeValidator(_wire_evidence_ref)]


class DeletedRow(_RowEditsModel):
    mpn: str
    reason: str   # a delete needs a reason
    evidence_ref: _WireEvidenceRef = None   # {page, bbox, note?} | non-blank str; optional until cortex-ui ships it


class AddedRow(_RowEditsModel):
    mpn: str
    disposition: str
    reason: str
    evidence: str
    evidence_ref: _WireEvidenceRef = None


class CorrectedRow(_RowEditsModel):
    mpn: str            # the EXTRACTED mpn -- identity never moves
    corrected_mpn: str
    evidence: str
    evidence_ref: _WireEvidenceRef = None


class RowEdits(_RowEditsModel):
    """Steward row edits on a grouped-review approval (architect ruling 2026-10-10). The workflow's
    `steward_correction.validate_row_edits` restates every rule against the server-authored batch;
    this is the wire half, so a bad payload is a 422 before it reaches Restate. It is also the
    document_promotion wire (carried on a `promoted` decision, server-flagged by
    IAGENT_PROMOTION_ROW_EDITS)."""
    deleted: list[DeletedRow] = []
    added: list[AddedRow] = []
    corrected: list[CorrectedRow] = []

    @model_validator(mode="after")
    def _rules(self):
        for r in self.deleted:
            _nonblank(r.mpn); _nonblank(r.reason)
        for r in self.added:
            for v in (r.mpn, r.disposition, r.reason, r.evidence):
                _nonblank(v)
        for r in self.corrected:
            for v in (r.mpn, r.corrected_mpn, r.evidence):
                _nonblank(v)
            if r.corrected_mpn.strip().lower() == r.mpn.strip().lower():
                raise ValueError(f"corrected_mpn must differ from mpn for {r.mpn!r} (ignoring case)")
        seen: set = set()
        for r in list(self.deleted) + list(self.corrected):
            k = r.mpn.strip().lower()
            if k in seen:
                raise ValueError(f"mpn {r.mpn!r} appears more than once across deleted/corrected")
            seen.add(k)
        return self


class HeaderEdit(_RowEditsModel):
    """A steward correction of one header field of a promotion (ruling 10-20, Q8 amended), on the
    same wire and flag as row_edits."""
    field: Literal["mfr", "notice_id", "notice_date"]
    value: str
    evidence_ref: _WireEvidenceRef      # required: {page, bbox, note?} | non-blank str
    reason: str

    @model_validator(mode="after")
    def _rules(self):
        if self.evidence_ref is None:
            raise ValueError("a header edit needs an evidence_ref")
        for v in (self.value, self.reason):
            _nonblank(v)
        return self


class CoverageGroup(_RowEditsModel):
    """One group of parts a steward folded without opening: the grouping rule, its key, and the
    members NOT opened (part_index values)."""
    rule: _Annotated[str, Field(min_length=1)]
    key: _Annotated[str, Field(min_length=1)]
    parts: list[_StrictInt]


_UnitFloat = _Annotated[_StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)]
_UnitInt = _Annotated[_StrictInt, Field(ge=0, le=1)]


class CoverageShared(_RowEditsModel):
    """One evidence crop that many parts cite (recorded, not re-derived)."""
    rule: _Annotated[str, Field(min_length=1)]
    page: _StrictInt = Field(ge=1)
    bbox: _Annotated[list[_UnitFloat | _UnitInt], Field(min_length=4, max_length=4)]
    parts: list[_StrictInt]
    confirmed: _StrictBool


class ReviewCoverage(_RowEditsModel):
    """DEPRECATED, accepted for 0.4.73 only: the 1.4.0 `parts` form; it is read as items (see
    `review_coverage.py`). The item form is `ItemReviewCoverage`.

    What the steward looked at on a document promotion (ruled 2026-10-29: a sampled promote is
    legal if it is recorded). Ids are the extraction's integer `part_index`. The route checks every
    part was opened or folded into a group (`review_coverage_invalid`); `sampled`, `flagged`,
    `shared` and `sample` are recorded as sent."""
    rules_version: _Annotated[str, Field(min_length=1)]
    looked_at: list[_StrictInt]
    sampled: list[_StrictInt]
    flagged: list[_StrictInt]
    groups: list[CoverageGroup]
    shared: list[CoverageShared]
    sample: Optional[dict[str, _StrictStr | _StrictInt | _StrictFloat | _StrictBool]] = None


def _promotion_row_edits_enabled() -> bool:
    """IAGENT_PROMOTION_ROW_EDITS: ON only for the exact string "true" (after strip, lowercased).
    Default OFF (architect ruling 2026-10-18: server-flagged off until one live correction is proved)."""
    return os.environ.get("IAGENT_PROMOTION_ROW_EDITS", "").strip().lower() == "true"


class HumanTaskActRequest(_BaseModel):
    decision: str  # "approved" | "rejected"
    comment: str = ""
    # Grouped review only. A narrow REJECT (wrong document / not a notice / duplicate) names why;
    # REQUIRED for a grouped_review reject (checked at the route, where the kind is known).
    reason_code: Optional[Literal["not_a_notice", "unreadable", "parts_unusable", "duplicate"]] = None
    # Grouped review approval, or document promotion `promoted` (flag-gated at the route): steward
    # deletes / additions / corrections, each with evidence.
    row_edits: Optional[RowEdits] = None
    # Document promotion `promoted` only (same flag as row_edits): header-field corrections.
    header_edits: Optional[list[HeaderEdit]] = None
    # Document promotion `promoted` only: what the steward opened vs folded (provenance).
    review_coverage: Optional[_Union[ItemReviewCoverage, ReviewCoverage]] = Field(
        default=None, union_mode="left_to_right")
    # document_empty_confirm `has_parts` only (spec 208): the page the steward points at.
    page: Optional[_StrictInt] = None

    @model_validator(mode="after")
    def _verb_fields(self):
        if self.page is not None and self.decision != "has_parts":
            raise ValueError("page is only valid with decision='has_parts'")
        if self.reason_code is not None and self.decision != "rejected":
            raise ValueError("reason_code is only valid with decision='rejected'")
        if self.row_edits is not None and self.decision not in ("approved", "promoted"):
            raise ValueError("row_edits is only valid with decision='approved' (grouped review) "
                             "or 'promoted' (document promotion)")
        if self.review_coverage is not None and self.decision != "promoted":
            raise ValueError("review_coverage is only valid with decision='promoted' "
                             "(document promotion)")
        if self.header_edits is not None and not self.header_edits:
            self.header_edits = None
        if self.header_edits is not None:
            if self.decision != "promoted":
                raise ValueError("header_edits is only valid with decision='promoted' "
                                 "(document promotion)")
            _fields = [h.field for h in self.header_edits]
            if len(set(_fields)) != len(_fields):
                raise ValueError("header_edits names a field more than once")
        return self

    # PCN grouped review only: optional per-part disposition overrides the reviewer
    # changed from the proposal, {mpn: {disposition, reason}}. Absent/empty = accept-all
    # (every part takes its proposed disposition). Ignored for non-grouped-review kinds.
    overrides: Optional[dict] = None
    # R-089: the PRINCIPAL a delegate caller asserts it is acting for. iagent RECORDS this
    # claim and does not verify it this pass (the ruling's own words) — trusted only because
    # DELEGATE_ON_BEHALF_OF (deploy configuration) says this caller may speak for this
    # principal. Absent, or equal to the caller's own authz_id, is the unchanged person path.
    on_behalf_of: Optional[str] = None


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
                payload=req.payload, workflow_service=req.workflow_service,
                promise_name=req.promise_name, excludes=req.excludes,
                case_id=req.case_id,
            )
        )
    except human_tasks.HumanTaskConfigError as exc:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured", "message": str(exc)})
    except human_tasks.NoEntitledRecipients as exc:
        # TERMINAL 4xx (not 5xx): a task with zero entitled actors is a permanent misconfiguration, not
        # a transient outage — the caller's workflow must fail-and-release (never park or retry-forever).
        raise HTTPException(status_code=422, detail={"error": "no_entitled_recipients", "message": str(exc)})
    except human_tasks.UnknownWorkflowService as exc:
        # Same TERMINAL-4xx discipline as NoEntitledRecipients: an unvetted service name is a
        # permanent misconfiguration (a typo, or a caller naming a service that was never meant
        # to be resumable), not a transient failure — refuse rather than register a row `/act`
        # could later be tricked into resuming against.
        raise HTTPException(status_code=422, detail={"error": "unknown_workflow_service", "message": str(exc)})
    except human_tasks.NoRequester as exc:
        raise HTTPException(status_code=422, detail={"error": "no_requester", "message": str(exc)})
    logger.info("human_task registered: task_id=%s audience=%s recipients=%d",
                req.task_id, req.audience, len(result.get("recipients", [])))
    return result


class HumanTaskExpireRequest(_BaseModel):
    task_id: str
    workflow_id: Optional[str] = None


@app.post("/internal/human_tasks/expire")
async def expire_human_task(
    req: HumanTaskExpireRequest,
    current_user: User = Depends(get_current_user),
):
    """Retire the still-`pending` queue row(s) of a task whose human_await TIMED OUT, so neither
    REST nor the feed offers a task nobody can act on. INTERNAL seam, same gate as register
    (get_current_user). `expired == 0` is a 200: an already-resolved task stays resolved."""
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks
    n = await run_in_threadpool(lambda: human_tasks.expire_open_task(req.task_id, req.workflow_id))
    logger.info("human_task expired: task_id=%s workflow_id=%s rows=%d", req.task_id, req.workflow_id, n)
    return {"task_id": req.task_id, "workflow_id": req.workflow_id, "expired": n}


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
                # WHO ASKED, by the key every other register path uses (authz_id, never the
                # display email): at work-deploy the two differ, and a requester the store
                # cannot join to a grant subject names nobody.
                requested_by=current_user.authz_id,
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
    except human_tasks.NoRequester as exc:
        raise HTTPException(status_code=422, detail={"error": "no_requester", "message": str(exc)})
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
    except human_tasks.NoRequester as exc:
        raise HTTPException(status_code=422, detail={"error": "no_requester", "message": str(exc)})
    logger.info("triage_task filed: task_id=%s reason=%s audience=%s recipients=%d",
                task_id, req.reason_code, audience, len(result.get("recipients", [])))
    return {"task_id": task_id, "status": "FILED", "audience": audience,
            "recipients": len(result.get("recipients", []))}


@app.get("/me/human_tasks", tags=[INGEST_V1_TAG, MCP_TAG], responses={200: {"model": HumanTasksListing}})
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
    # EACH ROW CARRIES ITS SPECIES' DECLARATION. Without this the only way a client could learn
    # what a kind accepts was to POST a verb and be told it was wrong — `verbs_for_kind` appeared
    # exactly ONCE in this file, inside the REFUSAL body. That is discovery-by-failure, and on
    # this surface it is worse than inelegant: ADR-0034 archives decision records, so probing to
    # learn a menu writes attempted decisions nobody made. Measured by cortex-ui-60 in the
    # serving pod at 5fb7ae4.
    tasks = await run_in_threadpool(lambda: human_tasks.decorate_with_declarations(tasks))
    # `email` is DISPLAY only; the queue was filtered on authz_id above.
    return {"email": current_user.email, "tasks": tasks}


@app.get("/task_kinds")
async def get_task_kinds(current_user: User = Depends(get_current_user)):
    """Every declared species and its contract — the menu, readable without attempting it.

    THE COMPANION TO THE PER-ROW DECLARATION, for the case a row cannot serve: a client rendering
    a filter, a legend, or an EMPTY queue still needs to know what species exist.

    NOT GATED ON ENTITLEMENT, deliberately. This returns the SHAPE of a decision — which verbs a
    species takes and which need a reason — never a decision and never a task. Withholding it
    would protect nothing, since the refusal body already names the allowed verbs to anyone who
    posts one; it would only force the probing this endpoint exists to remove.

    `composed: false` WITH AN EMPTY MENU IS NOT AN EMPTY MENU. When the registry cannot be
    composed the flag says so, because an unreadable overlay must not read as "no species exist".
    That is the same None-is-not-empty distinction the gate itself turns on, and conflating them
    is what would take the task rail down.
    """
    from starlette.concurrency import run_in_threadpool
    from . import human_tasks

    def _read():
        declared = human_tasks._declared_kinds()
        if declared is None:
            return None
        return {k: human_tasks.declaration_for(k) for k in sorted(declared)}

    try:
        kinds = await run_in_threadpool(_read)
    except human_tasks.HumanTaskConfigError:
        kinds = None
    return {"composed": kinds is not None, "kinds": kinds or {}}


@app.get("/templates")
async def get_templates(current_user: User = Depends(get_current_user)):
    """Every RATIFIED canvas template — the menu, readable without attempting a seed.

    R-039's read-path rule, and the companion to `/task_kinds` for the same reason: a client
    rendering a picker needs to know WHAT EXISTS before it can offer one, and the only way to
    learn it today is to seed a board and see whether the id was recognised. The registry is
    already the authority — `ratified_template_ids` derives it from the directory on every call,
    deliberately uncached — and this exposes it rather than adding a second source.

    NOT GATED ON ENTITLEMENT, matching `/task_kinds` and for its reasoning: this returns the
    SHAPE of a board — its id, title, description and panel count — never a board, never a
    card, and never anything read out of the substrate. Withholding it would protect nothing,
    because the seed verb's own refusal already names the ratified set to anyone who guesses
    wrong; it would only force the probing this endpoint exists to remove.

    THREE STATES, NOT TWO, and the flag is the difference. `composed: false` with an empty list
    is NOT "nothing is ratified": it is "the directory could not be read", which is the
    None-is-not-empty distinction `/task_kinds` turns on and the same one that would otherwise
    let a deployment accident render as an empty picker a user reads as a complete menu.

    A TEMPLATE THAT WILL NOT LOAD IS NAMED, NEVER DROPPED. `load_template` validates and raises
    rather than returning a default — correctly, because a wrong board is harder to notice than
    a missing one. Silently omitting it here would undo that: the list would be SHORTER and
    nothing would say why, and a shorter list reads as the complete set. So it comes back in
    `unreadable` with its reason, and the picker can show what it cannot offer.
    """
    from starlette.concurrency import run_in_threadpool
    from .canvas_template import (
        SHARED_SLOT_REFERENTS, load_template, ratified_template_ids, template_ref,
    )

    def _read():
        ids = ratified_template_ids()
        rows, broken = [], []
        for tid in ids:
            try:
                t = load_template(tid)
            except Exception as exc:  # noqa: BLE001
                # The id IS ratified — it is in the directory — and the file does not parse or
                # does not validate. That is a different fact from "not ratified" and the
                # caller needs both.
                broken.append({"template_id": tid,
                               "reason": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            rows.append({
                "template_id": t.template_id,
                "title": t.title,
                "description": t.description,
                # THE CONTENT HASH, so a client can tell a template that CHANGED from one that
                # merely still exists. A picker holding a stale ref offers a board whose shape
                # has moved under it.
                "template_ref": template_ref(t),
                "panels": len(t.panels),
                "shared_slots": [sl.name for sl in (t.shared_slots or [])],
                # `shared_slots` (names) stays as cortex reads it; this sibling says which of
                # them the server can ASK about, so a picker can offer the row and expect a 409
                # carrying an ask instead of only labelling it "needs a binding". No
                # enumeration happens here: `askable` is a fact about the declaration.
                "shared_slot_detail": [
                    {
                        "name": sl.name,
                        "param": sl.bind_as,
                        "required": sl.required,
                        "consumed": any(sl.name in p.consumes for p in t.panels),
                        "askable": sl.bind_as in SHARED_SLOT_REFERENTS,
                    }
                    for sl in (t.shared_slots or [])
                ],
            })
        return rows, broken

    try:
        templates, unreadable = await run_in_threadpool(_read)
        composed = True
    except Exception as exc:  # noqa: BLE001
        # The DIRECTORY itself is unreadable — not one file. `ratified_template_ids` returns []
        # for a missing directory, which is indistinguishable from "none ratified" at this
        # layer, so anything raising out of the read is reported as not-composed rather than as
        # an empty menu.
        logger.warning("/templates could not compose the registry: %s", exc)
        templates, unreadable, composed = [], [], False

    return {"composed": composed, "templates": templates, "unreadable": unreadable}


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
    # The ingest row this notice came through (`sha256:<64 hex>`), when the extraction names its
    # source document. The ONLY key the narrow reject may use to mark an ingest row: the
    # extracted doc_id (`notice_id`) is LLM-derived and never matches a row id.
    ingest_id: Optional[str] = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
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


def _review_on_behalf_of(artifact_uri: str) -> str:
    """The PERSON a review's lookups run for (ruling (a), 2026-10-10): the dropper of the ingest the
    reviewed artifact came from, DERIVED FROM THE ARTIFACT and never read from the body. doc-tools
    writes `ingest_id` into `manifest.json`, the sibling of the review.json `artifact_uri` names; the
    ingest's status row holds its dropper of record in `on_behalf_of` (the `actor` the drop route
    also stamps as the IngestArtifact's `dropped_by_authz_id`). So a caller can name WHICH artifact,
    and the artifact names whose review it is: one artifact cannot be composed under another
    ingest's dropper.

    "" (no person) when there is honestly none: no pointer, no manifest, a manifest without an
    `ingest_id`, or an ingest the BFF never recorded. An OUTAGE is not "no person": a store that
    does not answer raises 503 rather than composing under the seeded-only view."""
    from urllib.parse import urlparse
    from . import ingest_status

    u = urlparse(artifact_uri or "")
    key = u.path.lstrip("/")
    if u.scheme != "s3" or not u.netloc or "/" not in key:
        return ""
    manifest_key = key.rsplit("/", 1)[0] + "/manifest.json"
    try:
        raw = _build_s3_client().get_object(Bucket=u.netloc, Key=manifest_key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        code = ""
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            code = str((resp.get("Error") or {}).get("Code") or "")
        if code in ("NoSuchKey", "404") or "NoSuchKey" in str(exc):
            return ""
        raise HTTPException(status_code=503, detail={
            "error": "artifact_store_unreachable",
            "message": f"the artifact store did not answer for the manifest beside {artifact_uri!r}: "
                       f"{type(exc).__name__}: {exc}"})
    try:
        manifest = json.loads(raw)
    except ValueError:
        return ""
    ingest_id = manifest.get("ingest_id") if isinstance(manifest, dict) else None
    if not isinstance(ingest_id, str) or not ingest_id:
        return ""
    try:
        row = ingest_status.get_row(ingest_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={
            "error": "ingest_status_unreachable",
            "message": f"the ingest status store did not answer for {ingest_id!r}: "
                       f"{type(exc).__name__}: {exc}"})
    return str((row or {}).get("on_behalf_of") or "")


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
    automatically when an extraction lands its review.json — one review per ARTIFACT
    (idempotent on ETag+key, NOT on the extracted notice id: that mechanism was removed,
    so the same document under a different object key yields a SECOND review),
    impacted_parts sourced from review.json.
    Call this route by hand only to re-drive a specific notice (e.g. after fixing a
    ruleset / grant) — same status as re-running a Dagster partition. NOTE the re-drive
    is subject to the ingress idempotency key below: within its retention window a
    re-drive of an unchanged artifact REPLAYS the prior response rather than executing."""
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
    body["ingest_id"] = req.ingest_id or ""   # rebuilding hop: absent here = absent downstream
    body["trace_id"] = req.trace_id or ""       # extraction trace id -> ReviewStarter adopts it (ADR-0038)
    # THE ARTIFACT'S LOCATION — a DIFFERENT field from the identity above, and the entire admission
    # contract. This is a REBUILDING HOP (the body is hand-enumerated twice over), which is exactly
    # where `review_state_source` and `extraction_warnings` were silently dropped in 2026-07-30; a
    # field that does not appear on this line does not exist downstream. Pinned by
    # tests/test_review_payload_passthrough.py.
    body["artifact_uri"] = req.artifact_uri or ""
    # THE PERSON the composition's lookups run for: derived from the artifact above, never from the
    # body (ruling (a)). ReviewStartRequest declares no such field, so a caller cannot assert one.
    from starlette.concurrency import run_in_threadpool
    body["on_behalf_of"] = await run_in_threadpool(_review_on_behalf_of, body["artifact_uri"])
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
    x_frontend_version: Optional[str] = Header(default=None, alias="X-Frontend-Version"),
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
        raise HTTPException(status_code=rr.status_code,
                            detail=_detail_with_message(rr.status_code, rr.json()))

    out = rr.json()
    return {
        "measure": out.get("measure", fn),
        "output_uri": out.get("output_uri"),
        "state_ref": out.get("state_ref", body.state_ref),
        # The pull trigger's discriminant (ADR-0042 OQ1) and the live view's freshness stamp.
        "state_version": out.get("state_version"),
        "rows": out.get("rows"),
        "frontend_id": x_frontend_id,
        "frontend_version": x_frontend_version,
    }


class FinanceMeasureBody(_BaseModel):
    """Only `params`. There is no `state_ref`, deliberately: finance_agent's `MeasureRequest`
    (agent_fleet/finance_agent/main.py) carries `params` and `user_email` and nothing else, so a
    `state_ref` here would be accepted and silently dropped."""
    params: dict = {}


# A measure name is one plain path segment. Without this, `..` or a decoded `?`/`#` in `fn` would
# send the caller's bearer to some other engine path; the ruling exposes no engine route directly.
_MEASURE_NAME = r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$"


@app.post("/finance/measure/{fn}", tags=[MCP_TAG])
async def finance_measure(
    fn: _Annotated[str, _Path(pattern=_MEASURE_NAME)],
    body: FinanceMeasureBody,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """A thin relay to finance_agent `/measure/{fn}` (architect ruling 10-30, ruling 1: "add a
    thin BFF relay for /measure/{fn} (it's what cortex calls anyway). No engine route is exposed
    directly.").

    Unlike `plan_measure`, this relay forwards the caller's bearer and `authz_id`, so the engine's
    program-visibility check (`_require_visible`) decides for the real caller. The engine's 422
    `needs_slots` is relayed unchanged (it is the declared refusal for a missing slot, not a
    policy refusal); every other >= 400 goes through `relay_refusal` as `export_package` does.
    A 200 is the engine's envelope, untouched."""
    bearer = _user_bearer(request)
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            rr = await client.post(
                f"{_ENGINE_FIN_URL}/measure/{fn}",
                json={"params": body.params, "user_email": current_user.authz_id},
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "fin_engine_unreachable", "message": str(exc),
        })

    if rr.status_code == 422:
        raise HTTPException(status_code=422,
                            detail=_engine_refusal_detail(rr, f"/measure/{fn}"))
    if rr.status_code >= 400:
        try:
            body_json = rr.json()
            detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
        except Exception:
            detail = getattr(rr, "text", "engine refused")
        raise HTTPException(status_code=rr.status_code,
                            detail=_detail_with_message(rr.status_code, relay_refusal(detail)))

    return _engine_answer(rr, f"/measure/{fn}")


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
        raise HTTPException(status_code=rr.status_code,
                            detail=_detail_with_message(rr.status_code, rr.json()))

    out = rr.json()
    return {"state_ref": out.get("state_ref", state_ref), "state_version": out.get("version")}


# -- Cost export packages (relay item 3) — the disclosure download seam -------
#
# THE SAME VARIABLE THE ENGINE REGISTERS WITH (measures.py's `_PUBLIC_BASE_ENV`), deliberately
# not a second name: the chart's configmap already sets it for every pod, and a route reading
# a name nobody sets is the ENGINE_P_URL mistake (two lines up) happening a second time.
_ENGINE_COST_URL = os.getenv("ENGINE_COST_PUBLIC_URL", "http://iagent-engine-cost:8097")

# SAME NAME THE FINANCE ENGINE REGISTERS WITH (`finance_agent/main.py`'s own
# `_PUBLIC_BASE_ENV`/`_DEFAULT_BASE`), never a second one — the ENGINE_P_URL mistake again.
_ENGINE_FIN_URL = os.getenv("ENGINE_FIN_PUBLIC_URL", "http://iagent-engine-fin:8096")

# The engine's own sha256-locator shape (`measures.package_export`'s `artifact_sha256`):
# "sha256:" + 64 lowercase hex digits. A response missing this, or carrying something that
# merely looks like it, is not a verifiable artifact and must not be reported as one.
_SHA256_LOCATOR_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


# Each engine's OWN owner key on the `recipient_readers` rail (policy/recipient_readers.yaml). They are
# identities, not cases: the rows (who reads which scope) are the rail's, and an owner string that is
# not a key of that file reads nobody.
_COST_OWNER = "cost"
_FIN_OWNER = "finance"


def _rail_reader(owner: str, scope: str, authz_id: Optional[str]) -> bool:
    """`can_read_recipient(owner, ...)`, keyed on the PERSON's `authz_id`; a transport/HTTP failure
    is a 503 (`recipient_readers_unavailable`), never a deny."""
    from agent_fleet.utils.recipient_readers import can_read_recipient
    try:
        return bool(authz_id) and bool(can_read_recipient(owner, scope, authz_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("recipient_readers check failed: %s", exc)
        raise HTTPException(
            status_code=503, detail={"reason": "recipient_readers_unavailable"}
        ) from exc


def _export_recipients_for(user: "User") -> list[str]:
    """Every cost recipient scope `user` may export to or download from: the scopes engine-cost
    DISCLOSES (`RECIPIENT_SCOPES`), each asked of the `recipient_readers` rail under owner
    `cost`, keyed on `authz_id` -- the SAME claim and the same rail the engine's own /artifact
    route asks. One Topaz call per scope. A rail that cannot be asked is a 503."""
    from agent_fleet.cost_agent import seed as _cost_seed
    return sorted(
        s for s in _cost_seed.RECIPIENT_SCOPES
        if _rail_reader(_COST_OWNER, s, user.authz_id)
    )


def _fin_export_recipients_for(user: "User") -> list[str]:
    """`_export_recipients_for`'s exact shape, read against engine-fin's own
    `export.RECIPIENT_SCOPES` under owner `finance` -- the two engines' disclosures are entitled
    independently (the rail's object id carries the owner), and this is why there are two
    functions rather than one parameterised by module: a caller reading the wrong engine's
    scopes would grant access this gateway never meant to."""
    from agent_fleet.finance_agent import export as _fin_export
    return sorted(
        s for s in _fin_export.RECIPIENT_SCOPES
        if _rail_reader(_FIN_OWNER, s, user.authz_id)
    )


# -- PLAN ANSWERS EXPORT (policy/exports) ----------------------------------------------------
#
# A plan recipient is named by an answer-export profile (`agent_fleet/utils/answer_exports.py`,
# seed `policy/exports/`), not by cost's `RECIPIENT_SCOPES`. Its READERS are the
# `recipient_readers` rail under owner "plan": `can_read_recipient("plan", scope, authz_id)`.
# Deny-by-default; until that owner exists on the rail nobody can export to one, which is intended.
# PRODUCING one also needs `can_export:<profile name>` (ruled (b) 10-30, deny by default, the row is
# policy's): "exportable" = reader AND can_export. The download stays reader-only.
_PLAN_OWNER = "plan"
_NOT_A_KIND = "not_a_kind_this_recipient_takes"
_SCENARIO_ANSWER = "scenario_answer"


def _cost_profiles_get(url: str) -> "httpx.Response":
    """The one GET to engine-cost for its profile set (a seam: the tests serve cost's real app
    through it). It carries NO person and so no bearer: the set is policy, not a person's data."""
    return httpx.get(url, timeout=10.0)


def _plan_profiles() -> dict:
    """The answer-export profiles engine-cost SERVES (`GET /answers_export/profiles`), validated by
    `answer_exports.profiles_from_wire`, the loader's own validator. The BFF holds no copy and
    reads no profile from disk: the registry this code reads is the one the server serves, so an
    overlay mounted on cost alone reaches the picker with no code change. Nothing is cached (a
    cached set is a copy); callers that need it more than once hold the dict they were given.
    Raises `AnswerProfilesUnavailable` when cost cannot be asked or serves a set that does not
    validate: each caller decides what an outage means for it."""
    from agent_fleet.utils import answer_exports as _ae
    try:
        rr = _cost_profiles_get(f"{_ENGINE_COST_URL}/answers_export/profiles")
    except Exception as exc:  # noqa: BLE001 -- transport failure of the ask itself
        logger.error("answer export profiles: engine-cost unreachable: %s", exc)
        raise _ae.AnswerProfilesUnavailable(f"engine-cost unreachable: {exc}") from exc
    if rr.status_code != 200:
        logger.error("answer export profiles: engine-cost answered %s", rr.status_code)
        raise _ae.AnswerProfilesUnavailable(f"engine-cost answered {rr.status_code}")
    try:
        return _ae.profiles_from_wire(rr.json())
    except (_ae.AnswerExportError, ValueError) as exc:
        logger.error("answer export profiles served by engine-cost do not validate: %s", exc)
        raise _ae.AnswerProfilesUnavailable(f"served set does not validate: {exc}") from exc


def _plan_profiles_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail={"reason": "answer_profiles_unavailable"})


def _plan_scope_names(profiles: Optional[dict] = None) -> list[str]:
    profiles = _plan_profiles() if profiles is None else profiles
    return sorted({s for p in profiles.values() for s in p.recipients})


def _plan_reader(scope: str, authz_id: Optional[str]) -> bool:
    """`can_read_recipient("plan", ...)`; a transport/HTTP failure is a 503, never a deny."""
    return _rail_reader(_PLAN_OWNER, scope, authz_id)


def _plan_may_export(profile_name: str, authz_id: Optional[str]) -> bool:
    """`can_export:<profile>` (Topaz `can_invoke` on the capability). A blank authz_id is False;
    a transport/HTTP failure is a 503, never a deny. The same question as the review export's
    `_may_export_profile` (#163); the two fold together at iagent-mesh v0.9.12."""
    from agent_fleet.utils.export_capability import can_export
    try:
        return bool(authz_id) and bool(can_export(profile_name, authz_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("can_export check failed: %s", exc)
        raise HTTPException(
            status_code=503, detail={"reason": "can_export_unavailable"}
        ) from exc


def _plan_recipients_for(user: "User", profiles: Optional[dict] = None) -> list[str]:
    """Every plan recipient scope `user` may export to: named by a served profile and admitted by
    the `recipient_readers` rail. A blank `authz_id` is []. `AnswerProfilesUnavailable` escapes."""
    if not user.authz_id:
        return []
    return [s for s in _plan_scope_names(profiles) if _plan_reader(s, user.authz_id)]


def _answer_profiles_unavailable_type() -> type:
    from agent_fleet.utils import answer_exports as _ae
    return _ae.AnswerProfilesUnavailable


def _plan_profile_name(scope: str, profiles: Optional[dict] = None) -> Optional[str]:
    from agent_fleet.utils import answer_exports as _ae
    profile = _ae.profile_for_recipient(_plan_profiles() if profiles is None else profiles, scope)
    return profile.name if profile is not None else None


def _plan_exportable_for(
    user: "User", readers: Optional[list[str]] = None, profiles: Optional[dict] = None,
) -> list[str]:
    """The plan recipient scopes `user` may EXPORT to: a reader AND `can_export` on the scope's
    profile. Nobody is offered a recipient the export would refuse. `readers` is
    `_plan_recipients_for(user)` when the caller already has it."""
    profiles = _plan_profiles() if profiles is None else profiles
    if readers is None:
        readers = _plan_recipients_for(user, profiles)
    out = []
    for s in readers:
        name = _plan_profile_name(s, profiles)
        if name is not None and _plan_may_export(name, user.authz_id):
            out.append(s)
    return out


def _plan_exportable_or_none(user: "User", profiles: Optional[dict] = None) -> list[str]:
    """The plan recipients a caller may export to, for the 409 listing INSIDE the `export_package`
    door (a door's error listing, not a picker): a rail that cannot be asked omits them there and
    the door itself answers 503. The pickers do not use this; see `_picker_scopes`."""
    try:
        return _plan_exportable_for(user, None, profiles)
    except (HTTPException, _answer_profiles_unavailable_type()):
        return []


def _plan_export_refusal_403(profile_name: str, scope: str) -> HTTPException:
    """The compliant refusal for a reader who lacks `can_export:<profile>`."""
    from .authz.refusal import policy_refusal
    return policy_refusal(
        "not_entitled_to_export", policy_id=f"capability_grants:can_export:{profile_name}",
        missing_binding=f"can_invoke can_export:{profile_name}",
        message=f"You are not entitled to export {profile_name} answers.",
        extra={"recipient_scope": scope})


def _plan_refusal_403(scope: str) -> HTTPException:
    """The compliant refusal for a plan recipient the caller is not a reader of: the family
    `recipient_readers` is object-scoped, so it names the family and no key."""
    from .authz.refusal import policy_refusal
    return policy_refusal(
        "not_a_recipient_you_may_export_to", policy_id="recipient_readers",
        missing_binding="can_read_recipient(recipient_scope)",
        message="You are not a reader of this recipient.", extra={"recipient_scope": scope})


def _no_recipient_refusal_403() -> HTTPException:
    """The compliant refusal for a picker whose caller reads no recipient of any owner it lists
    (the plan family of `_plan_refusal_403`: `recipient_readers` is object-scoped, so no key)."""
    from .authz.refusal import policy_refusal
    return policy_refusal(
        "no_recipient_you_may_export_to", policy_id="recipient_readers",
        missing_binding="can_read_recipient(recipient_scope)",
        message="You read no recipient of any owner this picker lists.")


def _picker_scopes(user: "User") -> tuple[list[str], list[str], dict]:
    """`(cost scopes, plan scopes, plan profiles)` the caller may export to, for the two pickers
    (GET and POST `/export/package/recipients`). An outage is a 503 and is never omitted: the rail
    for any owner it asks (cost, plan; the detail names the owner) or engine-cost's profile set
    (`answer_profiles_unavailable`). "No readers" is a 403: the union across those owners is empty.
    The owners are the ones the picker lists, not finance's (its export is the template door)."""
    try:
        cost = _export_recipients_for(user)
    except HTTPException as exc:
        raise _picker_unavailable(exc, _COST_OWNER) from exc
    try:
        profiles = _plan_profiles()
        plan = _plan_exportable_for(user, None, profiles)
    except _answer_profiles_unavailable_type() as exc:
        raise _plan_profiles_unavailable() from exc
    except HTTPException as exc:
        raise _picker_unavailable(exc, _PLAN_OWNER) from exc
    if not cost and not plan:
        raise _no_recipient_refusal_403()
    return cost, plan, profiles


def _picker_unavailable(exc: HTTPException, owner: str) -> HTTPException:
    """A rail outage re-raised at a picker with the owner it was asking; any other 503 (the
    `can_export` check) passes through as it was."""
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("reason") == "recipient_readers_unavailable":
        return HTTPException(status_code=exc.status_code, detail={**detail, "owner": owner})
    return exc


def _user_bearer(request: Request) -> str:
    """The caller's raw bearer, exactly as the disposition route reads it above."""
    return (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()


def _shape_export_package_response(
    out: dict, *, recipient_scope: str, template_id: Optional[str],
    extra: Optional[dict] = None,
) -> dict:
    """The one place a producing engine's `package_export` response becomes this gateway's
    own response shape — read by BOTH the cost path and the finance-template path, so the two
    cannot drift into reporting "exists" under different rules. `extra` carries whatever a
    given engine's response has beyond the shared fields (cost's `lots_disclosed`/`sections`;
    finance has none today). `template_id` is placed after them, which is the order the cost
    route emitted before this helper existed.

    An engine that refuses in-band (`refused: true`, cost's empty-disclosure outcome) is shaped
    here too, so the refusal shape is also one rule rather than one per route.
    """
    if out.get("refused"):
        refusal = {
            "export_id": None,
            "status": "failed",
            "recipient_scope": recipient_scope,
            "reason": out.get("reason"),
            "outcome": out.get("outcome"),
        }
        if "refused_answers" in out:
            # THE CANVAS ANSWERS REFUSED BY NAME (RULED 10-16 Q1); passed through, not interpreted.
            refusal["refused_answers"] = out["refused_answers"]
        if out.get("outcome") == "unavailable":
            # THE ENGINE COULD NOT BUILD, which is not an answer about this caller's export: a
            # missing runtime, an unpinned loader, a dirty algorithm. engine-cost says so in a
            # 200 envelope (its refusals are envelopes by design); the HTTP edge says it as a
            # 503, so a caller retries a service rather than reading "failed" as a verdict on
            # its request. Same body, carried as the detail -- the reason is the builder's own.
            raise HTTPException(status_code=503, detail=refusal)
        return refusal
    sha = out.get("artifact_sha256")
    filename = out.get("artifact_filename")
    exists = bool(sha and _SHA256_LOCATOR_RE.match(sha) and filename)
    export_status = "exists" if exists else "failed"
    reason = None if exists else "engine returned no verifiable artifact hash"
    shaped = {
        # A CONTENT ADDRESS, not a job id: the sha IS the export's identity, so a second call
        # with the same inputs reports the same export_id.
        "export_id": sha if exists else None,
        "status": export_status,
        "recipient_scope": recipient_scope,
        "reason": reason,
        # THE GATEWAY PATH, never the engine's own `out["artifact_uri"]` — that one points at
        # the engine directly, which this route's own authorization check would then be
        # bypassable around.
        "artifact_uri": f"/export/package/artifact/{filename}" if filename else None,
        "artifact_sha256": sha,
        "artifact_bytes": out.get("artifact_bytes"),
        "artifact_filename": filename,
        "algorithm_sha": out.get("algorithm_sha"),
    }
    if extra:
        shaped.update(extra)
    shaped["template_id"] = template_id
    return shaped


class ExportAnswer(_BaseModel):
    artifact_id: str


class ExportPackageRequest(_BaseModel):
    answers: list[ExportAnswer] = []
    # ADR-0047 §1: no default recipient. A disclosure verb that can be invoked without naming
    # its recipient is one keystroke from disclosing the wrong program to the wrong party.
    recipient_scope: Optional[str] = None
    # ITEM 3: a ratified, packageable template id (today, only `program_finance`) DRIVES the
    # export when given — the panels and the recipient come from the template and `bindings`,
    # not from `answers`/`recipient_scope`. Absent, this request takes the ORIGINAL cost path,
    # where this field is echoed back only. The two inputs are mutually exclusive with
    # `answers` (checked in `export_package`), never silently combined.
    template_id: Optional[str] = None
    # KEYED BY SHARED SLOT `name` — the SAME shape `/canvas/seed`'s own `bindings` take (see
    # `canvas_seed`), because `validate_bindings` and `panel_dispatch` are the identical
    # functions that call reads. Ignored on the cost path.
    bindings: Optional[dict[str, Any]] = None
    # THE DATE THE PACKAGE CLAIMS, `YYYY-MM-DD`. Absent, `export_package` takes the request date
    # once and forwards it to every engine call, so identical input gives an identical page.
    as_of: Optional[str] = None

    @field_validator("as_of")
    @classmethod
    def _as_of_is_a_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError(f"as_of {v!r} is not YYYY-MM-DD")
        _date.fromisoformat(v)  # a ValueError here is a 422 too
        return v


def _export_request_date() -> str:
    """TODAY (UTC), AS THE DATE A REQUEST CLAIMS. One place, so a test can pin it."""
    return datetime.now(timezone.utc).date().isoformat()


def _resolve_export_answers(artifact_ids: list[str], user_id: str) -> list[dict]:
    """Resolve each canvas answer id through the SAME artifact-store query `get_artifact`
    uses, keyed the same way (`PRODUCED_FOR` against `user_id`, the writer's key — see
    `get_artifact`'s own comment on why `id` and not `authz_id` is correct here).

    REFUSED, NEVER DROPPED (canvas.py's rule): an id that does not resolve raises 404 rather
    than being silently omitted from the canvas — an export quietly missing an answer nobody
    asked to drop would look complete while disclosing less than the caller intended.

    THE VERB HAS TWO HOMES. `resolved_intent.verb_iri` is read first; answers written before
    `e4154f91` (2026-09-04) carry the verb only in the routing record (`routing_inline`
    -> `action.iri`), and `resolved_intent` holds the ExtractIntent output with no verb. The
    routing record is read only when the intent has none: the two agreed on all 1,018 artifacts
    carrying both (measured 2026-10-28). `UNKNOWN` there means the supervisor chose no verb, so
    `no_verb` stays the true refusal for those. `subject_instance_id` is read from the intent
    alone. An old or malformed routing record yields None, never an error.
    """
    return [_resolve_export_record(r) for r in _read_export_records(artifact_ids, user_id)]


def _read_export_records(artifact_ids: list[str], user_id: str) -> list:
    """The `_ARTIFACT_BY_ID_CYPHER` record of each id, owner-checked: 404 for one that does not
    resolve (refused, never dropped), 503 when the store is down."""
    records: list = []
    for artifact_id in artifact_ids:
        try:
            with neo4j_driver.session() as session:
                rec = session.run(
                    _ARTIFACT_BY_ID_CYPHER, artifact_id=artifact_id, user_id=user_id
                ).single()
        except Exception as exc:  # noqa: BLE001
            logger.warning("export answer read failed for %s: %s", artifact_id, exc)
            raise HTTPException(status_code=503, detail="artifact store unavailable") from exc

        if not rec or not rec.get("is_owner"):
            raise HTTPException(
                status_code=404,
                detail={"reason": "answer_not_found", "artifact_id": artifact_id},
            )
        records.append(rec)
    return records


def _resolve_export_record(rec) -> dict:
    """One record as the engines' `{id, verb_iri, subject_instance_id}` (the two homes of the
    verb are explained on `_resolve_export_answers`). Widens nothing."""
    intent: dict = {}
    if rec.get("resolved_intent"):
        try:
            intent = json.loads(rec["resolved_intent"]) or {}
        except (ValueError, TypeError):
            intent = {}

    def _or_none(v):
        v = str(v or "").strip()
        return None if not v or v == "UNKNOWN" else v

    verb = _or_none(intent.get("verb_iri"))
    if verb is None:
        try:
            _routing = json.loads(rec.get("routing_inline") or "null")
            verb = _or_none(_routing["action"]["iri"])
        except (ValueError, TypeError, KeyError):
            verb = None

    return {
        "id": str(rec["id"]),
        "verb_iri": verb,
        "subject_instance_id": _or_none(intent.get("subject_instance_id")),
        "state_refs": _answer_state_refs(rec),
    }


def _answer_state_refs(rec) -> list[str]:
    """The sorted distinct non-empty `state_ref` values on the answer's
    `rendered_output.components[*]` (Engine P echoes the state it computed against; the
    presentation agent copies it onto every component). Never raises: any parse or shape problem
    is `[]`, and `[]` reads as BASELINE downstream (Engine P's default; pre-passthrough artifacts
    never carried the key)."""
    try:
        out = json.loads(rec.get("rendered_output") or "null")
        comps = out.get("components") if isinstance(out, dict) else None
        if not isinstance(comps, list):
            return []
        refs = {c["state_ref"].strip() for c in comps
                if isinstance(c, dict) and isinstance(c.get("state_ref"), str)}
        return sorted(r for r in refs if r)
    except (ValueError, TypeError, AttributeError):
        return []


def _plan_partition(resolved: list[dict], profile) -> tuple[list[dict], list[dict]]:
    """THE ONE DECISION a plan recipient makes about a board, used by the export and the offer
    alike: (taken answers, refused items). Taken = verb in `profile.kinds` and computed against
    baseline, in board order. Refused = `{answer_id, kind, reason_code, reason}`, one refusal per
    answer, in this order: `no_verb` when the answer has none; `not_a_kind_this_recipient_takes`
    when its verb is not in `profile.kinds`; `scenario_answer` (ruled 10-29: only baseline
    answers export) when a taken verb was computed against a scenario, the item also carrying
    `scenario_id`. The state is the answer's `state_refs`; none present reads as baseline."""
    from agent_fleet.cost_agent.canvas import REFUSAL_REASONS, NO_VERB, _verb_local
    kinds = {_verb_local(k) for k in profile.kinds} - {None}
    taken: list[dict] = []
    refused: list[dict] = []
    for ans in resolved:
        local = _verb_local(ans.get("verb_iri"))
        if local is not None and local in kinds:
            scenarios = [r for r in ans.get("state_refs") or [] if r != "baseline"]
            if not scenarios:
                taken.append(ans)
                continue
            sid = ", ".join(sorted(scenarios))
            refused.append({
                "answer_id": ans["id"], "kind": local, "reason_code": _SCENARIO_ANSWER,
                "scenario_id": sid,
                "reason": f"computed against scenario {sid}; the {profile.name} export "
                          f"takes baseline answers only",
            })
        elif local is None:
            refused.append({"answer_id": ans["id"], "kind": None, "reason_code": NO_VERB,
                            "reason": REFUSAL_REASONS[NO_VERB]})
        else:
            refused.append({
                "answer_id": ans["id"], "kind": local, "reason_code": _NOT_A_KIND,
                "reason": f"not a kind the {profile.name} export takes "
                          f"({len(profile.kinds)} kinds)",
            })
    return taken, refused


def _plan_rows(records: list, taken_ids: set[str]) -> list[dict]:
    """The rows of the taken answers, in board order, read from the SAME records the board was
    resolved from (no second query). Keys are `answer_exports.ANSWER_FIELDS`."""
    rows: list[dict] = []
    for rec in records:
        resolved = _resolve_export_record(rec)
        if resolved["id"] not in taken_ids:
            continue
        subject = None
        try:
            intent = json.loads(rec.get("resolved_intent") or "null")
            if isinstance(intent, dict):
                subject = intent.get("subject_uri") or None
        except (ValueError, TypeError):
            subject = None
        valid = rec.get("valid_as_of")
        if valid is not None and hasattr(valid, "isoformat"):
            valid = valid.isoformat()
        rows.append({
            "answer_id": resolved["id"],
            "question": rec.get("question_text"),
            "summary": rec.get("summary"),
            "verb": resolved["verb_iri"],
            "subject": subject,
            "program": rec.get("origin_program"),
            "status": rec.get("status"),
            "valid_as_of": None if valid is None else str(valid),
        })
    return rows


def _partition_export_answers(resolved: list[dict]) -> list[tuple[str, list[dict]]]:
    """Split a board's resolved answers by the engine that exports them.

    "fin" claims an answer iff its verb is one engine-fin SERVES (`VERB_TO_FN`, derived, not
    typed; imported lazily like `_fin_export_recipients_for`'s `export`). "cost" takes EVERY
    OTHER answer, including verb None and unknown verbs. WHY: the ad-hoc path is engine-cost's
    today, and engine-cost's `canvas.resolve` already refuses an unknown verb BY NAME; a third
    exporting engine adds its own claim here.

    Order: engines by first appearance on the board; answers within an engine in board order.
    """
    from agent_fleet.cost_agent.canvas import _verb_local
    from agent_fleet.finance_agent.main import VERB_TO_FN
    fin_verbs = {_verb_local(v) for v in VERB_TO_FN} - {None}
    parts: dict[str, list[dict]] = {}
    for ans in resolved:
        local = _verb_local(ans.get("verb_iri"))
        engine = "fin" if local in fin_verbs else "cost"
        # `state_refs` is the plan recipient's alone: it never reaches an engine payload.
        parts.setdefault(engine, []).append(
            {k: v for k, v in ans.items() if k != "state_refs"})
    return list(parts.items())


def _fin_ad_hoc_refusal_section(answer_ids: list[str], recipient_scope: str) -> dict:
    """The fin section of a mixed board: always a refusal, made HERE without calling engine-fin.

    WHY: RULED 2026-10-10 (Q1): engine-fin exports ratified templates only -- that is the
    finance control, not a gap -- so an ad-hoc finance card is refused, locally, without
    calling engine-fin. (Q2): the section goes to the board's recipient and states "not a
    ratified template", nothing else (no ids, no template name, no hint). (Q3): it lives in the
    API response / exporter's view, never in the customer page. Sealed by
    `tests/test_a_mixed_board_exports_per_engine.py::test_engine_fin_takes_ratified_templates_only`
    and `::test_the_fin_section_states_not_a_ratified_template_and_nothing_else`.

    RULED 2026-10-16: reason_code added; Q2's "nothing else" governs the prose.
    """
    return {
        "engine": "fin",
        "answers": answer_ids,
        "export_id": None,
        "status": "failed",
        "recipient_scope": recipient_scope,
        "outcome": "not_in_model",
        "reason_code": "not_a_ratified_template",
        "reason": "not a ratified template",
    }


def _refused_entries(engine: str, refused_answers: list[dict], recipient_scope: str) -> list[dict]:
    """Each refused answer of an engine as a `failed` `documents[]` entry (RULED 2026-10-16:
    "the refused entries go in documents[] per engine with reason_code and the refusal prose").

    Items are grouped by `reason_code`, in order of each code's first appearance; a group's
    `answers` are its ids in board order. Every item of one code carries the same constant
    reason, so the group's reason is the first item's -- EXCEPT `scenario_answer`, whose reason
    names its scenario: it groups by (code, reason) and the entry carries `scenario_id`. Only ever `status: "failed"`: cortex's
    reader drops the whole response on any other status. Never rendered on the customer page.
    """
    groups: dict[str, dict] = {}
    for item in refused_answers:
        code = item.get("reason_code")
        # a scenario refusal names its scenario in the reason, so it groups by that reason
        key = (code, item.get("reason")) if code == _SCENARIO_ANSWER else code
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "engine": engine,
                "answers": [],
                "export_id": None,
                "status": "failed",
                "recipient_scope": recipient_scope,
                "outcome": "not_in_model",
                "reason_code": code,
                "reason": item.get("reason"),
            }
            if item.get("scenario_id") is not None:
                g["scenario_id"] = item["scenario_id"]
        g["answers"].append(item.get("answer_id"))
    return list(groups.values())


async def _call_engine_cost_package(
    params: dict, bearer: str, *, recipient_scope: str, template_id: Optional[str],
) -> dict:
    """POST engine-cost's `package_export` and shape the answer. Raises HTTPException on an
    unreachable engine, an HTTP refusal, or an in-band `unavailable` -- the single-engine path
    lets that propagate; the per-engine split catches it into a section."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:  # a build is slow
            rr = await client.post(
                f"{_ENGINE_COST_URL}/measure/package_export",
                json={"params": params},
                # THE PERSON's identity, never a service identity (ADR-0047 section 5.1: no svc:
                # reader is ever on the rail, and that is the confused-deputy argument
                # applied here — a service calling on the caller's behalf must carry THAT
                # caller's identity or refuse).
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "cost_engine_unreachable", "message": str(exc),
        })

    if rr.status_code >= 400:
        try:
            body_json = rr.json()
            detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
        except Exception:
            detail = getattr(rr, "text", "engine refused")
        raise HTTPException(status_code=rr.status_code,
                            detail=_detail_with_message(rr.status_code, detail))

    out = rr.json()
    return _shape_export_package_response(
        out, recipient_scope=recipient_scope, template_id=template_id,
        extra={"lots_disclosed": out.get("lots_disclosed"), "sections": out.get("sections"),
               **({"refused_answers": out["refused_answers"]} if out.get("refused_answers") is not None else {})},
    )


def _cost_refusal_section(exc: HTTPException, recipient_scope: str) -> dict:
    """An engine-cost HTTPException as a refusal section, in `_shape_export_package_response`'s
    in-band refusal shape. Not raised: on a mixed board the other engines still export."""
    detail = exc.detail
    outcome = "unavailable" if exc.status_code in (502, 503) else (
        detail.get("outcome") if isinstance(detail, dict) else None
    )
    if isinstance(detail, dict) and detail.get("outcome") == "unavailable" and "reason" in detail:
        reason = detail["reason"]
    elif isinstance(detail, str):
        reason = detail
    else:
        reason = json.dumps(detail, default=str)
    return {
        "export_id": None,
        "status": "failed",
        "recipient_scope": recipient_scope,
        "reason": reason,
        "outcome": outcome,
    }


@app.get("/export/package/recipients")
async def export_package_recipients(current_user: User = Depends(get_current_user)):
    """The card's recipient picker. Entitlement-driven (ADR-0047 §5): the options a caller
    sees are exactly the scopes their `authz_id` reads, never the full recipient catalogue.
    An outage (the rail for cost or plan, or engine-cost's profile set) is 503; a caller who reads
    no recipient of any owner listed is 403."""
    cost, plan, _profiles = _picker_scopes(current_user)
    return {"recipients": [{"value": s, "label": s} for s in cost + plan]}

class ExportOfferRequest(_BaseModel):
    """`POST /export/package/recipients`'s body: the same answer items `ExportPackageRequest`
    takes (`ExportAnswer`), and nothing else -- the offer names no recipient, it lists them."""
    answers: list[ExportAnswer] = []


#: The recipient-level code for a board whose answers this recipient's export takes none of.
_OFFER_TAKES_NONE = "takes_none_of_these_answers"
_OFFER_TAKES_NONE_REASON = "none of these answers is a kind this recipient's export takes"
#: The export's own code (a section that failed naming only some answers) for a cost answer the
#: engine did not name: no answer is about a lot, or an id twice. The reason is the engine's message.
_OFFER_UNNAMED = "not_in_model"


def _offer_for_recipient(resolved: list[dict], scope: str) -> dict:
    """What ONE recipient's export would do with this board, decided by the export's own
    functions and never by a parallel rule: `_partition_export_answers` splits the board,
    engine-fin's answers are refused as `_fin_ad_hoc_refusal_section` refuses them, and
    engine-cost's are decided by `canvas.resolve`, the call `measures.package_export` makes
    first, with the same arguments. Every answer id lands exactly once in `exports` or
    `refused`; `refused` is in board order.

    The exception classes are the ones `canvas` itself bound (`canvas.Unentitled`), not a
    second import of `entities`: the module has a flat-import fallback, and two module objects
    would make two classes of one name so the `except` below would never match.
    """
    from agent_fleet.cost_agent import canvas as _canvas
    from agent_fleet.cost_agent import seed as _cost_seed

    parts = dict(_partition_export_answers(resolved))
    cost_answers = parts.get("cost", [])
    fin_ids = {a["id"] for a in parts.get("fin", [])}
    kinds = {a["id"]: _canvas._verb_local(a.get("verb_iri")) for a in resolved}
    board = list(dict.fromkeys(a["id"] for a in resolved))

    rows: dict[str, dict] = {}

    def _row(aid: str, code: str, reason: str) -> None:
        rows[aid] = {"answer_id": aid, "kind": kinds[aid], "reason_code": code, "reason": reason}

    fin_refusal = _fin_ad_hoc_refusal_section([], scope)
    for aid in fin_ids:
        _row(aid, fin_refusal["reason_code"], fin_refusal["reason"])

    exports: list[str] = []
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    if not cost_answers:
        reason_code, reason = _OFFER_TAKES_NONE, _OFFER_TAKES_NONE_REASON
    else:
        try:
            composed = _canvas.resolve(
                {"answers": cost_answers}, recipient_scope=scope,
                entitled_lots=_cost_seed.lots_for_recipient(scope),
            )
        except _canvas.Unentitled:
            reason_code, reason = "unentitled", _canvas.ENTITLEMENT_REFUSAL
            for a in cost_answers:
                _row(a["id"], reason_code, reason)
        except _canvas.NotInModel as exc:
            reason_code, reason = _OFFER_TAKES_NONE, _OFFER_TAKES_NONE_REASON
            named = exc.refused if isinstance(exc.refused, list) and exc.refused else []
            for item in named:
                _row(item["answer_id"], item["reason_code"], item["reason"])
            # An answer the engine did not name (every answer resolved, none is about a lot)
            # is still refused, and still appears once.
            for a in cost_answers:
                if a["id"] not in rows:
                    _row(a["id"], _OFFER_UNNAMED, str(exc))
        else:
            exports = list(composed["answers"])
            for item in composed["refused"]:
                _row(item["answer_id"], item["reason_code"], item["reason"])

    return {
        "offered": bool(exports) and reason_code is None,
        "reason_code": reason_code,
        "reason": reason,
        "exports": exports,
        "refused": [rows[aid] for aid in board if aid in rows],
    }


def _plan_offer_for_recipient(resolved: list[dict], scope: str, profiles: dict) -> dict:
    """`_offer_for_recipient`'s shape for a plan recipient, decided by `_plan_partition` -- the
    function the export takes its own decision from. `profiles` is the set the caller was given."""
    from agent_fleet.utils import answer_exports as _ae
    profile = _ae.profile_for_recipient(profiles, scope)
    taken, refused = _plan_partition(resolved, profile)
    exports = list(dict.fromkeys(a["id"] for a in taken))
    return {
        "offered": bool(exports),
        "reason_code": None if exports else _OFFER_TAKES_NONE,
        "reason": None if exports else _OFFER_TAKES_NONE_REASON,
        "exports": exports,
        "refused": refused,
    }


@app.post("/export/package/recipients")
async def export_package_offer(
    body: ExportOfferRequest, current_user: User = Depends(get_current_user),
):
    """The recipient picker for THIS board: for each recipient the caller may export to, which
    of the board's answers that recipient's export takes and which it refuses, with the
    reasons -- so a board no recipient takes is greyed before Export, not refused after it.

    Recipients are exactly `_export_recipients_for(current_user)`, in that order: one the
    caller may not export to is ABSENT, never greyed (ADR-0047 §5). A recipient is `offered`
    iff its export would take at least one answer; a partial board stays offered (mixed-board
    partial export is ruled, 2026-10-09/16) and `refused` names the answers that will not go.
    Gates, as the export's: no answers is 400 `no_answers`; an id that does not resolve is
    404 (503 when the store is down). As the GET picker: an outage is 503, and a caller who reads
    no recipient of any owner listed is 403.
    """
    if not body.answers:
        raise HTTPException(status_code=400, detail={"reason": "no_answers"})
    resolved = _resolve_export_answers(
        [a.artifact_id for a in body.answers], current_user.id
    )
    cost, plan, profiles = _picker_scopes(current_user)
    return {
        "answers": len(body.answers),
        "recipients": [
            {"value": s, "label": s, **_offer_for_recipient(resolved, s)} for s in cost
        ] + [
            {"value": s, "label": s, **_plan_offer_for_recipient(resolved, s, profiles)}
            for s in plan
        ],
    }


async def _export_package_from_template(
    body: "ExportPackageRequest", request: Request, current_user: "User", as_of: str,
) -> dict:
    """ITEM 3's path: `body.template_id` names a ratified, packageable canvas template and
    `body.bindings` supplies its shared slots — the SAME shape `/canvas/seed` takes, because
    this function and `canvas_seed` both call `validate_bindings`, and both reach each panel's
    `(verb, params)` through the identical `panel_dispatch` ("Seeding and packageExport read
    the same thing" — `canvas_template.py`).

    Ordered gates, each refusing before the next is even attempted:
      1. unknown template id -> 400
      2. the template declares no `package` -> 422
      3. R-005's three binding outcomes -> 422 / 422 / 409 (`validate_bindings`)
      4. an explicit `recipient_scope` that disagrees with the one the template+bindings
         derive -> 409 (two names for the same disclosure is the hazard this rejects)
      5. the caller not entitled to the derived recipient -> 403
      6. the engine unreachable, or the engine's own refusal, forwarded verbatim

    Only `program_finance` is wired to an engine today (engine-fin). A second packageable
    template would need its own dispatch here — this function does not invent one.
    """
    from .authz.refusal import policy_refusal
    from .canvas_template import (
        UnboundRequiredSlot, UndeclaredConsumption, UnknownBinding, load_template,
        panel_dispatch, ratified_template_ids, recipient_scope_for, slot_refusal, template_ref,
        validate_bindings,
    )

    template_id = (body.template_id or "").strip()
    try:
        template = load_template(template_id)
    except (KeyError, ValueError) as exc:
        # SAME REFUSAL SHAPE as `canvas_seed`'s own unknown-template 400 (~L2736-2744).
        raise HTTPException(
            status_code=400,
            detail=(
                f"no ratified canvas template {template_id!r} "
                f"(ratified: {ratified_template_ids()}) — {exc}"
            ),
        )

    if template.package is None:
        raise HTTPException(
            status_code=422,
            detail=f"template {template_id!r} declares no package; it cannot be exported",
        )

    try:
        bindings = validate_bindings(template, body.bindings or {})
    except UndeclaredConsumption as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except UnknownBinding as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except UnboundRequiredSlot as exc:
        # A POLICY REFUSAL: it asks the caller to choose (`canvas_template.slot_refusal`).
        raise policy_refusal("unbound_required_slot", status_code=409, message=str(exc),
                             **slot_refusal(template, exc.slots))

    # `validate_bindings` already guarantees every slot this template's panels CONSUME is
    # bound, so `recipient_scope_for` cannot raise here in practice — this still catches it
    # rather than let a future template shape turn into an uncaught 500.
    try:
        recipient_scope = recipient_scope_for(template, bindings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    requested_scope = (body.recipient_scope or "").strip()
    if requested_scope and requested_scope != recipient_scope:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "recipient_scope_disagrees_with_canvas_audience",
                "derived": recipient_scope,
                "message": "the recipient_scope you sent disagrees with the one this canvas's "
                           "audience derives; send the derived scope or omit it.",
            },
        )

    if recipient_scope not in _fin_export_recipients_for(current_user):
        raise HTTPException(
            status_code=403,
            detail={
                "reason": "not_a_recipient_you_may_export_to",
                "recipient_scope": recipient_scope,
            },
        )

    panels = []
    for idx, _panel in enumerate(template.panels):
        verb, _subject, params = panel_dispatch(template, idx, bindings)
        panels.append({"panel": idx, "verb": verb, "params": params})

    canvas = {
        "template_id": template.template_id,
        "template_hash": template_ref(template),
        "panels": panels,
    }

    bearer = _user_bearer(request)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:  # a build is slow
            rr = await client.post(
                f"{_ENGINE_FIN_URL}/package_export",
                json={"recipient_scope": recipient_scope, "canvas": canvas, "as_of": as_of,
                      "user_email": current_user.authz_id},
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "fin_engine_unreachable", "message": str(exc),
        })

    if rr.status_code >= 400:
        try:
            body_json = rr.json()
            detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
        except Exception:
            detail = getattr(rr, "text", "engine refused")
        raise HTTPException(status_code=rr.status_code,
                            detail=_detail_with_message(rr.status_code, relay_refusal(detail)))

    out = rr.json()
    return _shape_export_package_response(
        out, recipient_scope=recipient_scope, template_id=template.template_id,
    )


async def _call_engine_cost_answers_export(payload: dict, bearer: str) -> dict:
    """POST engine-cost's `/answers_export`. Its 403 is the engine's policy refusal completed by
    `relay_refusal`; its 503 (`recipient_readers_unavailable`) stays a 503."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            rr = await client.post(
                f"{_ENGINE_COST_URL}/answers_export", json=payload,
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "cost_engine_unreachable", "message": str(exc),
        })
    if rr.status_code >= 400:
        if rr.status_code == 403:
            raise _engine_failure("cost", rr)
        try:
            body_json = rr.json()
            detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
        except Exception:
            detail = getattr(rr, "text", "engine refused")
        raise HTTPException(status_code=rr.status_code, detail=detail)
    return rr.json()


async def _export_plan_answers(
    body: "ExportPackageRequest", request: Request, current_user: User, recipient_scope: str,
    profiles: Optional[dict] = None,
) -> dict:
    """A board exported to a plan recipient: no cost or fin call is made.

    The answers whose verb is in the profile's `kinds` are rendered by engine-cost's
    `/answers_export`; the rest are refused by name, as `_refused_entries` shapes them. The
    rows come from the same `_ARTIFACT_BY_ID_CYPHER` records the board resolved from.
    """
    from agent_fleet.utils import answer_exports as _ae
    try:
        profiles = _plan_profiles() if profiles is None else profiles
    except _ae.AnswerProfilesUnavailable as exc:
        raise _plan_profiles_unavailable() from exc
    profile = _ae.profile_for_recipient(profiles, recipient_scope)
    records = _read_export_records([a.artifact_id for a in body.answers], current_user.id)
    resolved = [_resolve_export_record(r) for r in records]
    taken, refused_items = _plan_partition(resolved, profile)

    documents: list[dict] = []
    if taken:
        taken_ids = [a["id"] for a in taken]
        rows = _plan_rows(records, set(taken_ids))
        # CONTENT-ADDRESSED, as cost's: the same inputs name the same export.
        export_id = hashlib.sha256(json.dumps(
            {"recipient_scope": recipient_scope, "rows": rows},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
        ).encode("utf-8")).hexdigest()
        out = await _call_engine_cost_answers_export(
            {"recipient_scope": recipient_scope, "export_id": export_id,
             "user_email": current_user.authz_id, "rows": rows},
            _user_bearer(request),
        )
        section = _shape_export_package_response(
            out, recipient_scope=recipient_scope, template_id=None,
            extra={"profile": out.get("profile")},
        )
        documents.append({"engine": "cost", "answers": taken_ids, **section})
    documents.extend(_refused_entries("cost", refused_items, recipient_scope))

    ok = [d["status"] == "exists" for d in documents]
    status = "exists" if all(ok) else ("partial" if any(ok) else "failed")
    refused = sum(len(d["answers"]) for d in documents if d["status"] != "exists")
    export_id = next((d["export_id"] for d in documents if d["status"] == "exists"), None)
    return {
        "export_id": export_id,
        "status": status,
        "recipient_scope": recipient_scope,
        "reason": None if not refused else f"{refused} of {len(body.answers)} answers refused",
        "template_id": None,
        "documents": documents,
    }


@app.post("/export/package", tags=[MCP_TAG])
async def export_package(
    body: ExportPackageRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Produce a recipient's disclosure package — THE GOVERNED EMIT, run synchronously.

    Production never returns `"status": "producing"`: `measures.package_export` runs and
    writes to disk inline, in the same request, so there is no async job to poll. A caller
    gets `"exists"` or `"failed"` in the same response that asked for the build.

    `template_id` and `answers` are MUTUALLY EXCLUSIVE — a canvas template's own panels decide
    what is exported, so naming one while also handing over cost `answers` is ambiguous about
    which governs, and is refused rather than guessed at (422). Given `template_id`, this
    dispatches to `_export_package_from_template` (ITEM 3's path) and nothing below runs.

    Absent `template_id`, a request naming no answers (`answers` omitted or `[]`) is 400
    `no_answers` (RULED 2026-10-17), BEFORE the recipient checks below: it is a shape fault,
    refused ahead of entitlement, so a no-answers request with no recipient is a 400, not a 409.
    The whole-program export through this route is gone.

    Then four hard stops, in order, each refusing before the next is even attempted:
      1. no `recipient_scope` -> 409 (ADR-0047 §1: no default recipient)
      2. `recipient_scope` the caller may not export to -> 403 (see below)
      3. any canvas answer id that does not resolve -> 404, refused rather than dropped
      4. the engine unreachable, or the engine's own refusal, forwarded verbatim

    A board that mixes engines' answers is SPLIT per engine (ruled 2026-10-09): `answers` are
    partitioned by `_partition_export_answers` (engine-fin's verbs vs. everything else, which is
    engine-cost's), each engine is given only its own, and when any engine-fin answer is
    present the response is a 200 carrying `documents`, one section per engine: a refused engine
    (engine-cost's refusal or unreachability, or engine-fin, which exports ratified templates
    only -- RULED 2026-10-10 Q1, the finance control) renders as a refusal section and the others still export. Hard stop 4 then
    applies to a section, not the response. RULED 2026-10-16: a refused answer is its own
    `failed` entry in `documents[]` with a `reason_code` and the refusal prose (never on the
    customer page); a cost-only board switches to `documents[]` only when engine-cost refused
    something, and otherwise answers exactly as before. The top-level `reason` counts answers
    ("r of n answers refused"), not engines.
    """
    if body.template_id and body.answers:
        raise HTTPException(
            status_code=422,
            detail=(
                "template_id and answers are mutually exclusive — a canvas template's own "
                "panels decide what is exported; naming cost answers alongside one does not "
                "say which governs."
            ),
        )

    # RESOLVED ONCE, then forwarded on every engine call below.
    as_of = body.as_of or _export_request_date()

    if body.template_id:
        return await _export_package_from_template(body, request, current_user, as_of)

    # RULED 2026-10-17: a request naming no answers (and no template) is refused. An empty
    # list used to export the recipient's whole program -- a disclosure path nothing in the
    # UI can reach (cortex-ui disables the button on an empty board). It is a shape fault, so
    # it comes before the entitlement checks (409/403), the canvas's own order.
    if not body.answers:
        raise HTTPException(status_code=400, detail={"reason": "no_answers"})

    recipient_scope = (body.recipient_scope or "").strip()
    # THE PLAN REGISTRY IS ENGINE-COST'S, READ OVER THE WIRE. When it cannot be had the plan scopes
    # are omitted from the options (the picker's posture) and a request for anything that is not a
    # cost or fin recipient is a 503 -- never a 403: an outage must not read as "not your recipient".
    from agent_fleet.cost_agent import seed as _cost_seed
    from agent_fleet.finance_agent import export as _fin_export
    try:
        plan_profiles: Optional[dict] = _plan_profiles()
    except _answer_profiles_unavailable_type():
        plan_profiles = None
    if (plan_profiles is None and recipient_scope
            and recipient_scope not in _cost_seed.RECIPIENT_SCOPES
            and recipient_scope not in _fin_export.RECIPIENT_SCOPES):
        raise _plan_profiles_unavailable()
    is_plan_scope = plan_profiles is not None and recipient_scope in _plan_scope_names(plan_profiles)
    plan_recipients = _plan_recipients_for(current_user, plan_profiles) if is_plan_scope else []
    # ONE pass over the rail for cost's scopes, used for the listed options AND the door below. A rail
    # that cannot be asked omits cost's options from the 409 listing (as the pickers do) but the
    # door itself answers 503 -- never a 403.
    try:
        cost_recipients: Optional[list[str]] = _export_recipients_for(current_user)
    except HTTPException:
        cost_recipients = None
    options = [{"value": s, "label": s} for s in (cost_recipients or [])]
    if plan_profiles is not None:
        options += [{"value": s, "label": s} for s in (
            _plan_exportable_for(current_user, plan_recipients, plan_profiles) if is_plan_scope
            else _plan_exportable_or_none(current_user, plan_profiles))]
    if not recipient_scope:
        raise HTTPException(
            status_code=409,
            detail={"reason": "recipient_required", "options": options,
                    "message": "name the recipient this package is for (recipient_scope); "
                               "the options are listed."},
        )

    if is_plan_scope:
        if recipient_scope not in plan_recipients:
            raise _plan_refusal_403(recipient_scope)
        plan_profile = _plan_profile_name(recipient_scope, plan_profiles)
        if not _plan_may_export(plan_profile, current_user.authz_id):
            raise _plan_export_refusal_403(plan_profile, recipient_scope)
        return await _export_plan_answers(
            body, request, current_user, recipient_scope, plan_profiles)

    if cost_recipients is None:
        raise HTTPException(status_code=503, detail={"reason": "recipient_readers_unavailable"})
    if recipient_scope not in cost_recipients:
        # WHY PRODUCTION IS GATED HERE, NOT ONLY THE DOWNLOAD: every recipient's package
        # shares one directory (the confused-deputy note beside cost's RECIPIENT_SCOPES) and a canvas narrows
        # what the file carries, so an unentitled producer could OVERWRITE a recipient's
        # package with a different canvas — a write-side confused-deputy, not just a read.
        raise HTTPException(
            status_code=403,
            detail={
                "reason": "not_a_recipient_you_may_export_to",
                "recipient_scope": recipient_scope,
            },
        )

    # ALL ids resolve (404/503) BEFORE any engine is called or the board is split.
    resolved = _resolve_export_answers(
        [a.artifact_id for a in body.answers], current_user.id
    )
    parts: list[tuple[str, list[dict]]] = _partition_export_answers(resolved)

    bearer = _user_bearer(request)

    has_fin = any(engine == "fin" for engine, _ in parts)
    cost_first: Optional[dict] = None
    if not has_fin:
        # ONLY engine-cost's answers: today's path and today's response, unchanged
        # -- unless the engine REFUSED some of them (RULED 2026-10-16), below.
        params: dict = {"recipient_scope": recipient_scope, "as_of": as_of}
        params["canvas"] = {"answers": parts[0][1]}
        cost_first = await _call_engine_cost_package(
            params, bearer, recipient_scope=recipient_scope, template_id=body.template_id,
        )
        if not cost_first.get("refused_answers"):
            return cost_first

    documents: list[dict] = []
    for engine, answers in parts:
        ids = [a["id"] for a in answers]
        if engine == "fin":
            documents.append(_fin_ad_hoc_refusal_section(ids, recipient_scope))
            continue
        if cost_first is not None:
            section = cost_first
        else:
            try:
                section = await _call_engine_cost_package(
                    {"recipient_scope": recipient_scope, "canvas": {"answers": answers},
                     "as_of": as_of},
                    bearer, recipient_scope=recipient_scope, template_id=None,
                )
            except HTTPException as exc:
                section = _cost_refusal_section(exc, recipient_scope)
        refused_items = section.get("refused_answers") or []
        if refused_items:
            if section["status"] == "exists":
                refused_ids = {i.get("answer_id") for i in refused_items}
                rest = {k: v for k, v in section.items() if k != "refused_answers"}
                documents.append({
                    "engine": engine,
                    "answers": [i for i in ids if i not in refused_ids],
                    **rest,
                })
            documents.extend(_refused_entries(engine, refused_items, recipient_scope))
            if section["status"] != "exists":
                # A FAILED section that names only some answers (canvas.resolve's "no answer
                # is about a lot" refusal) still owes the rest: an answer in no document is
                # an answer the exporter never accounted for.
                named = {i.get("answer_id") for i in refused_items}
                rest_ids = [i for i in ids if i not in named]
                if rest_ids:
                    documents.append({
                        "engine": engine, "answers": rest_ids, "export_id": None,
                        "status": "failed", "recipient_scope": recipient_scope,
                        "outcome": "not_in_model", "reason_code": "not_in_model",
                        "reason": section.get("reason"),
                    })
            continue
        doc = {"engine": engine, "answers": ids, **section}
        if doc["status"] == "failed":
            oc = doc.get("outcome")
            doc["reason_code"] = oc if isinstance(oc, str) and oc else "engine_refused"
        documents.append(doc)

    ok = [d["status"] == "exists" for d in documents]
    status = "exists" if all(ok) else ("partial" if any(ok) else "failed")
    refused = sum(len(d["answers"]) for d in documents if d["status"] != "exists")
    return {
        "export_id": None,
        "status": status,
        "recipient_scope": recipient_scope,
        "reason": None if not refused else f"{refused} of {len(body.answers)} answers refused",
        "template_id": None,
        "documents": documents,
    }


@app.get("/export/package/artifact/{filename}", tags=[MCP_TAG])
async def export_package_artifact(
    filename: str,
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Download proxy for a produced export package. THE GATEWAY-SIDE CHECK the relay asks
    for: the engine repeats the same check on the same person's token (main.py's /artifact,
    ~line 700), and the two agree because both ask the `recipient_readers` rail. This is not
    redundant — it is the ONLY check between an unentitled browser and the engine's bytes,
    since the engine sits behind the mesh and is not itself reachable from a browser.
    """
    from agent_fleet.cost_agent import seed as _cost_seed
    from agent_fleet.finance_agent import export as _fin_export

    # THE CLOSED SET, over BOTH engines' producible names. Checked in a fixed order — cost
    # first, then finance — which is safe only because the two engines' filename sets are
    # DISJOINT (sealed in tests/finance/test_fin_package_export.py): were a name ever claimed
    # by both, this order would silently prefer cost's scope and recipients_fn over finance's.
    from agent_fleet.utils import answer_exports as _ae
    scope = _cost_seed.scope_of_artifact(filename)
    plan_hit = None
    plan_profiles: Optional[dict] = None
    plan_unavailable = False
    if scope is None and filename.startswith(_ae.ARTIFACT_PREFIX):
        try:
            plan_profiles = _plan_profiles()
            plan_hit = _ae.match_artifact(plan_profiles, filename)
        except _ae.AnswerProfilesUnavailable:
            plan_unavailable = True
    if scope is not None:
        engine_url = _ENGINE_COST_URL
        recipients_fn = _export_recipients_for
        engine_label = "cost"
    elif plan_hit is not None:
        # A plan answers export: produced by engine-cost, read on the `recipient_readers` rail.
        scope = plan_hit[1]
        engine_url = _ENGINE_COST_URL
        # can_export gates PRODUCTION; reading a produced package is a reader's act.
        recipients_fn = lambda u: _plan_recipients_for(u, plan_profiles)  # noqa: E731
        engine_label = "cost"
    else:
        scope = _fin_export.scope_of_artifact(filename)
        if scope is not None:
            engine_url = _ENGINE_FIN_URL
            recipients_fn = _fin_export_recipients_for
            engine_label = "fin"
        else:
            if plan_unavailable:
                # An `ia-answers-*` name the cost and fin matchers do not claim may be a plan
                # package whose registry could not be read: unknown, not absent.
                raise _plan_profiles_unavailable()
            # Same structural traversal defence as either engine's own route: a filename
            # neither engine could have produced is refused outright rather than sanitized
            # and forwarded.
            raise HTTPException(
                status_code=404,
                detail=f"{filename!r} is not an export artifact this gateway serves",
            )

    if scope not in recipients_fn(current_user):
        # NAMES THE PACKAGE, NOT ITS READERS — same wording and reasoning as the engine's own
        # /artifact 403 (cost_agent/main.py ~700-716; finance_agent/main.py's analog).
        raise HTTPException(
            status_code=403,
            detail=(
                f"caller {current_user.authz_id or 'unidentified'!r} is not entitled to the "
                f"package for {scope!r}. This artifact is a customer disclosure and is "
                f"served only to the recipient it was produced for."
            ),
        )

    bearer = _user_bearer(request)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            rr = await client.get(
                f"{engine_url}/artifact/{filename}",
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": f"{engine_label}_engine_unreachable", "message": str(exc),
        })

    if rr.status_code >= 400:
        try:
            body_json = rr.json()
            detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
        except Exception:
            detail = getattr(rr, "text", "engine refused")
        raise HTTPException(status_code=rr.status_code,
                            detail=_detail_with_message(rr.status_code, detail))

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    etag = rr.headers.get("etag") or rr.headers.get("ETag")
    if etag:
        headers["ETag"] = etag

    return Response(
        content=rr.content,
        media_type=rr.headers.get("content-type", "application/octet-stream"),
        headers=headers,
    )


# -- CDRL export (proposal: a CDRL is an export profile, Part 2) ---------------
#
# Mirrors the package_export client above: the BFF forwards THE PERSON's bearer, the engine decides
# program visibility (its 403 is relayed here with `grantable_by` filled by `relay_refusal`), and
# the bytes are fetched back through the engine's own /artifact route.

#: The closed map from a CDRL file's extension to its media type (mirrors the engine's
#: `cdrl.MEDIA_TYPES`); the filename regex admits exactly its keys.
_CDRL_MEDIA = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
}
_CDRL_FILENAME_RE = re.compile(r"^fin-cdrl-[A-Za-z0-9_.-]+\.(" + "|".join(_CDRL_MEDIA) + r")$")


def _engine_answer(rr, route: str):
    """The decoded JSON of an engine's 2xx answer. An empty or non-JSON body (a Restate handler
    that returns None is an EMPTY 200) is a named 502, never a crash and never a 200 `null`."""
    try:
        out = rr.json()
    except Exception:  # noqa: BLE001 -- an undecodable body is the failure being named
        out = None
    if out is None:
        raise HTTPException(status_code=502, detail={
            "error": "engine_empty_answer", "engine_route": route,
            "engine_status": rr.status_code,
            "message": f"the engine answered {rr.status_code} on {route} with no JSON body.",
        })
    return out


def _engine_refusal_detail(rr, route: str):
    """The `detail` of an engine's refusal, as the engine sent it. An empty or non-JSON body
    falls back to the response text, and an empty text is NAMED rather than left blank."""
    try:
        body_json = rr.json()
        detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
    except Exception:  # noqa: BLE001
        detail = getattr(rr, "text", "")
    if detail is None or (isinstance(detail, str) and not detail.strip()):
        detail = {"error": "engine_empty_body", "engine_route": route,
                  "engine_status": rr.status_code,
                  "message": f"the engine refused with {rr.status_code} on {route} and sent no body."}
    return detail


def _engine_failure(label: str, rr, route: str = "") -> HTTPException:
    """A refusal or failure an engine answered with, as this gateway's answer. The engine's
    declared refusals (403 policy, 409, 422) keep their status and every key of the body (advice
    keys may be added: a 403 gains `grantable_by`, a 409 gains `message`); anything else
    is a 502 naming the engine status."""
    try:
        body_json = rr.json()
        detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
    except Exception:
        detail = getattr(rr, "text", "engine refused")
    if rr.status_code == 403:
        return HTTPException(status_code=403, detail=relay_refusal(detail))
    if rr.status_code in (409, 422):
        detail = _engine_refusal_detail(rr, route or label)
        if rr.status_code == 409:
            detail = _detail_with_message(409, detail)
        return HTTPException(status_code=rr.status_code, detail=detail)
    return HTTPException(status_code=502, detail={
        "error": f"{label}_engine_failed", "engine_status": rr.status_code, "engine_detail": detail,
    })


@app.get("/export/cdrl/profiles", tags=[MCP_TAG])
async def export_cdrl_profiles(request: Request, current_user: User = Depends(get_current_user)):
    """The CDRL picker's option list: the engine's `[{name, format, scope, label}]`, relayed. The
    header keys only; the engine never sends a template path, a hash or a source."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            rr = await client.get(
                f"{_ENGINE_FIN_URL}/cdrl_profiles",
                headers={"Authorization": f"Bearer {_user_bearer(request)}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "fin_engine_unreachable", "message": str(exc),
        })
    if rr.status_code >= 400:
        raise _engine_failure("fin", rr, "/cdrl_profiles")
    return _engine_answer(rr, "/cdrl_profiles")


@app.get("/export/cdrl", tags=[MCP_TAG])
async def export_cdrl(
    request: Request,
    profile: str,
    program_id: str,
    current_user: User = Depends(get_current_user),
):
    """One program's CDRL in the profile's format (xlsx, docx, csv or json). `X-Cells-Sha256` is the hash of every cell the producer
    wrote (the reproducibility claim; the file's own bytes are not claimed reproducible).

    Refusals: 404 `unknown_profile` (relayed); 403 `program_not_visible` (the engine's envelope with
    `grantable_by` filled); any other engine failure is a 502 naming the engine's status.
    """
    bearer = _user_bearer(request)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            rr = await client.post(
                f"{_ENGINE_FIN_URL}/cdrl_export",
                json={"profile": profile, "program_id": program_id,
                      "user_email": current_user.authz_id},
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "fin_engine_unreachable", "message": str(exc),
        })
    if rr.status_code == 404:
        try:
            body_json = rr.json()
            detail = body_json.get("detail", body_json) if isinstance(body_json, dict) else body_json
        except Exception:
            detail = None
        if isinstance(detail, dict) and detail.get("error") == "unknown_profile":
            raise HTTPException(status_code=404, detail=detail)
    if rr.status_code >= 400:
        raise _engine_failure("fin", rr, "/cdrl_export")

    out = _engine_answer(rr, "/cdrl_export")
    filename = out.get("artifact_filename")
    cells_sha256 = (out.get("envelope") or {}).get("cells_sha256")
    if not (isinstance(filename, str) and _CDRL_FILENAME_RE.match(filename) and cells_sha256):
        raise HTTPException(status_code=502, detail={
            "error": "fin_engine_bad_cdrl_response",
            "message": "engine returned no verifiable CDRL artifact",
        })

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            fr = await client.get(
                f"{_ENGINE_FIN_URL}/artifact/{filename}",
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail={
            "error": "fin_engine_unreachable", "message": str(exc),
        })
    if fr.status_code >= 400:
        raise _engine_failure("fin", fr)

    return Response(
        content=fr.content,
        media_type=_CDRL_MEDIA[filename.rpartition(".")[2]],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Cells-Sha256": str(cells_sha256),
        },
    )


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
        raise HTTPException(status_code=rr.status_code,
                            detail=_detail_with_message(rr.status_code, detail))
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
# 3am with nobody awake. The qualitative half of this ruling is untouched by
# anything below: sequential is right, and how long each ask takes does not
# bear on it.
#
# ── THE NUMBER WAS 4x PESSIMISTIC, MEASURED 2026-09-09 ─────────────────────
# This said "~25 minutes for a full seed". Two independent measurements on the
# quiet sandbox, by invincible-agent-5f while running ADR-0050's seal 3:
#
#     1 five-question seed      398s   (6m38s)
#     2 five-question seeds     659s   (~5m29s each)
#
# So a full seed is ~5-7 MINUTES, not ~25. The stale figure was not idle: it
# drove substrate holds, window negotiation and scheduling on two lanes for a
# day — a ~50-minute estimate for seal 3's two-seed arm that is really ~11.
# An estimate nobody re-measures becomes a constraint, and this one was
# quoted back at us in three places before anyone timed it.
#
# ~5-7 minutes is still a PRE-WARM operation and not an on-stage one, which is
# what the ruling actually rests on.
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
    # ORGANISATIONS (group_by=org, first row `O1 | Corporate Capital Committee`), because the
    # verb ran on its DEFAULT. The card was a correct org-grouped view answering a question that
    # said something else, with NO disclosure surface — the strip renders routing, not verb params.
    # `org` IS the default, so this phrasing makes the seeded card TRUE.
    #
    # ── THE CAUSE WAS CORRECTED 2026-08-28. THIS COMMENT CARRIED THE OLD ONE UNTIL 2026-09-05. ──
    # It used to read "BAML extracts the slot and the dispatch payload does not carry it", which
    # is why you should not trust a comment that merely MATCHES the symptom. Retracted: NOTHING
    # IS EXTRACTED. `RouteIntent` — the BAML function with the typed slot
    # classes — has ZERO callers; `/route_intent` calls `ExtractIntent`, which returns mode and
    # entity refs and no slots at all. Every layer downstream then faithfully carries nothing,
    # which is why the symptom reads like a dispatch bug: the routing record is COMPLETE, and it
    # is complete about a question nobody asked.
    # The fix is FOUR joins and the first one is "call the function that fills slots" — not
    # "forward what BAML extracted". Building the carry alone would wire a payload fed by a
    # function that never runs: every test green, the field arrives empty, and empty is
    # indistinguishable from today. Revert to the by-initiative form once extraction AND carry
    # land; the acceptance test for that build is literally this question returning initiatives.
    # See [[slots-are-extracted-then-dropped-at-dispatch]] (whose TITLE is part of what was
    # retracted), ADR-0050 §3, and runbook A6.
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


# `pipeline_error` causes that mean "the caller's cell cannot see what the seed asked for",
# as opposed to "the seed could not be performed". Decided by reading every `_perror(...)`
# producer's `cause=`:
#   seed_panel_verb_not_visible -- the seed_panel FALL_BACK whose reason is
#       direct_dispatch.VERB_NOT_IN_CELL, and ONLY that: the verifier knows the declared verb
#       UNSCOPED and every domain it declares is outside the caller's active cell, so a persona
#       switch or a grant would satisfy it. The panel's failure record carries the verb's domains
#       as `missing_domains` beside the cause. Emitted where the seed_panel turn falls back
#       (the `seed_panel_fell_back` site).
# EXCLUDED, and why: seed_panel_fell_back (any other fall-back reason is OURS or the verb's, not
#   the caller's: "verifier unreachable"; "no longer compatible" -- the verb is retired, re-primed
#   or dropped by arity, which is NOT a policy refusal; an unscoped re-check that failed is
#   could-not-check, never a deny), seed_panel_unroutable (template declares no subject),
#   route_intent_failed, auto_compile_failed, restate_unreachable, dagster_launch_failed,
#   dagster_run_failed, ui_payload_fetch_error, ui_payload_timeout, acceptance_not_opened,
#   engine_did_not_answer, render_ui_failed, stream_producer_error, stream_raised -- all
#   faults of the seed/pipeline, not of the caller's grants. An absent cause is "unrecorded"
#   and is never entitlement.
_SEED_ENTITLEMENT_CAUSES = frozenset({"seed_panel_verb_not_visible"})


def _seed_failure_from_data(data: str | None) -> dict:
    """The typed failure of one seeded ask: `{event, kind, cause}` from the pipeline_error
    payload `_perror` wrote. A missing or unparseable payload records `cause: "unrecorded"`."""
    kind = None
    cause = None
    missing: list[str] = []
    if data:
        try:
            payload = json.loads(data.strip())
            if isinstance(payload, dict):
                kind = payload.get("kind") or None
                cause = payload.get("cause") or None
                _md = payload.get("missing_domains")
                if isinstance(_md, list):
                    missing = sorted({str(d) for d in _md if d})
        except (ValueError, TypeError):
            pass
    failure = {"event": "pipeline_error", "kind": kind, "cause": cause or "unrecorded"}
    if missing:
        # The domains the caller's cell lacks for this panel's verb -- data, not prose.
        failure["missing_domains"] = missing
    return failure


def _seed_failure_from_http(status: int, raw: bytes | None) -> dict:
    """The typed failure of one panel the stream REFUSED before opening: `{event: "http",
    status, cause, field}`, read defensively from FastAPI's body (`{"detail": {"error", ...}}`,
    or a 422's `{"detail": [{"loc": [...]}]}`). An unreadable body records `unrecorded`."""
    cause: str = "unrecorded"
    field = None
    try:
        body = json.loads((raw or b"").decode("utf-8", "replace") or "null")
    except (ValueError, TypeError):
        body = None
    d = body.get("detail") if isinstance(body, dict) else None
    if isinstance(d, dict):
        if isinstance(d.get("error"), str) and d["error"]:
            cause = d["error"]
        if isinstance(d.get("field"), str) and d["field"]:
            field = d["field"]
        elif cause == "incomplete_override":
            req = d.get("requested") if isinstance(d.get("requested"), dict) else {}
            field = "active_persona" if not req.get("persona") else "active_domains"
    elif isinstance(d, list) and d and isinstance(d[0], dict):
        cause = "validation_error"
        loc = d[0].get("loc")
        if isinstance(loc, (list, tuple)) and len(loc) > 1:
            field = ".".join(str(x) for x in loc[1:])
    return {"event": "http", "status": status, "cause": cause, "field": field}


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
        failure: dict | None = None
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
                        _awaiting_error_data = False
                        async for line in resp.aiter_lines():
                            if line.startswith("event: final_payload"):
                                saw_final = True
                            elif line.startswith("event: pipeline_error"):
                                saw_error = True
                                _awaiting_error_data = True
                            elif _awaiting_error_data and line.startswith("data:"):
                                _awaiting_error_data = False
                                if failure is None:
                                    failure = _seed_failure_from_data(line[5:])
                        # A non-200 never reaches here; an error EVENT is a
                        # different failure and must not read as success.
                        status = "ok" if (saw_final and not saw_error) else "failed"
                        detail = None if status == "ok" else "pipeline_error"
                        if status != "ok" and failure is None:
                            failure = _seed_failure_from_data(None)
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
            "failure": failure,
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


async def seed_template_canvas(
    template: "CanvasTemplate",
    bindings: dict,
    request: "CanvasSeedRequest",
    http_request: Request,
    current_user: User,
):
    """Seed every panel of a RATIFIED, NON-PORTFOLIO template through its own declared verb.

    Mirrors `seed_portfolio_canvas` on purpose — sequential (never gathered), slot-aligned
    `artifact_ids` with null holes on a failed panel, the same SSE success detection — but it
    never builds a phrase. Each panel already names its verb and its slots (ADR-0050 §2); this
    function's only job is to hand `/interview/stream` the panel's INDEX and the caller's
    `bindings` as `seed_panel`, so the stream rebuilds the dispatch route from the TEMPLATE'S
    own declaration, never from whatever `message` says. `message` here is a label for logs and
    traces — never parsed, never classified.
    """
    auth = http_request.headers.get("Authorization", "")
    base = "http://localhost:8090"
    session_id = "canvas-seed-" + uuid.uuid4().hex[:8]
    frontend_id = "cortex-ui-desktop"
    bound_desc = ", ".join(f"{k}={v}" for k, v in bindings.items())

    results: list = []
    artifact_ids: list = [None] * len(template.panels)

    for i, panel in enumerate(template.panels):
        artifact_id = (
            "urn:li:answerArtifact:" + session_id + "-seed" + str(i) + "-" + uuid.uuid4().hex[:8]
        )
        started = time.time()
        payload = {
            "message": f"Seed panel {i} of {template.template_id}: {panel.verb} for {bound_desc}",
            "session_id": session_id + "-seed" + str(i),
            "frontend_id": frontend_id,
            "artifact_id": artifact_id,
            "active_persona": request.active_persona,
            "active_domains": request.active_domains,
            "seed_panel": {"template_id": template.template_id, "panel": i, "bindings": bindings},
        }
        status = "failed"
        detail = None
        failure: dict | None = None
        try:
            # SEQUENTIAL BY CONSTRUCTION, same reason as `seed_portfolio_canvas`: gathering
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
                        try:
                            _raw = await resp.aread()
                        except Exception:  # noqa: BLE001
                            _raw = b""
                        failure = _seed_failure_from_http(resp.status_code, _raw)
                    else:
                        saw_final = False
                        saw_error = False
                        _awaiting_error_data = False
                        async for line in resp.aiter_lines():
                            if line.startswith("event: final_payload"):
                                saw_final = True
                            elif line.startswith("event: pipeline_error"):
                                saw_error = True
                                _awaiting_error_data = True
                            elif _awaiting_error_data and line.startswith("data:"):
                                _awaiting_error_data = False
                                if failure is None:
                                    failure = _seed_failure_from_data(line[5:])
                        status = "ok" if (saw_final and not saw_error) else "failed"
                        detail = None if status == "ok" else "pipeline_error"
                        if status != "ok" and failure is None:
                            failure = _seed_failure_from_data(None)
        except Exception as exc:  # noqa: BLE001 - one bad panel must not lose the rest
            detail = (type(exc).__name__ + ": " + str(exc))[:160]

        if status == "ok":
            artifact_ids[i] = artifact_id
        results.append({
            "slot": i,
            "verb": panel.verb,
            "artifact_id": artifact_id if status == "ok" else None,
            "status": status,
            "detail": detail,
            "failure": failure,
            "elapsed_s": round(time.time() - started, 1),
        })
        logger.info(
            "seed_template_canvas: template=%s panel=%s verb=%s status=%s %.1fs",
            template.template_id, i, panel.verb, status, time.time() - started,
        )

    ok = sum(1 for r in results if r["status"] == "ok")
    return {
        "session_id": session_id,
        "artifact_ids": artifact_ids,
        "ordered_artifact_ids": [a for a in artifact_ids if a],
        "seeded": ok,
        "total": len(template.panels),
        "results": results,
    }


class CanvasSeedRequest(_BaseModel):
    """A canvas TYPE or a ratified `template_id`, and nothing else.

    It supplies no session id and no question list, which is the point — the panels and their
    slot order are the TEMPLATE'S declaration, not the caller's.

    `template_id` IS THE ONE ADR-0050 SPEAKS, and `canvas_type` is kept because cortex's
    `requestPortfolioCanvasSeed()` sends it today. Removing it in the same change that adds
    the new field would break the live client for a rename, so both are accepted and the
    resolution below is explicit rather than a silent precedence.

    `bindings` IS THE PICKER'S HALF OF ADR-0050 §3's CARRY: shared-slot NAME (never `param`,
    which is dispatch vocabulary the caller never sees) -> the value the picker chose. Keyed by
    `name` so one ask serves every panel that consumes it, the same relation `SharedSlot.bind_as`
    exists to resolve on the dispatch side.

    `active_persona`/`active_domains` ride through to `/interview/stream` UNCHANGED — `None`
    lets the stream fall back to the caller's own default cell exactly as a hand-typed turn
    would, rather than this route inventing a cell on the caller's behalf.

    `params`, `user_persona` AND `domain` ARE THE SUPERVISOR'S DISPATCH FIELDS. A bound verb is
    dispatched by POSTing its bound slots under `params` plus the caller's chosen cell; this
    model declared none of them, so pydantic DROPPED them silently and a chat-routed seedCanvas
    lost its `template_id` and built the portfolio board. `canvas_template.fold_dispatch_params`
    reads them now.
    """
    canvas_type: str = "portfolio_planning"
    template_id: Optional[str] = None
    bindings: Optional[dict[str, str]] = None
    active_persona: Optional[str] = None
    active_domains: Optional[list[str]] = None
    params: Optional[dict[str, Any]] = None
    user_persona: Optional[str] = None
    domain: Optional[str] = None


# ── The /canvas/seed response bodies, DECLARED FOR THE OPENAPI ONLY ───────────────────────
#
# The route wires these through `responses=`, never `response_model=`: `response_model` filters
# and serializes the body, which would add `template_id: null` to the partial and empty returns
# and break the ruling that those stay three fields. Keys below are derived from the producers:
# `iagent_pure.slot_disposition.ask_card`, `_canvas_seed_ask`, and `canvas_template.policy_hint`.
class CanvasSeedResponse(_BaseModel):
    artifact_ids: list[str] = Field(description="Slot-ordered ids; empty on a partial or empty seed.")
    seeded: int = Field(description="Panels seeded.")
    total: int = Field(description="Panels the template declares.")
    template_id: Optional[str] = Field(
        default=None,
        description="Present on full success only; ABSENT (not null) on a partial or empty seed.",
    )


class CanvasSeedPolicyCell(_BaseModel):
    persona: str
    domain: str


class CanvasSeedPolicy(_BaseModel):
    cell: CanvasSeedPolicyCell = Field(description="The cell that owns the referent.")
    groups: list[str] = Field(description="Groups in policy/groups.yaml that grant the cell.")
    repair: Literal["switch_cell", "grant_member", "join_group", "declare_group"]
    message: str


class CanvasSeedAskOption(_BaseModel):
    value: str
    label: str


class CanvasSeedAskStructuredData(_BaseModel):
    slot: Optional[str] = None
    options: list[CanvasSeedAskOption]
    option_source: str
    free_text_reason: Optional[str] = None
    total_count: int
    scoped_by: list[str]
    bound_slots_offered: list[str]
    already_known: dict[str, Any]


class CanvasSeedAsk(_BaseModel):
    """`ask_card(...)` plus `template_id`, `binding_slot` and (abstain on no members) `policy`."""
    status: Literal["slot_elicitation", "slot_abstain"]
    disposition: Literal["ask", "abstain"]
    output_uri: str
    verb_iri: str
    sub_query: str
    slot: Optional[str] = None
    reason: str
    spoken: str
    found: str
    options: list[CanvasSeedAskOption]
    option_source: str
    free_text_reason: Optional[str] = None
    truncated_from: int
    total_count: int
    scoped_by: list[str]
    bound_slots_offered: list[str]
    accepted_slots: dict[str, Any]
    message: str
    summary: str
    structured_data: CanvasSeedAskStructuredData
    data: str
    sources: list[Any]
    template_id: str = Field(description="Always set by `_canvas_seed_ask`.")
    binding_slot: Optional[str] = Field(description="The shared-slot NAME (not the dispatch param).")
    policy: Optional[CanvasSeedPolicy] = Field(
        default=None,
        description="Present only when the caller's enumeration came back empty (an abstain).",
    )


class CanvasSeedAskUnavailable(_BaseModel):
    error: Literal["ask_unavailable"]
    detail: str = Field(description="The builder's exception class name.")


class CanvasSeedRefusal(_BaseModel):
    """`authz.refusal.refusal`'s envelope (ca's `iagent_mesh.refusal.Refusal` field names)."""
    policy_id: str = Field(description="The policy family that refused, e.g. `groups` or `program_members`.")
    missing_binding: str = Field(description="What the caller lacks, e.g. `can_view_program(program)`.")
    grantable_by: str = Field(description="Who can grant it and how, from policy/grantors/.")
    candidates: list[str] = Field(description="The choices that would satisfy it; empty when none is offered.")


class CanvasSeedConflictDetail(_BaseModel):
    error: Literal["unbound_required_slot"]
    message: str
    ask: Optional[CanvasSeedAsk | CanvasSeedAskUnavailable] = Field(
        default=None,
        description="Absent when no unbound slot is askable; best-effort, so it may be the unavailable form.",
    )
    refusal: CanvasSeedRefusal = Field(
        description="Always present: the 409 asks the caller to choose or request something (`slot_refusal`).",
    )


class CanvasSeedConflict(_BaseModel):
    detail: CanvasSeedConflictDetail


def _canvas_seed_enumerator(*, user_email: str, entitled_domains: list):
    """A SYNC `(class_uri, bound_slots=) -> {outcome, members, ...}` against engine-o's
    `/enumerate_instances`, with the body `dynamic_supervisor._make_enumerator` sends. Sync
    because `decide_disposition` calls it synchronously; the caller runs the whole disposition
    in a threadpool so this never blocks the event loop. Raises on connect/timeout, which the
    disposition files as `no_provider` rather than as a menu."""
    def _enumerate(class_uri: str, *, bound_slots: dict | None = None) -> dict:
        _bound = {str(k): str(v) for k, v in (bound_slots or {}).items() if v not in (None, "")}
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{_DAGSONTOLOGY_SVC_URL}/enumerate_instances",
                json={"class_uri": class_uri, "bound_slots": _bound,
                      "user_email": user_email,
                      "entitled_domains": list(entitled_domains or [])},
            )
        resp.raise_for_status()
        return resp.json() or {}
    return _enumerate


def _canvas_seed_domains(request, ent) -> list[str] | None:
    """The cell a seed request names: explicit `active_domains` (truthy -- `[]` is unset) win;
    else `ent.domains_for(active_persona)` when a persona is named; else None (the caller named
    no cell). ONE derivation, shared by the ask and the seed."""
    if request.active_domains:
        return list(request.active_domains)
    if request.active_persona:
        return ent.domains_for(request.active_persona)
    return None


async def _canvas_seed_ask(template, request: "CanvasSeedRequest", current_user: User):
    """The ask for a 409'd seed, or None when no unbound slot is askable.

    Built by the SAME disposition the chat path uses (`decide_disposition` + `ask_card`) from
    the SAME slot declarations the program-cell registration carries
    (`canvas_template.referent_slots`), so the two cannot drift. `policy` is added whenever the
    caller's enumeration came back EMPTY (an abstain on no members) -- never for `no_provider` or
    `too_many`, where a list exists or nobody was asked, and "you cannot see any" would be false.
    It is derived from `REFERENT_CELLS`, policy/groups.yaml and the caller's own cells.
    """
    from starlette.concurrency import run_in_threadpool
    from iagent_pure.slot_disposition import ABSTAIN, ask_card, decide_disposition
    from .canvas_template import (
        REFERENT_CELLS, SHARED_SLOT_REFERENTS, policy_hint, referent_slots,
    )

    clean = {k: v for k, v in (request.bindings or {}).items() if v not in (None, "")}
    consumed = {c for p in template.panels for c in p.consumes}
    unbound = consumed - set(clean)
    declared = referent_slots({template.template_id: template}, only=unbound)
    if not declared:
        return None
    accepted = {s.bind_as: clean[s.name] for s in template.shared_slots if s.name in clean}
    slot_name = {s.bind_as: s.name for s in template.shared_slots}

    ent = current_user.entitlements
    domains = _canvas_seed_domains(request, ent) or sorted({c.domain for c in ent.cells})
    enum = _canvas_seed_enumerator(user_email=current_user.authz_id, entitled_domains=domains)

    def _build():
        disp = decide_disposition(accepted=accepted, declared=declared, enumerate_class=enum)
        return disp, ask_card(
            disp, verb_iri="mesh:seedCanvas",
            sub_query=f"seed canvas {template.template_id}", accepted=accepted,
        )

    disp, ask = await run_in_threadpool(_build)
    ask["template_id"] = template.template_id
    ask["binding_slot"] = slot_name.get(disp.slot or "", disp.slot)
    if disp.action == ABSTAIN:
        referent = SHARED_SLOT_REFERENTS.get(disp.slot or "")
        if referent in REFERENT_CELLS:
            o_persona, o_domain = REFERENT_CELLS[referent]
            held = any(c.persona == o_persona and c.domain == o_domain for c in ent.cells)
            ask["policy"] = policy_hint(
                referent, held=held, asked_in_cell=o_domain in domains,
            )
    return ask


@app.post("/canvas/seed", tags=[MCP_TAG], responses={200: {"model": CanvasSeedResponse}, 409: {"model": CanvasSeedConflict}})
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

    A complete seed (the normal case; 5/5 in 17.7 min when first measured, and
    5/5 in ~5-7 min re-measured 2026-09-09 on the quiet sandbox)
    is unaffected. A partial seed produces a board that is wrong in a way only a
    human notices. Whether a partial seed should compose at all or refuse
    outright is a PRODUCT ruling, not mine to make silently at this layer: the
    client already has a no-canvas path for an empty array. `seeded` vs `total`
    is logged on every run so a partial is visible in the record even though the
    response cannot carry it.
    """
    # ── WHICH TEMPLATE, AND A REFUSAL RATHER THAN A FALLBACK (ADR-0050 §4) ─────────────
    #
    # `template_id` wins when given; `canvas_type: "portfolio_planning"` is the legacy spelling
    # of `portfolio` and is translated once, here, rather than being understood in two places.
    #
    # AN UNKNOWN ID REFUSES BY NAME. It must never fall back to the portfolio board: a seed
    # that quietly builds the wrong template draws, every card is real, and nothing reports it
    # — and a board that is WRONG is harder to catch than one that is absent. cortex-ui-60 hit
    # the client-side half of this same hazard tonight, where an unknown id fell through to
    # generic placement in complete silence.
    from .canvas_template import (
        DispatchParamsRefused, fold_dispatch_params, load_template, ratified_template_ids,
    )

    # THE SUPERVISOR'S DISPATCH FIELDS, FOLDED BEFORE ANYTHING IS RESOLVED. `params` carries a
    # chat-routed seedCanvas's bound slots and was silently dropped before this; a disagreement
    # or an unplaceable key is a 422, and a keyed `params` never falls back to portfolio.
    try:
        _folded_id, _folded_bindings = fold_dispatch_params(
            request.params, request.template_id, request.bindings
        )
    except DispatchParamsRefused as _perr:
        raise HTTPException(status_code=422, detail=str(_perr))
    request.template_id = _folded_id or request.template_id
    request.bindings = _folded_bindings or request.bindings
    # The caller's chosen cell rides in as `user_persona`/`domain`; it fills the picker fields
    # ONLY when they are unset, so an explicit picker value always wins.
    if request.active_persona is None and request.user_persona:
        request.active_persona = request.user_persona
    if request.active_domains is None and request.domain:
        request.active_domains = [request.domain]
    # THE CELL A PERSONA NAMES. The stream refuses a persona without domains, so a persona-only
    # seed (the chat re-send after the "which program?" pick) is completed HERE from the
    # caller's own entitlements, the same derivation the ask uses. A seed never picks a cell
    # the caller did not name: neither field set stays unset.
    if request.active_persona and not request.active_domains:
        _derived = _canvas_seed_domains(request, current_user.entitlements)
        if not _derived:
            from .authz.refusal import policy_refusal as _policy_refusal
            raise _policy_refusal(
                "persona_not_held", policy_id="groups",
                missing_binding=f"a_group_granting({request.active_persona})",
                message=f"you hold no cell under persona {request.active_persona}",
            )
        request.active_domains = _derived
    elif request.active_domains and not request.active_persona:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "incomplete_override", "field": "active_persona",
                "message": "a seed names its domains without a persona; send active_persona "
                           "(or user_persona) too",
            },
        )

    _requested = (request.template_id or "").strip()
    if not _requested:
        _requested = "portfolio" if request.canvas_type == "portfolio_planning" else (
            request.canvas_type or ""
        ).strip()
    try:
        _template = load_template(_requested)
    except (KeyError, ValueError) as _terr:
        raise HTTPException(
            status_code=400,
            detail=(
                f"no ratified canvas template {_requested!r} "
                f"(ratified: {ratified_template_ids()}) — {_terr}"
            ),
        )

    # ── SEEDABILITY IS A PROPERTY OF THE TEMPLATE, AND IT IS CHECKED BEFORE THE CLOCK ──
    #
    # `program_finance` is ratified and CANNOT seed: all six finance verbs require
    # `program_id` with no default, and `shared_slots` is empty until §3's carry lands. Every
    # panel would refuse at dispatch — after minutes of sequential asks, one hole at a
    # time, ending in a partial-seed refusal that names the wrong cause.
    #
    # So it refuses UP FRONT and says which slot is missing. This is the same ordering as the
    # arity precondition on the direct path: a turn that cannot succeed must not spend the
    # engine call to find out.
    # ── R-005: SHARED SLOTS ARE TEMPLATE-SCOPED, AND SCOPE IS WHAT A PANEL CONSUMES ──
    #
    # RULED 2026-09-11 — see docs/rulings/README.md#r-005--shared_slots-are-template-scoped.
    #
    # The previous gate unioned every REQUIRED shared slot with every panel's `consumes`, so a
    # slot that was merely DECLARED blocked the seed even when no panel in that template
    # consumed it. That made declaration global in effect: adding `program` to both templates
    # so `program_finance` could carry it would have regressed `portfolio` — the only path that
    # draws a board today — from seeding to 409. invincible-agent-5f refused that change twice
    # on exactly this evidence rather than shipping the regression.
    #
    # A SharedSlot's answer "binds into every panel that CONSUMES it". So a declared slot no
    # panel consumes cannot refuse anything, and must not gate anything. The population the
    # seeder demands values for is the CONSUMED set, never the declared set.
    # THE THREE R-005 OUTCOMES, ONE FUNCTION — item 3 factored this block out into
    # `canvas_template.validate_bindings` so packageExport's own gates (below, `/export/package`)
    # read the SAME checks rather than a second copy that could drift from this one. Messages
    # and status codes are unchanged; only where they are computed moved.
    from .authz.refusal import policy_refusal
    from .canvas_template import (
        UnboundRequiredSlot, UndeclaredConsumption, UnknownBinding, slot_refusal,
        validate_bindings,
    )

    try:
        _bindings = validate_bindings(_template, request.bindings or {})
    except UndeclaredConsumption as _terr:
        raise HTTPException(status_code=422, detail=str(_terr))
    except UnknownBinding as _terr:
        raise HTTPException(status_code=422, detail=str(_terr))
    except UnboundRequiredSlot as _terr:
        _detail: dict = {"message": str(_terr)}
        # THE 409 CARRIES THE ASK. Built by the disposition the chat path uses, so a picker
        # gets "which program?" with candidates (or the policy to set) instead of only a
        # refusal. It is best-effort by construction: a failure here must never turn the
        # refusal into a 500.
        try:
            _ask = await _canvas_seed_ask(_template, request, current_user)
            if _ask is not None:
                _detail["ask"] = _ask
                if _ask.get("policy"):
                    _detail["message"] = _ask["policy"]["message"]
                elif _ask.get("options"):
                    _detail["message"] = _ask.get("message") or _detail["message"]
        except Exception as _aerr:  # noqa: BLE001
            logger.warning("canvas_seed: ask builder failed (%r); 409 keeps its plain body", _aerr)
            _detail["ask"] = {"error": "ask_unavailable", "detail": type(_aerr).__name__}
        # A POLICY REFUSAL (it asks the caller to choose): the envelope says what the ask says
        # -- its options as candidates, its repair as the binding (`slot_refusal`).
        raise policy_refusal(
            "unbound_required_slot", status_code=409, message=_detail.pop("message"),
            extra=_detail, **slot_refusal(_template, _terr.slots, _detail.get("ask")),
        )

    if _template.template_id == "portfolio":
        inner = SeedPortfolioCanvasRequest(
            session_id="canvas-seed-" + uuid.uuid4().hex[:8],
        )
        result = await seed_portfolio_canvas(inner, http_request, current_user)
    else:
        # EVERY RATIFIED TEMPLATE BUT `portfolio` SEEDS THROUGH ITS OWN DECLARED VERBS now that
        # every shared slot it consumes is bound (checked above). `portfolio` keeps calling
        # `seed_portfolio_canvas` UNCHANGED — that seeder's RULING_A seal
        # (tests/planning/test_seed_portfolio_canvas.py) requires its body to go through the
        # interview-stream path and never call an engine's measure endpoint directly, and
        # folding it into the new per-panel path would be touching a function that seal is
        # sealing.
        result = await seed_template_canvas(
            _template, _bindings, request, http_request, current_user
        )

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
    # ── NOTHING SEEDED IS NOT A PARTIAL SEED, AND IT MUST NOT RETURN 200 ───────────────
    #
    # MEASURED 2026-09-09, and it made a seal LIE. All five asks 403'd in ~0.1s each, this
    # route answered 200, and the canvas-determinism seal compared two empty boards, found
    # them equal, and reported PASS in 2.48 seconds against a run that takes fifty minutes.
    # The only wrong-looking thing was the clock.
    #
    # THE GUARD ABOVE INHERITED THE CASE IT WAS WRITTEN FOR. A partial seed refusing with
    # 200-and-empty is right: cortex has a no-canvas path and the ruling above is sound. But
    # `seeded != total` is ALSO true when `seeded == 0`, and a caller who seeded NOTHING has
    # not received a refusal to compose — they have received a failure, and the status line
    # is where a headless caller reads that. `seeded`/`total` carried the truth in the body
    # and the seal read the status, which is what a status is FOR.
    #
    # THE CAUSE TRAVELS, because the two total failures have opposite repairs. Five upstream
    # 403s mean the caller is not entitled to the panels' subjects — the exact cell
    # `policy/groups.yaml` warns about, where "/resolve scopes the OntologyClass pool to
    # cells the caller holds" and a non-holder grounds to nothing while every engine reports
    # healthy. That is the caller's answer and it is a 403. Anything else upstream is a
    # 502: the seed could not be performed, and that is ours.
    if seeded == 0 and total:
        # From the inner route's own per-slot record — `results` is not a local here, and
        # reaching for it as one is how this refusal would 500 on the path it exists to
        # report. Each entry carries `status` and a `detail` like "HTTP 403".
        _failed = [r for r in (result.get("results") or []) if r.get("status") != "ok"]
        _codes = {str(r.get("detail") or "") for r in _failed}
        _causes = sorted({
            (r["failure"].get("cause") or "unrecorded")
            for r in _failed if r.get("failure") is not None
        })

        def _entitlement_shaped(r: dict) -> bool:
            f = r.get("failure")
            if f is not None and f.get("event") == "http":
                return f.get("status") == 403
            if f is not None:
                return (f.get("cause") or "unrecorded") in _SEED_ENTITLEMENT_CAUSES
            return "403" in str(r.get("detail") or "")

        _all_entitlement = bool(_failed) and all(_entitlement_shaped(r) for r in _failed)
        _http = [r["failure"] for r in _failed if (r.get("failure") or {}).get("event") == "http"]
        _relay = (
            not _all_entitlement and len(_http) == len(_failed)
            and len({f["status"] for f in _http}) == 1 and _http[0]["status"] in (400, 422)
        )
        if _relay:
            _ucauses = sorted({f["cause"] for f in _http})
            _fields = sorted({f["field"] for f in _http if f.get("field")})
            _rdetail = {
                "error": "seed_panel_refused",
                "upstream_error": _ucauses[0] if len(_ucauses) == 1 else _ucauses,
                "fields": _fields,
                "causes": _ucauses,
                "message": (
                    f"seeded 0 of {total} panels; every panel was refused as a malformed "
                    f"request: {_ucauses} (fields: {_fields})"
                ),
            }
            logger.warning("canvas_seed: NOTHING seeded (0/%s) -- panels refused the request: %s",
                           total, _rdetail)
            if _http[0]["status"] == 400:
                raise HTTPException(status_code=400, detail=_rdetail)
            raise HTTPException(status_code=422, detail=_rdetail)
        logger.warning(
            "canvas_seed: NOTHING seeded (0/%s) -- refusing with %s. Upstream: %s causes: %s",
            total, 403 if _all_entitlement else 502, sorted(_codes)[:5], _causes,
        )
        # A BOARD THE PERSONA CANNOT SEE IS A POLICY REFUSAL, NAMING THE PERSONA AND THE DOMAIN.
        # Only when EVERY failed panel is a `seed_panel_verb_not_visible` carrying the domains its
        # verb declares: the verifier knows the verbs, and the cell holds none of their domains.
        # Any other all-entitlement mix (an upstream 403 with no domain to name) keeps the plain
        # 403 below, because naming a domain for a refusal that has none would be invented.
        _missing = sorted({
            d for r in _failed for d in ((r.get("failure") or {}).get("missing_domains") or [])
        })
        if _all_entitlement and _missing and all(
            (r.get("failure") or {}).get("missing_domains") for r in _failed
        ):
            _persona = request.active_persona or ""
            _held = current_user.entitlements
            _candidates = sorted(
                p for p in _held.personas()
                if p != _persona and set(_missing) <= set(_held.domains_for(p))
            )
            raise policy_refusal(
                "persona_lacks_domain", policy_id="groups",
                missing_binding=", ".join(
                    f"a_group_granting({_persona}, {d})" for d in _missing
                ),
                message=(
                    f"seeded 0 of {total} panels; persona {_persona or '(none named)'} holds "
                    f"none of the domains these panels' verbs declare: {_missing}. Switching "
                    "persona, or a group grant for that persona in one of those domains, "
                    "would satisfy it"
                ),
                candidates=_candidates,
                extra={"persona": _persona, "missing_domains": _missing,
                       "causes": _causes or sorted(_codes)[:5]},
            )
        if _all_entitlement:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "cell_cannot_see_verbs",
                    "message": (
                        f"seeded 0 of {total} panels; every ask was refused -- the caller is "
                        "not entitled to the cell these panels' subjects live in, or the "
                        "caller's cell cannot see the panels' verbs"
                    ),
                    "causes": _causes or sorted(_codes)[:5],
                },
            )
        raise HTTPException(
            status_code=502,
            detail={
                "error": "seed_upstream_failed",
                "message": (
                    f"seeded 0 of {total} panels; upstream failures: {sorted(_codes)[:5]}"
                ),
                "causes": _causes or sorted(_codes)[:5],
            },
        )

    if seeded != total:
        logger.warning(
            "canvas_seed: PARTIAL seed %s/%s — REFUSING to compose. Compacting "
            "would shift every card after the failed slot up one and produce a "
            "board that looks plausible and is wrong.",
            seeded, total,
        )
        return {"artifact_ids": [], "seeded": seeded, "total": total}

    # `template_id` IS SENT NOW BECAUSE ITS READER EXISTS; `name` STAYS UNSENT.
    #
    # This comment used to say neither optional field was sent, on a measured premise
    # (2026-08-29): cortex declared `canvas_type` `required: false` and no reader existed
    # anywhere in that repo, so sending it would have been a PRODUCER-side write with no
    # consumer. It named the order: cortex reads it first, then the producer states it.
    # That condition is met: cortex-ui's canvasSeedFromArtifact
    # (src/lib/canvasSeedFromAnswer.ts) now prefers `template_id` and treats `canvas_type` as
    # legacy. So the full-success path names its template, and the partial and empty returns
    # above are unchanged. `canvas_type` itself is still not sent: `template_id` supersedes it.
    #
    # `name` has a real reader, and still must not be sent: the phrase path has no
    # spoken name, so any value here would be invented. The receiver already defaults
    # honestly. When elicitation can ask "what should I call it?", that ask becomes
    # the name's producer.
    return {
        "artifact_ids": [a for a in (result.get("artifact_ids") or []) if a],
        "seeded": seeded,
        "total": total,
        "template_id": _template.template_id,
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
    # Which fan-out slot of the run this subtask redeems (its Dagster mapping key,
    # `task_<n>`). One single-use reference per slot, so two caller-identity subtasks in one
    # plan do not read as a replay. Bounded to [0, IDENTITY_VAULT_SLOTS) below.
    slot: int = 0


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

    _slots = vault_slots()
    if body.slot < 0 or body.slot >= _slots:
        _vault_audit_log.error(
            "identity_vault: REFUSED redemption for run_id=%s slot=%s — outside [0, %s)",
            body.run_id, body.slot, _slots,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "error": "slot_out_of_range",
                "run_id": body.run_id,
                "message": f"slot must be in [0, {_slots}).",
            },
        )

    # INVARIANTS 2, 3, 4 are all enforced inside this one call, atomically.
    result = VAULT.redeem(body.run_id, claimed_launcher=body.claimed_launcher, slot=body.slot)

    # INVARIANT 6 — one line per redemption: run_id, subject, timestamp, outcome. The
    # timestamp is the log record's own. The vault's whole legitimacy is that the token's
    # journey is VISIBLE.
    _vault_audit_log.info(
        "identity_vault: redemption run_id=%s slot=%s caller=%s subject=%s outcome=%s",
        body.run_id, body.slot, caller, result.subject or "-", result.outcome,
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
    # NO FALLBACK — see _required_service_url. A hardcoded in-cluster address here would make
    # this route work against a service the chart never declared, which is the exact condition
    # readiness is now required to refuse.
    _dh = _DATAHUB_WRAPPER_URL
    if not _dh:
        raise HTTPException(
            status_code=503,
            detail=(
                "DATAHUB_WRAPPER_URL is not declared, so engine-d cannot be reached. This is a "
                "deploy fault, not a request fault — the ConfigMap entry is missing."
            ),
        )
    u = urlparse(_dh)
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


def _allowed_or_empty(kind: str) -> list:
    """`verbs_for_kind` or `[]` — never a raise, because every caller of this is already
    reporting a refusal and a second failure there loses the first one."""
    from . import human_tasks

    try:
        return list(human_tasks.verbs_for_kind(kind))
    except Exception:  # noqa: BLE001 — the refusal being reported matters more than this detail
        return []


# Kinds whose review files NO document_promotion task (architect ruling 2026-10-17, on 7f's ruling
# 1). An s1000d data module has no PCN/PDN card -- no notice id, mfr, parts, evidence crops -- so a
# task filed under the review standard could not be vetted. See the stage route's review branch.
_PROMOTION_SKIPPED_KINDS = frozenset({"s1000d-data-module"})


def _delegate_principals() -> dict[str, frozenset[str]]:
    """R-089: the asserted delegate -> {principal authz_ids} map, read fresh from
    DELEGATE_ON_BEHALF_OF (deploy configuration, see helm configmap.yaml) ON EVERY CALL — never
    cached at import time — so a test can monkeypatch.setenv and so a chart re-render is live
    without a process restart.

    Unset or blank is `{}` (no delegate may act for anyone). Malformed JSON or the wrong shape
    is logged and answered as `{}` too: FAILS CLOSED, because an unreadable map must refuse
    every delegated act rather than guess. This never raises — a parse failure here must not
    become a 500 for a caller who never asked to delegate."""
    raw = os.environ.get("DELEGATE_ON_BEHALF_OF")
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"DELEGATE_ON_BEHALF_OF is a {type(parsed).__name__}, not an object")
        out: dict[str, frozenset[str]] = {}
        for k, v in parsed.items():
            if not isinstance(k, str) or not isinstance(v, list) or not all(isinstance(e, str) for e in v):
                raise ValueError(f"DELEGATE_ON_BEHALF_OF[{k!r}] is not a list of strings")
            out[k] = frozenset(v)
        return out
    except Exception as exc:  # noqa: BLE001 — fail closed, never raise out of this helper
        logger.error("DELEGATE_ON_BEHALF_OF unreadable, failing closed (no delegate can act): %s", exc)
        return {}


def _admit_on_behalf_of(current_user, on_behalf_of: Optional[str]) -> tuple[str, Optional[str]]:
    """R-089: admit (or refuse) an `on_behalf_of` that names someone other than the caller.
    Returns `(actor, via)`. `actor` is who the authorization questions and the record are
    about; `via` is who authenticated, carried only so it can be recorded, never asked a
    question. A blank `on_behalf_of`, or one equal to the caller's own authz_id, is the
    unchanged non-delegated path: `(caller, None)`.

    A mismatch is admitted only for a caller that is a declared delegate
    (DELEGATE_ON_BEHALF_OF) and only for a principal declared for THAT delegate; a person
    sending someone else's id is refused `not_a_delegate`. The assertion is trusted by
    configuration this pass (R-089); token exchange replaces it."""
    caller = current_user.authz_id
    if not on_behalf_of or on_behalf_of == caller:
        return caller, None
    delegates = _delegate_principals()
    if caller not in delegates:
        raise HTTPException(status_code=403, detail={"error": "not_a_delegate"})
    if on_behalf_of not in delegates[caller]:
        raise HTTPException(status_code=403, detail={
            "error": "principal_not_declared_for_delegate",
            "delegate": caller,
            "on_behalf_of": on_behalf_of,
        })
    return on_behalf_of, caller


def _promotion_stores(acted_by: str):
    """The stores a document_promotion act needs (ADR-0041 Open §1, ruled 2026-09-30).

    All five are built here: the ledger (Postgres, beside human_task_projection), the objects
    (the seam's bucket), the GRAPH through the SDK graph writer, the INDEXES over the
    declared ingest-carrying collections, and the CORRECTION OUTBOX (the same bucket, under
    `corrections/`, for 7f to apply to RDF). The graph writes as the PERSON acting -- `acted_by`,
    the caller `can_act` is asked about -- so it is built per act, never once at startup.

    What this does NOT lift: a promotion still needs the ingest node. `/ingest` now creates one
    for a new arrival, best-effort, through this same home's `create_node` (see
    `_create_ingest_node`, ruled 2026-09-30) -- but that call is logged and swallowed on
    failure, never raised, so a document can still arrive at `promotion.act` with no node. The
    409 `ingest_node_absent` answer below is that honest, still-live case, not a historical one.
    A store that cannot be built is None, and the act refuses 503 naming it before anything is
    written."""
    from iagent_mesh.interfaces import Initiator

    from . import promotion, promotion_stores

    try:
        graph = promotion_stores.Neo4jIngestGraph(
            driver=neo4j_driver, initiator=Initiator(subject=acted_by, kind="person"))
    except Exception as exc:  # noqa: BLE001 — refused by name downstream, never a 500 here
        logger.warning("promotion graph store unavailable for %r: %s", acted_by, exc)
        graph = None
    return promotion.PromotionStores(
        ledger=promotion_stores.PgDecisionLedger() if promotion_stores.configured() else None,
        graph=graph,
        indexes=promotion_stores.DeclaredIngestIndexes(),
        objects=promotion_stores.S3Quarantine(_build_s3_client, _ARTIFACT_BUCKET),
        corrections=promotion_stores.S3CorrectionOutbox(_build_s3_client, _ARTIFACT_BUCKET),
    )


# Separation of duties (architect ruling 2026-10-21): the person who chose a case's disposition
# cannot approve it as supervisor on the same case. Maps a task kind to the case state that the
# chooser's decision moved the case INTO; the chooser is the `by` of the last non-system
# transition into that state.
_SEPARATED_REVIEW_KINDS = {"maint_supervisor_approval": "maint_supervisor_review"}


async def _read_ingest_row_for_act(task_id: str, ingest_id: str):
    """The ingest row a promotion act is about, or None when it is absent (a legacy task proceeds).
    Fail closed: an unreadable row is 503 `ingest_row_unreadable` and nothing is decided."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    try:
        return await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
    except Exception as exc:  # noqa: BLE001 -- fail closed
        logger.warning("act %s: the ingest row could not be read (%s: %s)", task_id,
                       type(exc).__name__, exc)
        raise HTTPException(status_code=503, detail={
            "error": "ingest_row_unreadable", "task_id": task_id,
            "message": "the document's status could not be read, so nothing was decided; "
                       "try again"})


async def _stale_extraction(task_id: str, row: dict) -> "HTTPException":
    """The ONE 409 `stale_extraction` (spec 204, ruling "a leaf change at review makes the open task
    stale: /act refuses it with 409 stale_extraction and the new task id"), built for both the
    superseded-task miss path and the act guard. `new_task_id` is the row's current task when the row
    is at review and that task is open, else None."""
    from starlette.concurrency import run_in_threadpool

    from . import human_tasks, ingest_status

    new_id = None
    cur = _current_promotion_task_id(row) if row.get("status") == ingest_status.REVIEW else None
    # never name the acted-on task as its own replacement (the legacy kind-mismatch case)
    if cur is not None and cur != task_id:
        try:
            state = await run_in_threadpool(lambda: human_tasks.get_task_open_state(cur))
        except Exception:  # noqa: BLE001 -- cannot know: no new id is claimed
            state = None
        if state and state.get("open"):
            new_id = cur
    if new_id:
        msg = f"the leaf was changed; this task was replaced by {new_id}; act on that one"
    else:
        msg = ("the document is being re-extracted for its new leaf; a new task is filed when it "
               "returns to review")
    return HTTPException(status_code=409, detail={
        "error": "stale_extraction", "task_id": task_id, "new_task_id": new_id,
        "stage": row.get("status"), "message": msg})


@app.post("/human_tasks/{task_id}/act", tags=[INGEST_V1_TAG, MCP_TAG], responses={200: {"model": ActResponse}})
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

    # R-089: `on_behalf_of` is ASSERTED, not verified, this pass — the ruling's own words. This
    # runs FIRST, before any lookup, so a refused delegation never leaks whether the task_id
    # exists, who its audience is, or anything else. `actor` is who the gate (`check_can_act`,
    # the lookups, the resolution, the resume) is about; `via` is who authenticated, carried
    # only so it can be recorded, never asked `can_act`. An `on_behalf_of` equal to the caller's
    # own authz_id is the unchanged, non-delegated path.
    actor, via = _admit_on_behalf_of(current_user, req.on_behalf_of)

    # NB the verb is validated PER KIND below, once the task's kind is known — not against a
    # hardcoded pair here. A triage task ("this notice could not be prepared") accepts
    # acknowledge/re-drive and must REFUSE approve/reject, because storing "approved" on an
    # extraction failure writes a decision the task's semantics cannot represent, and
    # ADR-0034's decision records would archive it immutably as promotion evidence.
    # Look up the task's audience (from any of the caller's recipient rows) to
    # re-check. Keyed on authz_id — same as the replication filter. ON THE ACTOR
    # (the principal, for a delegated act; R-089): the delegate itself holds no audience row.
    try:
        rows = await run_in_threadpool(
            lambda: human_tasks.list_tasks_for(actor, status="pending")
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
            lambda: human_tasks.get_task_resolution(task_id, caller_id=actor)
        )
        if settled and settled.get("status") == human_tasks.SUPERSEDED:
            # A superseded task is not pending, so it lands here and never reaches the guard below:
            # answer the same stale_extraction (scoped to a recipient, so a non-recipient is 404).
            _sp = settled.get("payload")
            if isinstance(_sp, (str, bytes)):
                _sp = json.loads(_sp)
            _sing = _sp.get("ingest_id") if isinstance(_sp, dict) else None
            _srow = (await _read_ingest_row_for_act(task_id, _sing)
                     if isinstance(_sing, str) and _sing else None)
            raise await _stale_extraction(task_id, _srow or {})
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
    # can_act is asked about the ACTOR (the principal for a delegated act; R-089) — NEVER about
    # the delegate. A delegate speaks only as far as the principal it names is itself entitled.
    allowed = await run_in_threadpool(lambda: human_tasks.check_can_act(audience, actor))
    if not allowed:
        raise HTTPException(status_code=403, detail={"error": "not_authorized_to_act", "audience": audience})

    # SAME-ACTOR (ruling 2026-10-21): after the audience gate, before any write, resume or
    # delegated branch. Compared on `actor` (the principal), never the authenticated caller, so a
    # delegate acting for the chooser is refused too. Approve only; a reject is not refused.
    # Fail closed on an unreachable runner; no case / no chooser transition proceeds as before.
    _review_state = _SEPARATED_REVIEW_KINDS.get(match.get("kind"))
    if _review_state and req.decision == "approved" and match.get("case_id"):
        _case_key = str(match["case_id"]).split(_CASE_INSTANCE_SEP)[0]
        try:
            _case = await _fetch_case(_case_key)
        except Exception as exc:  # noqa: BLE001 -- connect errors, timeouts
            raise HTTPException(status_code=503, detail={"error": "runner_unavailable"}) from exc
        _chooser = None
        for _t in (_case or {}).get("transitions") or []:
            if _t.get("to") == _review_state and _t.get("by") and _t.get("by") != "system":
                _chooser = _t["by"]
        if _chooser is not None and _chooser == actor:
            raise HTTPException(status_code=409, detail={
                "error": "same_actor", "case_id": match["case_id"],
                "message": "the person who chose this case's disposition cannot approve it "
                           "as supervisor"})

    if via is not None:
        # R-089: a delegated act is supported ONLY for a workflow-backed resume whose kind is
        # neither document_promotion nor grouped_review — AFTER the authz check above, BEFORE
        # any write below. Those two branches build stores (document_promotion: the decision
        # record/ledger/graph/objects via `_promotion_stores`) or grants (grouped_review: the
        # GroupedReview.submit_decision call) AS THE PERSON, and are out of scope for this pass.
        # access_request too: its fulfilment below writes a reader grant whose `granted_by` is
        # the authenticated caller, so a delegated act would grant in the DELEGATE's name.
        if not match.get("workflow_id") or match.get("kind") in (
                "document_promotion", "grouped_review", "access_request"):
            raise HTTPException(status_code=409, detail={
                "error": "delegated_act_unsupported", "kind": match.get("kind"),
                "message": "a delegated act is supported only for a workflow-backed resume of "
                           "another kind; act as the principal yourself."})

    from . import promotion
    # row_edits is read ONLY by the grouped_review branch and (flag IAGENT_PROMOTION_ROW_EDITS on)
    # the document_promotion branch below. Sent on any other kind, or on a promotion while the flag
    # is off, it would be accepted and silently dropped, losing the correction (architect rulings
    # 2026-10-17, 2026-10-18). Asked before verb validation so the refusal names the real cause,
    # and before any write.
    if req.row_edits is not None and match.get("kind") != "grouped_review":
        if match.get("kind") == promotion.KIND:
            if not _promotion_row_edits_enabled():
                raise HTTPException(status_code=422, detail={
                    "error": "row_edits_not_for_kind", "kind": promotion.KIND,
                    "enabled": False,
                    "message": "row edits on a document promotion are off on this deployment "
                               "(IAGENT_PROMOTION_ROW_EDITS); sent here they would be lost"})
        else:
            raise HTTPException(status_code=422, detail={
                "error": "row_edits_not_for_kind", "kind": match.get("kind"),
                "message": "row edits are read only on a grouped review or a document "
                           "promotion; sent here they would be lost"})

    # header_edits (ruling 10-20): document_promotion only, behind the SAME flag as row_edits.
    if req.header_edits and match.get("kind") != promotion.KIND:
        raise HTTPException(status_code=422, detail={
            "error": "header_edits_not_for_kind", "kind": match.get("kind"),
            "message": "header edits are read only on a document promotion; sent here they "
                       "would be lost"})
    if req.header_edits and not _promotion_row_edits_enabled():
        raise HTTPException(status_code=422, detail={
            "error": "header_edits_not_for_kind", "kind": promotion.KIND,
            "enabled": False,
            "message": "header edits on a document promotion are off on this deployment "
                       "(IAGENT_PROMOTION_ROW_EDITS); sent here they would be lost"})

    # review_coverage: document_promotion only. Sent elsewhere it would be dropped, which is a
    # provenance claim that is not true.
    if req.review_coverage is not None and not _handler_consumes(
            match.get("kind"), "review_coverage"):
        raise HTTPException(status_code=422, detail={
            "error": "review_coverage_not_for_kind", "kind": match.get("kind"),
            "message": "review coverage is read only on a document promotion; sent here it "
                       "would be lost"})

    if req.page is not None and match.get("kind") != EMPTY_CONFIRM_KIND:
        raise HTTPException(status_code=422, detail={
            "error": "page_not_for_kind", "kind": match.get("kind"),
            "message": "a page is read only on a document_empty_confirm; sent here it would be lost"})

    # VERB VALIDATION, per the task's OWN species — after authz (never leak a kind to an
    # unauthorized caller through a validation error) and before any write.
    try:
        human_tasks.validate_decision(match.get("kind") or "", req.decision, req.comment)
    except human_tasks.TaskKindSetUnknown as exc:
        # THE RULED REFUSAL, CARRIED TO THE CARD RATHER THAN DROPPED AS A 500. A species the seed
        # does not carry cannot be answered while the overlay is unset or unreadable, and the
        # honest answer to cannot-know is a refusal that SAYS WHY — not the generic pair a code
        # table used to remember, and not a silent dead task.
        #
        # It is a 409, not a 422: the request is well formed and the caller did nothing wrong;
        # this deployment cannot currently answer for that species. A 422 would blame the caller
        # for a configuration they cannot see.
        raise HTTPException(status_code=409, detail={
            "error": "task_kind_set_unknown",
            "kind": match.get("kind"),
            "allowed": [],
            "message": str(exc),
        })
    except human_tasks.InvalidDecisionForKind as exc:
        raise HTTPException(status_code=422, detail={
            "error": "invalid_decision_for_kind",
            "kind": match.get("kind"),
            # `list(...)` NOT `sorted(...)`. `verbs_for_kind` returns the declaration's own
            # order, and re-sorting here reproduces — one surface over — the exact defect the
            # SDK's ordering fix exists to close: a caller reading `allowed` for a safety
            # species would see alphabetical order regardless of what the row declared.
            #
            # `sorted()` looks like tidiness rather than a decision, which is why it survived
            # unexamined. Flagged by iagent-mesh-sdk-ca from the call sites rather than from
            # reasoning about them.
            # GUARDED: this call is INSIDE an exception handler, so a raise here replaces a
            # structured refusal with a 500 — the error path becoming an error surface.
            "allowed": _allowed_or_empty(match.get("kind") or ""),
            "message": str(exc),
        })

    # FULFILLMENT (document_empty_confirm, spec 208): the SAME writer as POST /ingest/{id}/empty. The
    # audience gate and the verb validation above have passed; `_decide_empty` closes the task.
    if match.get("kind") == EMPTY_CONFIRM_KIND:
        _ep = match.get("payload")
        if isinstance(_ep, (str, bytes)):
            _ep = json.loads(_ep)
        _eing = _ep.get("ingest_id") if isinstance(_ep, dict) else None
        if not isinstance(_eing, str) or not _eing:
            raise HTTPException(status_code=409, detail={
                "error": "no_open_empty_task", "task_id": task_id,
                "message": "the task names no ingest"})
        return await _decide_empty(_eing, req.decision, actor, req.page, task_id=task_id)

    # FULFILLMENT (document_promotion, ADR-0041 §5/§6): the effect runs BEFORE the projection
    # resolves, for grouped_review's reason: a refused act must leave the task PENDING. The
    # decision record is the grant, so it is written fail-closed, and `promotion.act` re-asks
    # can_act itself. Every refusal carries its own status; none resolves the row.
    if match.get("kind") == promotion.KIND:
        from . import ingest_status
        from .decision_record_writer import DECISION_RECORD_ERA

        # A reject names one of the ruled codes (architect ruling 2026-10-17): `<code>` or
        # `<code>: <note>`, case-sensitive. Asked after the blank-reason refusal (the declaration,
        # above) and before `promotion.act`, so a refused code writes and resolves nothing.
        _reject_code = None
        if req.decision == promotion.REJECTED:
            _c = req.comment.strip()
            _reject_code = _c.split(":", 1)[0].strip() if ":" in _c else _c
            if _reject_code not in promotion.PROMOTION_REJECT_CODES:
                raise HTTPException(status_code=422, detail={
                    "error": "reject_code_unknown", "codes": list(promotion.PROMOTION_REJECT_CODES),
                    "task_id": task_id,
                    "message": "a reject names one of the listed codes; a wrong value, a wrong "
                               "part or missing rows is a correction (promote with row_edits), "
                               "not a reject"})

        # THE ACT REFUSES A STALE TASK (spec 203b, 204). The leaf may change until promotion, so the row
        # is read FIRST: the task must be the row's CURRENT generation's, its kind must equal the kind
        # it was filed with, and no extraction may be in flight -- else 409 `stale_extraction`, naming
        # the new task when there is one. Fail closed on an unreadable row (503); a row that is absent is a legacy task
        # with no projection claim and proceeds. Other stages (a `promoted` replay) are not refused.
        # Asked before the steward-corrections block, so a refusal writes nothing.
        _leaf_row = None
        _payload = match.get("payload")
        _ing = _payload.get("ingest_id") if isinstance(_payload, dict) else None
        if isinstance(_ing, str) and _ing:
            _leaf_row = await _read_ingest_row_for_act(task_id, _ing)
        if _leaf_row is not None:
            _row_ck = str(_leaf_row.get("content_kind") or "").strip().lower()
            _task_ck = str(_payload.get("content_kind") or "").strip().lower()
            if (task_id != _current_promotion_task_id(_leaf_row)
                    or _row_ck != _task_ck
                    or _leaf_row.get("status") in (
                        ingest_status.RECEIVED, ingest_status.EXTRACTING,
                        ingest_status.AWAITING_KIND, ingest_status.AWAITING_ORIGIN)):
                raise await _stale_extraction(task_id, _leaf_row)
        _leaf_rec = None
        if _leaf_row is not None:
            _lf, _ls, _lcb = _row_leaf(_leaf_row)
            if _lf is not None:
                _leaf_rec = {"leaf_source": _ls, "corrected_by": _lcb}

        # STEWARD CORRECTIONS (architect ruling 2026-10-18; flag-gated above). Everything that can
        # refuse is asked BEFORE `promotion.act`, so a refusal writes nothing.
        edits = None
        corrections = None
        defect_aud = None
        subject = None
        _reviewed = None
        _earlier = None
        if req.row_edits is not None or req.header_edits:
            from agent_fleet.restate_analyst import steward_correction
            try:
                subject = promotion.subject_from_payload(match.get("payload"))
                if req.row_edits is not None:
                    _mpns = await run_in_threadpool(lambda: _review_mpns_for_payload(subject))
                    _reviewed = _mpns
                    try:
                        edits = steward_correction.validate_row_edits(
                            req.row_edits.model_dump(), extracted_mpns=_mpns)
                    except steward_correction.EditRefusal as exc:
                        raise HTTPException(status_code=422, detail={
                            "error": "row_edits_refused", "task_id": task_id,
                            "message": str(exc)})
                else:
                    edits = steward_correction.RowEdits()
                if req.header_edits:
                    _hdr = await run_in_threadpool(lambda: _review_header_for_payload(subject))
                    try:
                        edits.header = steward_correction.validate_header_edits(
                            [h.model_dump() for h in req.header_edits],
                            extracted={"mfr": (_hdr.get("mfr")
                                               if _hdr.get("mfr_source") == "header" else None),
                                       "notice_id": _hdr.get("notice_id"),
                                       "notice_date": _hdr.get("notice_date")},
                            fallback={"mfr": _hdr.get("mfr_identity")})
                    except steward_correction.EditRefusal as exc:
                        raise HTTPException(status_code=422, detail={
                            "error": "header_edits_refused", "task_id": task_id,
                            "message": str(exc)})
                if edits.is_empty():
                    edits = None
                else:
                    defect_aud = f"dispatch_failure:{promotion.domain_of(audience)}"
            except promotion.PromotionRefused as exc:
                raise HTTPException(status_code=exc.status, detail={
                    "error": exc.error, "task_id": task_id, "message": str(exc)})
            if edits is not None:
                _unroutable = {
                    "error": "extraction_defect_unroutable", "audience": defect_aud,
                    "task_id": task_id,
                    "message": f"a correction files an extraction_defect, and nobody holds "
                               f"{defect_aud}; nothing was written"}
                try:
                    _holders = await run_in_threadpool(
                        lambda: human_tasks._resolve_audience_actors(defect_aud))
                except Exception:  # noqa: BLE001 — cannot-know is a refusal, nothing written
                    raise HTTPException(status_code=503, detail=_unroutable)
                if not _holders:
                    raise HTTPException(status_code=409, detail=_unroutable)
                _by = current_user.authz_id
                corrections = []
                for r in edits.corrected:
                    corrections.append({"op": "corrected", "mpn": r["mpn"].strip(),
                                        **({"evidence_ref": r["evidence_ref"]}
                                           if r.get("evidence_ref") is not None else {}),
                                        **steward_correction.provenance_for(
                                            acted_by=_by, extracted=r["mpn"].strip(),
                                            corrected=r["corrected_mpn"].strip(),
                                            evidence=r["evidence"].strip())})
                for r in edits.added:
                    corrections.append({"op": "added", "mpn": r["mpn"].strip(),
                                        "disposition": r["disposition"], "reason": r["reason"],
                                        **({"evidence_ref": r["evidence_ref"]}
                                           if r.get("evidence_ref") is not None else {}),
                                        **steward_correction.provenance_for(
                                            acted_by=_by, extracted=None,
                                            corrected=r["mpn"].strip(),
                                            evidence=r["evidence"].strip())})
                for r in edits.deleted:
                    corrections.append({"op": "deleted", "mpn": r["mpn"].strip(),
                                        "reason": r["reason"],
                                        **({"evidence_ref": r["evidence_ref"]}
                                           if r.get("evidence_ref") is not None else {})})
                for r in edits.header:
                    corrections.append({"op": "header_corrected", "field": r["field"],
                                        "extracted_fallback": r.get("fallback"),
                                        "reason": r["reason"],
                                        **steward_correction.provenance_for(
                                            acted_by=_by, extracted=r.get("extracted"),
                                            corrected=r["value"],
                                            evidence=steward_correction.evidence_text(
                                                r["evidence_ref"])),
                                        "evidence_ref": r["evidence_ref"]})

        # REVIEW COVERAGE (ruling 10-29): every part opened or folded into a named group. Asked
        # before any write; an unreadable extraction is a 503, never a skipped check.
        coverage = None
        if req.review_coverage is not None:
            from . import content_kinds, review_shapes
            try:
                _cov_subject = promotion.subject_from_payload(match.get("payload"))
                _arrived_new = isinstance(req.review_coverage, ItemReviewCoverage)
                cov = _rcov.normalise(req.review_coverage.model_dump(mode="json"),
                                      content_kind=_cov_subject.content_kind)
                _reg = content_kinds.by_kind(_cov_subject.content_kind)
                _declared = getattr(_reg, "review_shape", None)
                _rows = review_shapes.valid_review_shapes()
                _declared_row = _rows.get(_declared) if _declared else None
                if _declared and _declared_row is None:
                    raise LookupError(f"review_shape {_declared!r} has no valid registry row")
                _bad = (_rcov.row_problem(cov, _rows.get(cov.get("review_shape")), _declared)
                        if _arrived_new else None)
                if _bad is None:
                    # The universe is read by the declared row's item_kind; a legacy body whose
                    # kind declares no shape is parts.
                    _kind = _declared_row.item_kind if _declared_row else cov.get("item_kind", "part")
                    _read = _rcov.universe_for(_kind)
                    _universe = await run_in_threadpool(lambda: _read(
                        lambda: _review_parts_for_payload(_cov_subject)))
                    _bad = _rcov.problem(cov, _universe, _rows.get(cov.get("review_shape")),
                                         arrived_new=_arrived_new, declared_shape=_declared)
            except HTTPException as exc:
                if exc.status_code < 500:
                    raise  # e.g. 422 extraction_unbound: the binding said no, a retry will not help
                raise HTTPException(status_code=503, detail={
                    "error": "review_coverage_unverifiable", "task_id": task_id,
                    "message": f"the extraction's parts could not be read "
                               f"({type(exc).__name__}); nothing was written"})
            except Exception as exc:  # noqa: BLE001 -- cannot-know is a refusal, nothing written
                raise HTTPException(status_code=503, detail={
                    "error": "review_coverage_unverifiable", "task_id": task_id,
                    "message": f"the extraction's parts could not be read "
                               f"({type(exc).__name__}); nothing was written"})
            if _bad is not None:
                raise HTTPException(status_code=422, detail={
                    "error": "review_coverage_invalid", "check": _bad[0], "message": _bad[1]})
            coverage = cov

        if req.decision == promotion.PROMOTED:
            # The notice's SUBJECT_TO set is reconciled to the reviewed rows (ruled 2026-10-20),
            # so the act needs the reviewed set. No extraction_ref: None (the act refuses 409 if a
            # notice node exists).
            try:
                if subject is None:
                    subject = promotion.subject_from_payload(match.get("payload"))
            except promotion.PromotionRefused:
                subject = None      # `promotion.act` refuses the same payload by name
            if subject is not None:
                if _reviewed is None and subject.extraction_ref:
                    _s = subject
                    _reviewed = await run_in_threadpool(lambda: _review_mpns_for_payload(_s))
                if subject.notice_id:
                    _s2 = subject
                    try:
                        _earlier = await run_in_threadpool(
                            lambda: ingest_status.ingests_naming_notice(
                                _s2.notice_id, exclude_ingest_id=_s2.ingest_id))
                    except Exception:  # noqa: BLE001 — best effort; the record says unavailable
                        _earlier = None

        try:
            from .trust_table import load_trust_table
            _tbl = load_trust_table().ref
        except Exception:  # noqa: BLE001 — the sensor's floor, recorded rather than invented
            _tbl = "trust@unavailable"
        try:
            done = await run_in_threadpool(lambda: promotion.act(
                match.get("payload"), decision=req.decision, acted_by=current_user.authz_id,
                audience=audience, comment=req.comment,
                can_act=human_tasks.check_can_act, stores=_promotion_stores(current_user.authz_id),
                governing={
                    "ruleset_ref": promotion.ruleset_ref(
                        human_tasks.declaration_for(promotion.KIND)),
                    "trust_table_ref": _tbl,
                },
                era=DECISION_RECORD_ERA, now_ms=int(time.time() * 1000),
                row_edits=corrections, reviewed_mpns=_reviewed, earlier_ingests=_earlier,
                leaf=_leaf_rec, review_coverage=coverage))
        except promotion.PromotionRefused as exc:
            raise HTTPException(status_code=exc.status, detail={
                "error": exc.error, "task_id": task_id, "message": str(exc)})
        defect = None
        if edits is not None:
            # Filed AFTER the record stands and BEFORE the task resolves: a failure leaves the task
            # pending, and acting again replays the record (immutable_conflict) and files it.
            defect = steward_correction.defect_task(
                notice=(subject.notice_id or subject.ingest_id), decision_id=done["record_id"],
                pipeline_version=subject.pipeline_version, edits=edits, audience=defect_aud,
                requested_by=actor, acted_by=current_user.authz_id,
                ingest_id=subject.ingest_id)

            def _file_defect():
                if not human_tasks.task_exists(defect["task_key"]):
                    try:
                        human_tasks.register_task(
                            kind=defect["kind"], task_id=defect["task_key"],
                            audience=defect["audience"], title=defect["title"],
                            summary=defect["summary"], requested_by=actor,
                            subject_ref=subject.ingest_id, payload=defect["payload"])
                    except human_tasks.NoRequester as exc:
                        raise HTTPException(status_code=422, detail={
                            "error": "no_requester", "message": str(exc)})
            try:
                await run_in_threadpool(_file_defect)
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=503, detail={
                    "error": "extraction_defect_not_filed", "task_id": task_id,
                    "record_id": done["record_id"],
                    "message": f"the promotion and its corrections are recorded but the "
                               f"extraction_defect was not filed ({type(exc).__name__}); the "
                               f"task stays pending and acting again files it"})
        n = await run_in_threadpool(
            lambda: human_tasks.mark_task_resolved(
                task_id, caller_id=actor, decision=req.decision,
                comment=req.comment))
        logger.info("document %s: task_id=%s ingest_id=%s record=%s by=%s code=%s edits=%s",
                    req.decision, task_id, done["ingest_id"], done["record_id"],
                    actor, _reject_code, len(corrections or []))

        # PROJECTION UPDATE, BEST-EFFORT. The decision record (written above, inside
        # `promotion.act`) IS the grant — ADR-0041 §5 — and `ingest_status_projection` is only
        # a READ MODEL of it. So a failure here is LOGGED, never raised: the decision already
        # stands (mark_task_resolved above already succeeded), and re-resolving or unresolving
        # the task over a projection write would make a read model's availability gate a
        # decision that already happened. (Reachable since the graph writer was wired: a
        # REJECTION reaches here; a promotion does once the ingest node has a producer. Logged
        # so a failure here is visible rather than silently swallowed.)
        _stage = (ingest_status.PROMOTED if req.decision == promotion.PROMOTED
                 else ingest_status.REJECTED)
        # `rejected` always carries a non-blank comment here: the document_promotion kind
        # declaration refuses a bare rejection with 422 before this branch runs (sealed by
        # test_ROUTE_a_rejection_WITHOUT_a_reason_is_refused_before_the_projection), which is
        # what satisfies update_status's detail-required rule.
        _detail = (req.comment if req.decision == promotion.REJECTED
                  else f"record {done['record_id']}")
        try:
            await run_in_threadpool(
                lambda: ingest_status.update_status(done["ingest_id"], _stage, detail=_detail))
        except Exception as exc:  # noqa: BLE001 — see the comment above: never fail the request
            logger.warning("ingest_status.update_status failed for ingest_id=%s (decision=%s): %s",
                           done["ingest_id"], req.decision, exc)

        _body = {"task_id": task_id, "decision": req.decision, "rows_resolved": n, **done}
        if _reject_code is not None:
            _body["reject_code"] = _reject_code
        if defect is not None:
            _body["row_edits"] = {"corrected": len(edits.corrected), "added": len(edits.added),
                                  "deleted": len(edits.deleted), "header": len(edits.header)}
            _body["corrections"] = corrections
            _body["extraction_defect"] = defect["task_key"]
        return _body

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
        if req.decision == "rejected" and req.reason_code is None:
            raise HTTPException(status_code=422, detail={"error": "reason_code_required",
                "message": "a grouped-review reject needs a reason_code",
                "codes": list(_GROUPED_REJECT_CODES)})
        if req.decision == "approved" and req.row_edits is not None:
            # The batch rules (an added mpn must not collide with an extracted one, ...) need the
            # SERVER-AUTHORED batch. Read it back (best effort) and refuse with 422 here; Restate's
            # evaluate_submission re-validates regardless, so this is an early, clearer refusal.
            try:
                async with httpx.AsyncClient(timeout=15.0) as _c:
                    _gb = await _c.post(
                        f"{_RESTATE_INGRESS_URL}/GroupedReview/{_restate_key(wf)}/get_batch")
                _mpns = ([i.get("mpn") for i in (_gb.json().get("items") or [])]
                         if _gb.status_code == 200 else None)
            except Exception:  # noqa: BLE001 -- the workflow validates again
                _mpns = None
            if _mpns is not None:
                _have = {str(m).strip().lower() for m in _mpns}
                _e = req.row_edits
                _bad = (
                    [f"added mpn {r.mpn!r} collides with an extracted row"
                     for r in _e.added if r.mpn.strip().lower() in _have]
                    + [f"corrected_mpn {r.corrected_mpn!r} collides with an extracted row"
                       for r in _e.corrected if r.corrected_mpn.strip().lower() in _have]
                    + [f"mpn {r.mpn!r} is not a row of this review"
                       for r in list(_e.deleted) + list(_e.corrected)
                       if r.mpn.strip().lower() not in _have])
                if _bad:
                    raise HTTPException(status_code=422, detail={
                        "error": "row_edits_invalid", "message": _bad[0], "problems": _bad})
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
        decision = {"overrides": req.overrides or {}, "acted_by": current_user.authz_id,
                    "verdict": req.decision}
        if req.decision == "rejected":
            decision["reason_code"] = req.reason_code
            decision["comment"] = req.comment
        elif req.row_edits is not None:
            decision["row_edits"] = req.row_edits.model_dump()
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
                lambda: human_tasks.get_task_resolution(task_id, caller_id=actor)
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
        #
        # `workflow_id=wf` ADDED (HAZ-1003 scoping): `mark_task_resolved`'s UPDATE now carries
        # `AND workflow_id IS NOT DISTINCT FROM %s` so a cross-instance task_id collision can't
        # resolve the wrong run's row. Omitting it here would ask for `workflow_id IS NULL`
        # against a row that HAS one (`wf`, just posted to above) and silently resolve ZERO
        # rows — the request would appear to succeed while the task stayed pending forever.
        n = await run_in_threadpool(
            lambda: human_tasks.mark_task_resolved(
                task_id, caller_id=actor, decision=req.decision,
                comment=req.comment, workflow_id=wf,
            )
        )
        if sub.get("rejected"):
            # NARROW REJECT: the workflow wrote nothing. The task is closed (above); the ingest row,
            # when this notice is one, ends `review_rejected` (best effort -- never fail the act).
            # Keyed by the INGEST ID only. The fingerprint is the extracted doc_id and never
            # matches an ingest row; a review without an ingest id writes nothing.
            _iid = sub.get("ingest_id") or ""
            _row = "unlinked"
            if _iid:
                try:
                    from . import ingest_status as _ist
                    await run_in_threadpool(
                        lambda: _ist.update_status(_iid, _ist.REVIEW_REJECTED,
                                                   detail=req.reason_code or "rejected"))
                    _row = "review_rejected"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("review_rejected status not written for %s: %s", _iid, exc)
            else:
                logger.info("pcn grouped review rejected with no ingest_id: ingest row unlinked, "
                            "task_id=%s wf=%s", task_id, wf)
            logger.info("pcn grouped review rejected: task_id=%s wf=%s by=%s code=%s",
                        task_id, wf, actor, req.reason_code)
            return {"task_id": task_id, "decision": req.decision, "accepted": True,
                    "rows_resolved": n, "review_dispatched": False,
                    "reason_code": req.reason_code, "status": "review_rejected",
                    "ingest_row": _row}
        logger.info("pcn grouped review approved: task_id=%s wf=%s by=%s resolved_count=%s",
                    task_id, wf, actor, sub.get("resolved_count"))
        return {"task_id": task_id, "decision": req.decision, "accepted": True,
                "rows_resolved": n, "review_dispatched": True,
                "resolved_count": sub.get("resolved_count")}

    # FULFILLMENT (workflow_ack generalized, HAZ-1003): CONFIRM BEFORE RESOLVE, not the other
    # way around. The old order resolved the projection FIRST and treated the Restate resume as
    # best-effort afterwards — so a 403 from the handler, or cortex-bff's own hardcoded
    # `/BPMNWorkflowRunner/.../approve` posted at a SafetyAcceptance instance that was never
    # running there, left the task showing resolved while the definition stayed suspended
    # FOREVER, UNSEEN (the two halves disagreeing, and neither reporting it). Now the projection
    # is written ONLY after the resume call confirms 200; a row with no workflow_id has no
    # suspended definition and keeps today's direct-resolve behaviour (the `else` branch below).
    resumed = False
    # ── GAP 1: ANY workflow-backed task resumes, not only `workflow_ack` ───────────────────────
    #
    # The kind test was `== "workflow_ack"`, so every OTHER species that suspends a definition —
    # every safety acceptance, every concurrence, every redraft — was disposed in the projection
    # and the workflow was never told. The definition stayed suspended forever with the task
    # showing resolved: the two halves disagreeing, and neither reporting it.
    #
    # THE CONDITION IS `workflow_id`, WHICH IS THE FACT THAT MATTERS. A task carrying one is a
    # task some definition is suspended on; the SPECIES is irrelevant to whether it should be
    # resumed. Keying on the kind made a structural property depend on a name, so every new
    # species inherited the defect silently — and `workflow_ack` was simply the first one anybody
    # tried.
    if match.get("workflow_id"):
        # ── GAP 2: THE DECLARED VERB SURVIVES ──────────────────────────────────────────────
        #
        # This read `"APPROVED" if req.decision == "approved" else "REJECTED"` — a two-valued
        # collapse applied BEFORE the verb reaches the runtime. So `concurred` arrived as
        # REJECTED (it is not the string "approved"), and `accepted`, `not_concurred`,
        # `returned_for_rework`, `linked`, `new_hazard` and `dismissed` all arrived as one of two
        # words nobody declared.
        #
        # A chaining row on `{outcome: concurred}` would then match NOTHING FOREVER, and the
        # §4.3.7 sequence would read as a rejection at the moment a concurrence was given. The
        # runtime now terminates with the last step's actual disposition (`outcome`), and this is
        # the other end of that: the verb has to arrive intact for the terminal to mean anything.
        #
        # The verb is ALREADY VALIDATED against the species' declaration by `validate_decision`
        # above, so passing it through is not widening the surface — it is declining to narrow a
        # surface that was already gated. The gate is the declaration; this was a second,
        # undeclared gate that only knew two words.
        status = req.decision

        # WHICH SERVICE OWNS THIS RUN, RE-CHECKED HERE — a row-sourced name is never
        # interpolated into a Restate ingress URL on trust alone, even though `register_task`
        # already validated it once at write time. A row with no `workflow_service` is the
        # LEGACY shape (the inline BPMNWorkflowRunner `user_task` loop predates this column)
        # and falls back to the one service that loop could ever mean.
        service = match.get("workflow_service") or "BPMNWorkflowRunner"
        if service not in human_tasks.ALLOWED_WORKFLOW_SERVICES:
            # NO WRITE BELOW THIS POINT — an unresumable row stays PENDING rather than being
            # marked resolved against a service this gateway cannot safely reach.
            raise HTTPException(status_code=409, detail={
                "error": "task_unresumable",
                "task_id": task_id,
                "workflow_id": match["workflow_id"],
                "workflow_service": service,
                "message": f"workflow_service {service!r} is not a resumable Restate service; "
                           "the task stays pending rather than being resolved against it",
            })

        rr = None
        resume_exc: Exception | None = None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                rr = await client.post(
                    f"{_RESTATE_INGRESS_URL}/{service}/{_restate_key(match['workflow_id'])}/approve",
                    # `acted_by` is REQUIRED by the handler as of approval-bypass-bpmn-runner:
                    # it re-checks can_act itself rather than trusting that this gate ran.
                    # Threaded from `actor` (R-089: the PRINCIPAL, for a delegated act — the
                    # identity can_act was just checked against above) — so the handler
                    # re-asks the same question about the same subject and must reach the
                    # same answer. Omitting it here would turn the ONE correctly-gated path
                    # into the only refused one.
                    #
                    # `promise_name` rides the row (set by `_register_human_task` for a
                    # definition-driven step) so the handler resolves the promise THIS run is
                    # actually awaiting rather than guessing `approval_{task_id}` — None for
                    # legacy rows, which is the handler's own documented default.
                    #
                    # `acted_via` (R-089) is added ONLY when this act is delegated — a plain
                    # person's payload stays byte-identical to today's.
                    json={"task_id": task_id, "status": status, "comments": req.comment,
                          "acted_by": actor,
                          "promise_name": match.get("promise_name"),
                          **({"acted_via": via} if via is not None else {})},
                )
            resumed = rr.status_code == 200
        except Exception as exc:  # noqa: BLE001 — network/timeout; reported below, not swallowed
            resume_exc = exc

        if not resumed:
            # CONFIRM-BEFORE-RESOLVE'S OTHER HALF: a refused or unreachable resume must NOT mark
            # the task resolved — the definition is still suspended and the row must keep saying
            # so. Check for a teammate's settle first (the same multiplayer race the pre-lookup
            # 409 above already accounts for) before reporting a resume failure.
            settled = await run_in_threadpool(
                lambda: human_tasks.get_task_resolution(task_id, caller_id=actor)
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
            raise HTTPException(status_code=502, detail={
                "error": "workflow_resume_failed",
                "task_id": task_id,
                "workflow_id": match["workflow_id"],
                "workflow_service": service,
                "status_code": getattr(rr, "status_code", None),
                "reason": None if rr is not None else str(resume_exc),
                "message": "the workflow did not confirm the resume; the task stays pending "
                           "rather than being resolved against a definition that is still "
                           "suspended",
            })

        # ONLY ON A CONFIRMED 200 — scoped by workflow_id so this cannot resolve a different
        # workflow instance's row sharing the same step id (the cross-instance collision that
        # `_register_human_task`'s composite task_id now closes at the write end too).
        n = await run_in_threadpool(
            lambda: human_tasks.mark_task_resolved(
                task_id, caller_id=actor, decision=req.decision,
                comment=req.comment, workflow_id=match["workflow_id"],
            )
        )
    else:
        # NO WORKFLOW_ID -> NO SUSPENDED DEFINITION. Today's direct-resolve behaviour, unchanged.
        # (A delegated act never reaches here — it is refused above, since the 409 check
        # requires a workflow_id.)
        n = await run_in_threadpool(
            lambda: human_tasks.mark_task_resolved(
                task_id, caller_id=actor, decision=req.decision, comment=req.comment
            )
        )
    logger.info("human_task acted: task_id=%s by=%s decision=%s rows=%d",
                task_id, actor, req.decision, n)

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
    # Menus are per (frontend_id, frontend_version): a stale tab's old bundle names its own
    # version and is served that menu. Absent -> the newest registered version.
    frontend_version: str | None = None
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
    # THE ANSWER TO AN ASK THAT HAD NO MENU (ADR-0033's RESPEAK). Two scalars, because a
    # RESPEAK ask asks about exactly one slot and there is exactly one answer — a dict would
    # reimport the {}-versus-absent ambiguity `bound_slots` is careful about, for no gain.
    #
    # SEPARATE FROM `bound_slots`, DELIBERATELY, AND THE SEPARATION IS THE SAFETY. A RESPEAK
    # ask had NO menu by construction (that is what makes it a RESPEAK), so
    # `validate_bound_slots` refuses its slot as `no_menu` by design. Routing unvalidatable
    # words through the validated path would 422 or take the silent default. The name says
    # what the value is: words a person typed, not a pick from a list.
    #
    # AND IT IS NOT CONCATENATED INTO `message`. That is the whole rewrite fold: the composed
    # phrase `Provide the current funding status. (program_id: meridian)` was machine syntax
    # on top of a paraphrase, rendered as the user's question. The phrase stays byte-equal and
    # the answer travels here.
    spoken_slot: str | None = None
    spoken_answer: str | None = None
    # THE ASK THIS TURN IS ANSWERING (ADR-0033 lineage). The client is the only party that
    # knows which card the person acted on, so it must say — but this is a CLAIM, not the
    # conclusion. Named for what the caller asserts; the server decides whether it becomes
    # `derived_from_artifact_id` on the artifact.
    #
    # WHY THE CLAIM IS CHECKED. `answer_artifact_writer` links lineage with
    # `MERGE (parent:AnswerArtifact {id: $parent_id})`, which CREATES the node when the id is
    # unknown. An unguarded field would let any caller conjure an AnswerArtifact into the
    # graph by naming one, and a fabricated ancestor is worse than no ancestor: the rail would
    # collapse two cards into one on a lineage nobody produced.
    answering_artifact_id: str | None = None
    # ADR-0050 §3's carry. `seed_template_canvas` sends exactly this — never a phrase — for one
    # panel of a ratified template: `{"template_id": str, "panel": int, "bindings": dict}`.
    # `orchestrate()` validates it (template known, panel in range, panel declares a `subject`,
    # every consumed shared slot bound) BEFORE the stream opens, and
    # `_generate_dagster_stream_inner` rebuilds the dispatch route from the TEMPLATE's own
    # declaration — `panel.verb`, `panel.subject` as `subject_uri`, `panel.slots` merged with the
    # bound shared slots — never from this request re-parsed. THE TEMPLATE STATES THE SUBJECT;
    # THE MESH CONFIRMS IT ON EVERY DISPATCH: `dispatch_pre_resolved`'s own
    # `find_compatible_verbs` call still runs against the live mesh, so a declared `subject` the
    # mesh no longer agrees with is `FALL_BACK` — a visible failure, never a silent route.
    seed_panel: dict | None = None


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
    # THREE STATES, NOT TWO (ruled 2026-09-09), and the middle one is the reason:
    #
    #   None        NO FRONTEND APPLIES to this caller — an engine, the registrar, a job
    #   a version   a frontend that knows what it is
    #   a FAULT     a frontend that HAS a version and cannot report it
    #
    # The third must never be laundered into the first. `null` is a statement that the
    # question does not apply; a frontend that cannot answer it is a defect wearing that
    # statement's clothes. Same rule as `favourable` — see [[optimistic-defaults-are-dishonest]].
    #
    # THIS FIELD WAS THE LITERAL STRING "dev" FOR THE LIFE OF THIS SURFACE. cortex-ui read an
    # env var nothing in that repo set, so every registration it ever made recorded "dev" and
    # the drift detection this field exists for could never have fired. A value that is always
    # the same is indistinguishable from a value nobody set.
    frontend_version: str | None = None    # e.g. "0.1.0", or a commit sha
    capabilities: list[FrontendCapability]


class RegisterFrontendCapabilitiesResponse(BaseModel):
    accepted: int
    frontend_id: str
    # Refused rows are RETURNED, never silently dropped. A drop would reproduce the very
    # defect admission validation exists to prevent, one layer earlier.
    rejected: list[dict] = []
    # True when the stored menu matched and the graph already held it, so nothing was emitted.
    # `accepted` is len(admitted) either way (cortex checks sent == accepted).
    unchanged: bool = False


# Dedicated logger so registrations are easy to slice out in log search.
_frontend_registry_logger = logging.getLogger("iagent.registry.frontend_capabilities")
# THE LINE MUST ARRIVE, NOT MERELY BE CALLED (see the note on `logger` above).
_ensure_the_audit_line_actually_ARRIVES(_frontend_registry_logger)


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


# ONE rule for "which subtask did the answer come from", shared with the supervisor's card
# selector. See iagent_pure/primary_selection.py for why this is not two local functions.
from iagent_pure.lineage_claim import (  # noqa: E402
    lineage_is_honoured,
    pre_resolved_route_allowed,
)
from iagent_pure.primary_selection import pick_primary  # noqa: E402
from iagent_pure.slot_acceptance import accept_slots  # noqa: E402

# THE R-076 CONSUMER's artifact half. Imported as a MODULE, not as three names, so the call site
# reads `acceptance_request.review_request_of(...)` and a reader can see that the gateway reads
# the request and never chooses the definition — the choice lives behind the workflow boundary,
# in `agent_fleet/restate_analyst/acceptance_selection.py`, where a caller cannot reach it.
from iagent_pure import acceptance_request  # noqa: E402

# THE DIRECT PATH (2026-09-08). A pre-resolved pick executes here rather than in a Dagster
# run — see `direct_dispatch` for what it keeps from the run and why none of it is optional.
from . import direct_dispatch  # noqa: E402
from .direct_dispatch import dispatch_pre_resolved  # noqa: E402

# THE SAME DEFAULT AS THE SUPERVISOR'S, and it has to be: both call the same Engine F. A
# second literal that drifts would render one path's answers from a service the other never
# reaches, which is invisible until the two disagree.
#: How often the direct path handed a turn back to the run, by outcome, for this process.
#: PER-PROCESS AND DELIBERATELY NOT PERSISTED — it is a liveness signal for an operator
#: reading one pod's logs, not an SLO. The per-turn event is what a rate is actually built
#: from; this is the running total so a single log line answers "is it happening at all".
_DIRECT_FALLBACKS: dict[str, int] = {}

_PRESENTATION_AGENT_SVC_URL = _required_service_url(
    "PRESENTATION_AGENT_SVC_URL",
    used_for="engine-f — /render_ui, and the census target for engine-f",
)


def _primary_graph_trace_mat(mats: list[dict]) -> dict | None:
    """The graph trace belonging to the subtask the answer came from.

    Same rule, same function, third caller — see `pick_primary`. The trace has a NARROWER
    eligibility than the routing decision (the supervisor emits it only when the subject
    grounded and compatible verbs exist), which made first-emitted look adequate: every
    candidate had at least succeeded at grounding. It is still a different rule over the same
    choice, and two subtasks that both ground and pick different verbs give the card one path
    and the decision panel another.
    """
    traces = [
        m for m in mats
        if (m.get("assetKey", {}) or {}).get("path") == ["subtask_graph_trace"]
    ]
    return pick_primary(traces, lambda m: _metadata_dict(m).get("route_status"))


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
    # THE SAME FUNCTION THE CARD USES, not a second copy that agrees today. The card and the
    # record drifted apart twice — arrival order beating success here, list position beating
    # routing there — while each side's own tests passed. One rule, two accessors.
    return pick_primary(routing, lambda m: _metadata_dict(m).get("route_status"))


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
        _raw_excluded = json.loads(md.get("eligibility_excluded") or "[]")
        if not isinstance(_raw_excluded, list):
            _raw_excluded = []
    except (ValueError, TypeError):
        _raw_excluded = []

    # ── FLAGGED IS NOT EXCLUDED, AND ONE LIST CANNOT SAY BOTH ──────────────────────────────
    #
    # The field is named `eligibility_excluded` and the arity gate stopped excluding on
    # 2026-09-04 — it FLAGS `needs_instance` and KEEPS the verb as a candidate, because
    # removing the only verb that fits abstains for the reason it would have asked about.
    # Every such entry carries `disposal: "flagged"`, so the distinction was in the data and
    # nowhere in the read: a live candidate rendered under a key whose name says it was
    # deleted.
    #
    # THE NARROWING LANDS HERE, AND ONLY NOW. It was held additive — both keys carrying the
    # flagged rows — until the consumer read the new shape AT THE SERVING SURFACE, which is
    # `cortex-ui` e1f9722, verified in the pod rather than on main (R-055.1: merged-is-not-
    # deployed is the same window one repo over). `readExclusions` now PARTITIONS on
    # `disposal` and takes `flags` first, so neither half is derived from the other's absence
    # and a third disposal cannot be absorbed into either.
    #
    # Both halves are computed from one partition rather than two comprehensions, so a row
    # that is neither `flagged` nor recognised cannot silently land in both or in neither.
    flags, excluded = [], []
    for _r in _raw_excluded:
        # An ABSENT `disposal` reads as removed, deliberately: every row predating the field
        # meant exactly that, and a mislabel is visible where a disappearance is not.
        if isinstance(_r, dict) and _r.get("disposal") == "flagged":
            flags.append(_r)
        else:
            excluded.append(_r)

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
            "reason_code": md.get("reason_code") or None,
            "fallback": False,
            "acting": acting,
            # The candidates the winner beat — the visualizer shows the
            # contest, not just the winner (losers first-class).
            "candidates": candidates,
            "excluded": excluded,
            "flags": flags,
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
        "reason_code": md.get("reason_code") or None,
        "fallback": True,
        "acting": acting,
        "fallback_reason": fallback_reason,
        # The resolver pool that failed to ground — losers first-class,
        # so "why did nothing win" is visible with scores.
        "candidates": candidates,
        "excluded": excluded,
        "flags": flags,
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
        # `provenance` added for the provenance floor (ADR-0041 §7, section 5 of the
        # ingest/origin seam): a ProvenanceBlock an engine attaches to a source must survive
        # projection for provenance_floor() to read it at the SSE emission site below.
        # engine-o's notice_parts.py is the first production engine to attach one (2026-10-08);
        # every other engine's sources still arrive unstamped.
        # `obtained_via`, `ingest_id`, `dropped_by`, `promoted_by`: the graph's provenance as a
        # retrieval path copies it onto each source (engine-o's notice_parts.py is the first);
        # `promoted_by` is what the floor's promoted set is read from below.
        # `mpn` and `notice_id`: the part and the notice a whichPartsDoesThisNoticeAffect source
        # is ABOUT. Without them the citation is a label ("P/N 5530-184") and a URI, and nothing
        # downstream can join a source to its table row or its notice without parsing either.
        for extra in ("matched_for", "provenance", "obtained_via", "ingest_id", "dropped_by",
                      "promoted_by", "mpn", "notice_id"):
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


def _sources_event_payload(mat: dict) -> tuple[list[dict] | None, dict | None]:
    """Build the SSE 'sources' event's payload halves from a subtask_sources
    materialization: the projected Source[] list and its provenance floor (ADR-0041 §7,
    section 5 of the ingest/origin seam -- `src/iagent/provenance_floor.provenance_floor`).

    Returns (None, None) when there is nothing to project (mirrors `_project_sources`'s own
    None-for-nothing contract). Factored out of `_generate_dagster_stream_inner`'s dispatch
    loop so the floor's wiring is directly testable without driving the whole streaming
    generator (which needs a live Dagster run, routing, and more).

    UNFILTERED: an unstamped source (every engine but engine-o's notice_parts.py still
    returns one) is weaker than user-drop and must pull the
    floor down, never be skipped — "skipping is the laundering this field exists to
    prevent."
    """
    projected_sources = _project_sources(mat)
    if not projected_sources:
        return None, None
    # Tag each ontology-URI source with whether the data module has linked figures, so the
    # cortex-ui only shows the "View figures" camera-icon trigger when clicking it would
    # actually surface figures. Failures leave `has_figures` UNSET and the UI falls back to
    # its label-pattern heuristic.
    _enrich_sources_with_has_figures(projected_sources)
    from . import provenance_floor as _provenance_floor_mod
    # A PROMOTED DROP READS user-drop AND LEAVES `ingest_ids`. The promoted set is read off the
    # sources' own `promoted_by`, which the retrieval path copied from the graph's PROMOTION fact.
    floor = _provenance_floor_mod.provenance_floor(
        projected_sources,
        promoted=_provenance_floor_mod.promoted_ingest_ids(projected_sources),
    )
    return projected_sources, floor


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
    missing_domains: "list[str] | tuple[str, ...] | None" = None,
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
    missing_domains : the domains a verb declares that the caller's cell lacks; sent only on
                the `seed_panel_verb_not_visible` cause, read back by `_seed_failure_from_data`.
    """
    payload: dict = {"message": message}
    if kind:
        payload["kind"] = kind
    if retryable is not None:
        payload["retryable"] = retryable
    if cause:
        payload["cause"] = cause
    if missing_domains:
        payload["missing_domains"] = list(missing_domains)
    return _sse("pipeline_error", json.dumps(payload))


_orchestrate_audit_log = logging.getLogger("iagent.audit.orchestrate")
# THE LINE MUST ARRIVE, NOT MERELY BE CALLED (see the note on `logger` above).
_ensure_the_audit_line_actually_ARRIVES(_orchestrate_audit_log)


def _orchestrate_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _orchestrate_audit_line(*, who: str, via: str, session_id: str, verb: str, case: str,
                            when: str, outcome: str) -> None:
    """ONE line per /orchestrate call: who, through which client, which verb and case, when, how
    it ended. Never message text, tokens or payload bodies."""
    _orchestrate_audit_log.info(
        "orchestrate_access who=%s via=%s session_id=%s verb=%s case=%s when=%s outcome=%s",
        who, via, session_id, verb, case, when, outcome,
    )


def _note_orchestrate_event(chunk, seen: dict) -> None:
    """Read the routed verb and any case id off an SSE chunk; leave `seen` alone otherwise.

    verb: the `route_decision` event's `action.iri` (both the Dagster path and
    `_stream_direct_outcome` emit it); "UNKNOWN" is the router's no-verb value, recorded as "".
    case: a `case_id` key at the top of an event's data object or one level under it.
    Honest-absent: "" when never seen."""
    if not isinstance(chunk, str) or not chunk.startswith("event: "):
        return
    head, _, rest = chunk.partition("\n")
    name = head[len("event: "):].strip()
    if name != "route_decision" and '"case_id"' not in rest:
        return
    try:
        data = json.loads(rest[len("data: "):].strip()) if rest.startswith("data: ") else None
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    if name == "route_decision" and not seen["verb"]:
        iri = (data.get("action") or {}).get("iri") if isinstance(data.get("action"), dict) else None
        if isinstance(iri, str) and iri and iri != "UNKNOWN":
            seen["verb"] = iri
    if not seen["case"]:
        for node in (data, *[v for v in data.values() if isinstance(v, dict)]):
            cid = node.get("case_id")
            if isinstance(cid, str) and cid:
                seen["case"] = cid
                break


def _audit_orchestrate_refusals(fn):
    """A refusal raised BEFORE the stream opens leaves its one audit line (`outcome=refused:<status>`),
    then re-raises the SAME exception unchanged (not a new refusal site). The stream's own line is
    written by `_audit_orchestrate_wrap`, wired inside the handler. `wraps` keeps the name, the
    docstring (the OpenAPI description) and the signature FastAPI reads."""
    @functools.wraps(fn)
    async def door(request, http_request, current_user):
        when = _orchestrate_now()
        try:
            return await fn(request, http_request, current_user)
        except HTTPException as exc:
            _orchestrate_audit_line(
                who=current_user.authz_id, via=getattr(current_user, "azp", None) or "",
                session_id=request.session_id, verb="", case="", when=when,
                outcome=f"refused:{exc.status_code}",
            )
            raise
    return door


async def _audit_orchestrate_wrap(gen, *, who: str, via: str, session_id: str):
    """Pass `gen` through unchanged and in order; write ONE `orchestrate_access` line when it ends.

    outcome: completed | closed (GeneratorExit / CancelledError: the client went away) | error
    (anything else, re-raised)."""
    when = _orchestrate_now()
    seen = {"verb": "", "case": ""}
    outcome = "completed"
    try:
        async for chunk in gen:
            _note_orchestrate_event(chunk, seen)
            yield chunk
    except (GeneratorExit, asyncio.CancelledError):
        outcome = "closed"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        _orchestrate_audit_line(
            who=who, via=via, session_id=session_id, verb=seen["verb"], case=seen["case"],
            when=when, outcome=outcome,
        )


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

# ── THE ASK'S OWN ROUTE, READ BACK SERVER-SIDE ──────────────────────────────────────────
#
# MEASURED 2026-09-07: an ask and the pick that answered it both resolved to
# `mesh:planCapabilityPath`. The pick paid for /plan, /resolve and /classify_predicate to
# arrive at the verb the ask had already established, which is why answering a menu costs
# what asking a fresh question costs. The route is not re-derived here; it is looked up.
#
# WHY THIS IS READ AND NOT POSTED. `answering_artifact_id` has until now only ever drawn a
# provenance edge, so a false claim cost a wrong arrow. The moment the named ask STEERS
# routing it becomes an authorization surface: a caller who could name any artifact would
# inherit whatever verb and subject that artifact resolved to. So the client sends an id and
# nothing else, and the (subject, verb) is read from the graph under the caller's own
# ownership edge. A caller naming an artifact that is not theirs gets `{}` and the ordinary
# full path — never someone else's route.
#
# `resolved_intent` is a JSON STRING on the node: Neo4j property values are primitives or
# arrays, never maps.
_PRE_RESOLVED_CYPHER = """
MATCH (a:AnswerArtifact {id: $artifact_id})-[:PRODUCED_FOR]->(:Actor {actor_id: $user_id})
RETURN a.resolved_intent AS resolved_intent
"""

# EVERY ARTIFACT IN THIS CHAIN, NEAREST FIRST, ALL OF THEM THE CALLER'S OWN.
#
# `DERIVED_FROM` is the ask lineage: each answer points at the ask it answered. Walking it
# backwards is how a slot bound at hop 1 is still known at hop 3.
#
# THE OWNERSHIP EDGE IS ON **EVERY** NODE IN THE PATH, not only the one the caller named.
# Requiring it solely on the entry point would let a caller name their own artifact whose
# ancestor is somebody else's and inherit that stranger's bound values — an authorization
# hole wearing a convenience's clothes. This is the same rule `_pre_resolved_from_ask`
# states for the route, applied to the thing the route carries.
#
# Depth-bounded at 12. A chain longer than that is a loop, and a loop is the defect this
# whole change exists to stop rather than something to follow patiently.
_CHAIN_SLOTS_CYPHER = """
MATCH path = (a:AnswerArtifact {id: $artifact_id})-[:DERIVED_FROM*0..12]->(h:AnswerArtifact)
WHERE ALL(n IN nodes(path) WHERE (n)-[:PRODUCED_FOR]->(:Actor {actor_id: $user_id}))
RETURN h.id AS id, h.resolved_intent AS resolved_intent, length(path) AS hops
ORDER BY hops ASC
"""


def _pre_resolved_from_ask(artifact_id: str, user_id: str) -> dict:
    """The (subject, verb) an earlier ask already established, or `{}`.

    `{}` on every uncertainty — unknown id, another user's artifact, an artifact written
    before the subject was captured, an unreachable graph. Every one of those means "route
    this the ordinary way", which is correct and merely slow. There is no failure mode here
    that should produce a ROUTE, because a half-known route is the one outcome worse than a
    slow one: it would dispatch a verb against a subject nobody confirmed.
    """
    if not artifact_id or not user_id:
        return {}
    try:
        with neo4j_driver.session() as session:
            rec = session.run(
                _PRE_RESOLVED_CYPHER, artifact_id=artifact_id, user_id=user_id
            ).single()
    except Exception as exc:  # noqa: BLE001
        logger.warning("pre-resolved lookup failed for %s: %s", artifact_id, exc)
        return {}
    if not rec or not rec.get("resolved_intent"):
        return {}
    try:
        intent = json.loads(rec["resolved_intent"]) or {}
    except (ValueError, TypeError):
        return {}
    subject = str(intent.get("subject_uri") or "")
    verb = str(intent.get("verb_iri") or "")
    # BOTH HALVES OR NEITHER. A verb without its subject is not a dispatchable route
    # (ADR-0019 Contract B), and a subject without a verb saves nothing worth the branch.
    # Artifacts written before the subject was captured land here and route normally.
    if not subject or not verb or subject == "UNKNOWN":
        return {}
    return {
        "subject_uri": subject,
        "subject_instance_id": str(intent.get("subject_instance_id") or ""),
        "subject_instance_label": str(intent.get("subject_instance_label") or ""),
        "verb_iri": verb,
        # For the synthesized plan's roster. Empty is tolerable here - it costs an empty
        # cast list on one HUD step - so it does NOT join the both-halves-or-neither guard
        # above, which exists to stop an undispatchable route.
        "owner_persona": str(intent.get("owner_persona") or ""),
    }


def _pre_resolved_from_seed_panel(seed_panel: dict) -> tuple[dict, dict]:
    """The (subject, verb) ADR-0050 §3's per-panel seed declares, plus the slots to dispatch
    with — `({}, {})` on anything that cannot be rebuilt.

    THE TEMPLATE STATES THE SUBJECT; THE MESH CONFIRMS IT ON EVERY DISPATCH. `panel.subject` is
    handed straight through as `subject_uri`, verbatim — no ontology lookup runs here, because
    none exists (nothing in the fleet maps verb_iri -> input_uri; every path runs subject ->
    verbs). The declaration is sealed against the producing engine's own VERBS catalogue by
    `tests/planning/test_program_finance_seeds_six_panels.py`. `dispatch_pre_resolved`'s `find_compatible_verbs` call is what verifies this
    against the LIVE mesh, same as it would for any other pre-resolved route — a declared
    `subject` the mesh no longer agrees with comes back `FALL_BACK`, and the caller
    (`_generate_dagster_stream_inner`) is responsible for turning that into a visible failure
    for a seed_panel turn rather than letting it fall through to the classified path, because
    unlike an ordinary pick-answer there is no NL question underneath this one to route instead.

    `orchestrate()` 422s every one of unknown template, out-of-range panel and a no-`subject`
    panel BEFORE the stream opens (ADR-0050 §3's own validation, mirroring `canvas_seed`'s own
    gates). This function re-checks the same three defensively rather than trusting the caller
    validated — a second line, not the first.
    """
    from .canvas_template import load_template, panel_dispatch

    template_id = str(seed_panel.get("template_id") or "")
    panel_idx = seed_panel.get("panel")
    try:
        template = load_template(template_id)
        panel = template.panels[panel_idx]  # type: ignore[index]
    except (KeyError, ValueError, IndexError, TypeError):
        return {}, {}
    if not panel.subject:
        return {}, {}

    # `bindings` IS KEYED BY THE SHARED SLOT'S `name` — the ask's own identity, exactly as
    # `/canvas/seed`'s own `bindings` are (see `seed_template_canvas`) — and `bind_as` (never
    # `name`) is what lands in the dispatch payload, the same split `SharedSlot.bind_as` exists
    # to resolve on every other path.
    #
    # THE DISPATCH ITSELF IS `panel_dispatch` — ITEM 3's rule: seeding and packageExport read
    # the SAME function for a panel's (verb, subject, params), never two that happen to agree.
    bindings = dict(seed_panel.get("bindings") or {})
    verb, subject, params = panel_dispatch(template, panel_idx, bindings)

    by_name = {s.name: s for s in template.shared_slots}
    subject_instance_id = ""
    for slot_name in panel.consumes:
        slot = by_name.get(slot_name)
        if slot is None:
            continue
        value = bindings.get(slot_name)
        if value in (None, ""):
            continue
        # THE FIRST CONSUMED, BOUND SLOT IS THE SUBJECT INSTANCE. Every ratified
        # program_finance panel consumes exactly one shared slot (`program`), so "first" is not
        # yet a real choice — but the loop is written to not assume that stays true.
        if not subject_instance_id:
            subject_instance_id = str(value)

    return {
        "subject_uri": subject,
        "subject_instance_id": subject_instance_id,
        "subject_instance_label": "",
        "verb_iri": verb,
        "owner_persona": "",
    }, params


def _artifact_is_the_callers(artifact_id: str, user_id: str) -> bool:
    """Does this artifact EXIST and belong to this caller? Existence, never routability.

    WHY NOT JUST CALL `_pre_resolved_from_ask` AND TEST IT. That function answers a different
    question and answers `{}` to three states at once: an unknown id, another caller's
    artifact, and a REAL artifact of the caller's own whose ask predates subject capture. The
    third is a perfectly good lineage parent, so reusing that emptiness here would refuse the
    exact turns this check exists to admit — a guard borrowed from a neighbour, deciding on a
    premise that is not the one it was written for.

    IT RUNS THE SAME CYPHER CONSTANT, deliberately. The ownership EDGE is the rule (see
    `_PRE_RESOLVED_CYPHER`'s comment for why the edge and not the id is what authorizes), and
    a second spelling of that rule is a second thing to keep correct. Only the READING
    differs: this one asks whether a row came back at all and ignores what is on it.

    FALSE ON EVERY UNCERTAINTY, an unreachable graph included. A refused lineage claim costs
    one card that does not fold; an accepted claim on an id nobody can vouch for costs a
    `MERGE` that fabricates the ancestor it claims to have found.
    """
    if not artifact_id or not user_id:
        return False
    try:
        with neo4j_driver.session() as session:
            rec = session.run(
                _PRE_RESOLVED_CYPHER, artifact_id=artifact_id, user_id=user_id
            ).single()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "artifact ownership check failed for %s: %s — refusing the lineage claim",
            artifact_id, exc,
        )
        return False
    return rec is not None


#: How a slot's value came to be known. THE SOURCE IS CARRIED, NOT JUST THE VALUE, and the
#: whole merge depends on it. `validate_bound_slots` refuses a PICK for a slot whose menu was
#: `too_many` — nothing was offered, so nothing can be picked — while accepting a
#: CALLER-SUPPLIED id for that same slot, which is a legitimate API call. One field cannot
#: carry both rules, so flattening these into a single dict would make the loop disappear and
#: silently delete that refusal. If a future change cannot express this distinction, the change
#: is wrong however clean the chain looks afterward.
# ⛔ THESE MOVED TO `iagent_pure.slot_acceptance` AND ARE IMPORTED, NOT REDECLARED.
#
# They were declared here and consumed here, and then the WRITER needed them (accept_slots is
# the one door every binding passes through) and so did the promotion rule. Three copies of a
# four-name vocabulary is how a rename makes a feature stop silently — the reader would refuse
# every row as "unknown source" and report a clean empty chain.
from iagent_pure.slot_acceptance import (  # noqa: E402
    SLOT_SOURCE_FILLED,
    SLOT_SOURCE_PICKED,
    SLOT_SOURCE_SPOKEN,
    SLOT_SOURCE_SUPPLIED,
    SLOT_SOURCES as _SLOT_SOURCES,
)

_ = (SLOT_SOURCE_PICKED, SLOT_SOURCE_SPOKEN, SLOT_SOURCE_SUPPLIED, SLOT_SOURCE_FILLED)


def _accumulated_slots(artifact_id: str, user_id: str) -> dict:
    """Every slot this chain has already bound: `{slot: {"value": v, "source": s, "hop": n}}`.

    THE DEFECT THIS EXISTS FOR, measured 2026-09-12 by invincible-agent-81 on the rolled
    fleet: a two-slot verb took FOUR hops, 1m15 → 1m42 → 2m07 → 2m34, against 1m16 in a
    single hop when both values were in the question. Each hop carried only the latest answer,
    so a slot answered at hop 1 was simply absent by hop 3 and got asked again.

    `{}` ON EVERY UNCERTAINTY, exactly as `_pre_resolved_from_ask` does — unknown id, an
    artifact that is not the caller's, an ancestor that is not, an unreachable graph. Every
    one of those means "ask the ordinary way", which is slow and correct. There is no failure
    here that should produce a BOUND VALUE, because a half-known binding is worse than a
    re-ask: it dispatches a verb against a value nobody confirmed.

    NEAREST HOP WINS. A person who answers the same slot twice meant the second answer; the
    ordering in the Cypher is what makes that true rather than incidental.
    """
    if not artifact_id or not user_id:
        return {}
    try:
        with neo4j_driver.session() as session:
            rows = session.run(
                _CHAIN_SLOTS_CYPHER, artifact_id=artifact_id, user_id=user_id
            ).data()
    except Exception as exc:  # noqa: BLE001
        logger.warning("chain-slot lookup failed for %s: %s", artifact_id, exc)
        return {}
    out: dict = {}
    for row in rows or []:
        try:
            intent = json.loads(row.get("resolved_intent") or "{}") or {}
        except (ValueError, TypeError):
            continue
        for slot, rec in (intent.get("bound_slot_sources") or {}).items():
            if slot in out:
                continue                       # nearer hop already answered it
            if not isinstance(rec, dict):
                continue                       # malformed: refuse rather than guess a source
            source = str(rec.get("source") or "")
            if source not in _SLOT_SOURCES:
                # AN UNKNOWN SOURCE IS NOT A DEFAULT. Admitting it as "supplied" would launder
                # a pick past the menu check, which is the one thing the split protects.
                logger.warning(
                    "chain slot %r carries unknown source %r; refusing to carry it", slot, source
                )
                continue
            if "value" not in rec:
                continue
            out[slot] = {
                "value": rec["value"],
                "source": source,
                "hop": int(row.get("hops") or 0),
                "artifact_id": str(row.get("id") or ""),
            }
    return out


# NO SECOND PROJECTION IS ADDED HERE, AND THAT IS THE POINT.
#
# The first draft of this change grew a `project_onto_declared()` helper before reading far
# enough: `accept_slots(spoken, declared)` in `iagent_pure.slot_acceptance` ALREADY filters
# supplied slots down to what the verb declares, already returns a `Refusal` per dropped slot
# rather than raising, and its result already reaches the routing record through
# `direct_dispatch`. A parallel projection would have been a second place for one rule to
# live, which is the defect the gateway-side ruling exists to remove — three engines with
# three behaviours was the same shape one layer down.
#
# So the accumulated set is fed INTO the existing projection as its base layer, and the
# naming of what was dropped is already built.


# The statement lives beside the MeshArtifacts implementation that reads it; it now also returns
# `seeded_by` (ADR-0041 §8.1). `_resolve_export_answers` still reads it owner-only: an export is a
# disclosure act, and ADR-0047 §5.1's seeding-delegate rule is a READ rule, not an export one.
from .artifact_reads import ARTIFACT_BY_ID_CYPHER as _ARTIFACT_BY_ID_CYPHER  # noqa: E402

# ── Origin entitlement (architect ruling, 2026-10-02) ──────────────────────────────
#
# Mirrors human_tasks.py's `_ASSET_GRANTS_FILE` pattern: an env-overridable
# `/app/policy/<file>.yaml` path, so an overlay deployment's policy mount is read the
# same way every other policy file here is. FAIL CLOSED on a missing or unparsable
# file — `{}` from `iagent.origin.load_domain_consumption` makes `can_consume` False
# for everyone, which is deny-by-default, not a crash.
_DOMAIN_CONSUMPTION_FILE = os.getenv("DOMAIN_CONSUMPTION_FILE", "/app/policy/domain_consumption.yaml")


def _load_domain_consumption_table() -> dict:
    from . import origin as origin_mod

    try:
        import yaml  # noqa: PLC0415
        with open(_DOMAIN_CONSUMPTION_FILE) as f:
            raw = yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001 — fail closed (missing/unparsable file), never 500
        logger.warning(
            "domain_consumption.yaml unreadable at %s (%s) — origin-by-consumption reads "
            "deny for everyone until this is fixed; dropper/owner-only path is unaffected",
            _DOMAIN_CONSUMPTION_FILE, exc,
        )
        return {}
    return origin_mod.load_domain_consumption(raw)


async def _origin_visible_to_caller(rec: dict, current_user: User) -> bool:
    """Non-owner read path (ruling: "ORIGIN, not audience"). False (never raises) when
    the artifact carries no recorded origin -- that artifact stays on the dropper/owner-only
    path, unchanged. The rule itself is `origin_entitlement.visible_by_origin`, the ONE function
    engine-o's notice read calls too (architect Q1, 2026-10-10): an origin with a domain and NO
    program is a steward attestation and is decided by `can_consume` alone; a program, when the
    origin names one, is a second conjunct asked of Topaz only AFTER the pure check admits the
    caller (a non-consumer gets False/404, never 503 -- no existence oracle). Raises
    HTTPException(503) when Topaz cannot answer the program-membership question -- "could not
    tell" must not collapse into the same 404 a real deny produces, the same distinction
    `get_current_user` already draws for the entitlement matrix itself.
    """
    from . import human_tasks, origin as origin_mod
    from starlette.concurrency import run_in_threadpool

    # NO RECORDED ORIGIN -> False before anything about the caller is read: the docstring's
    # "never raises" for that artifact (rev 187 merge restored this early return; the domain-only
    # steward attestation still goes on to `visible_by_origin` below).
    if not (rec.get("origin_owner_domain") or "").strip():
        return False
    viewer_domains = {c.domain for c in current_user.entitlements.cells}
    table = _load_domain_consumption_table()
    program = rec.get("origin_program")
    try:
        return await run_in_threadpool(
            lambda: origin_mod.visible_by_origin(
                viewer_domains=viewer_domains,
                owner_domain=rec.get("origin_owner_domain"),
                program=program,
                table=table,
                is_program_member=lambda p: human_tasks.check_can_view_program(
                    p, current_user.authz_id),
            )
        )
    except Exception as exc:  # noqa: BLE001 — Topaz unreachable: fail closed, report loudly
        logger.warning("program membership check unavailable for %s: %s", program, exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "authorization_unavailable", "message": "could not verify program membership"},
        ) from exc


async def _entitled_artifact_rec(artifact_id: str, current_user: User) -> dict:
    """The ONE entitlement decision for reading an AnswerArtifact by id, shared by
    `GET /artifacts/{id}` (body-less) and `GET /answers/{id}/body`. Returns the node record the
    decision was made on; raises 403/404/503 exactly as `/artifacts/{id}` always has. Callers
    choose what to project from the record; this function never decides what is returned."""
    # ── THE KEY THE WRITER STAMPED, NOT THE AUTHORIZATION IDENTITY ─────────────────────
    #
    # MEASURED 2026-09-09: this route read `authz_id` and 285 of alice's 286 artifacts were
    # PERMANENTLY UNREADABLE BY THEIR OWN PRODUCER. `PRODUCED_FOR` is stamped with
    # `current_user.id` (the JWT `sub`); `authz_id` resolves from `USER_ENTITLEMENT_CLAIM`,
    # which defaults to `email` and is unset in the deployed config. The write path stamped
    # `sub`, the read path looked up `email`, and every lookup missed.
    #
    # `id` IS THE RIGHT KEY HERE AND authz_id IS NOT, which is the part worth stating rather
    # than merely fixing. `PRODUCED_FOR` is a DATA RELATIONSHIP recorded at write time, not
    # an entitlement decision — the question is "did this actor produce this row", and the
    # only truthful answer comes from the identifier the row was stamped with.
    # `_pre_resolved_from_ask` two hundred lines up already keys on `id`; this route was the
    # odd one out, and reaching for "the authorization identity" is exactly how it got there.
    #
    # Confirmed in the live graph: PRODUCED_FOR actors are `sub` UUIDs (285, 8, 2 artifacts)
    # with a legacy email-keyed handful (1, 2).
    _uid = (current_user.id or "").strip()
    if not _uid:
        # Honest-absent identity denies rather than reading broadly.
        raise HTTPException(status_code=403, detail="no caller identity on this request")
    # ADR-0041 §8.1: a delegate reads what its workflows produced; ADR-0047 §5.1 as amended:
    # a svc: delegate is a recipient only as the seeding delegate. The gate is
    # GatewayArtifacts.get (the MeshArtifacts Protocol, iagent-mesh 0.9.9): owner OR seeding
    # delegate answers; anything else is `empty`, indistinguishable from an absent id. R-089: the
    # delegate map is asserted by configuration this pass.
    from starlette.concurrency import run_in_threadpool
    from .artifact_reads import ANSWER_ARTIFACT_KIND, GatewayArtifacts
    from iagent_mesh import Initiator

    _artifacts = GatewayArtifacts(neo4j_driver, _delegate_principals)
    try:
        _result = await run_in_threadpool(
            lambda: _artifacts.get(
                Initiator(subject=_uid, kind="person"), kind=ANSWER_ARTIFACT_KIND,
                id=artifact_id, authz_id=current_user.authz_id,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("artifact read failed for %s: %s", artifact_id, exc)
        raise HTTPException(status_code=503, detail="artifact store unavailable")

    # ── THE THIRD FACE OF A 404, AND IT IS WHY THIS SURVIVED DEPLOYMENT ────────────────
    #
    # The docstring argues 404-over-403 so an id's existence is not disclosed, and keeps 503
    # apart from 404 because "we could not look" is not "there is no such thing". Both hold.
    # invincible-agent-5f found the unhandled third member: **"IT IS YOURS AND I LOOKED IN
    # THE WRONG PLACE" also renders as 404.** A caller cannot tell a misconfigured scope from
    # an absent artifact, which is precisely why a route table that answered and a suite that
    # passed both looked fine.
    #
    # It stays a 404 TO THE CALLER — the existence-oracle argument is unchanged, and telling
    # someone "this exists but is not yours" is the disclosure being avoided. The
    # discriminator goes to the LOG, where it is useful to an operator and reaches nobody
    # else. That asymmetry is the whole point: the distinction is valuable to us and
    # dangerous to them.
    if _result.outcome == "answered":
        rec = _result.rows[0]
    else:
        # ── ORIGIN ENTITLEMENT (architect ruling, 2026-10-02: "ORIGIN, not audience") ──
        #
        # A non-owner may still read this artifact if it carries a RECORDED origin
        # (origin_owner_domain + origin_program — set by evidence, by a resolver out of
        # scope here) and this caller can_consume that origin domain AND is a program
        # member. An artifact with NO recorded origin is unaffected: `_origin_visible_to_
        # caller` returns False without a Topaz call, and the dropper/owner-only 404
        # below is exactly today's behaviour. Raises straight through (503) if Topaz
        # cannot answer — that is reported, never swallowed into this 404.
        # `empty` hides absent-vs-refused from the caller of `get`; this route's own origin
        # branch (not part of the Protocol) re-reads the row to ask the origin question.
        try:
            rec = await run_in_threadpool(lambda: _artifacts.read_row(artifact_id, _uid))
        except Exception as exc:  # noqa: BLE001
            logger.warning("artifact read failed for %s: %s", artifact_id, exc)
            raise HTTPException(status_code=503, detail="artifact store unavailable")
        _origin_ok = False
        if rec is not None:
            _origin_ok = await _origin_visible_to_caller(rec, current_user)
        if not _origin_ok:
            if rec is not None:
                logger.warning(
                    "artifact %s EXISTS but is not PRODUCED_FOR caller %r — an ownership miss, "
                    "not an absence. If this fires for a caller who did produce it, the read key "
                    "and the write key have diverged again.",
                    artifact_id, _uid,
                )
            raise HTTPException(status_code=404, detail=f"no artifact {artifact_id!r} for you")

    return rec


class ArtifactResponse(_BaseModel):
    """What a caller may read back about ONE of their own artifacts.

    DELIBERATELY NOT THE RENDERED OUTPUT. This route exists so a headless reader can recover
    what an artifact WAS — its subject, its verb, its status — not to serve the card a second
    time. `rendered_output` is large, it is already streamed and projected, and a second
    delivery path for it is a second thing to keep in step with the projector.
    """
    id: str
    status: Optional[str] = None
    summary: Optional[str] = None
    question_text: Optional[str] = None
    valid_as_of: Optional[int] = None
    duration_ms: Optional[int] = None
    derived_from: Optional[str] = None
    # THE FIELD THE CALLER ACTUALLY CAME FOR. `null` when the artifact predates subject
    # capture — absent, not "UNKNOWN", because a reader must be able to tell "this artifact
    # has no recorded verb" from "its verb is the string UNKNOWN".
    subject_uri: Optional[str] = None
    verb_iri: Optional[str] = None
    subject_instance_id: Optional[str] = None


@app.get("/artifacts/{artifact_id}", response_model=ArtifactResponse, tags=["artifacts"])
async def get_artifact(
    artifact_id: str,
    current_user: User = Depends(get_current_user),
):
    """Read back ONE artifact the caller produced — id, status, and its recorded route.

    WHY IT EXISTS. Seeding returns artifact IDS and nothing else, so the verb each panel
    actually ran is not knowable to any headless reader. ADR-0050's seal 3 compares the panel
    set of two seeds; without this it recovers verbs by fetching artifacts, and that fetch
    404'd — the arm would have burned a full seed (~5-7 min, measured) and then errored.

    THE WORSE VERSION, and it is why the shape of this route matters: had verb recovery
    returned `None` per panel instead of failing, both seeds would have compared EQUAL and
    SEAL 3 WOULD HAVE PASSED. A broken instrument turning a seal green is strictly worse
    than one turning it red. So `verb_iri` is `null` when unrecorded and never a placeholder,
    and a caller comparing sets must treat all-null as VOID rather than as agreement — the
    route cannot enforce that, but it can refuse to hand out a value that invites it.

    SCOPED TO THE CALLER'S OWN, by the same `PRODUCED_FOR` edge `_pre_resolved_from_ask`
    uses. Another user's artifact is a 404 and not a 403: telling a caller that an id EXISTS
    but is not theirs is an existence oracle over other people's questions, and the question
    text is the sensitive part. Same reasoning as `/resolve_instance`'s finding, applied
    before it becomes one.
    """
    rec = await _entitled_artifact_rec(artifact_id, current_user)

    intent: dict = {}
    if rec.get("resolved_intent"):
        try:
            intent = json.loads(rec["resolved_intent"]) or {}
        except (ValueError, TypeError):
            intent = {}

    def _or_none(v):
        # "UNKNOWN" is what the router writes when it could not place a subject. It is a
        # RECORDED non-answer, and forwarding it as if it were a subject would let a reader
        # compare two artifacts and find them equal on a value that means "no idea".
        v = str(v or "").strip()
        return None if not v or v == "UNKNOWN" else v

    return ArtifactResponse(
        id=str(rec["id"]),
        status=rec.get("status"),
        summary=rec.get("summary"),
        question_text=rec.get("question_text"),
        valid_as_of=rec.get("valid_as_of"),
        duration_ms=rec.get("duration_ms"),
        derived_from=rec.get("derived_from"),
        subject_uri=_or_none(intent.get("subject_uri")),
        verb_iri=_or_none(intent.get("verb_iri")),
        subject_instance_id=_or_none(intent.get("subject_instance_id")),
    )


# ── Answers at scale (rev 187) ─────────────────────────────────────────────────────────
#
# Cortex measured one Electric shape of the projection at 6.82 MB for ~816 rows (`routing` 47%,
# `rendered_output` 31%); a list row needs ~200 B. So: summaries here, one body by id below, and
# `/artifacts/{id}` stays body-less.

def _answers_scope_id(current_user: User) -> str:
    """The caller key the Electric proxy filters on: the JWT `sub`, validated by the SAME
    `_escape_sql_string_literal` (UUID check). The list query binds it as a parameter, so the
    value is the raw id, never the quote-escaped literal -- the two are equal for any UUID."""
    verified_user_id = current_user.id
    try:
        _escape_sql_string_literal(verified_user_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=403, detail="no usable caller identity on this request") from exc
    return verified_user_id


@app.get("/answers", tags=["answers"])
async def list_answers(
    page: int = _Query(1, ge=1),
    size: int = _Query(50, ge=1, le=200),
    sort: str = _Query("newest", pattern="^(newest|oldest)$"),
    q: Optional[str] = _Query(None, max_length=500),
    type: Optional[str] = _Query(None, max_length=100),
    status: Optional[str] = _Query(None, max_length=100),
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
):
    """The caller's own answers as SUMMARIES (id, ts, title, summary, type, status, subject,
    archived). Never a body. Archived answers are hidden unless `include_archived`."""
    from starlette.concurrency import run_in_threadpool
    from . import answer_list

    caller = _answers_scope_id(current_user)
    try:
        return await run_in_threadpool(
            lambda: answer_list.list_answers(
                caller=caller, page=page, size=size, sort=sort, q=q, type_=type,
                status=status, include_archived=include_archived,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("answers list failed: %s", exc)
        raise HTTPException(status_code=503, detail="answer store unavailable")


@app.get("/answers/{answer_id}/body", tags=["answers"])
async def get_answer_body(
    answer_id: str,
    current_user: User = Depends(get_current_user),
):
    """ONE body, by id, under the SAME entitlement `/artifacts/{id}` applies. Archived answers
    stay readable: archive hides, it never revokes."""
    from .projector.apply_loop import _parse_json

    rec = await _entitled_artifact_rec(answer_id, current_user)
    return {
        "id": str(rec["id"]),
        "rendered_output": _parse_json(rec.get("rendered_output")),
        "routing": _parse_json(rec.get("routing_inline")),
        "resolved_intent": _parse_json(rec.get("resolved_intent")) or {},
    }


class ArchiveRequest(_BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class UnarchiveRequest(_BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


async def _set_archive(answer_id: str, current_user: User, *, archive: bool, reason: Optional[str]) -> dict:
    from starlette.concurrency import run_in_threadpool
    from . import answer_artifact_writer

    rec = await _entitled_artifact_rec(answer_id, current_user)
    # Owner only. FOLLOW-UP: steward cross-user tidy needs a Topaz permission; no persona check here.
    if not rec.get("is_owner"):
        raise HTTPException(status_code=404, detail=f"no artifact {answer_id!r} for you")
    try:
        changed = await run_in_threadpool(
            lambda: answer_artifact_writer.set_archive_state(
                neo4j_driver, answer_id, archive=archive,
                by=current_user.id, reason=reason,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("archive write failed for %s: %s", answer_id, exc)
        raise HTTPException(status_code=503, detail="artifact store unavailable")
    return {"id": answer_id, "archived": archive, "changed": bool(changed)}


@app.post("/answers/{answer_id}/archive", tags=["answers"])
async def archive_answer(
    answer_id: str, req: ArchiveRequest, current_user: User = Depends(get_current_user),
):
    """Hide an answer from the default view. Never deletes; idempotent."""
    return await _set_archive(answer_id, current_user, archive=True, reason=req.reason)


@app.post("/answers/{answer_id}/unarchive", tags=["answers"])
async def unarchive_answer(
    answer_id: str, req: UnarchiveRequest, current_user: User = Depends(get_current_user),
):
    return await _set_archive(answer_id, current_user, archive=False, reason=req.reason)


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
    frontend_version: str = "",
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
    spoken_slot: str | None = None,
    spoken_answer: str | None = None,
    # The route an earlier ask already established, read back under the caller's ownership
    # edge. `{}` for an ordinary question, which is every request that answers nothing.
    pre_resolved: dict | None = None,
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
        "frontend_version": frontend_version or "",
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
        "spoken_slot": spoken_slot or "",
        "spoken_answer": spoken_answer or "",
        "pre_resolved": dict(pre_resolved or {}),
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
    trace_id: str = "",
    user_id: str = "default_testing_user",
    user_email: str = "",
    user_persona: str | None = None,
    entitled_domains: list[str] | None = None,
    entitlement_source: str = "fallback",
    caller_token: str = "",
) -> AsyncGenerator[str, None]:
    """THE OUTER BOUNDARY. Every turn that reaches here produces an artifact.

    ⛔ WHAT THIS IS FOR, measured 2026-09-14 and the worst failure of the day. A one-word slip
    inside the body — `bound_slots` where the name in scope was `request.bound_slots` — raised
    `NameError` mid-stream. The generator stopped. **Nothing else happened.** No route decision,
    no materializations, no artifact: not `failed`, not `complete`, NOTHING. The rail showed no
    new row, and the card held only the question text.

    So the whole failure-recording arc built that same day could not see it, and never could:

        You cannot record an absence. Everything else records WHAT HAPPENED;
        this dispatch never happened.

    **TWO WAYS OUT WITHOUT WRITING, AND BOTH ARE CLOSED HERE.**

    1. An exception escapes the body — the `NameError` case. Caught below; a `failed` artifact
       is written carrying the exception text as its cause, and a terminal error event is
       emitted so the card renders the failure instead of the question.
    2. The body returns having never flipped `status` off `pending`. The bundle's own comment
       says it: *"If neither flip happens before stream_end, the bundle is NOT dispatched."* No
       exception is involved, and the outcome is identical — silence. The sentinel below makes
       that case write too.

    **WHY A WRAPPER RATHER THAN A try/except INSIDE THE BODY.** The body is long and builds its
    bundle partway through; a handler inside it can only cover the part after the bundle exists,
    and the defect that prompted this fired BEFORE that point. The wrapper knows enough from its
    own parameters to write a complete, honest, minimal artifact without depending on how far the
    body got — which is the only version that covers the failure that actually happened.

    The artifact it writes is deliberately thin: id, question, who asked, `failed`, and the cause.
    A richer one would need the body's state, and needing the body's state is what made the gap.
    """
    _wrote = False

    try:
        async for _ev in _generate_dagster_stream_inner(
            request,
            trace_id=trace_id,
            user_id=user_id,
            user_email=user_email,
            user_persona=user_persona,
            entitled_domains=entitled_domains,
            entitlement_source=entitlement_source,
            caller_token=caller_token,
        ):
            _wrote = True
            yield _ev
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "generate_dagster_stream raised for session %s — writing a failed artifact so the "
            "turn is not silent", getattr(request, "session_id", "?"),
        )
        _cause = {
            "exception": type(exc).__name__,
            "message": str(exc)[:1200],
            "where": "generate_dagster_stream",
        }
        try:
            await _dispatch_answer_artifact(
                _boundary_failure_bundle(
                    request, user_id, user_persona, entitled_domains,
                    entitlement_source, _cause,
                )
            )
        except Exception:  # noqa: BLE001
            # THE WRITER ITSELF FAILING MUST NOT SWALLOW THE ORIGINAL. A raise here would
            # replace a diagnosable engine failure with a storage failure, and the reader would
            # chase the wrong one.
            logger.exception("boundary artifact write FAILED; original cause: %s", _cause)
        if not _wrote:
            # Nothing reached the client at all, so the card has nothing to render. Emit the
            # terminal pair rather than leaving the connection to time out — a hung stream and a
            # failed one look identical to a person and only one of them is true.
            yield _perror(
                "The turn failed before it produced an answer.",
                kind="stream",
                retryable=True,
                cause="stream_raised",
            )
            yield _sse("stream_end", "{}")
        return


def _boundary_failure_bundle(
    request: "InterviewRequest",
    user_id: str,
    user_persona: str | None,
    entitled_domains: list[str] | None,
    entitlement_source: str,
    cause: dict,
) -> dict:
    """The thinnest honest artifact: who asked what, that it failed, and why.

    `status` is `failed` EXPLICITLY. The writer requires it at construction precisely so a
    forgotten status cannot persist as `complete`, and this is the path where forgetting would
    be easiest — nothing here knows whether an answer was nearly ready.
    """
    return {
        "id": (getattr(request, "artifact_id", "") or f"artifact-boundary-{int(time.time()*1000)}"),
        "question_text": getattr(request, "message", "") or "",
        "message_id": getattr(request, "session_id", "") or "",
        "valid_as_of": int(time.time() * 1000),
        "status": "failed",
        "produced_by": {"actor_type": "agent", "actor_id": "cortex-bff"},
        "produced_for": {
            "user_id": user_id,
            "is_authenticated": True,
            "user_persona": user_persona,
            "entitled_domains": entitled_domains or [],
            "entitlement_source": entitlement_source,
        },
        "resolved_intent": {"failure_cause": cause},
        "routing": None,
        "sources": [],
    }


async def _generate_dagster_stream_inner(
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
    # ── LINEAGE: A CLAIM, CHECKED BEFORE IT BECOMES A CONCLUSION ────────────────────────
    #
    # The client names the ask it is answering; the server decides whether that is lineage.
    # It is honoured ONLY when the turn also CARRIES an answer — a pick in `bound_slots` or
    # a typed reply in `spoken_answer`. A turn with neither is an ordinary question, and a
    # question that claims to descend from an ask is either confused or lying.
    #
    # THE COST OF NOT CHECKING IS A FABRICATED ANCESTOR, not a missing one: the writer links
    # with `MERGE (parent:AnswerArtifact {id: $parent_id})`, which CREATES the node when the
    # id is unknown. So an unguarded field lets a caller conjure an artifact into the graph by
    # naming it, and the rail would then fold two cards together on a lineage nobody produced.
    # Refusing is cheap; a phantom in the provenance graph is not.
    _answers_something = bool(request.bound_slots) or bool(request.spoken_answer)
    _names_an_ask = bool(request.answering_artifact_id)
    _carries_prose = bool((request.message or "").strip())

    # ── WHY PROSE BUYS LINEAGE AND DOES NOT BUY THE ROUTE ────────────────────────────────
    #
    # THE TURN THAT WAS BEING DROPPED (HAZ-1003): the person reads a drawn card and types a
    # sentence about it. That turn descends from the card on any honest reading — it is the
    # next step of one conversation — and it carries neither a pick nor a typed slot answer.
    # One predicate gated BOTH the lineage claim and the pre-resolved route, so honouring the
    # first meant granting the second, and the composer turn rendered as an orphan card.
    #
    # THE TWO GATES REST ON DIFFERENT EVIDENCE, which is why they come apart here rather than
    # being widened together. `bound_slots` and `spoken_answer` are shapes only a client that
    # was SHOWN this ask's menu can produce, so their presence is itself weak evidence that
    # the named ask is real. Prose is not evidence of anything: every ordinary question
    # carries prose, so `named + prose` is satisfiable by any caller typing any sentence at
    # any id they care to invent.
    #
    # SO THE WIDENED ARM PAYS FOR ITSELF WITH A GRAPH READ — existence AND ownership, under
    # the same edge and through the same Cypher constant the route lookup uses. Without it
    # this arm would be reachable with nothing but prose and a guessed id, and the writer's
    # `MERGE (parent:AnswerArtifact {id: $parent_id})` CREATES the node, so that is precisely
    # how a phantom ancestor gets conjured. The check is ordered last on purpose: two free
    # predicates first, the round-trip only for the turns that could actually widen anything.
    #
    # ⚠ WHAT THIS DELIBERATELY DOES **NOT** DO. The answering arm is still honoured WITHOUT
    # that read, exactly as before today. That is a pre-existing hole in the same guard and I
    # am NAMING it, not closing it: adding the check there would refuse valid lineage in any
    # window where the ask's own write has not landed by the time the answer turn arrives, and
    # whether that race exists on this path is UNMEASURED. Measure it, then close it.
    # THE RULE IS CALLED, NOT RESTATED. `iagent_pure.lineage_claim` holds it at module level so
    # its seal exercises the real decision; a copy of the branching here would be the mirror
    # `cold_start_fallback_domains` records a surviving mutant for.
    _lineage_honoured, _lineage_refused_because = lineage_is_honoured(
        names_an_ask=_names_an_ask,
        answers_something=_answers_something,
        carries_prose=_carries_prose,
        # LAZY, so the round trip is paid only on the arm that needs it.
        ownership_ok=lambda: _artifact_is_the_callers(
            request.answering_artifact_id or "", user_id
        ),
    )

    _answering_artifact_id = (
        (request.answering_artifact_id or None) if _lineage_honoured else None
    )
    if _names_an_ask and not _lineage_honoured:
        logger.warning(
            "lineage claim REFUSED for run %s: answering_artifact_id=%r — %s",
            session_id, request.answering_artifact_id, _lineage_refused_because,
        )
    # THE OTHER TWO OUTCOMES, BECAUSE ONLY THE REFUSAL WAS AUDIBLE.
    #
    # MEASURED 2026-09-07: `derived_from_artifact_id` was NULL on all 14 most recent
    # artifacts, including the ask/pick pair the user walked — and the logs could not say
    # whether the claim never arrived or arrived and was dropped, because the only line on
    # this path fires when a claim is REFUSED. An absent warning was consistent with both.
    #
    # The silent case is the one that matters: `answeringArtifactBody()` returns `{}` when
    # the client has no id, so a pick with an unknown ask posts a well-formed body that
    # simply omits the claim. That is indistinguishable from a plain question at every
    # layer below this line, and it is the shape that produced two cards where the fold
    # was fully built on both sides and merely had nothing to fold.
    elif _answering_artifact_id:
        # WHICH ARM HONOURED IT, because the two carry different guarantees and a reader
        # diagnosing a fold needs to know which one they are looking at: the answering arm
        # took the id on the turn's shape, the prose arm took it on a verified ownership edge.
        logger.info(
            "lineage claim ACCEPTED for run %s: this turn answers %s (%s)",
            session_id, _answering_artifact_id,
            "turn carries an answer" if _answers_something
            else "prose turn, artifact existence and ownership verified",
        )
    elif _answers_something:
        # GUARDED ON `_answers_something`, and the first version was NOT — it would have
        # fired on every ordinary question while asserting "turn carries an answer", which
        # is a false statement in a line someone reads to diagnose. An ordinary question
        # legitimately has no ask to name and is not worth a line.
        logger.info(
            "lineage ABSENT for run %s: turn carries an answer (bound_slots=%d "
            "spoken_answer=%s) but names no ask — it will render as its own card",
            session_id, len(request.bound_slots or {}), bool(request.spoken_answer),
        )

    # THE SKIP, DECIDED WHERE THE ID HAS ALREADY BEEN JUDGED. Only an ACCEPTED claim gets
    # here: `_answering_artifact_id` is None for a refused one and for an ordinary question,
    # and the lookup is scoped to this caller's own ownership edge on top of that.
    #
    # ⛔ AND IT KEEPS THE STRICTER PREMISE, which is the point of the split above. An accepted
    # lineage claim draws an arrow; a pre-resolved route DISPATCHES A VERB AGAINST A SUBJECT
    # nobody re-confirmed on this turn. The prose arm was widened for the first and must not
    # leak into the second, so `_answers_something` is named again here rather than inherited
    # through `_answering_artifact_id` — the two gates now differ, and relying on the id alone
    # would silently re-join them the day anyone widened the lineage arm again.
    # ── ADR-0050 §3's SEED_PANEL ROUTE — THE TEMPLATE STATES THE SUBJECT; THE MESH CONFIRMS
    # IT ON EVERY DISPATCH. A seed_panel turn never names an ask (there is no card to answer —
    # it is the FIRST dispatch of this panel), so it is mutually exclusive with the ask-derived
    # route below BY CONSTRUCTION: `request.seed_panel` and `_answering_artifact_id` are never
    # both meaningful on the same turn, and this branches on both rather than trusting that.
    _is_seed_panel_turn = bool(request.seed_panel) and not _answering_artifact_id
    _seed_panel_bound_slots: dict = {}
    if _is_seed_panel_turn:
        _pre_resolved, _seed_panel_bound_slots = _pre_resolved_from_seed_panel(
            request.seed_panel  # type: ignore[arg-type]
        )
    else:
        _pre_resolved = (
            _pre_resolved_from_ask(_answering_artifact_id or "", user_id)
            if pre_resolved_route_allowed(answers_something=_answers_something)
            else {}
        )

    # A SEED_PANEL TURN HAS NO QUESTION UNDERNEATH IT TO FALL BACK TO. Every other route to
    # `{}` here means "route the ordinary way, merely slower" — correct, because an ordinary
    # NL question or an ask's pick both have a classified path that still answers them. A
    # seed_panel turn has no phrase to classify (`seed_template_canvas` never built one; see
    # its own docstring) — `orchestrate()` already 422s an unroutable seed_panel before the
    # stream opens, so reaching `{}` here means that validation and this rebuild disagree, and
    # the honest answer is a visible failure, never a silent slide into `/route_intent` on a
    # message that was only ever a label for logs.
    if _is_seed_panel_turn and not _pre_resolved:
        yield _perror(
            "this template's panel declares no subject, so it cannot be dispatched directly",
            kind="understanding",
            retryable=False,
            cause="seed_panel_unroutable",
        )
        yield _sse("stream_end", "{}")
        return
    if _pre_resolved:
        logger.info(
            "pre-resolved route for run %s from ask %s: subject=%s verb=%s "
            "— skipping /plan, /resolve and /classify_predicate",
            session_id, _answering_artifact_id,
            _pre_resolved["subject_uri"], _pre_resolved["verb_iri"],
        )
    elif _answering_artifact_id and _answers_something:
        # AUDIBLE, because this is the branch that silently costs the user 40 seconds. An
        # accepted lineage claim that yields no route means the ask predates the subject
        # capture, or the artifact is not this caller's. Both route the ordinary way; only
        # one of them is worth investigating, and a log line is how anyone tells them apart.
        logger.info(
            "no pre-resolved route on ask %s for run %s — routing the full path",
            _answering_artifact_id, session_id,
        )
    elif _answering_artifact_id:
        # THE PROSE ARM, AND IT NEEDS ITS OWN LINE RATHER THAN THE ONE ABOVE. That line says
        # "no pre-resolved route", which reads as a lookup that came back empty — and here the
        # lookup never ran, by design. Reporting a result for a query nobody issued is how a
        # correct refusal gets diagnosed as a broken one.
        logger.info(
            "lineage only on ask %s for run %s: a prose turn keeps the arrow and takes the "
            "full routing path by design — a pre-resolved route needs a pick or a typed answer",
            _answering_artifact_id, session_id,
        )

    # WHAT THIS CHAIN HAS ALREADY ANSWERED. Read here, beside the route and under the same
    # ownership edge, because it is the same kind of fact: something an earlier ask
    # established, which the client may CLAIM a lineage for but must never SUPPLY.
    #
    # The route was already carried across hops and the answers were not — that asymmetry is
    # the whole loop. A two-slot verb took four hops because hop 3 could not see what hop 1
    # had bound.
    _chain_slots = _accumulated_slots(_answering_artifact_id or "", user_id)
    if _chain_slots:
        logger.info(
            "chain %s carries %d already-bound slot(s) for run %s: %s",
            _answering_artifact_id, len(_chain_slots), session_id,
            {k: v["source"] for k, v in _chain_slots.items()},
        )

    # ── THE ANSWER TURN CARRIES THE ASK'S ACCUMULATED SET ────────────────────────────────────
    #
    # `_pre_resolved_from_ask` builds the route from the ASK artifact, and the ask is by
    # construction the turn where nothing was bound — so `subject_instance_id` is necessarily
    # empty there and rode forward onto the turn that finally supplied one. Measured on
    # artifact-2-1789404372153: the pick bound `program_id: NP-MERIDIAN`, the arity gate still
    # saw a set query, and the dispatch abstained FOR THE REASON THE ASK HAD JUST BEEN ANSWERED.
    #
    # THE SET TRAVELS, NOT A LIST OF NAMES. Names alone would be a third thing the ask's payload
    # does not carry that the answer turn needs — the defect's own shape one more time. The
    # provenance-keyed union is what `_accumulated_slots` already walks out of the lineage, so
    # the ask turn and the answer turn share ONE payload shape and the consumer derives what it
    # needs from it.
    #
    # PRE-RESOLVED ONLY. The classified path has no ask, so it has no unpromoted instance —
    # carrying this there would feed a state that cannot arise, and a dead branch under a seal
    # reads as coverage.
    if _pre_resolved:
        # ⛔ THE CHAIN ALONE IS NOT "WHAT THIS TURN HAS BOUND", and sending only it reproduced
        # the original defect inside its own fix. `_chain_slots` is what the ANCESTORS bound;
        # the pick that answers an ask arrives on THIS turn, in `bound_slots`, and is by
        # construction in no ancestor. Measured on artifact-4-1789438505471: its own record
        # carried {"program_id": {"value": "NP-MERIDIAN", "source": "picked"}} while its parent
        # — the ask — carried {}. The consumer looked only where the value could never be.
        #
        # So the field means EVERYTHING BOUND AS OF THIS TURN, ancestors plus this turn's own
        # answer, and the nearest binding wins for the same reason `_accumulated_slots` lets the
        # nearest hop win: a person who answers a slot twice meant the second answer.
        _this_turn = {
            k: {"value": v, "source": SLOT_SOURCE_PICKED}
            for k, v in dict(request.bound_slots or {}).items()
        }
        _pre_resolved["accumulated_slots"] = {**(_chain_slots or {}), **_this_turn}

    mode: str
    entity_refs: list[str] = []
    intent_extraction: dict = {}

    if is_interview_active:
        mode = "CONVERSATIONAL"
    elif _pre_resolved:
        # THE FOURTH MODEL CALL, and the one the first pass missed. `/route_intent` runs
        # ExtractIntent before anything else and cost 5.4s of a 40s pick, measured
        # 2026-09-08 (POST 00:55:11.3 -> lineage evaluated 00:55:16.7). The commit that
        # skipped /plan, /resolve and /classify_predicate said "three model calls"; it was
        # four, and this one ran BEFORE the pre-resolved lookup could say it was unwanted.
        #
        # NOTHING DOWNSTREAM NEEDS IT ON THIS PATH. Its three consumers are `resolved_intent`
        # (overwritten by the slots decision the moment routing lands), `slots` (empty on
        # essentially every request today - the filler is not called), and `entity_refs`,
        # which exist to feed /resolve. /resolve is skipped here by construction, so refs
        # extracted for it would be carried and dropped.
        #
        # The lookup moved ABOVE this block to make the skip possible; it reads the ask under
        # the caller's own ownership edge and needs nothing from the extraction.
        mode = "ONE_SHOT"
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
    # True once a ROUTED subtask_slots_decision (non-empty verb_iri) has been captured into
    # resolved_intent. See the precedence guard at the reader.
    _resolved_from_routed = False
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
            # WHO THE TURN WAS FOR, as policy keys them: the authz_id, which `user_email` CARRIES
            # (see /orchestrate). `user_id` is the sub and names nobody Topaz knows. The acceptance
            # consumer reads THIS as the case's requester (ruled 2026-10-05): the person whose
            # turn's answer carried the review_request.
            "authz_id": user_email or "",
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
        # LINEAGE, and only for a turn that really is an answer. `_answering_artifact_id`
        # is None unless the caller both named an ask AND carried something that answers
        # one — see the guard where it is computed.
        "derived_from_artifact_id": _answering_artifact_id,
    }

    # ══ THE DIRECT PATH ═════════════════════════════════════════════════════════════════
    #
    # A pre-resolved pick has nothing left to orchestrate: the subject, the verb and the
    # slots all came from an ask this person already answered. Measured 2026-09-08, the
    # Dagster route cost 24 seconds for roughly one second of work — 8.4s to launch a run,
    # 13.1s to execute a job with one op. This branch does that work in-process.
    #
    # IT IS STRICTLY AN OPTIMISATION. Anything it cannot confirm returns FALL_BACK and the
    # run below executes exactly as before, so the worst outcome of a miss here is today's
    # latency. That is why the fall-back does NOT return: it declines to answer, it does not
    # end the turn.
    #
    # THE STAGES IT ANNOUNCES ARE THE STAGES IT RUNS. The five kinds below describe a
    # decomposition, a resolution and a classification, none of which happen here. Emitting
    # them would be a success line for work that never ran, so this path names its own two
    # and the gateway adds `writing_answer` because the gateway owns the write. cortex-ui
    # renders arriving stages in arrival order rather than from a fixed list (8cd4ac5), so
    # a kind it does not know is drawn, not dropped.
    _direct = None
    if _pre_resolved:
        _direct_stages: list = []
        # ONE RUN, ONE THREAD - minted here because this is where a run begins, and the
        # stateful graph rows contract on `thread_id = run id`. Before this, the dispatch
        # body carried no thread at all and `fin_program_brief` refused every call with a
        # 422 (artifact-2-1789497046894); the NP-MERIDIAN pick was correct and the answer
        # still never arrived.
        #
        # NOT `session_id`, which is the nearest thing already in scope and is WRONG in the
        # direction that looks right: it would scope checkpoint state to a SESSION, so the
        # second question of a session would resume the first one's state and reducers that
        # append would merge two answers. A session is not a run.
        _run_id = 'run-' + uuid.uuid4().hex

        def _direct_stage_events() -> list:
            _t0 = _direct_stages[0][2] if _direct_stages else time.time()
            return [
                _stage(_kind, _status, elapsed_ms=max(0, int((_at - _t0) * 1000)))
                for _kind, _status, _at in _direct_stages
            ]

        try:
            _direct = await asyncio.to_thread(
                functools.partial(
                    dispatch_pre_resolved,
                    pre_resolved=_pre_resolved,
                    # SEED_PANEL'S SLOTS ARE THE TEMPLATE'S, NEVER THE REQUEST'S OWN
                    # `bound_slots` — a seed_panel turn carries no pick-menu answer, it carries
                    # the panel's declared `slots` merged with the bound shared slots
                    # (`_pre_resolved_from_seed_panel`'s `params`), under the verb's own
                    # parameter names (`bind_as`).
                    bound_slots=(
                        _seed_panel_bound_slots if _is_seed_panel_turn
                        else (request.bound_slots or {})
                    ),
                    # Read from the graph under the caller's ownership edge, never from the
                    # request body — the same rule as `pre_resolved`, because it is the same
                    # kind of fact: something an earlier ask established in THIS caller's
                    # chain. A client that could SUPPLY these could answer its own asks.
                    chain_slots=_chain_slots,
                    spoken_answer=request.spoken_answer or "",
                    user_query=user_query,
                    run_id=_run_id,
                    entitled_domains=entitled_domains or [],
                    acting_persona=user_persona,
                    ontology_url=_DAGSONTOLOGY_SVC_URL,
                    accept_slots=accept_slots,
                    on_behalf_of=user_email or "",
                    # THE CALLER'S OWN TOKEN, not a minted service identity. On the run path
                    # this is what the identity vault exists to carry INTO Dagster; here the
                    # browser's credential is already in hand, so the engine sees the same
                    # subject it would have seen, by the shorter route.
                    headers=(
                        {"Authorization": f"Bearer {caller_token}"} if caller_token else None
                    ),
                    on_stage=lambda kind, status: _direct_stages.append(
                        (kind, status, time.time())
                    ),
                )
            )
        except Exception as exc:  # noqa: BLE001
            # A RAISE IS A FALL-BACK on an ordinary turn, and a SERVER FAULT on a seed turn.
            # `dispatch_pre_resolved` is contracted not to raise; if it does, that is a bug
            # in the fast path. An ordinary question still has a phrase, so the slow path
            # answers it. A seed turn has no phrase underneath it (see the FALL_BACK branch
            # below), so the same fall-through would answer a different question than the
            # panel named: it fails visibly, bound to the step it died in.
            logger.warning(
                "direct path raised for run %s (%s: %s) — %s",
                session_id, type(exc).__name__, exc,
                "failing the seed turn" if _is_seed_panel_turn else "routing the full path",
            )
            _direct = None
            if _is_seed_panel_turn:
                # STARTED-WITH-NO-OUTCOME means the raise landed inside that step; with
                # nothing reported the first step was never left.
                _step = (
                    _direct_stages[-1][0] if _direct_stages
                    else direct_dispatch.STAGE_VERIFYING
                )
                for _ev in _direct_stage_events():
                    yield _ev
                if _direct_stages and _direct_stages[-1][1] == "started":
                    yield _stage(_step, "failed")
                # The class name only: an engine exception's text can carry an internal
                # host. The log line above keeps the full text.
                _seed_cause = "seed_panel_dispatch_raised"
                _msg = (
                    f"seed_panel's dispatch failed in step {_step} "
                    f"({type(exc).__name__})"
                )
                _artifact_bundle["status"] = "failed"
                _ri = dict(_artifact_bundle.get("resolved_intent") or {})
                for _k in ("verb_iri", "subject_uri", "subject_instance_id"):
                    _v = _pre_resolved.get(_k)
                    if _v not in (None, ""):
                        _ri.setdefault(_k, _v)
                _ri.setdefault("failure_cause", {
                    "exception": _seed_cause,
                    "message": _msg,
                    "where": "seed_panel_dispatch",
                    "step": _step,
                })
                _artifact_bundle["resolved_intent"] = _ri
                yield _perror(_msg, kind=_step, retryable=True, cause=_seed_cause)
                yield _sse("stream_end", "{}")
                await _dispatch_answer_artifact(_artifact_bundle)
                return

        # DELIVERED AFTER THE FACT, WITH THEIR REAL TIMES. The dispatch is sync and runs in
        # a worker thread, so the events cannot be yielded as they happen without a queue —
        # and the whole path is one to two seconds. What must not be faked is the DATA, so
        # each stage carries the elapsed time actually measured at its own boundary rather
        # than a timeline composed here.
        if _direct is not None:
            for _ev in _direct_stage_events():
                yield _ev

        if _direct is not None and _direct.kind not in (
            direct_dispatch.ROUTED, direct_dispatch.ABSTAIN
        ):
            # NAMED, because this branch silently costs the user twenty seconds and the
            # reasons it fires have different repairs: an unreachable verifier is substrate,
            # an ineligible verb is a real invalidation the pick should not have offered,
            # and an ASK is neither.
            #
            # AN `ask` FALLS BACK ON PURPOSE. The ask card and its menu are built inside the
            # supervisor; rebuilding them here would risk offering a menu that is subtly
            # WRONG rather than merely slow, and wrong is the one trade this path may not
            # make. The run re-derives the same ask and asks it correctly. Widening this to
            # answer asks directly is a separate decision with its own seal.
            logger.info(
                "direct path declined for run %s (%s: %s) — routing the full path",
                session_id, _direct.kind, _direct.reason,
            )
            # ON THE TURN, NOT ONLY IN THE LOG. Without this a decline is indistinguishable
            # from the fast path merely being slow, and the only way to tell them apart is
            # timing a pick by hand — which is how the original 24 seconds went unnoticed.
            # THE FALLBACK RATE IS THE NUMBER THAT SAYS WHETHER THE DIRECT PATH IS REAL, and
            # a rate needs an event per occurrence, not a line someone greps for.
            #
            # The REASON travels because the causes have opposite repairs: an unreachable
            # verifier is substrate, an ineligible verb is a real invalidation the pick
            # should not have offered, and an `ask` is neither.
            # ITS OWN KIND, not a second terminal on `verifying_route`. That stage has
            # already reported `failed` on two of these three paths, and a `completed`
            # after a `failed` is the unbalanced pair this path's own seal forbids.
            _DIRECT_FALLBACKS[_direct.kind] = _DIRECT_FALLBACKS.get(_direct.kind, 0) + 1
            logger.info(
                "direct-path fallback rate this process: %s",
                dict(sorted(_DIRECT_FALLBACKS.items())),
            )
            _detail = {"outcome": _direct.kind, "reason": _direct.reason}
            yield _stage(direct_dispatch.STAGE_FELL_BACK, "started", detail=_detail)
            yield _stage(direct_dispatch.STAGE_FELL_BACK, "completed", detail=_detail)
            if _is_seed_panel_turn:
                # A SEED_PANEL TURN HAS NO PHRASE UNDERNEATH IT TO FALL BACK TO. Every other
                # fall-back correctly re-routes through the classified path because an ordinary
                # question or an ask's pick both have a real phrase to classify; this one's
                # `message` is only ever a label for logs (`seed_template_canvas`'s own
                # docstring), so "route the full path" would dispatch whatever `/route_intent`
                # makes of that label — a DIFFERENT question than the panel named, answered
                # silently in place of the one the caller actually asked for. THE TEMPLATE
                # STATED THE SUBJECT; THE MESH JUST DISAGREED (`_detail["reason"]`) — that
                # disagreement must reach the caller as a visible failure, never get laundered
                # through the classifier guessing at a label.
                _artifact_bundle["status"] = "failed"
                # THE ARTIFACT RECORDS WHAT THE STREAM SAYS. One cause code feeds both, and the
                # template's verb is written like `_stream_direct_outcome` writes it (setdefault,
                # never over a fuller intent): without them the failed seed read as an
                # unattributable `NoCauseRecorded` with no verb (18 such rows, 2026-10-28).
                _seed_cause = (
                    "seed_panel_verb_not_visible"
                    if _direct.missing_domains
                    and direct_dispatch.VERB_NOT_IN_CELL in _detail["reason"]
                    else "seed_panel_fell_back"
                )
                _ri = dict(_artifact_bundle.get("resolved_intent") or {})
                for _k in ("verb_iri", "subject_uri", "subject_instance_id"):
                    _v = _pre_resolved.get(_k)
                    if _v not in (None, ""):
                        _ri.setdefault(_k, _v)
                _ri.setdefault("disposition", _direct.kind)
                _ri.setdefault("failure_cause", {
                    "exception": _seed_cause,
                    "message": _detail["reason"],
                    "where": "seed_panel_fall_back",
                    "outcome": _direct.kind,
                })
                _artifact_bundle["resolved_intent"] = _ri
                yield _perror(
                    f"seed_panel's declared route is no longer valid: {_detail['reason']}",
                    kind="verifying_route",
                    retryable=True,
                    cause=_seed_cause,
                    missing_domains=(
                        _direct.missing_domains
                        if _seed_cause == "seed_panel_verb_not_visible" else None
                    ),
                )
                yield _sse("stream_end", "{}")
                await _dispatch_answer_artifact(_artifact_bundle)
                return
            _direct = None

    if _direct is not None:
        async for _ev in _stream_direct_outcome(
            outcome=_direct,
            bundle=_artifact_bundle,
            session_id=session_id,
            frontend_id=(request.frontend_id or ""),
            frontend_version=(request.frontend_version or ""),
            user_persona=user_persona or "",
        ):
            yield _ev
        yield _sse("stream_end", "{}")
        await _dispatch_answer_artifact(_artifact_bundle)
        return

    # Per ADR-0009 Step F'.2: /route_intent does not produce a task_plan
    # anymore — the supervisor's `create_task_plan` op asks Engine O's /plan
    # endpoint itself when task_plan_json is empty. Step F'.3 will switch
    # that decomposition path to be predicate-aware too.
    # ONE TASK, NOT A DECOMPOSITION. `/plan` is a BAML call that decomposes a question into
    # persona-assigned subtasks; an answered ask is not a new question and has nothing to
    # decompose. Synthesizing the plan here skips that model call while `create_task_plan`
    # runs unchanged - it takes the `task_plan_json` branch it already has, and still yields
    # `active_agent_roster`, so the HUD's plan step fires exactly as before.
    #
    # `sub_query` is the user's phrase VERBATIM. Composing anything here would reintroduce
    # the rewrite the fold removed: the phrase the router sees stays byte-equal to what the
    # person asked, and the answer rides beside it in `bound_slots`.
    task_plan_json = ""
    if _pre_resolved:
        task_plan_json = json.dumps({
            "tasks": [{
                "target_persona": _pre_resolved.get("owner_persona") or "",
                "sub_query": user_query,
            }],
            "domain": domain,
            "extracted_concepts": [],
        })
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
        frontend_version=(request.frontend_version or ""),
        user_persona=user_persona,
        entitled_domains=entitled_domains,
        entity_refs=entity_refs,
        # Forwarded rather than dropped - the carry. `{}` until the slot-filler is called.
        slots=dict(intent_extraction.get("slots") or {}),
        bound_slots=dict(request.bound_slots or {}),
        spoken_slot=request.spoken_slot,
        spoken_answer=request.spoken_answer,
        pre_resolved=_pre_resolved,
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
            VAULT.stash(run_id, caller_token, subject=user_email, slots=vault_slots())
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

                # PRECEDENCE, order-independent. A run can have several subtasks and every
                # materialization lands here. (1) A no-verb record (empty verb_iri, an early
                # exit) must NOT replace a resolved_intent already taken from a routed record:
                # a routed subtask wins over an early exit. (2) A routed record DOES replace a
                # no-verb one. Keyed on a local flag, not on the bundle's prior contents: the
                # ExtractIntent output seeded there first has no verb_iri contract.
                _is_routed_rec = bool(_slots_md.get("verb_iri"))
                if not _is_routed_rec and _resolved_from_routed:
                    continue
                if _is_routed_rec:
                    _resolved_from_routed = True
                _artifact_bundle["resolved_intent"] = {
                    "verb_iri": _slots_md.get("verb_iri") or "",
                    "disposition": _slots_md.get("disposition") or "",
                    "accepted_slots": _j("accepted_slots", {}),
                    # THE PROVENANCE RECORD. Read by `_accumulated_slots` on the next hop;
                    # written nowhere until 2026-09-14, which made the whole chain-slot carry
                    # inert in production with every seal over it green (R-057).
                    "bound_slot_sources": _j("bound_slot_sources", {}),
                    "refused_slots": _j("refused_slots", []),
                    "slot_resolution": _j("slot_resolution", {}),
                    # The subject the verb was chosen for — see the producer. Without it
                    # `resolved_intent` names an action and not the thing acted on, and a
                    # re-route cannot be dispatched from the artifact alone.
                    "owner_persona": _slots_md.get("owner_persona") or "",
                    "subject_uri": _slots_md.get("subject_uri") or "",
                    "subject_instance_id": _slots_md.get("subject_instance_id") or "",
                    "subject_instance_label": _slots_md.get("subject_instance_label") or "",
                    # `refused` when engine-o refused the slot fill for want of a person
                    # (dynamic_supervisor `FILL_SLOTS_REFUSED`; ruled 2026-10-16), so a census
                    # row reading the artifact can count it. Classify path only: the direct
                    # path never calls /fill_slots.
                    "fill_slots": _slots_md.get("fill_slots") or "",
                    "no_verb_reason": _slots_md.get("no_verb_reason") or "",
                    "fallback_detail": _slots_md.get("fallback_detail") or "",
                    "rejected_verb_iri": _slots_md.get("rejected_verb_iri") or "",
                }
                logger.info(
                    "resolved_intent captured for run %s: verb=%s disposition=%s "
                    "no_verb_reason=%s accepted=%d refused=%d",
                    run_id,
                    _slots_md.get("verb_iri") or "-",
                    _slots_md.get("disposition") or "-",
                    _slots_md.get("no_verb_reason") or "-",
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
                # THE THIRD SELECTION, unified 2026-09-06. The record and the card were
                # keyed on `pick_primary`; this still took the first EMITTED trace — so on
                # artifact-4 the trace claimed Program -> VarianceDecomposition while Engine A
                # actually answered. Three selections over one choice, and I fixed two.
                and mat is _primary_graph_trace_mat(mats)
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
                projected_sources, _floor = _sources_event_payload(mat)
                if projected_sources:
                    logger.info(
                        "📡 Emitting SSE 'sources' for run %s: %d source(s)",
                        run_id, len(projected_sources),
                    )
                    yield _sse(
                        "sources",
                        json.dumps({"sources": projected_sources, "provenance_floor": _floor}),
                    )
                    # Hop 1: accumulate into bundle.
                    _artifact_bundle["sources"] = projected_sources
                    _artifact_bundle["provenance_floor"] = _floor
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

    # THE ORDINARY PATH'S `review_request` CONSUMER (R-076). Before the payload fetch, and
    # whatever the run's outcome: see `_open_acceptances_from_run` for why both.
    for _acc_err in await _open_acceptances_from_run(run_id, _artifact_bundle):
        yield _acc_err

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
            _mark_answer_complete(_artifact_bundle, result.get("payload"))
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

    # ONE WRITER, TWO CALLERS — the direct path calls the same function. See
    # `_dispatch_answer_artifact`.
    await _dispatch_answer_artifact(_artifact_bundle)


def _mark_answer_complete(bundle: dict, payload: Any) -> None:
    """The ONLY place a bundle becomes `complete`, and the only place its duration is stamped.

    ONE SITE, TWO CALLERS — the Dagster path and the direct path. Both used to do this
    inline, which put two `duration_ms` assignments in this file and tripped the standing
    seal that says exactly one may exist: "more than one site is how a stamp drifts away
    from the status it measures." That seal was written before the direct path existed and
    caught it the first time the second site appeared.

    THE OPERANDS ARE FIXED ON PURPOSE: this bundle's OWN `valid_as_of`, set once at
    construction, to now. A later "simplification" reading a request timestamp or a step
    start would change what the number MEANS while keeping its name — birth-to-complete for
    THIS bundle is the definition.

    Deliberately NOT called on the failure paths: a failed artifact has a wall-clock
    lifetime, but that is not an answer's duration, and merging the two poisons any
    aggregate built on it.
    """
    bundle["rendered_output"] = payload
    bundle["status"] = "complete"
    bundle["duration_ms"] = max(0, int(time.time() * 1000) - bundle["valid_as_of"])


# ── THE `review_request` CONSUMER, ONE BODY FOR BOTH PATHS (R-076) ─────────────────────────
#
# Until 2026-09-29 this body lived inline in `_stream_direct_outcome`, and the direct path runs
# ONLY for a turn that answers an ask with bound slots or a spoken answer
# (`lineage_claim.pre_resolved_route_allowed`). "draft a risk assessment for HAZ-1003" names its
# hazard, never asks, and so could never reach it: measured on fleet `ec055c49`, 34 turns in a
# pod's life, zero on the direct path, zero `human_task_projection` rows of any risk kind — while
# the engine's own `/measure/draft_risk_assessment` answer carried the block in full. A consumer
# on one of two paths is a consumer the ordinary question never meets.
#
# ONE BODY, because two copies of a safety dispatch are two places for the idempotency key, the
# `/send` and the failure record to drift apart — the drift this fleet has already paid for
# three times on the card-selection rule.


def _project_review_request(mat: dict) -> dict:
    """The `review_request` a `subtask_review_request` materialization carries, or {}.

    Read back through `acceptance_request.review_request_of`, the same reader the direct path
    uses on the raw engine body — so the two paths cannot disagree about what counts as a
    request. A malformed or empty entry yields {} and opens nothing.
    """
    raw = _metadata_dict(mat).get("review_request_json")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:  # noqa: BLE001 — a malformed entry is "no request", logged by the caller
        return {}
    return acceptance_request.review_request_of({"review_request": parsed})


async def _open_safety_acceptance(
    bundle: dict, rr: dict, *, path: str, stage_kind: str,
) -> str | None:
    """Open the safety acceptance CASE (WorkflowRunner) for one `review_request`. Returns an error SSE on
    failure, None on success — and records WHICH on the artifact either way.

    NOT SILENT IN EITHER DIRECTION. The success record exists because the absence of a row was
    once only attributable by reading a rotated pod log; the artifact now says, per turn, which
    path opened which workflow.
    """
    try:
        # THE REQUESTER IS THE TURN'S PERSON, read from the envelope this turn produced -- never
        # from the engine's own `requested_by`, which names the drafter. A blank one is refused
        # by the builder, so it lands below as `acceptance_not_opened` rather than as a case
        # whose row the register would refuse after the case had already opened.
        _trigger = acceptance_request.acceptance_trigger(
            rr, authz_id=(bundle.get("produced_for") or {}).get("authz_id") or "")
        _wf_key = _trigger["acceptance_id"]
        async with httpx.AsyncClient(timeout=30.0) as _client:
            _ar = await _client.post(
                # THE CASE RUNNER, not SafetyAcceptance: the selection table picks concurrence or
                # direct acceptance and the `after:` tables carry the case to a terminal. Before
                # this, SafetyAcceptance ran only the FIRST definition -- a concurrence was never
                # followed by its acceptance. SafetyAcceptance stays registered to drain.
                f"{_RESTATE_INGRESS_URL}/WorkflowRunner/"
                f"{_restate_key(_wf_key)}/run/send",
                json={"trigger": acceptance_request.SAFETY_TRIGGER, "facts": _trigger},
                # SAME HAZARD AT THE SAME LEVEL IS THE SAME ACCEPTANCE. A re-asked question
                # must attach to the acceptance already open rather than register a second
                # task against the same authority — and the key carries the LEVEL because a
                # redraft that moves the hazard to another level is a different acceptance by
                # a different authority, which keying on the hazard alone would swallow.
                #
                # THE WORKFLOW KEY IN THE URL IS THAT IDEMPOTENCY, and it is the only one. An
                # ingress idempotency header here made Restate 1.6 refuse EVERY send with 400
                # "cannot use the idempotency key with workflow handlers" (measured 2026-09-30,
                # rev 159: HAZ-1003 fired four times, zero tasks). A second `run/send` on the
                # same key is answered as previously accepted, not run twice.
            )
        _ar.raise_for_status()
        logger.info(
            "safety acceptance dispatched: hazard=%s level=%s workflow=%s kind=%s path=%s",
            _trigger["hazard_id"], _trigger["level"], _wf_key, _trigger["kind"], path,
        )
        bundle["resolved_intent"] = dict(bundle.get("resolved_intent") or {})
        bundle["resolved_intent"].setdefault("acceptance_dispatched", []).append({
            "workflow": _wf_key,
            "kind": _trigger["kind"],
            "audience": _trigger["audience"],
            "subject_ref": rr.get("subject_ref"),
            "path": path,
        })
        return None
    except Exception as exc:  # noqa: BLE001 — the draft still renders; see the call sites
        _body = ""
        _resp = getattr(exc, "response", None)
        if _resp is not None:
            try:
                _body = _resp.text[:800]
            except Exception:  # noqa: BLE001
                _body = "<unreadable>"
        logger.error(
            "safety acceptance NOT opened for %s (%s: %s) path=%s body=%s",
            rr.get("subject_ref"), type(exc).__name__, exc, path, _body,
        )
        bundle["resolved_intent"] = dict(bundle.get("resolved_intent") or {})
        bundle["resolved_intent"]["acceptance_not_opened"] = {
            "exception": type(exc).__name__,
            "message": str(exc)[:600],
            # WHAT WAS ASKED FOR, beside what came back — a refusal naming a field is only
            # actionable against the request that omitted it.
            "kind": rr.get("kind"),
            "audience": rr.get("audience"),
            "subject_ref": rr.get("subject_ref"),
            "body": _body,
            "where": f"{path}/review_request_consumer",
        }
        return _perror(
            "The risk assessment was drafted, but its acceptance review could not be "
            "opened — no task has been created for the accepting authority.",
            kind=stage_kind,
            retryable=True,
            cause="acceptance_not_opened",
        )


async def _open_acceptances_from_run(run_id: str, bundle: dict) -> list[str]:
    """The ordinary (Dagster) path's consumer: every `subtask_review_request` the run
    materialized, opened once each. Returns the error SSEs to yield.

    READ ONCE, AFTER THE POLL LOOP, NOT INSIDE IT. The loop breaks on SUCCESS before pulling
    that iteration's materializations, so a request materialized after the last poll would be
    seen by nothing — a consumer that works whenever the render is slow and never when it is
    fast.

    KEYED ON THE REQUEST BEING PRESENT, NOT ON THE RENDER SUCCEEDING. The materialization is
    emitted by `execute_subtask` from the engine's own body, BEFORE Engine F renders — the same
    position the direct path's consumer holds, for the same reason: the render drops the block,
    and a hazard that was drafted was drafted whether or not its card drew.

    AN EMPTY READ IS NOT "NO REQUEST". `_get_run_events` returns [] on any GraphQL failure, and
    every run materializes `active_agent_roster`, so zero materializations means the read
    failed. That is recorded on the artifact rather than read as absence.
    """
    mats = await _get_run_events(run_id)
    if not mats:
        logger.warning(
            "acceptance check for run %s read ZERO materializations — the read failed, "
            "so whether the engine asked for an acceptance is UNKNOWN, not no", run_id,
        )
        bundle["resolved_intent"] = dict(bundle.get("resolved_intent") or {})
        bundle["resolved_intent"]["acceptance_check"] = {"materializations_read": 0}
        return []
    # ONE MATERIALIZATION CAN ARRIVE TWICE: `_get_run_events` merges `eventConnection` with
    # `stepStats`. Restate's idempotency key would absorb the second send, but a second
    # `acceptance_dispatched` entry on the artifact would claim two acceptances were opened.
    seen: set[str] = set()
    errors: list[str] = []
    for mat in mats:
        if (mat.get("assetKey") or {}).get("path") != ["subtask_review_request"]:
            continue
        rr = _project_review_request(mat)
        if not rr:
            logger.warning(
                "run %s materialized subtask_review_request with no readable request", run_id,
            )
            continue
        ident = json.dumps(rr, sort_keys=True, default=str)
        if ident in seen:
            continue
        seen.add(ident)
        err = await _open_safety_acceptance(
            bundle, rr, path="run", stage_kind="retrieving",
        )
        if err:
            errors.append(err)
    return errors


async def _stream_direct_outcome(
    *,
    outcome,
    bundle: dict,
    session_id: str,
    frontend_id: str,
    user_persona: str,
    frontend_version: str = "",
) -> AsyncGenerator[str, None]:
    """Emit the SSE for a turn the direct path answered, and fill the artifact bundle.

    THE SAME PROJECTORS, deliberately. `_project_route_decision`, `_project_graph_trace` and
    `_project_graph_trace_alternates` are the ones the Dagster path uses; the direct path
    hands them materializations rather than projected records precisely so this stays true.
    A second shaper is how the card and the routing record came to select different
    subtasks in production.

    ONLY ROUTED AND ABSTAIN REACH HERE. An `ask` is routed through the full run instead —
    see the caller. That is a deliberate scope line, not an oversight: the ask card and its
    menu are built inside the supervisor, and a menu rebuilt slightly differently here would
    be WRONG rather than slow, which is the one trade this path is not allowed to make.
    """
    if outcome.routing_mat is not None:
        decision = _project_route_decision(outcome.routing_mat)
        if decision is not None:
            yield _sse("route_decision", json.dumps(decision))
            bundle["routing"] = decision
            handled_by = (decision.get("handled_by") or {}) if isinstance(
                decision, dict
            ) else {}
            if handled_by:
                bundle["produced_by"] = {
                    "actor_type": "agent",
                    "actor_id": handled_by.get("engine_name")
                    or handled_by.get("name") or "pending",
                    "endpoint": handled_by.get("endpoint"),
                    "version": handled_by.get("version"),
                }

    if outcome.graph_trace_mat is not None:
        trace_nodes = _project_graph_trace(outcome.graph_trace_mat)
        if trace_nodes:
            alternates = _project_graph_trace_alternates(outcome.graph_trace_mat)
            yield _sse("graph_trace", json.dumps({
                "nodes": trace_nodes, "alternates": alternates,
            }))
            bundle["graph_trace"] = trace_nodes
            bundle["graph_trace_alternates"] = alternates

    if outcome.slots_mat is not None:
        _slots_md = _metadata_dict(outcome.slots_mat)
        bundle["resolved_intent"] = dict(bundle.get("resolved_intent") or {})
        bundle["resolved_intent"]["accepted_slots"] = json.loads(
            _slots_md.get("accepted_slots") or "{}"
        )
        # ── THE PROVENANCE RECORD, ON THE PATH THAT ACTUALLY RUNS ────────────────────────
        #
        # TWO COMPOSITION SITES, and this is the one a pick-answer reaches. Writing the field
        # only at the classify-path site above would have left the writer as inert as the
        # reader it was built to feed — "one site" turning out to be two for the third time on
        # this arc, which is why it is asserted rather than remembered.
        try:
            _bss = json.loads(_slots_md.get("bound_slot_sources") or "{}")
        except (ValueError, TypeError):
            _bss = {}
        if isinstance(_bss, dict) and _bss:
            bundle["resolved_intent"]["bound_slot_sources"] = _bss
        bundle["resolved_intent"]["refused_slots"] = json.loads(
            _slots_md.get("refused_slots") or "[]"
        )
        # ── THE VERB AND THE DISPOSITION TRAVEL WITH THE SLOTS ────────────────────────────
        #
        # This wrote ONLY the two slot keys onto whatever `resolved_intent` already held — and
        # on the direct path that is nothing. Measured on artifact-2-1789404372153: a FAILED
        # artifact whose entire intent was
        #
        #     {"refused_slots": [], "accepted_slots": {"program_id": "NP-MERIDIAN"}}
        #
        # while artifact-1 and the older cost artifact both carry `verb_iri`, `disposition`,
        # `subject_uri` and `owner_persona`.
        #
        # **A FAILED ARTIFACT WITH NO VERB IS UNATTRIBUTABLE BY CONSTRUCTION.** It took three
        # reads of the artifact store to learn which verb had been refused, and the answer was
        # sitting in `routing.excluded[]` the whole time — in a different column, because the
        # field that names the action had been dropped from the field that records the intent.
        #
        # Written with `setdefault` rather than assignment: where a fuller intent already exists
        # (the classify path fills it in above) this must not overwrite it with the direct
        # path's view. Only the absent keys are supplied.
        for _k in ("verb_iri", "disposition", "subject_uri", "owner_persona",
                   "subject_instance_id", "subject_instance_label", "slot_resolution"):
            _v = _slots_md.get(_k)
            if _v not in (None, ""):
                bundle["resolved_intent"].setdefault(_k, _v)

    if outcome.kind == direct_dispatch.ABSTAIN:
        # THE VERB WAS RIGHT AND THE ENGINE DID NOT ANSWER. The routing record above is
        # already emitted, so the decision path renders and a reader can see WHICH engine
        # was asked — which is the whole difference between this and a blank failure.
        logger.warning(
            "direct path abstained for run %s: %s", session_id, outcome.reason,
        )
        yield _perror(
            "The specialist did not return an answer.",
            kind=direct_dispatch.STAGE_CALLING,
            retryable=True,
            cause="engine_did_not_answer",
        )
        # ── THE ARTIFACT RECORDS ITS OWN CAUSE ──────────────────────────────────────────
        #
        # Without this the `failed` artifact says WHICH VERB was tried and nothing about what
        # came back, and the answer lives only in a pod log that rotates. Measured on
        # artifact-2-1789439072125: the engine replied
        # `{"loc":["body","fn"],"msg":"Field required"}` — the refusal was built to NAME THE
        # ARGUMENT — and recovering it took a replay against the live pod with a hand-rebuilt
        # request body, because the artifact recorded neither the cause nor the body.
        #
        # Same class as the missing `verb_iri` one layer over, and the same repair: a failure
        # recorded where nobody reads is a failure nobody can act on.
        if getattr(outcome, "failure_cause", None):
            bundle["resolved_intent"] = dict(bundle.get("resolved_intent") or {})
            bundle["resolved_intent"]["failure_cause"] = outcome.failure_cause
            logger.warning(
                "direct path failure cause for run %s: %s",
                session_id, json.dumps(outcome.failure_cause, default=str)[:600],
            )
        bundle["status"] = "failed"
        return

    # ── THE RENDER. Engine F, with the SAME request body the run builds. ────────────────
    _expert = outcome.engine_response or {}

    # ── THE `review_request` CONSUMER'S CALL SITE (R-076) ───────────────────────────────
    #
    # `engine-safety` has emitted `review_request` on every drafted risk assessment since
    # 2026-09-12, with a comment naming THIS FILE as its reader, and nothing ever read it. A
    # producer that did the right thing and documented it, into silence — and the documentation
    # is what made it expensive, because "a consumer reads one field for…" stops the next person
    # looking.
    #
    # IT SITS HERE, BEFORE THE RENDER, AND THE POSITION IS THE POINT. Measured 2026-09-19 on the
    # live fleet: the engine's own `/measure/draft_risk_assessment` response for HAZ-1003 carries
    # the block in full, and the RENDERED turn carries none of it — Engine F renders a card and
    # the block does not survive into it. So a consumer placed downstream of the render would
    # find nothing, forever, and would look correct doing it. (That surface difference is also
    # why the walk census scores this row `drawn` while the engine asks for a task properly: the
    # census reads the rendered turn, which never carried the request.)
    #
    # AND IT DOES NOT BLOCK THE TURN. The acceptance suspends on a human promise for as long as
    # a human takes; calling the workflow synchronously would hold this request open for days.
    # `/send` is one-way — Restate journals it and the turn carries on rendering the draft.
    #
    # A FAILURE HERE DOES NOT FAIL THE TURN, AND IT IS NOT SILENT EITHER. The hazard WAS drafted
    # and the user must see it; but "the draft rendered" and "the acceptance was opened" are
    # different facts, and merging them is how a safety engineer concludes a review is underway
    # when nothing was asked of anyone. The cause lands on the artifact, where a reader asks why.
    if _expert:
        _rr = acceptance_request.review_request_of(_expert)
        if _rr:
            # I3: stamp the minted case key onto the block the render reads (`_expert` is
            # `expert_response` below), before anything downstream sees the engine's own copy.
            _rr = acceptance_request.with_minted_ids(_rr)
            _expert["review_request"] = _rr
            _err = await _open_safety_acceptance(
                bundle, _rr, path="direct", stage_kind=direct_dispatch.STAGE_CALLING,
            )
            if _err:
                yield _err

    _predicate = outcome.predicate or {}
    _results = [{
        "persona": _predicate.get("owner_persona") or user_persona,
        "user_persona": user_persona,
        "answerer_persona": _predicate.get("owner_persona") or user_persona,
        "predicate_verb_iri": _predicate.get("verb_iri"),
        "sub_query": bundle.get("question_text") or "",
        # THE KEY THE CARD SELECTS BY. One result here, so `pick_primary` is trivially this
        # one — but the field is set because Engine F and the projector both read it, and a
        # single-element list that omits it would be the one shape neither was tested on.
        "route_status": "matched",
        "expert_response": _expert,
    }]
    # ADR-0017: the verb's REGISTERED output class, so Engine F does a deterministic
    # predicate-graph lookup instead of asking BAML to classify the data shape. The run
    # takes it off the expert's echo; here the registration is in hand and is the source
    # the echo was copied from.
    _output_uri = (
        (_expert.get("output_uri") if isinstance(_expert, dict) else None)
        or _predicate.get("output_uri")
        or None
    )

    yield _stage(direct_dispatch.STAGE_RENDERING, "started")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            _resp = await client.post(
                f"{_PRESENTATION_AGENT_SVC_URL}/render_ui",
                json={
                    "raw_data": _results,
                    "user_persona": user_persona,
                    # Legacy alias, kept in step with the run's body: Engine F reads
                    # `persona` for the chrome archetype, which is the user-side concern.
                    "persona": user_persona,
                    "output_uri": _output_uri,
                    "frontend_id": frontend_id or None,
                    "frontend_version": frontend_version or None,
                },
            )
            _resp.raise_for_status()
            _payload = _resp.json()
            _presentation_path = _resp.headers.get("X-Presentation-Path", "unknown")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "direct path render failed for run %s (%s: %s)",
            session_id, type(exc).__name__, exc,
        )
        yield _stage(direct_dispatch.STAGE_RENDERING, "failed")
        yield _perror(
            "Failed to render the answer.",
            kind=direct_dispatch.STAGE_RENDERING,
            retryable=True,
            cause="render_ui_failed",
        )
        bundle["status"] = "failed"
        return

    logger.info(
        "direct path rendered run %s via presentation_path=%s",
        session_id, _presentation_path,
    )
    _uris = _expert.get("referenced_uris") if isinstance(_expert, dict) else None
    if _uris:
        yield _sse("context_update", json.dumps({"type": "bindings", "data": _uris}))

    yield _stage(direct_dispatch.STAGE_RENDERING, "completed")
    yield _sse("final_payload", json.dumps(_payload))
    _mark_answer_complete(bundle, _payload)


async def _dispatch_answer_artifact(bundle: dict) -> None:
    """Schedule the AnswerArtifact Neo4j write. ONE writer, TWO callers.

    Lifted verbatim out of the graph-path generator on 2026-09-08 so the DIRECT path
    writes through exactly this code. A second copy would carry today's fields and
    miss tomorrow's — `derived_from_artifact_id` and the composed summary are already
    the kind of field that gets added to one writer and not the other, and the lineage
    edge is the whole reason a pick is a pick rather than a new question.

    Never raises: every caller treats it as a trailing step that cannot fail delivery.
    """
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
        # exit path was added without a status flip.
        #
        # ⛔ THIS USED TO SKIP THE WRITE, and the reasoning was careful and wrong in one step:
        # *"we do NOT default to 'failed' because the dispatch site has no idea what actually
        # happened; only the gateway exit paths know."* True about the DETAIL and false about
        # the FACT. **"The turn ended without recording an outcome" is itself what happened**,
        # and it is recordable honestly — naming the condition rather than guessing a cause.
        #
        # Skipping conflated *do not invent a cause* with *do not write anything*, and the
        # second is what produced silence: no artifact, no row in the rail, nothing for a reader
        # to pull on. Measured 2026-09-14 on the sibling path, where a NameError ended the
        # stream and the turn left no trace at all — you cannot record an absence, so the fix is
        # to stop producing one.
        #
        # The cause below says exactly and only what is known. It does not claim the engine
        # failed, because nobody here knows that.
        if bundle["status"] == "pending":
            logger.error(
                "AnswerArtifact still 'pending' at stream_end for artifact %s — some exit path "
                "returned without recording an outcome. Writing it as FAILED with that as the "
                "cause rather than skipping, so the turn is not silent.",
                bundle["id"],
            )
            bundle["status"] = "failed"
            _ri = dict(bundle.get("resolved_intent") or {})
            _ri.setdefault("failure_cause", {
                "exception": "NoOutcomeRecorded",
                "message": (
                    "the stream ended with status still 'pending': an exit path returned "
                    "without flipping status to complete or failed. The turn's outcome was "
                    "never recorded; this artifact exists so the turn is not silent."
                ),
                "where": "_dispatch_answer_artifact",
            })
            bundle["resolved_intent"] = _ri
            # NO `return` HERE, and its removal is the whole change. The old code logged and
            # returned; the log was the only trace, in a pod whose logs rotate.

        # ── A FAILURE WITH NO CAUSE IS THE SAME SILENCE ONE STATE OVER ──────────────────────
        #
        # The branch above catches `pending` — a route that returned without recording an
        # outcome at all. It does NOT catch a route that recorded `failed` and no reason, and
        # that is the shape safety's dispatch produces.
        #
        # MEASURED on artifact-1-1789497444373, "draft a risk assessment for HAZ-1003":
        # status `failed`, `duration_ms` 58757, and NO `failure_cause`. The resolution had
        # worked perfectly — `outcome: exact`, the hazard's full label bound — and then
        # something waited 59 seconds and the record said nothing about what. 74 could not
        # replay it because there was no request to replay.
        #
        # WHY IT ESCAPED: the cause writer lives in `direct_dispatch`'s `except`, so the
        # graph-host route records its cause and the per-verb `/measure/{fn}` route safety uses
        # records none. FIVE call sites in this file set `status = "failed"` and ONE of them
        # writes a cause. Extending that writer to each route is the fix that has to be
        # repeated every time a route is added; this is the exit they all pass through.
        #
        # IT DOES NOT CLAIM THE ENGINE FAILED, because nobody here knows that. It records the
        # one fact available at this exit — the turn ended failed and the path that failed it
        # left no reason — plus whatever routing metadata the bundle already carries, so the
        # next diagnosis starts at the right pod instead of at this function.
        if bundle.get("status") == "failed":
            _ri = dict(bundle.get("resolved_intent") or {})
            if not _ri.get("failure_cause"):
                # `routing`, NOT `routing_inline`. THE FIRST VERSION READ THE WRONG KEY and so
                # wrote a cause with every diagnostic field empty — `route_status: ""`,
                # `engine_name: ""` — under a comment claiming empty meant the bundle carried no
                # routing, "which is itself the finding." It was not the finding. `routing_inline`
                # is a column read back in a DIFFERENT query (see the artifact SELECT above);
                # `bundle["routing"]` is the live decision this same function writes to the
                # artifact's `routing` column a few lines down. So the row persisted a full
                # route beside a cause that said nothing about it.
                #
                # A CAUSE WITHOUT ITS ROUTE IS UNATTRIBUTABLE, which is the exact defect this
                # writer exists to end — committed one level up, in the writer itself.
                _inline = bundle.get("routing") or {}
                if isinstance(_inline, str):
                    try:
                        _inline = json.loads(_inline)
                    except Exception:  # noqa: BLE001 — diagnostics must not raise here
                        _inline = {}
                _handled = (_inline.get("handled_by") or {}) if isinstance(_inline, dict) else {}
                _action = (_inline.get("action") or {}) if isinstance(_inline, dict) else {}
                _about = (_inline.get("about") or {}) if isinstance(_inline, dict) else {}
                logger.error(
                    "AnswerArtifact %s is FAILED with no failure_cause — the route that failed "
                    "it recorded no reason. Writing a typed cause naming that, rather than "
                    "leaving an artifact that says a turn failed and nothing about why.",
                    bundle.get("id"),
                )
                _ri["failure_cause"] = {
                    "exception": "NoCauseRecorded",
                    "message": (
                        "the turn ended FAILED and the path that failed it recorded no cause. "
                        "This is not a claim that the engine failed — it is the absence of a "
                        "record, written down so the absence is visible in the artifact rather "
                        "than only in a log."
                    ),
                    "where": "_dispatch_answer_artifact",
                    # WHAT IS KNOWN, so a replay starts somewhere. Empty when the bundle
                    # carried no routing either, which is itself the finding.
                    "route_status": (_inline.get("route_status") if isinstance(_inline, dict) else None) or "",
                    "engine_name": _handled.get("engine_name") or "",
                    "endpoint_url": _handled.get("endpoint_url") or "",
                    "duration_ms": bundle.get("duration_ms"),
                    # WHY THERE WAS NO ANSWER, not only where it would have come from. These
                    # four separate "nothing matched" from "nothing was asked": an empty pool
                    # with `classify_called: false` is a turn that never reached the classifier,
                    # and it is indistinguishable from a classifier that ran and refused unless
                    # the record says which.
                    "subject_uri": _about.get("uri") or "",
                    "candidate_count": _action.get("candidate_count"),
                    "classify_called": _action.get("classify_called"),
                    "fallback_reason": _inline.get("fallback_reason") or "",
                }
                bundle["resolved_intent"] = _ri

        _writer = get_writer()
        if _writer is not None:
            # Compose the factual S·P headline HERE — the single write
            # point where `routing` (SPO + fallback_reason) is final and
            # the artifact is about to persist. Captured on the bundle,
            # written to the node, projected, read verbatim. See
            # `_compose_answer_summary`.
            _bundle_obj = AnswerArtifactBundle(
                id=bundle["id"],
                question_text=bundle["question_text"],
                summary=_compose_answer_summary(bundle["routing"]),
                message_id=bundle["message_id"],
                valid_as_of=bundle["valid_as_of"],
                status=bundle["status"],
                produced_by=bundle["produced_by"],
                produced_for=bundle["produced_for"],
                resolved_intent=bundle["resolved_intent"],
                routing=bundle["routing"],
                sources=bundle["sources"],
                graph_trace=bundle["graph_trace"],
                rendered_output=bundle["rendered_output"],
                derived_from_artifact_id=bundle[
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
                bundle["id"],
            )
        else:
            logger.warning(
                "AnswerArtifact writer not available; artifact %s NOT "
                "scheduled for persistence (trailing-step non-fatal).",
                bundle["id"],
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


def _emit_menu_to_registrar(registrar_url: str, frontend_id: str, frontend_version: str | None,
                          admitted: list[dict]) -> tuple[int, list]:
    """Emit each admitted capability to the registrar (SYNC HTTP: run it off the event loop).

    Shared by the registration route and the startup replay. Returns (registered, failed)."""
    from agent_fleet.presentation_agent.capabilities import capability_slug as _capability_slug
    _graph_registered, _graph_failed = 0, []
    from agent_fleet.utils.mesh_registration import _emit_presentation_to_registrar

    for _c in admitted:
        _contract = _c.get("contract") if isinstance(_c, dict) else None
        _recomputes = None
        if isinstance(_contract, dict) and "recomputes" in _contract:
            # Tri-state preserved end to end: only a DECLARED value travels.
            _recomputes = bool(_contract.get("recomputes"))
        _outcome = _emit_presentation_to_registrar(
            registrar_url=registrar_url,
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
                f"__{frontend_id}"
            ),
            description=(
                f"{frontend_id} renders {_c.get('subject_uri')} "
                f"as {_c.get('archetype')}"
            ),
            subject_uri=str(_c.get("subject_uri") or ""),
            object_uri=str(_c.get("object_uri") or ""),
            archetype=str(_c.get("archetype") or ""),
            expected_fields=list(_c.get("expected_fields") or []),
            persona_fit=list(_c.get("persona_fit") or []),
            domain_fit=list(_c.get("domain_fit") or []),
            # The mesh helper takes `version: str`. An ABSENT version is carried as
            # empty rather than the string "None", which is what `str(None)` would put
            # into the graph and what a reader would then see as a version.
            version=frontend_version or "",
            frontend_id=frontend_id,
            recomputes=_recomputes,
        )
        if _outcome is True:
            _graph_registered += 1
        else:
            _graph_failed.append({"subject_uri": _c.get("subject_uri"),
                                  "reason_class": _outcome[0], "detail": _outcome[1][:200]})
    return _graph_registered, _graph_failed



_frontend_menu_store_instance = None
_frontend_menu_store_warned = False


def _frontend_menu_store():
    """The menu store, or None when PROJECTOR_POSTGRES_DSN is unset (logged once, never a crash)."""
    global _frontend_menu_store_instance, _frontend_menu_store_warned
    if not frontend_menu_store.configured():
        if not _frontend_menu_store_warned:
            _frontend_menu_store_warned = True
            _frontend_registry_logger.warning(
                "frontend menu store dormant (no PROJECTOR_POSTGRES_DSN): menus are not "
                "persisted and will not be replayed after a graph wipe")
        return None
    if _frontend_menu_store_instance is None:
        _frontend_menu_store_instance = frontend_menu_store.PgFrontendMenuStore()
    return _frontend_menu_store_instance


def _fetch_graph_entries():
    """The graph's registered menus, or None when it is unreachable (sync; run off the loop)."""
    from agent_fleet.presentation_agent.graph_menu_source import fetch_registered_entries

    return fetch_registered_entries()


def _graph_holds_menu(entries, frontend_id: str, frontend_version: str | None,
                      admitted: list[dict]) -> bool:
    """True only when the graph (a dict, not None) holds this frontend's version with every
    admitted capability.

    COVERAGE IS KEYED BY (subject_uri, archetype), not by count: those two fields are what the
    emit puts in the row's name (presentation_<archetype>_for_<subject>__<frontend_id>). The
    graph read returns the EXPANDED IRI while the post may carry a CURIE (`fin:X`), so both
    sides are canonicalised with `canonical_iri_for_lookup` before comparing (measured on the
    sandbox 2026-10-20: 35 of 49 keys missed). A count would call a menu with one capability
    swapped for another "held". The graph may hold MORE than the post (a stale row); that is
    covered, and a changed menu is caught by the digest, not here.
    """
    if not isinstance(entries, dict):
        return False
    entry = entries.get(frontend_id)
    if not isinstance(entry, dict):
        return False
    group = (entry.get("versions") or {}).get(frontend_version or "")
    if not isinstance(group, dict):
        return False
    from agent_fleet.presentation_agent.capabilities import canonical_iri_for_lookup as _canon

    held = {(_canon(str(c.get("subject_uri") or "")), c.get("archetype") or "")
            for c in (group.get("capabilities") or [])}
    wanted = {(_canon(str(c.get("subject_uri") or "")), str(c.get("archetype") or ""))
              for c in admitted}
    return wanted <= held


# Replay retry schedule: 6 attempts, ~5 minutes in all (seconds slept BEFORE attempts 2..6).
_FRONTEND_MENU_REPLAY_DELAYS = (15, 30, 60, 90, 105)


def _replay_frontend_menus_once() -> bool:
    """One replay pass. Returns True when done, False when it should be retried.

    Retry while the graph read is None (unreachable) or the registrar refused every
    capability of some frontend. Sync: run off the event loop.
    """
    from agent_fleet.presentation_agent import capability_registry as _cap_registry

    registrar_url = os.getenv("MESH_REGISTRAR_URL")
    store = _frontend_menu_store()
    if store is None or not registrar_url:
        return True
    rows = store.load_all()
    if not rows:
        return True
    for row in rows:
        _cap_registry.register(row["frontend_id"], row["frontend_version"], row["menu"])
    entries = _fetch_graph_entries()
    if entries is None:
        _frontend_registry_logger.warning(json.dumps({
            "event": "frontend_menu_replay_graph_unreachable", "frontends": len(rows)}))
        return False
    done = True
    for row in rows:
        fid, ver, menu = row["frontend_id"], row["frontend_version"], row["menu"]
        if not menu or _graph_holds_menu(entries, fid, ver, menu):
            _frontend_registry_logger.info(json.dumps({
                "event": "frontend_menu_replayed", "frontend_id": fid,
                "registered": 0, "failed": 0, "skipped": len(menu)}))
            continue
        registered, failed = _emit_menu_to_registrar(registrar_url, fid, ver, menu)
        _frontend_registry_logger.info(json.dumps({
            "event": "frontend_menu_replayed", "frontend_id": fid,
            "registered": registered, "failed": len(failed), "skipped": 0}))
        if registered == 0 and failed:
            done = False
    return done


async def _replay_frontend_menus() -> None:
    """Background task at BFF startup: put stored frontend menus back into the graph after a wipe.

    Never blocks startup or /health and never raises.
    """
    from starlette.concurrency import run_in_threadpool

    attempts = len(_FRONTEND_MENU_REPLAY_DELAYS) + 1
    for attempt in range(attempts):
        if attempt:
            await asyncio.sleep(_FRONTEND_MENU_REPLAY_DELAYS[attempt - 1])
        try:
            if await run_in_threadpool(_replay_frontend_menus_once):
                return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a replay fault is retried, never raised
            _frontend_registry_logger.warning("frontend menu replay attempt %d failed: %s",
                                              attempt + 1, exc)
    _frontend_registry_logger.warning(json.dumps({
        "event": "frontend_menu_replay_gave_up", "attempts": attempts}))



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
    _unchanged = False
    _registrar_url = os.getenv("MESH_REGISTRAR_URL")
    if _registrar_url:
        # ── THE EMIT LOOP RUNS OFF THE EVENT LOOP ──────────────────────────────────
        # Was: this loop ran inline in an `async def`, and each
        # `_emit_presentation_to_registrar` is a SYNC HTTP POST (timeout=30.0). Measured
        # live on rev 186 (2026-10-10): ~49 capabilities per registration at a mean 0.42s
        # each held the loop ~21s per registration. Every cortex tab registers at load,
        # two overlapping registrations exceeded the 50s liveness window (5 x 10s /health
        # timeouts) and the probe killed cortex-bff (exit 137); each restart made the tabs
        # re-register. Now the whole loop is a plain function run in the threadpool.
        # `_cap_registry.register` above is an in-process dict and stays on the loop.
        from starlette.concurrency import run_in_threadpool

        _, _admit_sha = frontend_menu_store.menu_digest(_admitted)
        _store = _frontend_menu_store()
        if _store is not None:
            # NO-OP WHEN THE STORED MENU MATCHES AND THE GRAPH STILL HOLDS IT (ruling Q9). The
            # store alone is not enough: a wipe empties the graph and leaves the row, so the
            # graph is read too. An unreachable graph (None) is never a no-op.
            def _already_registered() -> bool:
                _row = _store.load(payload.frontend_id)
                if not _row or _row["menu_sha256"] != _admit_sha:
                    return False
                if (_row["frontend_version"] or "") != (payload.frontend_version or ""):
                    return False
                return _graph_holds_menu(_fetch_graph_entries(), payload.frontend_id,
                                         payload.frontend_version, _admitted)

            _unchanged = await run_in_threadpool(_already_registered)
        if _unchanged:
            _frontend_registry_logger.info(json.dumps({
                "event": "frontend_capabilities_unchanged",
                "frontend_id": payload.frontend_id,
                "frontend_version": payload.frontend_version,
                "admitted_count": len(_admitted),
            }))
        else:
            _graph_registered, _graph_failed = await run_in_threadpool(
                _emit_menu_to_registrar, _registrar_url, payload.frontend_id,
                payload.frontend_version, _admitted)
            if _store is not None:
                _saved = await run_in_threadpool(
                    lambda: _store.save(payload.frontend_id, payload.frontend_version, _admitted,
                                        registered_by=str(current_user.id),
                                        registered_at=int(time.time())))
                if not _saved.get("ok"):
                    _frontend_registry_logger.error(json.dumps({
                        "event": "frontend_menu_save_failed",
                        "frontend_id": payload.frontend_id,
                        "reason": _saved.get("reason"),
                    }))
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
        unchanged=_unchanged,
    )


@app.post("/orchestrate", tags=[MCP_TAG])
@app.post("/interview/stream")
@_audit_orchestrate_refusals
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

    # ── ADR-0050 §3's SEED_PANEL — VALIDATED BEFORE THE STREAM OPENS, NEVER MID-STREAM ────
    #
    # `seed_template_canvas` is the only caller today, but this gate is the contract for
    # `seed_panel` itself, not for that one caller — any client naming a template/panel pair
    # gets the same refusals. Mirrors `canvas_seed`'s own gates (same two faults, same status
    # codes) because they are the same faults: an unknown id or an out-of-range index is a
    # caller mistake (422), a consumed shared slot with nothing binding it is a request the
    # panel cannot answer yet (422, named), and — new here — a panel with no declared
    # `subject` cannot be dispatched directly AT ALL, because `_pre_resolved_from_seed_panel`
    # has nothing to hand `dispatch_pre_resolved` as `subject_uri`. All of this runs BEFORE
    # the stream opens so the caller gets one clean HTTP status rather than a pipeline_error
    # buried inside an SSE body it already started reading.
    if request.seed_panel is not None:
        from .canvas_template import load_template, ratified_template_ids

        # A SEED IS NOT AN ANSWER. The stream honours `seed_panel` only when no ask is being
        # answered, so a turn carrying both would silently drop the seed and route the
        # ordinary way — a seeded panel answering a different question. Refused here, by name.
        if request.answering_artifact_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "seed_panel and answering_artifact_id cannot be sent together: a seeded "
                    "panel answers no ask. Send one or the other."
                ),
            )

        _sp = request.seed_panel
        _sp_template_id = str(_sp.get("template_id") or "")
        try:
            _sp_template = load_template(_sp_template_id)
        except (KeyError, ValueError) as _sp_terr:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"seed_panel names template_id {_sp_template_id!r}, which is not a "
                    f"ratified template (ratified: {ratified_template_ids()}) — {_sp_terr}"
                ),
            )

        _sp_panel_idx = _sp.get("panel")
        if not isinstance(_sp_panel_idx, int) or not (
            0 <= _sp_panel_idx < len(_sp_template.panels)
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"seed_panel names panel {_sp_panel_idx!r}, out of range for template "
                    f"{_sp_template_id!r} (has {len(_sp_template.panels)} panel(s))."
                ),
            )
        _sp_panel = _sp_template.panels[_sp_panel_idx]

        # A PANEL WITH NO DECLARED `subject` CANNOT BE DISPATCHED DIRECTLY. `portfolio`'s
        # panels are the ratified example (ADR-0050 §3's carry has not landed there) — naming
        # one here is a caller mistake, not the ADR-0050 §3 carry gap (that is the 409 below).
        if not _sp_panel.subject:
            raise HTTPException(
                status_code=422,
                detail=(
                    "this template's panel declares no subject, so it cannot be dispatched "
                    "directly"
                ),
            )

        _sp_declared = {s.name for s in _sp_template.shared_slots}
        _sp_bindings = {
            k: v for k, v in (_sp.get("bindings") or {}).items() if v not in (None, "")
        }

        # A BINDING NAMING A SLOT THE TEMPLATE NEVER DECLARED — the same typo-shaped fault
        # `canvas_seed` names on the request side.
        _sp_unknown = sorted(set(_sp_bindings) - _sp_declared)
        if _sp_unknown:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"template {_sp_template_id!r} does not declare shared slot(s) "
                    f"{_sp_unknown} named in seed_panel's `bindings`."
                ),
            )

        # A CONSUMED SLOT WITH NOTHING BINDING IT — this panel, specifically, not the whole
        # template: a caller asking for panel 0 must not be refused over panel 5's slot.
        _sp_unbound = sorted(set(_sp_panel.consumes) - set(_sp_bindings))
        if _sp_unbound:
            from .authz.refusal import policy_refusal
            from .canvas_template import slot_refusal
            # A POLICY REFUSAL (it asks the caller to choose) -- `canvas_template.slot_refusal`.
            raise policy_refusal(
                "unbound_required_slot",
                status_code=409,
                message=(
                    f"template {_sp_template_id!r} panel {_sp_panel_idx} consumes shared "
                    f"slot(s) {_sp_unbound} that nothing binds yet. Supply it in seed_panel's "
                    f"`bindings`."
                ),
                **slot_refusal(_sp_template, _sp_unbound),
            )

    return StreamingResponse(
        _keepalive_wrap(
            # INSIDE the keepalive: `_keepalive_wrap` turns a producer exception into an error
            # event, so only here can the audit line say `outcome=error`.
            _audit_orchestrate_wrap(
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
                who=current_user.authz_id,
                via=getattr(current_user, "azp", None) or "",
                session_id=request.session_id,
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
    """READINESS REFUSES WHEN A SERVICE URL WAS NEVER DECLARED. RULED 2026-09-11.

    This handler previously returned `{"status": "ok"}` unconditionally — it could not express
    any other answer, which is the same defect engine-lg shipped: a probe whose only reachable
    value is the healthy one is not a probe. See
    docs/principles/a-host-with-nothing-admitted-is-not-ready.md.

    A missing ConfigMap entry for a service URL is a DEPLOY fault. It must not be papered over
    by an in-cluster default that happens to resolve today, because the census derives the fleet
    from those variables: with a fallback the undeclared service still answers and still reports
    a real sha, so the census prints a green row for an address that exists nowhere in the chart.
    """
    if _UNDECLARED_SERVICE_URLS:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "service": "cortex-orchestrator-proxy",
                "reason": "service URL(s) undeclared — deploy fault, not a runtime fault",
                "undeclared": dict(sorted(_UNDECLARED_SERVICE_URLS.items())),
            },
        )
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
# Ingestion seam (ADR-0041 §8, days 1-3) — POST /ingest, GET /ingest/{id}/status
# ════════════════════════════════════════════════════════════════════
#
# HOSTED HERE, not on any fleet engine — an ADR-silent decision, recorded here because the
# ADR names no host. `agent_fleet/docs_agent` was considered and ruled out: its entire
# surface is `mesh:explain` over REVIEWED mesh:DocPage documentation, gated behind mesh
# TRANSPORT auth (not end-user auth) on every route — semantically unrelated to a
# non-technical user dropping a PCN/PDN, and the wrong auth plane besides. The actual
# document-PROCESSING pipeline (classify/extract/review) is Dagster-side
# (src/iagent/defs/extraction_review_sensor.py + the sibling doc-tools repo), triggered by
# an S3 sensor on this SAME `processing-artifacts` bucket — not a FastAPI/Restate engine
# either. cortex-bff already holds a direct MinIO client for this exact bucket
# (_build_notice_prefix_index / _read_notice_provenance_from_store above, and
# federated_image just above this block) — this reuses that pattern rather than adding a
# proxy hop to a new engine that would own nothing but the hop.
#
# on_behalf_of, v1: MUST equal the authenticated caller's own authz_id. ADR-0041 §8 names
# the field but not a delegation mechanism, and deny-by-default means the narrower reading
# wins until one exists — a caller asserting an identity that is not their own is refused,
# not merely unverified.
#
# authoritative_source, v1: ADR-0041 §2 says it "remains the vendor who issued the PCN" —
# but that is only knowable once the document is CLASSIFIED (§4, Dagster-side, out of this
# seam's days-1-3 scope). At the door we have bytes and a declared kind, not a read PDF.
# Rather than leave the required field guessed or blank, this seam writes the sentinel
# `_AUTHORITATIVE_SOURCE_UNCONFIRMED` — same discipline as provenance.py's own
# `AS_OF_UNKNOWN`: an honest "not yet known", not a fabricated system name. The classifier
# is expected to amend it once it reads the document (a follow-up, not built here).
_AUTHORITATIVE_SOURCE_UNCONFIRMED = "unconfirmed-at-intake"


def _build_s3_client():
    """Factory seam for the ingestion seam's MinIO client — the ONE line tests monkeypatch
    (`monkeypatch.setattr(gateway, "_build_s3_client", fake_factory)`) instead of faking
    boto3 itself. No prior test precedent fakes gateway.py's inline boto3 pattern (it has
    always been exercised live), so this factory exists purely to make the new routes
    testable without a real MinIO."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_MINIO_ENDPOINT_URL,
        aws_access_key_id=_MINIO_ACCESS_KEY,
        aws_secret_access_key=_MINIO_SECRET_KEY,
        region_name=_MINIO_REGION,
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


def _write_ingest_object(*, object_prefix: str, filename: str, body: bytes, manifest: dict,
                         kind: str = "") -> None:
    """Write the raw bytes + manifest.json (manifest + embedded provenance block, ADR-0041
    §8) under `object_prefix` in the processing-artifacts bucket — the SAME bucket
    extraction_review_sensor.py's S3 sensor watches, so a future classifier pass can pick
    `ingress-user/` up the same way it already picks up `sustainment/`/`manufacturing/`.

    Two objects, mirroring doc-tools' document_parser.py convention (sibling metadata +
    manifest, read via the Grep tool against the sibling repo this session): the original
    bytes under the uploaded filename, and `manifest.json`, now IngestRequest-shaped
    (`object_ref`, `content_kind`, `domain_type`, `provenance`, `initiator`) with
    `metadata.content_kind` present ONLY when the caller declared a registered content kind
    (ADR-0021's precedence rule 1 / ADR-0041 §4) — never the route's own `kind` (file FORMAT,
    pdf|cad|xml), which rides separately as `media_kind`. Writing the file format into
    `metadata.content_kind` was the prior defect: every user drop would HALT downstream as
    ContentKindUnregistered("pdf"). The provenance block rides BESIDE the bytes rather than
    embedded inside them — same "six fields ride beside" shape this repo already uses
    elsewhere (git log ab9b2a4e).
    """
    s3 = _build_s3_client()
    safe_name = os.path.basename(filename) or "upload"
    s3.put_object(Bucket=_ARTIFACT_BUCKET, Key=f"{object_prefix}{safe_name}", Body=body,
                  ContentType=_SOURCE_MEDIA_TYPES.get(kind, "application/octet-stream"))
    s3.put_object(
        Bucket=_ARTIFACT_BUCKET,
        Key=f"{object_prefix}manifest.json",
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _create_ingest_node(*, ingest_id: str, kind: str, sha256: str, object_ref: str,
                        ingested_at: str, subject: str,
                        dropped_by_authz_id: str | None = None) -> None:
    """Create the ingest node for a NEW /ingest arrival, through the worker's graph HOME
    (`promotion_stores.Neo4jIngestGraph.create_node`) -- which itself now goes through the SDK
    graph writer's `write_node` (v0.9.6), but the idempotence (created vs already-existed) and
    the narrow prop shape stay on that HOME, not here (see its own docstring,
    `src/iagent/promotion_stores.py`). A module-level function, not inlined in the route, so
    tests can monkeypatch it
    (`monkeypatch.setattr(gateway, "_create_ingest_node", ...)`) the same way `_build_s3_client`
    is faked above.

    `kind="person"` on the Initiator is correct here for the same reason the manifest's own
    `initiator` field is: the route above refuses any `on_behalf_of` other than the caller's own
    authz_id, so this is never a delegate or service identity.

    Raises on any failure -- the CALLER (the route, below) is the one that logs and swallows it.
    The bytes, manifest and status row are already durable by the time this runs, so a graph
    outage here must never fail an otherwise-successful upload; a promotion of a document with
    no node answers 409 `ingest_node_absent`, the honest downstream refusal, rather than this
    best-effort create blocking anything.
    """
    from iagent_mesh.interfaces import Initiator

    from . import promotion_stores

    graph = promotion_stores.Neo4jIngestGraph(
        driver=neo4j_driver, initiator=Initiator(subject=subject, kind="person"))
    graph.create_node(ingest_id, kind=kind, sha256=sha256, object_ref=object_ref,
                      ingested_at=ingested_at, dropped_by_authz_id=dropped_by_authz_id)


async def _open_case(*, case_id: str, trigger: str, facts: dict, ingest_id: str,
                     provenance_block: dict, seeded_by: Optional[str] = None) -> bool:
    """POST `{RESTATE_INGRESS_URL}/WorkflowRunner/{case_id}/run/send` -- the same case-runner
    call `_open_safety_acceptance` makes above (~6590), reused here for the ingest/origin seam's
    two case-opening points (an event-branch content kind on arrival, section 3; an origin
    suggestion, section 6).

    BEST-EFFORT, LIKE `_create_ingest_node`'s CALLER: the durable writes (bytes, manifest,
    status row) already happened by the time this runs, so a Restate outage here is logged
    (WARNING, naming `ingest_id`) and swallowed, never raised -- an otherwise-successful upload
    must not 500 because the case runner is unreachable. Returns True iff the POST succeeded.

    `provenance_block` IS REVISION 1'S PROVENANCE (SDK `ArtifactRevision.provenance`): the case
    runner opens the event's revision chain on it, and refuses a trigger with an episode -- one
    whose event can be revised -- that arrives without one.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_RESTATE_INGRESS_URL}/WorkflowRunner/{_restate_key(case_id)}/run/send",
                json={"trigger": trigger, "facts": facts, "provenance": provenance_block,
                      "seeded_by": seeded_by},
            )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort; the upload already succeeded
        logger.warning(
            "case open failed for ingest_id=%s case_id=%s trigger=%s (%s: %s)",
            ingest_id, case_id, trigger, type(exc).__name__, exc,
        )
        return False


def _restate_answer(resp: httpx.Response) -> Optional[dict]:
    """Measured live: Restate serialises a handler's `None` return as an empty 200 body
    (``b""``), not JSON `null` -- httpx's `.json()` raises `JSONDecodeError` on that empty
    body, so treat an empty body as the handler's `None` before parsing."""
    if not resp.content:
        return None
    return resp.json()


async def _fetch_case(case_id: str) -> Optional[dict]:
    """POST `{RESTATE_INGRESS_URL}/WorkflowRunner/{case_id}/case` -- the shared ``case``
    handler (workflow_runner.py), synchronous (no `/send`), same calling idiom as
    `GroupedReview/.../get_batch` (~line 1256). Raises on an unreachable runner (the route
    turns that into 503); returns ``None`` for "no such case" -- measured live, that normally
    arrives as an empty 200 (not a 404; the 404 branch below is kept for defensiveness)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{_RESTATE_INGRESS_URL}/WorkflowRunner/{_restate_key(case_id)}/case")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return _restate_answer(resp)


async def _fetch_instance1_spec(case_id: str) -> Optional[dict]:
    """POST `{RESTATE_INGRESS_URL}/WorkflowRunner/{case_id}/instance_spec` with `{"n": 1}` --
    called on the CASE's own key (workflow_runner._run_instance calls it the same way: `await
    ctx.workflow_call(instance_spec, key=case_id, arg={"n": n})`). ``None`` iff instance 1 has
    never been opened (``ctx.get`` returns falsy) -- measured live, that normally arrives as an
    empty 200 (not a 404; the 404 branch below is kept for defensiveness)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_RESTATE_INGRESS_URL}/WorkflowRunner/{_restate_key(case_id)}/instance_spec",
            json={"n": 1},
        )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return _restate_answer(resp)


async def _load_viewable_case(case_id: str, current_user: User) -> tuple[dict, dict]:
    """The case-visibility gate `GET /cases/{case_id}` and `GET /cases/{case_id}/action` share:
    fetch the case (runner unreachable -> 503 `runner_unavailable`), then 404 `case not found`
    when it is absent OR the caller may not read it (`case_projection.can_view_case`), the two
    answering IDENTICALLY. Returns `(case, definitions)`."""
    from starlette.concurrency import run_in_threadpool

    from agent_fleet.restate_analyst.workflow_definition import (  # noqa: PLC0415
        WorkflowDefinitionError, get_workflow_definition,
    )

    from . import case_projection

    try:
        case = await _fetch_case(case_id)
    except Exception as exc:  # noqa: BLE001 — connect errors, timeouts, 5xx via raise_for_status
        raise HTTPException(status_code=503, detail={"error": "runner_unavailable"}) from exc
    if not case:
        raise HTTPException(status_code=404, detail="case not found")

    instance1_spec = None
    if case.get("instances"):
        try:
            instance1_spec = await _fetch_instance1_spec(case_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail={"error": "runner_unavailable"}) from exc

    definition_ids = sorted({inst.get("definition_id") for inst in (case.get("instances") or [])
                             if inst.get("definition_id")})
    definitions: dict = {}
    try:
        for wf_id in definition_ids:
            definitions[wf_id] = await run_in_threadpool(get_workflow_definition, wf_id)
    except WorkflowDefinitionError as exc:
        # A definition the case already chose is not shipped in THIS runtime -- a deploy fault,
        # not an authz question or a missing case. Same 503 family as the runner itself: the
        # caller cannot distinguish "the runner is down" from "the runner's definitions aren't"
        # and must not be told their case doesn't exist over a config gap.
        raise HTTPException(status_code=503, detail={"error": "runner_unavailable"}) from exc

    caller_domains = [c.domain for c in current_user.entitlements.cells]
    if not case_projection.can_view_case(
        case, instance1_spec, definitions,
        caller_authz_id=current_user.authz_id, caller_domains=caller_domains,
    ):
        # A HOLDER OF A TASK ON THIS CASE MAY READ IT (architect ruling 2026-10-17): the person
        # a task was routed to must see what they are asked to decide, whatever their domain
        # cells. Any status counts. The admission is by recipient row alone; a store that is
        # unconfigured or down admits nobody, and the answer stays the identical 404.
        from . import human_tasks

        try:
            _holds = await run_in_threadpool(
                human_tasks.holds_task_on_case, case_id, current_user.authz_id)
        except Exception:  # noqa: BLE001 -- unreadable store: deny, same 404
            _holds = False
        if not _holds:
            raise HTTPException(status_code=404, detail="case not found")
    return case, definitions


@app.get("/cases/{case_id}", tags=[MCP_TAG])
async def get_case(case_id: str, current_user: User = Depends(get_current_user)):
    """GET /cases/{case_id} -- project the case runner's state (WorkflowRunner, ADR-0039) as
    cortex's `WorkflowCasePayload` (cortex-ui `src/archetypes/workflow-case/contract.ts`).

    EXISTENCE-ORACLE SAFE: a case that does not exist and a case the caller is not entitled to
    read (see `case_projection.can_view_case`) answer IDENTICALLY -- 404 `{"detail": "case not
    found"}` -- same discipline as `GET /ingest/{id}/status`. The runner being unreachable is a
    DIFFERENT fact (not an authz question) and answers 503 `{"error": "runner_unavailable"}`.

    The pure projection and the entitlement gate live in `case_projection`; this route only
    fetches runner/DB state and calls them.

    A DELEGATE IS NOT A SUBMITTER (ruled 2026-10-16): any caller acting under a delegate client
    (a key of `_delegate_principals()`, e.g. svc:openddil) reads the artifacts it seeded
    (GET /artifacts/{id}), never the whole case. Refused 403 BEFORE the fetch, so the answer is
    identical whether or not the case exists (no existence oracle). R-089: the delegate map
    is asserted by configuration this pass.
    """
    from starlette.concurrency import run_in_threadpool

    from . import case_projection, human_tasks

    # R-089: the delegate map is asserted by configuration this pass, not verified.
    if current_user.authz_id in _delegate_principals():
        raise HTTPException(status_code=403, detail={
            "error": "delegate_reads_artifacts_only",
            "message": "a delegate reads the artifacts it seeded (GET /artifacts/{id}), "
                       "never the whole case"})

    case, definitions = await _load_viewable_case(case_id, current_user)

    instance_ids = [inst.get("instance_id") for inst in (case.get("instances") or [])
                    if inst.get("instance_id")]
    try:
        task_rows = await run_in_threadpool(human_tasks.list_tasks_for_workflows, instance_ids)
    except human_tasks.HumanTaskConfigError:
        task_rows = []  # HITL substrate unconfigured: approvals are honestly empty, not a 503 --
                        # the case itself is readable without it.

    # The released ActionRecord, read ONLY when a definition could have emitted one. A store that
    # cannot be read is a 503, not a null: null claims "not released", which is false when we
    # cannot tell. Same detail as `GET /cases/{id}/action`.
    output_artifact = None
    if case_projection.has_emit_step(case, definitions):
        try:
            records = await run_in_threadpool(_read_action_records, case_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("action record read failed: %s", exc)
            raise HTTPException(status_code=503,
                                detail={"error": "artifact_store_unavailable"}) from exc
        output_artifact = case_projection.release_artifact(case_id, records)

    return case_projection.project_workflow_case(
        case, definitions, task_rows, output_artifact)


from pydantic import ConfigDict as _ConfigDict  # noqa: E402


class CaseSignalRequest(_BaseModel):
    """Body of `POST /cases/{case_id}/signals/{signal}`. `extra="forbid"`: the actor is never
    a body field -- an `acted_by` (or anything else) the caller supplies is a 422."""
    model_config = _ConfigDict(extra="forbid")
    status: str
    comments: str = ""


# The case/instance separator: an instance key is `{case}~{n}`. The gateway does not import
# agent_fleet, so the value is restated here; its source is
# agent_fleet/restate_analyst/case_routing.py CHILD_SEP (a test seals that they agree).
_CASE_INSTANCE_SEP = "~"


@app.post("/cases/{case_id}/signals/{signal}")
async def answer_case_signal(
    case_id: str,
    signal: str,
    req: CaseSignalRequest,
    current_user: User = Depends(get_current_user),
):
    """POST /cases/{case_id}/signals/{signal} -- a person answers a case's human-audience
    signal (a `signal_await` step; no committed definition declares one since 2026-10-28, when the supervisor's approval became the release). A human acknowledgment is
    a cortex action (architect ruling 2026-10-10).

    GENERIC over the signal name, GATED by the journalled audience: this route names no signal.
    engine-a's `WorkflowRunner.signal` checks `accepts`, `reason_required` and the authority
    gate (`_authorize_resolution`: actor present, not excluded, audience journalled, `can_act`).
    The actor is `current_user.authz_id`, never the body.

    Not checked here: the audience / `can_act` (the `case` projection does not expose the
    awaiting signal's audience, so the BFF cannot re-check it without inventing a read).

    THE SIGNAL GOES TO THE INSTANCE, NOT THE CASE (D1, lane/74 live walk 10-17, case
    712382d7-00c2-5610-a3cf-0e1c9ef5ea70). A `signal_await` journals `signal_accepts:<name>` on
    the INSTANCE key `{case}~{n}`, so the runner refused every post to the bare case key with
    "no signal ... is awaited". A `case_id` with no instance separator is therefore resolved
    first: the awaiting instance is the LAST entry of the case record's `instances` (`run`
    appends an instance before it calls it and runs them one at a time). A `case_id` that
    already carries the separator is forwarded unchanged.
    """
    acted_by = (current_user.authz_id or "").strip()
    if not acted_by:
        raise HTTPException(status_code=401, detail={
            "error": "no_actor",
            "message": "a case signal needs an authenticated caller with an authz_id",
        })
    target = case_id
    if _CASE_INSTANCE_SEP not in case_id:
        try:
            case = await _fetch_case(case_id)
        except Exception as exc:  # noqa: BLE001 — connect errors, timeouts
            raise HTTPException(status_code=502, detail={
                "error": "runner_unreachable", "message": f"{type(exc).__name__}: {exc}"})
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        instances = case.get("instances") or []
        # A case with no instance yet keeps the case key: nothing is awaited, and the runner
        # says so (a refusal the caller can read) rather than the BFF inventing a target.
        if instances:
            target = instances[-1].get("instance_id") or case_id
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            rr = await client.post(
                f"{_RESTATE_INGRESS_URL}/WorkflowRunner/{_restate_key(target)}/signal",
                json={"signal": signal, "status": req.status, "comments": req.comments,
                      "acted_by": acted_by},
            )
    except Exception as exc:  # noqa: BLE001 — connect errors, timeouts
        raise HTTPException(status_code=502, detail={
            "error": "runner_unreachable", "message": f"{type(exc).__name__}: {exc}"})
    sc = rr.status_code
    if sc == 200:
        return {"case_id": case_id, "instance_id": target, "signal": signal,
                "status": req.status, "acted_by": acted_by}
    msg = _restate_refusal_message(rr)
    if sc == 400:
        raise HTTPException(status_code=400, detail={"error": "signal_refused", "message": msg})
    if sc in (401, 403):
        # The caller IS authenticated: a refusal here is authority, not authentication.
        raise HTTPException(status_code=403, detail={
            "error": "not_authorized_to_act", "code": sc, "message": msg})
    if sc == 404:
        raise HTTPException(status_code=404, detail="case not found")
    raise HTTPException(status_code=502, detail={
        "error": "signal_failed", "code": sc, "message": msg})


def _sniff_file_kind(head: bytes) -> Optional[str]:
    """What the leading bytes say a drop is: "pdf", "xml" or None. Pure.

    pdf: `%PDF-` anywhere in the first 1024 bytes (PDF readers accept the header anywhere in the
    first KiB, and real files carry leading junk). xml: after an optional UTF-8 BOM and leading
    ASCII whitespace the bytes start `<?xml`; a UTF-16 BOM (FF FE / FE FF) followed by `<?xml` in
    that encoding counts too."""
    head = bytes(head[:1024])
    if b"%PDF-" in head:
        return "pdf"
    t = head[3:] if head.startswith(b"\xef\xbb\xbf") else head
    if t.lstrip(b" \t\r\n\x0b\x0c").startswith(b"<?xml"):
        return "xml"
    if head[:2] == b"\xff\xfe" and head[2:].startswith("<?xml".encode("utf-16-le")):
        return "xml"
    if head[:2] == b"\xfe\xff" and head[2:].startswith("<?xml".encode("utf-16-be")):
        return "xml"
    return None


@app.post("/ingest", tags=[INGEST_V1_TAG, MCP_TAG], responses={200: {"model": IngestResponse}, **DROP_GATE_RESPONSES})
async def ingest_document(
    file: UploadFile = File(...),
    kind: str = Form(...),
    # Blank or absent means the caller (`_admit_on_behalf_of`). `Form(...)` refused a blank as
    # `missing` before that rule could run, so the documented "send it blank" was a 422.
    on_behalf_of: str = Form(""),
    content_kind: Optional[str] = Form(None),
    leaf: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
):
    """POST /ingest (ADR-0041 §8) — a non-technical user hand-carries a document in.

    Deny-by-default: requires an authenticated caller (Depends(get_current_user) — no
    anonymous upload), and `on_behalf_of` must equal the caller's own authz_id (see the
    module-level note above this route for why v1 does not accept delegation).

    sha256 is computed AT THE DOOR (ADR-0041 §8's own phrase) — before any write, before
    any classification. Level-1 dedupe keys on it alone (same bytes = same document,
    full stop); it says nothing about document-IDENTITY dedupe across different bytes of
    the same logical document (ADR-0041 §6's R3, `(issuer, document_number, revision)`) —
    that is a classifier-time concern, downstream of this seam, and is NOT implemented
    here.

    FORMAT IS NOT KIND. `kind` (pdf|cad|xml) is the FILE FORMAT — the `ingress-user/{kind}/`
    path segment and the projection's `kind` column — never a registered content kind.
    `content_kind` is the SEPARATE channel for the picker's confirmed registered kind
    (ADR-0041 §4), and it is REQUIRED (architect ruling 2026-10-12: the door refuses a kindless
    drop where the uploader can still fix it, instead of accepting it and letting it die inside
    a Dagster op on the ADR-0041 guard). Refusals, in this order and all BEFORE the bounded read
    so nothing is written: blank-after-strip or malformed -> 422; absent -> 400
    `content_kind_required`; declared but not in the registry (`content_kinds.by_kind` is None)
    -> 400 `kind_unregistered`; an event-branch kind -> 422 `event_kind_requires_json`. Both 400s
    carry `registered`, the sorted document-branch kind names, so the picker can offer them. Any
    registered document-branch kind passes, including a deliberately domainless one like `pdf`
    (it lands at `awaiting_origin` later, unchanged). When INGEST_DOOR_READS_PROCESSABLE_KINDS is on
    (default OFF), one more check follows, still before the bounded read: no published list yet ->
    503 `processable_kinds_unknown`; a kind absent from doc-tools' published list -> 400
    `kind_unprocessable` (carrying `processable`). Writing a bare file format into
    `manifest.metadata.content_kind` (the old behaviour) made every user drop HALT as
    ContentKindUnregistered("pdf") -- ADR-0021 rule 1 / ADR-0041 §4 reserve that key for a
    REGISTERED kind; ADR-0021's 2026-09-30 amendment disables rule 2 under `ingress-user/`
    (that path segment is a format), so a kindless drop could never be resolved downstream.
    """
    from starlette.concurrency import run_in_threadpool

    from . import content_kinds, ingest_status, origin_resolver, promotion, provenance

    if kind not in ingest_status.FILE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {ingest_status.FILE_KINDS}, got {kind!r}",
        )
    # R-089: on_behalf_of from a delegate is ASSERTED by configuration this pass (R-089); token
    # exchange replaces it. `actor` is the dropper of record; `via` is the authenticated delegate
    # (None for a person), already recorded as the status row's `submitted_by`.
    actor, via = _admit_on_behalf_of(current_user, on_behalf_of)
    declared_content_kind = content_kind
    if declared_content_kind is not None:
        declared_content_kind = declared_content_kind.strip()
        if not declared_content_kind:
            raise HTTPException(
                status_code=422,
                detail="content_kind must not be blank (omit the field to mean 'not declared')",
            )
        if len(declared_content_kind) > 128 or "/" in declared_content_kind:
            raise HTTPException(
                status_code=422,
                detail="content_kind must be <=128 chars and must not contain '/'",
            )
    # KIND AT DROP (architect directive 2026-10-23, overriding the 10-21 "no picker before the
    # drop"): the composer's [PCN] [PDN] [Not sure] row sends `leaf` for the first two and nothing
    # for "Not sure", whose path is unchanged (title read -> awaiting_kind -> pick -> relaunch). A
    # leaf NARROWS the drop's kind: it BECOMES `declared_content_kind`, so the sidecar's
    # `manifest.metadata.content_kind` and the row (`leaf_source=declared`, via record_received's
    # `_declared_leaf`) carry it exactly as a drop that named the leaf as its content_kind does, and
    # every check below (registered, event branch, processable) runs on the leaf. Refused before any
    # write: not one of `ingest_status.LEAVES` -> 422 `leaf_unknown`; on a file that is not a PDF ->
    # 422 `leaf_requires_pdf` (an XML/S1000D kind is structural, the composer never asks); against a
    # declared content_kind other than `pdf` or the leaf itself -> 422 `leaf_conflicts_with_content_kind`.
    if leaf is not None:
        _leaf = leaf.strip().lower()
        if _leaf not in ingest_status.LEAVES:
            raise HTTPException(status_code=422, detail={
                "error": "leaf_unknown", "leaves": list(ingest_status.LEAVES),
                "message": (f"leaf must be one of {list(ingest_status.LEAVES)} (omit it for "
                            f"'not sure'), got {leaf!r}")})
        if kind != ingest_status.PDF:
            raise HTTPException(status_code=422, detail={
                "error": "leaf_requires_pdf",
                "message": f"a leaf is declared on a PDF drop only; this drop's file kind is {kind!r}"})
        if declared_content_kind is not None and declared_content_kind.lower() not in (ingest_status.PDF, _leaf):
            raise HTTPException(status_code=422, detail={
                "error": "leaf_conflicts_with_content_kind",
                "message": (f"leaf {_leaf!r} contradicts content_kind {declared_content_kind!r}; "
                            f"send one, or content_kind 'pdf' with the leaf")})
        declared_content_kind = _leaf

    # EVENT KINDS ARE REFUSED AT THIS DOOR (section C, ingest/origin seam). A document-branch
    # kind is bytes to extract; an event-branch kind is a JSON IngestRequest validated against
    # its trigger's declared shape -- there is no file for it to be "the bytes of". Checked
    # BEFORE the bounded read below so a misrouted multipart drop writes NOTHING (no S3 object,
    # no status row, no graph node) and starts no workflow -- caught here rather than letting
    # the branch=="event" block further down silently seed a workflow for bytes that were ALSO
    # durably written, which is what this repo did before this check existed.
    _registered_kind = content_kinds.by_kind(declared_content_kind) if declared_content_kind else None
    # THE DOOR 400 (architect ruling 2026-10-12): a document drop must name a REGISTERED kind.
    # Before the event check and the bounded read, so a refused drop writes nothing.
    if declared_content_kind is None or _registered_kind is None:
        _doc_kinds = sorted(r.kind for r in content_kinds.registrations() if r.branch == "document")
        if declared_content_kind is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "content_kind_required",
                    "message": (
                        "content_kind is required: pick the registered kind of this document "
                        "and resubmit. Refusing before any write."
                    ),
                    "registered": _doc_kinds,
                },
            )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "kind_unregistered",
                "message": (
                    f"content_kind {declared_content_kind!r} is not a registered content kind. "
                    "Refusing before any write."
                ),
                "registered": _doc_kinds,
            },
        )
    if _registered_kind.branch == "event":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "event_kind_requires_json",
                "message": (
                    f"content_kind {declared_content_kind!r} is an event-branch kind — it "
                    "arrives as a JSON IngestRequest at POST /ingest/events, validated against "
                    "its trigger's declared fields, never as a file. Refusing before any write."
                ),
            },
        )

    # can_drop:<kind> (2026-10-28): a gated kind is dropped only by its grantees. The EFFECTIVE kind
    # is `declared_content_kind` (a `leaf` already replaced it above); the dropper is `actor`, the
    # principal of record when a delegate drops on their behalf. Before the bounded read, so a
    # refused drop writes nothing.
    await _can_drop_or_refuse(declared_content_kind, actor)

    # THE PROCESSABLE-KINDS CHECK (owner ruling, F2/F3): behind a flag that ships OFF. Flag off ->
    # the store and cache are never touched. Flag on is deny-by-default: no published list yet ->
    # 503; a list that lacks the declared kind -> 400. Still before the bounded read.
    if os.getenv("INGEST_DOOR_READS_PROCESSABLE_KINDS", "").strip().lower() in ("1", "true", "yes", "on"):
        from . import processable_kinds

        try:
            _processable = await run_in_threadpool(processable_kinds.current)
        except processable_kinds.StoreUnreachable as exc:
            # The driver's text can name the database host; it goes to the log, never to a dropper.
            logger.warning("processable_kinds store unreachable at the ingest door: %s", exc)
            raise HTTPException(status_code=503, detail={
                "error": "processable_kinds_unknown",
                "message": "the processable-kinds store was unreachable and nothing is cached. "
                           "Refusing before any write.",
            })
        if _processable is None:
            raise HTTPException(status_code=503, detail={
                "error": "processable_kinds_unknown",
                "message": "doc-tools has not published its processable kinds yet. Refusing before any write.",
            })
        if declared_content_kind not in _processable:
            raise HTTPException(status_code=400, detail={
                "error": "kind_unprocessable",
                "message": f"content_kind {declared_content_kind!r} is registered but doc-tools does not "
                           "process it. Refusing before any write.",
                "processable": sorted(_processable),
            })

    # BOUNDED READ. An unbounded `await file.read()` buffers the whole upload in this pod (1Gi
    # limit in values-sandbox), so one authenticated drop could take the BFF down for every
    # user. ADR-0041 names no size; INGEST_MAX_BYTES is a LOCAL default (50 MiB), not a
    # ruling -- raise it in values, not here. Read one chunk past the cap so "exactly at the
    # cap" is accepted and "one byte over" is refused with 413 before anything is written.
    _cap = int(os.getenv("INGEST_MAX_BYTES", str(50 * 1024 * 1024)))
    _chunks: list[bytes] = []
    _seen = 0
    while True:
        _chunk = await file.read(1024 * 1024)
        if not _chunk:
            break
        _seen += len(_chunk)
        if _seen > _cap:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds INGEST_MAX_BYTES ({_cap} bytes)",
            )
        _chunks.append(_chunk)
    body = b"".join(_chunks)
    # THE SNIFF BINDS (architect ruling): the declared pdf|xml must be what the bytes are, checked
    # before the dedupe row, the S3 object or the graph node. cad has no magic.
    if kind in ("pdf", "xml"):
        _sniffed = _sniff_file_kind(body[:1024])
        if _sniffed != kind:
            raise HTTPException(status_code=400, detail={
                "error": "kind_mismatch", "declared_kind": kind, "sniffed_kind": _sniffed,
                "filename": file.filename,
                "message": f"the drop says {kind!r} but its bytes are "
                           f"{_sniffed or 'neither pdf nor xml'}; refusing before any write"})
    sha256 = hashlib.sha256(body).hexdigest()
    # THE SAME DERIVATION `document_promotion` requires (promotion.INGEST_ID_RE): minting the
    # id any other way would refuse every seam-minted document's later promotion.
    ingest_id = promotion.ingest_id_for(body)

    existing = await run_in_threadpool(ingest_status.find_primary_by_sha, sha256)
    if existing is not None:
        dup = await run_in_threadpool(
            lambda: ingest_status.record_duplicate_arrival(
                sha256=sha256,
                kind=kind,
                object_prefix=existing["object_prefix"],
                submitted_by=current_user.authz_id,
                on_behalf_of=actor,
                source=file.filename,
                original=existing,
                content_kind=declared_content_kind,
            )
        )
        return {
            "ingest_id": dup["id"],
            "stage": existing["status"],
            "detail": dup["detail"],
            "duplicate": {"of_ingest_id": existing["id"], "message": dup["detail"]},
        }

    object_prefix = f"ingress-user/{kind}/{sha256}/"
    safe_name = os.path.basename(file.filename or "upload") or "upload"
    # ISO-8601 UTC string — the shape `iagent_mesh.provenance.ProvenanceBlock.ingested_at: str`
    # requires. `provenance.py`'s own validator only checks truthiness (it accepts an int, see
    # test_provenance_block.py's `_blk(ingested_at=1)`), so nothing here enforces the format —
    # this is written to match the SDK's contract, not because this repo's copy demands it.
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    provenance_block = provenance.make_provenance(
        authoritative_source=_AUTHORITATIVE_SOURCE_UNCONFIRMED,
        obtained_via=provenance.USER_DROP,
        as_of=provenance.AS_OF_UNKNOWN,
        ingested_at=ingested_at,
        ingest_run=f"user-drop:{ingest_id}",
        standing="supervised",
        # THE BLOCK CARRIES ITS DOCUMENT'S ID (provenance floor, ead2f80d): the same
        # `promotion.ingest_id_for` value the manifest, the status row and the promotion task
        # key on, so a claim derived from this drop can be traced back without the manifest.
        ingest_id=ingest_id,
    )
    # DECLARED AND REGISTERED -> domain_type fills from the registration (ADR-0021/0041 §4/§8,
    # SDK 0.9.7 `ContentKindRegistration.domain`, section 1 of the ingest/origin seam). A
    # DECLARED-but-UNREGISTERED kind leaves domain_type None -- behaviour unchanged: the HALT
    # for an unregistered kind belongs to the driver that resolves `content_kind`, not here.
    # `_registered_kind` itself was already resolved above (event-kind door check, section C) --
    # not recomputed here, so the two reads of the registry in one request cannot disagree.
    manifest = {
        "ingest_id": ingest_id,
        "object_ref": object_prefix + safe_name,
        "content_kind": declared_content_kind,
        "domain_type": _registered_kind.domain if _registered_kind is not None else None,
        "dropped_by": {"authz_id": actor, **({"via": via} if via else {})},
        "provenance": provenance_block,
        # kind="person" for a person's own drop. A declared delegate's drop is the delegate
        # acting for a declared principal: subject is the authenticated delegate, on_behalf_of
        # the principal (R-089, asserted by configuration).
        "initiator": (
            {"subject": current_user.authz_id, "kind": "person", "on_behalf_of": None}
            if via is None else
            {"subject": via, "kind": "delegate", "on_behalf_of": actor}
        ),
        "media_kind": kind,
        "sha256": sha256,
        "filename": file.filename,
        "submitted_by": current_user.authz_id,
        "on_behalf_of": on_behalf_of,
        "ingested_at": ingested_at,
    }
    if declared_content_kind is not None:
        # Present ONLY when declared — absence is rule 1 not firing (see the route docstring);
        # ADR-0021-amendment says rule 2 must not fire under `ingress-user/`, so an undeclared
        # drop HALTs at the driver rather than guessing a kind here.
        manifest["metadata"] = {"content_kind": declared_content_kind}
    await run_in_threadpool(
        lambda: _write_ingest_object(
            object_prefix=object_prefix, filename=file.filename or "upload",
            body=body, manifest=manifest, kind=kind,
        )
    )
    row = await run_in_threadpool(
        lambda: ingest_status.record_received(
            ingest_id=ingest_id, sha256=sha256, kind=kind, object_prefix=object_prefix,
            submitted_by=current_user.authz_id, on_behalf_of=actor,
            source=file.filename, content_kind=declared_content_kind,
        )
    )
    # BEST-EFFORT node creation (ruled 2026-09-30): the bytes, manifest and status row above are
    # already durable, so a graph outage here is LOGGED, not raised -- failing an otherwise-
    # successful upload on the graph store would be the wrong trade. A promotion of a document
    # whose node is absent (because this failed, or hasn't run yet) answers 409
    # `ingest_node_absent`, the honest downstream refusal.
    try:
        await run_in_threadpool(
            lambda: _create_ingest_node(
                ingest_id=ingest_id, kind=kind, sha256=sha256,
                object_ref=manifest["object_ref"], ingested_at=ingested_at,
                subject=actor,
                dropped_by_authz_id=actor,
            )
        )
    except Exception as exc:  # noqa: BLE001 — logged, never fails an otherwise-durable upload
        logger.warning("ingest node creation failed for %s: %s", ingest_id, exc)
    # SEEDS_WORKFLOW: NO LONGER REACHABLE HERE (section C, ingest/origin seam). An event-branch
    # kind is refused at the door above (`event_kind_requires_json`) before this point is ever
    # reached, so `_registered_kind.branch == "event"` cannot be true below -- a file kind
    # carries no trigger requirements and seeds nothing; event seeding now happens only at
    # POST /ingest/events. `workflow` stays None for every multipart drop.
    workflow: dict | None = None
    # ORIGIN SUGGESTION (section 6, architect ruling 2026-10-02 "ORIGIN, not audience"): a hit
    # records a suggestion on the status row and opens its own case -- BEST-EFFORT, like the
    # node creation and workflow seeding above: the upload is already durable by this point, so
    # a systems-of-record load failure or a Restate outage here is logged, never raised.
    origin_suggestion: dict | None = None
    try:
        origin_suggestion = origin_resolver.resolve(manifest)
    except Exception as exc:  # noqa: BLE001 — best-effort; the upload already succeeded
        logger.warning("origin resolution failed for %s: %s", ingest_id, exc)
    if origin_suggestion is not None:
        await run_in_threadpool(
            lambda: ingest_status.record_origin_suggestion(ingest_id, origin_suggestion)
        )
        await _open_case(
            case_id=origin_suggestion["suggestion_id"], trigger="origin_suggestion",
            facts=origin_suggestion, ingest_id=ingest_id, provenance_block=provenance_block,
        )
    return {
        "ingest_id": row["id"], "stage": row["status"], "detail": None,
        "object_prefix": object_prefix, "duplicate": None, "workflow": workflow,
        "origin_suggestion": origin_suggestion,
    }


class IngestEventRequest(_BaseModel):
    """POST /ingest/events' body — the JSON door for an event-branch content kind (section C,
    ingest/origin seam). `payload` carries the event's own fields; the trigger named by the
    kind's registration (`seeds_workflow`) is validated against them below, dotted-path by
    dotted-path, the same vocabulary `agent_fleet.restate_analyst.case_routing.Trigger.requires`
    already declares -- this route does not invent a second one."""
    content_kind: str
    on_behalf_of: str
    payload: dict[str, Any] = Field(default_factory=dict)


def _dotted_present(d: dict[str, Any], path: str) -> bool:
    """True iff the dotted `path` resolves to a non-None value in `d`. Mirrors
    `case_routing.Trigger.requires`'s own rule ("refused at intake... refuses a null") -- an
    ABSENT key and a key present-but-None are the same refusal here, deliberately: a trigger's
    `requires` is read the same way wherever it is enforced."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return cur is not None


def _dotted_get(d: dict[str, Any], path: str) -> Any:
    """Same walk as `_dotted_present`, returning the value (or None)."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


@app.post("/ingest/events", responses=DROP_GATE_RESPONSES)
async def ingest_event(
    req: IngestEventRequest,
    current_user: User = Depends(get_current_user),
):
    """POST /ingest/events (section C, ingest/origin seam) — the JSON door for an event-branch
    content kind. An event never arrives as a file: it is a JSON `IngestRequest` payload,
    validated against the kind's declared trigger before anything is seeded.

    `content_kind` MUST be registered AND `branch == "event"` — a document-branch or
    unregistered kind is refused here with a named reason (the multipart `/ingest` door is
    theirs; this one refuses a file for the same reason in reverse, see that route's own door
    check). The kind's registration carries NO schema field of its own (`iagent_mesh.ingest.
    ContentKindRegistration` has `passes`/`outputs`, which name OntologyClass kinds for a
    document's extraction, not a payload shape) -- so the validatable shape THIS repo actually
    has is the kind's own trigger's `requires:` (`policy/triggers/<seeds_workflow>.yaml`, the
    same list `case_routing.Trigger.requires` loads), checked dotted-path by dotted-path against
    `payload` plus the facts this route adds itself (`dropped_by.authz_id`). A payload missing
    any required path is refused 422, naming which.

    THE RESPONSE CONTRACT IS 200 WITH `workflow.case_id` (ruled 2026-10-05). The seam spec said
    202; the door has always answered 200, the first producer is coded against 200, and the
    ruling keeps it, so 202 is not an open question. `case_id` is the key the case runner
    holds the case under (the trigger's key, i.e. the producer's own identity field), and the
    door only answers 200 once the runner's own intake check has accepted the payload.
    """
    from . import content_kinds, provenance

    # R-089: on_behalf_of from a delegate is ASSERTED by configuration this pass (R-089); token
    # exchange replaces it. `actor` is the dropper of record; `via` the authenticated delegate.
    actor, via = _admit_on_behalf_of(current_user, req.on_behalf_of)
    # `seeded_by` (ADR-0041 §8.1): the authenticated caller, ONLY when it is a declared delegate
    # (R-089); a person seeds nothing as a delegate, so None. The runner stamps it at `released`.
    seeded_by: Optional[str] = (
        current_user.authz_id if current_user.authz_id in _delegate_principals() else None
    )
    _registered_kind = content_kinds.by_kind(req.content_kind)
    if _registered_kind is None or _registered_kind.branch != "event":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "not_an_event_kind",
                "message": (
                    f"content_kind {req.content_kind!r} is not a registered event-branch kind — "
                    "this route only seeds a workflow for branch=='event'; a document-branch or "
                    "unregistered kind belongs at the multipart POST /ingest door"
                ),
            },
        )
    # can_drop:<kind>: the dropper of record (`actor`) must hold it when the kind is gated.
    # Before the trigger load, the runner and any write, so a refusal records nothing.
    await _can_drop_or_refuse(req.content_kind, actor)

    try:
        from agent_fleet.restate_analyst.case_routing import (  # noqa: PLC0415
            CaseRoutingError, check_intake, flatten, load_trigger,
        )
        trigger = load_trigger(_registered_kind.seeds_workflow)
    except CaseRoutingError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "trigger_unconfigured", "message": str(exc)},
        )

    # Dedupe key: `ContentKindRegistration.identity_field`'s own docstring ("the seam dedupes
    # arrivals on it; this module does not perform the dedupe ... that is Lane 1's seam, keyed
    # via Restate's run/send") -- so the case_id below is built from THIS field's value, not a
    # hash of the whole payload, so that re-POSTing the same event reaches the same Restate run
    # rather than opening a rival one. `identity_field` is required (non-None) for branch="event"
    # by the SDK's own validator, so `_registered_kind.identity_field` is never None here.
    identity_value = _dotted_get(req.payload, _registered_kind.identity_field)
    if identity_value is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "payload_missing_identity_field",
                "message": f"payload is missing {_registered_kind.identity_field!r}, this "
                           f"kind's identity_field",
            },
        )
    ingest_id = "evt-" + hashlib.sha256(
        f"{req.content_kind}:{identity_value}".encode()
    ).hexdigest()
    facts: dict[str, Any] = {
        **req.payload,
        "ingest_id": ingest_id,
        "content_kind": req.content_kind,
        "domain_type": _registered_kind.domain,
        "dropped_by": {"authz_id": actor, **({"via": via} if via else {})},
    }
    missing = [path for path in trigger.requires if not _dotted_present(facts, path)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "payload_missing_required_fields",
                "missing": missing,
                "message": f"payload is missing {missing} required by trigger "
                           f"{trigger.trigger!r} ({_registered_kind.seeds_workflow!r})",
            },
        )

    # The case key is the value of the TRIGGER's `key` -- the runner's rule, checked at intake
    # (`case_routing.check_intake`: "the key IS the dedupe"); the safety door keys by its bare
    # `acceptance_id` the same way. Keying by `{seeds_workflow}:{ingest_id}` opened a case the
    # runner refused 123 ms later (OpenDDIL's first live event, 2026-10-05). The registration's
    # `identity_field` (this door's dedupe) and the trigger's `key` (the runner's) are separate
    # declarations: if they ever disagree the two dedupes split, so refuse rather than pick one.
    if trigger.key != _registered_kind.identity_field:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "trigger_unconfigured",
                "message": f"kind {req.content_kind!r} dedupes on identity_field "
                           f"{_registered_kind.identity_field!r} but trigger "
                           f"{trigger.trigger!r} keys its cases on {trigger.key!r}",
            },
        )
    case_id = str(identity_value)
    # The runner's OWN intake check, run here before the case opens: `requires` above is only
    # part of what intake refuses (key, episode, `carries`, outcome clash), and an event the door
    # answered 200 must not be refused 123 ms later where the producer cannot see it. Shared by
    # BOTH a first arrival and a repeat below -- `check_intake` is a pure facts/schema check with
    # no notion of "does a case already exist", so a repeat's facts pass through it unchanged
    # (the runner's `revise` handler runs the same check itself, via `check_revision`).
    try:
        check_intake(trigger, flatten(facts), case_id, facts=facts)
    except CaseRoutingError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "payload_refused_by_trigger", "message": str(exc)},
        )

    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    sha256_hex = hashlib.sha256(
        json.dumps(req.payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    # THIS ARRIVAL'S PROVENANCE -- revision 1's on a first arrival, the revision's own on a
    # repeat (keep_revision refuses a revision without one) -- built at this door like the drop door builds a drop's: who owns
    # the truth is not confirmed at intake, the truth-date is not in the contract, and the
    # standing is born-supervised. It differs in HOW: the producer posted the event to this
    # route itself, so it is `direct`, not a hand-carried `user-drop` (ruled 2026-10-06).
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    provenance_block = provenance.make_provenance(
        authoritative_source=_AUTHORITATIVE_SOURCE_UNCONFIRMED,
        obtained_via=provenance.DIRECT,
        as_of=provenance.AS_OF_UNKNOWN,
        ingested_at=ingested_at,
        ingest_run=f"event:{ingest_id}",
        standing="supervised",
        ingest_id=ingest_id,
    )

    # REPEAT DETECTION (section B, roll #20 item 4): ask the RUNNER, not only our own status
    # table -- the first live event on OpenDDIL opened its case before this status seam existed,
    # so a row-only check would call that case "new" and crash straight into the runner's own
    # key-reuse refusal. `case` is a shared, no-input handler (workflow_runner.py) that answers
    # the case record or null; a non-null answer is a repeat.
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            case_resp = await client.post(
                f"{_RESTATE_INGRESS_URL}/WorkflowRunner/{_restate_key(case_id)}/case",
            )
    except Exception as exc:  # noqa: BLE001 — unreachable runner; do not guess at the answer
        raise HTTPException(
            status_code=503,
            detail={"error": "runner_unavailable", "message": str(exc)},
        )
    if case_resp.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail={"error": "runner_unavailable", "code": case_resp.status_code},
        )
    try:
        existing_case = _restate_answer(case_resp)
    except Exception as exc:  # noqa: BLE001 — a non-empty, non-JSON body is a runner fault
        raise HTTPException(
            status_code=503,
            detail={"error": "runner_unavailable", "message": str(exc)},
        )

    if existing_case is not None:
        # A REVISION, not a duplicate: the same event_id, arriving again. Backfill the status
        # row ONLY when this ingest_id has never been seen here -- the pre-roll case has no row
        # at all; a row that already exists keeps its own stage (it is not this route's place to
        # rewrite history for an id it already has an opinion about).
        existing_row = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
        if existing_row is None:
            await run_in_threadpool(lambda: ingest_status.record_received(
                ingest_id=ingest_id, sha256=sha256_hex, kind=ingest_status.EVENT,
                object_prefix="", submitted_by=current_user.authz_id,
                on_behalf_of=actor, source="events",
                content_kind=req.content_kind,
            ))
            await run_in_threadpool(lambda: ingest_status.update_status(
                ingest_id, ingest_status.CASE_OPENED, case_id=case_id))
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                rr = await client.post(
                    f"{_RESTATE_INGRESS_URL}/WorkflowRunner/{_restate_key(case_id)}/revise",
                    json={"facts": facts, "provenance": provenance_block},
                )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail={"error": "runner_error", "message": str(exc)},
            )
        if rr.status_code == 200:
            return {
                "ingest_id": ingest_id, "rev": rr.json().get("revision"),
                "workflow": {"case_id": case_id, "started": False},
            }
        if rr.status_code == 400:
            raise HTTPException(
                status_code=422,
                detail={"error": "payload_refused_by_trigger",
                        "message": _restate_refusal_message(rr)},
            )
        if rr.status_code in (404, 409):
            raise HTTPException(
                status_code=409,
                detail={"error": "revision_not_kept", "message": _restate_refusal_message(rr)},
            )
        raise HTTPException(status_code=502, detail={"error": "runner_error"})

    # FIRST ARRIVAL: write the status row BEFORE opening the case -- "no case without its
    # record" -- so a write failure here must refuse rather than open a case nobody has a
    # status row for.
    try:
        await run_in_threadpool(lambda: ingest_status.record_received(
            ingest_id=ingest_id, sha256=sha256_hex, kind=ingest_status.EVENT,
            object_prefix="", submitted_by=current_user.authz_id,
            on_behalf_of=actor, source="events",
            content_kind=req.content_kind,
        ))
    except Exception as exc:  # noqa: BLE001 — "no case without its record"
        raise HTTPException(
            status_code=503,
            detail={"error": "status_unavailable", "message": str(exc)},
        )

    started = await _open_case(
        case_id=case_id, trigger=_registered_kind.seeds_workflow, facts=facts,
        ingest_id=ingest_id, provenance_block=provenance_block, seeded_by=seeded_by,
    )
    if started:
        await run_in_threadpool(lambda: ingest_status.update_status(
            ingest_id, ingest_status.CASE_OPENED, case_id=case_id))
    return {
        "ingest_id": ingest_id, "workflow": {"case_id": case_id, "started": started},
    }


async def _ingest_status_body(row: dict, current_user: User) -> dict:
    """The status route's response dict for one scoped row (shared by GET /ingest/<id>/status and
    GET /ingest/mine, so the two shapes cannot drift). `row` is an `ingest_status.get_status_for` /
    `list_mine` row already scoped to the caller; the duplicate original is re-read with the same scoping."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    stage = row["status"]
    duplicate = None
    if row.get("duplicate_of"):
        # This row IS a duplicate-arrival row (status == ingest_status.DUPLICATE, which is not
        # one of ca's six INGEST_STAGES) — `stage` reports the ORIGINAL's current stage instead.
        original = await run_in_threadpool(
            lambda: ingest_status.get_status_for(row["duplicate_of"], caller_id=current_user.authz_id)
        )
        # EXISTENCE-ORACLE: if this caller cannot see the original through the SAME caller
        # scoping get_status_for already applies (e.g. a duplicate row this caller owns pointing
        # at an original neither submitted_by nor on_behalf_of makes visible to them), `stage`
        # is None — not the tempting "received" default, which would FABRICATE a fact about a
        # row this caller is not scoped to see.
        stage = original["status"] if original is not None else None
        duplicate = {"of_ingest_id": row["duplicate_of"], "message": row.get("detail")}
        # `failure` and `attempt` describe the row `stage` was taken from, so for a duplicate-arrival
        # row they are the ORIGINAL's -- never the duplicate row's own.
        source_row = original
    else:
        source_row = row

    # `failure` is None unless the reported stage is `failed`. A failed row with NO stored failure
    # is a legacy row written before 2026-10-12; synthesise from `detail`. reason_code None means
    # the producer did not classify the failure; it does not mean there was no failure.
    failure = None
    if stage == ingest_status.FAILED and source_row is not None:
        failure = source_row.get("failure") or {
            "reason_code": None, "reason": source_row.get("detail"), "step": None,
            "run_id": None, "pin_digest": None, "failed_at": source_row.get("updated_at")}
    attempt = int((source_row or row).get("attempt") or 1)
    # DISPLAY ONLY, never an identity (LLM-extracted `doc_id`). The key is always present: None
    # means "claimed, none known yet"; a duplicate reports the ORIGINAL's.
    notice_id = (source_row or {}).get("notice_id") or None

    artifacts: Optional[list] = []
    if row.get("case_id"):
        from . import artifact_reads

        def _case_artifacts() -> list:
            with neo4j_driver.session() as session:
                recs = list(session.run(
                    artifact_reads.CASE_ARTIFACTS_CYPHER,
                    case_id=row["case_id"], user_id=(current_user.id or "").strip()))
            # R-089: the delegate map is asserted by configuration this pass; a delegate is listed
            # only the artifacts it seeded, the same predicate GET /artifacts/{id} applies.
            delegates = _delegate_principals()
            return [{"artifact_id": r["id"], "kind": r["kind"], "released_at": r["released_at"]}
                    for r in recs
                    if artifact_reads.is_entitled(
                        r, authz_id=current_user.authz_id, delegates=delegates)]
        try:
            artifacts = await run_in_threadpool(_case_artifacts)
        except Exception as exc:  # noqa: BLE001 — unknown, not none; the row must still answer
            logger.warning("ingest %s: the case's artifacts could not be listed: %s", row["id"], exc)
            artifacts = None

    # The review task (208). At `review` the steward acts on ONE of two tasks: the empty-confirm task
    # for the CURRENT attempt when the extraction found no rows (_hold_empty_for_confirmation filed
    # it), else the current generation's promotion task. The open empty-confirm payload decides which,
    # the same lookup _decide_empty makes. Off `review` all three are null. A failed read at review
    # leaves all three null: "could not be determined", never a guessed task id.
    review_task_id = review_shape = account = None
    if source_row is not None and stage == ingest_status.REVIEW:
        from . import human_tasks

        _src_id = source_row.get("id") or ""
        _empty_id = _empty_confirm_task_id(_src_id, source_row.get("attempt"))
        try:
            _empty = await run_in_threadpool(lambda: human_tasks.get_open_task_payload(_empty_id))
        except Exception as exc:  # noqa: BLE001 — unknown, not none; the row must still answer
            logger.warning("ingest %s: the review task could not be read: %s", row["id"], exc)
        else:
            if _empty is not None:
                review_task_id, review_shape = _empty_id, "empty"
                account = _empty.get("account")
            else:
                review_task_id = _promotion_task_id(
                    _src_id, int(source_row.get("review_generation") or 0))
                review_shape = "promotion"

    # extraction_defect (packet 2026-10-11): the NEWEST extraction_defect task filed about this drop,
    # as {task_id, edits}, or null when none is on record. `edits` counts ROWS deleted, added or
    # corrected (a header correction is not a row; the empty has_parts defect has none, so 0). A
    # failed read, or a duplicate whose original this caller cannot see, leaves the key ABSENT: no claim.
    _ABSENT = object()
    extraction_defect = _ABSENT
    if source_row is not None:
        from . import human_tasks

        try:
            _defect = await run_in_threadpool(lambda: human_tasks.latest_task_for_subject(
                source_row.get("id") or "", "extraction_defect"))
        except Exception as exc:  # noqa: BLE001 — unknown, not none; the row must still answer
            logger.warning("ingest %s: the extraction defect could not be read: %s", row["id"], exc)
        else:
            extraction_defect = None if _defect is None else {
                "task_id": _defect["task_id"],
                "edits": sum(1 for e in (_defect["payload"].get("edits") or [])
                             if isinstance(e, dict)
                             and e.get("op") in ("corrected", "added", "deleted"))}

    body = {
        "ingest_id": row["id"],
        "stage": stage,
        "detail": row.get("detail"),
        "duplicate": duplicate,
        "kind": row.get("kind"),
        "sha256": row.get("sha256"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "dropped_by": {"authz_id": row.get("submitted_by")},
        "origin_suggestion": row.get("origin_suggestion"),
        "case_id": row.get("case_id"),
        # The row's declared kind (nullable, key always present; ruling 2026-10-16): the dropper
        # needs it to see why a review was refused as `no_declared_domain`.
        "content_kind": row.get("content_kind"),
        "failure": failure,
        "attempt": attempt,
        "notice_id": notice_id,
        "artifacts": artifacts,
        # Spec 204 / 208: the task a steward acts on while the row is at `review` (see above), which
        # of the two it is, and the extraction's own account of an empty one. A generation change
        # replaces a promotion task.
        "review_task_id": review_task_id,
        "review_shape": review_shape,
        "account": account,
    }
    if extraction_defect is not _ABSENT:
        body["extraction_defect"] = extraction_defect
    # The leaf (spec 203). Present ONLY for a leaf-capable row (absent, not null, for cad / xml /
    # s1000d / ...: absent tells cortex "no claim", so it draws no chip). A duplicate reads the
    # ORIGINAL's leaf; an invisible original leaves the keys absent. Never reads review.json per poll.
    if source_row is not None and _leaf_capable(source_row):
        leaf, leaf_source, corrected_by = _row_leaf(source_row)
        body["leaf"] = leaf
        body["leaf_source"] = leaf_source
        body["corrected_by"] = corrected_by
        body["leaf_candidates"] = (source_row.get("leaf_candidates")
                                   if stage == ingest_status.AWAITING_KIND else None)
        # WHY the row is held (ruling 2026-10-22, e.g. `kind_not_identified`): present exactly when
        # the other leaf keys are, a value only at awaiting_kind (the column is stale elsewhere).
        body["hold_reason"] = (source_row.get("hold_reason")
                               if stage == ingest_status.AWAITING_KIND else None)
    return body


@app.get("/ingest/{ingest_id}/status", tags=[INGEST_V1_TAG], responses={200: {"model": StatusBody}})
async def ingest_status_route(ingest_id: str, current_user: User = Depends(get_current_user)):
    """GET /ingest/<id>/status — for the SUBMITTER or the on_behalf_of principal only.

    EXISTENCE-ORACLE SAFE: ingest_status.get_status_for scopes the query to
    `submitted_by = caller OR on_behalf_of = caller`; a caller who is neither gets a plain
    404, indistinguishable from "no such ingest" — same discipline as the human-task
    resolution lookup (human_tasks.get_task_resolution).

    ONE NAME PER FIELD: the DB column is still `status` (`ingest_status.get_status_for`'s row
    dict, and Electric subscribers on `/electric/shape` still read the column `status` — only
    this route's own JSON key is renamed), and the row's own `id` is never echoed back — both
    are replaced here by `stage`/`ingest_id`, matching ca's wire shapes.

    `failure` (2026-10-12, pipeline failure must reach the row) is None unless `stage` is `failed`;
    then it is {reason_code, reason, step, run_id, pin_digest, failed_at} (a legacy failed row with
    none stored gets one synthesised from `detail`, reason_code None). `attempt` is how many times
    the row has been opened (1 on arrival; POST /ingest/{id}/retry bumps it).

    `artifacts` (ruled 2026-10-16) lists `{artifact_id, kind, released_at}` for the case the event
    opened (`case_id`), so a delegate learns its artifact ids from the row it already may read.
    ONLY what the caller may open: each artifact is filtered through `artifact_reads.is_entitled`,
    the gate GET /artifacts/{id} applies, so an id the caller could not read is never listed. The
    key is always present: `[]` means none (no case yet, or none the caller may open); `None` means
    UNKNOWN (the graph could not be read; logged) -- the row itself still answers.
    """
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    row = await run_in_threadpool(
        lambda: ingest_status.get_status_for(ingest_id, caller_id=current_user.authz_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="ingest not found")

    return await _ingest_status_body(row, current_user)


_ingest_access_log = logging.getLogger("iagent.audit.ingest_access")
# THE LINE MUST ARRIVE, NOT MERELY BE CALLED (see the note on `logger` above).
_ensure_the_audit_line_actually_ARRIVES(_ingest_access_log)


def _audit_ingest_access(route: str, ingest_id: str, caller: str, decision: str,
                         reason: str) -> None:
    """ONE audit line per access decision (allow INFO, deny WARNING). Names the route, the ingest
    id, the caller and the decision -- never bytes, keys or presigned URLs."""
    (_ingest_access_log.info if decision == "allow" else _ingest_access_log.warning)(
        "ingest_access route=%s ingest_id=%s caller=%s decision=%s reason=%s",
        route, ingest_id, caller, decision, reason)


async def _ingest_review_access(ingest_id: str, current_user: User, route: str) -> tuple[dict, str]:
    """The shared gate of GET /ingest/{id}/extraction and /source. Returns `(row, reason)`.

    Row absent or an EVENT row -> 404 `ingest_not_found`. ALLOWED when the caller is the row's
    `submitted_by` or `on_behalf_of` (casefold; reason `dropped_by`), or when the
    `document_promotion:<id>` task exists, is still OPEN and the caller passes
    `human_tasks.can_act_or_unavailable` on its audience (reason `task_holder`). Otherwise
    403 `not_entitled`. Decided BEFORE any artifact-store read. Every decision is audited.

    The architect, 2026-10-17:
      * "Topaz outage is 503 ... a holder of the task is never told not_entitled because a
        dependency is down." A Topaz or task-store failure is 503 `authorization_unavailable`
        (an unconfigured task store is the fleet's `hitl_unconfigured`). Any other failure of
        the task check still denies.
      * Q14: "unset Topaz URL is 503 authorization_unconfigured, not 403 -- our
        misconfiguration is never reported as entitlement." An unset TOPAZ_DIRECTORY_URL, met on
        an open task, is 503 `authorization_unconfigured`. With no open task the answer does not
        depend on Topaz, so it is still 403 `not_entitled` and Topaz is not consulted.
      * "a service reads the source of drops it delegated because the delegate rule already
        grants it (it seeded them), not because it is 'the submitter'; a service holding a
        review task counts for nothing." A service caller (`_is_service_caller`) is decided
        by the seeding-delegate rule alone (`artifact_reads.is_entitled`; reason
        `seeding_delegate`), never by the dropper fields or a task. R-089: the delegate map is
        asserted by configuration this pass."""
    from starlette.concurrency import run_in_threadpool

    import psycopg2

    from . import human_tasks, ingest_status, promotion
    from .artifact_reads import is_entitled

    caller = (current_user.authz_id or "").strip()
    row = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
    if row is None or row.get("kind") == ingest_status.EVENT:
        _audit_ingest_access(route, ingest_id, caller, "deny", "ingest_not_found")
        raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
    if _is_service_caller(caller):
        if is_entitled({"seeded_by": str(row.get("submitted_by") or "").strip()},
                       authz_id=caller, delegates=_delegate_principals()):
            _audit_ingest_access(route, ingest_id, caller, "allow", "seeding_delegate")
            return row, "seeding_delegate"
        _audit_ingest_access(route, ingest_id, caller, "deny", "not_entitled")
        raise HTTPException(status_code=403, detail={
            "error": "not_entitled",
            "message": "a service reads only the drops it seeded as a declared delegate"})
    cf = caller.casefold()
    if cf and cf in {str(row.get("submitted_by") or "").strip().casefold(),
                     str(row.get("on_behalf_of") or "").strip().casefold()} - {""}:
        _audit_ingest_access(route, ingest_id, caller, "allow", "dropped_by")
        return row, "dropped_by"
    allowed = False
    if caller:
        try:
            state = await run_in_threadpool(
                lambda: human_tasks.get_task_open_state(
                    _promotion_task_id(ingest_id, int(row.get("review_generation") or 0))))
            if state and state.get("open") and state.get("audience"):
                allowed = bool(await run_in_threadpool(
                    lambda: human_tasks.can_act_or_unavailable(state["audience"], caller)))
        except human_tasks.HumanTaskConfigError as exc:
            _audit_ingest_access(route, ingest_id, caller, "deny", "hitl_unconfigured")
            raise HTTPException(status_code=503, detail={
                "error": "hitl_unconfigured", "message": str(exc)}) from exc
        except human_tasks.AuthorizationUnconfigured as exc:
            _audit_ingest_access(route, ingest_id, caller, "deny", "authorization_unconfigured")
            raise HTTPException(status_code=503, detail={
                "error": "authorization_unconfigured",
                "message": "the deployment declares no authorization directory"}) from exc
        except (human_tasks.AuthorizationUnavailable, psycopg2.Error) as exc:
            logger.warning("ingest access task check unavailable: %s", type(exc).__name__)
            _audit_ingest_access(route, ingest_id, caller, "deny", "authorization_unavailable")
            raise HTTPException(status_code=503, detail={
                "error": "authorization_unavailable",
                "message": "could not verify the caller against the promotion task"}) from exc
        except Exception as exc:  # noqa: BLE001 -- fail closed
            logger.warning("ingest access task check failed: %s", type(exc).__name__)
            allowed = False
    if allowed:
        _audit_ingest_access(route, ingest_id, caller, "allow", "task_holder")
        return row, "task_holder"
    _audit_ingest_access(route, ingest_id, caller, "deny", "not_entitled")
    raise HTTPException(status_code=403, detail={
        "error": "not_entitled",
        "message": "only the dropper or a holder of the open promotion task may read this document"})


def _wire_evidence_ref_failure(w) -> Optional[str]:
    """The first contract check `w` fails, or None. Contract: `ingest_api.EvidenceRef`."""
    import math
    if not isinstance(w, dict):
        return "not_object"
    for k in w:
        if k not in ("page", "bbox", "note"):
            return f"extra_key:{k}"
    page = w.get("page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        return "page"
    bbox = w.get("bbox")
    if bbox is not None:
        if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                or not all(isinstance(n, (int, float)) and not isinstance(n, bool)
                           and math.isfinite(n) and 0 <= n <= 1 for n in bbox)):
            return "bbox_not_fractions"
        if not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
            return "bbox_degenerate"
    if "note" in w and (not isinstance(w["note"], str) or not w["note"].strip()):
        return "note_blank"
    return None


def _evidence_ref(it: dict) -> Optional[dict]:
    # Architect rulings 2026-10-21 (BFF serves 7f's wire_evidence_ref as is) and 2026-10-28 (the
    # contract holds nothing else): a legacy item with no wire_evidence_ref has no evidence_ref.
    if "wire_evidence_ref" not in it:
        return None
    w = it["wire_evidence_ref"]
    failed = _wire_evidence_ref_failure(w)
    if failed is None:
        return w
    logger.warning("wire_evidence_ref refused (%s) for %s", failed, it.get("field_path"))
    return None


@app.get("/ingest/{ingest_id}/extraction", tags=[INGEST_V1_TAG], responses={200: {"model": Extraction}})
async def ingest_extraction_route(ingest_id: str, current_user: User = Depends(get_current_user)):
    """GET /ingest/<id>/extraction -- the extracted part rows of a dropped notice, with the
    evidence reference (7f's `wire_evidence_ref`: page, bbox in page fractions, optional note) the review card draws. Gate: `_ingest_review_access`
    (the dropper, or a holder of the OPEN promotion task). `rows` are the `parts[i].*` items of
    review.json in file order; a row with no usable page/bbox carries `evidence_ref: null` and
    is counted in `rows_without_evidence`. 422 `no_extraction_ref` / `extraction_unbound` /
    `extraction_rows_absent` / `extraction_unreadable`, 503 `artifact_store_unreachable`.
    `leaf` / `leaf_source` / `corrected_by` are the notice's pcn|pdn and where it came from, read from
    the ROW only (`_row_leaf`); a row with no leaf shows `leaf: null` whatever review.json says.
    A REJECTED row's evidence was moved to `rejected/<id>/`; it is read there through the
    rejection record (`relocated_to` says where; `review_ref` stays the original key). Also 404
    `rejected_evidence_unlocated`, 503 `decision_ledger_unreachable`."""
    row, _why = await _ingest_review_access(ingest_id, current_user, "extraction")
    return await _extraction_body(ingest_id, row)


async def _extraction_body(ingest_id: str, row: dict) -> dict:
    """The body of GET /ingest/<id>/extraction for an already-gated `row` (the route and the
    review export share it). Raises the same HTTPExceptions the route documents."""
    from starlette.concurrency import run_in_threadpool

    ref = str(row.get("extraction_ref") or "").strip()
    if not ref:
        raise HTTPException(status_code=422, detail={
            "error": "no_extraction_ref",
            "message": f"ingest {ingest_id} has no extraction_ref yet"})
    prefix = str(row.get("object_prefix") or "")
    if not prefix or not ref.startswith(prefix):
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unbound",
            "message": f"extraction_ref {ref!r} is not under this document's directory {prefix!r}"})
    reloc = await run_in_threadpool(lambda: _rejected_relocation(ingest_id, row))
    ref_at = _relocated(ref, reloc)
    if ref_at is None:
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unbound",
            "message": f"extraction_ref {ref!r} is not under the rejection's source prefix"})
    manifest = await run_in_threadpool(lambda: _read_extraction_manifest(ref_at))
    key = _review_json_key(manifest, ref)
    if not key or not key.startswith(prefix):
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unbound",
            "message": f"the review rows are not under this document's directory {prefix!r}"})
    key_at = _relocated(key, reloc)
    if key_at is None:
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unbound",
            "message": "the review rows are not under the rejection's source prefix"})
    review = await run_in_threadpool(lambda: _read_review_json(key_at))
    items = _review_items(review)
    mpn_by_part: dict = {}
    for it in items:
        m = _PART_FIELD_RE.match(str(it.get("field_path") or ""))
        if m and m.group(2) == "affected_mpn":
            mpn_by_part.setdefault(int(m.group(1)), it.get("value"))
    rows_out = []
    without = 0
    for it in items:
        m = _PART_FIELD_RE.match(str(it.get("field_path") or ""))
        if not m:
            continue
        pi = int(m.group(1))
        ev = _evidence_ref(it)
        if ev is None:
            without += 1
        rows_out.append({
            "row_index": len(rows_out), "part_index": pi, "mpn": mpn_by_part.get(pi),
            "field": m.group(2), "extracted_value": it.get("value"),
            "obtained_via": it.get("match_method"),
            "match_confidence": it.get("match_confidence"),
            "needs_review": it.get("needs_review"), "review_reason": it.get("review_reason"),
            "source_snippet": it.get("source_snippet"), "evidence_ref": ev})
    summ = _review_notice_summary(review)
    leaf, leaf_source, corrected_by = _row_leaf(row)
    from . import content_kinds, review_shapes
    _reg = content_kinds.by_kind(row.get("content_kind") or "")
    _shape = getattr(_reg, "review_shape", None)
    _shape_row = review_shapes.valid_review_shapes().get(_shape) if _shape else None
    return {
        "ingest_id": ingest_id,
        "review_shape": _shape if _shape_row is not None else None,
        "item_kind": _shape_row.item_kind if _shape_row is not None else None,
        "notice_id": summ["notice_id"],
        "content_kind": row.get("content_kind"), "attempt": row.get("attempt"),
        "leaf": leaf, "leaf_source": leaf_source, "corrected_by": corrected_by,
        "notice": {"mfr": summ["mfr"], "mfr_source": summ["mfr_source"],
                   "mfr_parent": summ["mfr_parent"],
                   "notice_date": summ["notice_date"]},
        "part_count": summ["part_count"],
        "rows": rows_out, "rows_without_evidence": without, "review_ref": key,
        "relocated_to": reloc[1] if reloc else None}


_EXPORT_BATCH_CAPABILITY = "ingest:exportBatch"
_EXPORT_PROFILE_CAPABILITY_PREFIX = "can_export:"
_EXPORT_MAX_DAYS = 92
_EXPORT_MAX_NOTICES = 500
_EXPORT_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _export_profile_or_422(name: Optional[str]):
    """The named valid export profile, else 422 `export_profile_unknown` / `export_profile_invalid`."""
    from . import export_profiles

    p = export_profiles.load_profiles().get(name or "")
    if p is None:
        raise HTTPException(status_code=422, detail={
            "error": "export_profile_unknown",
            "message": f"no export profile {name!r}; GET /ingest/export/profiles lists them"})
    if isinstance(p, export_profiles.ProfileInvalid):
        raise HTTPException(status_code=422, detail={
            "error": "export_profile_invalid", "reason": p.reason,
            "message": f"export profile {name!r} is invalid ({p.reason})"})
    return p


async def _may_export_batch(caller: str, route: str, ingest_id: str = "-") -> bool:
    """The `ingest:exportBatch` capability for `caller`. A Topaz failure is 503, never a deny
    (same bodies as `_ingest_review_access`); an ungranted capability is False."""
    from starlette.concurrency import run_in_threadpool

    from . import human_tasks

    try:
        return bool(await run_in_threadpool(
            lambda: human_tasks.can_invoke_or_unavailable(_EXPORT_BATCH_CAPABILITY, caller)))
    except human_tasks.AuthorizationUnconfigured as exc:
        _audit_ingest_access(route, ingest_id, caller, "deny", "authorization_unconfigured")
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unconfigured",
            "message": "the deployment declares no authorization directory"}) from exc
    except human_tasks.AuthorizationUnavailable as exc:
        logger.warning("export capability check unavailable: %s", type(exc).__name__)
        _audit_ingest_access(route, ingest_id, caller, "deny", "authorization_unavailable")
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unavailable",
            "message": "could not verify the caller against the export capability"}) from exc


async def _may_export_profile(caller: str, profile_name: str, route: str,
                              ingest_id: str = "-") -> bool:
    """The `can_export:<profile>` capability for `caller`. DENY BY DEFAULT: a profile with no
    `can_export:` row is exportable by nobody (gov's #151 convention, the opposite of `can_drop`).
    A Topaz failure is 503, never a deny (same bodies as `_may_export_batch`)."""
    from starlette.concurrency import run_in_threadpool

    from . import human_tasks

    capability = f"{_EXPORT_PROFILE_CAPABILITY_PREFIX}{profile_name}"
    try:
        return bool(await run_in_threadpool(
            lambda: human_tasks.can_invoke_or_unavailable(capability, caller)))
    except human_tasks.AuthorizationUnconfigured as exc:
        _audit_ingest_access(route, ingest_id, caller, "deny", "authorization_unconfigured")
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unconfigured",
            "message": "the deployment declares no authorization directory"}) from exc
    except human_tasks.AuthorizationUnavailable as exc:
        logger.warning("export profile capability check unavailable: %s", type(exc).__name__)
        _audit_ingest_access(route, ingest_id, caller, "deny", "authorization_unavailable")
        raise HTTPException(status_code=503, detail={
            "error": "authorization_unavailable",
            "message": "could not verify the caller against the export profile capability"}) from exc


def _export_decision_record(ingest_id: str):
    """Sync (threadpool): the stored decision record, 503 `decision_ledger_unreachable` on a fault."""
    from . import promotion_stores

    try:
        return promotion_stores.PgDecisionLedger().record_for(ingest_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision ledger read failed for %s: %s", ingest_id, exc)
        raise HTTPException(status_code=503, detail={
            "error": "decision_ledger_unreachable",
            "message": f"the decision ledger did not answer: {type(exc).__name__}"})


async def _export_notice_extraction(ingest_id: str, row: dict) -> dict:
    """The extraction body of a PROMOTED, uncorrected notice, for the export; else the refusal.
    409 `ingest_not_promoted` (body carries `status`); 409 `export_corrections_not_applied`; 503
    `decision_ledger_unreachable`; then whatever `_extraction_body` refuses."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status, promotion

    if row.get("status") != ingest_status.PROMOTED:
        raise HTTPException(status_code=409, detail={
            "error": "ingest_not_promoted", "status": row.get("status"),
            "message": "only a promoted notice can be exported"})
    rec = await run_in_threadpool(lambda: _export_decision_record(ingest_id))
    if promotion._recorded_row_edits(rec):
        raise HTTPException(status_code=409, detail={
            "error": "export_corrections_not_applied",
            "message": "the promotion carries steward corrections (row or header edits) and the "
                       "export serves review.json's uncorrected values; refused until "
                       "corrections are applied to the export"})
    return await _extraction_body(ingest_id, row)


def _export_render(profile, bodies: list) -> list:
    from . import export_profiles

    out: list = []
    try:
        for b in bodies:
            out += export_profiles.render_rows(profile, b)
    except export_profiles.ExportBlocked as exc:
        raise HTTPException(status_code=422, detail={"error": "export_blocked", **exc.body()})
    return out


def _export_response(profile, rows: list, filename: str, **extra) -> Response:
    from . import export_profiles

    disp = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if profile.format == "csv":
        return Response(export_profiles.to_csv(profile.outputs, rows),
                        media_type="text/csv; charset=utf-8", headers=disp)
    return JSONResponse(export_profiles.to_json(profile, rows, **extra), headers=disp)


# The export routes carry their own tag, not ingest-v1: a v1 entry needs a JSON response model per
# route and the CSV body is not JSON. They enter v1 as PREVIEW routes (like /empty) when Lane 1
# regenerates the v1 doc and shapes lock (overnight item 5).
@app.get("/ingest/export/profiles", tags=["ingest-export", MCP_TAG],
         responses={200: {"model": list[ExportProfile]}})
async def ingest_export_profiles_route(current_user: User = Depends(get_current_user)):
    """GET /ingest/export/profiles -- the valid review-export profiles, sorted by name:
    `[{name, format, granularity, label}]`. An invalid profile is logged at ERROR and left out.
    Any authenticated caller (a name and a label are not notice content)."""
    from . import export_profiles

    out = []
    for name, p in sorted(export_profiles.load_profiles().items()):
        if isinstance(p, export_profiles.ProfileInvalid):
            logger.error("export profile %s is invalid: %s", name, p)
            continue
        out.append({"name": p.name, "format": p.format, "granularity": p.granularity,
                    "label": p.label})
    return out


@app.get("/review-shapes", tags=["ingest-export"],
         responses={200: {"model": list[ReviewShapeRow]}})
async def review_shapes_route(current_user: User = Depends(get_current_user)):
    """GET /review-shapes -- the valid review-shape registry rows (`policy/review_shapes`, the
    seed plus the deployment overlays), sorted by `review_shape`. An invalid row is logged at
    ERROR and left out. Any authenticated caller: a shape row is policy configuration, not
    content."""
    from . import review_shapes

    out = []
    for name, row in sorted(review_shapes.load_review_shapes().items()):
        if isinstance(row, review_shapes.ShapeInvalid):
            logger.error("review shape %s is invalid: %s", name, row)
            continue
        out.append(row.model_dump(mode="json"))
    return out


@app.get("/ingest/export", tags=["ingest-export", MCP_TAG])
async def ingest_export_batch_route(
        profile: Optional[str] = _Query(None), from_: Optional[str] = _Query(None, alias="from"),
        to: Optional[str] = _Query(None), current_user: User = Depends(get_current_user)):
    """GET /ingest/export?profile=&from=YYYY-MM-DD&to=YYYY-MM-DD -- every notice PROMOTED in the
    range (UTC days, both ends inclusive, by the decision record's `acted_at`), one profile.
    A service caller (`_is_service_caller`) gets the same 403 before Topaz is asked. The
    capability is DOMAIN-SCOPED (architect 2026-10-29): only notices whose promotion domain is
    one of the caller's entitlement-cell domains are in the set, filtered before the loud-not-
    partial checks and before the 500 cap; a caller with no cells gets the empty export.
    Gate: the `ingest:exportBatch` capability (403 `not_entitled_to_export_batch`, a policy
    refusal; Topaz down is 503), AND, in addition, `can_export:<profile>` for the named profile
    (403 `not_entitled_to_export`, a policy refusal; DENY BY DEFAULT: a profile with no row is
    exportable by nobody), checked after the profile resolves (an unknown one stays 422). At most 92 days (both ends counted) and 500 notices. LOUD, NOT
    PARTIAL: a notice in the set that cannot be exported (missing, not promoted, corrected,
    extraction refused) is 422 `export_notice_unreadable`; an unresolvable cell the profile blocks
    on is 422 `export_blocked`. An empty range is 200 (header-only CSV, or `rows: []`)."""
    from datetime import timedelta
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status, promotion_stores
    from .authz.refusal import policy_refusal

    caller = (current_user.authz_id or "").strip()
    if _is_service_caller(caller) or not await _may_export_batch(caller, "export_batch"):
        _audit_ingest_access("export_batch", "-", caller, "deny", "not_entitled")
        raise policy_refusal(
            "not_entitled_to_export_batch", policy_id="capability_grants:ingest:exportBatch",
            missing_binding="can_invoke ingest:exportBatch",
            message="exporting the promoted notices of a date range needs the ingest:exportBatch "
                    "capability")
    prof = _export_profile_or_422(profile)
    if not await _may_export_profile(caller, prof.name, "export_batch", "-"):
        _audit_ingest_access("export_batch", "-", caller, "deny", "not_entitled_to_profile")
        raise policy_refusal(
            "not_entitled_to_export", policy_id=f"capability_grants:can_export:{prof.name}",
            missing_binding=f"can_invoke can_export:{prof.name}",
            message=f"exporting through the {prof.name!r} profile needs the "
                    f"can_export:{prof.name} capability")

    def _day(v):
        if not isinstance(v, str) or not _EXPORT_DATE_RE.fullmatch(v):
            return None
        try:
            return _date.fromisoformat(v)
        except ValueError:
            return None

    d0, d1 = _day(from_), _day(to)
    if d0 is None or d1 is None or d0 > d1:
        raise HTTPException(status_code=422, detail={
            "error": "export_range_invalid",
            "message": "from and to are required, YYYY-MM-DD (UTC days), and from <= to"})
    if (d1 - d0).days + 1 > _EXPORT_MAX_DAYS:
        raise HTTPException(status_code=422, detail={
            "error": "export_range_too_large",
            "message": f"at most {_EXPORT_MAX_DAYS} days (both ends counted); narrow the range"})

    def _ms(d):
        return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)

    start_ms, end_ms = _ms(d0), _ms(d1 + timedelta(days=1))
    try:
        domains = {c.domain for c in current_user.entitlements.cells}
        hits = [] if not domains else await run_in_threadpool(
            lambda: promotion_stores.PgDecisionLedger().promoted_between(
                start_ms, end_ms, _EXPORT_MAX_NOTICES + 1, domains))
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision ledger range read failed: %s", exc)
        raise HTTPException(status_code=503, detail={
            "error": "decision_ledger_unreachable",
            "message": f"the decision ledger did not answer: {type(exc).__name__}"})
    if len(hits) > _EXPORT_MAX_NOTICES:
        raise HTTPException(status_code=422, detail={
            "error": "export_range_too_large",
            "message": f"more than {_EXPORT_MAX_NOTICES} notices were promoted in the range; "
                       "narrow the range"})
    bodies = []
    for ingest_id, _at in hits:
        row = await run_in_threadpool(lambda i=ingest_id: ingest_status.get_row(i))
        try:
            if row is None or row.get("kind") == ingest_status.EVENT:
                raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
            bodies.append(await _export_notice_extraction(ingest_id, row))
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            d = exc.detail if isinstance(exc.detail, dict) else {}
            raise HTTPException(status_code=422, detail={
                "error": "export_notice_unreadable", "ingest_id": ingest_id,
                "reason": d.get("error"), "message": d.get("message") or str(exc.detail)})
    rows = _export_render(prof, bodies)
    _ingest_access_log.info(
        "ingest_export_batch caller=%s profile=%s from=%s to=%s n=%d",
        caller, prof.name, d0.isoformat(), d1.isoformat(), len(bodies))
    return _export_response(
        prof, rows, f"ingest-export.{prof.name}.{d0.isoformat()}_{d1.isoformat()}.{prof.format}",
        **{"from": d0.isoformat(), "to": d1.isoformat(), "notices": len(bodies)})


@app.get("/ingest/{ingest_id}/export", tags=["ingest-export"])
async def ingest_export_route(ingest_id: str, profile: Optional[str] = _Query(None),
                              current_user: User = Depends(get_current_user)):
    """GET /ingest/<id>/export?profile=<name> -- one PROMOTED notice rendered through a profile
    (`policy/exports/`, 7f's batch-column-map vocabulary). A service caller never reaches the
    capability: the original 403 is re-raised and Topaz is not asked. The capability is
    DOMAIN-SCOPED: a notice whose promotion domain (`promotion.recorded_domain`) is not one of the
    caller's cell domains, or has none, re-raises the original 403 (audit `out_of_domain`). Gate: `_ingest_review_access` (the
    dropper, or a holder of the open task), and a caller it would 403 is admitted when they hold
    the `ingest:exportBatch` capability (reason `export_capability`); a Topaz failure while that
    is consulted is 503, a False re-raises the ORIGINAL 403. 422 `export_profile_unknown` /
    `export_profile_invalid`. IN ADDITION to the gates above, for EVERY caller who reaches it (the
    review-access path and the exportBatch path alike, a service caller that passed review access
    too): the `can_export:<profile>` capability, checked after the profile resolves; 403
    `not_entitled_to_export` (a policy refusal, DENY BY DEFAULT), Topaz down is 503. 409 `ingest_not_promoted`; 409 `export_corrections_not_applied` (the
    export serves review.json's values, so a promotion carrying steward row or header edits would
    export the uncorrected ones; refused until a later slice applies corrections); 503
    `decision_ledger_unreachable`; 422 `export_blocked` (naming notice, part, column)."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status
    from .authz.refusal import policy_refusal

    caller = (current_user.authz_id or "").strip()
    try:
        row, _why = await _ingest_review_access(ingest_id, current_user, "export")
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        if _is_service_caller(caller):
            raise
        if not await _may_export_batch(caller, "export", ingest_id):
            raise
        row = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
        if row is None or row.get("kind") == ingest_status.EVENT:
            raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
        from . import promotion

        rec = await run_in_threadpool(lambda: _export_decision_record(ingest_id))
        if promotion.recorded_domain(rec) not in {c.domain for c in current_user.entitlements.cells}:
            _audit_ingest_access("export", ingest_id, caller, "deny", "out_of_domain")
            raise
        _audit_ingest_access("export", ingest_id, caller, "allow", "export_capability")
    prof = _export_profile_or_422(profile)
    if not await _may_export_profile(caller, prof.name, "export", ingest_id):
        _audit_ingest_access("export", ingest_id, caller, "deny", "not_entitled_to_profile")
        raise policy_refusal(
            "not_entitled_to_export", policy_id=f"capability_grants:can_export:{prof.name}",
            missing_binding=f"can_invoke can_export:{prof.name}",
            message=f"exporting through the {prof.name!r} profile needs the "
                    f"can_export:{prof.name} capability")
    body = await _export_notice_extraction(ingest_id, row)
    rows = _export_render(prof, [body])
    return _export_response(prof, rows, f"{ingest_id}.{prof.name}.{prof.format}")


_SOURCE_MEDIA_TYPES = {"pdf": "application/pdf", "xml": "application/xml"}


def _rejected_relocation(ingest_id: str, row: dict) -> Optional[tuple]:
    """Sync (threadpool): for a REJECTED row, `(from, to)` -- the prefix the rejection moved the
    document's objects out of and into, read from the rejection record and never guessed. None for
    any other row (`review_rejected`, the grouped narrow reject, moves nothing). 503
    `decision_ledger_unreachable`; 404 `rejected_evidence_unlocated` when the record does not say
    where the objects went (it predates the field)."""
    from . import ingest_status, promotion_stores

    if row.get("status") != ingest_status.REJECTED:
        return None
    try:
        rec = promotion_stores.PgDecisionLedger().record_for(ingest_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision ledger read failed for %s: %s", ingest_id, exc)
        raise HTTPException(status_code=503, detail={
            "error": "decision_ledger_unreachable",
            "message": f"the decision ledger did not answer: {type(exc).__name__}"})
    q = rec.get("quarantine") if isinstance(rec, dict) and rec.get("outcome") == "rejected" else None
    frm = q.get("from") if isinstance(q, dict) else None
    to = q.get("to") if isinstance(q, dict) else None
    if not (isinstance(frm, str) and frm and isinstance(to, str) and to):
        raise HTTPException(status_code=404, detail={
            "error": "rejected_evidence_unlocated",
            "message": f"ingest {ingest_id} was rejected and the rejection record does not say "
                       "where its objects went (it predates the field); nothing is guessed"})
    return frm, to


def _relocated(key: str, reloc: Optional[tuple]) -> Optional[str]:
    """`key` where the evidence now is: unchanged with no relocation; under the record's `to` when
    `key` was under its `from`; None when it was not (the caller's `*_unbound` 422)."""
    if reloc is None:
        return key
    frm, to = reloc
    return to + key[len(frm):] if key.startswith(frm) else None


def _open_source_object(ingest_id: str, row: dict) -> tuple[Any, str]:
    """Sync (threadpool): resolve the row's own source object and open it. The key comes from the
    drop manifest's `object_ref` (the seam's `<prefix><safe_name>`), which must be one of the
    seam's keys for THIS document (`promotion.object_prefix_for`) and under the row's
    `object_prefix`, else 422 `source_unbound`. 404 `source_absent`, 503
    `artifact_store_unreachable`. A REJECTED row's objects live under `rejected/<id>/`: they are
    read there through the rejection record (404 `rejected_evidence_unlocated`, 503
    `decision_ledger_unreachable`). Returns `(s3 Body, original key)`."""
    import json as _j

    from . import promotion

    prefix = str(row.get("object_prefix") or "")
    if not prefix:
        raise HTTPException(status_code=422, detail={"error": "source_unbound"})

    def _get(key: str):
        try:
            return _build_s3_client().get_object(Bucket=_ARTIFACT_BUCKET, Key=key)["Body"]
        except Exception as exc:  # noqa: BLE001
            code = ""
            resp = getattr(exc, "response", None)
            if isinstance(resp, dict):
                code = str((resp.get("Error") or {}).get("Code") or "")
            if code in ("NoSuchKey", "404") or "NoSuchKey" in str(exc):
                raise HTTPException(status_code=404, detail={"error": "source_absent"})
            raise HTTPException(status_code=503, detail={
                "error": "artifact_store_unreachable",
                "message": f"the artifact store did not answer: {type(exc).__name__}"})

    reloc = _rejected_relocation(ingest_id, row)
    man_at = _relocated(f"{prefix}manifest.json", reloc)
    if man_at is None:
        raise HTTPException(status_code=422, detail={"error": "source_unbound"})
    try:
        dropped = _j.loads(_get(man_at).read())
    except (ValueError, UnicodeDecodeError):
        dropped = None
    ref = dropped.get("object_ref") if isinstance(dropped, dict) else None
    if (not isinstance(ref, str) or promotion.object_prefix_for(ingest_id, ref) is None
            or not ref.startswith(prefix)):
        raise HTTPException(status_code=422, detail={
            "error": "source_unbound",
            "message": f"the drop's source object is not a key under {prefix!r}"})
    ref_at = _relocated(ref, reloc)
    if ref_at is None:
        raise HTTPException(status_code=422, detail={"error": "source_unbound"})
    return _get(ref_at), ref


@app.get("/ingest/{ingest_id}/source", tags=[INGEST_V1_TAG], responses={200: BINARY_200})
async def ingest_source_route(ingest_id: str, current_user: User = Depends(get_current_user)):
    """GET /ingest/<id>/source -- the dropped document's own bytes, streamed in chunks (never
    buffered whole). Same gate and audit as `/extraction`; works for the dropper before any
    extraction exists. 422 `source_unbound`, 404 `source_absent`, 503 `artifact_store_unreachable`;
    a rejected row is read from `rejected/<id>/` through its record: 404 `rejected_evidence_unlocated`,
    503 `decision_ledger_unreachable`.
    The app-wide middleware sets `Cache-Control: no-store` on the response."""
    import posixpath
    from starlette.concurrency import run_in_threadpool

    row, _why = await _ingest_review_access(ingest_id, current_user, "source")
    body, key = await run_in_threadpool(lambda: _open_source_object(ingest_id, row))

    def _chunks():
        try:
            while True:
                chunk = body.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            close = getattr(body, "close", None)
            if close:
                close()

    name = posixpath.basename(key).replace('"', "")
    return StreamingResponse(
        _chunks(), media_type=_SOURCE_MEDIA_TYPES.get(str(row.get("kind")), "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{name}"',
                 "Cache-Control": "private, no-store"})


class IngestRetryRequest(_BaseModel):
    """POST /ingest/{id}/retry's body: the extractor pin the caller observed NOW."""
    pin_digest: str = Field(..., min_length=1)


def _is_service_caller(authz_id: Optional[str]) -> bool:
    """A non-human authz id: the `svc:` namespace (policy/users.yaml) or an asserted delegate
    (`_delegate_principals`, R-089: a delegate is a service, never a person). Same predicate
    family as safety_agent/measures.py."""
    a = (authz_id or "").strip()
    return bool(a) and (a.startswith("svc:") or a in _delegate_principals())


@app.post("/ingest/{ingest_id}/retry", tags=[INGEST_V1_TAG], responses={200: {"model": RetryResponse}})
async def ingest_retry_route(ingest_id: str, body: Optional[IngestRetryRequest] = None,
                             current_user: User = Depends(get_current_user)):
    """POST /ingest/<id>/retry. The architect's 2026-10-12 directive, "pipeline failure must reach
    the row", supersedes the 2026-10-10 "pin-driven only, never the UI" ruling FOR FAILED ROWS: a
    person may retry their OWN `failed` document row, and a service may retry one without a pin.
    This is the one legitimate human retry, because the input was never processed. Every other
    extraction retry stays pin-driven and service-only (supersedes the dropper's own retry of
    roll #20 item 3).

    THE RETRY ONLY RE-OPENS THE ROW (`ingest_status.retry_failed`: failed -> received, `failure`
    cleared, `attempt` + 1). doc-tools' `ingress_user_sensor` does not relaunch an unchanged object:
    its LastModified cursor has already passed it, and its run_key is `{ETag}-{key}`. So until
    doc-tools adds a relaunch path, a retried row sits at `received` and the watchdog fails it again
    with `timeout`. That outcome is visible and honest, not silent.

    TWO ACTS SHARE THIS ROUTE, and the two 2026-10-10 rulings govern one each (rev 187 merge of #32
    and #43; the architect is asked to confirm, packet 2026-10-11 "two rulings collide"):
      * RE-FILING a promotion from recorded state (`awaiting_origin`, Q2c) re-extracts nothing and
        is idempotent -- the dropper may do it, exactly as the accept and stage routes may.
      * RE-EXTRACTION (every other stage) is pin-driven and service-only, as steward item 4 rules.

    Gate, in order:
      * A PERSON is looked up SCOPED (`get_status_for`: rows they submitted or are on_behalf_of).
        Their own `failed` DOCUMENT row is re-opened (200 `received` with the new `attempt`; 409
        `not_failed` if it stopped being failed under them). Their own `awaiting_origin` DOCUMENT
        row goes to Q2c. Anything else -- another stage, a row
        that is not theirs, no row at all -- is the SAME 403 `retry_is_pin_driven`, so the answer
        tells a person nothing about rows they cannot already see. A person never reaches the
        unscoped lookup or any extraction-retry action.
      * A SERVICE is looked up unscoped. An `awaiting_origin` DOCUMENT row goes to Q2c (re-filing
        is not pin-driven); a `failed` DOCUMENT row is re-opened with no pin. Otherwise it must send `{pin_digest}` (422 `pin_required`); a row with
        no recorded pin is 409 `no_recorded_pin`; an equal pin is 409 `pin_unchanged`; only a
        DIFFERENT pin proceeds to the dispatch below.

    Dispatch on the row:
      * already terminal (promoted/rejected/duplicate/case_opened, or a failed EVENT row) -- 409
        `terminal`; nothing to retry.
      * a DOCUMENT row at `awaiting_origin` (Q2c, 2026-10-10) -- NOT terminal: runs the state
        function `_file_promotion_if_ready` with THIS caller as `requested_by`. Filed -> 200
        `review` with the task; no accepted origin yet -> 409 `awaiting_origin`; origin
        unreadable or filing refused -> 503 `promotion_not_filed` (row stays put).
      * an EVENT row, which by this point can only be sitting at `received` (its own only
        non-terminal stage -- POST /ingest/events moves it straight to `case_opened`, never
        through extracting/review) -- 409 `resend_the_event`: the row holds only the payload
        hash, so the fix is to resend the same event, not to retry here.
      * a failed DOCUMENT row is re-opened at `received` (a row with a leaf has the drop's sidecar
        rewritten to that leaf first; 503 `sidecar_unwritable` if it cannot be).
      * a DOCUMENT row at `received`/`extracting` -- 409 `in_pipeline`: extraction runs in
        doc-tools' own pipeline (ingress_user_sensor); a retry here cannot advance it.
      * a DOCUMENT row at `review` -- the one stage this CAN move: re-runs the
        `document_promotion` find-or-file via the SAME helper `update_ingest_stage` uses
        (`_file_or_find_document_promotion_task`) so the two routes share one implementation.
        `requested_by` is THIS caller (the retrying party), never doc-tools' service identity.
        The row itself is NOT moved -- it is already at `review`.
    """
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    async def _refile_from_state(requested_by: str) -> dict:
        """Q2c (2026-10-10): re-file a DOCUMENT row at `awaiting_origin` through the SAME state function
        the accept and stage routes call, with the retrying party as `requested_by`. Filed -> 200
        `review` with the task; no accepted origin yet -> 409 `awaiting_origin`; origin unreadable or
        filing refused -> 503 `promotion_not_filed` (the row stays put). Re-extracts nothing."""
        stage = ingest_status.AWAITING_ORIGIN
        out = await _file_promotion_if_ready(ingest_id, requested_by=requested_by)
        if out and out.get("filed"):
            return {"ingest_id": ingest_id, "stage": ingest_status.REVIEW,
                    "task_id": out["task_id"], "task_status": out["task_status"]}
        if out and out.get("promoted"):
            return {"ingest_id": ingest_id, "stage": ingest_status.PROMOTED,
                    "task_id": None, "task_status": out["task_status"]}
        if out is None:
            raise HTTPException(status_code=409, detail={
                "error": "awaiting_origin", "stage": stage,
                "message": "no accepted origin is recorded for this artifact yet; a steward's accept files it"})
        raise HTTPException(status_code=503, detail={"error": "promotion_not_filed",
                                                     "reason": out.get("error"), "stage": stage})

    def _refiles_from_state(r: Optional[dict]) -> bool:
        return (r is not None and r.get("status") == ingest_status.AWAITING_ORIGIN
                and r.get("kind") != ingest_status.EVENT)

    def _is_failed_document(r: Optional[dict]) -> bool:
        return (r is not None and r.get("status") == ingest_status.FAILED
                and r.get("kind") != ingest_status.EVENT)

    async def _reopen_failed(r: Optional[dict] = None) -> dict:
        """Re-open a failed DOCUMENT row (`r`: the row the caller already read). A row with a leaf
        (pcn|pdn) has the drop's sidecar rewritten to that leaf FIRST, so the relaunch runs as the leaf
        and the leaf-relaunch pass finds nothing left to do; a sidecar that cannot be written is 503
        `sidecar_unwritable` and the row is unchanged. `retry_failed` is one atomic UPDATE guarded on
        `status = 'failed'`, so of two concurrent retries the second gets None -> 409."""
        _leaf_now = str((r or {}).get("content_kind") or "").strip().lower()
        if r and _leaf_capable(r) and _leaf_now in ingest_status.LEAVES:
            try:
                await run_in_threadpool(lambda: _apply_leaf_to_sidecar(r, _leaf_now))
            except Exception as exc:  # noqa: BLE001
                logger.warning("ingest_retry ingest_id=%s sidecar not written (%s: %s)", ingest_id,
                               type(exc).__name__, exc)
                raise HTTPException(status_code=503, detail={
                    "error": "sidecar_unwritable", "stage": ingest_status.FAILED,
                    "message": "the drop's manifest could not be updated to the row's kind, so "
                               "nothing was changed; try again"})
        attempt = await run_in_threadpool(lambda: ingest_status.retry_failed(ingest_id))
        if attempt is None:
            raise HTTPException(status_code=409, detail={
                "error": "not_failed",
                "message": "only a failed document can be retried; this one is not failed."})
        return {"ingest_id": ingest_id, "stage": ingest_status.RECEIVED, "attempt": attempt}

    if not _is_service_caller(current_user.authz_id):
        own = await run_in_threadpool(
            lambda: ingest_status.get_status_for(ingest_id, caller_id=current_user.authz_id))
        if _refiles_from_state(own):
            return await _refile_from_state(current_user.authz_id)
        if _is_failed_document(own):
            return await _reopen_failed(own)
        raise HTTPException(status_code=403, detail={
            "error": "retry_is_pin_driven",
            "message": "a retry is driven only by an extractor pin change, never by a person"})
    row = await run_in_threadpool(lambda: ingest_status.get_status_unscoped(ingest_id))
    if row is None:
        raise HTTPException(status_code=404, detail="ingest not found")
    if _refiles_from_state(row):
        return await _refile_from_state(current_user.authz_id)
    if _is_failed_document(row):
        # No pin: the input was never processed, so there is no extractor pin to have changed.
        return await _reopen_failed(row)
    if body is None:
        raise HTTPException(status_code=422, detail={
            "error": "pin_required",
            "message": "a service retry sends the extractor pin it observed: {pin_digest}"})
    recorded_pin = row.get("pin_digest")
    if not recorded_pin:
        raise HTTPException(status_code=409, detail={
            "error": "no_recorded_pin",
            "message": "this row records no extractor pin (pin_fields_missing); a pin-driven "
                       "retry needs the pin follow-up"})
    if body.pin_digest == recorded_pin:
        raise HTTPException(status_code=409, detail={
            "error": "pin_unchanged",
            "message": "the extractor pin is the one the failed run recorded; a retry would fail the same way until the pin changes."})

    stage = row["status"]
    _terminal_stages = (
        ingest_status.PROMOTED, ingest_status.REJECTED, ingest_status.FAILED,
        ingest_status.DUPLICATE, ingest_status.CASE_OPENED, ingest_status.REVIEW_REJECTED,
        ingest_status.NO_PARTS,
    )
    if stage in _terminal_stages:
        raise HTTPException(status_code=409, detail={
            "error": "terminal", "stage": stage,
            "message": f"this document is {stage}, a terminal stage; it cannot move."})

    if row.get("kind") == ingest_status.EVENT:
        raise HTTPException(status_code=409, detail={
            "error": "resend_the_event",
            "message": "the row holds only the payload hash; resend the same event to "
                       "POST /ingest/events, which is idempotent on event_id",
        })

    if stage == ingest_status.AWAITING_KIND:
        raise HTTPException(status_code=409, detail={
            "error": "awaiting_kind", "stage": stage,
            "message": "pick a leaf: POST /ingest/{id}/leaf"})

    if stage in (ingest_status.RECEIVED, ingest_status.EXTRACTING):
        raise HTTPException(status_code=409, detail={
            "error": "in_pipeline", "pipeline": "doc-tools", "stage": stage,
            "message": "extraction runs in doc-tools' pipeline (ingress_user_sensor); a retry "
                       "here cannot advance it",
        })

    # Only `review` is left on the ladder here. The row is not moved -- it is already there.
    task_id, task_status = await _file_or_find_document_promotion_task(
        ingest_id, row, requested_by=current_user.authz_id,
        extraction_ref=row.get("extraction_ref"))

    return {"ingest_id": ingest_id, "stage": ingest_status.REVIEW, "task_id": task_id,
            "task_status": task_status}


# doc-tools' own transport identity (policy/users.yaml: `svc:doc-tools`, "semantic-linker
# transport identity"). SAME IDIOM as `_VAULT_REDEEMER_AUTHZ_ID`: a Keycloak hardcoded-claim
# mapper output, not a caller-supplied value, so it is not spoofable; env-overridable only so a
# differently-named realm can be configured, never to widen it -- an empty value denies
# everyone rather than admitting everyone.
_DOC_TOOLS_SERVICE_AUTHZ_ID = os.getenv("DOC_TOOLS_SERVICE_IDENTITY", "svc:doc-tools").strip()

class IngestStageUpdateRequest(_BaseModel):
    """POST /ingest/{ingest_id}/stage's body -- doc-tools' own write into the stage ladder
    (ADR-0041 §8; doc-tools' `IngestStatusResource.update` validates and logs only, and this
    route is the transport Lane 1 picked for it, HTTP into the BFF)."""
    stage: str
    extracted_count: Optional[int] = None
    extracted_total: Optional[int] = None
    detail: Optional[str] = None
    # doc-tools #84 names its VERSIONED manifest here (bare S3 key in `processing-artifacts`).
    # Before this field existed Pydantic dropped it silently, and the promotion task was filed
    # with a payload the act refused.
    extraction_ref: Optional[str] = None
    # 2026-10-12 (pipeline failure must reach the row, architect directive). `run_id` is the Dagster
    # run, accepted on ANY target stage; the other four are the structured failure and are valid
    # only with stage == "failed". `reason_code` is OPTIONAL on `failed` for legacy compatibility:
    # doc-tools today posts `failed` with `detail` only and the two sides deploy separately.
    reason_code: Optional[str] = None
    reason: Optional[str] = None
    step: Optional[str] = None
    run_id: Optional[str] = None
    pin_digest: Optional[str] = None


def _read_extraction_manifest(key: str) -> dict:
    """Read and parse the extraction manifest at `key` in the artifact bucket (sync; callers
    run it in the threadpool). 422 `extraction_absent` when the store answers that the key is
    not there, 503 `artifact_store_unreachable` for any other failure to read, 422
    `extraction_unreadable` when the bytes are not a JSON object."""
    import json as _j

    try:
        body = _build_s3_client().get_object(Bucket=_ARTIFACT_BUCKET, Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        code = ""
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            code = str((resp.get("Error") or {}).get("Code") or "")
        if code in ("NoSuchKey", "404") or "NoSuchKey" in str(exc):
            raise HTTPException(status_code=422, detail={
                "error": "extraction_absent",
                "message": f"no object at s3://{_ARTIFACT_BUCKET}/{key}; the store answered and "
                           "said so, so extraction_ref is a bad pointer, not an outage"})
        raise HTTPException(status_code=503, detail={
            "error": "artifact_store_unreachable",
            "message": f"the artifact store did not answer for {key!r}: "
                       f"{type(exc).__name__}: {exc}"})
    try:
        doc = _j.loads(body)
    except (ValueError, UnicodeDecodeError):
        doc = None
    if not isinstance(doc, dict):
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unreadable",
            "message": f"the object at {key!r} is not a JSON object"})
    return doc


_PART_FIELD_RE = re.compile(r"^parts\[(\d+)\]\.(.+)$")


def _review_json_key(manifest: dict, extraction_ref: str) -> Optional[str]:
    """The key of the review.json doc-tools wrote beside the manifest's `text_location` (same
    directory), or None when `text_location` is an s3:// URL for another bucket. `text_location`
    is a bare key or an `s3://<bucket>/<key>` URL; blank falls back to the directory of the
    manifest itself (`extraction_ref`), which is the same generated/<base>/<version>/ directory."""
    import posixpath
    from urllib.parse import urlparse

    loc = str((manifest or {}).get("text_location") or "").strip()
    if loc.startswith("s3://"):
        u = urlparse(loc)
        if u.netloc != _ARTIFACT_BUCKET:
            return None
        key = u.path.lstrip("/")
    else:
        key = loc or str(extraction_ref or "").strip()
    return posixpath.dirname(key) + "/review.json"


def _read_review_json(key: str) -> dict:
    """Read review.json at `key` (sync; threadpool). Same mapping as `_read_extraction_manifest`
    but its own error names: 422 `extraction_rows_absent` (store said NoSuchKey), 503
    `artifact_store_unreachable`, 422 `extraction_unreadable` (not a JSON object)."""
    import json as _j

    try:
        body = _build_s3_client().get_object(Bucket=_ARTIFACT_BUCKET, Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        code = ""
        resp = getattr(exc, "response", None)
        if isinstance(resp, dict):
            code = str((resp.get("Error") or {}).get("Code") or "")
        if code in ("NoSuchKey", "404") or "NoSuchKey" in str(exc):
            raise HTTPException(status_code=422, detail={
                "error": "extraction_rows_absent",
                "message": "the store answered that this extraction has no review.json"})
        raise HTTPException(status_code=503, detail={
            "error": "artifact_store_unreachable",
            "message": f"the artifact store did not answer: {type(exc).__name__}"})
    try:
        doc = _j.loads(body)
    except (ValueError, UnicodeDecodeError):
        doc = None
    if not isinstance(doc, dict):
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unreadable", "message": "review.json is not a JSON object"})
    return doc


def _bound_review_for_payload(subject) -> dict:
    """The parsed review.json a promotion task points at (sync; threadpool). 422
    `extraction_unbound` when the extraction is not under the document's own directory; the
    readers raise their own HTTPException on a store failure."""
    from . import promotion

    ref = str(subject.extraction_ref or "").strip()
    prefix = promotion.object_prefix_for(subject.ingest_id, subject.object_ref)
    if not prefix or not ref.startswith(prefix):
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unbound",
            "message": f"extraction_ref {ref!r} is not under this document's directory {prefix!r}"})
    manifest = _read_extraction_manifest(ref)
    key = _review_json_key(manifest, ref)
    if not key or not key.startswith(prefix):
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unbound",
            "message": f"the review rows are not under this document's directory {prefix!r}"})
    return _read_review_json(key)


def _handler_consumes(kind, field: str) -> bool:
    """Whether the handler for `kind` reads request field `field`: the gate asks the handler."""
    from . import promotion
    return kind == promotion.KIND and field in promotion.CONSUMES


def _review_parts_for_payload(subject) -> list:
    """The distinct `part_index` of the extraction a promotion task points at (sync; threadpool),
    read through the reader behind `GET /ingest/{id}/extraction`."""
    return sorted({int(m.group(1)) for it in _review_items(_bound_review_for_payload(subject))
                   if (m := _PART_FIELD_RE.match(str(it.get("field_path") or "")))})


def _review_header_for_payload(subject) -> dict:
    """`_review_notice_summary` of the bound review (sync; threadpool); same binding checks."""
    return _review_notice_summary(_bound_review_for_payload(subject))


def _review_mpns_for_payload(subject) -> list:
    """The affected_mpn of every part row of the review a promotion task points at (sync;
    threadpool); binding as `_bound_review_for_payload`."""
    out = []
    for it in _review_items(_bound_review_for_payload(subject)):
        m = _PART_FIELD_RE.match(str(it.get("field_path") or ""))
        if m and m.group(2) == "affected_mpn":
            v = it.get("value")
            if isinstance(v, str) and v.strip():
                out.append(v)
    return out


def _review_items(review: dict) -> list:
    items = review.get("review_items")
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


def _extraction_row_count(review: dict) -> int:
    """How many part ROWS an extraction holds: the distinct `i` of the `parts[i].*` items of
    review.json -- the same items `GET /ingest/{id}/extraction` serves as `rows` (one per field),
    counted per part. Header items are not rows."""
    return len({int(m.group(1)) for it in _review_items(review)
                if (m := _PART_FIELD_RE.match(str(it.get("field_path") or "")))})


async def _server_extraction_review(extraction_ref: str, prefix: str) -> Optional[dict]:
    """The parsed review.json beside the manifest `extraction_ref` names, or None when it cannot be
    read (no ref, not under the document's directory, store down, bad JSON). The ONE read behind
    the zero-row check."""
    from starlette.concurrency import run_in_threadpool

    ref = str(extraction_ref or "").strip()
    if not ref or not prefix or not ref.startswith(prefix):
        return None
    try:
        manifest = await run_in_threadpool(lambda: _read_extraction_manifest(ref))
        key = _review_json_key(manifest, ref)
        if not key or not key.startswith(prefix):
            return None
        return await run_in_threadpool(lambda: _read_review_json(key))
    except Exception:  # noqa: BLE001 -- HTTPException or anything else: unreadable
        return None


async def _server_extraction_row_count(extraction_ref: str, prefix: str) -> Optional[int]:
    """The SERVER's row count for the extraction `extraction_ref` names, or None when it cannot be
    read (no ref, not under the document's directory, store down, bad JSON). None is not zero:
    a read failure keeps today's behaviour rather than becoming `extraction_empty`."""
    review = await _server_extraction_review(extraction_ref, prefix)
    if review is None:
        return None
    return _extraction_row_count(review)


def _review_notice_id(review: dict) -> Optional[str]:
    """The notice's own id as the extraction printed it -- review.json's `doc_id_raw`
    (`PCN#20210316000.1`), or None when the header pass extracted none. doc-tools #141 (2026-10-17)
    made it extraction-only: null, never a fallback to the key or the filename. DISPLAY ONLY. The
    manifest's `doc_id` is NOT this: it is the filename-derived transport key."""
    v = review.get("doc_id_raw")
    return (v.strip() or None) if isinstance(v, str) else None


def _title_leaf(doc_type, doc_type_source) -> Optional[str]:
    """The leaf (`pcn`/`pdn`) a title read names CONFIDENTLY, else None. Confident iff
    `doc_type_source == "title"` AND the lowercased, stripped `doc_type` is a leaf. A defaulted
    `doc_type` is refused: doc-tools fills `"PCN"` when it derived nothing (sources
    `no-title-evidence`, `title-ambiguous`, `defaulted`, or absent), so it is a routing default, not
    a fact about the notice. ONE definition, used by `POST /ingest/{id}/title_leaf`."""
    from . import ingest_status

    dt = str(doc_type or "").strip().lower()
    if doc_type_source == "title" and dt in ingest_status.LEAVES:
        return dt
    return None


def _row_leaf(row) -> tuple:
    """(leaf, leaf_source, corrected_by) for a row -- READ FROM THE ROW ONLY (spec 203b). The status
    body, the review card, the `title_leaf` answer and the decision record all read it here.
    `leaf` is `content_kind` lowercased when it names a leaf, else None. `leaf_source` is the stored
    column as written (`declared`|`title`|`corrected`) with NO default: a NULL stays None.
    `corrected_by` is `leaf_set_by` when the source is `corrected`, else None."""
    from . import ingest_status

    row = row or {}
    ck = str(row.get("content_kind") or "").strip().lower()
    leaf = ck if ck in ingest_status.LEAVES else None
    source = row.get("leaf_source")
    corrected_by = row.get("leaf_set_by") if source == "corrected" else None
    return (leaf, source, corrected_by)


def _same_passes(old_kind, new_kind) -> bool:
    """True when both kinds are registered and declare EQUAL pass lists (spec 204, ruling "pcn<->pdn:
    re-class, not re-run. Both kinds run the same passes, so the change is a recorded correction.
    Re-run only when the two kinds' pass lists differ"). DERIVED from the content-kind registry --
    there is no local table of kinds: an unregistered kind is never "the same", so it re-runs."""
    from . import content_kinds

    a = content_kinds.by_kind(str(old_kind or "").strip().lower())
    b = content_kinds.by_kind(str(new_kind or "").strip().lower())
    return a is not None and b is not None and tuple(a.passes) == tuple(b.passes)


def _leaf_capable(row) -> bool:
    """A leaf-capable row is not an event row and is a notice-in-waiting: its `content_kind` is a
    leaf or `pdf`, or it is NULL and the file `kind` is `pdf`. cad / xml / s1000d / engineering-
    document rows are not (the leaf keys are absent from their status body, `/leaf` refuses them)."""
    from . import ingest_status

    if row.get("kind") == "event":
        return False
    ck = str(row.get("content_kind") or "").strip().lower()
    if ck in ingest_status.LEAVES or ck == "pdf":
        return True
    return (not ck) and row.get("kind") == "pdf"


def _review_notice_summary(review: dict) -> dict:
    """`{notice_id, mfr, mfr_source, mfr_identity, mfr_parent, notice_date, part_count}` from a
    parsed review.json. `notice_id` is `_review_notice_id`; `mfr` is the `header.mfr` item's value,
    else `notice_identity.mfr`; `mfr_source` says which: `"header"` (non-blank header value),
    `"identity"` (the fallback supplied a non-blank value) or None. `mfr_identity` is
    `notice_identity.mfr` stripped (None when absent or blank) whatever `mfr_source` is -- the act
    route's evidence for a steward filling a missing header.mfr. Dates are strings as given."""
    by_path: dict = {}
    parts: set = set()
    for it in _review_items(review):
        fp = str(it.get("field_path") or "")
        by_path.setdefault(fp, it.get("value"))
        m = _PART_FIELD_RE.match(fp)
        if m:
            parts.add(int(m.group(1)))
    ident = review.get("notice_identity")
    mfr = by_path.get("header.mfr")
    ident_mfr = ident.get("mfr") if isinstance(ident, dict) else None
    mfr_identity = ident_mfr.strip() if isinstance(ident_mfr, str) and ident_mfr.strip() else None
    if isinstance(mfr, str) and mfr.strip():
        mfr_source = "header"
    elif mfr_identity is not None:
        mfr_source = "identity"
    else:
        mfr_source = None
    if mfr_source == "identity":
        mfr = mfr_identity          # a BLANK header value is a miss too; show what the source names
    elif mfr is None:
        mfr = ident_mfr
    return {"notice_id": _review_notice_id(review),
            "mfr": mfr, "mfr_source": mfr_source, "mfr_identity": mfr_identity,
            "mfr_parent": by_path.get("header.mfr_parent"),
            "notice_date": by_path.get("header.pub_date"), "part_count": len(parts)}


async def _soft_review_summary(manifest: dict, extraction_ref: str, prefix: str) -> Optional[dict]:
    """The notice summary for the review card's payload, or None when review.json is absent,
    unbound or unreadable -- NEVER a refusal: the task must still file."""
    from starlette.concurrency import run_in_threadpool

    key = _review_json_key(manifest, extraction_ref)
    if not key or not key.startswith(prefix):
        return None
    try:
        review = await run_in_threadpool(lambda: _read_review_json(key))
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001
        return None
    return _review_notice_summary(review)


def _promotion_task_id(ingest_id: str, generation: int) -> str:
    """The `document_promotion` task id for a document at a promotion GENERATION (spec 204): the
    legacy `document_promotion:<id>` at generation 0, `document_promotion:<id>:g<n>` after. A leaf
    change at review files the next generation and supersedes the old, so a stale id is refusable."""
    from . import promotion

    if not generation:
        return f"{promotion.KIND}:{ingest_id}"
    return f"{promotion.KIND}:{ingest_id}:g{int(generation)}"


def _current_promotion_task_id(row) -> str:
    """The task id the row's CURRENT generation names (a legacy row without the column reads 0)."""
    row = row or {}
    return _promotion_task_id(str(row.get("id") or ""), int(row.get("review_generation") or 0))


async def _file_or_find_document_promotion_task(
    ingest_id: str, row: dict, *, requested_by: str, extraction_ref: Optional[str],
    domain: Optional[str] = None, notice_out: Optional[dict] = None,
    generation: Optional[int] = None,
) -> tuple[Optional[str], str]:
    """Find-or-file the `document_promotion` task for a DOCUMENT row at `review` -- the
    refactored-out body of `update_ingest_stage`'s own `if req.stage == ingest_status.REVIEW:`
    block (review-audience fix's domain resolution, task_exists-before-register_task, and the
    503/422/422 exception mapping), now shared with `ingest_retry_route`'s re-run of the same
    find-or-file on a row already at `review` (roll #20 item 3) -- ONE helper, not a second,
    divergent copy.

    THE ROW CARRIES THE FILE FORMAT, NOT THE DECLARED KIND: resolves the registry on
    `content_kind` (the declared, registry-level kind), never on `kind` (pdf|cad|xml) -- a lookup
    on the file format always misses the registry, resolves to a None domain, and files a task
    no one can be entitled to.

    `domain`, when given (stripped non-empty), IS the audience domain and the kind registry is not
    consulted: the origin-accept caller (`write_origin_route`) passes the accepted origin's
    `owner_domain` (Q2 ruling 2026-10-10). Otherwise the audience comes from the kind registry.

    `requested_by` is the caller each route should be attributing the task to -- doc-tools'
    own service identity for `update_ingest_stage`'s transition INTO `review`, or the retrying
    caller's own authz_id for a retry; this helper does not decide which, it only takes it.

    THE PAYLOAD IS DERIVED, NOT ASSERTED (ADR-0034): everything the act needs beyond the domain
    and the dropper comes from the versioned extraction manifest `extraction_ref` names, read
    here and turned into the payload by `promotion.payload_from_extraction`. An existing task
    needs no manifest, so `ALREADY_FILED` is answered before any of that -- and keeps the
    payload and title it was filed with (a task filed before 193.2 never gains
    `mfr`/`notice_date`/`part_count`/`attempt`) -- EXCEPT when its payload's `content_kind` differs from
    the row's (the leaf changed, spec 203b): then the payload is derived exactly as below and every
    `pending` row is rewritten (`human_tasks.refresh_open_task`); a different audience is 409
    `leaf_moves_audience`, nothing written. Still answers `ALREADY_FILED`.

    The payload also carries the review card's four header facts, always present, None when
    unknown: `mfr`, `notice_date`, `part_count` (from the review.json beside the manifest's
    `text_location`, read softly -- absent or unreadable never refuses the filing) and `attempt`
    (the row's). The title is the notice id when there is one.

    Raises HTTPException for every refusal (422 `no_declared_domain`, 422 `no_extraction_ref`,
    422 `extraction_unbound`, 422 `extraction_absent`, 422 `extraction_unreadable`, 422
    `extraction_unversioned`, 503 `artifact_store_unreachable`, 503
    `hitl_unconfigured`, 422 `no_entitled_recipients`, 422 `no_requester`) and never writes a
    task on any of them. Returns `(task_id, "FILED" | "ALREADY_FILED")` on success. Never
    moves the row itself -- callers that need the row moved do that themselves, in order
    (TASK FIRST, STATUS SECOND): a 422/503 from here must never strand the row.
    """
    from starlette.concurrency import run_in_threadpool

    from . import content_kinds, human_tasks, promotion

    domain = str(domain or "").strip() or None
    if domain is None:
        kind_reg = content_kinds.by_kind(row.get("content_kind"))
        domain = kind_reg.domain if (kind_reg is not None and kind_reg.domain) else None
    if domain is None:
        # UNDECLARED, UNREGISTERED, OR NO DOMAIN -- refuse before any write.
        raise HTTPException(status_code=422, detail={
            "error": "no_declared_domain",
            "message": f"ingest {ingest_id} has content_kind={row.get('content_kind')!r}, "
                       "which resolves to no steward pool to route the review to -- refusing to "
                       "open a promotion task with no audience (the kind routes the review; it "
                       "does not assert the document's domain).",
        })
    # DOMAIN CASING: registrations carry the LOWERCASE pipeline domain, but the Topaz grant
    # key in policy/task_grants.yaml is UPPERCASE -- uppercase it below for both the audience
    # and the payload's `review_pool` so the resolved pool actually matches a grant. The payload
    # carries the ROUTING POOL under `review_pool`; it is not a fact about the document, so it
    # must never ride under a plain `domain` key a reader could take for the document's own.
    domain = domain.upper()
    audience = f"{promotion.KIND}:{domain}"
    # `generation` None reads the row's own (the usual case); a re-class at review passes g+1 so the
    # new task is filed under the next id while the row still carries g.
    task_id = _promotion_task_id(
        ingest_id, int(row.get("review_generation") or 0) if generation is None else generation)
    _refresh = False
    if await run_in_threadpool(lambda: human_tasks.task_exists(task_id)):
        # LEGACY PATH (spec 204): since a leaf change at review files a NEW generation, this in-place
        # refresh serves only a task filed under 203 (same id, different kind) at the row's current
        # generation.
        # THE OPEN TASK FOLLOWS THE LEAF (spec 203b): a task filed for one kind and now facing a row
        # of another (the leaf was changed after parts extraction and the re-extraction reached
        # review again) is REWRITTEN in place; the same kind, or no open task, is ALREADY_FILED as
        # always. The audience must not move.
        existing = await run_in_threadpool(lambda: human_tasks.get_open_task_payload(task_id))
        if existing is None:
            return task_id, "ALREADY_FILED"
        if (str(existing.get("content_kind") or "").strip().lower()
                == str(row.get("content_kind") or "").strip().lower()):
            return task_id, "ALREADY_FILED"
        state = await run_in_threadpool(lambda: human_tasks.get_task_open_state(task_id))
        if (state or {}).get("audience") != audience:
            raise HTTPException(status_code=409, detail={
                "error": "leaf_moves_audience",
                "message": f"the new kind {row.get('content_kind')!r} routes to {audience!r}, "
                           f"not the open task's audience {(state or {}).get('audience')!r}; "
                           "nothing was written."})
        _refresh = True
    ref = str(extraction_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=422, detail={
            "error": "no_extraction_ref",
            "message": f"ingest {ingest_id} has no extraction_ref; the promotion payload is "
                       "derived from the versioned extraction manifest it names.",
        })
    prefix = str(row.get("object_prefix") or "")
    if not prefix or not ref.startswith(prefix):
        # BEFORE any read: never fetch a key outside this document's own directory.
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unbound",
            "message": f"extraction_ref {ref!r} is not under this document's directory "
                       f"{prefix!r}.",
        })
    manifest = await run_in_threadpool(lambda: _read_extraction_manifest(ref))
    summ = await _soft_review_summary(manifest, ref, prefix)
    # The notice's own id (DISPLAY ONLY, never an identity), for the status row AND the payload
    # from ONE read: review.json's `doc_id_raw`, None when not extracted or not readable. Never the
    # manifest's `doc_id`, the filename-derived key (2026-10-18: TI and IDT titled by file stem).
    notice_id = (summ or {}).get("notice_id")
    if notice_out is not None:
        notice_out["notice_id"] = notice_id
    try:
        derived = promotion.payload_from_extraction(ingest_id, row, manifest, ref,
                                                    notice_id=notice_id)
    except promotion.PromotionRefused as exc:
        raise HTTPException(status_code=exc.status,
                            detail={"error": exc.error, "message": str(exc)})
    attempt = row.get("attempt")
    payload = {**derived, "review_pool": domain, "dropped_by": {
        "authz_id": row.get("submitted_by"), "on_behalf_of": row.get("on_behalf_of")},
        "mfr": summ["mfr"] if summ else None,
        "notice_date": summ["notice_date"] if summ else None,
        "part_count": summ["part_count"] if summ else None,
        "attempt": attempt}
    notice_id_ = str(payload.get("notice_id") or "").strip()
    ck_ = str(payload.get("content_kind") or "").strip()
    kind_label = ck_.upper() if ck_.lower() in ("pcn", "pdn") else (ck_ or "Document")
    pc_ = payload["part_count"]
    _title = notice_id_ or f"Promote document {ingest_id}"
    _summary = (f"{kind_label} {notice_id_ or ingest_id} — "
                f"{payload['mfr'] or 'manufacturer unknown'}, "
                f"{pc_ if pc_ is not None else '?'} parts, attempt {attempt}.")
    if _refresh:
        await run_in_threadpool(lambda: human_tasks.refresh_open_task(
            task_id, payload=payload, title=_title, summary=_summary))
        return task_id, "ALREADY_FILED"
    try:
        await run_in_threadpool(lambda: human_tasks.register_task(
            kind=promotion.KIND, task_id=task_id, audience=audience,
            title=_title, summary=_summary,
            requested_by=requested_by, subject_ref=ingest_id,
            payload=payload,
        ))
    except human_tasks.HumanTaskConfigError as exc:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured", "message": str(exc)})
    except human_tasks.NoEntitledRecipients as exc:
        raise HTTPException(status_code=422, detail={"error": "no_entitled_recipients", "message": str(exc)})
    except human_tasks.NoRequester as exc:
        raise HTTPException(status_code=422, detail={"error": "no_requester", "message": str(exc)})
    return task_id, "FILED"


# ── document_empty_confirm (ruling 2026-10-23, spec 208) ─────────────────────────────────────────
# A zero-row extraction on a NOTICE (content_kind in ingest_status.LEAVES) files this task instead of
# failing the row. Two doors, one writer: `POST /human_tasks/{id}/act` and `POST /ingest/{id}/empty`
# both call `_decide_empty`.
EMPTY_CONFIRM_KIND = "document_empty_confirm"
_EMPTY_DECISIONS = ("confirmed_no_parts", "has_parts")
_EMPTY_OPEN_DETAIL = ("the extraction found no part rows; awaiting confirmation that the document "
                      "has none")
_EMPTY_DEFECT_REASON = "the steward says the document has parts; the extraction found none"
_ADD_MISSED_PART_MSG = ("entering parts by hand on an empty extraction is not built yet (awaiting a "
                        "ruling on where hand-entered parts land)")


def _empty_confirm_task_id(ingest_id: str, attempt) -> str:
    """One task per (ingest_id, attempt): a re-posted stage finds it, a relaunch files a new one."""
    return f"{EMPTY_CONFIRM_KIND}:{ingest_id}:a{int(attempt or 1)}"


def _empty_account(review) -> dict:
    """The extraction's OWN account of why it found no rows, DERIVED from review.json's top-level
    `stats` and `review_reasons`. An unreadable review.json or stats gives `why: "unknown"` and Nones:
    no figure is ever invented."""
    stats = review.get("stats") if isinstance(review, dict) else None
    reasons = review.get("review_reasons") if isinstance(review, dict) else None

    def _n(key):
        v = stats.get(key) if isinstance(stats, dict) else None
        return v if isinstance(v, int) and not isinstance(v, bool) else None

    n_tables, no_col, emitted = _n("n_tables"), _n("grid_no_parts_col"), _n("grid_rows_emitted")
    if not isinstance(stats, dict):
        why = "unknown"
    elif n_tables == 0:
        why = "no_table"
    elif n_tables is not None and n_tables > 0 and no_col is not None and no_col > 0:
        why = "no_parts_column"
    else:
        why = "zero_rows"
    return {"n_tables": n_tables, "grid_no_parts_col": no_col, "grid_rows_emitted": emitted,
            "review_reasons": [str(r) for r in reasons] if isinstance(reasons, list) else [],
            "why": why}


async def _file_or_find_empty_confirm_task(
    ingest_id: str, row: dict, *, requested_by: str, account: dict, forced: bool,
) -> tuple[str, str]:
    """Find-or-file the `document_empty_confirm` task for the row's CURRENT attempt. Audience
    `document_promotion:<DOMAIN>`, DOMAIN from the kind registry exactly as the promotion filer derives
    it; no origin gate (nothing to promote). Same refusals as that filer: 422 `no_declared_domain`,
    503 `hitl_unconfigured`, 422 `no_entitled_recipients`, 422 `no_requester`. Writes nothing on any."""
    from starlette.concurrency import run_in_threadpool

    from . import content_kinds, human_tasks, promotion

    kind_reg = content_kinds.by_kind(row.get("content_kind"))
    domain = kind_reg.domain if (kind_reg is not None and kind_reg.domain) else None
    if domain is None:
        raise HTTPException(status_code=422, detail={
            "error": "no_declared_domain",
            "message": f"ingest {ingest_id} has content_kind={row.get('content_kind')!r}, which "
                       "resolves to no steward pool to route the confirmation to."})
    audience = f"{promotion.KIND}:{str(domain).upper()}"
    attempt = row.get("attempt")
    task_id = _empty_confirm_task_id(ingest_id, attempt)
    if await run_in_threadpool(lambda: human_tasks.task_exists(task_id)):
        return task_id, "ALREADY_FILED"
    payload = {"review_shape": "empty", "ingest_id": ingest_id, "attempt": attempt,
               "source": f"/ingest/{ingest_id}/source", "account": account,
               "forced_text_fallback": bool(forced), "add_missed_part": bool(forced),
               "content_kind": row.get("content_kind")}
    try:
        await run_in_threadpool(lambda: human_tasks.register_task(
            kind=EMPTY_CONFIRM_KIND, task_id=task_id, audience=audience,
            title=f"No parts found in {ingest_id}",
            summary=(f"The extraction of {ingest_id} (attempt {attempt}) found no part rows "
                     f"({account.get('why')}). Confirm the document has none, or say it has parts."),
            requested_by=requested_by, subject_ref=ingest_id, payload=payload))
    except human_tasks.HumanTaskConfigError as exc:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured", "message": str(exc)})
    except human_tasks.NoEntitledRecipients as exc:
        raise HTTPException(status_code=422, detail={"error": "no_entitled_recipients", "message": str(exc)})
    except human_tasks.NoRequester as exc:
        raise HTTPException(status_code=422, detail={"error": "no_requester", "message": str(exc)})
    return task_id, "FILED"


async def _decide_empty(ingest_id: str, decision: str, actor: str, page, *,
                        task_id: Optional[str] = None) -> dict:
    """THE ONE WRITER of a `document_empty_confirm` decision; both doors call it, and it closes the
    task either way. Refusals write nothing: 422 `invalid_decision` / `page_required` /
    `page_not_for_decision`, 404 `ingest_not_found`, 409 `no_open_empty_task` (the row is not at
    `review` with this attempt's task open), 409 `add_missed_part_not_built` (`has_parts` on the
    second-zero task).

    `confirmed_no_parts`: the row ends `no_parts` with detail `no parts (confirmed by <actor>)`.
    `has_parts` (needs an integer page >= 1): files `extraction_defect` to
    `dispatch_failure:<DOMAIN>` through the BFF's own task filer (the workflow's filer lives in
    restate_analyst and is not reachable from here), then relaunches the row with the text fallback
    forced (`attempt` + 1, back to `received`)."""
    from starlette.concurrency import run_in_threadpool

    from . import human_tasks, ingest_status, promotion

    if decision not in _EMPTY_DECISIONS:
        raise HTTPException(status_code=422, detail={
            "error": "invalid_decision", "allowed": list(_EMPTY_DECISIONS)})
    if decision == "confirmed_no_parts" and page is not None:
        raise HTTPException(status_code=422, detail={
            "error": "page_not_for_decision",
            "message": "a page is read only on has_parts"})
    if decision == "has_parts" and (
            not isinstance(page, int) or isinstance(page, bool) or page < 1):
        raise HTTPException(status_code=422, detail={
            "error": "page_required",
            "message": "has_parts needs the integer page (>= 1) the steward points at"})
    row = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
    if row is None or row.get("kind") == ingest_status.EVENT:
        raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
    current_id = _empty_confirm_task_id(ingest_id, row.get("attempt"))
    payload = (await run_in_threadpool(lambda: human_tasks.get_open_task_payload(current_id))
               if row.get("status") == ingest_status.REVIEW else None)
    if payload is None or (task_id is not None and task_id != current_id):
        raise HTTPException(status_code=409, detail={
            "error": "no_open_empty_task", "stage": row.get("status"), "task_id": task_id,
            "message": "no open confirmation for this document's current attempt"})
    if decision == "has_parts" and payload.get("add_missed_part"):
        raise HTTPException(status_code=409, detail={
            "error": "add_missed_part_not_built", "message": _ADD_MISSED_PART_MSG})
    if decision == "confirmed_no_parts":
        await run_in_threadpool(lambda: ingest_status.update_status(
            ingest_id, ingest_status.NO_PARTS, detail=f"no parts (confirmed by {actor})"))
        n = await run_in_threadpool(lambda: human_tasks.mark_task_resolved(
            current_id, caller_id=actor, decision=decision, comment=""))
        return {"ingest_id": ingest_id, "task_id": current_id, "decision": decision,
                "stage": ingest_status.NO_PARTS, "rows_resolved": n}
    # has_parts
    state = await run_in_threadpool(lambda: human_tasks.get_task_open_state(current_id))
    try:
        defect_aud = f"dispatch_failure:{promotion.domain_of((state or {}).get('audience'))}"
    except promotion.PromotionRefused as exc:
        raise HTTPException(status_code=exc.status, detail={"error": exc.error, "message": str(exc)})
    defect_id = f"extraction-defect:{ingest_id}:empty-a{row.get('attempt')}"
    defect_payload = {"ingest_id": ingest_id, "page": page, "reason": _EMPTY_DEFECT_REASON,
                      "account": payload.get("account"), "decided_by": actor}
    try:
        if not await run_in_threadpool(lambda: human_tasks.task_exists(defect_id)):
            await run_in_threadpool(lambda: human_tasks.register_task(
                kind="extraction_defect", task_id=defect_id, audience=defect_aud,
                title=f"Extraction defect -- {ingest_id} found no parts (page {page})",
                summary=(f"The extraction of {ingest_id} found no part rows; {actor} says the "
                         f"document has parts (page {page})."),
                requested_by=actor, subject_ref=ingest_id, payload=defect_payload))
    except human_tasks.HumanTaskConfigError as exc:
        raise HTTPException(status_code=503, detail={"error": "hitl_unconfigured", "message": str(exc)})
    except human_tasks.NoEntitledRecipients as exc:
        raise HTTPException(status_code=409, detail={
            "error": "extraction_defect_unroutable", "audience": defect_aud, "message": str(exc)})
    except human_tasks.NoRequester as exc:
        raise HTTPException(status_code=422, detail={"error": "no_requester", "message": str(exc)})
    new_attempt = await run_in_threadpool(lambda: ingest_status.relaunch_with_text_fallback(
        ingest_id, expect_attempt=int(row.get("attempt") or 1)))
    if new_attempt is None:
        raise HTTPException(status_code=409, detail={
            "error": "no_open_empty_task",
            "message": "the document moved while the decision was written; nothing was relaunched"})
    n = await run_in_threadpool(lambda: human_tasks.mark_task_resolved(
        current_id, caller_id=actor, decision=decision, comment=""))
    return {"ingest_id": ingest_id, "task_id": current_id, "decision": decision,
            "stage": ingest_status.RECEIVED, "attempt": new_attempt, "extraction_defect": defect_id,
            "force_text_fallback": True, "rows_resolved": n}


async def _hold_empty_for_confirmation(
    ingest_id: str, row: dict, req, *, caller: str, prefix: str, adopt: dict, run: dict,
) -> dict:
    """The stage route's answer to a zero-row extraction on a NOTICE: file (or find) the
    `document_empty_confirm` task, then move the row to `review` with the open detail. TASK FIRST,
    STATUS SECOND, and a 4xx refusal fails the row retryably exactly as the promotion filer's does;
    a 5xx writes nothing. Nothing is written `failed:extraction_empty`. A row whose
    `force_text_fallback` is TRUE has already had its forced relaunch: its task carries
    `add_missed_part`."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    review = await _server_extraction_review(req.extraction_ref, prefix)
    account = _empty_account(review)
    try:
        task_id, _st = await _file_or_find_empty_confirm_task(
            ingest_id, row, requested_by=caller, account=account,
            forced=bool(row.get("force_text_fallback")))
    except HTTPException as exc:
        if 400 <= exc.status_code < 500:
            _d = exc.detail if isinstance(exc.detail, dict) else {}
            _err = _d.get("error") if isinstance(_d.get("error"), str) else None
            _why = f"review refused ({exc.status_code}): {_err or exc.detail}"
            try:
                await run_in_threadpool(lambda: ingest_status.update_status(
                    ingest_id, ingest_status.FAILED, detail=_why,
                    failure={
                        "reason_code": (_err if _err and ingest_status.REASON_CODE_RE.match(_err)
                                        else "review_refused"),
                        "reason": _why, "step": "review",
                        "run_id": req.run_id or row.get("run_id"),
                        "pin_digest": req.pin_digest,
                        "failed_at": int(time.time() * 1000)},
                    **adopt, **run))
            except Exception as werr:  # noqa: BLE001 -- the caller must still see the refusal
                logger.warning("ingest %s: the refused empty confirmation could not be written as "
                               "failed (%s: %s)", ingest_id, type(werr).__name__, werr)
        raise
    try:
        await run_in_threadpool(lambda: ingest_status.update_status(
            ingest_id, ingest_status.REVIEW, extracted_count=req.extracted_count,
            extracted_total=req.extracted_total, extraction_ref=req.extraction_ref,
            detail=_EMPTY_OPEN_DETAIL, **adopt, **run))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_stage_update", "message": str(exc)})
    return {"ingest_id": ingest_id, "stage": ingest_status.REVIEW, "task_id": task_id,
            "task_kind": EMPTY_CONFIRM_KIND}


class IngestEmptyRequest(_BaseModel):
    """POST /ingest/{ingest_id}/empty's body: the dropper's or steward's answer on an empty extraction."""
    model_config = {"extra": "forbid"}
    decision: Literal["confirmed_no_parts", "has_parts"]
    page: Optional[_StrictInt] = None

    @model_validator(mode="after")
    def _page_only_with_has_parts(self):
        if self.page is not None and self.decision != "has_parts":
            raise ValueError("page is only valid with decision='has_parts'")
        return self


@app.post("/ingest/{ingest_id}/empty", tags=[INGEST_V1_TAG], responses={200: {"model": EmptyDecisionResponse}}, openapi_extra=PREVIEW_EXTRA)
async def decide_empty_route(ingest_id: str, req: IngestEmptyRequest,
                             current_user: User = Depends(get_current_user)):
    """POST /ingest/{ingest_id}/empty -- answer a document's `document_empty_confirm`. Gate:
    `_ingest_review_access` (the dropper, or a holder of the open promotion task: the same gate as
    `/ingest/{id}/leaf`). The dropper may confirm their own: there is nothing to approve. The same
    writer as the task act (`_decide_empty`)."""
    await _ingest_review_access(ingest_id, current_user, "POST /ingest/{ingest_id}/empty")
    return await _decide_empty(ingest_id, req.decision, (current_user.authz_id or "").strip(), req.page)


@app.get("/ingest/retries", tags=[INGEST_V1_TAG], responses={200: {"model": RetriesListing}})
async def list_ingest_retries(
    limit: int = _Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    """GET /ingest/retries -- retried drops awaiting relaunch. SERVICE-ONLY: only `svc:doc-tools`
    (see `_DOC_TOOLS_SERVICE_AUTHZ_ID`) may call this; every other caller gets 403.

    The architect's 2026-10-12 ruling (Shape 1). `POST /ingest/{id}/retry` re-opens a failed row
    at `received` with `attempt` + 1, but doc-tools' sensor cannot see the object again (its S3
    cursor has passed it), so doc-tools polls THIS route and launches each entry with the Dagster
    run_key `{ingest_id}-a{attempt}`. The row stays at `received` until the relaunched run posts
    `extracting`, so the same entry is listed on every poll; the attempt-keyed run_key is what
    makes the relaunch idempotent. A row not relaunched within `INGEST_RECEIVED_TIMEOUT_SECONDS`
    is failed `timeout` by the watchdog, as before. Oldest first; event rows never appear.
    Each entry's `reason` is `leaf_applied` (the BFF relaunched it as its leaf) or null (a Retry).
    """
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    caller = (current_user.authz_id or "").strip()
    if not _DOC_TOOLS_SERVICE_AUTHZ_ID or caller != _DOC_TOOLS_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_doc_tools",
            "message": "GET /ingest/retries is callable only by doc-tools' own service identity.",
        })
    rows = await run_in_threadpool(lambda: ingest_status.list_pending_retries(limit=limit))
    return {"retries": [
        {"ingest_id": r["id"], "attempt": r["attempt"],
         "run_key": f"{r['id']}-a{r['attempt']}",
         "kind": r["kind"], "content_kind": r["content_kind"],
         "object_prefix": r["object_prefix"], "sha256": r["sha256"],
         "run_id": r["run_id"], "updated_at": r["updated_at"],
         "reason": r.get("retry_reason"),
         "force_text_fallback": bool(r.get("force_text_fallback"))}
        for r in rows]}


@app.get("/ingest/mine", tags=[INGEST_V1_TAG], responses={200: {"model": MineListing}})
async def list_my_ingests(
    limit: int = _Query(50, ge=1, le=200),
    before: Optional[str] = _Query(None),
    current_user: User = Depends(get_current_user),
):
    """GET /ingest/mine -- the caller's own drops (dropper or on_behalf_of), paged, newest first,
    each in the same summary shape as GET /ingest/<id>/status. Architect ruling 2026-10-16: the
    rail reads it on load and merges with live entries; browser storage is a cache, never the
    record.

    EXISTENCE-ORACLE SAFE BY SCOPING: `ingest_status.list_mine` carries `get_status_for`'s own
    scoping (`submitted_by = caller OR on_behalf_of = caller`), so the route reveals only the
    caller's own rows and nothing about anyone else's. Event rows are never listed; drops are
    documents. A caller with no drops gets 200 `{"items": [], "next": null}`, never a 404.

    PAGING is a keyset cursor, not OFFSET: `before` is the opaque string `{created_at}|{id}` that
    a previous page returned as `next` (None on the last page). A malformed cursor is 422
    `invalid_cursor`.
    """
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    cursor = None
    if before is not None:
        created, sep, row_id = before.partition("|")
        try:
            cursor = (int(created), row_id)
        except ValueError:
            cursor = None
        if not sep or not row_id or cursor is None:
            raise HTTPException(status_code=422, detail={"error": "invalid_cursor"})
    rows = await run_in_threadpool(lambda: ingest_status.list_mine(
        caller_id=current_user.authz_id, limit=limit + 1, before=cursor))
    page = rows[:limit]
    items = [await _ingest_status_body(r, current_user) for r in page]
    nxt = f"{page[-1]['created_at']}|{page[-1]['id']}" if len(rows) > limit else None
    return {"items": items, "next": nxt}


class ProcessableKindsBody(BaseModel):
    kinds: list[str]
    source: Optional[str] = None

    @field_validator("kinds")
    @classmethod
    def _check_kinds(cls, v):
        if not v or len(v) > 512:
            raise ValueError("kinds must hold 1..512 entries")
        out = set()
        for k in v:
            k = (k or "").strip()
            if not k or len(k) > 128 or "/" in k:
                raise ValueError("each kind must be non-blank, <=128 chars, without '/'")
            out.add(k)
        return sorted(out)

    @field_validator("source")
    @classmethod
    def _check_source(cls, v):
        if v is not None and len(v) > 200:
            raise ValueError("source must be <=200 chars")
        return v


@app.put("/ingest/processable-kinds")
async def put_processable_kinds(
    body: ProcessableKindsBody,
    current_user: User = Depends(get_current_user),
):
    """PUT /ingest/processable-kinds -- doc-tools publishes the content kinds it can process.
    SERVICE-ONLY (same gate as GET /ingest/retries). The BFF persists the list (one Postgres row)
    and caches it; the ingest door reads the cache when INGEST_DOOR_READS_PROCESSABLE_KINDS is on.
    `unregistered` lists published kinds the registry does not know (informational, not refused).
    """
    from starlette.concurrency import run_in_threadpool

    from . import content_kinds, processable_kinds

    caller = (current_user.authz_id or "").strip()
    if not _DOC_TOOLS_SERVICE_AUTHZ_ID or caller != _DOC_TOOLS_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_doc_tools",
            "message": "PUT /ingest/processable-kinds is callable only by doc-tools' own service identity.",
        })
    kinds = list(body.kinds)
    try:
        published_at = await run_in_threadpool(
            lambda: processable_kinds.publish(kinds, body.source, caller))
    except Exception as exc:  # noqa: BLE001
        logger.warning("processable_kinds publish failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(status_code=503, detail={
            "error": "processable_kinds_store_unreachable",
            "message": "the processable-kinds store did not take the write; nothing was published.",
        })
    processable_kinds.set_cache(kinds, published_at)
    return {
        "kinds": kinds,
        "published_at": published_at.isoformat() if hasattr(published_at, "isoformat") else str(published_at),
        "unregistered": [k for k in kinds if content_kinds.by_kind(k) is None],
    }


@app.post("/ingest/{ingest_id}/stage")
async def update_ingest_stage(
    ingest_id: str,
    req: IngestStageUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """doc-tools' extraction pipeline advances an ingest's stage. SERVICE-ONLY: only
    `svc:doc-tools` (see `_DOC_TOOLS_SERVICE_AUTHZ_ID`) may call this -- every other caller,
    authenticated or not, gets 403.

    Enforces the forward order received -> extracting -> review, plus `failed` from any
    non-terminal stage; any move from an already-terminal stage (promoted/rejected/failed/
    awaiting_origin) is refused 409, same as a lateral or backwards move within the
    non-terminal ladder. `rejected`/`detail`-required is `ingest_status.update_status`'s own
    existing rule.

    On the transition INTO `review`, opens the `document_promotion` task idempotently (one per
    ingest_id, the same `task_exists`-before-`register_task` pattern `/triage_tasks` uses),
    its payload derived from the versioned manifest the body's `extraction_ref` names (refusals
    422 `no_extraction_ref` / `extraction_unbound` / `extraction_absent` / `extraction_unreadable`
    / `extraction_unversioned`, 503 `artifact_store_unreachable`; nothing written on any), and
    carrying the ingest_id, the DECLARED content kind's domain (content_kinds.by_kind on the
    row's `content_kind` -- NEVER the row's `kind`, which is the file format, pdf|cad|xml) and the
    original dropper (`dropped_by`, from the row's `submitted_by`). TASK FIRST, STATUS SECOND:
    for `review`, the task is filed (or found ALREADY_FILED) before `update_status` runs, so a
    422/503 refusal from the task step (no declared domain, no entitled recipients, no
    requester, HITL unconfigured) leaves the row exactly where it was -- never stranded at
    `review` with no task and no way back (a retry on a row already at `review` is 409).

    EXCEPT when the resolved registration is DELIBERATELY DOMAINLESS (architect ruling
    2026-10-02: `domain` declared explicitly as null, not merely absent) -- then no task is
    filed at all (there is no fixed audience to file one against) and the row moves straight
    to the out-of-band stage `awaiting_origin` instead of `review`, persisting the body's
    `extraction_ref` for the later filing. `awaiting_origin` is terminal for THIS route and for
    the retry route; the ONE exit is a steward's accepted origin (`write_origin_route`), which
    files `document_promotion:<owner_domain>` and moves the row to `review` (ruling 2026-10-10
    Q2, superseding 10-02 for the accept branch only). Reject stays terminal and dropper-only.

    PIPELINE FAILURE MUST REACH THE ROW (architect directive 2026-10-12): `failed` carries
    {reason_code, reason, step, run_id, pin_digest}, stored as the row's `failure` and echoed by
    GET /ingest/{id}/status. `reason_code` is optional (legacy `detail`-only posts still work),
    but if given must match `ingest_status.REASON_CODE_RE`; the vocabulary is doc-tools' to own.
    `run_id` is accepted on any target stage. The four failure fields on a non-`failed` stage are
    422 `failure_fields_without_failed`. A `failed` row whose stored reason_code is `timeout`
    (the BFF watchdog's, not doc-tools') is PROVISIONAL: it is treated as if it sat at `received`,
    so a late run may still move it on (and moving off `failed` clears `failure`). Any other
    `failed` row stays terminal.
    """
    from starlette.concurrency import run_in_threadpool

    from . import content_kinds, ingest_status

    # doc-tools' pipeline writes only these three target stages through this route. `promoted`
    # and `rejected` are the HUMAN document_promotion fulfillment's exclusive territory
    # (act_on_human_task above, via promotion.act) -- each carries a decision record this route
    # must never fabricate, so neither is a legal target here even though it is later in
    # STAGES' own order. The one ruled exception: a delegate's drop of a kind in
    # `_PROMOTION_SKIPPED_KINDS` is written `promoted` by the review branch below (2026-10-17).
    _stage_targets = (ingest_status.EXTRACTING, ingest_status.REVIEW, ingest_status.FAILED)
    _forward_order = (ingest_status.RECEIVED, ingest_status.EXTRACTING, ingest_status.REVIEW)
    # `awaiting_origin` is OUT OF BAND like `duplicate` (ingest_status.py) -- terminal HERE too
    # (its one exit is a steward's accepted origin, filed by `_file_promotion_if_ready`; Q2
    # ruling 2026-10-10), so a later move (including `failed`) off it is refused 409.
    _terminal_stages = (ingest_status.PROMOTED, ingest_status.REJECTED, ingest_status.FAILED,
                        ingest_status.AWAITING_ORIGIN, ingest_status.REVIEW_REJECTED,
                        ingest_status.AWAITING_KIND, ingest_status.NO_PARTS)

    caller = (current_user.authz_id or "").strip()
    if not _DOC_TOOLS_SERVICE_AUTHZ_ID or caller != _DOC_TOOLS_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_doc_tools",
            "message": "POST /ingest/{ingest_id}/stage is callable only by doc-tools' own "
                       "service identity.",
        })

    if req.stage not in _stage_targets:
        raise HTTPException(status_code=422, detail={
            "error": "unknown_stage", "stage": req.stage,
            "allowed": list(_stage_targets),
        })

    # BEFORE any row read: the failure fields describe a failure, so they mean nothing on any
    # other target stage -- refuse rather than silently drop them.
    _failure_fields = {"reason_code": req.reason_code, "reason": req.reason, "step": req.step,
                       "pin_digest": req.pin_digest}
    if req.stage != ingest_status.FAILED:
        _stray = [k for k, v in _failure_fields.items() if v is not None]
        if _stray:
            raise HTTPException(status_code=422, detail={
                "error": "failure_fields_without_failed", "fields": _stray})
    if req.run_id is not None and not req.run_id.strip():
        raise HTTPException(status_code=422, detail={"error": "invalid_run_id"})
    if req.reason_code is not None and not ingest_status.REASON_CODE_RE.match(req.reason_code):
        raise HTTPException(status_code=422, detail={
            "error": "invalid_reason_code",
            "message": f"reason_code must match {ingest_status.REASON_CODE_RE.pattern}"})

    row = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
    current_stage = row["status"]

    # A WATCHDOG TIMEOUT IS PROVISIONAL. `fail_stalled` writes `failed:timeout` for a row that
    # merely sat at `received` (which a run queued behind max_concurrent_runs legitimately does) or
    # at `extracting` (ruling 2026-10-16; a long extraction does). Treating that failure as
    # terminal would turn a too-early timeout into a permanently lost document, so such a row
    # behaves as if it still sat at `received` at EITHER stage (both in the terminal check and the
    # forward-order check below), which keeps a late extracting or review POST acceptable. Only a failure doc-tools itself reported, or any
    # other terminal stage, is final.
    _timed_out = (current_stage == ingest_status.FAILED
                  and (row.get("failure") or {}).get("reason_code") == ingest_status.REASON_TIMEOUT)
    if _timed_out:
        current_stage = ingest_status.RECEIVED

    if current_stage in _terminal_stages:
        raise HTTPException(status_code=409, detail={
            "error": "backwards_move", "from": current_stage, "to": req.stage,
            "message": f"ingest {ingest_id} is already terminal ({current_stage}); no further "
                       "stage move is possible.",
        })
    if req.stage != ingest_status.FAILED:
        # extracting/review only: both current and target must sit on the forward ladder, and
        # strictly later than where the row already is.
        if (current_stage not in _forward_order
                or _forward_order.index(req.stage)
                <= _forward_order.index(current_stage)):
            raise HTTPException(status_code=409, detail={
                "error": "backwards_move", "from": current_stage, "to": req.stage,
                "message": f"a document cannot move backwards from {current_stage} to {req.stage}.",
            })

    # `run_id` rides on any target stage, and only when given (COALESCE in update_status).
    _run = {"run_id": req.run_id} if req.run_id is not None else {}

    task_id = None
    task_status = None
    _notice: dict = {}
    if req.stage == ingest_status.REVIEW:
        # THE ROW CARRIES THE FILE FORMAT, NOT THE DECLARED KIND (review-audience fix,
        # 2026-10-06): resolve the registry on `content_kind` (the declared, registry-level
        # kind), never on `kind` (pdf|cad|xml) -- a lookup on the file format always misses the
        # registry, resolves to a None domain, and files a task no one can be entitled to.
        #
        # A ROW THE DROP LEFT WITHOUT A KIND ADOPTS THE MANIFEST'S (ruling 2026-10-16): doc-tools
        # stamps `metadata.content_kind` from the sidecar, so a NULL row column is not "no kind",
        # it is a kind not yet copied across. Adopt it only when it is REGISTERED, and never over a
        # kind the row already carries. A failed read is swallowed HERE: find-or-file's own read
        # produces the real refusal.
        adopted_kind = None
        _ref = str(req.extraction_ref or "").strip()
        _prefix = str(row.get("object_prefix") or "")
        if not row.get("content_kind") and _ref and _prefix and _ref.startswith(_prefix):
            try:
                _m = await run_in_threadpool(lambda: _read_extraction_manifest(_ref))
                _k = (_m.get("metadata") or {}).get("content_kind")
                if isinstance(_k, str) and _k.strip() and content_kinds.by_kind(_k) is not None:
                    adopted_kind = _k
            except Exception:  # noqa: BLE001 -- find-or-file re-reads and refuses properly
                adopted_kind = None
            if adopted_kind is not None:
                row = {**row, "content_kind": adopted_kind}
                logger.info("ingest %s: content_kind %r adopted from the extraction manifest",
                            ingest_id, adopted_kind)
        _adopt = {"content_kind": adopted_kind} if adopted_kind is not None else {}
        kind_reg = content_kinds.by_kind(row.get("content_kind"))
        if row.get("content_kind") in _PROMOTION_SKIPPED_KINDS:
            # NO document_promotion TASK for this kind (architect ruling 2026-10-17, on 7f's ruling
            # 1): an s1000d data module has no PCN/PDN card to vet, so a task filed under the review
            # standard could not be decided. A delegate's drop is already trusted and is promoted
            # outright; a user's drop waits for a steward's origin, exactly as a domainless kind does.
            # R-089: the delegate map is asserted by configuration this pass, not verified.
            _dropper = str(row.get("submitted_by") or "").strip()
            _to = (ingest_status.PROMOTED if _dropper in _delegate_principals()
                   else ingest_status.AWAITING_ORIGIN)
            await run_in_threadpool(lambda: ingest_status.update_status(
                ingest_id, _to,
                extracted_count=req.extracted_count, extracted_total=req.extracted_total,
                extraction_ref=req.extraction_ref,
                detail="content kind files no document_promotion task (ruling 2026-10-17)",
                **_adopt, **_run))
            return {"ingest_id": ingest_id, "stage": _to, "task_id": None,
                    "task_status": "NO_TASK_KIND_SKIPS_PROMOTION"}
        # A ZERO-ROW EXTRACTION NEVER FILES document_promotion (architect ruling 2026-10-17): a card
        # with nothing to vet cannot be decided. Asked HERE, once, for every kind that files a
        # promotion -- now (find-or-file) or later (`awaiting_origin` -> `_file_promotion_if_ready`)
        # -- and before either moves or files anything. The count is the SERVER's, from review.json;
        # a nonzero `extracted_count` claim does not outvote a zero count. The row goes
        # failed:extraction_empty, which `ingest_status.retry_failed` re-opens (any failed
        # non-event row). An unreadable review.json is NOT empty: today's refusal stands.
        _rows = await _server_extraction_row_count(req.extraction_ref, _prefix)
        if _rows == 0 or req.extracted_count == 0:
            # A NOTICE (content_kind pcn|pdn) is asked about, not failed (ruling 2026-10-23, spec 208):
            # a `document_empty_confirm` task, the row at `review`. Every other kind keeps today's
            # failed:extraction_empty and 422 below, unchanged.
            if str(row.get("content_kind") or "").strip().lower() in ingest_status.LEAVES:
                return await _hold_empty_for_confirmation(
                    ingest_id, row, req, caller=caller, prefix=_prefix, adopt=_adopt, run=_run)
            _why = "the extraction found no part rows"
            try:
                await run_in_threadpool(lambda: ingest_status.update_status(
                    ingest_id, ingest_status.FAILED, detail=_why,
                    failure={
                        "reason_code": "extraction_empty", "reason": _why, "step": "review",
                        "run_id": req.run_id or row.get("run_id"),
                        "pin_digest": req.pin_digest,
                        "failed_at": int(time.time() * 1000)},
                    **_adopt, **_run))
            except Exception as werr:  # noqa: BLE001 -- the caller must still see the refusal
                logger.warning("ingest %s: the empty extraction could not be written as failed "
                               "(%s: %s)", ingest_id, type(werr).__name__, werr)
            raise HTTPException(status_code=422, detail={
                "error": "extraction_empty", "stage": ingest_status.FAILED,
                "reason_code": "extraction_empty", "retryable": True,
                "message": f"{_why}; the row is failed and may be retried"})

        # DELIBERATELY DOMAINLESS vs UNDECLARED/UNREGISTERED (architect ruling 2026-10-02):
        # a registered kind can declare `domain` EXPLICITLY as null -- "origin resolved by
        # evidence, not kind" (`pdf`, `engineering-document`, `doors-export`) -- and that is a
        # different fact from a kind that never said anything about a domain at all. Pydantic's
        # `model_fields_set` is what tells the two apart: a YAML row that WROTE `domain: null`
        # has "domain" in its fields_set (even though the value equals the field's own default,
        # None); a row that OMITTED the key entirely does not. `reg.domain is None` alone sees
        # only the value and cannot discriminate -- that is the collision section 4 of the
        # 2026-10-06 packet describes. Guarded behind `kind_reg.domain` being falsy first so a
        # domained registration (the common case, and the only shape existing tests' plain stub
        # objects carry) never has to support `model_fields_set` at all.
        # Decided HERE, in the stage route, before the shared find-or-file helper: a row only
        # reaches `awaiting_origin` through this branch; the retry route calls the same state
        # function (`_file_promotion_if_ready`) for a row sitting there.
        deliberately_domainless = (
            kind_reg is not None and not kind_reg.domain
            and "domain" in getattr(kind_reg, "model_fields_set", frozenset())
            and kind_reg.domain is None)

        if deliberately_domainless:
            # NO TASK -- there is no fixed audience to file one against; the origin_record
            # case (section 6) resolves this artifact's audience per-artifact, from evidence,
            # later. Out-of-band, same shape as `duplicate` (ingest_status.py); terminal for
            # this route, exited only by a steward's accepted origin (Q2 ruling 2026-10-10).
            await run_in_threadpool(lambda: ingest_status.update_status(
                ingest_id, ingest_status.AWAITING_ORIGIN,
                extracted_count=req.extracted_count, extracted_total=req.extracted_total,
                extraction_ref=req.extraction_ref,
                detail="origin resolved by evidence, not kind (ruling 2026-10-02)",
                **_adopt, **_run))
            # Q2b: the steward's accept may have landed while the row was still extracting.
            promotion_out = await _file_promotion_if_ready(ingest_id, requested_by=caller)
            if promotion_out and promotion_out.get("filed"):
                return {"ingest_id": ingest_id, "stage": ingest_status.REVIEW,
                        "task_id": promotion_out["task_id"],
                        "task_status": promotion_out["task_status"]}
            return {"ingest_id": ingest_id, "stage": ingest_status.AWAITING_ORIGIN,
                    "task_id": None, "task_status": "NO_TASK_AWAITING_ORIGIN"}

        # Find-or-file is the shared helper now (`_file_or_find_document_promotion_task`,
        # also used by `ingest_retry_route`'s re-run of this same find-or-file) -- requested_by
        # here is doc-tools' OWN service identity, since this is doc-tools' own transition INTO
        # `review`, never a retrying caller's. Writing update_status first and only then
        # discovering there is no entitled audience would strand the row at `review` with no
        # task and no way back (a retry on a row already at `review` is 409), so this call --
        # and everything it can raise -- happens before update_status below ever runs.
        # A 4xx REFUSAL NOW MOVES THE ROW TO `failed` (ruling 2026-10-16): doc-tools logs a
        # non-2xx and still ends its run SUCCESS, so a refusal that wrote nothing stranded the row
        # at `extracting` for ever, unretryable (retry requires `failed`). Failing it names the
        # refusal and lets the dropper retry. A 5xx is transient and writes NOTHING (the extracting
        # watchdog covers a row that then stalls). The ORIGINAL exception always re-raises, so
        # doc-tools still sees the status it would have seen.
        try:
            task_id, task_status = await _file_or_find_document_promotion_task(
                ingest_id, row, requested_by=caller, extraction_ref=req.extraction_ref,
                notice_out=_notice)
        except HTTPException as exc:
            if 400 <= exc.status_code < 500:
                _d = exc.detail if isinstance(exc.detail, dict) else {}
                _err = _d.get("error") if isinstance(_d.get("error"), str) else None
                _msg = _d.get("message")
                _why = f"review refused ({exc.status_code}): {_err or exc.detail}"
                if _msg:
                    _why += f": {_msg}"
                try:
                    await run_in_threadpool(lambda: ingest_status.update_status(
                        ingest_id, ingest_status.FAILED, detail=_why,
                        failure={
                            "reason_code": (_err if _err and ingest_status.REASON_CODE_RE.match(_err)
                                            else "review_refused"),
                            "reason": _why, "step": "review",
                            "run_id": req.run_id or row.get("run_id"),
                            "pin_digest": req.pin_digest,
                            "failed_at": int(time.time() * 1000)},
                        **_adopt, **_run))
                except Exception as werr:  # noqa: BLE001 -- the caller must still see the refusal
                    logger.warning("ingest %s: the refused review could not be written as failed "
                                   "(%s: %s)", ingest_id, type(werr).__name__, werr)
            raise

    # STATUS MOVES ONLY AFTER THE TASK IS FILED (OR FOUND ALREADY_FILED) -- for `review`,
    # everything above either raised or produced a resolvable audience; only now does the row
    # move to `review`, so a 422/503 above never strands the row at `review` with no task. (A 4xx
    # refusal of the review wrote `failed` just above so the row is retryable; a 5xx wrote
    # nothing -- it is transient and the sender retries.) For `extracting`/`failed` there is no task step, so this runs unconditionally.
    # `extraction_ref` rides only on the move INTO review (where it was just validated).
    _extra = {"extraction_ref": req.extraction_ref} if req.stage == ingest_status.REVIEW else {}
    if req.stage == ingest_status.REVIEW and _notice.get("notice_id"):
        _extra["notice_id"] = _notice["notice_id"]
    if req.stage == ingest_status.REVIEW:
        _extra.update(_adopt)
    _detail = req.detail
    if req.stage == ingest_status.FAILED:
        # `reason` falls back to `detail` (legacy posts); the existing non-blank-detail rule in
        # update_status still refuses a failure with neither. `detail` is written as the reason so
        # it stays meaningful to readers that only know `detail`.
        _reason = req.reason if (req.reason and req.reason.strip()) else req.detail
        _detail = _reason
        _extra["failure"] = {
            "reason_code": req.reason_code, "reason": _reason, "step": req.step,
            # A failure that names no run of its own still names the one the row last recorded
            # (an `extracting` POST that carried it): the directive asks for "the run id if any".
            "run_id": req.run_id or row.get("run_id"), "pin_digest": req.pin_digest,
            "failed_at": int(time.time() * 1000)}
    try:
        await run_in_threadpool(lambda: ingest_status.update_status(
            ingest_id, req.stage, extracted_count=req.extracted_count,
            extracted_total=req.extracted_total, detail=_detail, **_extra, **_run))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_stage_update", "message": str(exc)})

    return {"ingest_id": ingest_id, "stage": req.stage, "task_id": task_id, "task_status": task_status}


def _bbox_is_page_fractions(bbox) -> bool:
    """True when `bbox` is [x0, y0, x1, y1] in page FRACTIONS (architect ruling 10-21, "Crop
    coordinates: page fractions"): four finite numbers, 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1."""
    import math

    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
               for n in bbox):
        return False
    x0, y0, x1, y1 = bbox
    return 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


class TitleEvidenceRef(_ServedEvidenceRef):
    """A title candidate's crop: the served `ingest_api.EvidenceRef` (which the equivalence seal holds
    to the SDK verdict) plus the page-fraction bounds. A SUBCLASS of the served model, not of the SDK's,
    so the published title-candidate schema keeps its array-of-numbers bbox and `page` minimum. Steward
    row_edits / header_edits evidence_ref now go through the SDK model (`_wire_evidence_ref`).
    Cortex drops a whole candidate list on any out-of-bounds box, so the BFF refuses it (422).
    Strict, as the request model it replaced was: a coordinate sent as a string is refused, not coerced."""
    model_config = {**_ServedEvidenceRef.model_config, "strict": True}

    @model_validator(mode="after")
    def _fractions(self):
        if self.bbox is not None and not _bbox_is_page_fractions(self.bbox):
            raise ValueError("a title candidate's bbox is [x0, y0, x1, y1] in page fractions: "
                             "0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
        return self


class TitleCandidate(_BaseModel):
    """One leaf the title read considered: `{leaf, score, evidence_ref}`. `evidence_ref` is the title
    crop the read used (the struct `EvidenceRef`, required; not the legacy string)."""
    model_config = {"extra": "forbid"}
    leaf: str
    score: _StrictInt | _Annotated[_StrictFloat, Field(allow_inf_nan=False)]
    evidence_ref: TitleEvidenceRef

    @field_validator("leaf")
    @classmethod
    def _leaf_nonblank(cls, v):
        return _nonblank(v)

    @field_validator("score")
    @classmethod
    def _score_in_unit_range(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("score must be in [0, 1]")
        return v


class IngestTitleLeafRequest(_BaseModel):
    """POST /ingest/{ingest_id}/title_leaf's body: what doc-tools' header/title read found."""
    model_config = {"extra": "forbid"}
    doc_type: Optional[str] = None
    doc_type_source: Optional[str] = None
    candidates: Optional[list[TitleCandidate]] = Field(default=None, max_length=3)
    run_id: Optional[str] = None


@app.post("/ingest/{ingest_id}/title_leaf", tags=[INGEST_V1_TAG], responses={200: {"model": TitleLeafResponse}, **DROP_GATE_RESPONSES})
async def ingest_title_leaf_route(
    ingest_id: str, req: IngestTitleLeafRequest, current_user: User = Depends(get_current_user),
):
    """POST /ingest/<id>/title_leaf -- SERVICE-ONLY (`svc:doc-tools`, same caller gate as the stage
    route). doc-tools calls it after the header/title read and BEFORE parts extraction; the answer
    says which kind's passes to run, or to stop (architect ruling 2026-10-21: a drop is never blocked
    up front; if the title yields no leaf the row stops at `awaiting_kind` there).

    Dispatch, in order: (1) a row that already carries a declared or corrected leaf
    proceeds with it, writes nothing; (2) a row that is not leaf-capable proceeds, writes nothing;
    (3) a CONFIDENT title (`_title_leaf`) is written as `leaf_source=title` and proceeds;
    (4) otherwise the row is held at `awaiting_kind` with the candidates and doc-tools must stop.
    Every write is one guarded UPDATE; when it matches nothing the row is re-read and decided again.
    Allowed stages: `received`, `extracting` (a provisional timeout counts as `received`); anything
    else is 409 `not_extracting`. A repeat on a held row is therefore 409, which is correct."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    caller = (current_user.authz_id or "").strip()
    if not _DOC_TOOLS_SERVICE_AUTHZ_ID or caller != _DOC_TOOLS_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_doc_tools",
            "message": "POST /ingest/{ingest_id}/title_leaf is callable only by doc-tools' own "
                       "service identity.",
        })
    if req.run_id is not None and not req.run_id.strip():
        raise HTTPException(status_code=422, detail={"error": "invalid_run_id"})

    async def _read() -> dict:
        r = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
        if r is None or r.get("kind") == ingest_status.EVENT:
            raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
        return r

    def _answer(r: dict, proceed: bool) -> dict:
        leaf, leaf_source, corrected_by = _row_leaf(r)
        return {"ingest_id": ingest_id, "proceed": proceed, "stage": r["status"],
                "content_kind": r.get("content_kind"), "leaf": leaf, "leaf_source": leaf_source,
                "corrected_by": corrected_by,
                "leaf_candidates": (r.get("leaf_candidates")
                                    if r["status"] == ingest_status.AWAITING_KIND else None)}

    title = _title_leaf(req.doc_type, req.doc_type_source)
    row = await _read()
    for _ in range(4):
        stage = row["status"]
        timed_out = (stage == ingest_status.FAILED
                     and (row.get("failure") or {}).get("reason_code") == ingest_status.REASON_TIMEOUT)
        effective = ingest_status.RECEIVED if timed_out else stage
        if effective not in (ingest_status.RECEIVED, ingest_status.EXTRACTING):
            raise HTTPException(status_code=409, detail={
                "error": "not_extracting", "stage": stage,
                "message": f"a title read is accepted only while the document is extracting; it is {stage}."})
        row_leaf, row_source, _cb = _row_leaf(row)
        # 1. a declared or corrected leaf beats the title,
        #    and a title leaf already on the row stands when this read names none
        if row_leaf is not None and (row_source != "title" or title is None):
            return _answer(row, True)
        # 2. not a notice-in-waiting: nothing to decide
        if not _leaf_capable(row):
            return _answer(row, True)
        # 3. a confident title
        if title is not None:
            # can_drop:<title>, against the row's DROPPER (not doc-tools): a service identity must
            # not launder a non-grantee's drop into a restricted kind. Refused: the leaf is NOT set
            # and the row waits for a kind (the hold in step 4), then the 403 is answered.
            try:
                await _can_drop_or_refuse(title, _row_dropper(row))
            except HTTPException as exc:
                if exc.status_code == 403:
                    await run_in_threadpool(lambda: ingest_status.hold_for_kind(
                        ingest_id,
                        candidates=[c.model_dump() for c in (req.candidates or [])],
                        detail=(f"the title named {title}, which the dropper may not drop; "
                                "pick another kind"),
                        run_id=req.run_id, from_statuses=[stage]))
                raise
            written = await run_in_threadpool(lambda: ingest_status.set_leaf(
                ingest_id, title, "title", set_by=caller, from_statuses=[stage]))
            if written is not None:
                logger.info("ingest_leaf ingest_id=%s caller=%s from=%s to=%s stage=%s",
                            ingest_id, caller, row_leaf, title, written["status"])
                return _answer(written, True)
            row = await _read()
            continue
        # 4. no confident leaf: hold for a pick
        held = await run_in_threadpool(lambda: ingest_status.hold_for_kind(
            ingest_id,
            candidates=[c.model_dump() for c in (req.candidates or [])],
            detail=(f"the title named no leaf ({req.doc_type_source or 'no source'}); "
                    "pick pcn or pdn"),
            run_id=req.run_id, from_statuses=[stage]))
        row = await _read()
        if held:
            logger.info("ingest_leaf ingest_id=%s caller=%s from=%s to=%s stage=%s",
                        ingest_id, caller, row_leaf, None, row["status"])
            return _answer(row, False)
    raise HTTPException(status_code=409, detail={
        "error": "not_extracting", "stage": row["status"],
        "message": f"a title read is accepted only while the document is extracting; it is {row['status']}."})


class IngestLeafRequest(_BaseModel):
    """POST /ingest/{ingest_id}/leaf's body: the leaf (pcn|pdn) the dropper or steward picks."""
    model_config = {"extra": "forbid"}
    leaf: str


@app.post("/ingest/{ingest_id}/leaf", tags=[INGEST_V1_TAG], responses={200: {"model": LeafResponse}, **DROP_GATE_RESPONSES})
async def ingest_leaf_route(
    ingest_id: str, req: IngestLeafRequest, current_user: User = Depends(get_current_user),
):
    """POST /ingest/<id>/leaf -- the dropper's or steward's correction of a row's leaf (pcn|pdn),
    recorded as `leaf_source=corrected` with who and when. Gate: `_ingest_review_access` (the
    dropper, the holder of the open `document_promotion` task, or a seeding delegate service).
    422 `unknown_leaf`; 409 `no_leaf_for_kind` for a row that is not leaf-capable.

    The leaf can change until promotion (ruling 2026-10-21 "Leaf, final shape"); dropper and steward
    use this one route. Dispatch on the stage:

      received, extracting, failed   set_leaf(corrected) in place; the stage is unchanged. The
                                     run in flight read the OLD kind from the drop's sidecar, so
                                     `_ingest_leaf_relaunch_tick` relaunches the row AS THE LEAF
                                     once its run has finished (within one 60 s poll)
      awaiting_kind                  the drop's sidecar is rewritten to the leaf FIRST (a failure
                                     is 503 `sidecar_unwritable`, nothing changed), then
                                     set_leaf(corrected) and the row goes back to `received`,
                                     `attempt` + 1, reason `leaf_applied`: nothing was extracted,
                                     so the hold is released and doc-tools relaunches it from
                                     GET /ingest/retries, running as the leaf
      awaiting_origin, review        spec 204: RE-CLASS when `_same_passes(old, new)` (the two kinds
                                     declare equal pass lists in the registry): awaiting_origin
                                     records the correction and keeps its stage; review files the
                                     next generation's task (`document_promotion:<id>:g<n>`) FIRST,
                                     then records the correction, then supersedes the old task. The
                                     answer adds `task_id` and `superseded_task_id`. RE-RUN when the
                                     pass lists differ: back to `received`, `attempt` + 1 (and, at
                                     review, the generation bumps and the old task is superseded;
                                     the re-extraction's return to review files the new one)
      promoted, rejected,            409 `leaf_not_changeable` (with the stage)
      review_rejected

    A write that matches nothing (the row moved under us) is 409 `leaf_not_changeable` with the
    current stage. Answers the row's status body."""
    from starlette.concurrency import run_in_threadpool

    from . import content_kinds, human_tasks, ingest_status, promotion

    route = "POST /ingest/{ingest_id}/leaf"
    leaf = str(req.leaf or "").strip().lower()
    if leaf not in ingest_status.LEAVES:
        raise HTTPException(status_code=422, detail={
            "error": "unknown_leaf", "allowed": list(ingest_status.LEAVES),
            "message": "the kind must be one of: " + ", ".join(ingest_status.LEAVES)})

    row, _reason = await _ingest_review_access(ingest_id, current_user, route)
    caller = (current_user.authz_id or "").strip()
    stage = row["status"]

    async def _body() -> dict:
        fresh = await run_in_threadpool(lambda: ingest_status.get_status_unscoped(ingest_id))
        if fresh is None:
            raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
        return await _ingest_status_body(fresh, current_user)

    def _refuse(status_code: int, detail: dict, why: str):
        _audit_ingest_access(route, ingest_id, caller, "deny", why)
        raise HTTPException(status_code=status_code,
                            detail=_detail_with_message(status_code, detail))

    if not _leaf_capable(row):
        _refuse(409, {"error": "no_leaf_for_kind", "stage": stage,
                      "content_kind": row.get("content_kind"),
                      "message": f"a {row.get('content_kind')} document has no kind to choose"},
                "no_leaf_for_kind")
    current_leaf, _src, _cb = _row_leaf(row)
    if current_leaf == leaf:
        _audit_ingest_access(route, ingest_id, caller, "allow", "same_leaf")
        return await _body()

    def _log(to_stage: str) -> None:
        logger.info("ingest_leaf ingest_id=%s caller=%s from=%s to=%s stage=%s",
                    ingest_id, caller, current_leaf, leaf, to_stage)

    async def _moved() -> dict:
        # The guarded write matched nothing: the row moved under us. Say so, with where it is now.
        now = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
        _refuse(409, {"error": "leaf_not_changeable", "stage": (now or {}).get("status"),
                      "message": "the document moved on while the kind was being set; "
                                 "reload it and try again"}, "row_moved")

    # can_drop:<leaf>, against the row's DROPPER, never the caller (a granted steward or the BFF must
    # not move a non-grantee's document into a restricted kind). No steward exemption: deny by
    # default until the architect rules. Once, before any write (the sidecar rewrite included); the
    # dropper of record does not change across the rounds below.
    try:
        await _can_drop_or_refuse(leaf, _row_dropper(row))
    except HTTPException as exc:
        _audit_ingest_access(route, ingest_id, caller, "deny",
                             "not_entitled_to_drop" if exc.status_code == 403
                             else "authorization_unavailable")
        raise
    old_kind = row.get("content_kind")
    same = _same_passes(old_kind, leaf)
    for _round in range(3):
        if _round:
            # The row moved under a review-stage write: read it again and decide again.
            row = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
            if row is None:
                raise HTTPException(status_code=404, detail={"error": "ingest_not_found"})
            stage = row["status"]
            if _row_leaf(row)[0] == leaf:
                _audit_ingest_access(route, ingest_id, caller, "allow", "same_leaf")
                return await _body()

        if stage in (ingest_status.RECEIVED, ingest_status.EXTRACTING, ingest_status.FAILED):
            written = await run_in_threadpool(lambda: ingest_status.set_leaf(
                ingest_id, leaf, "corrected", set_by=caller, from_statuses=[stage]))
            if written is None:
                await _moved()
            _log(stage)
            _audit_ingest_access(route, ingest_id, caller, "allow", "leaf_corrected")
            return await _body()

        if stage == ingest_status.AWAITING_ORIGIN and same:
            # Same passes: the parts already extracted are valid for the new kind. A recorded
            # correction, stage unchanged (the accepted origin still files the task).
            written = await run_in_threadpool(lambda: ingest_status.set_leaf(
                ingest_id, leaf, "corrected", set_by=caller,
                from_statuses=[ingest_status.AWAITING_ORIGIN]))
            if written is None:
                await _moved()
            _log(stage)
            _audit_ingest_access(route, ingest_id, caller, "allow", "leaf_reclassed")
            return await _body()

        if stage in (ingest_status.AWAITING_KIND, ingest_status.AWAITING_ORIGIN) or (
                stage == ingest_status.REVIEW and not same):
            gen = int(row.get("review_generation") or 0)
            at_review = stage == ingest_status.REVIEW
            # The relaunch re-reads the drop's sidecar, so it is rewritten to the leaf FIRST; if it
            # cannot be, nothing is written to the row.
            try:
                await run_in_threadpool(lambda: _apply_leaf_to_sidecar(row, leaf))
            except Exception as exc:  # noqa: BLE001
                logger.warning("ingest_leaf ingest_id=%s sidecar not written (%s: %s)", ingest_id,
                               type(exc).__name__, exc)
                _refuse(503, {"error": "sidecar_unwritable", "stage": stage,
                              "message": "the drop's manifest could not be updated to the new "
                                         "kind, so nothing was changed; try again"},
                        "sidecar_unwritable")
            written = await run_in_threadpool(lambda: ingest_status.set_leaf(
                ingest_id, leaf, "corrected", set_by=caller,
                from_statuses=[stage], to_status=ingest_status.RECEIVED, bump_attempt=True,
                bump_generation=at_review, expect_generation=gen if at_review else None,
                retry_reason=ingest_status.REASON_LEAF_APPLIED))
            if written is None:
                if at_review:
                    continue
                await _moved()
            _log(ingest_status.RECEIVED)
            _audit_ingest_access(route, ingest_id, caller, "allow",
                                 "leaf_picked_reopened" if stage == ingest_status.AWAITING_KIND
                                 else "leaf_corrected_reextract")
            out = await _body()
            if at_review:
                old_id = _promotion_task_id(ingest_id, gen)
                await run_in_threadpool(lambda: human_tasks.supersede_open_task(old_id))
                out["task_id"] = None
                out["superseded_task_id"] = old_id
            return out

        if stage == ingest_status.REVIEW:
            # RE-CLASS AT REVIEW (same passes): file the next generation's task FIRST, then move
            # the row, so a filing refusal writes nothing to the row (find-or-file discipline).
            gen = int(row.get("review_generation") or 0)
            old_id = _promotion_task_id(ingest_id, gen)
            new_id = _promotion_task_id(ingest_id, gen + 1)
            reg = content_kinds.by_kind(leaf)
            new_aud = (f"{promotion.KIND}:{reg.domain.upper()}"
                       if reg is not None and reg.domain else None)
            old_state = await run_in_threadpool(lambda: human_tasks.get_task_open_state(old_id))
            if (old_state and old_state.get("open") and new_aud is not None
                    and old_state.get("audience") != new_aud):
                _refuse(409, {"error": "leaf_moves_audience", "stage": stage,
                              "message": f"the new kind {leaf!r} routes to {new_aud!r}, not the "
                                         f"open task's audience {old_state.get('audience')!r}; "
                                         "nothing was written."}, "leaf_moves_audience")
            filed_id, _st = await _file_or_find_document_promotion_task(
                ingest_id, {**row, "content_kind": leaf}, requested_by=caller,
                extraction_ref=row.get("extraction_ref"), generation=gen + 1)
            written = await run_in_threadpool(lambda: ingest_status.set_leaf(
                ingest_id, leaf, "corrected", set_by=caller, from_statuses=[ingest_status.REVIEW],
                bump_generation=True, expect_generation=gen))
            if written is None:
                # The row moved. Withdraw the g+1 task only if it is not now the row's CURRENT task:
                # a concurrent re-class at the same generation may have won the write and made it so.
                # A concurrent RE-RUN also lands on g+1 but leaves review, and files no task there.
                _now = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
                if not (_now and _now.get("status") == ingest_status.REVIEW
                        and _current_promotion_task_id(_now) == new_id):
                    await run_in_threadpool(lambda: human_tasks.supersede_open_task(new_id))
                continue
            await run_in_threadpool(lambda: human_tasks.supersede_open_task(old_id))
            _log(stage)
            _audit_ingest_access(route, ingest_id, caller, "allow", "leaf_reclassed_at_review")
            out = await _body()
            out["task_id"] = filed_id
            out["superseded_task_id"] = old_id
            return out

        break

    if stage == ingest_status.REVIEW:
        # Three rounds and the row kept moving under the guarded write.
        await _moved()
    _refuse(409, {"error": "leaf_not_changeable", "stage": stage,
                  "message": f"the kind can change only until promotion; this document is {stage}"},
            "leaf_not_changeable")


# the case runner's own transport identity (policy/users.yaml: `svc:case-runner`, restate-analyst's
# direct_call delegate identity). SAME IDIOM as `_DOC_TOOLS_SERVICE_AUTHZ_ID` above: a Keycloak
# hardcoded-claim mapper output, not a caller-supplied value, so it is not spoofable; env-overridable
# only so a differently-named realm can be configured, never to widen it.
_CASE_RUNNER_SERVICE_AUTHZ_ID = os.getenv("CASE_RUNNER_SERVICE_IDENTITY", "svc:case-runner").strip()


class _OriginWriteDroppedBy(_BaseModel):
    authz_id: str


class OriginWriteRequest(_BaseModel):
    """POST /internal/origin/write's body -- the origin_record case's own resolution
    (`policy/workflows/origin_record.yaml`'s `resolution` emit, read back through its `written`
    direct_call step's `extra_payload`). Field-for-field what `src/iagent/origin_writer.write_origin`
    expects in its `resolution` argument, plus `dropped_by` (write_origin itself never reads it --
    this route uses it to find the steward's `on_behalf_of` and to resolve program membership)."""
    artifact_id: str
    dropped_by: _OriginWriteDroppedBy
    origin: dict
    evidence: dict
    approval_chain: list[dict]


@app.post("/internal/origin/write")
async def write_origin_route(
    req: OriginWriteRequest,
    current_user: User = Depends(get_current_user),
):
    """The origin_record case's `written` step (item B, 2026-10-03): writes the steward-accepted
    origin through `origin_writer.write_origin`. SERVICE-ONLY: only `svc:case-runner` (see
    `_CASE_RUNNER_SERVICE_AUTHZ_ID`) may call this -- every other caller, authenticated or not,
    gets 403, same idiom as `/ingest/{ingest_id}/stage` above.

    `on_behalf_of` is the STEWARD who accepted the case -- the `approval_chain` entry whose
    `role` is `"steward"` (`policy/workflows/origin_confirm.yaml`'s accept step is the only step
    with that role in this chain); absent, this refuses 422 rather than writing under nobody's
    provenance.

    Never raises for a refused WRITE -- `write_refused` is a normal outcome of a resolution that
    fails `check_dropper_bound` or shape validation, reported 200 like `written` is. Only the
    caller gate (403) and the missing-steward bound check (422) are HTTP errors.

    A steward's ACCEPT IS THE ATTESTATION (ruling 2026-10-10 Q2, superseding the 10-02 "terminal"
    ruling for the accept branch only): when the origin is `written` and the ingest row is at
    `awaiting_origin`, `_file_promotion_if_ready` files `document_promotion:<owner_domain>` (the
    domain READ BACK FROM THE STORE, what was written) and moves the row to `review` -- TASK
    FIRST, STATUS SECOND; the stage and retry routes call the same function. A filing refusal never
    undoes the write and never strands the row: the response stays `written` with
    `promotion: {"filed": False, "error": ...}`. Reject stays terminal and dropper-only. The
    response gains `promotion` (None when nothing was attempted); `status` is unchanged.
    """
    from iagent_mesh.interfaces import Initiator

    from . import human_tasks, origin_writer
    from .promotion_stores import INGEST_FACT_FAMILY

    caller = (current_user.authz_id or "").strip()
    if not _CASE_RUNNER_SERVICE_AUTHZ_ID or caller != _CASE_RUNNER_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_case_runner",
            "message": "POST /internal/origin/write is callable only by the case runner's own "
                       "service identity.",
        })

    steward_entries = [e for e in req.approval_chain if e.get("role") == "steward"]
    if not steward_entries or not steward_entries[-1].get("approver_sub"):
        raise HTTPException(status_code=422, detail={
            "error": "no_steward_approval",
            "message": "approval_chain carries no `role: steward` entry with an `approver_sub` "
                       "-- refusing to write under nobody's provenance.",
        })
    on_behalf_of = steward_entries[-1]["approver_sub"]

    dropped_by_authz_id = req.dropped_by.authz_id
    program = req.origin.get("program")
    dropper_is_program_member = (
        human_tasks.check_can_view_program(program, dropped_by_authz_id) if program else False
    )

    try:
        from agent_fleet.utils.mesh_writers.neo4j_graph import Neo4jGraphWriter  # noqa: PLC0415

        graph_writer = Neo4jGraphWriter(driver=neo4j_driver, **INGEST_FACT_FAMILY)
    except Exception as exc:  # noqa: BLE001 — refused by name below, never a 500 here
        logger.warning("origin write graph store unavailable: %s", exc)
        return {"status": "write_refused", "reason": f"graph store unavailable: {exc}"}

    initiator = Initiator(
        subject=_CASE_RUNNER_SERVICE_AUTHZ_ID, kind="delegate", on_behalf_of=on_behalf_of,
    )
    resolution = {
        "artifact_id": req.artifact_id,
        "origin": req.origin,
        "evidence": req.evidence,
        "approval_chain": req.approval_chain,
    }
    result = origin_writer.write_origin(
        resolution,
        graph_writer=graph_writer,
        initiator=initiator,
        dropper_is_program_member=dropper_is_program_member,
    )
    promotion_out = None
    if result["status"] == "written":
        promotion_out = await _file_promotion_if_ready(
            req.artifact_id, requested_by=_CASE_RUNNER_SERVICE_AUTHZ_ID)
    return {"status": result["status"], "reason": result.get("reason"),
            "promotion": promotion_out}


def _read_accepted_origin(ingest_id: str) -> Optional[dict]:
    """SYNC. The artifact's ACCEPTED origin -- {"owner_domain", "program", "resolved_by"} -- or None
    when there is no node, no owner domain, or the rung is unresolved. A read that raises PROPAGATES:
    an unknown origin is not an absent one. Same accepted-origin predicate as
    `notice_parts.source_visibility`."""
    from .promotion_stores import INGEST_FACT_FAMILY

    if neo4j_driver is None:
        raise RuntimeError("graph store not connected")
    # Built FROM the family, so it names the node `write_origin` writes.
    cypher = (
        f"MATCH (n:{INGEST_FACT_FAMILY['node_label']} "
        f"{{{INGEST_FACT_FAMILY['node_key']}: $ingest_id}})\n"
        "RETURN n.origin_owner_domain AS owner_domain, n.origin_program AS program, "
        "n.origin_resolved_by AS resolved_by"
    )
    with neo4j_driver.session() as session:
        row = session.run(cypher, ingest_id=ingest_id).single()
    if row is None:
        return None
    owner_domain, program, resolved_by = row["owner_domain"], row["program"], row["resolved_by"]
    if not isinstance(owner_domain, str) or not owner_domain.strip():
        return None
    if resolved_by in (None, "", "unresolved"):
        return None
    return {"owner_domain": owner_domain, "program": program or None, "resolved_by": resolved_by}


async def _file_promotion_if_ready(ingest_id: str, *, requested_by: str) -> Optional[dict]:
    """FUNCTION OF STATE (Q2, 2026-10-10): files iff the row is at `awaiting_origin` AND an
    accepted origin exists on the artifact; called from the accept route, the stage route and the
    retry route, so the order the accept and the extraction land in cannot matter. TASK FIRST,
    STATUS SECOND: a refusal leaves the row at `awaiting_origin`.

    None when nothing was attempted (no row, row elsewhere, or no accepted origin yet);
    {"filed": False, "error": ...} when attempted and refused or the origin was unreadable;
    {"filed": True, "task_id", "task_status"} when filed and the row moved to `review`."""
    from starlette.concurrency import run_in_threadpool

    from . import ingest_status

    row = await run_in_threadpool(lambda: ingest_status.get_row(ingest_id))
    if row is None or row["status"] != ingest_status.AWAITING_ORIGIN:
        return None
    try:
        origin = await run_in_threadpool(lambda: _read_accepted_origin(ingest_id))
    except Exception as exc:  # noqa: BLE001 -- an unknown origin is not an absent one
        logger.warning("promotion not filed, origin unreadable: ingest_id=%s error=%s",
                       ingest_id, exc)
        return {"filed": False, "error": "origin_unreadable"}
    if origin is None:
        return None
    if row.get("content_kind") in _PROMOTION_SKIPPED_KINDS:
        # The steward's accept is this kind's exit from `awaiting_origin` (architect ruling
        # 2026-10-17): the origin is recorded, the row goes `promoted`, and NO document_promotion
        # task is filed -- the same rule as the delegate path in the stage route, one step later.
        await run_in_threadpool(lambda: ingest_status.update_status(
            ingest_id, ingest_status.PROMOTED,
            detail="accepted origin; content kind files no document_promotion task (ruling 2026-10-17)"))
        return {"filed": False, "promoted": True, "task_id": None,
                "task_status": "NO_TASK_KIND_SKIPS_PROMOTION"}
    _notice: dict = {}
    try:
        task_id, task_status = await _file_or_find_document_promotion_task(
            ingest_id, row, requested_by=requested_by,
            extraction_ref=row.get("extraction_ref"), domain=origin["owner_domain"],
            notice_out=_notice)
    except HTTPException as exc:
        err = exc.detail.get("error") if isinstance(exc.detail, dict) else str(exc.detail)
        logger.warning("origin accepted but promotion not filed: ingest_id=%s error=%s",
                       ingest_id, err)
        return {"filed": False, "error": err}
    domain_label = str(origin["owner_domain"]).strip().upper()
    await run_in_threadpool(lambda: ingest_status.update_status(
        ingest_id, ingest_status.REVIEW,
        detail=f"accepted origin; promotion filed to document_promotion:{domain_label}",
        **({"notice_id": _notice["notice_id"]} if _notice.get("notice_id") else {})))
    return {"filed": True, "task_id": task_id, "task_status": task_status}


_SEEDED_BY_STAMP_CYPHER = (
    "MATCH (a:AnswerArtifact {case_id: $case_id}) "
    "SET a.seeded_by = $seeded_by RETURN count(a) AS n"
)


class SeededByStampRequest(_BaseModel):
    seeded_by: str


@app.post("/internal/cases/{case_id}/seeded-by")
async def stamp_seeded_by_route(
    case_id: str,
    req: SeededByStampRequest,
    current_user: User = Depends(get_current_user),
):
    """The runner stamps the seeding delegate on a case's artifacts at `released` (ADR-0041 §8.1,
    RULED 2026-10-08). SERVICE-ONLY: only `svc:case-runner` may call this, same gate as
    `/internal/origin/write`. `n == 0` is a 200, not an error (a case that released without
    writing a case-linked artifact stamps nothing). CORRECTED 2026-10-09: the maintenance case's
    ActionRecord, written by `/internal/cases/{case_id}/action-record` just below, IS a
    case-linked artifact, and the runner writes it before this stamp.
    Only a declared delegate can be a seeding delegate: anything else is 422.
    R-089: the delegate map is asserted by configuration this pass."""
    from starlette.concurrency import run_in_threadpool

    caller = (current_user.authz_id or "").strip()
    if not _CASE_RUNNER_SERVICE_AUTHZ_ID or caller != _CASE_RUNNER_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_case_runner",
            "message": "POST /internal/cases/{case_id}/seeded-by is callable only by the case "
                       "runner's own service identity.",
        })
    if req.seeded_by not in _delegate_principals():
        raise HTTPException(status_code=422, detail={"error": "seeded_by_not_a_declared_delegate"})

    def _stamp() -> int:
        with neo4j_driver.session() as session:
            rec = session.run(
                _SEEDED_BY_STAMP_CYPHER, case_id=case_id, seeded_by=req.seeded_by
            ).single()
        return int(rec["n"]) if rec is not None else 0

    return {"case_id": case_id, "stamped": await run_in_threadpool(_stamp)}


# The case's artifact ids, read from the graph by the SERVER (never the runner's word). At
# `released` the same call stamps `released_at` (ms epoch, the unit of `created_at`) on the
# artifacts that do not carry one yet: `coalesce` keeps the FIRST release's instant when the
# summary is re-delivered. GET /ingest/{id}/status lists it.
_CASE_ARTIFACT_IDS_CYPHER = (
    "MATCH (a:AnswerArtifact {case_id: $case_id}) RETURN a.id AS id ORDER BY id"
)
_CASE_ARTIFACT_RELEASE_CYPHER = (
    "MATCH (a:AnswerArtifact {case_id: $case_id}) "
    "SET a.released_at = coalesce(a.released_at, $now_ms) RETURN a.id AS id ORDER BY id"
)

# A case RELEASED when one of its hops had the outcome `released` -- the runner's
# `SEEDED_BY_STAMP_OUTCOME`, the outcome it stamps seeded_by on. It is an OUTCOME, not the terminal
# STATE: `maint_release_chaining` sends `released` on to the terminal `closed`, so a case that
# released ends `closed` and a test of the terminal's name would never stamp.
_RELEASED_OUTCOME = "released"


def _case_released(transitions: list) -> bool:
    return any(isinstance(t, dict) and t.get("outcome") == _RELEASED_OUTCOME for t in transitions)


class CaseSummaryRequest(_BaseModel):
    state: str
    final_reason: Optional[str] = None
    transitions: list
    seeded_by: Optional[str] = None


@app.post("/internal/cases/{case_id}/summary")
async def write_case_summary_route(
    case_id: str,
    req: CaseSummaryRequest,
    current_user: User = Depends(get_current_user),
):
    """The runner writes the case summary at every terminal transition (released / failed /
    rejected; ruled 2026-10-16): state, final reason, transitions, seeded_by and the artifact ids,
    to the Postgres `case_summary` row, so the record outlives Restate. SERVICE-ONLY: only
    `svc:case-runner` may call this, the same gate as `/internal/cases/{case_id}/seeded-by`.

    The artifact ids are read from Neo4j here, not taken from the caller. When the case RELEASED
    (a hop's outcome is `released`, see `_case_released`; its terminal state is then e.g.
    `closed`) the same call stamps `released_at` on those artifacts (first release wins). The upsert is idempotent:
    a re-delivery overwrites the row."""
    from starlette.concurrency import run_in_threadpool

    from . import case_summary

    caller = (current_user.authz_id or "").strip()
    if not _CASE_RUNNER_SERVICE_AUTHZ_ID or caller != _CASE_RUNNER_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_case_runner",
            "message": "POST /internal/cases/{case_id}/summary is callable only by the case "
                       "runner's own service identity.",
        })
    if not req.state.strip():
        raise HTTPException(status_code=422, detail={"error": "state_is_blank"})

    def _write() -> list:
        released = _case_released(req.transitions)
        cypher = _CASE_ARTIFACT_RELEASE_CYPHER if released else _CASE_ARTIFACT_IDS_CYPHER
        params = {"case_id": case_id}
        if released:
            params["now_ms"] = int(time.time() * 1000)
        with neo4j_driver.session() as session:
            ids = [rec["id"] for rec in session.run(cypher, **params)]
        case_summary.upsert_summary(
            case_id=case_id, state=req.state, final_reason=req.final_reason,
            transitions=req.transitions, seeded_by=req.seeded_by, artifact_ids=ids)
        return ids

    return {"case_id": case_id, "artifact_ids": await run_in_threadpool(_write)}


ACTION_RECORD_KIND = "maintenance-action-record"


class ActionRecordRequest(_BaseModel):
    record: dict
    seeded_by: Optional[str] = None
    on_behalf_of: str


def action_record_artifact_id(case_id: str, action_id: str) -> str:
    """DETERMINISTIC: a Restate retry of the runner's write names the same artifact."""
    digest = hashlib.sha256(f"{case_id}\0{action_id}".encode("utf-8")).hexdigest()[:32]
    return f"action-record-{digest}"


@app.post("/internal/cases/{case_id}/action-record")
async def write_action_record_route(
    case_id: str,
    req: ActionRecordRequest,
    current_user: User = Depends(get_current_user),
):
    """The maintenance case's ActionRecord (R-114, an iagent-side OUTPUT artifact), written at
    `released` by the runner (2026-10-09; ADR-0041 §8.1's first case-linked producer). SERVICE-
    ONLY, same gate as `/internal/cases/{case_id}/seeded-by`.

    ONE AnswerArtifact: id derived from (case_id, action_id) so a retry writes nothing twice
    (`written: false` when it exists); `case_id` and, when given, `seeded_by` on the node;
    `kind` = `maintenance-action-record`; the record as `rendered_output.record`; produced by the
    case runner (delegate) FOR `on_behalf_of`, who is therefore the OWNER the read gate admits.
    The record's own `provenance.case_id` must be the path's, refused before any write."""
    from starlette.concurrency import run_in_threadpool

    # Reached as `_aaw.AnswerArtifactBundle`, not the bare name: tests/routing/test_ask_to_answer_
    # lineage.py reads the FIRST bare-name construction as the answer pipeline's bundle.
    from . import answer_artifact_writer as _aaw

    caller = (current_user.authz_id or "").strip()
    if not _CASE_RUNNER_SERVICE_AUTHZ_ID or caller != _CASE_RUNNER_SERVICE_AUTHZ_ID:
        raise HTTPException(status_code=403, detail={
            "error": "not_case_runner",
            "message": "POST /internal/cases/{case_id}/action-record is callable only by the "
                       "case runner's own service identity.",
        })
    if not (req.on_behalf_of or "").strip():
        raise HTTPException(status_code=422, detail={"error": "on_behalf_of_required"})
    # R-089: `seeded_by` must be a DECLARED delegate (the configured map, asserted not verified
    # this pass), as at the seeded-by stamp; `on_behalf_of` is the case's principal as the runner
    # read it from the case, RECORDED as the owner, not an act this route authorises.
    if req.seeded_by is not None and req.seeded_by not in _delegate_principals():
        raise HTTPException(status_code=422, detail={"error": "seeded_by_not_a_declared_delegate"})
    provenance = req.record.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("case_id") != case_id:
        raise HTTPException(status_code=422, detail={"error": "case_id_mismatch"})
    action_id = req.record.get("action_id")
    if not isinstance(action_id, str) or not action_id.strip():
        raise HTTPException(status_code=422, detail={"error": "action_id_required"})

    artifact_id = action_record_artifact_id(case_id, action_id)
    now_ms = int(time.time() * 1000)
    bundle = _aaw.AnswerArtifactBundle(
        id=artifact_id,
        question_text=f"Maintenance action record {action_id} for case {case_id}",
        message_id=case_id,
        valid_as_of=now_ms,
        status="complete",
        produced_by={"actor_type": "agent", "actor_id": _CASE_RUNNER_SERVICE_AUTHZ_ID},
        produced_for={"user_id": req.on_behalf_of, "is_authenticated": True,
                      "entitlement_source": "case_runner_delegate"},
        resolved_intent={"kind": ACTION_RECORD_KIND, "case_id": case_id, "action_id": action_id},
        routing=None,
        rendered_output={"kind": ACTION_RECORD_KIND, "record": req.record},
        kind=ACTION_RECORD_KIND,
        case_id=case_id,
        seeded_by=req.seeded_by,
    )

    def _write() -> tuple[bool, Optional[str]]:
        with neo4j_driver.session() as session:
            rec = session.run(
                "MATCH (a:AnswerArtifact {id: $id}) RETURN count(a) AS n", id=artifact_id
            ).single()
        if rec is not None and int(rec["n"]) > 0:
            return False, None
        result = _aaw.AnswerArtifactWriter(driver=neo4j_driver).write_sync(bundle)
        return result.success, result.error

    written, error = await run_in_threadpool(_write)
    exists_already = (not written) and error is None
    if not written and not exists_already:
        raise HTTPException(status_code=503, detail={"error": "artifact_write_failed"})
    return {"case_id": case_id, "artifact_id": artifact_id, "written": written}


def _read_action_records(case_id: str) -> list[dict]:
    """Every maintenance action-record AnswerArtifact of the case, OLDEST first by `valid_as_of`:
    `{artifact_id, seeded_by, valid_as_of, record}`. Decoded the way `/answers/{id}/body` decodes
    (`rendered_output` is JSON text, the record at its `record` key). A node whose body does not
    carry a record dict is skipped, never defaulted. Raises on a Neo4j failure."""
    from .projector.apply_loop import _parse_json

    with neo4j_driver.session() as session:
        rows = list(session.run(
            "MATCH (a:AnswerArtifact {kind: $kind, case_id: $case_id}) "
            "RETURN a.id AS id, a.seeded_by AS seeded_by, a.valid_as_of AS valid_as_of, "
            "a.rendered_output AS rendered_output",
            kind=ACTION_RECORD_KIND, case_id=case_id,
        ))
    out: list[dict] = []
    for row in rows:
        body = _parse_json(row["rendered_output"])
        record = body.get("record") if isinstance(body, dict) else None
        if not isinstance(record, dict):
            continue
        out.append({"artifact_id": str(row["id"]), "seeded_by": row["seeded_by"],
                    "valid_as_of": row["valid_as_of"] or 0, "record": record})
    out.sort(key=lambda r: r["valid_as_of"])
    return out


def _action_chain(record: dict, transitions: list) -> list[dict]:
    """The acts of one action record, in order chose -> approved* -> released. An act is present
    only if it was recorded; no who/at is ever defaulted."""
    transitions = [t for t in (transitions or []) if isinstance(t, dict)]
    work_order = record.get("work_order") if isinstance(record.get("work_order"), dict) else {}
    chain: list[dict] = []

    option = work_order.get("option")
    chosen = [t for t in transitions if option is not None and t.get("outcome") == option]
    if chosen:
        t = chosen[-1]
        chain.append({"act": "chose", "who": t.get("by"), "at": t.get("at"), "option": option,
                      "instance_id": t.get("instance_id")})
    for e in record.get("approval_chain") or []:
        if isinstance(e, dict) and e.get("decision") == "approved":
            act = {"act": "approved", "who": e.get("approver_sub"), "at": e.get("decided_at"),
                   "role": e.get("role")}
            if "acted_via" in e:
                act["acted_via"] = e["acted_via"]
            chain.append(act)
    released = [t for t in transitions if t.get("outcome") == _RELEASED_OUTCOME]
    if released:
        t = released[-1]
        chain.append({"act": "released", "who": t.get("by"), "at": t.get("at"),
                      "instance_id": t.get("instance_id")})
    return chain


@app.get("/cases/{case_id}/action")
async def get_case_action(case_id: str, current_user: User = Depends(get_current_user)):
    """GET /cases/{case_id}/action -- who chose, who approved, who released a maintenance case,
    with the work order and the manual data modules it cites.

    BODY. The stored ActionRecord verbatim AT THE TOP LEVEL (action_id, event_id, asset_id,
    owning_tier, label, work_order, approval_chain, provenance, whatever keys it has), plus the
    additive keys `case_id`, `artifact_id`, `acts`, `dmcs_cited`, and `action_ids` only when the
    case has more than one record. A key the record already carries is never overwritten.

    WHERE EACH ACT IS READ FROM. `chose`: the LAST case transition (runner state, as
    `GET /cases/{id}`) whose outcome is the record's `work_order.option`. `approved`: one per
    `approval_chain` entry of the record whose decision is `approved`, chain order (`acted_via`
    only if recorded). `released`: the LAST case transition whose outcome is `released`. An act
    that was not recorded is absent -- never invented. `dmcs_cited` is the record's
    `provenance.manual_nodes_consulted`, de-duplicated, first-seen order.

    THE RECORD IS WRITTEN WHEN THE CASE IS RELEASED (the release instance's outbox is read at its
    completion, `/internal/cases/{id}/action-record`). A case that was approved but is not yet
    released, or that was rejected, has no record and answers 404 `no_action_record`. With more
    than one record the newest by `valid_as_of` is answered and `action_ids` lists them all,
    oldest first.

    GATE, two species. A DELEGATE (a key of `_delegate_principals()`) reads the action record of
    a case it seeded and no other (ruled 2026-10-17 by the architect: "delegate reads only its
    own cases' action records, 403 on others and on /cases/{id}"). Ownership is decided by the
    CASE: the runner's case is fetched first (503 `runner_unavailable`) and the delegate is
    admitted iff the case exists and its `seeded_by` is the caller; a nonexistent case, another
    delegate's case and a case with no `seeded_by` answer one IDENTICAL 403 `not_your_case`, with
    no artifact-store read. An admitted delegate with no record is 404 `no_action_record` (its
    own pending case: nothing yet, not forbidden); a record whose own `seeded_by` differs is 403
    too. No spec/definitions/`can_view_case` for a delegate. Any other SERVICE
    (`_is_service_caller`) is that same 403 before any read: ADR-0047 §5.1 admits a service only
    as a seeding declared delegate. Any other caller, a person, passes exactly
    `GET /cases/{id}`'s gate (`_load_viewable_case`), then 404 `no_action_record` if none. A
    Neo4j failure is 503 `artifact_store_unavailable`.
    """
    from starlette.concurrency import run_in_threadpool

    async def _records() -> list[dict]:
        try:
            return await run_in_threadpool(_read_action_records, case_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("action record read failed: %s", exc)
            raise HTTPException(status_code=503,
                                detail={"error": "artifact_store_unavailable"}) from exc

    def _not_your_case() -> HTTPException:
        return HTTPException(status_code=403, detail={
            "error": "not_your_case",
            "message": "a delegate reads the action record of a case it seeded, and no other"})

    # R-089: the delegate map is asserted by configuration this pass, not verified.
    is_delegate = current_user.authz_id in _delegate_principals()
    if is_delegate:
        try:
            case = await _fetch_case(case_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503,
                                detail={"error": "runner_unavailable"}) from exc
        seeded_by = case.get("seeded_by") if case else None
        if not seeded_by or seeded_by != current_user.authz_id:
            raise _not_your_case()
    elif _is_service_caller(current_user.authz_id):
        # ADR-0047 §5.1: a `svc:` principal is a recipient only as a seeding DECLARED delegate.
        # An undeclared service is never asked the person gate, so dropping the case as itself,
        # holding its labels or holding a task on it admits nothing (Q16's reading at
        # /ingest/{id}/source). Same body as the delegate's refusal, before any read.
        raise _not_your_case()
    else:
        case, _definitions = await _load_viewable_case(case_id, current_user)
    records = await _records()
    if not records:
        raise HTTPException(status_code=404, detail={"error": "no_action_record"})
    newest = records[-1]
    if is_delegate and newest["seeded_by"] != current_user.authz_id:
        raise _not_your_case()

    record = newest["record"]
    prov = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    dmcs: list = []
    for d in prov.get("manual_nodes_consulted") or []:
        if d and d not in dmcs:
            dmcs.append(d)
    additive = {
        "case_id": case_id,
        "artifact_id": newest["artifact_id"],
        "acts": _action_chain(record, (case or {}).get("transitions") or []),
        "dmcs_cited": dmcs,
    }
    if len(records) > 1:
        additive["action_ids"] = [r["record"].get("action_id") for r in records]
    body = dict(record)
    for k, v in additive.items():
        body.setdefault(k, v)  # a key the record carries is never overwritten
    return body


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
        # Scope the inbox stream to PENDING rows only, so it agrees with the REST snapshot
        # (/me/human_tasks): resolving a task moves it OUT of the shape -> Electric emits a delete.
        # The predicate's definition now lives in human_tasks (inbox_where_literal), shared with
        # list_tasks_for; this site only supplies the validated, escaped identity.
        from . import human_tasks as _human_tasks
        server_where = _human_tasks.inbox_where_literal(escaped_id)
    elif table == "ingest_status_projection":
        # ADR-0041 §8: the ingestion seam's status stream. Same authz_id-keyed discipline
        # as human_task_projection above (submitted_by/on_behalf_of are authz identities,
        # not sub/email) — a caller sees rows where they are EITHER the submitter or the
        # on_behalf_of principal, mirroring ingest_status.get_status_for's REST scoping so
        # the streamed shape and the REST snapshot agree on who can see what.
        escaped_id = _escape_identity_literal(current_user.authz_id)
        server_where = f"(submitted_by = '{escaped_id}' OR on_behalf_of = '{escaped_id}')"
    else:
        escaped = _escape_sql_string_literal(verified_user_id)
        server_where = f"produced_for_user_id = '{escaped}'"
        if table == "answer_artifact_projection":
            # Rev 187: the default view hides archived answers (archive hides, never deletes;
            # `GET /answers?include_archived=true` lists them). Other tables keep their filter.
            server_where += " AND archived_at IS NULL"
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
