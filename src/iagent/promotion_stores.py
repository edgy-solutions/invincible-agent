"""The concrete stores behind `promotion.act` (ADR-0041 Open §1, ruled 2026-09-30).

TWO OF FOUR EXIST. `promotion.PromotionStores` names four: the decision ledger, the graph, the
indexes and the objects. This module implements the ledger and the objects. The graph and the
indexes are left unconfigured, because no concrete writer for either exists in this repo or at
the fleet's SDK pin; `promotion.act` refuses 503 naming them, before anything is written.

THE LEDGER is the approval plane's Postgres, beside `human_task_projection` (same DSN, same
psycopg2 discipline as human_tasks.py; the async gateway wraps calls in run_in_threadpool). One
row per document: `record_id` is derived from the `ingest_id`, and both are unique, so a second
decision is an `immutable_conflict` that returns what was decided, by whom and when. The record
is stored as its canonical JSON text, so the bytes that were decided on are the bytes kept.
Nothing here updates or deletes a row: a rejection sweeps the document, never its record.

THE OBJECTS are the `/ingest` seam's S3 directory for the document. A rejection MOVES it to
`rejected/<ingest_id>/`, keeping each key's path below the directory. Every object is copied
before any is deleted, so a failure part-way leaves the originals in place, and a retry copies
again over the same keys and finishes the deletes.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

import psycopg2

from .decision_record import canonical_json
from .promotion import object_prefix_for

logger = logging.getLogger(__name__)

_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()

REJECTED_PREFIX = "rejected/"

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS document_decision_record (
    record_id TEXT PRIMARY KEY,
    ingest_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL,
    acted_by TEXT NOT NULL,
    acted_at BIGINT NOT NULL,
    record TEXT NOT NULL
);
"""

_INSERT_SQL = """
INSERT INTO document_decision_record (record_id, ingest_id, decision, acted_by, acted_at, record)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
RETURNING record_id
"""

_EXISTING_SQL = """
SELECT decision, acted_by, acted_at FROM document_decision_record
WHERE record_id = %s OR ingest_id = %s
"""


class DecisionLedgerConfigError(RuntimeError):
    """The ledger was asked to operate without its DSN. Same posture as HumanTaskConfigError."""


def _pg_connect():
    if not _PG_DSN:
        raise DecisionLedgerConfigError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def configured() -> bool:
    return bool(_PG_DSN)


def apply_migration() -> None:
    """Create document_decision_record if absent. Called at cortex-bff startup."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


class PgDecisionLedger:
    """`promotion.DecisionLedger` over Postgres. A store fault is an answer, not a raise."""

    def __init__(self, connect: Callable[[], Any] = _pg_connect):
        self._connect = connect

    def append(self, record: dict, *, acted_by: str, acted_at: int) -> dict:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(_INSERT_SQL, (record["record_id"], record["request_key"],
                                              record["outcome"], acted_by, acted_at,
                                              canonical_json(record)))
                    inserted = cur.fetchone()
                    existing = None
                    if inserted is None:
                        cur.execute(_EXISTING_SQL, (record["record_id"], record["request_key"]))
                        existing = cur.fetchone()
                conn.commit()
        except Exception as exc:  # noqa: BLE001 — reported, and `act` refuses on it
            logger.warning("decision ledger append failed for %s: %s",
                           record.get("record_id"), exc)
            return {"ok": False, "reason": "unreachable", "detail": str(exc)[:300]}
        if inserted is not None:
            return {"ok": True}
        if existing is None:
            return {"ok": False, "reason": "conflict_unreadable"}
        decision, by, at = existing
        return {"ok": False, "reason": "immutable_conflict",
                "existing": {"decision": decision, "acted_by": by, "acted_at": int(at)}}


class S3Quarantine:
    """`promotion.IngestObjects` over the seam's bucket."""

    def __init__(self, client_factory: Callable[[], Any], bucket: str):
        self._client = client_factory
        self._bucket = bucket

    def quarantine(self, ingest_id: str, object_ref: str) -> list:
        prefix = object_prefix_for(ingest_id, object_ref)
        if prefix is None:
            raise ValueError(f"object_ref {object_ref!r} is not the seam's key for {ingest_id}")
        s3 = self._client()
        keys: list = []
        token = None
        while True:
            kw = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            page = s3.list_objects_v2(**kw)
            keys += [o["Key"] for o in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                break
            token = page["NextContinuationToken"]
        moved = []
        for key in keys:
            dest = f"{REJECTED_PREFIX}{ingest_id}/{key[len(prefix):]}"
            s3.copy_object(Bucket=self._bucket, Key=dest,
                           CopySource={"Bucket": self._bucket, "Key": key})
            moved.append(dest)
        for key in keys:
            s3.delete_object(Bucket=self._bucket, Key=key)
        return moved
