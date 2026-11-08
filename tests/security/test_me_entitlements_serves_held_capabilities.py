"""GET /me/entitlements serves the capability keys the caller holds, read from the directory.

Sealed: `capabilities` is every Topaz directory object of type `capability` (read from the SERVER,
paginated, never from `policy/capability_grants.yaml`) on which the caller's authz_id holds
`can_invoke`, sorted. A directory that cannot be read is 503, never a partial list. No capability
key, prefix, kind or profile is named in the code: the keys here are made up (`zz:*`).

Rulings:
- Architect 2026-11-06: "/me/entitlements serves what the capability registry holds; cortex consumes;
  no new registry."
- Architect 2026-10-30 (recorded in cortex-ui `src/lib/reviewExport.ts`): "the signal is a
  `capabilities` list on `GET /me/entitlements`, Topaz-derived, carrying `ingest:exportBatch` and
  `can_export:<profile>`."

The authz_id (E1001) differs from the email, so an email-keyed check fails the arms. Every arm drives
the real `human_tasks` readers through an httpx.MockTransport.

Run:  uv run python -m pytest tests/security/test_me_entitlements_serves_held_capabilities.py -q
"""
from __future__ import annotations

import json
import types

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_api  # noqa: E402

AUTHZ = "E1001"
EMAIL = "a@x.test"
_REAL_CLIENT = httpx.Client
LIST = "/api/v3/directory/objects"
CHECK = "/api/v3/directory/check"


def _user(authz):
    return types.SimpleNamespace(
        authz_id=authz, id=authz, sub=authz, email=EMAIL, persona=None, entitled_domains=[],
        is_authenticated=True,
        entitlements=types.SimpleNamespace(cells=[], default=None, source="test"))


@pytest.fixture
def as_user():
    def _as(authz=AUTHZ):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user(authz)
        return TestClient(gateway.app, raise_server_exceptions=False)
    yield _as
    gateway.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_kinds(monkeypatch):
    monkeypatch.setattr(ck, "registrations", lambda: ())


def _directory(monkeypatch, handler):
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "http://topaz.test")
    monkeypatch.setattr(ht.httpx, "Client",
                        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def _rig(monkeypatch, pages, held, check_status=None):
    """`pages`: {token-or-"": (keys, next_token)}. `held`: keys answered check:true."""
    log = types.SimpleNamespace(requests=[], checks=[])

    def handler(request):
        log.requests.append(request)
        if request.url.path == LIST:
            keys, nxt = pages[request.url.params.get("page.token") or ""]
            body = {"results": [{"type": "capability", "id": k} for k in keys]}
            if nxt:
                body["page"] = {"next_token": nxt}
            return httpx.Response(200, json=body)
        if request.url.path == CHECK:
            req = json.loads(request.content)
            log.checks.append(req)
            st = (check_status or {}).get(req["object_id"])
            if st:
                return httpx.Response(st, json={})
            return httpx.Response(200, json={"check": req["object_id"] in held})
        return httpx.Response(404, json={})

    _directory(monkeypatch, handler)
    return log


def test_a1_the_held_subset_is_served_sorted(as_user, monkeypatch):
    log = _rig(monkeypatch, {"": (["zz:gamma", "zz:alpha", "zz:beta"], "")}, {"zz:alpha", "zz:gamma"})
    r = as_user().get("/me/entitlements")
    assert r.status_code == 200, r.text
    assert r.json()["capabilities"] == ["zz:alpha", "zz:gamma"]
    assert len(log.checks) == 3
    for c in log.checks:
        assert c["object_type"] == "capability" and c["relation"] == "can_invoke"
        assert c["subject_type"] == "user" and c["subject_id"] == AUTHZ
    assert {c["object_id"] for c in log.checks} == {"zz:alpha", "zz:beta", "zz:gamma"}
    ingest_api.Entitlements.model_validate(r.json())            # arm 8: the served body validates


def test_a2_a_404_on_a_check_is_not_held(as_user, monkeypatch):
    _rig(monkeypatch, {"": (["zz:alpha", "zz:beta"], "")}, {"zz:alpha"}, check_status={"zz:beta": 404})
    r = as_user().get("/me/entitlements")
    assert r.status_code == 200, r.text
    assert r.json()["capabilities"] == ["zz:alpha"]


def test_a3_pagination_walks_every_page(as_user, monkeypatch):
    log = _rig(monkeypatch, {"": (["zz:alpha"], "t2"), "t2": (["zz:beta"], "")}, {"zz:alpha", "zz:beta"})
    r = as_user().get("/me/entitlements")
    assert r.status_code == 200, r.text
    assert r.json()["capabilities"] == ["zz:alpha", "zz:beta"]
    lists = [q for q in log.requests if q.url.path == LIST]
    assert len(lists) == 2 and lists[0].url.params.get("page.token") is None
    assert lists[1].url.params.get("page.token") == "t2"
    assert all(q.url.params.get("object_type") == "capability" for q in lists)


def test_a4_the_policy_file_is_not_the_source(as_user, monkeypatch):
    _rig(monkeypatch, {"": (["zz:alpha"], "")}, {"zz:alpha", "ingest:exportBatch"})
    caps = as_user().get("/me/entitlements").json()["capabilities"]
    assert "ingest:exportBatch" not in caps and "zz:alpha" in caps


def _failing(case):
    repeats: list = []

    def handler(request):
        if request.url.path == CHECK:
            # Only `check500` fails a check; every other case is held, so its 503 is the list's.
            if case == "check500":
                return httpx.Response(500, json={})
            return httpx.Response(200, json={"check": True})
        if case == "connect":
            raise httpx.ConnectError("down", request=request)
        if case == "500":
            return httpx.Response(500, json={})
        if case == "nonjson":
            return httpx.Response(200, content=b"<html>")
        if case == "shape":
            return httpx.Response(200, json={"results": "nope"})
        if case == "noid":
            return httpx.Response(200, json={"results": [{"type": "capability"}]})
        if case == "repeat":
            # Bounded, so a missing repeat guard is a red (a served 200), not a hang.
            repeats.append(request)
            page = {"next_token": "t2"} if len(repeats) <= 5 else {}
            return httpx.Response(200, json={"results": [{"id": "zz:alpha"}], "page": page})
        return httpx.Response(200, json={"results": [{"id": "zz:alpha"}]})   # check500
    return handler


@pytest.mark.parametrize("case", ["connect", "500", "nonjson", "shape", "noid", "repeat", "check500"])
def test_a5_a_failure_is_503_never_a_partial_list(as_user, monkeypatch, case):
    _directory(monkeypatch, _failing(case))
    r = as_user().get("/me/entitlements")
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "authorization_unavailable"
    assert "retry-after" in {k.lower() for k in r.headers}
    assert "capabilities" not in r.json()


def test_a6_an_unset_directory_is_503_unconfigured(as_user, monkeypatch):
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "")
    r = as_user().get("/me/entitlements")
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "authorization_unconfigured"
    with pytest.raises(ht.AuthorizationUnconfigured):
        ht.capability_keys()


def test_a7_an_empty_authz_id_holds_nothing_and_asks_no_one(monkeypatch):
    log = _rig(monkeypatch, {"": (["zz:alpha"], "")}, {"zz:alpha"})
    assert ht.held_capabilities("") == []
    assert log.requests == []


def test_a8_a_body_without_capabilities_fails_validation(as_user, monkeypatch):
    _rig(monkeypatch, {"": (["zz:alpha"], "")}, {"zz:alpha"})
    body = as_user().get("/me/entitlements").json()
    del body["capabilities"]
    with pytest.raises(Exception):
        ingest_api.Entitlements.model_validate(body)
