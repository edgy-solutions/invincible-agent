"""The Keycloak seam (``identity_exchange.exchange``), alone: a standard RFC 8693 exchange of the
user's own access token, unset by default, and a failure of ANY kind is ``None`` -- never a token.

Every realm answer is a real ``httpx.Response`` through a ``MockTransport`` on a real
``httpx.AsyncClient``; no network is touched.

Run:  uv run --frozen python -m pytest tests/identity/test_identity_exchange.py -q
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent import identity_exchange as ix  # noqa: E402

NOW = 1_800_000_000.0
ALICE = "alice@example.com"


def _jwt(email=ALICE, exp=NOW + 3600, tag="x"):
    def b(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'none'})}.{b({'email': email, 'sub': 's-' + email, 'exp': exp, 'jti': tag})}.sig"


@pytest.fixture
def realm(monkeypatch):
    monkeypatch.setenv("IDENTITY_EXCHANGE_TOKEN_URL", "http://realm.invalid/token")
    monkeypatch.setenv("IDENTITY_EXCHANGE_CLIENT_ID", "gw")
    monkeypatch.setenv("IDENTITY_EXCHANGE_CLIENT_SECRET", "not-a-real-secret")
    monkeypatch.setattr(ix.time, "time", lambda: NOW)
    box = {"seen": [], "respond": None}

    def handler(request):
        box["seen"].append({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        return box["respond"](request)

    real = httpx.AsyncClient
    monkeypatch.setattr(ix.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return box


def _run(token):
    return asyncio.run(ix.exchange(token))


def test_unset_means_none_and_no_request(monkeypatch):
    for k in ("IDENTITY_EXCHANGE_TOKEN_URL", "IDENTITY_EXCHANGE_CLIENT_ID",
              "IDENTITY_EXCHANGE_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    assert _run(_jwt(exp=NOW + 5)) is None


def test_success_returns_the_new_token_and_sends_the_standard_form(realm):
    old, new = _jwt(exp=NOW + 5, tag="old"), _jwt(tag="new")
    realm["respond"] = lambda r: httpx.Response(200, json={"access_token": new})
    assert _run(old) == new
    form = realm["seen"][0]
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:token-exchange"
    assert form["subject_token"] == old
    assert "requested_subject" not in form, "impersonation is ruled out"


def test_no_exchange_without_a_subject_token(realm):
    realm["respond"] = lambda r: httpx.Response(200, json={"access_token": _jwt()})
    assert _run("") is None and realm["seen"] == []


@pytest.mark.parametrize("answer", [
    lambda r: httpx.Response(400, json={"error": "invalid_grant"}),
    lambda r: httpx.Response(500, text="boom"),
    lambda r: httpx.Response(200, text="not json"),
    lambda r: httpx.Response(200, json={}),
    lambda r: httpx.Response(200, json={"access_token": ""}),
    lambda r: httpx.Response(200, json={"access_token": _jwt(email="mallory@example.com")}),
    lambda r: httpx.Response(200, json={"access_token": _jwt(exp=NOW + 3, tag="short")}),
    lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
], ids=["400", "500", "not-json", "no-token", "empty-token", "other-person", "no-later-exp", "transport"])
def test_every_failure_is_none_never_a_token(realm, answer):
    old = _jwt(exp=NOW + 5, tag="old")
    realm["respond"] = answer
    assert _run(old) is None
