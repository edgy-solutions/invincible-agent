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


# ---------------------------------------------------------------------------
# ADR-0026 step 6: persona + entitled_domains come SOLELY from Topaz.
# The JWT-claim path is deleted. A user with zero entitlements gets
# HONEST-EMPTY (persona=None, entitled_domains=[], source="none") —
# NOT a fabricated MECHANIC. These tests pin that contract.
# ---------------------------------------------------------------------------
from iagent.authz import Entitlements, EntitlementCell  # noqa: E402


class _FakeCache:
    """Stand-in for the per-token EntitlementCache. Returns a fixed
    matrix regardless of key, so tests control what Topaz 'returned'."""
    def __init__(self, entitlements: Entitlements):
        self._e = entitlements

    def get(self, sub, jti, exp, lookup_key=None):
        return self._e


def test_honest_empty_when_no_entitlements(auth_mod, monkeypatch):
    """ZERO-ENTITLEMENTS FIXTURE (the null-stays-null gate). A user with
    no Topaz entitlements gets persona=None, entitled_domains=[],
    entitlement_source='none' — NOT a fabricated MECHANIC/ANALYST/etc.
    Even a JWT that HAPPENS to carry a legacy `persona` claim is
    ignored: claims no longer drive persona.
    """
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1",
        "email": "u@example.com",
        "realm_access": {"roles": ["analyst"]},
        "persona": "MECHANIC",           # legacy claim — MUST be ignored
        "entitled_domains": ["AVIATION"],  # legacy claim — MUST be ignored
    }))
    # No topaz cache configured (TOPAZ_DIRECTORY_URL unset) → empty matrix.
    monkeypatch.setattr(auth_mod, "_get_entitlement_cache", lambda: None)
    user = auth_mod.get_current_user(token="fake-token")
    assert user.persona is None, (
        f"honest-empty: persona must be None, not a fabricated default. "
        f"Got {user.persona!r}."
    )
    assert user.entitled_domains == []
    assert user.entitlement_source == "none"
    # The legacy JWT claims did NOT leak in:
    assert user.persona != "MECHANIC"


def test_persona_from_topaz_default_cell(auth_mod, monkeypatch):
    """With a Topaz matrix that has a default cell, persona = the
    default cell's persona; source = 'topaz'."""
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1", "email": "u@example.com",
    }))
    ents = Entitlements(
        cells=[
            EntitlementCell(persona="DATA_ENGINEER", domain="AVIATION"),
            EntitlementCell(persona="ARCHITECT", domain="DEFENSE"),
        ],
        default=EntitlementCell(persona="DATA_ENGINEER", domain="AVIATION"),
    )
    monkeypatch.setattr(auth_mod, "_get_entitlement_cache", lambda: _FakeCache(ents))
    user = auth_mod.get_current_user(token="fake-token")
    assert user.persona == "DATA_ENGINEER"
    assert user.entitlement_source == "topaz"
    # entitled_domains = all domains across cells, sorted, deduped.
    assert user.entitled_domains == ["AVIATION", "DEFENSE"]


def test_persona_from_first_cell_when_no_default(auth_mod, monkeypatch):
    """No default cell → persona falls to the first cell's persona
    (still a REAL entitled persona, never fabricated)."""
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1", "email": "u@example.com",
    }))
    ents = Entitlements(
        cells=[EntitlementCell(persona="MECHANIC", domain="AVIATION")],
        default=None,
    )
    monkeypatch.setattr(auth_mod, "_get_entitlement_cache", lambda: _FakeCache(ents))
    user = auth_mod.get_current_user(token="fake-token")
    assert user.persona == "MECHANIC"          # from the cell, not a default
    assert user.entitlement_source == "topaz"
    assert user.entitled_domains == ["AVIATION"]


def test_jwt_persona_claim_is_ignored(auth_mod, monkeypatch):
    """A JWT carrying a `persona` claim does NOT override Topaz — the
    claim path is deleted. Topaz's answer wins; here Topaz is empty so
    the honest-empty None wins over the claim."""
    import jwt
    monkeypatch.setattr(jwt, "decode", _decode_returning({
        "sub": "user-1", "email": "u@example.com",
        "persona": "COMMANDER",  # would have been honored pre-step-6
    }))
    monkeypatch.setattr(auth_mod, "_get_entitlement_cache", lambda: None)
    user = auth_mod.get_current_user(token="fake-token")
    assert user.persona is None
    assert user.persona != "COMMANDER"
