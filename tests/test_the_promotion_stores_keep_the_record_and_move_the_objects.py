"""The concrete promotion stores: the ledger keeps the record, the quarantine moves the objects.

What this seals:
  * THE LEDGER NEVER EDITS A DECISION. Its only write is an INSERT that does nothing on conflict;
    no statement in the module updates or deletes. A conflict answers with the STORED decision,
    actor and time, which is what lets `promotion.act` replay rather than strand a task.
  * THE RECORD IS KEPT AS ITS CANONICAL BYTES, keyed by record_id AND ingest_id, both unique.
  * A STORE FAULT IS AN ANSWER, never a raise and never an `ok`.
  * THE QUARANTINE MOVES, NEVER DELETES FIRST. Every object is copied to `rejected/<ingest_id>/`
    before any original is deleted, so a failure part-way loses nothing and a retry finishes.
  * IT MOVES THIS DOCUMENT'S DIRECTORY AND NOTHING ELSE, across every page of the listing.

Run: uv run --frozen pytest tests/test_the_promotion_stores_keep_the_record_and_move_the_objects.py -q
"""
from __future__ import annotations

import re

import pytest

from src.iagent import promotion_stores
from src.iagent.decision_record import canonical_json

HEX = "ab" * 32
INGEST_ID = "sha256:" + HEX
PREFIX = f"ingress-user/pdf/{HEX}/"
REF = PREFIX + "pcn-4471.pdf"
RECORD = {"record_id": "dr-1", "request_key": INGEST_ID, "outcome": "promoted",
          "checks": [{"name": "human_review"}]}


# ── THE LEDGER ────────────────────────────────────────────────────────────────────────────────

class Cursor:
    def __init__(self, rows):
        self.rows, self.executed = list(rows), []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.rows.pop(0)


class Conn:
    def __init__(self, cursor):
        self.cur, self.committed = cursor, False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True


def _ledger(*rows):
    cur = Cursor(rows)
    conn = Conn(cur)
    return promotion_stores.PgDecisionLedger(connect=lambda: conn), cur, conn


def test_a_first_decision_is_INSERTED_as_its_canonical_bytes_and_answers_ok():
    ledger, cur, conn = _ledger(("dr-1",))
    assert ledger.append(RECORD, acted_by="bob", acted_at=1_000) == {"ok": True}
    (sql, params), = cur.executed
    assert sql == promotion_stores._INSERT_SQL
    assert params == ("dr-1", INGEST_ID, "promoted", "bob", 1_000, canonical_json(RECORD))
    assert conn.committed


def test_a_second_decision_answers_WHAT_WAS_DECIDED_by_whom_and_when():
    ledger, cur, _ = _ledger(None, ("rejected", "al", 5))
    out = ledger.append(RECORD, acted_by="bob", acted_at=1_000)
    assert out == {"ok": False, "reason": "immutable_conflict",
                   "existing": {"decision": "rejected", "acted_by": "al", "acted_at": 5}}
    assert cur.executed[1] == (promotion_stores._EXISTING_SQL, ("dr-1", INGEST_ID))


def test_a_conflict_whose_row_cannot_be_read_is_NOT_a_conflict_answer():
    ledger, _, _ = _ledger(None, None)
    out = ledger.append(RECORD, acted_by="bob", acted_at=1)
    assert out["ok"] is False and out["reason"] == "conflict_unreadable"


def test_a_STORE_FAULT_is_an_answer_never_a_raise():
    def connect():
        raise RuntimeError("pg down")

    out = promotion_stores.PgDecisionLedger(connect=connect).append(RECORD, acted_by="b",
                                                                     acted_at=1)
    assert out["ok"] is False and out["reason"] == "unreachable"


def test_an_unset_DSN_refuses_to_connect(monkeypatch):
    monkeypatch.setattr(promotion_stores, "_PG_DSN", "")
    assert promotion_stores.configured() is False
    with pytest.raises(promotion_stores.DecisionLedgerConfigError):
        promotion_stores._pg_connect()


_SQL = {n: v for n, v in vars(promotion_stores).items() if n.endswith("_SQL")}


def test_the_statement_population_is_the_three_known():
    assert set(_SQL) == {"_MIGRATION_SQL", "_INSERT_SQL", "_EXISTING_SQL"}


@pytest.mark.parametrize("name", sorted(_SQL))
def test_NO_statement_updates_or_deletes_a_decision(name):
    assert not re.search(r"\b(UPDATE|DELETE|TRUNCATE|DROP)\b", _SQL[name], re.I)


def test_the_insert_does_NOTHING_on_conflict_and_the_keys_are_unique():
    assert re.search(r"ON CONFLICT DO NOTHING", promotion_stores._INSERT_SQL)
    assert re.search(r"record_id TEXT PRIMARY KEY", promotion_stores._MIGRATION_SQL)
    assert re.search(r"ingest_id TEXT NOT NULL UNIQUE", promotion_stores._MIGRATION_SQL)


def test_the_sql_twin_mirrors_the_migration_that_runs():
    from pathlib import Path
    twin = Path(__file__).resolve().parents[1] / "sql" / "create_document_decision_record.sql"
    body = "\n".join(l for l in twin.read_text(encoding="utf-8").splitlines()
                     if not l.startswith("--")).strip()
    assert body == promotion_stores._MIGRATION_SQL.strip()


# ── THE QUARANTINE ────────────────────────────────────────────────────────────────────────────

class S3:
    def __init__(self, keys, page=1000, fail_copy_at=None):
        self.objects = {k: f"bytes:{k}" for k in keys}
        self.page, self.fail_copy_at, self.log = page, fail_copy_at, []

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        chunk = keys[start:start + self.page]
        more = start + self.page < len(keys)
        out = {"Contents": [{"Key": k} for k in chunk], "IsTruncated": more}
        if more:
            out["NextContinuationToken"] = str(start + self.page)
        return out

    def copy_object(self, *, Bucket, Key, CopySource):
        if self.fail_copy_at is not None and len(
                [e for e in self.log if e[0] == "copy"]) == self.fail_copy_at:
            raise RuntimeError("minio down")
        self.log.append(("copy", CopySource["Key"], Key))
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_object(self, *, Bucket, Key):
        self.log.append(("delete", Key))
        del self.objects[Key]


OTHER = f"ingress-user/pdf/{'cd' * 32}/other.pdf"
MINE = [REF, PREFIX + "manifest.json", PREFIX + "pages/p1.png"]


def _q(s3):
    return promotion_stores.S3Quarantine(lambda: s3, "processing-artifacts")


def test_the_documents_directory_is_MOVED_whole_and_nothing_else_is_touched():
    s3 = S3(MINE + [OTHER])
    moved = _q(s3).quarantine(INGEST_ID, REF)
    dest = sorted(f"rejected/{INGEST_ID}/{k[len(PREFIX):]}" for k in MINE)
    assert sorted(moved) == dest
    assert sorted(s3.objects) == sorted(dest + [OTHER])
    assert s3.objects[f"rejected/{INGEST_ID}/pcn-4471.pdf"] == f"bytes:{REF}"


def test_EVERY_copy_precedes_ANY_delete():
    s3 = S3(MINE)
    _q(s3).quarantine(INGEST_ID, REF)
    kinds = [e[0] for e in s3.log]
    assert kinds == ["copy"] * 3 + ["delete"] * 3


def test_a_failure_part_way_LOSES_NOTHING_and_a_retry_finishes():
    s3 = S3(MINE, fail_copy_at=1)
    with pytest.raises(RuntimeError):
        _q(s3).quarantine(INGEST_ID, REF)
    assert all(k in s3.objects for k in MINE)
    s3.fail_copy_at = None
    _q(s3).quarantine(INGEST_ID, REF)
    assert not any(k in s3.objects for k in MINE)
    assert len([k for k in s3.objects if k.startswith("rejected/")]) == 3


def test_EVERY_page_of_the_listing_is_moved():
    s3 = S3(MINE, page=1)
    assert len(_q(s3).quarantine(INGEST_ID, REF)) == 3
    assert not any(k.startswith(PREFIX) for k in s3.objects)


def test_a_second_run_after_completion_moves_nothing_and_deletes_nothing():
    s3 = S3(MINE)
    _q(s3).quarantine(INGEST_ID, REF)
    s3.log.clear()
    assert _q(s3).quarantine(INGEST_ID, REF) == [] and s3.log == []


@pytest.mark.parametrize("ref", [OTHER, "sustainment/pdf/" + HEX + "/x.pdf"])
def test_an_object_ref_that_is_not_the_documents_is_REFUSED_and_nothing_moves(ref):
    s3 = S3(MINE + [OTHER])
    with pytest.raises(ValueError):
        _q(s3).quarantine(INGEST_ID, ref)
    assert s3.log == []
