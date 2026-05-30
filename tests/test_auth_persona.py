"""Tests for the ADR-0009 persona / entitled_domains claim plumbing in
``src/iagent/auth.py``.

We exercise the JWT-claim extraction directly by stubbing the JWKS client
and ``jwt.decode`` so the unit tests don't need a real Keycloak.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Make iagent importable from the repo's src/ layout.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture
def auth_mod(monkeypatch):
    """Import ``auth`` after stubbing PyJWKClient so the module-level
    ``jwks_client = PyJWKClient(...)`` initialization doesn't try to hit
    a real Keycloak."""
    import jwt

    class _FakeJWKSClient:
        def __init__(self, *_a, **_kw):
            pass
        def get_signing_key_from_jwt(self, token):
            class _K: key = "fake-key"
            return _K()

    monkeypatch.setattr(jwt, "PyJWKClient", _FakeJWKSClient)

    # Import auth.py directly via importlib — going through the `iagent`
    # package's __init__ would pull in Dagster `defs` (asset-decorator
    # validation runs at import time), which is unrelated to auth.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "iagent_auth_under_test",
        str(_SRC / "iagent" / "auth.py"),
    )
    auth_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auth_mod)
    return auth_mod


def _decode_returning(payload):
    """Return a fake ``jwt.decode`` that yields the given payload."""
    def _fake_decode(*_a, **_kw):
        return payload
    return _fake_decode


def test_persona_falls_back_when_claim_missing(auth_mod, monkeypatch):
    """No `persona` claim in the JWT → falls back to USER_PERSONA_FALLBACK."""
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1",
        "email": "u@example.com",
        "realm_access": {"roles": ["analyst"]},
    }))
    user = auth_mod.get_current_user(token="fake-token")
    assert user.persona == auth_mod.USER_PERSONA_FALLBACK
    assert user.entitled_domains == []


def test_persona_from_claim_is_uppercased(auth_mod, monkeypatch):
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1",
        "email": "u@example.com",
        "persona": "auditor",
    }))
    user = auth_mod.get_current_user(token="fake-token")
    assert user.persona == "AUDITOR"


def test_entitled_domains_list_claim(auth_mod, monkeypatch):
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1",
        "email": "u@example.com",
        "entitled_domains": ["maintenance", "data_engineering"],
    }))
    user = auth_mod.get_current_user(token="fake-token")
    assert user.entitled_domains == ["MAINTENANCE", "DATA_ENGINEERING"]


def test_entitled_domains_csv_string_claim(auth_mod, monkeypatch):
    """Some IdPs serialize multi-valued claims as comma-separated strings."""
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1",
        "email": "u@example.com",
        "entitled_domains": "MAINTENANCE, MANUFACTURING",
    }))
    user = auth_mod.get_current_user(token="fake-token")
    assert user.entitled_domains == ["MAINTENANCE", "MANUFACTURING"]


def test_alternative_persona_claim_name_via_env(monkeypatch):
    """Per the env-var contract: ``USER_PERSONA_CLAIM`` overrides the
    claim name PingSSO actually issues. Has to be set BEFORE importing
    the module since it's read at import time."""
    import jwt

    class _FakeJWKSClient:
        def __init__(self, *_a, **_kw):
            pass
        def get_signing_key_from_jwt(self, token):
            class _K: key = "fake-key"
            return _K()
    monkeypatch.setattr(jwt, "PyJWKClient", _FakeJWKSClient)

    monkeypatch.setenv("USER_PERSONA_CLAIM", "iagent_role")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "iagent_auth_under_test_env",
        str(_SRC / "iagent" / "auth.py"),
    )
    auth_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auth_mod)

    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1",
        "email": "u@example.com",
        "iagent_role": "tech_writer",
        "persona": "should-be-ignored",
    }))
    user = auth_mod.get_current_user(token="fake-token")
    assert user.persona == "TECH_WRITER"
