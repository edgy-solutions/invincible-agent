"""The MCP door's one exemption, derived: a declared delegate passes the door of a route whose request
body has an `on_behalf_of` field, and is refused on every other MCP route. A `svc:` id that is not a
delegate is refused on all of them. Plus the seal: every MCP-tagged route carries the door.

Run: uv run pytest tests/mcp_seals/test_the_mcp_door_admits_a_delegate_only_where_on_behalf_of_is_a_field.py -q
"""
from __future__ import annotations

import json
import time
import types

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from _mcp_surface_derived import mcp_routes, stub_for

from src.iagent import auth, gateway

DELEGATE = "svc:case-runner"


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def door(monkeypatch, key):
    pub = key.public_key()
    monkeypatch.setattr(auth.jwks_client, "get_signing_key_from_jwt",
                        lambda tok: types.SimpleNamespace(key=pub))
    monkeypatch.setattr(auth, "_get_entitlement_cache", lambda: None)
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps({DELEGATE: ["alice@example.com"]}))


def _bearer(key, authz_id):
    tok = jwt.encode({"exp": time.time() + 600, "iat": time.time(), "sub": "33333333-aaaa-bbbb-cccc-000000000003",
                      "azp": "x", auth.USER_ENTITLEMENT_CLAIM: authz_id}, key, algorithm="RS256")
    return {"Authorization": f"Bearer {tok}"}


def _ids(routes):
    return [f"{sorted(r.methods)[0]} {r.path}" for r in routes]


def _takes_on_behalf_of(route):
    return gateway._body_names_on_behalf_of(route)


def test_the_exemption_set_is_the_two_routes_that_take_on_behalf_of():
    got = {r.path for r in mcp_routes() if _takes_on_behalf_of(r)}
    assert got == {"/ingest", "/human_tasks/{task_id}/act"}, got
    assert len(mcp_routes()) == 13


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_a_delegate_is_admitted_only_where_the_body_has_on_behalf_of(route, key):
    r = TestClient(stub_for(route)).get("/x", headers=_bearer(key, DELEGATE))
    if _takes_on_behalf_of(route):
        assert r.status_code == 200, (route.path, r.status_code, r.text[:120])
    else:
        assert r.status_code == 403 and r.json()["detail"]["error"] == "service_token_refused", \
            (route.path, r.status_code, r.text[:120])


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_a_svc_id_that_is_not_a_delegate_is_refused_everywhere(route, key):
    r = TestClient(stub_for(route)).get("/x", headers=_bearer(key, "svc:mcp-server"))
    assert r.status_code == 403, (route.path, r.status_code)
    assert r.json()["detail"] == {"error": "service_token_refused", "authz_id": "svc:mcp-server"}


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_seal_every_mcp_route_carries_the_door(route):
    """A new MCP-tagged route without `dependencies=_mcp_door()` goes red here."""
    calls = [d.call for d in route.dependant.dependencies]
    assert any(getattr(c, "__mcp_door__", False) for c in calls), (route.path, "no mcp door")
