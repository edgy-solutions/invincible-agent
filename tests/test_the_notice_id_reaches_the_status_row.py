"""The notice's own id (e.g. PCN26-184) reaches the status row and the status route (2026-10-13).

The contract promised to cortex: `notice_id` ABSENT = no claim (an old fleet); `null` = claimed,
none known yet; a string = the notice's own id. It is DISPLAY ONLY and never an identity (it is the
LLM-extracted `doc_id`). The source is the extraction manifest's `doc_id`, the same field
`promotion.payload_from_extraction` derives the payload's `notice_id` from. It is written in the
SAME update_status call that moves the row into `review`, from the manifest the stage route already
reads to file the promotion task (no new read). Blank is stored as NULL, never "".
"""
from __future__ import annotations

from unittest import mock

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

HEX = "5e" * 32
ID = "sha256:" + HEX
DUP = "sha256:" + "d1" * 32
PREFIX = f"ingress-user/pdf/{HEX}/"
REF = PREFIX + "generated/doc_pdf/doc-tools@61f74dc/manifest.json"


def _manifest(**over):
    m = {"doc_id": "PCN26-184", "filename": "doc.pdf", "source_key": PREFIX + "doc.pdf",
         "pipeline_version": "doc-tools@61f74dc", "ingest_id": ID,
         "provenance": {"standing": "supervised", "ingest_id": ID}}
    m.update(over)
    return m


def _client_for(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def doc_tools_client():
    yield from _client_for("svc:doc-tools")


@pytest.fixture
def dropper():
    yield from _client_for("alice@example.com")


def _review_rig(monkeypatch, manifest):
    row = {"id": ID, "status": "extracting", "kind": "pdf", "content_kind": "pcn",
           "object_prefix": PREFIX, "submitted_by": "alice@example.com"}
    calls = []
    monkeypatch.setattr(ist, "get_row", lambda i: row)
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: calls.append((a, kw)))
    reg = type("Reg", (), {"domain": "sustainment"})()
    monkeypatch.setattr(ck, "by_kind", lambda kind: reg if kind == "pcn" else None)
    monkeypatch.setattr(ht, "task_exists", lambda t: False)
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: {"task_id": kw["task_id"], "recipients": []})
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: manifest)
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: {"review_items": [{"field_path": "parts[0].affected_mpn", "value": "X"}]})  # zero-row gate, ruling 2026-10-17
    return calls


# (a) the notice id rides the same update as the stage move ------------------------------------
def test_a_review_transition_writes_the_manifests_doc_id_in_the_same_update(doc_tools_client, monkeypatch):
    calls = _review_rig(monkeypatch, _manifest())
    r = doc_tools_client.post(f"/ingest/{ID}/stage", json={"stage": "review", "extraction_ref": REF})
    assert r.status_code == 200, r.text
    (args, kw), = calls
    assert args == (ID, "review")
    assert kw["notice_id"] == "PCN26-184"
    assert kw["extraction_ref"] == REF  # one act: the stage, the ref and the notice id together


# (b) blank / missing is NULL, never "" ---------------------------------------------------------
@pytest.mark.parametrize("doc_id", ["", "   ", None, "MISSING"])
def test_a_blank_or_missing_doc_id_writes_no_notice_id_not_an_empty_string(
        doc_tools_client, monkeypatch, doc_id):
    m = _manifest()
    if doc_id == "MISSING":
        del m["doc_id"]
    else:
        m["doc_id"] = doc_id
    calls = _review_rig(monkeypatch, m)
    r = doc_tools_client.post(f"/ingest/{ID}/stage", json={"stage": "review", "extraction_ref": REF})
    assert r.status_code == 200, r.text
    (_, kw), = calls
    assert kw.get("notice_id") is None, kw  # absent or None (COALESCE leaves the column NULL)


# (c) the status route: key always present -----------------------------------------------------
def _row(status="review", **extra):
    return {"id": ID, "status": status, "kind": "pdf", "submitted_by": "alice@example.com",
            "on_behalf_of": "alice@example.com", "content_kind": "pcn", "failure": None,
            "attempt": 1, "created_at": 1, "updated_at": 2, **extra}


def _status_rig(monkeypatch, rows):
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: rows.get(ingest_id))


def test_status_returns_the_notice_id_string_when_the_row_has_it(dropper, monkeypatch):
    _status_rig(monkeypatch, {ID: _row(notice_id="PCN26-184")})
    body = dropper.get(f"/ingest/{ID}/status").json()
    assert "notice_id" in body and body["notice_id"] == "PCN26-184"


def test_status_returns_null_with_the_key_present_when_the_rows_is_null(dropper, monkeypatch):
    _status_rig(monkeypatch, {ID: _row(notice_id=None)})
    body = dropper.get(f"/ingest/{ID}/status").json()
    assert "notice_id" in body and body["notice_id"] is None


def test_status_key_is_present_even_for_a_row_that_never_had_the_column(dropper, monkeypatch):
    _status_rig(monkeypatch, {ID: _row()})
    body = dropper.get(f"/ingest/{ID}/status").json()
    assert "notice_id" in body and body["notice_id"] is None


# (d) a duplicate reports the ORIGINAL's -------------------------------------------------------
def test_status_of_a_duplicate_carries_the_originals_notice_id(dropper, monkeypatch):
    original = _row(notice_id="ORIGINAL-1")
    original["id"] = DUP
    dup = _row(ist.DUPLICATE, duplicate_of=DUP, detail="dup", notice_id="THE-DUPLICATES-OWN")
    _status_rig(monkeypatch, {ID: dup, DUP: original})
    body = dropper.get(f"/ingest/{ID}/status").json()
    assert body["notice_id"] == "ORIGINAL-1"


def test_status_of_a_duplicate_whose_original_is_invisible_reports_null(dropper, monkeypatch):
    dup = _row(ist.DUPLICATE, duplicate_of=DUP, detail="dup", notice_id="THE-DUPLICATES-OWN")
    _status_rig(monkeypatch, {ID: dup})
    body = dropper.get(f"/ingest/{ID}/status").json()
    assert body["notice_id"] is None


# (e) COALESCE: a later stage move never erases it ---------------------------------------------
def _fake_conn():
    cur = mock.MagicMock()
    cur_cm = mock.MagicMock()
    cur_cm.__enter__ = mock.Mock(return_value=cur)
    cur_cm.__exit__ = mock.Mock(return_value=False)
    conn = mock.MagicMock()
    conn.cursor.return_value = cur_cm
    conn_cm = mock.MagicMock()
    conn_cm.__enter__ = mock.Mock(return_value=conn)
    conn_cm.__exit__ = mock.Mock(return_value=False)
    return conn_cm, cur


def test_update_status_without_a_notice_id_leaves_the_column_unchanged():
    cm, cur = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ist.update_status(ID, ist.PROMOTED)
    sql, params = cur.execute.call_args[0]
    assert "notice_id = COALESCE(%s, notice_id)" in " ".join(sql.split())
    assert None in params


def test_update_status_with_a_notice_id_writes_it_in_the_same_update():
    cm, cur = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ist.update_status(ID, ist.REVIEW, notice_id="PCN26-184")
    sql, params = cur.execute.call_args[0]
    assert sql.count("UPDATE") == 1 and "PCN26-184" in params
    assert "notice_id = COALESCE(%s, notice_id)" in " ".join(sql.split())


def test_the_selects_carry_notice_id():
    for fn in (lambda: ist.get_row(ID), lambda: ist.get_status_unscoped(ID),
               lambda: ist.get_status_for(ID, caller_id="alice@example.com")):
        cm, cur = _fake_conn()
        cur.fetchone.return_value = {"id": ID, "failure": None, "notice_id": "PCN26-184",
                                     "origin_suggestion": None}
        with mock.patch.object(ist, "_pg_connect", return_value=cm):
            out = fn()
        assert "notice_id" in " ".join(cur.execute.call_args[0][0].split())
        assert out["notice_id"] == "PCN26-184"
