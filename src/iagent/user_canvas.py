"""Server-side persistence for the canvas-dock custom canvases (ADR-0028).

A per-user (authz_id) JSON blob of the user's custom canvases, so a user's boards
survive across sessions/devices — localStorage is the offline cache on the
client; this is the durable source of truth. Mirrors human_tasks' psycopg2
pattern and reuses the same PROJECTOR_POSTGRES_DSN. The GLOBAL canvas is derived
(never persisted); only custom canvases + their item positions are stored.
"""
from __future__ import annotations

import json
import os
import time

import psycopg2

_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()

# In-module DDL so the container needs no external migration file (same posture
# as human_tasks). jsonb holds the CustomCanvas[] the client sends verbatim.
_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS user_canvas (
    user_id     text PRIMARY KEY,
    canvases    jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at  bigint
);
"""


class CanvasConfigError(RuntimeError):
    """PG DSN unset — persistence unavailable (dev/local boot stays alive)."""


def _pg_connect():
    if not _PG_DSN:
        raise CanvasConfigError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def apply_migration() -> None:
    """Create user_canvas if absent. Called at cortex-bff startup."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


def get_canvases(user_id: str) -> list:
    """The user's stored custom canvases (empty list if none / unconfigured)."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT canvases FROM user_canvas WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
    if not row or row[0] is None:
        return []
    val = row[0]
    return val if isinstance(val, list) else json.loads(val)


def save_canvases(user_id: str, canvases: list) -> None:
    """Upsert the user's full canvas set (last-write-wins per user)."""
    now = int(time.time() * 1000)
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_canvas (user_id, canvases, updated_at)
                   VALUES (%s, %s::jsonb, %s)
                   ON CONFLICT (user_id) DO UPDATE
                     SET canvases = EXCLUDED.canvases,
                         updated_at = EXCLUDED.updated_at""",
                (user_id, json.dumps(canvases), now),
            )
        conn.commit()
