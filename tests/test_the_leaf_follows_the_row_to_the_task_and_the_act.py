"""Spec 203b, the arms the leaf test files do not hold: the drop and the manifest adoption WRITE the
leaf's source, the backfill is a stated write, `candidates` is `[{leaf, score, evidence_ref}]` (max 3,
422 on a bad shape), the open task follows the leaf, the act refuses a stale or in-flight row, and the
decision record carries the source."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from unittest import mock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway, human_tasks as ht, ingest_status as ist, promotion  # noqa: E402
from tests.test_a_promotion_takes_row_edits_behind_its_flag import (  # noqa: E402,F401
    CORRECT, INGEST_ID, PAYLOAD, world,
)

EV = {"page": 1, "bbox": [1, 2, 3, 4]}
HEX = "cd" * 32


def _cm():
    cur = mock.MagicMock()
    cur.__enter__ = mock.Mock(return_value=cur)
    cur.__exit__ = mock.Mock(return_value=False)
    conn = mock.MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = mock.Mock(return_value=conn)
    conn.__exit__ = mock.Mock(return_value=False)
    return conn, cur


# ---- arm 1: the drop writes the source -----------------------------------------------------------
def _drop(fn, content_kind, **extra):
    conn, cur = _cm()
    with mock.patch.object(ist, "_pg_connect", return_value=conn):
        row = fn(sha256=HEX, kind="pdf", object_prefix=f"ingress-user/pdf/{HEX}/",
                 submitted_by="alice@example.com", on_behalf_of="alice@example.com",
                 source="n.pdf", content_kind=content_kind, **extra)
    return row, cur.execute.call_args[0][1]


@pytest.mark.parametrize("fn,extra", [
    (ist.record_received, {"ingest_id": "sha256:" + HEX}),
    (ist.record_duplicate_arrival, {"original": {"created_at": 1785000000000, "id": "x"}}),
])
def test_the_drop_of_a_leaf_writes_declared_and_a_pdf_drop_writes_null(fn, extra):
    row, params = _drop(fn, "PCN", **extra)
    assert params["leaf_source"] == "declared" and params["leaf_set_by"] == "alice@example.com"
    assert params["leaf_set_at"] is not None
    assert row["leaf_source"] == "declared"
    row, params = _drop(fn, "sustainment", **extra)
    assert params["leaf_source"] is None and params["leaf_set_by"] is None
    row, params = _drop(fn, None, **extra)
    assert params["leaf_source"] is None


# ---- arm 2: the manifest adoption writes the source (real update_status SQL, in sqlite) ----------
class _Cur:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.db.execute(sql.replace("%s", "?"), params)


class _Conn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, **kw):
        return _Cur(self.db)

    def commit(self):
        pass


def _adopt(row_ck, row_src, adopt):
    db = sqlite3.connect(":memory:")
    db.execute("create table ingest_status_projection (id, status, extracted_count, extracted_total,"
               " detail, case_id, extraction_ref, failure, run_id, notice_id, content_kind,"
               " leaf_source, updated_at)")
    db.execute("insert into ingest_status_projection (id, status, content_kind, leaf_source)"
               " values ('i','extracting',?,?)", (row_ck, row_src))
    with mock.patch.object(ist, "_pg_connect", return_value=_Conn(db)):
        ist.update_status("i", "review", content_kind=adopt)
    return db.execute("select content_kind, leaf_source from ingest_status_projection").fetchone()


def test_adopting_a_leaf_from_the_manifest_onto_a_null_row_leaves_declared():
    assert _adopt(None, None, "PCN") == ("PCN", "declared")


def test_adopting_a_non_leaf_leaves_the_source_null():
    assert _adopt(None, None, "sustainment") == ("sustainment", None)


def test_adoption_never_touches_a_row_that_already_has_a_kind_or_a_source():
    assert _adopt("pdn", "corrected", "pcn") == ("pdn", "corrected")
    assert _adopt("pdn", None, "pcn") == ("pdn", None)


# ---- arm 3: the backfill is stated -----------------------------------------------------------------
def test_the_backfill_names_exactly_the_leaves_and_only_a_null_source():
    sql = " ".join(ist._MIGRATION_SQL.split())
    assert ("UPDATE ingest_status_projection SET leaf_source = 'declared' WHERE leaf_source IS NULL"
            " AND kind <> 'event' AND lower(content_kind) IN ('pcn','pdn');") in sql


def test_the_retired_words_are_gone_from_the_vocabulary():
    assert ist.LEAF_SOURCES == ("declared", "title", "corrected")


# ---- arm 4: no default invented ---------------------------------------------------------------------
def test_row_leaf_on_a_leaf_with_no_source_returns_no_source():
    assert gateway._row_leaf({"content_kind": "pcn", "leaf_source": None}) == ("pcn", None, None)


# ---- arm 6: the candidates shape --------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    from types import SimpleNamespace
    user = SimpleNamespace(authz_id="svc:doc-tools", sub="svc:doc-tools", email="s@x", persona=None,
                           entitled_domains=[], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    held = []
    monkeypatch.setattr(ist, "get_row",
                        lambda i: {"id": i, "kind": "pdf", "status": "extracting", "content_kind": "pdf",
                                   "attempt": 1, "object_prefix": f"ingress-user/pdf/{HEX}/"})
    monkeypatch.setattr(ist, "hold_for_kind", lambda *a, **k: held.append(k) or True)
    with TestClient(gateway.app) as c:
        c.held = held
        yield c
    gateway.app.dependency_overrides.clear()


def _cand(leaf="pcn", score=0.5, **kw):
    return {"leaf": leaf, "score": score, "evidence_ref": dict(EV), **kw}


def _title(c, cands):
    return c.post(f"/ingest/sha256:{HEX}/title_leaf",
                  json={"doc_type": "PCN", "doc_type_source": "defaulted", "candidates": cands})


@pytest.mark.parametrize("cands", [
    [_cand(), _cand("pdn"), _cand(), _cand("pdn")],        # four
    ["pcn"],                                                # a bare string
    [{"leaf": "pcn", "score": 0.5}],                        # no evidence_ref
    [_cand(score=1.5)],                                     # score out of range
    [_cand(score=True)],                                    # a bool is not a score
    [_cand(extra=1)],                                       # unknown key
])
def test_a_bad_candidates_shape_is_422_and_holds_nothing(client, cands):
    r = _title(client, cands)
    assert r.status_code == 422, r.text
    assert client.held == []


def test_a_good_candidates_list_reaches_the_hold_as_dicts_in_order(client):
    r = _title(client, [_cand("pdn", 0.3), _cand("pcn", 0.7)])
    assert r.status_code == 200, r.text
    (k,) = client.held
    assert [c["leaf"] for c in k["candidates"]] == ["pdn", "pcn"]
    assert k["candidates"][0]["evidence_ref"]["page"] == 1


def test_hold_for_kind_drops_unknown_and_later_duplicates_and_sorts():
    conn, cur = _cm()
    cur.rowcount = 1
    with mock.patch.object(ist, "_pg_connect", return_value=conn):
        ist.hold_for_kind("i", candidates=[
            {"leaf": "pcn", "score": 0.2, "evidence_ref": EV},
            {"leaf": "zzz", "score": 0.99, "evidence_ref": EV},
            {"leaf": "pcn", "score": 0.9, "evidence_ref": EV},
            {"leaf": "pdn", "score": 0.5, "evidence_ref": {**EV, "note": None}}],
            detail="d", from_statuses=["extracting"])
    stored = [p for p in cur.execute.call_args[0][1] if isinstance(p, str) and p.startswith("[")]
    assert [c["leaf"] for c in json.loads(stored[0])] == ["pdn", "pcn"]
    assert "note" not in json.loads(stored[0])[0]["evidence_ref"]


# ---- arm 8: the open task follows the leaf ----------------------------------------------------------
@pytest.fixture
def task(monkeypatch):
    t = mock.MagicMock()
    t.registered, t.refreshed = [], []
    t.open_payload = {"content_kind": "pcn"}
    t.audience = "document_promotion:SUSTAINMENT"
    monkeypatch.setattr(ht, "task_exists", lambda i: True)
    monkeypatch.setattr(ht, "get_open_task_payload", lambda i: t.open_payload)
    monkeypatch.setattr(ht, "get_task_open_state", lambda i: {"audience": t.audience})
    monkeypatch.setattr(ht, "register_task", lambda **kw: t.registered.append(kw))
    monkeypatch.setattr(ht, "refresh_open_task", lambda i, **kw: t.refreshed.append((i, kw)) or 1)

    async def _soft(*a, **k):
        return {"mfr": "M", "notice_date": "d", "part_count": 2, "notice_id": "N1"}

    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda ref: {"m": 1})
    monkeypatch.setattr(gateway, "_soft_review_summary", _soft)
    monkeypatch.setattr(promotion, "payload_from_extraction",
                        lambda iid, row, m, ref, notice_id=None: {
                            "ingest_id": iid, "content_kind": row["content_kind"],
                            "notice_id": notice_id})
    return t


def _file(content_kind, domain="SUSTAINMENT"):
    prefix = f"ingress-user/pdf/{HEX}/"
    row = {"content_kind": content_kind, "object_prefix": prefix, "attempt": 2,
           "submitted_by": "a", "on_behalf_of": "a"}
    return asyncio.run(gateway._file_or_find_document_promotion_task(
        INGEST_ID, row, requested_by="svc:doc-tools", extraction_ref=prefix + "m.json", domain=domain))


def test_a_changed_leaf_rewrites_the_open_task_once_and_registers_nothing(task):
    tid, st = _file("pdn")
    assert st == "ALREADY_FILED" and tid == f"document_promotion:{INGEST_ID}"
    assert task.registered == []
    (i, kw), = task.refreshed
    assert i == tid and kw["payload"]["content_kind"] == "pdn" and "PDN" in kw["summary"]


def test_the_same_leaf_refreshes_nothing(task):
    assert _file("pcn")[1] == "ALREADY_FILED"
    assert task.refreshed == [] and task.registered == []


def test_a_leaf_that_moves_the_audience_is_409_and_writes_nothing(task):
    task.audience = "document_promotion:OTHER"
    with pytest.raises(fastapi.HTTPException) as e:
        _file("pdn")
    assert e.value.status_code == 409 and e.value.detail["error"] == "leaf_moves_audience"
    assert str(e.value.detail.get("message") or "").strip()
    assert task.refreshed == [] and task.registered == []


# ---- arm 9: the act guard ---------------------------------------------------------------------------
def _row(**o):
    return {"id": INGEST_ID, "content_kind": "pcn", "status": "review", "leaf_source": "title",
            "leaf_set_by": "svc:doc-tools", **o}


def _act(w):
    return w.client.post("/human_tasks/t-1/act", json={"decision": "promoted"})


def test_a_task_whose_leaf_is_stale_is_refused_and_the_act_never_runs(world, monkeypatch):
    monkeypatch.setattr(ist, "get_row", lambda i: _row(content_kind="pdn"))
    r = _act(world)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "leaf_changed", r.text
    assert str(r.json()["detail"].get("message") or "").strip(), r.text
    assert world.act_kwargs == [] and world.ledger.records == {} and world.resolved == []


@pytest.mark.parametrize("st", ["received", "extracting", "awaiting_kind", "awaiting_origin"])
def test_a_row_with_an_extraction_in_flight_is_refused(world, monkeypatch, st):
    monkeypatch.setattr(ist, "get_row", lambda i: _row(status=st))
    r = _act(world)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "extraction_in_flight", r.text
    assert str(r.json()["detail"].get("message") or "").strip(), r.text
    assert world.act_kwargs == [] and world.ledger.records == {}


def test_a_promoted_row_replays_and_the_record_carries_the_source(world, monkeypatch):
    monkeypatch.setattr(ist, "get_row", lambda i: _row(status="promoted", leaf_source="corrected",
                                                       leaf_set_by="bob"))
    r = _act(world)
    assert r.status_code == 200, r.text
    assert world.act_kwargs[0]["leaf"] == {"leaf_source": "corrected", "corrected_by": "bob"}
    (stored,) = world.ledger.records.values()
    inputs = stored["record"]["checks"][0]["inputs"]
    assert inputs["leaf_source"] == "corrected" and inputs["corrected_by"] == "bob"


def test_a_review_row_with_a_matching_leaf_proceeds(world, monkeypatch):
    monkeypatch.setattr(ist, "get_row", lambda i: _row())
    assert _act(world).status_code == 200
    (stored,) = world.ledger.records.values()
    inputs = stored["record"]["checks"][0]["inputs"]
    assert inputs["leaf_source"] == "title" and "corrected_by" not in inputs


def test_an_unreadable_row_fails_closed_with_503(world, monkeypatch):
    def boom(i):
        raise RuntimeError("pg down")

    monkeypatch.setattr(ist, "get_row", boom)
    r = _act(world)
    assert r.status_code == 503 and r.json()["detail"]["error"] == "ingest_row_unreadable", r.text
    assert str(r.json()["detail"].get("message") or "").strip(), r.text
    assert world.act_kwargs == []


def test_a_missing_row_proceeds_as_before(world, monkeypatch):
    monkeypatch.setattr(ist, "get_row", lambda i: None)
    assert _act(world).status_code == 200
    assert world.act_kwargs[0].get("leaf") is None


# ---- arm 10: build_record ---------------------------------------------------------------------------
def test_build_record_carries_the_source_only_when_given_and_the_corrector_only_when_corrected():
    subject = promotion.subject_from_payload(dict(PAYLOAD))
    kw = dict(decision="promoted", acted_by="bob", audience="document_promotion:SUSTAINMENT",
              comment="", governing={"ruleset_ref": "r", "trust_table_ref": "t"}, era="commissioning")
    none = promotion.build_record(subject, **kw)["checks"][0]["inputs"]
    assert "leaf_source" not in none and "corrected_by" not in none
    d = promotion.build_record(subject, leaf={"leaf_source": "declared", "corrected_by": None},
                               **kw)["checks"][0]["inputs"]
    assert d["leaf_source"] == "declared" and "corrected_by" not in d
    c = promotion.build_record(subject, leaf={"leaf_source": "corrected", "corrected_by": "bob"},
                               **kw)["checks"][0]["inputs"]
    assert c["leaf_source"] == "corrected" and c["corrected_by"] == "bob"
