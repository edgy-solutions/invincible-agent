"""The door 400 (architect ruling 2026-10-12): POST /ingest refuses a drop that names no
REGISTERED document content kind, before the bounded read, so nothing is written. 7f's report
found a kindless user drop was accepted and later died inside a Dagster op (the ADR-0041 guard).

Order: blank/malformed (422) -> absent (400 content_kind_required) -> unregistered (400
kind_unregistered) -> event-branch (422 event_kind_requires_json). Every refusal asserts the
write doubles (S3 put, dedupe lookup, status row) were never called.
"""
from __future__ import annotations

import types

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests._can_drop_open import can_drop_open  # noqa: F401

pytestmark = pytest.mark.usefixtures("can_drop_open")


def _reg(kind, branch="document", domain="maintenance"):
    return types.SimpleNamespace(kind=kind, branch=branch, domain=domain, seeds_workflow=None,
                                 identity_field=None)


_REGISTRY = (_reg("work-instruction"), _reg("pdf", domain=None), _reg("zeta-note"),
             _reg("maintenance-fault-event", branch="event"))


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
def rig(monkeypatch):
    """A fixed registry, plus doubles for every write the route could make."""
    s3: list[dict] = []
    looked: list = []
    recorded: list = []

    class _S3:
        def put_object(self, **kw):
            s3.append(kw)

    monkeypatch.setattr(ck, "registrations", lambda: _REGISTRY)
    monkeypatch.setattr(ck, "by_kind", lambda k: next((r for r in _REGISTRY if r.kind == k), None) if k else None)
    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _S3())
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: None)
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: looked.append(sha))
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: recorded.append(kw) or {"id": kw["ingest_id"], "status": "received"})
    return types.SimpleNamespace(s3=s3, looked=looked, recorded=recorded)


def _drop(client, **extra):
    return client.post("/ingest", files={"file": ("f.pdf", b"%PDF-1.4 door bytes", "application/pdf")},
                       data={"kind": "pdf", "on_behalf_of": "alice@example.com", **extra})


def _nothing_written(rig):
    assert rig.s3 == [] and rig.looked == [] and rig.recorded == []


def test_absent_content_kind_is_400_content_kind_required_and_writes_nothing(client, rig):
    r = _drop(client)
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert d["error"] == "content_kind_required"
    assert d["registered"] == ["pdf", "work-instruction", "zeta-note"]  # sorted, document branch only
    _nothing_written(rig)


def test_unregistered_content_kind_is_400_kind_unregistered_and_writes_nothing(client, rig):
    r = _drop(client, content_kind="no-such-kind")
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    assert d["error"] == "kind_unregistered"
    assert d["registered"] and "no-such-kind" not in d["registered"]
    _nothing_written(rig)


def test_a_registered_domainless_kind_is_not_refused_by_the_door(client, rig):
    r = _drop(client, content_kind="pdf")
    assert r.status_code == 200, r.text
    assert len(rig.recorded) == 1 and rig.recorded[0]["content_kind"] == "pdf"


def test_an_event_kind_is_still_422_and_writes_nothing(client, rig):
    r = _drop(client, content_kind="maintenance-fault-event")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "event_kind_requires_json"
    _nothing_written(rig)


@pytest.mark.parametrize("bad", ["   ", "a/b"])
def test_blank_or_malformed_keeps_its_422(client, rig, bad):
    r = _drop(client, content_kind=bad)
    assert r.status_code == 422, r.text
    _nothing_written(rig)


def test_the_real_openddil_lab_overlay_registers_xml_and_not_cad(client, rig, monkeypatch):
    """Against the REAL shipped overlay (not the fixed stand-in): `xml` passes the door,
    `cad` is 400 kind_unregistered. Deleting xml.yaml reddens the first half."""
    from pathlib import Path
    overlay = Path(__file__).resolve().parents[1] / "policy" / "overlays" / "openddil-lab" / "content_kinds"
    monkeypatch.undo()  # drop the rig's stand-in registry; rebuild the doubles over the real one
    from src.iagent import human_tasks as _ht
    monkeypatch.setattr(_ht, "capability_object_exists", lambda capability: False)  # undo() dropped can_drop_open
    monkeypatch.setattr(ck, "_REGISTRATIONS_CACHE", None)
    monkeypatch.setenv("CONTENT_KIND_OVERLAY_DIRS", str(overlay))
    s3, recorded = [], []

    class _S3:
        def put_object(self, **kw):
            s3.append(kw)

    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _S3())
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: None)
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: recorded.append(kw) or {"id": kw["ingest_id"], "status": "received"})
    ok = _drop(client, content_kind="xml")
    assert ok.status_code == 200, ok.text
    assert recorded and recorded[0]["content_kind"] == "xml"
    bad = _drop(client, content_kind="cad")
    assert bad.status_code == 400, bad.text
    assert bad.json()["detail"]["error"] == "kind_unregistered"
