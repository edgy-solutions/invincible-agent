"""The BFF's durable copy of each frontend's render menu (architect ruling Q9, 2026-10-19).

"A render menu is a registration like an engine's, and registrations survive prime. The BFF
persists cortex's menu and replays it after any wipe; the login-time post becomes a no-op when
the stored menu matches."

ONE ROW PER frontend_id: its LAST ACCEPTED menu. An accepted registration UPSERTS the row (this
is deliberately replaceable, unlike the decision ledger). The menu is stored as the canonical
JSON text of the ADMITTED capability list, with its sha256, so "does the stored menu match this
post" is a digest comparison.

Same posture as promotion_stores: PROJECTOR_POSTGRES_DSN, psycopg2, injectable `connect=` for
tests, and a store fault is an ANSWER (save -> {"ok": False, "reason": "unreachable"}, loads ->
None / []), never a raise into the route. An unset DSN means callers skip the store.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Callable

import psycopg2

from .decision_record import canonical_json

logger = logging.getLogger(__name__)

_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS frontend_menu (
    frontend_id TEXT PRIMARY KEY,
    frontend_version TEXT NOT NULL DEFAULT '',
    menu_sha256 TEXT NOT NULL,
    menu TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    registered_at BIGINT NOT NULL
);
"""

_UPSERT_SQL = """
INSERT INTO frontend_menu (frontend_id, frontend_version, menu_sha256, menu, registered_by, registered_at)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (frontend_id) DO UPDATE SET
    frontend_version = EXCLUDED.frontend_version,
    menu_sha256 = EXCLUDED.menu_sha256,
    menu = EXCLUDED.menu,
    registered_by = EXCLUDED.registered_by,
    registered_at = EXCLUDED.registered_at
"""

_COLUMNS = "frontend_id, frontend_version, menu_sha256, menu, registered_by, registered_at"
_SELECT_ONE_SQL = f"SELECT {_COLUMNS} FROM frontend_menu WHERE frontend_id = %s"
_SELECT_ALL_SQL = f"SELECT {_COLUMNS} FROM frontend_menu ORDER BY frontend_id"


def _pg_connect():
    if not _PG_DSN:
        raise RuntimeError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def configured() -> bool:
    return bool(_PG_DSN)


def menu_digest(admitted: list[dict]) -> tuple[str, str]:
    """(canonical JSON text, sha256 hex) of an admitted capability list."""
    text = canonical_json(admitted)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row(r) -> dict:
    return {"frontend_id": r[0], "frontend_version": r[1] or "", "menu_sha256": r[2],
            "menu": json.loads(r[3]), "registered_by": r[4], "registered_at": r[5]}


class PgFrontendMenuStore:
    """Last accepted menu per frontend. A store fault is an answer, not a raise."""

    def __init__(self, connect: Callable[[], Any] = _pg_connect):
        self._connect = connect
        self._migrated = False

    def _ensure(self, cur) -> None:
        if not self._migrated:
            cur.execute(_MIGRATION_SQL)
            self._migrated = True

    def save(self, frontend_id: str, frontend_version: str | None, admitted: list[dict], *,
             registered_by: str, registered_at: int) -> dict:
        text, sha = menu_digest(admitted)
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    self._ensure(cur)
                    cur.execute(_UPSERT_SQL, (frontend_id, frontend_version or "", sha, text,
                                              registered_by, registered_at))
                conn.commit()
        except Exception as exc:  # noqa: BLE001 — reported; the registration still stands
            logger.warning("frontend menu save failed for %s: %s", frontend_id, exc)
            return {"ok": False, "reason": "unreachable"}
        return {"ok": True}

    def load(self, frontend_id: str) -> dict | None:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    self._ensure(cur)
                    cur.execute(_SELECT_ONE_SQL, (frontend_id,))
                    r = cur.fetchone()
                conn.commit()
            return _row(r) if r else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("frontend menu load failed for %s: %s", frontend_id, exc)
            return None

    def load_all(self) -> list[dict]:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    self._ensure(cur)
                    cur.execute(_SELECT_ALL_SQL)
                    rows = cur.fetchall()
                conn.commit()
            return [_row(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("frontend menu load_all failed: %s", exc)
            return []
