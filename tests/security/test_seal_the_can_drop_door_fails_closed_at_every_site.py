"""SEAL (Lane saf's review of PR #153): the can_drop door fails CLOSED at every site that sets a kind.

The order: "Topaz error -> 503, not open." The door is `gateway._can_drop_or_refuse`; a kind is gated
iff `capability:can_drop:<kind>` exists (404 = open BY DESIGN, the only open answer), so the two ways
a Topaz fault could read as "open" are (1) the object read failing and (2) the invoke check failing
after the object exists. Each must be 503, with the right body, at every one of the four sites
(POST /ingest, POST /ingest/events, POST /ingest/{id}/title_leaf, POST /ingest/{id}/leaf), and an
UNCONFIGURED directory must be told apart from an UNAVAILABLE one (the unconfigured arm had no test:
mutating its mapping to the unavailable body survived the whole suite).

Each arm has its own positive control: the same site with an ungated kind gets past the gate, so a
503 cannot be a blanket the site always throws.

Companion to test_a_restricted_kind_is_dropped_only_by_its_grantees.py (which holds the 403 side and
the unavailable arm at three sites); this file does not repeat it.
"""
from __future__ import annotations

import types

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

DROPPER = "alice@example.com"
ID = "sha256:" + "b" * 64


def _reg(kind, branch="document", domain="maintenance", seeds=None):
    return types.SimpleNamespace(kind=kind, branch=branch, domain=domain, seeds_workflow=seeds,
                                 identity_field="event_id" if branch == "event" else None,
                                 passes=("p",))


_REGISTRY = (_reg("pdf", domain=None), _reg("pcn"),
             _reg("fault-event", branch="event", seeds="no-such-trigger"))


@pytest.fixture
def rig(monkeypatch):
    """Registry, write doubles, row doubles. Nothing real is touched; `w.effects` collects every
    write a site could make."""
    w = types.SimpleNamespace(effects=[], row=None)
    monkeypatch.setattr(ck, "registrations", lambda: _REGISTRY)
    monkeypatch.setattr(ck, "by_kind",
                        lambda k: next((r for r in _REGISTRY if r.kind == k), None) if k else None)

    class _S3:
        def put_object(self, **kw):
            w.effects.append(("s3", kw.get("Key")))

    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _S3())
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: None)
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: w.effects.append(("record", kw.get("ingest_id")))
                        or {"id": kw["ingest_id"], "status": "received"})
    monkeypatch.setattr(ist, "get_row", lambda i: dict(w.row) if w.row else None)
    monkeypatch.setattr(ist, "get_status_unscoped", lambda i: dict(w.row) if w.row else None)
    monkeypatch.setattr(ist, "set_leaf",
                        lambda *a, **k: w.effects.append(("set_leaf", a)) or dict(w.row))
    monkeypatch.setattr(ist, "hold_for_kind", lambda *a, **k: w.effects.append(("hold", a)) or True)

    async def _access(ingest_id, current_user, route):
        return dict(w.row), "dropped_by"

    async def _body(row, user):
        return {"id": row["id"], "content_kind": row["content_kind"]}

    monkeypatch.setattr(gateway, "_ingest_review_access", _access)
    monkeypatch.setattr(gateway, "_ingest_status_body", _body)
    monkeypatch.setattr(gateway, "_apply_leaf_to_sidecar", lambda row, leaf: True)
    monkeypatch.setattr(gateway, "_DOC_TOOLS_SERVICE_AUTHZ_ID", "svc:doc-tools")
    w.row = {"id": ID, "kind": "pdf", "content_kind": "pdf", "status": "received",
             "on_behalf_of": DROPPER, "submitted_by": "svc:delegate", "leaf_source": None,
             "leaf_set_by": None, "run_id": None}
    yield w
    gateway.app.dependency_overrides.clear()


def _client(who):
    user = types.SimpleNamespace(
        authz_id=who, id=who, sub=who, email=who, persona=None, entitled_domains=[],
        is_authenticated=True, entitlements=types.SimpleNamespace(cells=[], default=None, source="t"))
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    return TestClient(gateway.app, raise_server_exceptions=False)


def _drop():
    return _client(DROPPER).post(
        "/ingest", files={"file": ("f.pdf", b"%PDF-1.4 door bytes", "application/pdf")},
        data={"kind": "pdf", "content_kind": "pcn", "on_behalf_of": DROPPER})


def _event():
    return _client(DROPPER).post("/ingest/events", json={
        "content_kind": "fault-event", "on_behalf_of": DROPPER, "payload": {"event_id": "e1"}})


def _title_leaf():
    return _client("svc:doc-tools").post(
        f"/ingest/{ID}/title_leaf", json={"doc_type": "PCN", "doc_type_source": "title"})


def _leaf():
    return _client(DROPPER).post(f"/ingest/{ID}/leaf", json={"leaf": "pcn"})


SITES = {"drop": _drop, "events": _event, "title_leaf": _title_leaf, "leaf": _leaf}
FAULTS = {
    "unavailable": (ht.AuthorizationUnavailable("down"), "authorization_unavailable"),
    "unconfigured": (ht.AuthorizationUnconfigured("no directory"), "authorization_unconfigured"),
}
GATE_ERRORS = ("not_entitled_to_drop", "authorization_unavailable", "authorization_unconfigured")


def _detail(r):
    return r.json()["detail"]


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("site", sorted(SITES))
def test_s1_an_object_read_fault_is_503_at_every_site_and_writes_nothing(rig, monkeypatch, site, fault):
    exc, error = FAULTS[fault]

    def _boom(cap):
        raise exc

    monkeypatch.setattr(ht, "capability_object_exists", _boom)
    monkeypatch.setattr(ht, "check_can_invoke", lambda cap, who: True)            # even a granted one
    monkeypatch.setattr(ht, "can_invoke_or_unavailable", lambda cap, who: True)
    r = SITES[site]()
    assert r.status_code == 503, f"{site}/{fault}: {r.status_code} {r.text}"
    assert _detail(r)["error"] == error, f"{site}/{fault}: {r.text}"
    assert rig.effects == [], f"{site}/{fault}: a faulted gate must not write: {rig.effects}"


@pytest.mark.parametrize("fault", sorted(FAULTS))
@pytest.mark.parametrize("site", sorted(SITES))
def test_s1_an_invoke_check_fault_after_the_object_exists_is_503_at_every_site(
        rig, monkeypatch, site, fault):
    exc, error = FAULTS[fault]

    def _boom(cap, who):
        raise exc

    monkeypatch.setattr(ht, "capability_object_exists", lambda cap: True)        # gated
    monkeypatch.setattr(ht, "check_can_invoke", _boom)
    monkeypatch.setattr(ht, "can_invoke_or_unavailable", _boom)
    r = SITES[site]()
    assert r.status_code == 503, f"{site}/{fault}: {r.status_code} {r.text}"
    assert _detail(r)["error"] == error, f"{site}/{fault}: {r.text}"
    assert rig.effects == [], f"{site}/{fault}: {rig.effects}"


@pytest.mark.ingest_v1_unconformant(reason="the /leaf success body is a stub dict (rows double)")
@pytest.mark.parametrize("site", sorted(SITES))
def test_s1_control_the_same_site_with_an_ungated_kind_gets_past_the_gate(rig, monkeypatch, site):
    """The positive control: no fault, no object -> open BY DESIGN (the 404 case), so the 503s above
    are the fault's doing and not a blanket the site always throws."""
    monkeypatch.setattr(ht, "capability_object_exists", lambda cap: False)
    monkeypatch.setattr(ht, "check_can_invoke", lambda cap, who: pytest.fail("ungated: no invoke"))
    monkeypatch.setattr(ht, "can_invoke_or_unavailable", lambda cap, who: pytest.fail("ungated"))
    r = SITES[site]()
    err = _detail(r).get("error") if r.status_code >= 400 and isinstance(_detail(r), dict) else None
    assert err not in GATE_ERRORS, f"{site}: {r.status_code} {r.text}"


_REAL_CLIENT = httpx.Client


def _real_exists(monkeypatch, handler):
    real = _REAL_CLIENT
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "http://topaz.test")
    monkeypatch.setattr(ht.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_s1_the_only_open_answer_of_the_real_object_read_is_a_404(monkeypatch):
    """The seam `tests/_can_drop_open.py` stubs (`capability_object_exists`): with the real function,
    404 is False (open), 200 is True (gated), and EVERY other status raises -- never False."""
    _real_exists(monkeypatch, lambda req: httpx.Response(404, json={}))
    assert ht.capability_object_exists("can_drop:pcn") is False
    _real_exists(monkeypatch, lambda req: httpx.Response(200, json={"result": {}}))
    assert ht.capability_object_exists("can_drop:pcn") is True
    for status in (400, 401, 403, 500, 502, 503):
        _real_exists(monkeypatch, lambda req, s=status: httpx.Response(s, json={}))
        with pytest.raises((ht.AuthorizationUnavailable, ht.AuthorizationUnconfigured)):
            ht.capability_object_exists("can_drop:pcn")
