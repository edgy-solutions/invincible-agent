"""HITL HumanTask substrate — registration, viewability, and resolution.

The queue is the enforcement model's FIFTH namespace (see policy/task_grants.yaml
+ the `task_audience` Topaz type). This module owns the WRITE path into the
Electric-replicated `human_task_projection` table and the Topaz interactions that
make the two viewability layers derive from ONE truth:

  register_task(audience, ...)
    -> ask Topaz for the audience's authorized ACTORS (directory relations)
    -> materialize ONE projection row per actor (recipient_id = that actor)
  the cortex-bff /electric/shape proxy then filters this table by
    recipient_id = <server-verified caller authz_id>
  and resolve_task(...) RE-CHECKS Topaz can_act before acting.

Because the rows exist BECAUSE Topaz authorized them, the Electric replication
filter (what a subscription receives) and the Topaz can_act gate cannot diverge.
recipient_id holds the AUTHZ IDENTITY (authz_id = the USER_ENTITLEMENT_CLAIM key
Topaz is seeded by — email in sandbox, employee-ID at work-deploy) used end-to-end,
which ELIMINATES the recurring sub<->email bridge (no mapping to mis-route) and
keeps the schema identity-key-agnostic (switching the key is a config change).

Postgres = the SAME Electric-replicated DB the projector writes (PROJECTOR_POSTGRES_DSN).
psycopg2 (sync) is the projector's dependency; the async gateway wraps these calls
in starlette.run_in_threadpool.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional

import httpx
import psycopg2
import psycopg2.extras

# The Electric-replicated Postgres — same DSN the projector uses.
_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()
# Topaz Directory (relations + check). Same URL cortex-bff uses for entitlements.
_TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "").strip()

# Authoritative migration (cortex-bff applies at startup; mirrors
# sql/create_human_task_projection.sql, kept in-module so the container has no
# file-path dependency). Idempotent.
_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS human_task_projection (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    task_id TEXT NOT NULL,
    workflow_id TEXT,
    audience TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    subject_ref TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    acted_by TEXT,
    acted_at BIGINT,
    decision TEXT,
    comment TEXT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_htp_recipient_id ON human_task_projection (recipient_id);
CREATE INDEX IF NOT EXISTS idx_htp_task_id ON human_task_projection (task_id);
CREATE INDEX IF NOT EXISTS idx_htp_status ON human_task_projection (status);
"""


class HumanTaskConfigError(RuntimeError):
    """Raised when the substrate is asked to operate without its backing config
    (PG DSN / Topaz URL). Fail LOUD — never silently no-op a security surface."""


def _pg_connect():
    if not _PG_DSN:
        raise HumanTaskConfigError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def apply_migration() -> None:
    """Create human_task_projection if absent. Called at cortex-bff startup.
    No-op (logged by caller) when PG DSN unset so local/dev boot doesn't crash."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


# ── Topaz: the ONE authorization truth the two layers derive from ────────────

def _resolve_audience_actors(audience: str) -> list[str]:
    """Ask the Topaz Directory for the authz_ids granted `actor` on this audience —
    the authorized recipient set. Direct user grants only for v1 (group expansion
    deferred; the manifest allows group#member). Returns [] if none (deny-by-
    default: an ungranted audience yields NO rows -> invisible to everyone)."""
    if not _TOPAZ_DIRECTORY_URL:
        raise HumanTaskConfigError("TOPAZ_DIRECTORY_URL is unset")
    params = {
        "object_type": "task_audience",
        "object_id": audience,
        "relation": "actor",
    }
    with httpx.Client(base_url=_TOPAZ_DIRECTORY_URL, timeout=5.0) as c:
        r = c.get("/api/v3/directory/relations", params=params)
        r.raise_for_status()
        body = r.json()
    actors: list[str] = []
    for rel in body.get("results") or body.get("relations") or []:
        # subject is a user object; its id is the AUTHORIZATION identity (authz_id
        # — the USER_ENTITLEMENT_CLAIM key Topaz is seeded by: email in sandbox,
        # employee-ID at work-deploy). NOT necessarily an email.
        if (rel.get("subject_type") == "user") and rel.get("subject_id"):
            actors.append(rel["subject_id"])
    return actors


def check_can_act(audience: str, caller_id: str) -> bool:
    """Application-layer gate: re-check Topaz `can_act` for this caller on this
    audience at resolve time (defense in depth over the replication filter).
    `caller_id` is the authz_id (Topaz's key). Deny-by-default: any error or empty
    identity -> False."""
    if not caller_id or not _TOPAZ_DIRECTORY_URL:
        return False
    payload = {
        "object_type": "task_audience",
        "object_id": audience,
        "relation": "can_act",
        "subject_type": "user",
        "subject_id": caller_id,
    }
    try:
        with httpx.Client(base_url=_TOPAZ_DIRECTORY_URL, timeout=5.0) as c:
            r = c.post("/api/v3/directory/check", json=payload)
            r.raise_for_status()
            return bool(r.json().get("check"))
    except Exception:
        return False  # fail-closed


# ── Registration (materialize rows from the Topaz decision) ──────────────────

def register_task(
    *,
    kind: str,
    task_id: str,
    audience: str,
    title: str,
    summary: str,
    requested_by: str,
    workflow_id: Optional[str] = None,
    subject_ref: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Register a HumanTask: resolve the audience's authorized actors from Topaz
    and materialize ONE projection row per actor. Returns {task_id, recipients}.

    CLEARANCE-BOUNDED: `title`/`summary`/`subject_ref`/`payload` must be
    clearance-SAFE (reference + summary, never compartmented content) — the
    projection row is visible to every authorized actor and must not leak content
    an actor authorized for the TASK is not cleared for.
    """
    actors = _resolve_audience_actors(audience)
    now = int(time.time() * 1000)
    payload_json = json.dumps(payload or {})
    rows = []
    for actor_id in actors:
        rows.append((
            str(uuid.uuid4()), kind, task_id, workflow_id, audience, actor_id,
            "pending", title, summary, requested_by, subject_ref, payload_json,
            None, None, None, None, now, now,
        ))
    if rows:
        with _pg_connect() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO human_task_projection
                       (id, kind, task_id, workflow_id, audience, recipient_id,
                        status, title, summary, requested_by, subject_ref, payload,
                        acted_by, acted_at, decision, comment, created_at, updated_at)
                       VALUES %s""",
                    rows,
                )
            conn.commit()
    return {"task_id": task_id, "audience": audience, "recipients": actors}


def list_tasks_for(caller_id: str, *, status: str = "pending") -> list[dict[str, Any]]:
    """REST fallback / initial-load for the caller's queue (the live path is the
    Electric subscription). `caller_id` is the authz_id. Filters by recipient_id =
    caller — the SAME key the Electric proxy injects, so REST and streaming agree."""
    if not caller_id:
        return []
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, kind, task_id, workflow_id, audience, status, title,
                          summary, requested_by, subject_ref, payload, created_at
                     FROM human_task_projection
                    WHERE recipient_id = %s AND status = %s
                    ORDER BY created_at DESC""",
                (caller_id, status),
            )
            return [dict(r) for r in cur.fetchall()]


def mark_task_resolved(task_id: str, *, caller_id: str, decision: str,
                       comment: str = "") -> int:
    """Mark ALL recipient rows of a logical task resolved (one human acted for the
    audience). `caller_id` (authz_id) recorded as acted_by. Returns rows updated.
    Caller MUST have passed check_can_act first."""
    now = int(time.time() * 1000)
    status = "approved" if decision == "approved" else "rejected"
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE human_task_projection
                      SET status = %s, decision = %s, acted_by = %s, acted_at = %s,
                          comment = %s, updated_at = %s
                    WHERE task_id = %s AND status = 'pending'""",
                (status, decision, caller_id, now, comment, now, task_id),
            )
            n = cur.rowcount
        conn.commit()
    return n
