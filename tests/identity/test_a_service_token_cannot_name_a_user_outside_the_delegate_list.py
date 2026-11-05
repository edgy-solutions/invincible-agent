"""SEAL 1 -- a service token cannot name a user outside the delegate list.

Architect, overnight: "a service token cannot name a user outside the delegate list".

WHERE a caller can assert a person is DERIVED from the app, never listed: every route whose request
body carries an `on_behalf_of` field (`gateway._body_names_on_behalf_of`, the predicate the MCP door
uses). Each such site needs a driver below; a census fails if a site has none, so a person-asserting
site cannot arrive unsealed.

WHAT is declared is read from where the deploy declares it (`_identity_support`: the chart values,
rendered the way configmap.yaml renders DELEGATE_ON_BEHALF_OF) and put where the SERVER reads it (that
env var, read back through `gateway._delegate_principals()`). No principal is typed in this file.

BEHAVIOUR: each driver records the EFFECT at its site (the actor looked up, the dropper of record, the
case's principal, the artifact owner); the assertion is that a principal outside the caller's declared
list never appears in it. A control shows the declared pair IS admitted at the same site, so a request
that is merely broken cannot pass.

Legs per site: (a) a delegate naming a principal declared for ANOTHER delegate, (b) an undeclared
service identity naming a declared principal, (c) a person naming a declared principal.
"""
from __future__ import annotations

import json
import types

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import answer_artifact_writer as aaw  # noqa: E402
from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests._can_drop_open import can_drop_open  # noqa: E402,F401
from tests.identity._identity_support import install_delegates, pair_and_outsider  # noqa: E402
from tests.test_ingest_routes_admit_a_declared_delegate import _PAYLOAD  # noqa: E402

pytestmark = pytest.mark.usefixtures("can_drop_open")

PERSON = "a.person@example.invalid"


def _login(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id, "email": authz_id,
                          "azp": "client", "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


@pytest.fixture(autouse=True)
def _clean():
    yield
    gateway.app.dependency_overrides.clear()


def _client():
    return TestClient(gateway.app, raise_server_exceptions=False)


class _Fx:
    """Everything a driver saw land, stringified: a principal got in iff it appears here."""

    def __init__(self):
        self.seen: list[str] = []

    def note(self, *a, **k):
        self.seen.append(json.dumps([a, k], default=str))

    def has(self, who: str) -> bool:
        return any(who in s for s in self.seen)


def _drive_act(monkeypatch, who, named):
    fx = _Fx()
    monkeypatch.setattr(ht, "list_tasks_for", lambda actor, **k: (fx.note(actor), [])[1])
    monkeypatch.setattr(ht, "get_task_resolution", lambda *a, **k: None)
    _login(who)
    r = _client().post("/human_tasks/t-1/act", json={"decision": "approved", "on_behalf_of": named})
    return r, fx


def _drive_ingest(monkeypatch, who, named):
    fx = _Fx()
    real = ck.by_kind
    monkeypatch.setattr(ck, "by_kind", lambda kind: types.SimpleNamespace(
        kind=kind, branch="document", domain=None, seeds_workflow=None, identity_field=None)
        if kind == "notice" else real(kind))
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: {
        "id": "o", "sha256": "o", "object_prefix": "p/", "source": "x", "created_at": 1,
        "status": "received"})

    def dup(**kw):
        fx.note(**kw)
        return {"id": "n", "status": "duplicate", "duplicate_of": "o", "detail": "d"}
    monkeypatch.setattr(ist, "record_duplicate_arrival", dup)
    _login(who)
    r = _client().post("/ingest", files={"file": ("n.pdf", b"%PDF-1.4 same bytes", "application/pdf")},
                       data={"kind": "pdf", "on_behalf_of": named, "content_kind": "notice"})
    return r, fx


def _drive_events(monkeypatch, who, named):
    fx = _Fx()
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(ck, "by_kind", lambda kind: types.SimpleNamespace(
        kind=kind, branch="event", domain="maintenance-bridge",
        seeds_workflow="maintenance_fault", identity_field="event_id")
        if kind == "maintenance-fault-event" else None)
    monkeypatch.setattr(ist, "record_received", lambda **kw: (fx.note(**kw), {"id": kw["ingest_id"],
                                                                              "status": "received"})[1])
    monkeypatch.setattr(ist, "update_status", lambda *a, **kw: None)

    class _Resp:
        status_code = 200
        content = b""

        def raise_for_status(self):
            pass

    class _C:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, **k):
            fx.note(url, json)
            return _Resp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _C)
    _login(who)
    r = _client().post("/ingest/events", json={
        "content_kind": "maintenance-fault-event", "on_behalf_of": named, "payload": _PAYLOAD})
    return r, fx


def _drive_action_record(monkeypatch, who, named):
    fx = _Fx()

    class _Sess:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, *a, **k): return types.SimpleNamespace(single=lambda: {"n": 0})

    monkeypatch.setattr(gateway, "neo4j_driver", types.SimpleNamespace(session=lambda: _Sess()))

    class _W:
        def __init__(self, *a, **k): ...

        def write_sync(self, bundle):
            fx.note(repr(bundle))
            return types.SimpleNamespace(success=True, error=None)

    monkeypatch.setattr(aaw, "AnswerArtifactWriter", _W)
    _login(who)
    r = _client().post("/internal/cases/c-1/action-record", json={
        "record": {"action_id": "a-1", "provenance": {"case_id": "c-1"}}, "on_behalf_of": named})
    return r, fx


def _other_than_runner(served):
    return next(d for d in sorted(served) if d != gateway._CASE_RUNNER_SERVICE_AUTHZ_ID)


# site -> (driver, the delegate that is this site's legitimate caller, given the served map)
DRIVERS = {
    ("POST", "/human_tasks/{task_id}/act"): (_drive_act, _other_than_runner),
    ("POST", "/ingest"): (_drive_ingest, _other_than_runner),
    ("POST", "/ingest/events"): (_drive_events, _other_than_runner),
    ("POST", "/internal/cases/{case_id}/action-record"): (
        _drive_action_record, lambda s: gateway._CASE_RUNNER_SERVICE_AUTHZ_ID),
}


def _sites():
    return sorted({(m, r.path) for r in gateway.app.routes if hasattr(r, "dependant")
                   and gateway._body_names_on_behalf_of(r) for m in r.methods})


def test_every_site_that_takes_an_on_behalf_of_has_a_driver():
    """CENSUS, derived from the app: a person-asserting site with no driver is red until driven."""
    assert set(_sites()) == set(DRIVERS), {
        "undriven": sorted(set(_sites()) - set(DRIVERS)), "stale": sorted(set(DRIVERS) - set(_sites()))}


def _served(monkeypatch):
    served = install_delegates(monkeypatch)
    assert gateway._CASE_RUNNER_SERVICE_AUTHZ_ID in served, "the case runner is not a declared delegate"
    return served


@pytest.mark.parametrize("site", sorted(DRIVERS))
def test_control_the_declared_pair_is_admitted_at_the_site(monkeypatch, site):
    served = _served(monkeypatch)
    drive, caller_of = DRIVERS[site]
    d = caller_of(served)
    declared, _ = pair_and_outsider(served, d)
    r, fx = drive(monkeypatch, d, declared)
    assert r.status_code < 500 and fx.has(declared), (site, d, r.status_code, r.text[:200], fx.seen)


_ACTION_RECORD = ("POST", "/internal/cases/{case_id}/action-record")


@pytest.mark.parametrize("site", sorted(DRIVERS))
def test_a_delegate_cannot_name_a_principal_declared_only_for_another_delegate(monkeypatch, site):
    served = _served(monkeypatch)
    drive, _ = DRIVERS[site]
    bad = []
    for d in sorted(served):
        _, outsider = pair_and_outsider(served, d)
        r, fx = drive(monkeypatch, d, outsider)
        if fx.has(outsider):
            bad.append((d, outsider, r.status_code))
    assert not bad, f"{site}: a delegate got a principal outside its list recorded: {bad}"


@pytest.mark.parametrize("site", sorted(DRIVERS))
def test_an_undeclared_service_identity_cannot_name_a_declared_principal(monkeypatch, site):
    served = _served(monkeypatch)
    drive, caller_of = DRIVERS[site]
    undeclared = caller_of(served) + "-undeclared"
    assert undeclared not in served
    declared, _ = pair_and_outsider(served, caller_of(served))
    r, fx = drive(monkeypatch, undeclared, declared)
    assert not fx.has(declared), (site, undeclared, r.status_code, fx.seen)


@pytest.mark.parametrize("site", sorted(DRIVERS))
def test_a_person_cannot_name_a_declared_principal(monkeypatch, site):
    served = _served(monkeypatch)
    drive, caller_of = DRIVERS[site]
    declared, _ = pair_and_outsider(served, caller_of(served))
    r, fx = drive(monkeypatch, PERSON, declared)
    assert not fx.has(declared), (site, r.status_code, fx.seen)
