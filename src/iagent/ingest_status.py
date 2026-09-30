"""Ingestion seam (ADR-0041 §8) — the `ingest_status` projection.

SAME SHAPE as `human_task_projection` (see `human_tasks.py` and the module-level note there):
this module owns the WRITE path into the Electric-replicated `ingest_status_projection` table
(sql/create_ingest_status_projection.sql). The cortex-bff `/electric/shape` proxy filters this
table by `(submitted_by = <caller> OR on_behalf_of = <caller>)` — the server-verified authz_id
from the JWT, never client-controlled.

Postgres = the SAME Electric-replicated DB the projector writes (PROJECTOR_POSTGRES_DSN).
psycopg2 (sync); the async gateway wraps these calls in starlette.run_in_threadpool — same
discipline as human_tasks.py.

ONE ROW PER ARRIVAL. A new sha256 gets one row at id = sha256 (content-addressed). A repeat
arrival of a sha256 that already has a row is level-1 dedupe (ADR-0041 §8): rather than silently
no-op or overwrite, it gets its OWN row (`record_duplicate_arrival`) — "records the arrival as
provenance" per the ADR's own wording, because a second drop is a fact about who tried to
resubmit and when, not a fact to discard.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Optional

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()

# The status ladder (ADR-0041 §8), ORDER meaningful for the SAME reason obtained_via's is
# (provenance.py): it is a degradation-of-completeness path, not a cosmetic list.
RECEIVED, CLASSIFIED, EXTRACTING, EXTRACTED, REVIEW, PROMOTED, REJECTED = (
    "received", "classified", "extracting", "extracted", "review", "promoted", "rejected")
STATUSES = (RECEIVED, CLASSIFIED, EXTRACTING, EXTRACTED, REVIEW, PROMOTED, REJECTED)

# Out-of-band terminal: a repeat arrival never enters the ladder above (it never extracts,
# never reviews) — it is a DIFFERENT fact, recorded once and done. Kept separate from STATUSES
# so a caller walking the ladder in order does not have to reason about a branch that isn't one.
DUPLICATE = "duplicate"
ALL_STATUSES = STATUSES + (DUPLICATE,)

# ContentKind leaves (mesh_system.ttl's ContentKind tree, ADR-0041 §8) — deterministic,
# declared-at-the-door, never LLM-classified (ADR-0021's precedence). Two today; a third is a
# future commit (see mesh_system.ttl's comment on the tree), not a wider enum here.
PDF, CAD = "pdf", "cad"
KINDS = (PDF, CAD)

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS ingest_status_projection (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL,
    object_prefix TEXT NOT NULL,
    submitted_by TEXT NOT NULL,
    on_behalf_of TEXT NOT NULL,
    source TEXT,
    status TEXT NOT NULL,
    extracted_count INTEGER,
    extracted_total INTEGER,
    duplicate_of TEXT,
    detail TEXT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_isp_submitted_by ON ingest_status_projection (submitted_by);
CREATE INDEX IF NOT EXISTS idx_isp_on_behalf_of ON ingest_status_projection (on_behalf_of);
CREATE INDEX IF NOT EXISTS idx_isp_status ON ingest_status_projection (status);
CREATE INDEX IF NOT EXISTS idx_isp_sha256 ON ingest_status_projection (sha256);
"""


class IngestStatusConfigError(RuntimeError):
    """Raised when the substrate is asked to operate without its backing config (PG DSN).
    Fail LOUD — never silently no-op a security surface. Same posture as HumanTaskConfigError."""


def _pg_connect():
    if not _PG_DSN:
        raise IngestStatusConfigError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def apply_migration() -> None:
    """Create ingest_status_projection if absent. Called at cortex-bff startup.
    No-op (logged by caller) when PG DSN unset so local/dev boot doesn't crash."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


def find_primary_by_sha(sha256: str) -> Optional[dict[str, Any]]:
    """The earliest non-duplicate row for this sha256, or None if this content has never
    landed before. This IS the level-1 dedupe check (ADR-0041 §8) — a hit means "already
    processed", a miss means a genuinely new arrival."""
    if not sha256:
        return None
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of,
                          source, status, created_at
                     FROM ingest_status_projection
                    WHERE sha256 = %s AND status != %s
                    ORDER BY created_at ASC
                    LIMIT 1""",
                (sha256, DUPLICATE),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def record_received(
    *,
    sha256: str,
    kind: str,
    object_prefix: str,
    submitted_by: str,
    on_behalf_of: str,
    source: Optional[str] = None,
) -> dict[str, Any]:
    """A genuinely new arrival: one row, id = sha256 (content-addressed — same convention as
    mesh:body_sha's comment in mesh_system.ttl: different bytes is a different key, so a stale
    row is impossible rather than merely detectable). status = received."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    now = int(time.time() * 1000)
    row = {
        "id": sha256, "sha256": sha256, "kind": kind, "object_prefix": object_prefix,
        "submitted_by": submitted_by, "on_behalf_of": on_behalf_of, "source": source,
        "status": RECEIVED, "extracted_count": None, "extracted_total": None,
        "duplicate_of": None, "detail": None, "created_at": now, "updated_at": now,
    }
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingest_status_projection
                   (id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                    status, extracted_count, extracted_total, duplicate_of, detail,
                    created_at, updated_at)
                   VALUES (%(id)s, %(sha256)s, %(kind)s, %(object_prefix)s, %(submitted_by)s,
                           %(on_behalf_of)s, %(source)s, %(status)s, %(extracted_count)s,
                           %(extracted_total)s, %(duplicate_of)s, %(detail)s,
                           %(created_at)s, %(updated_at)s)""",
                row,
            )
        conn.commit()
    return row


def record_duplicate_arrival(
    *,
    sha256: str,
    kind: str,
    object_prefix: str,
    submitted_by: str,
    on_behalf_of: str,
    source: Optional[str],
    original: dict[str, Any],
) -> dict[str, Any]:
    """A repeat arrival of content already processed. ADR-0041 §8: "records the arrival as
    provenance" — so this WRITES a new row (id = fresh uuid, status = duplicate,
    duplicate_of = original['id']) rather than silently discarding the second drop. The
    caller-facing message ("already processed on <date> from <source>") is derived from
    `original`, not restated here — see gateway.py's ingest route."""
    now = int(time.time() * 1000)
    from datetime import datetime, timezone
    processed_on = datetime.fromtimestamp(
        original["created_at"] / 1000, tz=timezone.utc
    ).date().isoformat()
    detail = f"already processed on {processed_on} from {original.get('source') or 'unknown source'}"
    row = {
        "id": str(uuid.uuid4()), "sha256": sha256, "kind": kind, "object_prefix": object_prefix,
        "submitted_by": submitted_by, "on_behalf_of": on_behalf_of, "source": source,
        "status": DUPLICATE, "extracted_count": None, "extracted_total": None,
        "duplicate_of": original["id"], "detail": detail, "created_at": now, "updated_at": now,
    }
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO ingest_status_projection
                   (id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                    status, extracted_count, extracted_total, duplicate_of, detail,
                    created_at, updated_at)
                   VALUES (%(id)s, %(sha256)s, %(kind)s, %(object_prefix)s, %(submitted_by)s,
                           %(on_behalf_of)s, %(source)s, %(status)s, %(extracted_count)s,
                           %(extracted_total)s, %(duplicate_of)s, %(detail)s,
                           %(created_at)s, %(updated_at)s)""",
                row,
            )
        conn.commit()
    return row


def update_status(
    ingest_id: str,
    status: str,
    *,
    extracted_count: Optional[int] = None,
    extracted_total: Optional[int] = None,
    detail: Optional[str] = None,
) -> None:
    """Advance a row through the ladder (received -> classified -> extracting -> extracted ->
    review -> promoted|rejected). Not called by the ingest route itself (which only ever
    writes `received`) — this is the seam the classifier/extraction/review pipeline (future
    work, out of scope for days 1-3) will call as it progresses a document."""
    if status not in ALL_STATUSES:
        raise ValueError(f"status must be one of {ALL_STATUSES}, got {status!r}")
    now = int(time.time() * 1000)
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE ingest_status_projection
                      SET status = %s, extracted_count = COALESCE(%s, extracted_count),
                          extracted_total = COALESCE(%s, extracted_total),
                          detail = COALESCE(%s, detail), updated_at = %s
                    WHERE id = %s""",
                (status, extracted_count, extracted_total, detail, now, ingest_id),
            )
        conn.commit()


def get_status_for(ingest_id: str, *, caller_id: str) -> Optional[dict[str, Any]]:
    """The status of an ingest THIS caller submitted or is the on_behalf_of principal for, or
    None otherwise.

    EXISTENCE-ORACLE SAFE BY SCOPING: filtered on `submitted_by = caller OR on_behalf_of =
    caller`, exactly like `human_tasks.get_task_resolution`'s `recipient_id = caller` scoping —
    a caller who is neither gets None, indistinguishable from "no such ingest", preserving the
    deny-by-default 404 and never revealing another user's queue.
    """
    if not ingest_id or not caller_id:
        return None
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, sha256, kind, object_prefix, submitted_by, on_behalf_of, source,
                          status, extracted_count, extracted_total, duplicate_of, detail,
                          created_at, updated_at
                     FROM ingest_status_projection
                    WHERE id = %s AND (submitted_by = %s OR on_behalf_of = %s)""",
                (ingest_id, caller_id, caller_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None
