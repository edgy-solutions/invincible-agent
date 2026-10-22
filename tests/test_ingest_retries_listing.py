"""GET /ingest/retries (architect ruling 2026-10-12, Shape 1): the service-only listing of retried
drops awaiting relaunch. doc-tools polls it and launches each entry with run_key
`{ingest_id}-a{attempt}`.

Harness mirrors tests/test_a_pipeline_failure_reaches_the_row.py: TestClient(gateway.app) with
get_current_user overridden, `ingest_status` stubbed on the module the gateway imports, and the
SQL tested against a recording cursor double (statement text, because a stub returning the right
rows would pass whatever the predicate said).

WHAT THESE DEFEND:
  * a person, and an empty service identity, get 403 `not_doc_tools` and the DB is never touched;
  * svc:doc-tools gets each entry with `run_key == "{id}-a{attempt}"`;
  * `limit` is bounded 1..200 (default 50, passed through);
  * the SELECT lists only `received`, attempt > 1, non-event rows, oldest first.
"""
from __future__ import annotations

from unittest import mock

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_A = "sha256:" + "a" * 64
_B = "sha256:" + "b" * 64


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


def _entry(i, attempt):
    return {"id": i, "attempt": attempt, "kind": "pdf", "content_kind": "pcn",
            "object_prefix": f"ingress-user/pdf/{i}/", "sha256": i, "run_id": None,
            "updated_at": 1000 + attempt}


def _rig(monkeypatch, rows=()):
    calls: list[dict] = []

    def fake(**kw):
        calls.append(kw)
        return list(rows)

    monkeypatch.setattr(ist, "list_pending_retries", fake)
    return calls


def _fake_conn(fetchall_rows=()):
    cur = mock.MagicMock()
    cur.fetchall.return_value = list(fetchall_rows)
    cur_cm = mock.MagicMock()
    cur_cm.__enter__ = mock.Mock(return_value=cur)
    cur_cm.__exit__ = mock.Mock(return_value=False)
    conn = mock.MagicMock()
    conn.cursor.return_value = cur_cm
    conn_cm = mock.MagicMock()
    conn_cm.__enter__ = mock.Mock(return_value=conn)
    conn_cm.__exit__ = mock.Mock(return_value=False)
    return conn_cm, conn, cur


def _norm(sql):
    return " ".join(sql.split())


def test_a_person_gets_403_not_doc_tools_and_the_db_is_not_called(dropper, monkeypatch):
    calls = _rig(monkeypatch, [_entry(_A, 2)])
    r = dropper.get("/ingest/retries")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_doc_tools"
    assert calls == []


def test_an_empty_service_identity_denies_even_doc_tools(doc_tools_client, monkeypatch):
    monkeypatch.setattr(gateway, "_DOC_TOOLS_SERVICE_AUTHZ_ID", "")
    calls = _rig(monkeypatch, [_entry(_A, 2)])
    r = doc_tools_client.get("/ingest/retries")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_doc_tools"
    assert calls == []


def test_doc_tools_gets_each_entry_with_an_attempt_keyed_run_key(doc_tools_client, monkeypatch):
    _rig(monkeypatch, [_entry(_A, 2), _entry(_B, 5)])
    r = doc_tools_client.get("/ingest/retries")
    assert r.status_code == 200
    out = r.json()["retries"]
    assert [e["ingest_id"] for e in out] == [_A, _B]
    assert out[0] == {"ingest_id": _A, "attempt": 2, "run_key": f"{_A}-a2", "kind": "pdf",
                      "content_kind": "pcn", "object_prefix": f"ingress-user/pdf/{_A}/",
                      "sha256": _A, "run_id": None, "updated_at": 1002, "reason": None}
    for e in out:
        assert e["run_key"] == f"{e['ingest_id']}-a{e['attempt']}"


def test_limit_default_is_50_and_is_passed_through(doc_tools_client, monkeypatch):
    calls = _rig(monkeypatch)
    assert doc_tools_client.get("/ingest/retries").status_code == 200
    assert doc_tools_client.get("/ingest/retries?limit=7").status_code == 200
    assert calls == [{"limit": 50}, {"limit": 7}]


@pytest.mark.parametrize("limit", [0, 201])
def test_limit_out_of_bounds_is_422(doc_tools_client, monkeypatch, limit):
    calls = _rig(monkeypatch)
    assert doc_tools_client.get(f"/ingest/retries?limit={limit}").status_code == 422
    assert calls == []


def test_list_pending_retries_selects_received_retried_document_rows_oldest_first():
    cm, conn, cur = _fake_conn(fetchall_rows=[(_A, 2, "pdf", "pcn", "p/", _A, None, 9)])
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        rows = ist.list_pending_retries(limit=13)
    assert rows == [{"id": _A, "attempt": 2, "kind": "pdf", "content_kind": "pcn",
                     "object_prefix": "p/", "sha256": _A, "run_id": None, "updated_at": 9}]
    sql, params = cur.execute.call_args[0]
    sql = _norm(sql)
    assert sql.startswith("SELECT id, attempt, kind, content_kind, object_prefix, sha256")
    assert "status = 'received'" in sql
    assert "attempt > 1" in sql
    assert "kind <> 'event'" in sql
    assert "ORDER BY updated_at ASC, id ASC" in sql
    assert params == (13,)
