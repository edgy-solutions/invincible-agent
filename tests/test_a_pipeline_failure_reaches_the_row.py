"""Pipeline failure must reach the row (architect directive 2026-10-12, Lane 1's half).

doc-tools' op error boundary POSTs `failed` with {reason_code, reason, step, run_id, pin_digest};
the row stores it, GET /ingest/{id}/status returns it, a watchdog fails a row that sat at
`received` too long (`failed:timeout`), and a failed DOCUMENT row is retryable (the one
legitimate human retry: the input was never processed).

Harness/idiom mirrors tests/test_ingest_retry_route.py and tests/test_gateway_ingest_routes.py:
TestClient(gateway.app) + dependency_overrides[get_current_user], `ingest_status` functions stubbed
on the module the gateway imports. The SQL substrate (`fail_stale_received`, `retry_failed`) is
tested against a recording cursor double: the arms assert on the STATEMENT TEXT and the PARAMS,
because a stub that returns the right ids would pass whatever the predicate said.

WHAT THESE DEFEND (each arm is named for the behaviour):
  * the stage route records the structured failure, refuses failure fields off `failed`, refuses
    a malformed reason_code, and still accepts a legacy detail-only `failed`;
  * a watchdog `timeout` failure is PROVISIONAL (a late run supersedes it), any other failure is
    terminal;
  * the status route reports `failure` and `attempt`, taking them from the row `stage` came from;
  * the retry route re-opens a failed document row for its dropper and for a service, with no
    oracle for a person who cannot see the row, and leaves a failed event row terminal;
  * the watchdog UPDATE is one atomic statement that excludes event rows and carries each row's
    own run_id; the retry UPDATE is guarded on status = 'failed'.
"""
from __future__ import annotations

import asyncio
import json
from unittest import mock

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

_ID = "sha256:" + "a" * 64
_DUP = "sha256:" + "b" * 64


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


@pytest.fixture
def service():
    yield from _client_for("svc:pin-driver")


def _stage_rig(monkeypatch, row):
    """Stubs get_row and records every update_status call as (args, kwargs)."""
    calls: list[tuple] = []
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: row)
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: calls.append((a, kw)))
    return calls


def _row(status, **extra):
    return {"id": _ID, "status": status, "kind": "pdf", "submitted_by": "alice@example.com",
            "on_behalf_of": "alice@example.com", "content_kind": "pcn", "failure": None,
            "attempt": 1, "created_at": 1, "updated_at": 2, **extra}


# ===========================================================================
# Stage route: the failed POST
# ===========================================================================
def test_a_failed_post_with_all_five_fields_records_the_failure_and_detail_equals_reason(
        doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _row(ist.EXTRACTING))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={
        "stage": "failed", "reason_code": "ocr_unreadable", "reason": "page 3 is a blank scan",
        "step": "extract_text", "run_id": "run-123", "pin_digest": "sha256:" + "c" * 64})
    assert r.status_code == 200, r.text
    (args, kw), = calls
    assert args == (_ID, "failed")
    assert kw["detail"] == "page 3 is a blank scan"
    assert kw["run_id"] == "run-123"
    failure = kw["failure"]
    assert {k: failure[k] for k in ("reason_code", "reason", "step", "run_id", "pin_digest")} == {
        "reason_code": "ocr_unreadable", "reason": "page 3 is a blank scan",
        "step": "extract_text", "run_id": "run-123", "pin_digest": "sha256:" + "c" * 64}
    assert isinstance(failure["failed_at"], int) and failure["failed_at"] > 0


@pytest.mark.parametrize("field,value", [
    ("reason_code", "ocr_unreadable"), ("reason", "why"), ("step", "extract"),
    ("pin_digest", "sha256:" + "c" * 64)])
def test_failure_fields_on_a_non_failed_stage_are_422_and_nothing_is_written(
        doc_tools_client, monkeypatch, field, value):
    calls = _stage_rig(monkeypatch, _row(ist.RECEIVED))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "extracting", field: value})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == {"error": "failure_fields_without_failed", "fields": [field]}
    assert calls == []


def test_failure_fields_are_refused_before_any_row_read(doc_tools_client, monkeypatch):
    def _boom(ingest_id):
        raise AssertionError("row read before the failure-field check")
    monkeypatch.setattr(ist, "get_row", _boom)
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "review", "step": "x"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "failure_fields_without_failed"


@pytest.mark.parametrize("bad", ["OCR", "9lives", "has space", "", "a" * 65, "a-b"])
def test_a_malformed_reason_code_is_422_invalid_reason_code(doc_tools_client, monkeypatch, bad):
    calls = _stage_rig(monkeypatch, _row(ist.EXTRACTING))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={
        "stage": "failed", "reason_code": bad, "reason": "x"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "invalid_reason_code"
    assert calls == []


def test_a_legacy_failed_post_with_detail_only_records_an_unclassified_failure(
        doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _row(ist.EXTRACTING))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={
        "stage": "failed", "detail": "extraction blew up"})
    assert r.status_code == 200, r.text
    (_, kw), = calls
    assert kw["failure"]["reason_code"] is None
    assert kw["failure"]["reason"] == "extraction blew up"
    assert kw["detail"] == "extraction blew up"


def test_a_failed_post_with_no_run_id_names_the_run_the_row_already_recorded(
        doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _row(ist.EXTRACTING, run_id="run-7"))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={
        "stage": "failed", "reason_code": "parse_error", "reason": "bad page"})
    assert r.status_code == 200, r.text
    (_, kw), = calls
    assert kw["failure"]["run_id"] == "run-7"


def test_a_failed_post_with_neither_reason_nor_detail_keeps_the_detail_required_422(
        doc_tools_client, monkeypatch):
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: _row(ist.EXTRACTING))
    monkeypatch.setattr(ist, "_pg_connect", lambda: (_ for _ in ()).throw(AssertionError("db")))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "failed"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "invalid_stage_update"


def test_run_id_on_extracting_reaches_update_status(doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _row(ist.RECEIVED))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "extracting", "run_id": "run-9"})
    assert r.status_code == 200, r.text
    (_, kw), = calls
    assert kw["run_id"] == "run-9"
    assert "failure" not in kw


def test_a_blank_run_id_is_422_invalid_run_id(doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _row(ist.RECEIVED))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "extracting", "run_id": "  "})
    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "invalid_run_id"}
    assert calls == []


# ===========================================================================
# Stage route: a watchdog timeout is provisional, any other failure is terminal
# ===========================================================================
def _failed_row(reason_code):
    return _row(ist.FAILED, failure={"reason_code": reason_code, "reason": "r", "step": None,
                                     "run_id": None, "pin_digest": None, "failed_at": 5})


def test_a_timeout_failed_row_accepts_a_late_run_moving_to_extracting(doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _failed_row(ist.REASON_TIMEOUT))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "extracting", "run_id": "r1"})
    assert r.status_code == 200, r.text
    (args, kw), = calls
    assert args == (_ID, "extracting")
    # update_status itself clears `failure` for any non-failed status; the route must therefore
    # never pass one here.
    assert "failure" not in kw


def test_a_timeout_failed_row_accepts_a_late_failed_report(doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _failed_row(ist.REASON_TIMEOUT))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={
        "stage": "failed", "reason_code": "ocr_unreadable", "reason": "real cause"})
    assert r.status_code == 200, r.text
    assert calls[0][1]["failure"]["reason_code"] == "ocr_unreadable"


def test_a_failed_row_with_any_other_reason_code_stays_terminal(doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _failed_row("ocr_unreadable"))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "extracting"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "backwards_move"
    assert calls == []


def test_a_legacy_failed_row_with_no_stored_failure_stays_terminal(doc_tools_client, monkeypatch):
    calls = _stage_rig(monkeypatch, _row(ist.FAILED, failure=None))
    r = doc_tools_client.post(f"/ingest/{_ID}/stage", json={"stage": "extracting"})
    assert r.status_code == 409, r.text
    assert calls == []


def test_update_status_clears_failure_on_a_move_off_failed_and_refuses_failure_off_failed():
    cm, conn, cur = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ist.update_status(_ID, ist.EXTRACTING)
    sql, params = cur.execute.call_args[0]
    assert "failure = %s" in sql
    assert params[6] is None  # failure
    with pytest.raises(ValueError):
        ist.update_status(_ID, ist.EXTRACTING, failure={"reason_code": "x"})


# ===========================================================================
# Status route
# ===========================================================================
def _status_rig(monkeypatch, rows):
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: rows.get(ingest_id))


def test_status_failure_is_none_for_a_non_failed_row(dropper, monkeypatch):
    _status_rig(monkeypatch, {_ID: _row(ist.EXTRACTING)})
    body = dropper.get(f"/ingest/{_ID}/status").json()
    assert body["failure"] is None
    assert body["attempt"] == 1


def test_status_reports_the_stored_failure_for_a_failed_row(dropper, monkeypatch):
    stored = {"reason_code": "ocr_unreadable", "reason": "blank scan", "step": "extract",
              "run_id": "run-1", "pin_digest": None, "failed_at": 77}
    _status_rig(monkeypatch, {_ID: _row(ist.FAILED, failure=stored, detail="blank scan", attempt=3)})
    body = dropper.get(f"/ingest/{_ID}/status").json()
    assert body["stage"] == "failed"
    assert body["failure"] == stored
    assert body["attempt"] == 3


def test_status_synthesises_an_unclassified_failure_for_a_legacy_failed_row(dropper, monkeypatch):
    row = _row(ist.FAILED, detail="old failure", updated_at=1234)
    del row["attempt"]
    row["failure"] = None
    _status_rig(monkeypatch, {_ID: row})
    body = dropper.get(f"/ingest/{_ID}/status").json()
    assert body["failure"] == {"reason_code": None, "reason": "old failure", "step": None,
                               "run_id": None, "pin_digest": None, "failed_at": 1234}
    assert body["attempt"] == 1  # a missing key defaults to 1


def test_status_of_a_duplicate_row_reports_the_originals_failure_and_attempt(dropper, monkeypatch):
    original_failure = {"reason_code": "ocr_unreadable", "reason": "ORIGINAL", "step": None,
                        "run_id": None, "pin_digest": None, "failed_at": 9}
    original = _row(ist.FAILED, failure=original_failure, attempt=4)
    original["id"] = _DUP
    dup = _row(ist.DUPLICATE, duplicate_of=_DUP, detail="dup", attempt=1,
               failure={"reason_code": "WRONG", "reason": "the duplicate row's own"})
    _status_rig(monkeypatch, {_ID: dup, _DUP: original})
    body = dropper.get(f"/ingest/{_ID}/status").json()
    assert body["stage"] == "failed"
    assert body["failure"] == original_failure
    assert body["attempt"] == 4


# ===========================================================================
# Retry route
# ===========================================================================
def test_the_dropper_reopens_their_own_failed_pdf_row(dropper, monkeypatch):
    monkeypatch.setattr(ist, "get_status_for",
                        lambda ingest_id, *, caller_id: _row(ist.FAILED))
    monkeypatch.setattr(ist, "get_status_unscoped",
                        lambda i: (_ for _ in ()).throw(AssertionError("person reached unscoped")))
    seen = []
    monkeypatch.setattr(ist, "retry_failed", lambda i: seen.append(i) or 2)
    r = dropper.post(f"/ingest/{_ID}/retry")
    assert r.status_code == 200, r.text
    assert r.json() == {"ingest_id": _ID, "stage": "received", "attempt": 2}
    assert seen == [_ID]


def test_a_person_who_cannot_see_the_failed_row_gets_the_same_403_as_any_refusal(dropper, monkeypatch):
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: None)
    monkeypatch.setattr(ist, "get_status_unscoped", lambda i: _row(ist.FAILED))
    monkeypatch.setattr(ist, "retry_failed",
                        lambda i: (_ for _ in ()).throw(AssertionError("retried a stranger's row")))
    r = dropper.post(f"/ingest/{_ID}/retry")
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "retry_is_pin_driven"


def test_a_person_cannot_retry_their_own_failed_event_row(dropper, monkeypatch):
    monkeypatch.setattr(ist, "get_status_for",
                        lambda ingest_id, *, caller_id: _row(ist.FAILED, kind=ist.EVENT))
    monkeypatch.setattr(ist, "retry_failed",
                        lambda i: (_ for _ in ()).throw(AssertionError("retried an event")))
    r = dropper.post(f"/ingest/{_ID}/retry")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "retry_is_pin_driven"


def test_a_service_reopens_a_failed_pdf_row_with_no_body_and_no_pin(service, monkeypatch):
    monkeypatch.setattr(ist, "get_status_unscoped", lambda i: _row(ist.FAILED))
    monkeypatch.setattr(ist, "retry_failed", lambda i: 2)
    r = service.post(f"/ingest/{_ID}/retry")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "received"


def test_a_service_retry_of_a_failed_event_row_is_409_terminal(service, monkeypatch):
    monkeypatch.setattr(ist, "get_status_unscoped",
                        lambda i: _row(ist.FAILED, kind=ist.EVENT, pin_digest="sha256:" + "1" * 64))
    monkeypatch.setattr(ist, "retry_failed",
                        lambda i: (_ for _ in ()).throw(AssertionError("retried an event")))
    r = service.post(f"/ingest/{_ID}/retry", json={"pin_digest": "sha256:" + "2" * 64})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {"error": "terminal", "stage": "failed"}


def test_a_retry_that_loses_the_race_is_409_not_failed(dropper, monkeypatch):
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: _row(ist.FAILED))
    monkeypatch.setattr(ist, "retry_failed", lambda i: None)
    r = dropper.post(f"/ingest/{_ID}/retry")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {"error": "not_failed"}


# ===========================================================================
# SQL substrate, against a recording cursor double
# ===========================================================================
def _fake_conn(fetchone_row=None, fetchall_rows=()):
    cur = mock.MagicMock()
    cur.fetchone.return_value = fetchone_row
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


def test_fail_stale_received_is_one_atomic_update_over_stale_received_document_rows():
    cm, conn, cur = _fake_conn(fetchall_rows=[("id-1",), ("id-2",)])
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ids = ist.fail_stale_received(older_than_seconds=600, now_ms=10_000_000)
    assert ids == ["id-1", "id-2"]
    assert cur.execute.call_count == 1
    sql, params = cur.execute.call_args[0]
    sql = _norm(sql)
    assert sql.startswith("UPDATE ingest_status_projection")
    assert "WHERE status = 'received'" in sql
    # an event row at `received` is the case runner's fact, not the pipeline's
    assert "kind <> 'event'" in sql
    assert "updated_at < %s" in sql
    assert "RETURNING id" in sql
    # each row carries its OWN run_id, read in SQL
    assert "'run_id', run_id" in sql
    assert "'step', 'received'" in sql
    assert ist.REASON_TIMEOUT in params
    assert (10_000_000 - 600 * 1000) in params  # the threshold
    assert "600 seconds" in params[1]  # the reason text names the bound
    conn.commit.assert_called_once()


def test_retry_failed_is_one_atomic_update_guarded_on_failed_and_bumps_attempt():
    cm, conn, cur = _fake_conn(fetchone_row=(3,))
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        n = ist.retry_failed(_ID, now_ms=42)
    assert n == 3
    assert cur.execute.call_count == 1
    sql, params = cur.execute.call_args[0]
    sql = _norm(sql)
    assert "status = 'received'" in sql and "failure = NULL" in sql and "detail = NULL" in sql
    assert "attempt = attempt + 1" in sql
    assert "AND status = 'failed'" in sql
    assert "kind <> 'event'" in sql
    assert "RETURNING attempt" in sql
    assert params == (42, _ID)


def test_retry_failed_returns_none_when_no_row_matched():
    cm, _, _ = _fake_conn(fetchone_row=None)
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        assert ist.retry_failed(_ID) is None


def test_the_selects_carry_failure_run_id_and_attempt_and_parse_failure_json():
    stored = {"reason_code": "timeout", "reason": "r"}
    raw = {"id": _ID, "failure": json.dumps(stored), "run_id": "r", "attempt": 2,
           "origin_suggestion": None}
    for fn in (lambda: ist.get_row(_ID), lambda: ist.get_status_unscoped(_ID),
               lambda: ist.get_status_for(_ID, caller_id="alice@example.com")):
        cm, _, cur = _fake_conn(fetchone_row=dict(raw))
        with mock.patch.object(ist, "_pg_connect", return_value=cm):
            out = fn()
        sql = _norm(cur.execute.call_args[0][0])
        assert "failure, run_id, attempt" in sql
        assert out["failure"] == stored


# ===========================================================================
# Watchdog
# ===========================================================================
def test_one_watchdog_tick_calls_fail_stale_received_with_the_configured_timeout(monkeypatch):
    seen = []
    monkeypatch.setattr(ist, "fail_stale_received",
                        lambda *, older_than_seconds, now_ms=None: seen.append(older_than_seconds) or ["x"])
    assert asyncio.run(gateway._ingest_watchdog_tick(321)) == ["x"]
    assert seen == [321]


@pytest.mark.parametrize("value", ["0", "-5"])
def test_a_non_positive_timeout_disables_the_watchdog_and_starts_no_task(monkeypatch, value):
    monkeypatch.setenv("INGEST_RECEIVED_TIMEOUT_SECONDS", value)
    with mock.patch.object(gateway.asyncio, "create_task") as ct:
        assert gateway._start_ingest_watchdog() is None
    ct.assert_not_called()


def test_the_watchdog_defaults_to_600_seconds_not_the_sensor_interval(monkeypatch):
    monkeypatch.delenv("INGEST_RECEIVED_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("INGEST_WATCHDOG_INTERVAL_SECONDS", raising=False)
    started = []

    def _fake_create_task(coro):
        started.append(coro.cr_frame.f_locals.copy())
        coro.close()
        return mock.Mock()
    with mock.patch.object(gateway.asyncio, "create_task", _fake_create_task):
        assert gateway._start_ingest_watchdog() is not None
    assert started[0]["timeout_s"] == 600
    assert started[0]["interval_s"] == 30
