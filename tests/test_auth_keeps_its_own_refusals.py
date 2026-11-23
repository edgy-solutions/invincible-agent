"""get_current_user's own refusals reach the caller as raised, not re-wrapped as 401.

ADR-0026: "auth is down" is a distinct, retryable 503 so a caller can tell an outage from a
denial. Measured 2026-10-23: the catch-all `except Exception` at the end of get_current_user
caught the 503 it had just raised and answered 401 "Authentication failed: 503: ...", and
wrapped the no-identity 401 the same way. The ingest-v1 contract (docs/api/ingest-v1.md)
promises the 503; these arms seal that it is what goes out, and that the catch-all still
answers 401 for a failure that is not one of its own refusals.

Run: uv run --frozen --extra agent-fleet pytest tests/test_auth_keeps_its_own_refusals.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def auth_mod(monkeypatch):
    """auth.py loaded by file path with PyJWKClient stubbed (as tests/test_auth_persona.py)."""
    import jwt

    class _FakeJWKSClient:
        def __init__(self, *_a, **_kw):
            pass

        def get_signing_key_from_jwt(self, token):
            class _K:
                key = "fake-key"
            return _K()

    monkeypatch.setattr(jwt, "PyJWKClient", _FakeJWKSClient)
    spec = importlib.util.spec_from_file_location(
        "iagent_auth_refusals_under_test", str(_SRC / "iagent" / "auth.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # verified_claims refuses before decoding when either served list is empty.
    monkeypatch.setenv(mod.ACCEPTED_ISSUERS_ENV, "https://realm.test/realms/r")
    monkeypatch.setenv(mod.ACCEPTED_AUDIENCES_ENV, "bff.test")
    return mod


def _decode_returning(payload):
    return lambda *_a, **_kw: payload


def _refusal(auth_mod) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        auth_mod.get_current_user(token="fake-token")
    return exc.value


def test_topaz_unavailable_reaches_the_caller_as_a_retryable_503(auth_mod, monkeypatch):
    import jwt

    class _DownCache:
        def get(self, **_kw):
            raise auth_mod.AuthorizationUnavailable("topaz unreachable")

    monkeypatch.setattr(jwt, "decode", _decode_returning({"sub": "u-1", "email": "u@x"}))
    monkeypatch.setattr(auth_mod, "_get_entitlement_cache", lambda: _DownCache())
    e = _refusal(auth_mod)
    assert e.status_code == 503, (e.status_code, e.detail)
    assert isinstance(e.detail, dict), e.detail
    assert e.detail["error"] == "authorization_unavailable"
    assert e.detail["retryable"] is True


def test_a_token_with_no_identity_is_its_own_401_not_a_wrapped_one(auth_mod, monkeypatch):
    import jwt

    monkeypatch.setattr(jwt, "decode", _decode_returning({}))
    monkeypatch.setattr(auth_mod, "_get_entitlement_cache", lambda: None)
    e = _refusal(auth_mod)
    assert e.status_code == 401
    assert str(e.detail).startswith("Invalid token payload"), e.detail


class _FlakyJwks:
    """A JWKS client that raises `errors` in turn, then returns a key."""

    def __init__(self, *errors):
        self.errors = list(errors)
        self.calls = 0

    def get_signing_key_from_jwt(self, token):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)

        class _K:
            key = "fake-key"
        return _K()


def test_a_key_fetch_that_cannot_connect_is_retried_then_a_retryable_503(auth_mod, monkeypatch):
    """THE SEAL. The realm's keys unreachable on every attempt: retried, then the outage 503
    (ADR-0026), never a 401 that tells a signed-in client its token is bad."""
    import jwt

    down = _FlakyJwks(*[jwt.PyJWKClientConnectionError("realm restarting")] * 5)
    monkeypatch.setattr(auth_mod, "jwks_client", down)
    monkeypatch.setattr(auth_mod.time, "sleep", lambda _s: None)
    e = _refusal(auth_mod)
    assert down.calls == auth_mod.KEY_FETCH_ATTEMPTS >= 2, down.calls
    assert e.status_code == 503, (e.status_code, e.detail)
    assert e.detail["error"] == "authorization_unavailable"
    assert e.detail["retryable"] is True


def test_a_key_fetch_that_fails_once_is_retried_and_the_token_is_verified(auth_mod, monkeypatch):
    """The retry is not decoration: one failed connect, then the key, verifies the token."""
    import jwt

    flaky = _FlakyJwks(jwt.PyJWKClientConnectionError("realm restarting"))
    monkeypatch.setattr(auth_mod, "jwks_client", flaky)
    monkeypatch.setattr(auth_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(jwt, "decode", _decode_returning({"sub": "u-1"}))
    assert auth_mod.verified_claims("fake-token") == {"sub": "u-1"}
    assert flaky.calls == 2


def test_CONTROL_a_key_the_realm_does_not_hold_is_a_401_and_not_retried(auth_mod, monkeypatch):
    """Control, differing only in the error: an unknown `kid` is a verdict on the token
    (`PyJWKClientError`, not its connection subclass), so one attempt and a 401."""
    import jwt

    unknown = _FlakyJwks(jwt.PyJWKClientError("Unable to find a signing key that matches"))
    monkeypatch.setattr(auth_mod, "jwks_client", unknown)
    monkeypatch.setattr(auth_mod.time, "sleep", lambda _s: None)
    e = _refusal(auth_mod)
    assert unknown.calls == 1
    assert e.status_code == 401, (e.status_code, e.detail)


def test_a_failure_that_is_not_a_refusal_still_answers_401(auth_mod, monkeypatch):
    """Control: the catch-all is intact for an unexpected error that is neither a JWT verdict nor
    a key fetch that could not connect (that one is the 503 above)."""
    class _BrokenJwks:
        def get_signing_key_from_jwt(self, token):
            raise RuntimeError("jwks unreachable")

    monkeypatch.setattr(auth_mod, "jwks_client", _BrokenJwks())
    e = _refusal(auth_mod)
    assert e.status_code == 401
    assert str(e.detail).startswith("Authentication failed: jwks unreachable"), e.detail


def test_an_expired_token_answers_its_own_401(auth_mod, monkeypatch):
    import jwt

    def _expired(*_a, **_kw):
        raise jwt.ExpiredSignatureError("expired")

    monkeypatch.setattr(jwt, "decode", _expired)
    e = _refusal(auth_mod)
    assert (e.status_code, e.detail) == (401, "Token has expired")
