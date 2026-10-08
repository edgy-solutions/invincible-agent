"""POST /ingest and POST /ingest/events admit a declared delegate's on_behalf_of (R-089).

Ruled 2026-10-08 (Chris): the ingest routes accept `on_behalf_of != caller` for a declared
delegate (DELEGATE_ON_BEHALF_OF) acting for a principal declared for THAT delegate, and still
refuse it for a person. Same helper as the human-task act route (`_admit_on_behalf_of`).
/ingest/events also passes `seeded_by` to the case it opens: the authenticated caller when it is
a declared delegate, else None.

Run: uv run pytest tests/test_ingest_routes_admit_a_declared_delegate.py -v
"""
from __future__ import annotations

import json
import types

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as _ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

DELEGATE = "svc:openddil"
PRINCIPAL = "operator.atlantia@example.com"
OTHER = "operator.borduria@example.com"
PERSON = "alice@example.com"
_MAP = json.dumps({DELEGATE: [PRINCIPAL]})


def _login(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", _MAP)
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


# -- POST /ingest ------------------------------------------------------------------------------

def _drop(client, on_behalf_of):
    return client.post("/ingest", files={"file": ("n.pdf", b"same bytes", "application/pdf")},
                       data={"kind": "pdf", "on_behalf_of": on_behalf_of})


def _stub_dedupe_hit(monkeypatch):
    """A dedupe hit is the cheapest place past the gate: it proves the request got through."""
    seen = {}
    original = {"id": "deadbeef", "sha256": "deadbeef", "object_prefix": "p/", "source": "x",
                "created_at": 1, "status": "received"}
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: original)

    def dup(**kw):
        seen.update(kw)
        return {"id": "new", "status": "duplicate", "duplicate_of": "deadbeef", "detail": "d"}
    monkeypatch.setattr(ist, "record_duplicate_arrival", dup)
    return seen


def test_ingest_person_with_a_mismatch_is_not_a_delegate(client, monkeypatch):
    seen = _stub_dedupe_hit(monkeypatch)
    _login(PERSON)
    r = _drop(client, OTHER)
    assert r.status_code == 403
    assert r.json()["detail"] == {"error": "not_a_delegate"}
    assert seen == {}


def test_ingest_delegate_with_an_undeclared_principal_is_refused(client, monkeypatch):
    seen = _stub_dedupe_hit(monkeypatch)
    _login(DELEGATE)
    r = _drop(client, OTHER)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "principal_not_declared_for_delegate"
    assert seen == {}


def test_ingest_delegate_with_a_declared_principal_passes_the_gate(client, monkeypatch):
    seen = _stub_dedupe_hit(monkeypatch)
    _login(DELEGATE)
    r = _drop(client, PRINCIPAL)
    assert r.status_code == 200, r.text
    # actor is the principal; the delegate is the row's submitted_by (the recorded `via`)
    assert seen["on_behalf_of"] == PRINCIPAL
    assert seen["submitted_by"] == DELEGATE


def test_ingest_person_with_an_equal_on_behalf_of_is_unchanged(client, monkeypatch):
    seen = _stub_dedupe_hit(monkeypatch)
    _login(PERSON)
    assert _drop(client, PERSON).status_code == 200
    assert seen["on_behalf_of"] == PERSON and seen["submitted_by"] == PERSON


# -- POST /ingest/events -----------------------------------------------------------------------

_PAYLOAD = {
    "kind": "maintenance_fault", "event_id": "evt-001", "asset_id": "ASSET-1",
    "owning_tier": "tier-1", "fault": {"item": "pump", "fault_code": "F-01"},
    "picture": {
        "battle_condition": {"mission_essential": False,
                             "basis": {"rule": "R1", "observed_at": "2026-10-03T00:00:00Z"}},
        "spares": [], "nearest_spare": None,
    },
    "label": {"originator_nation": "US"},
}


@pytest.fixture
def events(client, monkeypatch):
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(
        _ck, "by_kind",
        lambda kind: types.SimpleNamespace(
            kind=kind, branch="event", domain="maintenance-bridge",
            seeds_workflow="maintenance_fault", identity_field="event_id")
        if kind == "maintenance-fault-event" else None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: {"id": kw["ingest_id"], "status": "received"})
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: None)
    calls: list[dict] = []

    class _Resp:
        status_code = 200
        content = b""

        def raise_for_status(self):
            pass

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k):
            calls.append({"url": url, "json": json})
            return _Resp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)

    def post(on_behalf_of):
        return client.post("/ingest/events", json={
            "content_kind": "maintenance-fault-event", "on_behalf_of": on_behalf_of,
            "payload": _PAYLOAD})
    return post, calls


def test_events_person_with_a_mismatch_is_not_a_delegate(events):
    post, calls = events
    _login(PERSON)
    r = post(OTHER)
    assert r.status_code == 403 and r.json()["detail"] == {"error": "not_a_delegate"}
    assert calls == []


def test_events_delegate_with_an_undeclared_principal_is_refused(events):
    post, calls = events
    _login(DELEGATE)
    r = post(OTHER)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "principal_not_declared_for_delegate"
    assert calls == []


def test_events_delegate_with_a_declared_principal_opens_a_case_seeded_by_it(events):
    post, calls = events
    _login(DELEGATE)
    r = post(PRINCIPAL)
    assert r.status_code == 200, r.text
    sent = [c for c in calls if c["url"].endswith("/run/send")]
    assert len(sent) == 1, calls
    assert sent[0]["json"]["seeded_by"] == DELEGATE
    # the dropper of record is the principal; the delegate rides as `via`
    assert sent[0]["json"]["facts"]["dropped_by"] == {"authz_id": PRINCIPAL, "via": DELEGATE}


def test_events_person_with_an_equal_on_behalf_of_seeds_nothing(events):
    post, calls = events
    _login(PERSON)
    r = post(PERSON)
    assert r.status_code == 200, r.text
    sent = [c for c in calls if c["url"].endswith("/run/send")]
    assert len(sent) == 1
    assert sent[0]["json"]["seeded_by"] is None
    assert sent[0]["json"]["facts"]["dropped_by"] == {"authz_id": PERSON}


def test_events_a_delegate_acting_for_itself_is_still_seeded_by_itself(events):
    """seeded_by turns on the CALLER being a declared delegate, not on a mismatch."""
    post, calls = events
    _login(DELEGATE)
    assert post(DELEGATE).status_code == 200
    sent = [c for c in calls if c["url"].endswith("/run/send")]
    assert sent[0]["json"]["seeded_by"] == DELEGATE
