"""The ingestion seam's BFF routes (ADR-0041 §8, days 1-3) — POST /ingest,
GET /ingest/{id}/status, and the /electric/shape WHERE-injection branch for
ingest_status_projection.

Harness mirrors tests/planning/test_gateway_plan_routes.py: TestClient(gateway.app) +
dependency_overrides[get_current_user], and the DB/object-store layers are faked rather than
hit for real — these are tests of the ROUTE's translation and gate, not of ingest_status.py's
SQL (covered separately in tests/test_ingest_status_projection.py) or of a live MinIO.

WHAT THESE DEFEND:
  * deny-by-default: no token -> refused before any DB/S3 touch.
  * on_behalf_of must equal the caller -- no delegation in v1 (ADR-0041 §8 names the field,
    not a delegation mechanism; the narrower reading wins).
  * kind is validated against the closed ContentKind set BEFORE any write (never an
    LLM-classified or free-text kind reaching the object store).
  * level-1 dedupe: a sha256 hit returns the "already processed on <date> from <source>"
    message and NEVER touches the object store or record_received a second time.
    a miss writes the object AND records `received`.
  * GET status is existence-oracle-safe: a caller who is neither submitted_by nor
    on_behalf_of gets 404, not another user's row.
  * /electric/shape?table=ingest_status_projection injects the caller-scoped WHERE the same
    way human_task_projection's branch does, mirrored in the dispatch's SAME if/elif chain.
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402


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
def fake_s3(monkeypatch):
    """Captures every put_object call instead of touching MinIO -- the gateway._build_s3_client
    seam added alongside the routes for exactly this purpose."""
    calls: list[dict] = []

    class _FakeS3:
        def put_object(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _FakeS3())
    return calls


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest — auth, validation, dedupe, write
# ─────────────────────────────────────────────────────────────────────────────

def test_ingest_refuses_an_unauthenticated_caller():
    """No dependency override -- the REAL Depends(get_current_user) gate runs. No S3/DB touch
    is even possible to assert here (nothing to fake); the gate itself is the assertion."""
    with TestClient(gateway.app) as c:
        r = c.post("/ingest", files={"file": ("notice.pdf", b"%PDF-1.4 stub", "application/pdf")},
                   data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code in (401, 403), r.text


def test_ingest_rejects_an_undeclared_kind_before_any_write(client, fake_s3, monkeypatch):
    called = {"find": False}
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda *a, **k: called.__setitem__("find", True))
    r = client.post("/ingest", files={"file": ("part.docx", b"stub", "application/octet-stream")},
                    data={"kind": "docx", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 400
    assert "kind" in str(r.json()["detail"])
    assert called["find"] is False, "an undeclared kind reached the dedupe/DB layer"
    assert fake_s3 == [], "an undeclared kind reached the object store"


def test_ingest_refuses_an_on_behalf_of_that_is_not_the_caller(client, fake_s3, monkeypatch):
    """Deny-by-default, v1: no delegation mechanism exists, so on_behalf_of asserting a
    DIFFERENT identity than the authenticated caller is refused, not merely unverified."""
    called = {"find": False}
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda *a, **k: called.__setitem__("find", True))
    r = client.post("/ingest", files={"file": ("notice.pdf", b"%PDF-1.4 stub", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "someone-else@example.com"})
    assert r.status_code == 403
    assert called["find"] is False, "an on_behalf_of mismatch reached the dedupe/DB layer"
    assert fake_s3 == [], "an on_behalf_of mismatch reached the object store"


def test_ingest_dedupe_hit_returns_the_message_and_never_writes(client, fake_s3, monkeypatch):
    """Level-1 dedupe (ADR-0041 §8): a sha256 already on file returns the 'already processed'
    message and RECORDS the arrival as its own row -- but never touches the object store and
    never calls record_received (that would be a second primary row for the same sha)."""
    original = {"id": "deadbeef", "sha256": "deadbeef", "object_prefix": "ingress-user/pdf/deadbeef/",
                "source": "first-drop.pdf", "created_at": 1767225600000}
    dup_row = {"id": "new-uuid", "status": "duplicate", "duplicate_of": "deadbeef",
               "detail": "already processed on 2026-01-01 from first-drop.pdf"}
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: original)
    monkeypatch.setattr(ist, "record_duplicate_arrival", lambda **kw: dup_row)
    received_called = {"v": False}
    monkeypatch.setattr(ist, "record_received", lambda **kw: received_called.__setitem__("v", True))

    r = client.post("/ingest", files={"file": ("re-drop.pdf", b"same bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "duplicate"
    assert body["detail"] == "already processed on 2026-01-01 from first-drop.pdf"
    assert body["duplicate_of"] == "deadbeef"
    assert fake_s3 == [], "a duplicate arrival must never write the object store"
    assert received_called["v"] is False, "a duplicate arrival must never call record_received"


def test_ingest_new_arrival_writes_the_object_and_records_received(client, fake_s3, monkeypatch):
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    received = {}
    def _record_received(**kw):
        received.update(kw)
        return {"id": kw["sha256"], "status": "received"}
    monkeypatch.setattr(ist, "record_received", _record_received)

    r = client.post("/ingest", files={"file": ("notice.pdf", b"brand new bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "received"
    assert body["object_prefix"].startswith("ingress-user/pdf/")
    assert body["object_prefix"].endswith("/")
    # two objects written: the bytes + manifest.json (manifest + provenance block)
    keys = sorted(c["Key"] for c in fake_s3)
    assert any(k.endswith("manifest.json") for k in keys), fake_s3
    assert any(k.endswith("notice.pdf") for k in keys), fake_s3
    manifest_call = next(c for c in fake_s3 if c["Key"].endswith("manifest.json"))
    import json as _json
    manifest = _json.loads(manifest_call["Body"])
    assert manifest["metadata"]["content_kind"] == "pdf"
    assert manifest["provenance"]["obtained_via"] == "user-drop"
    assert manifest["provenance"]["authoritative_source"], "authoritative_source must be non-empty"
    assert received["kind"] == "pdf"
    assert received["submitted_by"] == "alice@example.com"


# ─────────────────────────────────────────────────────────────────────────────
# GET /ingest/{id}/status — existence-oracle-safe
# ─────────────────────────────────────────────────────────────────────────────

def test_status_owner_gets_the_row(client, monkeypatch):
    monkeypatch.setattr(ist, "get_status_for",
                        lambda ingest_id, *, caller_id: {"id": ingest_id, "status": "review"})
    r = client.get("/ingest/deadbeef/status")
    assert r.status_code == 200
    assert r.json()["status"] == "review"


def test_status_non_owner_gets_404_not_another_users_row(client, monkeypatch):
    """SECURITY: get_status_for scopes by caller itself (tested directly in
    test_ingest_status_projection.py); here we assert the ROUTE turns a None into a plain
    404, never leaking existence via a different status code."""
    captured = {}
    def _fake(ingest_id, *, caller_id):
        captured["caller_id"] = caller_id
        return None
    monkeypatch.setattr(ist, "get_status_for", _fake)
    r = client.get("/ingest/someone-elses-ingest/status")
    assert r.status_code == 404
    assert captured["caller_id"] == "alice@example.com", "the route must pass the VERIFIED caller"


# ─────────────────────────────────────────────────────────────────────────────
# /electric/shape?table=ingest_status_projection — server-injected WHERE
# ─────────────────────────────────────────────────────────────────────────────

class _ElectricResp:
    def __init__(self):
        self.status_code = 200
        self.headers = {"electric-handle": "h1", "electric-offset": "o1",
                        "electric-up-to-date": "true"}
        self.content = b"[]"


@pytest.fixture
def stub_electric(monkeypatch):
    sent: dict = {}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, **k):
            sent["url"] = url
            sent["params"] = params
            return _ElectricResp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    return sent


def test_electric_shape_injects_the_caller_scoped_where_for_ingest_status(client, stub_electric):
    r = client.get("/electric/shape", params={"table": "ingest_status_projection"})
    assert r.status_code == 200
    where = stub_electric["params"]["where"]
    assert "submitted_by = 'alice@example.com'" in where
    assert "on_behalf_of = 'alice@example.com'" in where
    assert " OR " in where


def test_electric_shape_client_cannot_override_the_where_for_ingest_status(client, stub_electric):
    """Same discipline as the pre-existing human_task_projection branch: any client-supplied
    `where` is silently dropped, never merged with or replacing the server-injected clause."""
    r = client.get("/electric/shape", params={"table": "ingest_status_projection",
                                               "where": "1=1"})
    assert r.status_code == 200
    where = stub_electric["params"]["where"]
    assert "1=1" not in where
    assert "submitted_by = 'alice@example.com'" in where
