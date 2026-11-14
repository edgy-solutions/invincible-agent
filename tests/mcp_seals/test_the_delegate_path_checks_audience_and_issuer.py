"""The client-credentials path through the door checks audience and issuer too, for every declared delegate.

The delegates are DERIVED from the sandbox values (`keycloak.extraServiceClients`, kind `delegate`): each is
minted the way Keycloak mints its client-credentials token (no mailbox, `azp` = its clientId, the authz claim
= its authzId) and sent to every route whose body takes `on_behalf_of`. For each:

  * the right issuer and audience  -> admitted (the walk still works)
  * another audience               -> refused 401
  * another issuer                 -> refused 401

The admitted arm is the control for both refusals: the three tokens differ only in the claim under test.

Run: uv run pytest tests/mcp_seals/test_the_delegate_path_checks_audience_and_issuer.py -q
"""
from __future__ import annotations

import json
import time
import types
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from _mcp_surface_derived import mcp_routes, stub_for

from src.iagent import auth, gateway

ISSUER, AUDIENCE = "https://realm.test/realms/r", "bff.test"
_VALUES = Path(__file__).resolve().parents[2] / "helm" / "invincible-agent" / "values-sandbox.yaml"


def _delegates():
    clients = yaml.safe_load(_VALUES.read_text(encoding="utf-8"))["keycloak"]["extraServiceClients"]
    return [(c["clientId"], c["authzId"]) for c in clients if c.get("kind") == "delegate"]


def _door_routes():
    return [r for r in mcp_routes() if gateway._body_names_on_behalf_of(r)]


_CASES = [(d, r) for d in _delegates() for r in _door_routes()]
_IDS = [f"{cid}-{sorted(r.methods)[0]} {r.path}" for (cid, _), r in _CASES]


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def door(monkeypatch, key):
    pub = key.public_key()
    monkeypatch.setattr(auth.jwks_client, "get_signing_key_from_jwt",
                        lambda tok: types.SimpleNamespace(key=pub))
    monkeypatch.setattr(auth, "_get_entitlement_cache", lambda: None)
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF",
                       json.dumps({authz: ["alice@example.com"] for _, authz in _delegates()}))
    monkeypatch.setenv(auth.ACCEPTED_ISSUERS_ENV, ISSUER)
    monkeypatch.setenv(auth.ACCEPTED_AUDIENCES_ENV, AUDIENCE)


def _client_credentials(key, client_id, authz_id, **over):
    claims = {"exp": time.time() + 600, "iat": time.time(), "sub": "44444444-aaaa-bbbb-cccc-000000000004",
              "iss": ISSUER, "aud": AUDIENCE, "azp": client_id,
              "preferred_username": f"service-account-{client_id}", auth.USER_ENTITLEMENT_CLAIM: authz_id}
    claims.update(over)
    return {"Authorization": f"Bearer {jwt.encode(claims, key, algorithm='RS256')}"}


def test_the_population_was_derived_and_is_not_empty():
    assert len(_delegates()) >= 1, "instrument failure: no delegate in the sandbox values"
    assert {r.path for r in _door_routes()} == {"/ingest", "/human_tasks/{task_id}/act"}


@pytest.mark.parametrize("delegate,route", _CASES, ids=_IDS)
def test_control_the_delegate_with_the_served_issuer_and_audience_is_admitted(delegate, route, key):
    r = TestClient(stub_for(route)).get("/x", headers=_client_credentials(key, *delegate))
    assert r.status_code == 200 and r.json() == {"reached": True}, (route.path, r.status_code, r.text[:160])


@pytest.mark.parametrize("delegate,route", _CASES, ids=_IDS)
def test_the_delegate_with_another_audience_is_refused(delegate, route, key):
    r = TestClient(stub_for(route)).get("/x", headers=_client_credentials(key, *delegate, aud="account"))
    assert r.status_code == 401 and "audience" in r.text.lower(), (route.path, r.status_code, r.text[:160])


@pytest.mark.parametrize("delegate,route", _CASES, ids=_IDS)
def test_the_delegate_from_another_issuer_is_refused(delegate, route, key):
    r = TestClient(stub_for(route)).get(
        "/x", headers=_client_credentials(key, *delegate, iss="https://evil.test/realms/r"))
    assert r.status_code == 401 and "issuer" in r.text.lower(), (route.path, r.status_code, r.text[:160])
