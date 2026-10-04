"""THE CASE RUNNER'S TOKEN IS CACHED TO ITS EXPIRY -- AND NOT ONE MOMENT PAST IT.

Ruled 2026-10-03. Every `direct_call` without a human JWT minted a fresh case-runner token, one
client-credentials round trip per step. The token is now held in process memory, keyed by client
id, and served again only while more than the margin of its own `exp` remains. A token whose
`exp` cannot be read is never held. A 401/403 on a case-runner call drops what is held, so a
token refused before its expiry (a rotated realm key) costs one failed step, not every step
until it expires.

MINT AT USE still holds: the rule is against a token carried across a human's latency in durable
state. This cache is memory only, bounded by the token's own expiry, and minted inside the
step's `ctx.run`, whose journal records the response and never the header.

Run: uv run --frozen pytest tests/test_the_case_runner_token_is_cached_to_expiry.py -v
"""
from __future__ import annotations

import base64
import itertools
import json
import sys

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import main  # noqa: F401 -- sets the path

import spo_step_executor as ex  # noqa: E402 -- the executor main imports

#: The service_identity module object the EXECUTOR holds, derived, not imported a second way: a
#: module imported under two names is two caches, and an arm on the wrong one proves nothing.
si = sys.modules[ex.mint_case_runner_token.__module__]

NOW = 1_000_000.0
MARGIN = si._EXPIRY_MARGIN_S


_SERIAL = itertools.count()


def _jwt(claims) -> str:
    """A token Keycloak might mint. Every one is a distinct string -- two with equal claims would
    be the same token, and an arm telling a re-mint from a cache hit would be comparing equals."""
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"hdr.{body}.sig{next(_SERIAL)}"


@pytest.fixture
def realm(monkeypatch):
    """Keycloak, as the mint sees it: each mint returns the next scripted token and is counted.
    The clock is ours."""
    state = {"now": NOW, "tokens": [], "mints": []}

    def mint(*, client_id, client_secret, timeout):
        state["mints"].append(client_id)
        return state["tokens"].pop(0)
    monkeypatch.setattr(si, "mint_token", mint)
    monkeypatch.setattr(si.time, "time", lambda: state["now"])
    monkeypatch.setenv("CASE_RUNNER_CLIENT_ID", "case-runner")
    monkeypatch.setenv("CASE_RUNNER_CLIENT_SECRET", "s")
    si._CASE_RUNNER_TOKENS.clear()
    yield state
    si._CASE_RUNNER_TOKENS.clear()


def test_A_TOKEN_WITH_LIFE_LEFT_IS_SERVED_AGAIN(realm):
    a, b = _jwt({"exp": NOW + 300}), _jwt({"exp": NOW + 600})
    realm["tokens"] = [a, b]
    assert si.mint_case_runner_token() == a
    realm["now"] = NOW + 300 - MARGIN - 1
    assert si.mint_case_runner_token() == a
    assert realm["mints"] == ["case-runner"]


def test_INSIDE_THE_MARGIN_IT_IS_MINTED_AGAIN(realm):
    """At exactly the margin, not one tick later: a request in flight must not arrive expired."""
    a, b = _jwt({"exp": NOW + 300}), _jwt({"exp": NOW + 900})
    realm["tokens"] = [a, b]
    si.mint_case_runner_token()
    realm["now"] = NOW + 300 - MARGIN
    assert si.mint_case_runner_token() == b
    assert si.mint_case_runner_token() == b
    assert len(realm["mints"]) == 2


@pytest.mark.parametrize("token", [
    "opaque-token", "a.!!!not-base64!!!.c", _jwt({}), _jwt({"exp": str(NOW + 300)}),
    _jwt({"exp": None}), _jwt(["exp"]),
], ids=["opaque", "garbled", "no-exp", "exp-a-numeric-string", "exp-null", "not-an-object"])
def test_A_TOKEN_WHOSE_EXPIRY_CANNOT_BE_READ_IS_NEVER_HELD(realm, token):
    realm["tokens"] = [token, token]
    assert si.mint_case_runner_token() == token
    assert si.mint_case_runner_token() == token
    assert len(realm["mints"]) == 2


def test_A_TOKEN_MINTED_ALREADY_INSIDE_THE_MARGIN_IS_NOT_HELD(realm):
    short = _jwt({"exp": NOW + MARGIN})
    realm["tokens"] = [short, short]
    si.mint_case_runner_token()
    si.mint_case_runner_token()
    assert len(realm["mints"]) == 2


def test_THE_CACHE_IS_KEYED_BY_THE_IDENTITY(realm, monkeypatch):
    """A changed client id is a different identity, and never inherits the old one's token."""
    a, b = _jwt({"exp": NOW + 300}), _jwt({"exp": NOW + 300})
    realm["tokens"] = [a, b]
    si.mint_case_runner_token()
    monkeypatch.setenv("CASE_RUNNER_CLIENT_ID", "case-runner-2")
    assert si.mint_case_runner_token() == b
    assert realm["mints"] == ["case-runner", "case-runner-2"]


def test_FORGETTING_MAKES_THE_NEXT_STEP_MINT(realm):
    a, b = _jwt({"exp": NOW + 300}), _jwt({"exp": NOW + 300})
    realm["tokens"] = [a, b]
    si.mint_case_runner_token()
    si.forget_case_runner_token()
    assert si.mint_case_runner_token() == b


# ── THE EXECUTOR: A REFUSED TOKEN IS DROPPED ────────────────────────────────────────────────

class _Resp:
    def __init__(self, status):
        self.status_code, self.text = status, ""

    def raise_for_status(self):
        pass

    def json(self):
        return {"status": "written"}


def _call(monkeypatch, status, identity):
    sent = []
    monkeypatch.setattr(ex, "check_can_invoke", lambda cap, who, **kw: True)
    monkeypatch.setattr(ex.requests, "post", lambda url, json, headers, timeout: sent.append(
        headers.get("Authorization")) or _Resp(status))
    try:
        ex.execute_direct_call({"id": "w", "endpoint": "http://writer.test/w", "capability": "c"},
                               identity)
    except ex.StepFailAndRelease as exc:
        assert exc.status_code == 403, exc.status_code
    return sent


@pytest.mark.parametrize("status", [401, 403])
def test_A_CASE_RUNNER_CALL_REFUSED_401_403_DROPS_THE_TOKEN(realm, monkeypatch, status):
    a, b = _jwt({"exp": NOW + 300}), _jwt({"exp": NOW + 300})
    realm["tokens"] = [a, b]
    assert _call(monkeypatch, status, {}) == [f"Bearer {a}"]
    assert _call(monkeypatch, 200, {}) == [f"Bearer {b}"]


def test_CONTROL_AN_ANSWERED_CALL_KEEPS_IT_AND_A_HUMANS_REFUSAL_IS_NOT_OURS(realm, monkeypatch):
    """Same calls, differing only in the answer and in whose token was refused."""
    a, b = _jwt({"exp": NOW + 300}), _jwt({"exp": NOW + 300})
    realm["tokens"] = [a, b]
    assert _call(monkeypatch, 200, {}) == [f"Bearer {a}"]
    assert _call(monkeypatch, 401, {"user_jwt": "human", "authz_id": "h@x"}) == ["Bearer human"]
    assert _call(monkeypatch, 200, {}) == [f"Bearer {a}"]
    assert realm["mints"] == ["case-runner"]
