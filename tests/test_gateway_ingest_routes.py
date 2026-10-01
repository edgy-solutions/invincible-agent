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
  * a NEW arrival calls `_create_ingest_node` exactly once, with the minted ingest_id, the
    route's own kind, the sha256, the manifest's object_ref and the caller's authz_id as
    subject -- a DUPLICATE arrival never calls it, and a raise from the helper is logged and
    swallowed: the route still answers 200 with the same body (ruled 2026-09-30).
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
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
def fake_s3(monkeypatch):
    """Captures every put_object call instead of touching MinIO -- the gateway._build_s3_client
    seam added alongside the routes for exactly this purpose."""
    calls: list[dict] = []

    class _FakeS3:
        def put_object(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _FakeS3())
    return calls


@pytest.fixture
def fake_create_node(monkeypatch):
    """Captures every _create_ingest_node call instead of touching Neo4j -- the module-level
    helper exists for exactly this seam (gateway._create_ingest_node's own docstring)."""
    calls: list[dict] = []
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: calls.append(kw))
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


def test_ingest_dedupe_hit_returns_the_message_and_never_writes(
        client, fake_s3, fake_create_node, monkeypatch):
    """Level-1 dedupe (ADR-0041 §8): a sha256 already on file returns the 'already processed'
    message and RECORDS the arrival as its own row -- but never touches the object store and
    never calls record_received (that would be a second primary row for the same sha)."""
    original = {"id": "deadbeef", "sha256": "deadbeef", "object_prefix": "ingress-user/pdf/deadbeef/",
                "source": "first-drop.pdf", "created_at": 1767225600000, "status": "received"}
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
    assert body["ingest_id"] == "new-uuid"
    # stage is the ORIGINAL row's current status, not the duplicate row's own "duplicate" status
    assert body["stage"] == "received"
    assert body["detail"] == "already processed on 2026-01-01 from first-drop.pdf"
    assert body["duplicate"] == {"of_ingest_id": "deadbeef",
                                 "message": "already processed on 2026-01-01 from first-drop.pdf"}
    assert fake_s3 == [], "a duplicate arrival must never write the object store"
    assert received_called["v"] is False, "a duplicate arrival must never call record_received"
    assert fake_create_node == [], "a duplicate arrival must never call _create_ingest_node"


def test_ingest_new_arrival_writes_the_object_and_records_received(
        client, fake_s3, fake_create_node, monkeypatch):
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    received = {}
    def _record_received(**kw):
        received.update(kw)
        return {"id": kw["ingest_id"], "status": "received"}
    monkeypatch.setattr(ist, "record_received", _record_received)

    body_bytes = b"brand new bytes"
    r = client.post("/ingest", files={"file": ("notice.pdf", body_bytes, "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 200
    body = r.json()
    expected_ingest_id = promotion.ingest_id_for(body_bytes)
    # THE SAME DERIVATION document_promotion requires (promotion.ingest_id_for), so a
    # seam-minted document is never refused promotion for a spelling mismatch.
    assert body["ingest_id"] == expected_ingest_id
    assert promotion.INGEST_ID_RE.match(body["ingest_id"])
    assert body["stage"] == "received"
    assert body["detail"] is None
    assert body["duplicate"] is None
    assert body["object_prefix"].startswith("ingress-user/pdf/")
    assert body["object_prefix"].endswith("/")
    # two objects written: the bytes + manifest.json (manifest + provenance block)
    keys = sorted(c["Key"] for c in fake_s3)
    assert any(k.endswith("manifest.json") for k in keys), fake_s3
    assert any(k.endswith("notice.pdf") for k in keys), fake_s3
    manifest_call = next(c for c in fake_s3 if c["Key"].endswith("manifest.json"))
    import json as _json
    manifest = _json.loads(manifest_call["Body"])
    # FORMAT IS NOT KIND: undeclared content_kind -> manifest.content_kind is None and no
    # metadata.content_kind at all (never the route's own file-format `kind`).
    assert manifest["content_kind"] is None
    assert "metadata" not in manifest
    assert manifest["media_kind"] == "pdf"
    assert manifest["ingest_id"] == expected_ingest_id
    assert manifest["initiator"] == {"subject": "alice@example.com", "kind": "person",
                                     "on_behalf_of": None}
    assert manifest["provenance"]["obtained_via"] == "user-drop"
    assert manifest["provenance"]["authoritative_source"], "authoritative_source must be non-empty"
    # ONE id for the document across manifest, block and status row -- not a second derivation.
    assert manifest["provenance"]["ingest_id"] == expected_ingest_id == manifest["ingest_id"]
    assert received["kind"] == "pdf"
    assert received["ingest_id"] == expected_ingest_id
    assert received["submitted_by"] == "alice@example.com"
    # _create_ingest_node runs for a NEW arrival exactly once, with the minted ingest_id, the
    # route's own (file-format) kind, the sha256, the manifest's object_ref and the caller's
    # authz_id as subject (ruled 2026-09-30).
    assert len(fake_create_node) == 1, fake_create_node
    call = fake_create_node[0]
    assert call["ingest_id"] == expected_ingest_id
    assert call["kind"] == "pdf"
    assert call["sha256"] == gateway.hashlib.sha256(body_bytes).hexdigest()
    assert call["object_ref"] == manifest["object_ref"]
    assert call["subject"] == "alice@example.com"
    assert call["ingested_at"] == manifest["provenance"]["ingested_at"]


def test_ingest_new_arrival_still_returns_200_when_create_ingest_node_raises(
        client, fake_s3, monkeypatch):
    """BEST-EFFORT (ruled 2026-09-30): the bytes, manifest and status row are already durable by
    the time this runs, so a graph outage must be logged, never fail an otherwise-successful
    upload -- the route answers 200 with the same body it would have without the failure."""
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})

    def _boom(**kw):
        raise RuntimeError("neo4j unreachable")
    monkeypatch.setattr(gateway, "_create_ingest_node", _boom)

    body_bytes = b"node creation fails but the upload must not"
    r = client.post("/ingest", files={"file": ("notice.pdf", body_bytes, "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    expected_ingest_id = promotion.ingest_id_for(body_bytes)
    assert body["ingest_id"] == expected_ingest_id
    assert body["stage"] == "received"
    assert body["detail"] is None
    assert body["duplicate"] is None


def test_ingest_declared_content_kind_lands_in_manifest_and_metadata(client, fake_s3, monkeypatch):
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})

    r = client.post("/ingest", files={"file": ("wi.pdf", b"declared kind bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                          "content_kind": "work-instruction"})
    assert r.status_code == 200, r.text
    manifest_call = next(c for c in fake_s3 if c["Key"].endswith("manifest.json"))
    import json as _json
    manifest = _json.loads(manifest_call["Body"])
    assert manifest["content_kind"] == "work-instruction"
    assert manifest["metadata"]["content_kind"] == "work-instruction"
    assert manifest["media_kind"] == "pdf"


@pytest.mark.parametrize("bad_content_kind", ["a/b", "   "])
def test_ingest_refuses_a_malformed_content_kind_before_any_write(
        client, fake_s3, monkeypatch, bad_content_kind):
    looked = {"n": 0}
    def _find(sha):
        looked["n"] += 1
        return None
    monkeypatch.setattr(ist, "find_primary_by_sha", _find)
    r = client.post("/ingest", files={"file": ("wi.pdf", b"stub", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                          "content_kind": bad_content_kind})
    assert r.status_code == 422, r.text
    assert looked["n"] == 0 and fake_s3 == [], "a malformed content_kind must be refused before any lookup or write"


def test_ingest_refuses_a_content_kind_over_128_chars(client, fake_s3, monkeypatch):
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    r = client.post("/ingest", files={"file": ("wi.pdf", b"stub", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                          "content_kind": "x" * 129})
    assert r.status_code == 422, r.text
    assert fake_s3 == []


def test_ingest_refuses_one_byte_over_the_cap_before_any_lookup_or_write(client, fake_s3, monkeypatch):
    """The door buffers in the BFF pod, so its size is bounded: one byte over INGEST_MAX_BYTES
    is 413 before dedupe is consulted or the store is touched; exactly AT the cap is accepted
    (the control that shows the refusal is the cap, not the fixture)."""
    monkeypatch.setenv("INGEST_MAX_BYTES", "16")
    looked = {"n": 0}
    def _find(sha):
        looked["n"] += 1
        return None
    monkeypatch.setattr(ist, "find_primary_by_sha", _find)
    monkeypatch.setattr(ist, "record_received", lambda **kw: {"id": kw["sha256"], "status": "received"})

    over = client.post("/ingest", files={"file": ("big.pdf", b"x" * 17, "application/pdf")},
                       data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert over.status_code == 413, over.text
    assert looked["n"] == 0 and fake_s3 == [], "an oversize drop must be refused before any lookup or write"

    at = client.post("/ingest", files={"file": ("ok.pdf", b"x" * 16, "application/pdf")},
                     data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert at.status_code == 200, at.text
    assert looked["n"] == 1



# ─────────────────────────────────────────────────────────────────────────────
# GET /ingest/{id}/status — existence-oracle-safe
# ─────────────────────────────────────────────────────────────────────────────

def test_status_owner_gets_the_row(client, monkeypatch):
    monkeypatch.setattr(
        ist, "get_status_for",
        lambda ingest_id, *, caller_id: {"id": ingest_id, "status": "awaiting_disposition",
                                        "kind": "pdf", "sha256": "deadbeef",
                                        "created_at": 1, "updated_at": 2})
    r = client.get("/ingest/deadbeef/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ingest_id"] == "deadbeef"
    assert body["stage"] == "awaiting_disposition"
    assert body["duplicate"] is None
    assert "id" not in body and "status" not in body, "one name per field: id/status are dropped"


def test_status_of_a_duplicate_row_reports_the_ORIGINALS_current_stage(client, monkeypatch):
    rows = {
        "new-uuid": {"id": "new-uuid", "status": "duplicate", "duplicate_of": "deadbeef",
                    "detail": "already processed on 2026-01-01 from first-drop.pdf",
                    "kind": "pdf", "sha256": "deadbeef", "created_at": 1, "updated_at": 1},
        "deadbeef": {"id": "deadbeef", "status": "promoted", "kind": "pdf", "sha256": "deadbeef",
                    "created_at": 1, "updated_at": 2},
    }
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: rows.get(ingest_id))
    r = client.get("/ingest/new-uuid/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ingest_id"] == "new-uuid"
    assert body["stage"] == "promoted", "the ORIGINAL's current stage, not the row's own 'duplicate'"
    assert body["duplicate"] == {"of_ingest_id": "deadbeef",
                                 "message": "already processed on 2026-01-01 from first-drop.pdf"}


def test_status_of_a_duplicate_row_whose_original_is_not_visible_reports_None_not_received(
        client, monkeypatch):
    """EXISTENCE-ORACLE: a stage of None, never the tempting 'received' default, when the
    caller-scoped lookup of the original comes back empty."""
    rows = {
        "new-uuid": {"id": "new-uuid", "status": "duplicate", "duplicate_of": "deadbeef",
                    "detail": "already processed on 2026-01-01 from first-drop.pdf",
                    "kind": "pdf", "sha256": "deadbeef", "created_at": 1, "updated_at": 1},
    }
    monkeypatch.setattr(ist, "get_status_for", lambda ingest_id, *, caller_id: rows.get(ingest_id))
    r = client.get("/ingest/new-uuid/status")
    assert r.status_code == 200
    assert r.json()["stage"] is None


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
