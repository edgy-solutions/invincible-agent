"""The case summary (ruled 2026-10-16): the durable record of a case that reached a terminal.

Every terminal transition of a case (released / failed / rejected) writes its summary -- state,
final reason, transitions, seeded_by, artifact ids -- to the `case_summary` row, so the record
outlives Restate. A case record is durable evidence, not runtime state.

SAME SHAPE as `ingest_status` (sql/create_case_summary.sql is the readable copy of the DDL below):
psycopg2 (sync) against the Electric-replicated Postgres (PROJECTOR_POSTGRES_DSN), connected
through `ingest_status._pg_connect`, migrated idempotently at cortex-bff startup; the async
gateway wraps `upsert_summary` in starlette.run_in_threadpool.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

import psycopg2.extras

try:
    from . import ingest_status
except ImportError:  # pragma: no cover — direct file-load test harness has no parent package
    from src.iagent import ingest_status

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS case_summary (
    case_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    final_reason TEXT,
    transitions JSONB NOT NULL,
    seeded_by TEXT,
    artifact_ids JSONB NOT NULL DEFAULT '[]',
    terminal_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
"""

_UPSERT_SQL = """
INSERT INTO case_summary
    (case_id, state, final_reason, transitions, seeded_by, artifact_ids, terminal_at, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (case_id) DO UPDATE SET
    state = EXCLUDED.state,
    final_reason = EXCLUDED.final_reason,
    transitions = EXCLUDED.transitions,
    seeded_by = EXCLUDED.seeded_by,
    artifact_ids = EXCLUDED.artifact_ids,
    terminal_at = EXCLUDED.terminal_at,
    updated_at = EXCLUDED.updated_at
"""


def apply_migration() -> None:
    """Create case_summary if absent. Called at cortex-bff startup; raises
    `ingest_status.IngestStatusConfigError` when the PG DSN is unset (the caller logs it)."""
    with ingest_status._pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


def terminal_at_of(transitions: list) -> _dt.datetime:
    """When the case ended: the last transition's own `at`, so a re-delivery of the same summary
    writes the same instant. Falls back to now (UTC) when no transition carries a parseable one."""
    for t in reversed(transitions or []):
        at = t.get("at") if isinstance(t, dict) else None
        if isinstance(at, str):
            try:
                parsed = _dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
            except ValueError:
                continue
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)
    return _dt.datetime.now(_dt.timezone.utc)


def upsert_summary(
    *,
    case_id: str,
    state: str,
    final_reason: Optional[str],
    transitions: list,
    seeded_by: Optional[str],
    artifact_ids: list,
) -> None:
    """INSERT the case's summary, or overwrite the one a re-delivery already wrote (idempotent)."""
    now = _dt.datetime.now(_dt.timezone.utc)
    params: tuple[Any, ...] = (
        case_id, state, final_reason, psycopg2.extras.Json(transitions), seeded_by,
        psycopg2.extras.Json(list(artifact_ids)), terminal_at_of(transitions), now,
    )
    with ingest_status._pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, params)
        conn.commit()
