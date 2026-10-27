"""POST /ingest/{ingest_id}/retry -- PIN-DRIVEN ONLY (architect ruling 2026-10-10; supersedes the
dropper's own retry of roll #20 item 3). The caller is a SERVICE sending {pin_digest}; the pin-gate
arms live in tests/test_steward_correction.py, these defend the dispatch BEHIND the gate.

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


_RID = "sha256:" + "d" * 64
_OLD = "sha256:" + "1" * 64
_NEW = {"pin_digest": "sha256:" + "2" * 64}
_SVC = "svc:pin-driver"


def _extraction_for(row, monkeypatch, *, name="doc.pdf"):
    """Gives `row` its object_prefix and stubs the manifest read; returns the `extraction_ref` the
    row carries (what the stage route recorded when it moved the row to review)."""
    hex_ = row["id"].split(":", 1)[-1]
    row["object_prefix"] = f"ingress-user/pdf/{hex_}/"
    ref = f"{row['object_prefix']}generated/doc_pdf/doc-tools@61f74dc/manifest.json"
    manifest = {"doc_id": "N-1", "filename": name, "source_key": row["object_prefix"] + name,
                "pipeline_version": "doc-tools@61f74dc", "ingest_id": row["id"],
                "provenance": {"standing": "supervised", "ingest_id": row["id"]}}
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: manifest)
    return ref


@pytest.fixture
def client():
    user = type("U", (), {"authz_id": _SVC, "id": _SVC,
                          "sub": _SVC, "email": _SVC,
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


def test_retry_missing_row_gets_404(client, monkeypatch):
    monkeypatch.setattr(ist, "get_status_unscoped", lambda ingest_id: None)
    r = client.post("/ingest/no-such-row/retry", json=_NEW)
    assert r.status_code == 404


# FAILED is not in this list for a DOCUMENT row any more: 2026-10-12 ("pipeline failure must reach
# the row") makes a failed document row retryable (tests/test_a_pipeline_failure_reaches_the_row.py).
# A failed EVENT row stays terminal -- its fix is to resend the event -- so FAILED is exercised here
# with kind=event, every other stage with a pdf row as before.
@pytest.mark.parametrize("stage,kind", [
    (ist.PROMOTED, "pdf"), (ist.REJECTED, "pdf"), (ist.FAILED, ist.EVENT), (ist.DUPLICATE, "pdf"),
    (ist.CASE_OPENED, "pdf"), (ist.REVIEW_REJECTED, "pdf")])
def test_retry_terminal_stage_returns_409(client, monkeypatch, stage, kind):
    row = {"id": "deadbeef", "status": stage, "kind": kind,
          "submitted_by": "alice@example.com", "pin_digest": _OLD}
    monkeypatch.setattr(ist, "get_status_unscoped", lambda ingest_id: row)
    r = client.post("/ingest/deadbeef/retry", json=_NEW)
    assert r.status_code == 409, r.text
    assert {k: v for k, v in r.json()["detail"].items() if k != "message"} == {"error": "terminal", "stage": stage}
    assert r.json()["detail"]["message"].strip()


def test_retry_event_row_at_received_returns_409_resend_the_event(client, monkeypatch):
    row = {"id": "evt-deadbeef", "status": ist.RECEIVED, "kind": ist.EVENT,
          "submitted_by": "alice@example.com", "pin_digest": _OLD}
    monkeypatch.setattr(ist, "get_status_unscoped", lambda ingest_id: row)
    r = client.post("/ingest/evt-deadbeef/retry", json=_NEW)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "resend_the_event"


@pytest.mark.parametrize("stage", [ist.RECEIVED, ist.EXTRACTING])
def test_retry_document_row_in_pipeline_returns_409(client, monkeypatch, stage):
    row = {"id": "deadbeef", "status": stage, "kind": "pdf",
          "submitted_by": "alice@example.com", "pin_digest": _OLD}
    monkeypatch.setattr(ist, "get_status_unscoped", lambda ingest_id: row)
    r = client.post("/ingest/deadbeef/retry", json=_NEW)
    assert r.status_code == 409, r.text
    body = r.json()["detail"]
    assert body["error"] == "in_pipeline"
    assert body["pipeline"] == "doc-tools"
    assert body["stage"] == stage


def test_retry_review_row_with_no_task_files_it(client, monkeypatch):
    row = {"id": _RID, "status": ist.REVIEW, "kind": "pdf", "content_kind": "pcn",
          "submitted_by": "alice@example.com", "pin_digest": _OLD}
    monkeypatch.setattr(ist, "get_status_unscoped", lambda ingest_id: row)
    _stub_domain(monkeypatch)
    row["extraction_ref"] = _extraction_for(row, monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: False)
    registered = []
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: registered.append(kw) or {"task_id": kw["task_id"], "recipients": ["x"]})
    r = client.post(f"/ingest/{_RID}/retry", json=_NEW)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ingest_id": _RID, "stage": "review",
                    "task_id": f"{promotion.KIND}:{_RID}", "task_status": "FILED"}
    assert len(registered) == 1, registered
    reg = registered[0]
    assert reg["audience"] == f"{promotion.KIND}:SUSTAINMENT"
    assert reg["requested_by"] == _SVC, \
        "requested_by for a retry is the RETRYING (service) caller's own authz_id"


def test_retry_review_row_whose_task_exists_returns_already_filed(client, monkeypatch):
    row = {"id": "deadbeef", "status": ist.REVIEW, "kind": "pdf", "content_kind": "pcn",
          "submitted_by": "alice@example.com", "pin_digest": _OLD}
    monkeypatch.setattr(ist, "get_status_unscoped", lambda ingest_id: row)
    _stub_domain(monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: True)
    monkeypatch.setattr(ht, "get_open_task_payload", lambda task_id: None)
    registered = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: registered.append(kw))
    r = client.post("/ingest/deadbeef/retry", json=_NEW)
    assert r.status_code == 200, r.text
    assert r.json()["task_status"] == "ALREADY_FILED"
    assert registered == [], "register_task must NOT be called when the task already exists"


def test_retry_review_row_domainless_content_kind_returns_422(client, monkeypatch):
    row = {"id": "deadbeef", "status": ist.REVIEW, "kind": "pdf", "content_kind": None,
          "submitted_by": "alice@example.com", "pin_digest": _OLD}
    monkeypatch.setattr(ist, "get_status_unscoped", lambda ingest_id: row)
    monkeypatch.setattr(ck, "by_kind", lambda kind: None)
    task_calls = []
    monkeypatch.setattr(ht, "task_exists", lambda task_id: task_calls.append(task_id) or False)
    registered = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: registered.append(kw))
    r = client.post("/ingest/deadbeef/retry", json=_NEW)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "no_declared_domain"
    assert task_calls == []
    assert registered == []


@pytest.mark.parametrize("own", [
    {"id": _RID, "status": ist.REVIEW, "kind": "pdf", "pin_digest": _OLD},   # their own row
    None,                                                                   # not theirs / none
], ids=["own-review-row", "no-visible-row"])
def test_retry_on_behalf_of_human_is_refused_403(obo_client, monkeypatch, own):
    """The old dropper path is closed for RE-EXTRACTION: even the row's own principal is a person,
    and a person never drives one. A person is looked up SCOPED only (their own rows), never
    unscoped, and gets the SAME 403 whether the row is theirs at `review` or invisible to them --
    so the answer is no existence oracle. (Rev 187: their own `awaiting_origin` row re-files under
    Q2c instead; gov's seal in test_promotion_filing_is_a_function_of_state.py owns that arm.)"""
    monkeypatch.setattr(ist, "get_status_unscoped",
                        lambda ingest_id: pytest.fail("a person must never reach the unscoped lookup"))
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, caller_id: own)
    r = obo_client.post(f"/ingest/{_RID}/retry", json=_NEW)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error"] == "retry_is_pin_driven"
