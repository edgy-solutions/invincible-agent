"""A refusal an engine sends is the answer the caller reads: same status, same code, same body.

The relays are DERIVED: every route on the mcp surface whose handler opens an `httpx.AsyncClient`
to an engine. Each is driven through the real route with a REAL `httpx.Response` as the engine's
answer (status, headers, body bytes; so the empty body is the wire's empty body, not a stub's
`.json()`), and the caller's request is built from the route's own signature (path params and
required query params get a placeholder, a body gets `{}`), so nothing here names a route.

The declared refusals are 403 (policy), 409 and 422 (e.g. `needs_slots`). For each, the relay must
answer with that status and carry every key the engine sent. (`relay_refusal` ADDS `grantable_by`
to a policy refusal; that is the BFF completing it, not rewrapping it, so the check is that the
engine's keys survive, not that no key is added.) An engine that answers with NO body must never
become a 500 (an unhandled crash of the relay), and a refusal must never become a 200.

Two STRICT XFAILs name the defects found on master; see their reasons.

Run: uv run pytest tests/mcp_seals/test_a_relayed_refusal_passes_through.py -q
"""
from __future__ import annotations

import functools
import inspect
import json
from unittest import mock

import httpx
import pytest
from fastapi.testclient import TestClient

from _mcp_surface_derived import concrete_path, mcp_routes

from src.iagent import gateway

DECLARED = (403, 409, 422)
ENGINE_BODIES = {
    403: {"detail": {"error": "not_visible",
                     "refusal": {"policy_id": "members",
                                 "missing_binding": "can_view(scope)"},
                     "message": "You may not see what this request names."}},
    409: {"detail": {"error": "conflict", "message": "the state moved; reload.", "upstream": "x"}},
    422: {"detail": {"needs_slots": ["scope"], "question": "Which scope?", "slots": ["scope"]}},
}


class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "alice@example.com"
    email = "alice@example.com"
    azp = "mcp-client"


def _reaches_an_engine(route) -> bool:
    box = {"calls": [], "status": 200, "content": b"{}"}
    with mock.patch.object(gateway.httpx, "AsyncClient", _double(box)):
        saved = dict(gateway.app.dependency_overrides)
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User()
        try:
            _call(route)
        finally:
            gateway.app.dependency_overrides.clear()
            gateway.app.dependency_overrides.update(saved)
    return bool(box["calls"])


def candidates():
    """Routes whose handler opens an engine client."""
    return [r for r in mcp_routes() if "AsyncClient" in inspect.getsource(r.endpoint)]


@functools.cache
def relays():
    """The candidates that, driven from their own signature, actually call the engine. (One that
    answers before the engine call, e.g. a closed-set filename guard, is not a generic relay.)"""
    return [r for r in candidates() if _reaches_an_engine(r)]


def _ids(routes):
    return [f"{sorted(r.methods)[0]} {r.path}" for r in routes]


def _double(box):
    """An `httpx.AsyncClient` stand-in whose every call answers with a REAL `httpx.Response`
    (`box['status']`, `box['content']`) bound to its request."""
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def _answer(self, method, url, **kw):
            req = httpx.Request(method, url, json=kw.get("json"), headers=kw.get("headers"))
            box["calls"].append(req)
            return httpx.Response(box["status"], content=box["content"],
                                  headers={"content-type": "application/json"}, request=req)

        async def get(self, url, **kw):
            return await self._answer("GET", url, **kw)

        async def post(self, url, **kw):
            return await self._answer("POST", url, **kw)

        async def request(self, method, url, **kw):
            return await self._answer(method, url, **kw)

    return _Client


@pytest.fixture
def engine(monkeypatch):
    box: dict = {"calls": []}
    monkeypatch.setattr(gateway.httpx, "AsyncClient", _double(box))
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _User()
    try:
        yield box
    finally:
        gateway.app.dependency_overrides.clear()


def _call(route):
    """The caller's request, built from the route's own signature."""
    q = {p.alias: "x" for p in route.dependant.query_params if p.field_info.is_required()}
    method = sorted(m for m in route.methods if m != "HEAD")[0]
    kw = {"params": q, "headers": {"Authorization": "Bearer tok-abc"}}
    if route.body_field is not None:
        kw["json"] = {}
    return TestClient(gateway.app, raise_server_exceptions=False).request(
        method, concrete_path(route.path), **kw)


def _keys(obj):
    """Every dict key anywhere in `obj`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_the_relays_were_derived_and_each_reaches_the_engine_double(engine):
    assert len(relays()) >= 2, "instrument failure: fewer than two relay routes reached an engine"
    engine.update(status=200, content=b"{}")
    for r in relays():
        engine["calls"].clear()
        _call(r)
        assert engine["calls"], r.path
    assert len(relays()) <= len(candidates())


def _wraps_non_403(route) -> bool:
    """Whether the handler hands an engine failure to `_engine_failure` (which passes only 403)."""
    return "_engine_failure" in inspect.getsource(route.endpoint)


def _passing_cases():
    return [(r, st) for r in relays() for st in DECLARED if st == 403 or not _wraps_non_403(r)]


@pytest.mark.parametrize("route,status", _passing_cases(),
                         ids=[f"{sorted(r.methods)[0]} {r.path} {st}" for r, st in _passing_cases()])
def test_control_a_declared_refusal_with_a_body_keeps_its_status_and_keys(engine, route, status):
    """Where the relay passes the envelope, the status and the engine's keys survive. (A relay
    that hands every non-403 to `_engine_failure` is held by the strict xfail below instead.)"""
    engine.update(status=status, content=json.dumps(ENGINE_BODIES[status]).encode())
    r = _call(route)
    assert engine["calls"], "instrument failure: the engine double was not reached"
    assert r.status_code == status, (route.path, status, r.status_code, r.text[:160])
    got = set(_keys(r.json()))
    want = set(_keys(ENGINE_BODIES[status]["detail"]))
    assert want <= got, (route.path, sorted(want - got))


@pytest.mark.parametrize("route", relays(), ids=_ids(relays()))
@pytest.mark.parametrize("status", (403, 409, 404))
def test_an_empty_refusal_body_is_never_a_crash_or_a_200(engine, route, status):
    engine.update(status=status, content=b"")
    r = _call(route)
    assert engine["calls"], "instrument failure: the engine double was not reached"
    assert r.status_code not in (200, 500), (route.path, status, r.status_code)
    if status == 403 or not _wraps_non_403(route):
        assert r.status_code == status, (route.path, status, r.status_code)


@pytest.mark.xfail(strict=True, reason=(
    "DEFECT (Lane 1, gateway.py finance_measure on 422 and 200; export_cdrl_profiles and export_cdrl "
    "on 200): an engine answer with an EMPTY body reaches `rr.json()` unguarded, so the relay "
    "raises and answers 500 (a refusal the engine sent becomes a crash). The >= 400 arms that "
    "fall back to the response text are guarded. "
    "Packet: sessions/2026-10-30-packet-to-lane-01-relay-envelope-defects-finance-empty-body-and-cdrl-rewrap.md"))
def test_an_empty_422_or_200_body_is_never_a_500(engine):
    bad = []
    for route in relays():
        for status in (422, 200):
            engine.update(status=status, content=b"")
            engine["calls"].clear()
            r = _call(route)
            if engine["calls"] and r.status_code == 500:
                bad.append((sorted(route.methods)[0], route.path, status))
    assert not bad, f"an empty engine body became a 500: {bad}"


@pytest.mark.xfail(strict=True, reason=(
    "DEFECT (Lane 1, gateway.py _engine_failure, used by export_cdrl and export_cdrl_profiles): "
    "only a 403 is passed through; an engine 409 or 422 (declared refusals) is rewrapped into a "
    "502 `fin_engine_failed` carrying the engine's body as `engine_detail`. The status and the "
    "code the engine sent are gone. /finance/measure/{fn} passes 409 and 422 through. "
    "Packet: sessions/2026-10-30-packet-to-lane-01-relay-envelope-defects-finance-empty-body-and-cdrl-rewrap.md"))
def test_a_declared_409_or_422_is_not_rewrapped_into_a_502(engine):
    rewrapped = []
    for route in relays():
        for status in (409, 422):
            engine.update(status=status, content=json.dumps(ENGINE_BODIES[status]).encode())
            engine["calls"].clear()
            r = _call(route)
            if engine["calls"] and r.status_code != status:
                rewrapped.append((route.path, status, r.status_code))
    assert not rewrapped, f"declared engine refusals rewrapped: {rewrapped}"
