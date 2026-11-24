"""A VALID TOKEN IS RELEASED WHEN IT CANNOT BE REFRESHED (architect, 2026-11-24).

The 60 s refresh margin buys something only where a refresh is possible (the exchange is
configured). Where it is not, refusing a token that is still valid stalls the answer for no gain,
and the callee checks expiry itself: the vault releases it until ``exp`` minus the clock skew.

Run:  uv run --frozen python -m pytest tests/identity/test_a_valid_token_is_released_when_it_cannot_be_refreshed.py -q
"""
from __future__ import annotations

import pytest

from src.iagent import gateway
from src.iagent.identity_vault import IdentityVault, RedemptionOutcome
from tests.identity.test_identity_vault import ALICE, _FakeClock, _jwt
from tests.identity.test_redemption_endpoint import (  # noqa: F401  (fixtures + helpers)
    RUN, _NOW, _login, _redeem, client, fresh_vault, seam_unset,
)

WALL = 1000.0


def _vault(refreshable):
    return IdentityVault(clock=_FakeClock(), wall_clock=lambda: WALL, refresh_margin_seconds=60,
                         clock_skew_seconds=5, refreshable=lambda: refreshable)


def test_not_refreshable_a_token_with_30s_left_is_released():
    v = _vault(False)
    tok = _jwt(exp=WALL + 30)
    v.stash("r", tok, subject=ALICE)
    r = v.redeem("r", "c1")
    assert r.outcome == RedemptionOutcome.OK and r.token == tok


def test_not_refreshable_a_token_within_the_skew_still_needs_a_refresh():
    v = _vault(False)
    v.stash("r", _jwt(exp=WALL + 3), subject=ALICE)
    r = v.redeem("r", "c1")
    assert r.outcome == RedemptionOutcome.NEEDS_REFRESH and r.token is None


def test_CONTROL_refreshable_the_same_token_with_30s_left_needs_a_refresh():
    v = _vault(True)
    v.stash("r", _jwt(exp=WALL + 30), subject=ALICE)
    r = v.redeem("r", "c1")
    assert r.outcome == RedemptionOutcome.NEEDS_REFRESH and r.token is None


def test_the_default_refreshable_follows_the_exchange_environment(monkeypatch):
    keys = ("IDENTITY_EXCHANGE_TOKEN_URL", "IDENTITY_EXCHANGE_CLIENT_ID",
            "IDENTITY_EXCHANGE_CLIENT_SECRET")
    for k in keys:
        monkeypatch.delenv(k, raising=False)
    v = IdentityVault(clock=_FakeClock(), wall_clock=lambda: WALL, refresh_margin_seconds=60,
                      clock_skew_seconds=5)
    v.stash("r", _jwt(exp=WALL + 30), subject=ALICE)
    assert v.redeem("r", "c1").outcome == RedemptionOutcome.OK, "unset: not refreshable"
    for k in keys:
        monkeypatch.setenv(k, "x")
    assert v.redeem("r", "c2").outcome == RedemptionOutcome.NEEDS_REFRESH, "set: refreshable"


def test_the_skew_setting_defaults_to_5_and_reads_the_environment(monkeypatch):
    from src.iagent.identity_vault import vault_clock_skew_seconds
    monkeypatch.delenv("IDENTITY_VAULT_CLOCK_SKEW_SECONDS", raising=False)
    assert vault_clock_skew_seconds() == 5
    monkeypatch.setenv("IDENTITY_VAULT_CLOCK_SKEW_SECONDS", "9")
    assert vault_clock_skew_seconds() == 9
    monkeypatch.setenv("IDENTITY_VAULT_CLOCK_SKEW_SECONDS", "nope")
    assert vault_clock_skew_seconds() == 5


def test_an_unconfigured_exchange_names_the_pause_token_expired(
        client, seam_unset, monkeypatch):
    from src.iagent import identity_exchange
    monkeypatch.setattr(identity_exchange.time, "time", lambda: _NOW)
    v = IdentityVault(wall_clock=lambda: _NOW, clock_skew_seconds=5)  # default refreshable
    gateway.VAULT = v
    v.stash(RUN, _jwt(exp=_NOW + 3), subject=ALICE)
    _login("svc:supervisor")
    assert _redeem(client, "c1").status_code == 409
    assert v.reauth_reason(RUN) == "token_expired_and_not_refreshable"


def test_CONTROL_a_configured_exchange_that_fails_keeps_the_near_expiry_reason(
        client, monkeypatch):
    from src.iagent import identity_exchange
    for k in ("IDENTITY_EXCHANGE_TOKEN_URL", "IDENTITY_EXCHANGE_CLIENT_ID",
              "IDENTITY_EXCHANGE_CLIENT_SECRET"):
        monkeypatch.setenv(k, "x")

    async def _fails(token):
        return None

    monkeypatch.setattr(identity_exchange, "exchange", _fails)
    v = IdentityVault(wall_clock=lambda: _NOW, refresh_margin_seconds=60)
    gateway.VAULT = v
    v.stash(RUN, _jwt(exp=_NOW + 10), subject=ALICE)
    _login("svc:supervisor")
    assert _redeem(client, "c1").status_code == 409
    assert v.reauth_reason(RUN) == "token_near_expiry_and_not_refreshable"
