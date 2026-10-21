"""A refused review and a stalled extraction must reach the row (architect ruling 2026-10-16).

doc-tools logs any non-2xx from POST /ingest/{id}/stage and still ends its run SUCCESS. Before this
change a review refused 422 `no_declared_domain` wrote nothing, so the row sat at `extracting` for
ever: the watchdog watched only `received`, and POST /ingest/{id}/retry requires `failed`. Four live
rows were stranded exactly so -- content_kind NULL on the row while the versioned extraction manifest
carried `metadata.content_kind = "pcn"`.

Harness: TestClient(gateway.app) with get_current_user overridden; `ingest_status._pg_connect` is an
in-memory sqlite table, so the REAL get_row / update_status / fail_stalled / list_mine / get_status_for
SQL runs (a stubbed writer would pass whatever the statement said). `jsonb_build_object` and the
`::type` casts are the only Postgres-isms in the watchdog statement; the double supplies the first as
a sqlite function and strips the second.

WHAT THESE DEFEND (arms named for the behaviour):
  * a review on a row with a NULL content_kind adopts the manifest's REGISTERED kind (task filed, row
    at review, kind persisted); an UNREGISTERED manifest kind is not adopted, and a non-NULL row kind
    is never overridden;
  * a 4xx refusal of review writes `failed` (reason_code = the refusal's error, step review) and the
    caller still sees the original 422; a 5xx writes nothing; a failed write cannot swallow the 422;
  * the watchdog fails a stale `extracting` row naming the stage, leaves a young one, a `review`
    row, an `awaiting_origin` row and an event row alone, and leaves `received` exactly as it was;
    a row timed out at extracting still accepts a late review POST;
  * both status routes carry `content_kind` (None when NULL); update_status's content_kind writes
    only where the column is NULL.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from contextlib import contextmanager

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_COLS = ("id", "sha256", "kind", "object_prefix", "submitted_by", "on_behalf_of", "source",
         "status", "extracted_count", "extracted_total", "duplicate_of", "detail", "created_at",
         "updated_at", "origin_suggestion", "content_kind", "case_id", "extraction_ref", "failure",
         "run_id", "attempt", "notice_id", "leaf_source", "leaf_candidates", "leaf_set_by",
         "leaf_set_at")

_NOW_MS = 10_000_000_000


class _Pg:
    """An in-memory sqlite table behind the psycopg2 surface ingest_status uses."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row

        def _jbo(*kv):
            return json.dumps(dict(zip(kv[0::2], kv[1::2])))
        self.db.create_function("jsonb_build_object", -1, _jbo)
        self.db.execute(f"CREATE TABLE ingest_status_projection ({', '.join(_COLS)})")

    def seed(self, hexchar, *, status="received", kind="pdf", content_kind=None, updated=1000,
             run_id=None, failure=None):
        id_ = "sha256:" + hexchar * 64
        row = dict.fromkeys(_COLS)
        row.update(id=id_, sha256=id_, kind=kind,
                   object_prefix=f"ingress-user/{kind}/{hexchar * 64}/",
                   submitted_by="alice", on_behalf_of="alice", status=status,
                   created_at=updated, updated_at=updated, attempt=1, content_kind=content_kind,
                   run_id=run_id, failure=json.dumps(failure) if failure else None)
        self.db.execute(
            f"INSERT INTO ingest_status_projection VALUES ({', '.join('?' * len(_COLS))})",
            [row[c] for c in _COLS])
        return id_

    def row(self, id_):
        r = self.db.execute("SELECT * FROM ingest_status_projection WHERE id = ?", (id_,)).fetchone()
        d = dict(r)
        d["failure"] = json.loads(d["failure"]) if d["failure"] else None
        return d

    @contextmanager
    def connect(self):
        pg = self

        class _Cur:
            def execute(self, sql, params=()):
                sql = re.sub(r"::\w+", "", sql).replace("%s", "?")
                self.c = pg.db.execute(sql, tuple(params))

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

            def commit(self):
                pg.db.commit()

        yield _Conn()


@pytest.fixture
def pg(monkeypatch):
    p = _Pg()
    monkeypatch.setattr(ist, "_pg_connect", p.connect)
    return p


def _client(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def doc_tools():
    yield from _client("svc:doc-tools")


@pytest.fixture
def alice():
    yield from _client("alice")


_DOMAINS = {"pcn": "sustainment", "other": "quality"}


def _rig(monkeypatch, *, manifest_kind="pcn", registered=("pcn",), manifest_raises=None):
    """Registry answers only for `registered`; the manifest carries `manifest_kind`; the task
    store is a recording stub. Returns the list of registered tasks."""
    monkeypatch.setattr(ck, "by_kind", lambda kind: type("Reg", (), {"domain": _DOMAINS.get(kind, "x")})()
                        if kind in registered else None)

    def _read(key):
        if manifest_raises is not None:
            raise manifest_raises
        iid = "sha256:" + key.split("/")[2]
        m = {"doc_id": "N-1", "filename": "doc.pdf", "source_key": key.rsplit("generated", 1)[0] + "doc.pdf",
             "pipeline_version": "doc-tools@61f74dc", "ingest_id": iid,
             "provenance": {"standing": "supervised", "ingest_id": iid}}
        if manifest_kind is not None:
            m["metadata"] = {"content_kind": manifest_kind}
        return m
    monkeypatch.setattr(gateway, "_read_extraction_manifest", _read)
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: {"review_items": [{"field_path": "parts[0].affected_mpn", "value": "X"}]})  # zero-row gate, ruling 2026-10-17
    monkeypatch.setattr(ht, "task_exists", lambda task_id: False)
    tasks: list = []
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: tasks.append(kw) or {"task_id": kw["task_id"], "recipients": ["x"]})
    return tasks


def _ref(pg, id_):
    return pg.row(id_)["object_prefix"] + "generated/doc_pdf/doc-tools@61f74dc/manifest.json"


def _review(doc_tools, pg, id_, **extra):
    return doc_tools.post(f"/ingest/{id_}/stage",
                          json={"stage": "review", "extraction_ref": _ref(pg, id_), **extra})


# ===========================================================================
# Review adopts the manifest's declared kind
# ===========================================================================
def test_a_review_on_a_null_kind_row_adopts_the_registered_manifest_kind(doc_tools, pg, monkeypatch):
    tasks = _rig(monkeypatch)
    id_ = pg.seed("a", status="extracting", content_kind=None)
    r = _review(doc_tools, pg, id_)
    assert r.status_code == 200, r.text
    assert len(tasks) == 1 and tasks[0]["audience"].endswith(":SUSTAINMENT")
    row = pg.row(id_)
    assert row["status"] == "review"
    assert row["content_kind"] == "pcn"


def test_a_manifest_kind_that_is_unregistered_is_not_adopted_and_the_refusal_fails_the_row(
        doc_tools, pg, monkeypatch):
    tasks = _rig(monkeypatch, manifest_kind="mystery", registered=("pcn",))
    id_ = pg.seed("b", status="extracting", content_kind=None)
    r = _review(doc_tools, pg, id_, run_id="run-9")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "no_declared_domain"
    assert tasks == []
    row = pg.row(id_)
    assert row["status"] == "failed"
    assert row["content_kind"] is None
    f = row["failure"]
    assert f["reason_code"] == "no_declared_domain" and f["step"] == "review"
    assert f["run_id"] == "run-9"
    assert f["reason"].startswith("review refused (422): no_declared_domain")
    assert row["detail"] == f["reason"]


def test_a_non_null_row_kind_is_not_overridden_by_a_different_manifest_kind(doc_tools, pg, monkeypatch):
    tasks = _rig(monkeypatch, manifest_kind="other", registered=("pcn", "other"))
    id_ = pg.seed("c", status="extracting", content_kind="pcn")
    r = _review(doc_tools, pg, id_)
    assert r.status_code == 200, r.text
    # the AUDIENCE is the row's kind's domain (pcn -> sustainment), not the manifest kind's (quality)
    assert tasks[0]["audience"].endswith(":SUSTAINMENT")
    assert pg.row(id_)["content_kind"] == "pcn"


def test_an_unreadable_manifest_at_the_adoption_step_leaves_the_real_refusal_to_find_or_file(
        doc_tools, pg, monkeypatch):
    _rig(monkeypatch, manifest_raises=RuntimeError("store down"))
    id_ = pg.seed("d", status="extracting", content_kind=None)
    r = _review(doc_tools, pg, id_)
    # adoption swallowed the read error; find-or-file then refused for want of any kind
    assert r.status_code == 422 and r.json()["detail"]["error"] == "no_declared_domain"
    assert pg.row(id_)["status"] == "failed"


# ===========================================================================
# Refusal handling
# ===========================================================================
def test_a_503_from_find_or_file_does_not_move_the_row_to_failed(doc_tools, pg, monkeypatch):
    _rig(monkeypatch)

    async def _boom(*a, **kw):
        raise gateway.HTTPException(status_code=503, detail={"error": "artifact_store_unreachable"})
    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", _boom)
    id_ = pg.seed("e", status="extracting", content_kind="pcn")
    r = _review(doc_tools, pg, id_)
    assert r.status_code == 503
    assert pg.row(id_)["status"] == "extracting"


def test_a_failed_write_that_itself_raises_still_returns_the_original_422(doc_tools, pg, monkeypatch):
    _rig(monkeypatch, manifest_kind="mystery")
    id_ = pg.seed("f", status="extracting", content_kind=None)

    def _boom(*a, **kw):
        raise RuntimeError("pg down")
    monkeypatch.setattr(ist, "update_status", _boom)
    r = _review(doc_tools, pg, id_)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "no_declared_domain"


def test_a_4xx_refusal_with_a_non_conforming_error_code_falls_back_to_review_refused(
        doc_tools, pg, monkeypatch):
    _rig(monkeypatch)

    async def _boom(*a, **kw):
        raise gateway.HTTPException(status_code=422, detail="Not A Code!")
    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", _boom)
    id_ = pg.seed("1", status="extracting", content_kind="pcn")
    assert _review(doc_tools, pg, id_).status_code == 422
    f = pg.row(id_)["failure"]
    assert f["reason_code"] == "review_refused" and f["step"] == "review"


# ===========================================================================
# Watchdog
# ===========================================================================
def test_the_watchdog_fails_a_stale_extracting_row_and_only_that(pg):
    old = _NOW_MS - 4000 * 1000
    stale = pg.seed("2", status="extracting", updated=old, run_id="run-x")
    young = pg.seed("3", status="extracting", updated=_NOW_MS - 10 * 1000)
    review = pg.seed("4", status="review", updated=old)
    awaiting = pg.seed("5", status="awaiting_origin", updated=old)
    event = pg.seed("6", status="extracting", kind="event", updated=old)
    ids = ist.fail_stalled(stage=ist.EXTRACTING, older_than_seconds=3600, now_ms=_NOW_MS)
    assert ids == [stale]
    row = pg.row(stale)
    assert row["status"] == "failed"
    assert row["failure"]["reason_code"] == "timeout" and row["failure"]["step"] == "extracting"
    assert row["failure"]["run_id"] == "run-x"
    assert row["detail"] == "no stage move was reported within 3600 seconds of entering extracting"
    for untouched, status in ((young, "extracting"), (review, "review"),
                              (awaiting, "awaiting_origin"), (event, "extracting")):
        assert pg.row(untouched)["status"] == status


def test_received_behaviour_is_unchanged_step_received_and_todays_reason_text(pg):
    old = _NOW_MS - 700 * 1000
    stale = pg.seed("7", status="received", updated=old)
    extracting = pg.seed("8", status="extracting", updated=old)
    assert ist.fail_stale_received(older_than_seconds=600, now_ms=_NOW_MS) == [stale]
    row = pg.row(stale)
    assert row["failure"]["step"] == "received" and row["failure"]["reason_code"] == "timeout"
    assert row["detail"] == "no stage move was reported within 600 seconds of arrival"
    assert pg.row(extracting)["status"] == "extracting"


def test_fail_stalled_refuses_a_stage_that_waits_on_a_human():
    for stage in (ist.REVIEW, ist.AWAITING_ORIGIN, ist.FAILED):
        with pytest.raises(ValueError):
            ist.fail_stalled(stage=stage, older_than_seconds=1)


def test_the_tick_runs_each_enabled_stage_and_a_non_positive_timeout_skips_only_its_stage(monkeypatch):
    seen = []
    monkeypatch.setattr(ist, "fail_stalled",
                        lambda *, stage, older_than_seconds, now_ms=None:
                        seen.append((stage, older_than_seconds)) or [stage])
    assert asyncio.run(gateway._ingest_watchdog_tick(321, 654)) == ["received", "extracting"]
    assert seen == [("received", 321), ("extracting", 654)]
    seen.clear()
    assert asyncio.run(gateway._ingest_watchdog_tick(0, 654)) == ["extracting"]
    assert seen == [("extracting", 654)]
    seen.clear()
    assert asyncio.run(gateway._ingest_watchdog_tick(321, 0)) == ["received"]


def test_the_watchdog_is_off_only_when_both_timeouts_are_non_positive(monkeypatch):
    from unittest import mock
    monkeypatch.setenv("INGEST_RECEIVED_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("INGEST_EXTRACTING_TIMEOUT_SECONDS", "0")
    with mock.patch.object(gateway.asyncio, "create_task") as ct:
        assert gateway._start_ingest_watchdog() is None
    ct.assert_not_called()

    started = []

    def _fake(coro):
        started.append(coro.cr_frame.f_locals.copy())
        coro.close()
        return mock.Mock()
    monkeypatch.setenv("INGEST_RECEIVED_TIMEOUT_SECONDS", "0")
    monkeypatch.delenv("INGEST_EXTRACTING_TIMEOUT_SECONDS")
    with mock.patch.object(gateway.asyncio, "create_task", _fake):
        assert gateway._start_ingest_watchdog() is not None
    assert started[0]["extracting_timeout_s"] == 3600


def test_a_row_timed_out_at_extracting_still_accepts_a_late_review_post(doc_tools, pg, monkeypatch):
    tasks = _rig(monkeypatch)
    id_ = pg.seed("9", status="extracting", content_kind="pcn", updated=_NOW_MS - 4000 * 1000)
    assert ist.fail_stalled(stage=ist.EXTRACTING, older_than_seconds=3600, now_ms=_NOW_MS) == [id_]
    assert pg.row(id_)["status"] == "failed"
    r = _review(doc_tools, pg, id_)
    assert r.status_code == 200, r.text
    row = pg.row(id_)
    assert row["status"] == "review" and row["failure"] is None
    assert len(tasks) == 1


# ===========================================================================
# Status body, update_status
# ===========================================================================
def test_both_status_routes_carry_content_kind_none_when_null(alice, pg):
    kinded = pg.seed("a", content_kind="pcn", updated=2000)
    bare = pg.seed("b", content_kind=None, updated=1000)
    one = alice.get(f"/ingest/{kinded}/status").json()
    assert one["content_kind"] == "pcn"
    assert "content_kind" in alice.get(f"/ingest/{bare}/status").json()
    assert alice.get(f"/ingest/{bare}/status").json()["content_kind"] is None
    items = {i["ingest_id"]: i for i in alice.get("/ingest/mine").json()["items"]}
    assert items[kinded]["content_kind"] == "pcn"
    assert "content_kind" in items[bare] and items[bare]["content_kind"] is None


def test_update_status_content_kind_fills_a_null_column_and_never_overwrites_a_set_one(pg):
    bare = pg.seed("c", status="extracting", content_kind=None)
    kinded = pg.seed("d", status="extracting", content_kind="pcn")
    ist.update_status(bare, ist.REVIEW, content_kind="notice")
    ist.update_status(kinded, ist.REVIEW, content_kind="notice")
    assert pg.row(bare)["content_kind"] == "notice"
    assert pg.row(kinded)["content_kind"] == "pcn"
    other = pg.seed("e", status="extracting", content_kind="pcn")
    ist.update_status(other, ist.REVIEW)
    assert pg.row(other)["content_kind"] == "pcn"
