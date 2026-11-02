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


def test_a_failure_that_is_not_a_refusal_still_answers_401(auth_mod, monkeypatch):
    """Control: the catch-all is intact for what it was written for (a JWKS fetch failure)."""
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
