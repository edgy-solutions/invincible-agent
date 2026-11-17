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
CHECKS = "/api/v3/directory/checks"


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


def _rig(monkeypatch, pages, held, reasons=None):
    """`pages`: {token-or-"": (keys, next_token)}. `held`: keys answered check:true. `reasons`:
    {key: reason}, answered `check: false` with that `context.reason`, as the live directory answers
    a check it could not decide (measured 2026-11-14)."""
    log = types.SimpleNamespace(requests=[], checks=[])

    def handler(request):
        log.requests.append(request)
        if request.url.path == LIST:
            keys, nxt = pages[request.url.params.get("page.token") or ""]
            body = {"results": [{"type": "capability", "id": k} for k in keys]}
            if nxt:
                body["page"] = {"next_token": nxt}
            return httpx.Response(200, json=body)
        if request.url.path == CHECKS:
            req = json.loads(request.content)
            log.checks.append(req)
            items = []
            for c in req["checks"]:
                why = (reasons or {}).get(c["object_id"])
                items.append({"check": False, "context": {"reason": why}} if why
                             else {"check": c["object_id"] in held, "context": {}})
            return httpx.Response(200, json={"checks": items})
        return httpx.Response(404, json={})

    _directory(monkeypatch, handler)
    return log


def test_a1_the_held_subset_is_served_sorted(as_user, monkeypatch):
    log = _rig(monkeypatch, {"": (["zz:gamma", "zz:alpha", "zz:beta"], "")}, {"zz:alpha", "zz:gamma"})
    r = as_user().get("/me/entitlements")
    assert r.status_code == 200, r.text
    assert r.json()["capabilities"] == ["zz:alpha", "zz:gamma"]
    # One batched check names every key, under the caller's authz_id; no single check is sent.
    assert len(log.checks) == 1
    d = log.checks[0]["default"]
    assert d["object_type"] == "capability" and d["relation"] == "can_invoke"
    assert d["subject_type"] == "user" and d["subject_id"] == AUTHZ
    assert sorted(c["object_id"] for c in log.checks[0]["checks"]) == ["zz:alpha", "zz:beta", "zz:gamma"]
    assert [q.url.path for q in log.requests] == [LIST, CHECKS]
    ingest_api.Entitlements.model_validate(r.json())            # arm 8: the served body validates


def test_a2_a_check_on_a_missing_object_is_not_held(as_user, monkeypatch):
    _rig(monkeypatch, {"": (["zz:alpha", "zz:beta"], "")}, {"zz:alpha"},
         reasons={"zz:beta": "E20025 object not found: capability:zz:beta"})
    r = as_user().get("/me/entitlements")
    assert r.status_code == 200, r.text
    assert r.json()["capabilities"] == ["zz:alpha"]


@pytest.mark.parametrize("reason", ["E20036 relation not found", "E20026 object type not found"])
def test_a2b_a_check_the_directory_could_not_decide_is_503(as_user, monkeypatch, reason):
    _rig(monkeypatch, {"": (["zz:alpha", "zz:beta"], "")}, {"zz:alpha"}, reasons={"zz:beta": reason})
    r = as_user().get("/me/entitlements")
    assert r.status_code == 503, r.text
    assert r.json()["detail"]["error"] == "authorization_unavailable"


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
        if request.url.path == CHECKS:
            # Only the `check*` cases fail the batch; every other case is held, so its 503 is the list's.
            asked = json.loads(request.content)["checks"]
            if case == "check500":
                return httpx.Response(500, json={})
            if case == "check404":
                return httpx.Response(404, json={})
            if case == "checkcount":
                return httpx.Response(200, json={"checks": [{"check": True}] * (len(asked) + 1)})
            if case == "checkstring":
                return httpx.Response(200, json={"checks": [{"check": "true"}] * len(asked)})
            return httpx.Response(200, json={"checks": [{"check": True}] * len(asked)})
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
        return httpx.Response(200, json={"results": [{"id": "zz:alpha"}]})   # the check* cases
    return handler


@pytest.mark.parametrize("case", ["connect", "500", "nonjson", "shape", "noid", "repeat",
                                  "check500", "check404", "checkcount", "checkstring"])
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
    assert ht.can_invoke_each(["zz:alpha"], "") == [False]
    assert log.requests == []
    assert ht.capabilities_and_held("") == (["zz:alpha"], [])
    assert [q.url.path for q in log.requests] == [LIST]          # the list, and no check


def test_a8_a_body_without_capabilities_fails_validation(as_user, monkeypatch):
    _rig(monkeypatch, {"": (["zz:alpha"], "")}, {"zz:alpha"})
    body = as_user().get("/me/entitlements").json()
    del body["capabilities"]
    with pytest.raises(Exception):
        ingest_api.Entitlements.model_validate(body)
