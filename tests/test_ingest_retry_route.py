"""POST /ingest/{ingest_id}/retry (roll #20 item 3) -- let the dropper un-strand their own row
without a hand write.

Harness/idiom mirrors tests/test_gateway_ingest_routes.py: TestClient(gateway.app) +
dependency_overrides[get_current_user], ingest_status.get_status_for stubbed directly (its own
SQL/scoping is covered in tests/test_ingest_status_projection.py) and human_tasks/content_kinds
stubbed the same way the stage-route review tests do -- these are tests of THIS route's
dispatch, not of the DB or a live HITL config.

WHAT THESE DEFEND:
  * existence-oracle-safe: a stranger and a missing row get the identical 404 body the status
    route's own 404 gets -- the route reuses `ingest_status.get_status_for`, not a second,
    divergent lookup/predicate.
  * terminal stages (promoted/rejected/failed/duplicate/case_opened) refuse 409 `terminal`.
  * an EVENT row refuses 409 `resend_the_event` -- it holds only the payload hash.
  * a DOCUMENT row at received/extracting refuses 409 `in_pipeline` -- doc-tools owns that move.
  * a DOCUMENT row at review re-runs the SAME find-or-file `update_ingest_stage` uses
    (`_file_or_find_document_promotion_task`), with `requested_by` the RETRYING caller, not
    doc-tools' service identity; a domainless content_kind still refuses 422.
  * an on_behalf_of caller (not the submitter) is allowed -- same scoping as GET status.
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import promotion  # noqa: E402


@pytest.fixture
def client():
    user = type("U", (), {"authz_id": "alice@example.com", "id": "alice@example.com",
                          "sub": "alice@example.com", "email": "alice@example.com",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def obo_client():
    """The on_behalf_of PRINCIPAL, not the submitter -- same caller-scoping discipline GET
    /ingest/{id}/status relies on (submitted_by == caller OR on_behalf_of == caller)."""
    user = type("U", (), {"authz_id": "bob@example.com", "id": "bob@example.com",
                          "sub": "bob@example.com", "email": "bob@example.com",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


def _stub_domain(monkeypatch, domain="sustainment", expected="pcn"):
    """SAME idiom as test_gateway_ingest_routes.py's own `_stub_domain`: answers ONLY for
    `expected`, so a stub that cannot discriminate can never hide a `by_kind(row["kind"])`
    regression (the file format, not the declared content_kind)."""
    reg = type("Reg", (), {"domain": domain})()
    monkeypatch.setattr(ck, "by_kind", lambda kind: reg if kind == expected else None)


def test_retry_stranger_gets_404(client, monkeypatch):
    captured = {}
    def _fake(ingest_id, *, caller_id):
        captured["caller_id"] = caller_id
        return None
    monkeypatch.setattr(ist, "get_status_for", _fake)
    r = client.post("/ingest/someone-elses-ingest/retry")
    assert r.status_code == 404
    assert captured["caller_id"] == "alice@example.com"
    stranger_body = r.json()

    r2 = client.post("/ingest/no-such-row/retry")
    assert r2.status_code == 404
    assert r2.json() == stranger_body, "a stranger and a missing row get the IDENTICAL 404 body"


@pytest.mark.parametrize("stage", [ist.PROMOTED, ist.REJECTED, ist.FAILED, ist.DUPLICATE,
                                   ist.CASE_OPENED])
def test_retry_terminal_stage_returns_409(client, monkeypatch, stage):
    row = {"id": "deadbeef", "status": stage, "kind": "pdf",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: row)
    r = client.post("/ingest/deadbeef/retry")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == {"error": "terminal", "stage": stage}


def test_retry_event_row_at_received_returns_409_resend_the_event(client, monkeypatch):
    row = {"id": "evt-deadbeef", "status": ist.RECEIVED, "kind": ist.EVENT,
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: row)
    r = client.post("/ingest/evt-deadbeef/retry")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "resend_the_event"


@pytest.mark.parametrize("stage", [ist.RECEIVED, ist.EXTRACTING])
def test_retry_document_row_in_pipeline_returns_409(client, monkeypatch, stage):
    row = {"id": "deadbeef", "status": stage, "kind": "pdf",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: row)
    r = client.post("/ingest/deadbeef/retry")
    assert r.status_code == 409, r.text
    body = r.json()["detail"]
    assert body["error"] == "in_pipeline"
    assert body["pipeline"] == "doc-tools"
    assert body["stage"] == stage


def test_retry_review_row_with_no_task_files_it(client, monkeypatch):
    row = {"id": "deadbeef", "status": ist.REVIEW, "kind": "pdf", "content_kind": "pcn",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: row)
    _stub_domain(monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: False)
    registered = []
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: registered.append(kw) or {"task_id": kw["task_id"], "recipients": ["x"]})
    r = client.post("/ingest/deadbeef/retry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ingest_id": "deadbeef", "stage": "review",
                    "task_id": f"{promotion.KIND}:deadbeef", "task_status": "FILED"}
    assert len(registered) == 1, registered
    reg = registered[0]
    assert reg["audience"] == f"{promotion.KIND}:SUSTAINMENT"
    assert reg["requested_by"] == "alice@example.com", \
        "requested_by for a retry is the RETRYING caller's own authz_id"


def test_retry_review_row_whose_task_exists_returns_already_filed(client, monkeypatch):
    row = {"id": "deadbeef", "status": ist.REVIEW, "kind": "pdf", "content_kind": "pcn",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: row)
    _stub_domain(monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: True)
    registered = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: registered.append(kw))
    r = client.post("/ingest/deadbeef/retry")
    assert r.status_code == 200, r.text
    assert r.json()["task_status"] == "ALREADY_FILED"
    assert registered == [], "register_task must NOT be called when the task already exists"


def test_retry_review_row_domainless_content_kind_returns_422(client, monkeypatch):
    row = {"id": "deadbeef", "status": ist.REVIEW, "kind": "pdf", "content_kind": None,
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: row)
    monkeypatch.setattr(ck, "by_kind", lambda kind: None)
    task_calls = []
    monkeypatch.setattr(ht, "task_exists", lambda task_id: task_calls.append(task_id) or False)
    registered = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: registered.append(kw))
    r = client.post("/ingest/deadbeef/retry")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "no_declared_domain"
    assert task_calls == []
    assert registered == []


def test_retry_on_behalf_of_caller_is_allowed(obo_client, monkeypatch):
    """The on_behalf_of PRINCIPAL (not the submitter) can retry their own row -- same caller
    scoping GET /ingest/{id}/status relies on."""
    row = {"id": "deadbeef", "status": ist.REVIEW, "kind": "pdf", "content_kind": "pcn",
          "submitted_by": "alice@example.com", "on_behalf_of": "bob@example.com"}
    captured = {}
    def _fake(ingest_id, *, caller_id):
        captured["caller_id"] = caller_id
        return row
    monkeypatch.setattr(ist, "get_status_for", _fake)
    _stub_domain(monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: False)
    registered = []
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: registered.append(kw) or {"task_id": kw["task_id"], "recipients": ["x"]})
    r = obo_client.post("/ingest/deadbeef/retry")
    assert r.status_code == 200, r.text
    assert captured["caller_id"] == "bob@example.com"
    assert registered[0]["requested_by"] == "bob@example.com"
