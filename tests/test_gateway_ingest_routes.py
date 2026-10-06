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
def doc_tools_client():
    """doc-tools' OWN transport identity (`svc:doc-tools`) -- the only caller
    POST /ingest/{ingest_id}/stage accepts."""
    user = type("U", (), {"authz_id": "svc:doc-tools", "id": "svc:doc-tools",
                          "sub": "svc:doc-tools", "email": None,
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
        lambda ingest_id, *, caller_id: {"id": ingest_id, "status": "review",
                                        "kind": "pdf", "sha256": "deadbeef",
                                        "created_at": 1, "updated_at": 2})
    r = client.get("/ingest/deadbeef/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ingest_id"] == "deadbeef"
    assert body["stage"] == "review"
    assert body["duplicate"] is None
    assert "id" not in body and "status" not in body, "one name per field: id/status are dropped"


def test_status_route_passes_through_the_rows_origin_suggestion(client, monkeypatch):
    sugg = {"kind": "origin_suggestion", "suggestion_id": "origin:deadbeef:sor-test"}
    monkeypatch.setattr(
        ist, "get_status_for",
        lambda ingest_id, *, caller_id: {"id": ingest_id, "status": "review",
                                        "kind": "pdf", "sha256": "deadbeef",
                                        "created_at": 1, "updated_at": 2,
                                        "origin_suggestion": sugg})
    r = client.get("/ingest/deadbeef/status")
    assert r.status_code == 200
    assert r.json()["origin_suggestion"] == sugg


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


# ─────────────────────────────────────────────────────────────────────────────
# Ingest/origin seam (SDK 0.9.7, lane/01-seam) — sections 1-3: a declared AND registered
# content kind fills manifest["domain_type"]; dropped_by.authz_id is recorded (never sub);
# an event-branch kind seeds its workflow on arrival.
# ─────────────────────────────────────────────────────────────────────────────

from urllib.parse import quote  # noqa: E402

from src.iagent import content_kinds as _ck  # noqa: E402


def _fake_registration(**kw):
    """A lightweight stand-in for iagent_mesh.ingest.ContentKindRegistration: the gateway
    route only ever reads .branch/.domain/.seeds_workflow/.identity_field off whatever
    content_kinds.by_kind returns, so a real SDK model is not needed to exercise it.

    content_kinds is imported LOCALLY inside gateway.ingest_document (`from . import
    content_kinds, ...`), not at module level -- so these tests patch the attribute on the
    shared module object (`_ck.by_kind`) rather than `gateway.content_kinds`, which does not
    exist as a module-level name."""
    import types
    base = {"kind": "x", "branch": "document", "domain": None,
            "seeds_workflow": None, "identity_field": None}
    base.update(kw)
    return types.SimpleNamespace(**base)


#: A payload satisfying EVERY dotted path `policy/overlays/openddil-lab/triggers/
#: maintenance_fault.yaml`'s `requires:` names, read from that real file (not restated here) --
#: the tests below read the requires list itself via `case_routing.load_trigger`, this constant
#: only supplies values at the paths that file is known (as of this writing) to name.
_VALID_EVENT_PAYLOAD = {
    "kind": "maintenance_fault",
    "event_id": "evt-001",
    "asset_id": "ASSET-1",
    "owning_tier": "tier-1",
    "fault": {"item": "pump", "fault_code": "F-01"},
    "picture": {
        "battle_condition": {
            "mission_essential": False,
            "basis": {"rule": "R1", "observed_at": "2026-10-03T00:00:00Z"},
        },
        # the trigger's `carries`: present, and a null is an answer
        "spares": [],
        "nearest_spare": None,
    },
    "label": {"originator_nation": "US"},
}


@pytest.fixture
def stub_restate_post(monkeypatch):
    """Captures every POST the gateway makes through httpx.AsyncClient (the Restate ingress
    call `_open_case` / `_open_safety_acceptance` share) and answers 200 by default -- set
    `state["fail"] = True` to make raise_for_status raise instead, for the best-effort-on-
    error arm. Returns (calls, state)."""
    calls: list[dict] = []
    state = {"fail": False}

    class _Resp:
        def __init__(self):
            self.status_code = 200
        def raise_for_status(self):
            if state["fail"]:
                raise RuntimeError("boom: restate unreachable (stubbed)")

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k):
            calls.append({"url": url, "json": json})
            return _Resp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    return calls, state


def test_ingest_declared_and_registered_kind_fills_domain_type(
        client, fake_s3, fake_create_node, monkeypatch):
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="document",
                                        domain="maintenance-bridge",
                                        passes=("p",), outputs=("o",))
        if kind == "work-instruction" else None,
    )
    r = client.post("/ingest", files={"file": ("wi.pdf", b"registered kind bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                          "content_kind": "work-instruction"})
    assert r.status_code == 200, r.text
    manifest_call = next(c for c in fake_s3 if c["Key"].endswith("manifest.json"))
    import json as _json
    manifest = _json.loads(manifest_call["Body"])
    # MUTANT (section 1): leaving domain_type None here is the exact fragment this reds --
    # "manifest['domain_type'] == 'maintenance-bridge'".
    assert manifest["domain_type"] == "maintenance-bridge"


def test_ingest_declared_but_unregistered_kind_leaves_domain_type_none(
        client, fake_s3, fake_create_node, monkeypatch):
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    monkeypatch.setattr(_ck, "by_kind", lambda kind: None)
    r = client.post("/ingest", files={"file": ("wi.pdf", b"unregistered kind bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                          "content_kind": "work-instruction"})
    assert r.status_code == 200, r.text
    manifest_call = next(c for c in fake_s3 if c["Key"].endswith("manifest.json"))
    import json as _json
    manifest = _json.loads(manifest_call["Body"])
    assert manifest["domain_type"] is None


def test_ingest_records_dropped_by_authz_id_not_sub(client, fake_s3, fake_create_node, monkeypatch):
    """Ruling 1: authz_id is recorded, the JWT sub is not -- a User whose sub != authz_id
    proves the two are not conflated anywhere on this path."""
    user = type("U", (), {"authz_id": "alice-authz-id", "id": "alice-sub",
                          "sub": "alice-sub", "email": "alice@example.com",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    r = client.post("/ingest", files={"file": ("f.pdf", b"sub vs authz_id bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice-authz-id"})
    assert r.status_code == 200, r.text
    manifest_call = next(c for c in fake_s3 if c["Key"].endswith("manifest.json"))
    import json as _json
    manifest = _json.loads(manifest_call["Body"])
    # MUTANT (section 2): recording sub here is the exact fragment this reds --
    # "manifest['dropped_by'] == {'authz_id': 'alice-authz-id'}".
    assert manifest["dropped_by"] == {"authz_id": "alice-authz-id"}
    assert manifest["dropped_by"]["authz_id"] != "alice-sub"
    call = fake_create_node[0]
    assert call["dropped_by_authz_id"] == "alice-authz-id"


def test_ingest_refuses_an_event_kind_multipart_drop_with_zero_writes(
        client, fake_s3, fake_create_node, monkeypatch, stub_restate_post):
    """Section C (ingest/origin seam): an event-branch kind never arrives as a file -- it is a
    JSON IngestRequest at POST /ingest/events. The multipart door refuses it before the bounded
    read, so NOTHING is written: no S3 object, no status row, no graph node, no workflow start.
    """
    calls, _state = stub_restate_post
    called = {"find": False, "received": False}
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: called.__setitem__("find", True))
    # Returns a well-shaped row despite setting "received" -- so that a mutant which deletes the
    # door check (and so reaches this call for real) fails on the assertions below with a clean
    # 200 vs 422 mismatch, rather than on an unrelated KeyError/TypeError from a half-shaped fake.
    monkeypatch.setattr(
        ist, "record_received",
        lambda **kw: called.__setitem__("received", True) or {"id": kw["ingest_id"], "status": "received"},
    )
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="event",
                                        domain="maintenance-bridge",
                                        seeds_workflow="maintenance_fault",
                                        identity_field="event_id")
        if kind == "maintenance-fault-event" else None,
    )
    r = client.post("/ingest", files={"file": ("e.json", b"event kind bytes", "application/json")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                          "content_kind": "maintenance-fault-event"})
    # MUTANT (section C, "accept the file"): dropping this door check lets the multipart event
    # reach the bounded read / S3 write / workflow seeding below, which reds the exact fragment
    # -- "r.status_code == 422" (it would be 200) -- and every zero-write assertion below with it.
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "event_kind_requires_json", r.json()
    assert called["find"] is False, "an event kind reached the dedupe/DB layer"
    assert called["received"] is False, "an event kind reached record_received"
    assert fake_s3 == [], "an event kind reached the object store"
    assert fake_create_node == [], "an event kind reached the graph node write"
    assert calls == [], "an event kind reached the workflow-seeding POST"


def test_ingest_document_kind_starts_no_workflow(
        client, fake_s3, fake_create_node, monkeypatch, stub_restate_post):
    calls, _state = stub_restate_post
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    monkeypatch.setattr(
        _ck, "by_kind",
        # seeds_workflow is set here (unusually, for a document-branch kind) so this test
        # actually exercises the branch == "event" guard rather than vacuously passing because
        # seeds_workflow is None -- see the section-3 mutant in the report ("start on a
        # document kind"), which removed exactly that guard.
        lambda kind: _fake_registration(kind=kind, branch="document",
                                        domain="maintenance-bridge",
                                        seeds_workflow="should_never_fire",
                                        passes=("p",), outputs=("o",))
        if kind == "maintenance-action-record" else None,
    )
    r = client.post("/ingest", files={"file": ("d.pdf", b"document kind bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com",
                          "content_kind": "maintenance-action-record"})
    assert r.status_code == 200, r.text
    assert len(calls) == 0, calls
    assert r.json()["workflow"] is None


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest/events -- the JSON door for an event-branch content kind (section C). The
# trigger's own `requires:` (read from the REAL file via `case_routing.load_trigger`, no env
# override -- same discipline as tests/test_the_maintenance_fault_runs_as_a_case.py) is the
# validatable schema; a payload failing it is refused before any case is opened.
# ─────────────────────────────────────────────────────────────────────────────

def test_ingest_events_seeds_with_the_triggers_requires_satisfied(
        client, monkeypatch, stub_restate_post):
    calls, _state = stub_restate_post
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="event",
                                        domain="maintenance-bridge",
                                        seeds_workflow="maintenance_fault",
                                        identity_field="event_id")
        if kind == "maintenance-fault-event" else None,
    )
    r = client.post("/ingest/events", json={
        "content_kind": "maintenance-fault-event",
        "on_behalf_of": "alice@example.com",
        "payload": _VALID_EVENT_PAYLOAD,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(calls) == 1, calls
    sent = calls[0]
    assert sent["json"]["trigger"] == "maintenance_fault"
    assert sent["json"]["facts"]["asset_id"] == "ASSET-1"
    assert sent["json"]["facts"]["domain_type"] == "maintenance-bridge"
    assert sent["json"]["facts"]["dropped_by"] == {"authz_id": "alice@example.com"}
    assert body["workflow"]["started"] is True


def test_ingest_events_the_case_key_is_one_the_runner_accepts(
        client, monkeypatch, stub_restate_post):
    """THE JOIN: what the door POSTs (key in the URL, trigger and facts in the body) goes
    through the runner's REAL intake check. Each half had its own tests and the pair still
    disagreed -- the door keyed `{seeds_workflow}:{ingest_id}`, the runner demands the event's
    own `event_id` -- and OpenDDIL's first live event was refused at intake."""
    from urllib.parse import unquote
    from agent_fleet.restate_analyst import case_routing as cr
    calls, _state = stub_restate_post
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="event",
                                        domain="maintenance-bridge",
                                        seeds_workflow="maintenance_fault",
                                        identity_field="event_id")
        if kind == "maintenance-fault-event" else None,
    )
    r = client.post("/ingest/events", json={
        "content_kind": "maintenance-fault-event",
        "on_behalf_of": "alice@example.com",
        "payload": _VALID_EVENT_PAYLOAD,
    })
    # THE CONTRACT (ruled 2026-10-05): 200 with workflow.case_id, never the spec's 202.
    assert r.status_code == 200, r.text
    assert len(calls) == 1, calls
    url, sent = calls[0]["url"], calls[0]["json"]
    head, sep, tail = url.partition("/WorkflowRunner/")
    assert sep and tail.endswith("/run/send"), url
    key = unquote(tail[: -len("/run/send")])
    assert key == r.json()["workflow"]["case_id"], (key, r.json())
    trig = cr.load_trigger(sent["trigger"])
    # MUTANT (the 2026-10-05 key): `case_id = f"{seeds_workflow}:{ingest_id}"` reds here with
    # the runner's own message, "case key ... is not the event's event_id".
    cr.check_intake(trig, cr.flatten(sent["facts"]), key, facts=sent["facts"])


def test_ingest_events_a_payload_the_runner_would_refuse_is_refused_at_the_door(
        client, monkeypatch, stub_restate_post):
    """`requires` is not all intake checks: a payload with every required fact and without a
    `carries` key was answered 200 here and refused by the runner, where the producer cannot
    see it. The door now runs the runner's own check_intake first."""
    import copy
    calls, _state = stub_restate_post
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="event",
                                        domain="maintenance-bridge",
                                        seeds_workflow="maintenance_fault",
                                        identity_field="event_id")
        if kind == "maintenance-fault-event" else None,
    )
    bad_payload = copy.deepcopy(_VALID_EVENT_PAYLOAD)
    del bad_payload["picture"]["spares"]
    r = client.post("/ingest/events", json={
        "content_kind": "maintenance-fault-event",
        "on_behalf_of": "alice@example.com",
        "payload": bad_payload,
    })
    # MUTANT (drop the door's check_intake): 200 and one call -- reds both fragments below.
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "payload_refused_by_trigger", r.json()
    assert "picture.spares" in r.json()["detail"]["message"], r.json()
    assert calls == [], "a payload the runner refuses reached the workflow-seeding POST"


def test_ingest_events_identity_field_and_trigger_key_must_agree(
        client, monkeypatch, stub_restate_post):
    """Two declarations, two dedupes: the door's (`identity_field`) and the runner's (the
    trigger's `key`). A kind whose two disagree is refused before any case opens."""
    calls, _state = stub_restate_post
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="event",
                                        domain="maintenance-bridge",
                                        seeds_workflow="maintenance_fault",
                                        identity_field="asset_id")
        if kind == "maintenance-fault-event" else None,
    )
    r = client.post("/ingest/events", json={
        "content_kind": "maintenance-fault-event",
        "on_behalf_of": "alice@example.com",
        "payload": _VALID_EVENT_PAYLOAD,
    })
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "trigger_unconfigured", r.json()
    assert calls == [], "a kind whose dedupes disagree reached the workflow-seeding POST"


def test_ingest_events_a_payload_failing_the_trigger_schema_is_refused(
        client, monkeypatch, stub_restate_post):
    import copy
    calls, _state = stub_restate_post
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="event",
                                        domain="maintenance-bridge",
                                        seeds_workflow="maintenance_fault",
                                        identity_field="event_id")
        if kind == "maintenance-fault-event" else None,
    )
    bad_payload = copy.deepcopy(_VALID_EVENT_PAYLOAD)
    del bad_payload["fault"]["fault_code"]
    r = client.post("/ingest/events", json={
        "content_kind": "maintenance-fault-event",
        "on_behalf_of": "alice@example.com",
        "payload": bad_payload,
    })
    # MUTANT (section C, "skip the schema check"): dropping the `missing` check before opening
    # the case reds this exact fragment -- "r.status_code == 422" and "'fault.fault_code' in
    # r.json()['detail']['missing']" -- the case would open on an incomplete event instead.
    assert r.status_code == 422, r.text
    assert "fault.fault_code" in r.json()["detail"]["missing"], r.json()
    assert calls == [], "a schema-failing payload reached the workflow-seeding POST"


def test_ingest_events_restate_error_still_returns_200_with_started_false(
        client, monkeypatch, stub_restate_post):
    """Moved from the multipart door (now refused there, see the test above) to POST
    /ingest/events: `_open_case` is the same best-effort helper either way, so a Restate
    outage is logged and swallowed, not raised."""
    calls, state = stub_restate_post
    state["fail"] = True
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: _fake_registration(kind=kind, branch="event",
                                        domain="maintenance-bridge",
                                        seeds_workflow="maintenance_fault",
                                        identity_field="event_id")
        if kind == "maintenance-fault-event" else None,
    )
    r = client.post("/ingest/events", json={
        "content_kind": "maintenance-fault-event",
        "on_behalf_of": "alice@example.com",
        "payload": _VALID_EVENT_PAYLOAD,
    })
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    assert r.json()["workflow"]["started"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Ingest/origin seam, section 6 (architect ruling 2026-10-02 "ORIGIN, not audience"): the
# gateway wiring around `origin_resolver.resolve()` -- a hit records the suggestion on the
# status row and opens its own case; a miss does neither.
# ─────────────────────────────────────────────────────────────────────────────

from src.iagent import origin_resolver as _orr  # noqa: E402

_SUGGESTION = {
    "kind": "origin_suggestion", "suggestion_id": "origin:ART-X:sor-test",
    "artifact_id": "ART-X", "dropped_by": {"authz_id": "alice@example.com"},
    "suggested": {"owner_domain": "sandbox-domain", "program": "sandbox-program",
                  "obtained_via": "authoritative_source"},
    "evidence": {"source": "sor-test", "citation": "sandbox-fake:SANDBOX-FAKE-0001"},
}


def test_ingest_origin_suggestion_hit_records_and_opens_its_own_case(
        client, fake_s3, fake_create_node, monkeypatch, stub_restate_post):
    calls, _state = stub_restate_post
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    recorded: list = []
    monkeypatch.setattr(ist, "record_origin_suggestion",
                        lambda ingest_id, suggestion: recorded.append((ingest_id, suggestion)))
    monkeypatch.setattr(_orr, "resolve", lambda artifact: dict(_SUGGESTION))
    r = client.post("/ingest", files={"file": ("f.pdf", b"origin hit bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    # MUTANT (section 6): dropping the record_origin_suggestion call, or opening no case, reds
    # these two exact fragments -- "len(recorded) == 1" and "len(calls) == 1".
    assert len(recorded) == 1, recorded
    assert recorded[0][1] == _SUGGESTION, recorded
    assert len(calls) == 1, calls
    assert calls[0]["json"] == {"trigger": "origin_suggestion", "facts": _SUGGESTION}
    assert body["origin_suggestion"] == _SUGGESTION, body


def test_ingest_origin_suggestion_miss_records_and_opens_nothing(
        client, fake_s3, fake_create_node, monkeypatch, stub_restate_post):
    calls, _state = stub_restate_post
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    recorded: list = []
    monkeypatch.setattr(ist, "record_origin_suggestion",
                        lambda ingest_id, suggestion: recorded.append((ingest_id, suggestion)))
    monkeypatch.setattr(_orr, "resolve", lambda artifact: None)
    r = client.post("/ingest", files={"file": ("f.pdf", b"origin miss bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 200, r.text
    assert recorded == [], recorded
    assert calls == [], calls
    assert r.json()["origin_suggestion"] is None


def test_ingest_origin_resolver_failure_still_returns_200(
        client, fake_s3, fake_create_node, monkeypatch, stub_restate_post):
    """FAIL-CLOSED `origin_resolver.systems()` must not fail an otherwise-durable upload --
    same best-effort discipline as `_create_ingest_node` and the workflow-seeding POST."""
    calls, _state = stub_restate_post
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})

    def _boom(artifact):
        raise RuntimeError("systems-of-record load failed (stubbed)")
    monkeypatch.setattr(_orr, "resolve", _boom)
    r = client.post("/ingest", files={"file": ("f.pdf", b"origin resolver boom bytes", "application/pdf")},
                    data={"kind": "pdf", "on_behalf_of": "alice@example.com"})
    assert r.status_code == 200, r.text
    assert calls == []
    assert r.json()["origin_suggestion"] is None


# ─────────────────────────────────────────────────────────────────────────────
# POST /ingest/{ingest_id}/stage -- doc-tools' own write into the stage ladder
# ─────────────────────────────────────────────────────────────────────────────

def _stub_domain(monkeypatch, domain="SUSTAINMENT"):
    reg = type("Reg", (), {"domain": domain})()
    monkeypatch.setattr(ck, "by_kind", lambda kind: reg)


def test_stage_route_moves_the_row(doc_tools_client, monkeypatch):
    row = {"id": "sha256:" + "a" * 64, "status": "received", "kind": "pdf",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: row)
    calls = []
    monkeypatch.setattr(ist, "update_status",
                        lambda ingest_id, stage, **kw: calls.append((ingest_id, stage, kw)))
    _stub_domain(monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: False)
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: {"task_id": kw["task_id"], "recipients": ["x"]})
    r = doc_tools_client.post(f"/ingest/{row['id']}/stage", json={"stage": "extracting"})
    assert r.status_code == 200, r.text
    assert r.json() == {"ingest_id": row["id"], "stage": "extracting",
                        "task_id": None, "task_status": None}
    assert calls == [(row["id"], "extracting",
                      {"extracted_count": None, "extracted_total": None, "detail": None})]


def test_stage_review_opens_exactly_one_task(doc_tools_client, monkeypatch):
    row = {"id": "sha256:" + "b" * 64, "status": "extracting", "kind": "pdf",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: row)
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: None)
    _stub_domain(monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: False)
    registered = []
    monkeypatch.setattr(ht, "register_task",
                        lambda **kw: registered.append(kw) or {"task_id": kw["task_id"], "recipients": []})
    r = doc_tools_client.post(f"/ingest/{row['id']}/stage", json={"stage": "review"})
    assert r.status_code == 200, r.text
    assert len(registered) == 1, registered
    reg = registered[0]
    assert reg["kind"] == promotion.KIND
    assert reg["task_id"] == f"{promotion.KIND}:{row['id']}"
    assert reg["audience"] == f"{promotion.KIND}:SUSTAINMENT"
    assert reg["payload"]["ingest_id"] == row["id"]
    assert reg["payload"]["domain"] == "SUSTAINMENT"
    assert reg["payload"]["dropped_by"] == {"authz_id": "alice@example.com"}
    assert r.json()["task_id"] == f"{promotion.KIND}:{row['id']}"
    assert r.json()["task_status"] == "FILED"


def test_stage_repeat_review_opens_none(doc_tools_client, monkeypatch):
    row = {"id": "sha256:" + "c" * 64, "status": "extracting", "kind": "pdf",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: row)
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: None)
    _stub_domain(monkeypatch)
    monkeypatch.setattr(ht, "task_exists", lambda task_id: True)
    registered = []
    monkeypatch.setattr(ht, "register_task", lambda **kw: registered.append(kw))
    r = doc_tools_client.post(f"/ingest/{row['id']}/stage", json={"stage": "review"})
    assert r.status_code == 200, r.text
    assert registered == []
    assert r.json()["task_status"] == "ALREADY_FILED"


def test_stage_non_doc_tools_caller_gets_403(client, monkeypatch):
    row = {"id": "sha256:" + "d" * 64, "status": "received", "kind": "pdf",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: row)
    calls = []
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: calls.append((a, kw)))
    r = client.post(f"/ingest/{row['id']}/stage", json={"stage": "extracting"})
    assert r.status_code == 403, r.text
    assert calls == [], "a non-doc-tools caller must write nothing"


def test_stage_backwards_move_gets_409(doc_tools_client, monkeypatch):
    row = {"id": "sha256:" + "e" * 64, "status": "review", "kind": "pdf",
          "submitted_by": "alice@example.com"}
    monkeypatch.setattr(ist, "get_row", lambda ingest_id: row)
    calls = []
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: calls.append((a, kw)))
    r = doc_tools_client.post(f"/ingest/{row['id']}/stage", json={"stage": "extracting"})
    assert r.status_code == 409, r.text
    assert calls == [], "a backwards move must write nothing"
