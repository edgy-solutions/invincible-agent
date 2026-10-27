"""GET /ingest/mine (architect ruling 2026-10-16): the caller's own drops (dropper or
on_behalf_of), paged, newest first, in the status route's summary shape. The rail reads it on load
and merges with live entries; browser storage is a cache, never the record.

Harness: TestClient(gateway.app) with get_current_user overridden. `ingest_status._pg_connect` is
swapped for an in-memory sqlite table, so `list_mine`'s REAL SQL runs (a stubbed listing would pass
whatever the predicate, order or cursor said). A recording wrapper keeps the statement text and
parameters for the parameterization arms.

WHAT THESE DEFEND:
  * scope: submitted_by OR on_behalf_of = caller; another caller's rows and event rows never appear;
  * order: created_at DESC, id DESC (id breaks a tie);
  * paging: `next` chains by keyset cursor, no duplicates, last page `next` null;
  * a malformed cursor is 422 invalid_cursor; no drops is 200 {items: [], next: null};
  * each item has exactly the status route's key set (derived by calling it), a duplicate's stage
    is its original's;
  * every value is a bound parameter; the statement carries the event exclusion and the order.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_COLS = ("id", "sha256", "kind", "object_prefix", "submitted_by", "on_behalf_of", "source",
         "status", "extracted_count", "extracted_total", "duplicate_of", "detail", "created_at",
         "updated_at", "origin_suggestion", "content_kind", "case_id", "extraction_ref", "failure",
         "run_id", "attempt", "notice_id", "leaf_source", "leaf_candidates", "leaf_set_by",
         "leaf_set_at", "review_generation", "hold_reason")


class _Rec:
    """An in-memory sqlite table behind the psycopg2 surface list_mine / get_status_for use; it
    records every (sql, params) executed."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(f"CREATE TABLE ingest_status_projection ({', '.join(_COLS)})")
        self.log: list[tuple[str, tuple]] = []

    def seed(self, id, *, by="alice", obo=None, kind="pdf", created=1000, status="received",
             duplicate_of=None, case_id=None):
        row = dict.fromkeys(_COLS)
        row.update(id=id, sha256=id, kind=kind, object_prefix=f"p/{id}/", submitted_by=by,
                   on_behalf_of=obo, status=status, created_at=created, updated_at=created,
                   duplicate_of=duplicate_of, case_id=case_id, attempt=1)
        self.db.execute(
            f"INSERT INTO ingest_status_projection VALUES ({', '.join('?' * len(_COLS))})",
            [row[c] for c in _COLS])

    @contextmanager
    def connect(self):
        rec = self

        class _Cur:
            def execute(self, sql, params=()):
                rec.log.append((sql, tuple(params)))
                self.c = rec.db.execute(sql.replace("%s", "?"), tuple(params))

            def fetchall(self):
                return self.c.fetchall()

            def fetchone(self):
                return self.c.fetchone()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _Conn:
            def cursor(self, **kw):
                return _Cur()

        yield _Conn()


@pytest.fixture
def pg(monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(ist, "_pg_connect", rec.connect)
    return rec


def _client(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def alice():
    yield from _client("alice")


@pytest.fixture
def nobody():
    yield from _client("nobody")


def _ids(resp):
    return [i["ingest_id"] for i in resp.json()["items"]]


def test_scope_is_the_callers_documents_only(alice, pg):
    pg.seed("own", by="alice", created=3)
    pg.seed("delegated", by="svc:x", obo="alice", created=2)
    pg.seed("event", by="alice", kind="event", created=4)
    pg.seed("bobs", by="bob", created=5)
    r = alice.get("/ingest/mine")
    assert r.status_code == 200
    assert _ids(r) == ["own", "delegated"]


def test_order_is_newest_first_and_id_breaks_a_tie(alice, pg):
    pg.seed("a-old", created=1)
    pg.seed("b-tie", created=5)
    pg.seed("c-tie", created=5)
    pg.seed("d-new", created=9)
    assert _ids(alice.get("/ingest/mine")) == ["d-new", "c-tie", "b-tie", "a-old"]


def test_paging_chains_by_cursor_with_no_duplicates(alice, pg):
    for n, created in (("r1", 5), ("r2", 5), ("r3", 4), ("r4", 1)):
        pg.seed(n, created=created)
    seen, cursor, pages = [], None, 0
    while True:
        url = "/ingest/mine?limit=1" + (f"&before={cursor}" if cursor else "")
        body = alice.get(url).json()
        pages += 1
        assert len(body["items"]) == 1
        seen += [i["ingest_id"] for i in body["items"]]
        cursor = body["next"]
        if cursor is None:
            break
        assert pages < 10
    assert seen == ["r2", "r1", "r3", "r4"]
    assert len(set(seen)) == len(seen)
    assert pages == 4


def test_a_full_last_page_has_next_null(alice, pg):
    pg.seed("x", created=2)
    pg.seed("y", created=1)
    body = alice.get("/ingest/mine?limit=2").json()
    assert [i["ingest_id"] for i in body["items"]] == ["x", "y"]
    assert body["next"] is None


@pytest.mark.parametrize("cursor", ["abc", "x|y", "12", "|a", "12|"])
def test_a_malformed_cursor_is_422_invalid_cursor(alice, pg, cursor):
    r = alice.get("/ingest/mine", params={"before": cursor})
    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "invalid_cursor"}
    assert pg.log == []


def test_a_caller_with_no_drops_gets_an_empty_page_not_404(nobody, pg):
    pg.seed("own", by="alice")
    r = nobody.get("/ingest/mine")
    assert r.status_code == 200
    assert r.json() == {"items": [], "next": None}


def test_items_have_exactly_the_status_routes_key_set(alice, pg):
    pg.seed("orig", created=1, status="extracting")
    pg.seed("dup", created=2, status=ist.DUPLICATE, duplicate_of="orig")
    items = {i["ingest_id"]: i for i in alice.get("/ingest/mine").json()["items"]}
    for ingest_id in ("orig", "dup"):
        status_body = alice.get(f"/ingest/{ingest_id}/status").json()
        assert set(items[ingest_id]) == set(status_body)
        assert items[ingest_id] == status_body
    assert items["dup"]["stage"] == items["orig"]["stage"] == "extracting"
    assert items["dup"]["duplicate"]["of_ingest_id"] == "orig"


def test_the_sql_is_parameterized_and_carries_the_event_exclusion_and_order(pg):
    caller = "alice-secret-id"
    pg.seed("own", by=caller, created=7)
    ist.list_mine(caller_id=caller, limit=3, before=(9, "zzz"))
    sql, params = pg.log[-1]
    flat = " ".join(sql.split())
    assert caller not in sql and "zzz" not in sql
    assert params == (caller, caller, 9, "zzz", 3)
    assert "kind <> 'event'" in flat
    assert "submitted_by = %s OR on_behalf_of = %s" in flat
    assert "ORDER BY created_at DESC, id DESC" in flat
    assert "(created_at, id) < (%s, %s)" in flat
    assert "OFFSET" not in flat.upper()
    assert re.search(r"LIMIT %s$", flat)


def test_an_empty_caller_lists_nothing_and_does_not_query(pg):
    assert ist.list_mine(caller_id="", limit=5) == []
    assert pg.log == []
