"""No tool on the MCP surface answers without a user token.

The route set is DERIVED: every route `gateway.app` registers under `MCP_TAG`. Each route's own
door (its dependency chain, run in front of a handler that only says "reached", so no handler, no
neo4j, no Topaz and no engine is touched) is asked:

  * no token                      -> refused 401
  * a token that does not verify  -> refused 401
  * a service-only token (a `svc:` authz identity: the non-human namespace of policy/users.yaml,
    Keycloak client-credentials, no mailbox) -> refused

and one positive control: a verified user token is admitted, so a refusal above is the door and not
a broken instrument.

The service-only arm is a STRICT XFAIL on master: see the test's reason for the defect.

Run: uv run pytest tests/mcp_seals/test_no_mcp_tool_without_a_user_token.py -q
"""
from __future__ import annotations

import time
import types

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from _mcp_surface_derived import mcp_routes, stub_for

from src.iagent import auth, gateway


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def door(monkeypatch, key):
    """Verify against our own key; no Topaz (the cache is absent)."""
    pub = key.public_key()
    monkeypatch.setattr(auth.jwks_client, "get_signing_key_from_jwt",
                        lambda tok: types.SimpleNamespace(key=pub))
    monkeypatch.setattr(auth, "_get_entitlement_cache", lambda: None)


def _token(key, **claims) -> str:
    payload = {"exp": time.time() + 600, "iat": time.time(), **claims}
    return jwt.encode(payload, key, algorithm="RS256")


def _user_token(key):
    return _token(key, sub="11111111-aaaa-bbbb-cccc-000000000001", azp="mcp-client",
                  **{"email": "alice@example.com", auth.USER_ENTITLEMENT_CLAIM: "alice@example.com"})


def _service_token(key):
    return _token(key, sub="22222222-aaaa-bbbb-cccc-000000000002", azp="mcp-server",
                  preferred_username="service-account-mcp-server",
                  **{auth.USER_ENTITLEMENT_CLAIM: "svc:mcp-server"})


def _ids(routes):
    return [f"{sorted(r.methods)[0]} {r.path}" for r in routes]


def test_the_surface_was_derived_and_is_not_empty():
    assert len(mcp_routes()) >= 2, "instrument failure: no route found under the mcp tag"


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_no_token_is_refused(route):
    r = TestClient(stub_for(route)).get("/x")
    assert r.status_code == 401, (route.path, r.status_code, r.text[:120])


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_a_token_that_does_not_verify_is_refused(route, monkeypatch):
    def bad(tok):
        raise jwt.PyJWTError("signature does not verify")
    monkeypatch.setattr(auth.jwks_client, "get_signing_key_from_jwt", bad)
    r = TestClient(stub_for(route)).get("/x", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401, (route.path, r.status_code)


@pytest.mark.parametrize("route", mcp_routes(), ids=_ids(mcp_routes()))
def test_control_a_verified_user_token_is_admitted(route, key):
    """CONTROL: the stub admits a real user, so the refusals above are the door's."""
    r = TestClient(stub_for(route)).get("/x", headers={"Authorization": f"Bearer {_user_token(key)}"})
    assert r.status_code == 200 and r.json() == {"reached": True}, (route.path, r.status_code)


@pytest.mark.xfail(strict=True, reason=(
    "DEFECT (Lane 1, src/iagent/auth.py get_current_user): the door verifies a signature and "
    "resolves an authz id, and admits a service-only token (authz id in the `svc:` namespace, "
    "client-credentials, no mailbox) on every mcp route. Nothing at the door tells a user token "
    "from a service token; the only refusal of a `svc:` caller is per handler "
    "(`_is_service_caller`) and covers only some routes. "
    "Packet: sessions/2026-10-30-packet-to-lane-01-the-mcp-door-admits-a-service-token.md"))
def test_a_service_only_token_is_refused_on_every_route(key):
    admitted = []
    for route in mcp_routes():
        r = TestClient(stub_for(route)).get(
            "/x", headers={"Authorization": f"Bearer {_service_token(key)}"})
        if r.status_code not in (401, 403):
            admitted.append((sorted(route.methods)[0], route.path, r.status_code))
    assert not admitted, f"a service-only token passed the door of {len(admitted)} mcp routes: {admitted}"


def test_the_service_token_is_a_service_caller_by_the_servers_own_predicate(key):
    """CONTROL for the xfail: the token above is what the server itself calls a service caller, so
    the xfail is not red for want of a well-formed service token."""
    claims = jwt.decode(_service_token(key), options={"verify_signature": False})
    assert gateway._is_service_caller(auth.resolve_token_identity(claims)[1]) is True
    claims = jwt.decode(_user_token(key), options={"verify_signature": False})
    assert gateway._is_service_caller(auth.resolve_token_identity(claims)[1]) is False
