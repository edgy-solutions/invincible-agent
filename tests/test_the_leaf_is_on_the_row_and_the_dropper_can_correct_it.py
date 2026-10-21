"""Spec 203: the leaf is on the row, doc-tools' title read dispatches on it, and the dropper (or the
steward) can correct it (architect ruling 2026-10-21).

  * `POST /ingest/{id}/title_leaf` (svc:doc-tools only): a confident title (pcn|pdn from the TITLE)
    is written as `leaf_source=title`; a declared or corrected leaf beats it; a non-leaf-capable row
    is left alone; no confident leaf holds the row at `awaiting_kind` with the candidates.
  * `POST /ingest/{id}/leaf` (the review gate): `corrected`, dispatched on the stage; the leaf can
    change until promotion (ruling 2026-10-21 "Leaf, final shape", spec 203b).
  * the status body carries `leaf` / `leaf_source` / `leaf_candidates` for a leaf-capable row ONLY.
  * the stage route refuses a held row; a title is written by `title_leaf` alone (no backstop).

THE WRITES ARE THE REAL ONES. `ingest_status.set_leaf` and `hold_for_kind` run as written against a
small in-memory interpreter of exactly their UPDATE statements (`_FakePg`), so the arms defend the
guard in the SQL (`leaf_source IS NULL OR leaf_source = 'title'`, `status = ANY`, `kind <> 'event'`),
not a double that restates it. Everything the tests patch is restored by monkeypatch.

Run: PYTHONPATH="src;." python -m pytest tests/test_the_leaf_is_on_the_row_and_the_dropper_can_correct_it.py -q -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import types

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_HEX = "a" * 64
ID = "sha256:" + _HEX
OTHER_ID = "sha256:" + "b" * 64
PREFIX = f"ingress-user/pdf/{_HEX}/"
REF = f"{PREFIX}generated/doc_pdf/doc-tools@61f74dc/manifest.json"
ALICE = "alice@example.com"
BOB = "bob@example.com"
DOCTOOLS = "svc:doc-tools"
_REAL_FILE_PROMOTION_IF_READY = gateway._file_promotion_if_ready
_REAL_FILE_TASK = gateway._file_or_find_document_promotion_task


# --------------------------------------------------------------------------------------------
# the store: an in-memory interpreter of set_leaf / hold_for_kind / list_pending_retries SQL
# --------------------------------------------------------------------------------------------
class _FakeCur:
    def __init__(self, db):
        self.db = db
        self._one = None
        self._all = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        sql = " ".join(sql.split())
        params = list(params)
        if sql.startswith("UPDATE ingest_status_projection SET "):
            body = sql[len("UPDATE ingest_status_projection SET "):]
            set_part, rest = body.split(" WHERE ", 1)
            where = rest.split(" RETURNING")[0]
            returning = " RETURNING" in rest
            sets = re.findall(
                r"(\w+) = (COALESCE\(%s, \w+\)|%s|NULL|attempt \+ 1|'\w+')", set_part)
            assigned = []
            for col, expr in sets:
                if expr == "%s":
                    assigned.append((col, params.pop(0)))
                elif expr.startswith("COALESCE"):
                    v = params.pop(0)
                    assigned.append((col, v if v is not None else ("__keep__",)))
                elif expr == "NULL":
                    assigned.append((col, None))
                elif expr == "attempt + 1":
                    assigned.append((col, ("__incr__",)))
                else:
                    assigned.append((col, expr.strip("'")))
            assert where.startswith("id = %s AND status = ANY(%s) AND kind <> 'event'"), where
            row_id, statuses = params.pop(0), params.pop(0)
            guard_title = "leaf_source IS NULL OR leaf_source = 'title'" in where
            # hold_for_kind's guard: never hold a row that already carries a leaf.
            guard_no_leaf = "content_kind IS NULL OR NOT (content_kind = ANY(%s))" in where
            leaves = params.pop(0) if guard_no_leaf else ()
            assert not params, params
            r = self.db.rows.get(row_id)
            hit = (r is not None and r["status"] in statuses and r["kind"] != "event"
                   and (not guard_title or r.get("leaf_source") in (None, "title"))
                   and (not guard_no_leaf or r.get("content_kind") not in leaves))
            self.rowcount = 1 if hit else 0
            self._one = None
            if hit:
                for col, v in assigned:
                    if v == ("__keep__",):
                        continue
                    if v == ("__incr__",):
                        r[col] = r[col] + 1
                    else:
                        r[col] = v
                self._one = copy.deepcopy(r) if returning else None
        elif "WHERE status = 'received' AND attempt > 1" in sql:
            self._all = [
                (r["id"], r["attempt"], r["kind"], r.get("content_kind"), r["object_prefix"],
                 r["sha256"], r.get("run_id"), r["updated_at"])
                for r in self.db.rows.values()
                if r["status"] == "received" and r["attempt"] > 1 and r["kind"] != "event"]
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _FakeConn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, **kw):
        return _FakeCur(self.db)

    def commit(self):
        pass


class DB:
    def __init__(self):
        self.rows: dict = {}
        self.filed: list = []
        self.file_error: HTTPException | None = None
        self.stale_first_read: dict | None = None
        self.registered: list = []
        self.refreshed: list = []

    def add(self, id=ID, **kw):
        row = {"id": id, "sha256": id.split(":")[1], "kind": "pdf", "object_prefix": PREFIX,
               "submitted_by": ALICE, "on_behalf_of": ALICE, "source": "n.pdf",
               "status": "extracting", "extracted_count": None, "extracted_total": None,
               "duplicate_of": None, "detail": None, "created_at": 1, "updated_at": 1,
               "content_kind": "pdf", "extraction_ref": None, "failure": None, "run_id": None,
               "attempt": 1, "notice_id": None, "leaf_source": None, "leaf_candidates": None,
               "leaf_set_by": None, "leaf_set_at": None, "origin_suggestion": None,
               "case_id": None}
        row.update(kw)
        self.rows[id] = row
        return row

    def snap(self, id=ID):
        return copy.deepcopy(self.rows[id])

    # readers (the real ones run SELECTs; these return what they would, with the same parsing)
    def _out(self, r):
        out = copy.deepcopy(r)
        out["leaf_candidates"] = ist._parse_candidates(out.get("leaf_candidates"))
        return out

    def get_row(self, ingest_id):
        if self.stale_first_read is not None:
            stale, self.stale_first_read = self.stale_first_read, None
            return stale
        r = self.rows.get(ingest_id)
        return self._out(r) if r else None

    def get_status_unscoped(self, ingest_id):
        r = self.rows.get(ingest_id)
        return self._out(r) if r else None

    def get_status_for(self, ingest_id, caller_id=None):
        r = self.rows.get(ingest_id)
        if not r or caller_id not in (r["submitted_by"], r["on_behalf_of"]):
            return None
        return self._out(r)

    def update_status(self, ingest_id, status, **kw):
        r = self.rows[ingest_id]
        r["status"] = status
        for k in ("extraction_ref", "notice_id", "detail", "run_id"):
            if kw.get(k) is not None:
                r[k] = kw[k]
        if kw.get("content_kind") and not r.get("content_kind"):
            r["content_kind"] = kw["content_kind"]
        r["failure"] = kw.get("failure")

    async def file_task(self, ingest_id, row, **kw):
        if self.file_error is not None:
            raise self.file_error
        self.filed.append({"content_kind": row.get("content_kind"), **kw})
        return "T-1", "FILED"


_SUSTAINMENT = types.SimpleNamespace(domain="SUSTAINMENT")
_DOMAINLESS = types.SimpleNamespace(domain=None, model_fields_set=frozenset({"domain"}))


def _by_kind(kind):
    return {"pcn": _SUSTAINMENT, "pdn": _SUSTAINMENT, "pdf": _DOMAINLESS}.get(kind)


def _user(authz):
    return type("U", (), {"authz_id": authz, "id": authz, "sub": authz, "email": authz,
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()


@pytest.fixture
def db(monkeypatch):
    d = DB()
    monkeypatch.setattr(ist, "_pg_connect", lambda: _FakeConn(d))
    for name in ("get_row", "get_status_unscoped", "get_status_for", "update_status"):
        monkeypatch.setattr(ist, name, getattr(d, name))
    monkeypatch.setattr(ck, "by_kind", _by_kind)
    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", d.file_task)
    monkeypatch.setattr(ht, "get_task_open_state", lambda task_id: None)
    monkeypatch.setattr(ht, "register_task", lambda **kw: d.registered.append(kw) or {})
    monkeypatch.setattr(ht, "refresh_open_task",
                        lambda task_id, **kw: d.refreshed.append({"task_id": task_id, **kw}) or 1)
    yield d
    gateway.app.dependency_overrides.clear()


def _as(authz):
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user(authz)
    return TestClient(gateway.app)


def _title(c, body, id=ID):
    return c.post(f"/ingest/{id}/title_leaf", json=body)


CONFIDENT_PCN = {"doc_type": "PCN", "doc_type_source": "title"}
EV = {"page": 1, "bbox": [10, 10, 200, 40]}


def _cand(leaf, score, note=None, **kw):
    return {"leaf": leaf, "score": score,
            "evidence_ref": {**EV, **({"note": note} if note else {})}, **kw}


# --------------------------------------------------------------------------------------------
# title_leaf
# --------------------------------------------------------------------------------------------
def test_a_confident_title_on_a_pdf_row_proceeds_and_is_recorded_as_title(db):
    db.add(status="extracting")
    r = _title(_as(DOCTOOLS), {**CONFIDENT_PCN, "run_id": "run-1"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["proceed"] is True and b["content_kind"] == "pcn" and b["leaf"] == "pcn"
    assert b["leaf_source"] == "title" and b["stage"] == "extracting"
    row = db.rows[ID]
    assert row["content_kind"] == "pcn" and row["leaf_source"] == "title"
    assert row["leaf_set_by"] == DOCTOOLS and row["leaf_set_at"]


def test_a_title_works_on_a_row_with_no_declared_content_kind(db):
    db.add(status="received", content_kind=None)
    r = _title(_as(DOCTOOLS), {"doc_type": " pdn ", "doc_type_source": "title"})
    assert r.status_code == 200 and r.json()["content_kind"] == "pdn"


def test_a_title_that_names_no_leaf_holds_the_row_at_awaiting_kind(db):
    db.add(status="extracting")
    r = _title(_as(DOCTOOLS), {"doc_type": "PCN", "doc_type_source": "defaulted",
                               "candidates": [_cand("pcn", 0.4), _cand("bogus", 0.9),
                                              _cand("pdn", 0.6, note="n")], "run_id": "run-9"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["proceed"] is False and b["stage"] == "awaiting_kind"
    # an unknown leaf is dropped, a later duplicate of a leaf is dropped, best score first, note kept
    assert b["leaf_candidates"] == [
        {"leaf": "pdn", "score": 0.6, "evidence_ref": {**EV, "note": "n"}},
        {"leaf": "pcn", "score": 0.4, "evidence_ref": EV}]
    row = db.rows[ID]
    assert row["status"] == "awaiting_kind" and row["run_id"] == "run-9"
    assert row["content_kind"] == "pdf" and row["leaf_source"] is None
    assert "defaulted" in row["detail"] and "pick pcn or pdn" in row["detail"]


def test_a_confident_title_never_outvotes_a_non_title_source(db):
    db.add(status="extracting")
    for src in ("no-title-evidence", "title-ambiguous", None):
        r = _title(_as(DOCTOOLS), {"doc_type": "PCN", "doc_type_source": src})
        assert r.json()["proceed"] is False, src
        db.rows[ID]["status"] = "extracting"


@pytest.mark.parametrize("source", [None, "declared"])
def test_a_declared_leaf_beats_the_title_and_the_row_is_unchanged(db, source):
    db.add(status="extracting", content_kind="pdn", leaf_source=source)
    before = db.snap()
    r = _title(_as(DOCTOOLS), CONFIDENT_PCN)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["proceed"] is True and b["content_kind"] == "pdn" and b["leaf"] == "pdn"
    assert b["leaf_source"] == source   # as stored: no default is invented for a NULL
    assert db.snap() == before


def test_a_corrected_leaf_is_never_overwritten_by_a_title(db):
    db.add(status="extracting", content_kind="pdn", leaf_source="corrected")
    before = db.snap()
    r = _title(_as(DOCTOOLS), CONFIDENT_PCN)
    assert r.json()["content_kind"] == "pdn" and r.json()["leaf_source"] == "corrected"
    assert db.snap() == before


def test_a_correction_that_lands_between_the_read_and_the_write_beats_the_title(db):
    """The route reads a row with no leaf; a dropper's correction lands; the guarded write must match
    nothing, and the answer must come from the corrected row."""
    db.add(status="extracting", content_kind="pdn", leaf_source="corrected")
    stale = db.snap()
    stale.update(content_kind="pdf", leaf_source=None)
    db.stale_first_read = stale
    r = _title(_as(DOCTOOLS), CONFIDENT_PCN)
    assert r.status_code == 200, r.text
    assert r.json()["content_kind"] == "pdn" and r.json()["leaf_source"] == "corrected"
    assert db.rows[ID]["content_kind"] == "pdn" and db.rows[ID]["leaf_source"] == "corrected"


def test_set_leaf_with_a_title_source_matches_nothing_on_a_corrected_or_declared_row(db):
    for src in ("corrected", "declared"):
        db.add(status="extracting", content_kind="pdn", leaf_source=src)
        assert ist.set_leaf(ID, "pcn", "title", set_by=DOCTOOLS, from_statuses=["extracting"]) is None
        assert db.rows[ID]["content_kind"] == "pdn"
    db.add(status="extracting", content_kind="pdn", leaf_source="title")
    out = ist.set_leaf(ID, "pcn", "title", set_by=DOCTOOLS, from_statuses=["extracting"])
    assert out is not None and out["content_kind"] == "pcn"


def test_hold_for_kind_never_holds_a_row_a_correction_reached_first(db):
    # The dropper's /leaf landed between title_leaf's read and its hold: the corrected leaf wins.
    db.add(status="extracting", content_kind="pdn", leaf_source="corrected")
    assert ist.hold_for_kind(ID, candidates=[_cand("pcn", 0.5)], detail="x",
                             from_statuses=["extracting"]) is False
    row = db.rows[ID]
    assert row["status"] == "extracting" and row["content_kind"] == "pdn"
    # Control: the same call on a row with no leaf does hold, with candidates lower-cased and
    # stored best score first.
    db.rows[ID].update(content_kind="pdf", leaf_source=None)
    assert ist.hold_for_kind(ID, candidates=[_cand(" PCN ", 0.2), _cand("pdn", 0.7)], detail="x",
                             from_statuses=["extracting"]) is True
    assert db.rows[ID]["status"] == "awaiting_kind"
    assert json.loads(db.rows[ID]["leaf_candidates"]) == [
        {"leaf": "pdn", "score": 0.7, "evidence_ref": EV},
        {"leaf": "pcn", "score": 0.2, "evidence_ref": EV}]


def test_an_unconfident_repeat_keeps_a_title_leaf_already_on_the_row(db):
    db.add(status="extracting", content_kind="pcn", leaf_source="title")
    r = _title(_as(DOCTOOLS), {"doc_type": "PCN", "doc_type_source": "defaulted"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["proceed"] is True and b["content_kind"] == "pcn" and b["leaf_source"] == "title"
    assert db.rows[ID]["status"] == "extracting"


def test_set_leaf_validates_its_vocabulary(db):
    db.add()
    with pytest.raises(ValueError):
        ist.set_leaf(ID, "ecn", "title", set_by="x", from_statuses=["extracting"])
    with pytest.raises(ValueError):
        ist.set_leaf(ID, "pcn", "retired", set_by="x", from_statuses=["extracting"])
    assert ist.LEAF_SOURCES == ("declared", "title", "corrected")


@pytest.mark.parametrize("kind,ck_", [("cad", "cad"), ("xml", "s1000d-data-module"),
                                      ("pdf", "engineering-document")])
def test_a_row_that_is_not_leaf_capable_proceeds_and_nothing_is_written(db, kind, ck_):
    db.add(status="extracting", kind=kind, content_kind=ck_)
    before = db.snap()
    r = _title(_as(DOCTOOLS), CONFIDENT_PCN)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["proceed"] is True and b["content_kind"] == ck_
    assert b["leaf"] is None and b["leaf_source"] is None
    assert db.snap() == before


def test_a_caller_other_than_doc_tools_gets_403(db):
    db.add(status="extracting")
    for who in (ALICE, "svc:case-runner"):
        r = _title(_as(who), CONFIDENT_PCN)
        assert r.status_code == 403 and r.json()["detail"]["error"] == "not_doc_tools"
    assert db.rows[ID]["leaf_source"] is None


@pytest.mark.parametrize("stage", ["review", "awaiting_kind", "awaiting_origin", "promoted",
                                   "failed"])
def test_a_row_outside_received_and_extracting_is_409_not_extracting(db, stage):
    db.add(status=stage, failure={"reason_code": "extraction_empty"})
    before = db.snap()
    r = _title(_as(DOCTOOLS), CONFIDENT_PCN)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {"error": "not_extracting", "stage": stage}
    assert db.snap() == before


def test_a_timeout_provisional_failed_row_is_treated_as_received(db):
    db.add(status="failed", failure={"reason_code": "timeout"})
    r = _title(_as(DOCTOOLS), CONFIDENT_PCN)
    assert r.status_code == 200, r.text
    assert r.json()["proceed"] is True and r.json()["content_kind"] == "pcn"
    assert db.rows[ID]["leaf_source"] == "title"
    # and a no-leaf title holds it, from the failed status
    db.add(OTHER_ID, status="failed", failure={"reason_code": "timeout"})
    r = _title(_as(DOCTOOLS), {"doc_type_source": "no-title-evidence"}, id=OTHER_ID)
    assert r.json()["proceed"] is False and db.rows[OTHER_ID]["status"] == "awaiting_kind"


def test_a_repeat_of_the_confident_call_answers_the_same_and_a_repeat_on_a_held_row_is_409(db):
    db.add(status="extracting")
    c = _as(DOCTOOLS)
    first = _title(c, CONFIDENT_PCN).json()
    assert _title(c, CONFIDENT_PCN).json() == first
    db.add(OTHER_ID, status="extracting")
    assert _title(c, {"doc_type_source": "defaulted"}, id=OTHER_ID).json()["proceed"] is False
    r = _title(c, {"doc_type_source": "defaulted"}, id=OTHER_ID)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "not_extracting"


def test_title_leaf_refuses_an_absent_row_an_event_row_a_blank_run_id_and_extra_keys(db):
    db.add(OTHER_ID, kind="event", status="received", content_kind=None)
    c = _as(DOCTOOLS)
    assert _title(c, CONFIDENT_PCN, id=OTHER_ID).status_code == 404
    assert _title(c, CONFIDENT_PCN, id="sha256:" + "c" * 64).status_code == 404
    db.add()
    r = _title(c, {**CONFIDENT_PCN, "run_id": "  "})
    assert r.status_code == 422 and r.json()["detail"] == {"error": "invalid_run_id"}
    assert _title(c, {**CONFIDENT_PCN, "extra": 1}).status_code == 422


# --------------------------------------------------------------------------------------------
# /leaf
# --------------------------------------------------------------------------------------------
def _leaf(c, leaf, id=ID):
    return c.post(f"/ingest/{id}/leaf", json={"leaf": leaf})


def test_a_correction_at_extracting_overwrites_the_kind_and_leaves_the_stage(db):
    db.add(status="extracting", content_kind="pcn", leaf_source="title")
    r = _leaf(_as(ALICE), " PDN ")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["stage"] == "extracting" and b["leaf"] == "pdn" and b["leaf_source"] == "corrected"
    row = db.rows[ID]
    assert row["content_kind"] == "pdn" and row["leaf_source"] == "corrected"
    assert row["leaf_set_by"] == ALICE and row["status"] == "extracting"
    # the in-flight run's own title_leaf call now sees the correction and proceeds with it
    t = _title(_as(DOCTOOLS), CONFIDENT_PCN).json()
    assert t["proceed"] is True and t["content_kind"] == "pdn" and t["leaf_source"] == "corrected"


def test_a_pick_at_awaiting_kind_reopens_the_row_and_it_is_listed_for_relaunch(db):
    db.add(status="awaiting_kind", leaf_candidates=json.dumps([_cand("pcn", 0.5)]), detail="pick",
           failure={"reason_code": "x"})
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "received" and r.json()["attempt"] == 2
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2
    assert row["content_kind"] == "pdn" and row["leaf_source"] == "corrected"
    assert row["leaf_candidates"] is None and row["detail"] is None and row["failure"] is None
    lst = _as(DOCTOOLS).get("/ingest/retries")
    assert lst.status_code == 200, lst.text
    assert [(e["ingest_id"], e["attempt"], e["content_kind"], e["run_key"])
            for e in lst.json()["retries"]] == [(ID, 2, "pdn", f"{ID}-a2")]


def _no_task_touched(db):
    assert db.filed == [] and db.registered == [] and db.refreshed == []


@pytest.mark.parametrize("stage", ["awaiting_origin", "review"])
def test_a_correction_after_parts_extraction_sends_the_row_back_to_received_and_touches_no_task(
        db, stage):
    db.add(status=stage, content_kind="pcn", leaf_source="title", extraction_ref=REF,
           detail="d", extracted_count=3)
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["stage"] == "received" and b["attempt"] == 2 and b["leaf"] == "pdn"
    assert b["leaf_source"] == "corrected" and b["corrected_by"] == ALICE
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2 and row["content_kind"] == "pdn"
    assert row["leaf_source"] == "corrected" and row["leaf_set_by"] == ALICE
    _no_task_touched(db)
    # and it is listed for the relaunch, as the new kind
    lst = _as(DOCTOOLS).get("/ingest/retries").json()["retries"]
    assert [(e["ingest_id"], e["attempt"], e["content_kind"]) for e in lst] == [(ID, 2, "pdn")]


def test_a_correction_at_failed_is_in_place_and_the_stage_stays_failed(db):
    db.add(status="failed", content_kind="pcn", leaf_source="title", detail="boom",
           failure={"reason_code": "x"})
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "failed" and r.json()["leaf"] == "pdn"
    row = db.rows[ID]
    assert row["status"] == "failed" and row["attempt"] == 1 and row["content_kind"] == "pdn"
    assert row["leaf_source"] == "corrected" and row["leaf_set_by"] == ALICE
    _no_task_touched(db)



def _detail(r) -> dict:
    """The refusal body less its `message`, which must be there and non-empty: cortex shows it
    verbatim, so a code without one reaches the dropper as a raw code."""
    d = dict(r.json()["detail"])
    msg = d.pop("message", None)
    assert isinstance(msg, str) and msg.strip(), f"refusal without a message: {r.text}"
    return d

@pytest.mark.parametrize("stage", ["awaiting_origin", "review", "awaiting_kind"])
def test_a_row_that_moved_under_the_correction_is_409_with_its_current_stage(db, monkeypatch, stage):
    db.add(status=stage, content_kind="pcn", leaf_source="title")
    real = ist.set_leaf

    def _moved_first(*a, **k):
        db.rows[ID]["status"] = "promoted"
        return real(*a, **k)

    monkeypatch.setattr(ist, "set_leaf", _moved_first)
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 409, r.text
    assert _detail(r) == {"error": "leaf_not_changeable", "stage": "promoted"}
    assert db.rows[ID]["content_kind"] == "pcn" and db.rows[ID]["leaf_source"] == "title"
    _no_task_touched(db)


@pytest.mark.parametrize("stage", ["promoted", "rejected", "review_rejected",
                                   "duplicate", "case_opened"])
def test_a_correction_after_the_review_is_not_changeable(db, stage):
    db.add(status=stage, content_kind="pcn", leaf_source="title")
    before = db.snap()
    r = _leaf(_as(ALICE), "pdn")
    assert r.status_code == 409, r.text
    assert _detail(r) == {"error": "leaf_not_changeable", "stage": stage}
    assert db.snap() == before
    _no_task_touched(db)


def test_a_cad_row_has_no_leaf_to_correct(db):
    db.add(status="extracting", kind="cad", content_kind="cad")
    before = db.snap()
    r = _leaf(_as(ALICE), "pcn")
    assert r.status_code == 409, r.text
    assert _detail(r) == {"error": "no_leaf_for_kind", "stage": "extracting",
                          "content_kind": "cad"}
    assert db.snap() == before


def test_an_unknown_leaf_is_422_and_so_is_an_extra_key(db):
    db.add(status="extracting")
    r = _leaf(_as(ALICE), "ecn")
    assert r.status_code == 422
    assert _detail(r) == {"error": "unknown_leaf", "allowed": ["pcn", "pdn"]}
    assert _as(ALICE).post(f"/ingest/{ID}/leaf", json={"leaf": "pcn", "x": 1}).status_code == 422
    assert db.rows[ID]["leaf_source"] is None


def test_a_stranger_gets_403_and_nothing_is_written(db):
    db.add(status="extracting")
    before = db.snap()
    r = _leaf(_as(BOB), "pcn")
    assert r.status_code == 403 and r.json()["detail"]["error"] == "not_entitled"
    assert db.snap() == before


def test_an_absent_row_and_an_event_row_are_404(db):
    db.add(OTHER_ID, kind="event", status="received", content_kind=None)
    assert _leaf(_as(ALICE), "pcn", id=OTHER_ID).status_code == 404
    assert _leaf(_as(ALICE), "pcn", id="sha256:" + "c" * 64).status_code == 404


def test_the_same_leaf_answers_the_status_body_and_writes_nothing(db, monkeypatch):
    db.add(status="extracting", content_kind="pcn", leaf_source="title")
    before = db.snap()
    calls = []
    real = ist.set_leaf
    monkeypatch.setattr(ist, "set_leaf", lambda *a, **k: calls.append(1) or real(*a, **k))
    r = _leaf(_as(ALICE), "pcn")
    assert r.status_code == 200, r.text
    assert r.json()["leaf"] == "pcn" and r.json()["leaf_source"] == "title"
    assert calls == [] and db.snap() == before


# --------------------------------------------------------------------------------------------
# the status body
# --------------------------------------------------------------------------------------------
def _status(c, id=ID):
    return c.get(f"/ingest/{id}/status")


def test_a_pdf_row_with_no_leaf_yet_carries_the_keys_as_null(db):
    db.add(status="extracting")
    b = _status(_as(ALICE)).json()
    assert b["leaf"] is None and b["leaf_source"] is None and b["leaf_candidates"] is None
    assert b["corrected_by"] is None
    assert {"leaf", "leaf_source", "leaf_candidates", "corrected_by"} <= set(b)


def test_the_status_body_reads_the_stored_source_and_never_invents_one(db):
    db.add(status="extracting", content_kind="pdn", leaf_source="declared")
    b = _status(_as(ALICE)).json()
    assert (b["leaf"], b["leaf_source"], b["corrected_by"]) == ("pdn", "declared", None)
    db.rows[ID]["leaf_source"] = None
    b = _status(_as(ALICE)).json()
    assert (b["leaf"], b["leaf_source"]) == ("pdn", None)
    db.rows[ID].update(leaf_source="corrected", leaf_set_by=BOB)
    b = _status(_as(ALICE)).json()
    assert (b["leaf_source"], b["corrected_by"]) == ("corrected", BOB)


@pytest.mark.parametrize("kind,ck_", [("cad", "cad"), ("xml", "s1000d-data-module"),
                                      ("pdf", "engineering-document")])
def test_a_row_that_is_not_leaf_capable_has_no_leaf_keys_at_all(db, kind, ck_):
    db.add(status="extracting", kind=kind, content_kind=ck_)
    b = _status(_as(ALICE)).json()
    assert not ({"leaf", "leaf_source", "leaf_candidates", "corrected_by"} & set(b)), sorted(b)


def test_a_row_at_awaiting_kind_carries_the_candidates(db):
    cands = [{"leaf": "pcn", "score": 0.6, "evidence_ref": EV}]
    db.add(status="awaiting_kind", leaf_candidates=json.dumps(cands))
    b = _status(_as(ALICE)).json()
    assert b["stage"] == "awaiting_kind" and b["leaf_candidates"] == cands
    assert b["leaf"] is None


def test_the_candidates_are_only_shown_at_awaiting_kind(db):
    db.add(status="extracting", leaf_candidates=json.dumps([_cand("pcn", 0.5)]))
    assert _status(_as(ALICE)).json()["leaf_candidates"] is None


def test_a_duplicate_row_reads_the_originals_leaf(db):
    db.add(status="extracting", content_kind="pcn", leaf_source="corrected")
    db.add(OTHER_ID, status="duplicate", duplicate_of=ID, content_kind="pdf", detail="dup")
    b = _status(_as(ALICE), id=OTHER_ID).json()
    assert (b["leaf"], b["leaf_source"]) == ("pcn", "corrected")
    # an original this caller cannot see leaves the keys absent
    db.rows[ID]["submitted_by"] = db.rows[ID]["on_behalf_of"] = BOB
    b = _status(_as(ALICE), id=OTHER_ID).json()
    assert b["stage"] is None and "leaf" not in b


# --------------------------------------------------------------------------------------------
# the stage route
# --------------------------------------------------------------------------------------------
def _review_json(**kw):
    return {"review_items": [{"field_path": "parts[0].affected_mpn", "value": "X"}], **kw}


def _stage(db, monkeypatch, body, review=None, **row):
    db.add(**row)
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: {})
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: review or _review_json())

    async def _no_origin(*a, **kw):
        return None

    monkeypatch.setattr(gateway, "_file_promotion_if_ready", _no_origin)
    return _as(DOCTOOLS).post(f"/ingest/{ID}/stage", json=body)


@pytest.mark.parametrize("target", ["extracting", "review", "failed"])
def test_a_stage_post_on_a_held_row_is_409(db, monkeypatch, target):
    r = _stage(db, monkeypatch, {"stage": target, "extraction_ref": REF, "detail": "x"},
               status="awaiting_kind", leaf_candidates='["pcn"]')
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["from"] == "awaiting_kind"
    assert db.rows[ID]["status"] == "awaiting_kind"


def test_a_confident_title_at_the_review_post_writes_no_leaf_only_title_leaf_does(db, monkeypatch):
    # 7f measured (10-21) that a pdf row runs no plugin, so the 203 review-transition backstop that
    # read this title could never fire; it is removed. `title` is written by `title_leaf` alone.
    r = _stage(db, monkeypatch, {"stage": "review", "extraction_ref": REF},
               review=_review_json(doc_type="PDN", doc_type_source="title"), status="extracting")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "awaiting_origin"
    assert db.filed == []
    row = db.rows[ID]
    assert row["content_kind"] == "pdf" and row["leaf_source"] is None


def test_a_corrected_leaf_stands_at_the_review_post_and_files_its_kind(db, monkeypatch):
    r = _stage(db, monkeypatch, {"stage": "review", "extraction_ref": REF},
               review=_review_json(doc_type="PCN", doc_type_source="title"), status="extracting",
               content_kind="pdn", leaf_source="corrected")
    assert r.status_code == 200, r.text
    assert [f["content_kind"] for f in db.filed] == ["pdn"]
    assert db.rows[ID]["content_kind"] == "pdn" and db.rows[ID]["leaf_source"] == "corrected"


# --------------------------------------------------------------------------------------------
# the retry route and the migration
# --------------------------------------------------------------------------------------------
def test_a_service_retry_of_a_held_document_row_is_409_awaiting_kind(db, monkeypatch):
    db.add(status="awaiting_kind", pin_digest="sha256:" + "1" * 64)
    r = _as("svc:pin-driver").post(f"/ingest/{ID}/retry", json={"pin_digest": "sha256:" + "2" * 64})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "awaiting_kind"
    assert "POST /ingest/{id}/leaf" in r.json()["detail"]["message"]


def test_a_person_retry_of_a_held_row_stays_pin_driven_403(db):
    db.add(status="awaiting_kind")
    r = _as(ALICE).post(f"/ingest/{ID}/retry")
    assert r.status_code == 403 and r.json()["detail"]["error"] == "retry_is_pin_driven"


def test_the_vocabulary_and_the_migration_agree():
    assert ist.LEAVES == ("pcn", "pdn")
    assert "awaiting_kind" in ist.ALL_STATUSES and "awaiting_kind" not in ist.STAGES
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "sql" / "create_ingest_status_projection.sql"
           ).read_text(encoding="utf-8")
    for col in ("leaf_source TEXT", "leaf_candidates TEXT", "leaf_set_by TEXT", "leaf_set_at BIGINT"):
        stmt = f"ADD COLUMN IF NOT EXISTS {col}"
        assert stmt in sql and stmt in ist._MIGRATION_SQL, col
    with pytest.raises(ValueError):
        ist.fail_stalled(stage="awaiting_kind", older_than_seconds=1)
