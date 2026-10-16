"""The content kinds doc-tools can process, as doc-tools PUBLISHES them (owner ruling: PUT
/ingest/processable-kinds, svc:doc-tools only; the BFF persists and caches; the door reads the
cache; no mirrored JSON). One row in Postgres, a process-local TTL cache in front of it.

The door only consults this when INGEST_DOOR_READS_PROCESSABLE_KINDS is on (default OFF); with
the flag off nothing here is called.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import Optional

from . import ingest_status

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS ingest_processable_kinds (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    kinds JSONB NOT NULL,
    source TEXT,
    published_by TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_lock = threading.Lock()
# (kinds tuple, published_at, fetched_monotonic) or None
_cache: Optional[tuple[tuple[str, ...], Optional[datetime], float]] = None


class StoreUnreachable(RuntimeError):
    """The Postgres store could not be read."""


def cache_ttl_seconds() -> float:
    try:
        return float(os.getenv("PROCESSABLE_KINDS_CACHE_SECONDS", "30"))
    except ValueError:
        return 30.0


def reset_cache() -> None:
    """Test hook: forget the process-local cache."""
    global _cache
    with _lock:
        _cache = None


def apply_migration() -> None:
    with ingest_status._pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


def publish(kinds: list[str], source: Optional[str], published_by: str) -> datetime:
    """Upsert the single row; returns published_at."""
    with ingest_status._pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
            cur.execute(
                "INSERT INTO ingest_processable_kinds (id, kinds, source, published_by, published_at) "
                "VALUES (1, %s::jsonb, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET kinds = EXCLUDED.kinds, source = EXCLUDED.source, "
                "published_by = EXCLUDED.published_by, published_at = now() RETURNING published_at",
                (json.dumps(list(kinds)), source, published_by),
            )
            published_at = cur.fetchone()[0]
        conn.commit()
    return published_at


def load() -> Optional[tuple[tuple[str, ...], Optional[datetime]]]:
    """The published (kinds, published_at), or None when never published."""
    with ingest_status._pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
            cur.execute("SELECT kinds, published_at FROM ingest_processable_kinds WHERE id = 1")
            row = cur.fetchone()
        conn.commit()
    if row is None:
        return None
    kinds = row[0]
    if isinstance(kinds, str):
        kinds = json.loads(kinds)
    return tuple(kinds), row[1]


def set_cache(kinds, published_at) -> None:
    global _cache
    with _lock:
        _cache = (tuple(kinds), published_at, time.monotonic())


def current() -> Optional[tuple[str, ...]]:
    """Kinds for the door: a fresh cache entry, else load() and cache. None = never published.
    A failing store serves a stale cached value; with nothing cached it raises StoreUnreachable."""
    with _lock:
        hit = _cache
    if hit is not None and (time.monotonic() - hit[2]) < cache_ttl_seconds():
        return hit[0]
    try:
        loaded = load()
    except Exception as exc:  # noqa: BLE001 -- any store failure
        if hit is not None:
            return hit[0]
        raise StoreUnreachable(f"{type(exc).__name__}: {exc}") from exc
    if loaded is None:
        return None
    set_cache(*loaded)
    return loaded[0]
