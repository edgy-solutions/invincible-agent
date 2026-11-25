"""A PAUSED RUN HAS A BOUNDED WAIT; PAST IT THE SESSION IS EXPIRED, RUN-WIDE (2026-11-24).

The bound lives in the vault, the BFF's one record for the run, so once it passes every later
redemption of the run fails at once and the stream reads the same state. ``not_found`` still
fails at once.

Run:  uv run --frozen python -m pytest tests/identity/test_a_paused_run_has_a_bounded_wait.py -q
"""
from __future__ import annotations

import base64
import json

import pytest

from src.iagent import gateway
from src.iagent.defs import dynamic_supervisor as ds
from src.iagent.identity_vault import IdentityVault, RedemptionOutcome
from tests.identity.test_identity_vault import ALICE, TOKEN, _FakeClock
from tests.identity.test_redemption_endpoint import (  # noqa: F401  (fixtures + helpers)
    RUN, _login, _redeem, client, fresh_vault,
)
from tests.identity.test_supervisor_redeems_at_dispatch import (  # noqa: F401
    _Config, _Ctx, _Resp, _stub_mint,
)

WAIT = 180


def _vault(clock):
    return IdentityVault(clock=clock, wall_clock=lambda: 1000.0, reauth_wait_seconds=WAIT)


def test_a_paused_run_waits_up_to_the_bound_then_the_session_is_expired():
    clk = _FakeClock()
    v = _vault(clk)
    v.stash("r", TOKEN, subject=ALICE)
    assert v.mark_awaiting_reauth("r", "x", "the call", "sign in")
    clk.advance(WAIT - 1)
    assert v.redeem("r", "c1").outcome == RedemptionOutcome.AWAITING_REAUTH
    assert v.state("r") == "awaiting_reauth"
    clk.advance(1)
    r = v.redeem("r", "c2")
    assert r.outcome == RedemptionOutcome.SESSION_EXPIRED and r.token is None
    assert v.state("r") == "session_expired"
    assert v.reauth_reason("r") == "reauth_wait_exceeded"
    assert v.replace("r", TOKEN + "2", ALICE) is False, "the session is over; the person asks again"
    assert v.state("r") == "session_expired"
    assert v.pause_record("r") is None
    assert v.paused_runs_of(ALICE) == []
    # terminal and not tombstoned: the same call id is still answered session_expired
    assert v.redeem("r", "c2").outcome == RedemptionOutcome.SESSION_EXPIRED


def test_a_second_mark_does_not_restart_the_wait():
    clk = _FakeClock()
    v = _vault(clk)
    v.stash("r", TOKEN, subject=ALICE)
    v.mark_awaiting_reauth("r", "x")
    clk.advance(WAIT - 10)
    v.mark_awaiting_reauth("r", "x again")
    clk.advance(10)
    assert v.state("r") == "session_expired"


def test_CONTROL_a_resume_inside_the_bound_goes_live():
    clk = _FakeClock()
    v = _vault(clk)
    v.stash("r", TOKEN, subject=ALICE)
    v.mark_awaiting_reauth("r", "x")
    clk.advance(WAIT - 1)
    assert v.replace("r", TOKEN + "2", ALICE) is True
    clk.advance(WAIT * 2)
    assert v.state("r") == "live"
    assert v.redeem("r", "c1").ok


def test_a_token_expired_at_stash_starts_its_wait_at_the_stash():
    clk = _FakeClock()

    def b(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    old = f"{b({'alg': 'none'})}.{b({'exp': 10.0})}.sig"
    v = _vault(clk)
    v.stash("r", old, subject=ALICE)
    assert v.state("r") == "awaiting_reauth"
    clk.advance(WAIT)
    assert v.state("r") == "session_expired"


def test_the_wait_setting_defaults_to_180_and_reads_the_environment(monkeypatch):
    from src.iagent.identity_vault import vault_reauth_wait_seconds
    monkeypatch.delenv("IDENTITY_REAUTH_WAIT_SECONDS", raising=False)
    assert vault_reauth_wait_seconds() == 180
    monkeypatch.setenv("IDENTITY_REAUTH_WAIT_SECONDS", "30")
    assert vault_reauth_wait_seconds() == 30
    monkeypatch.setenv("IDENTITY_REAUTH_WAIT_SECONDS", "0")
    assert vault_reauth_wait_seconds() == 1


def test_the_endpoint_answers_410_session_expired(client, fresh_vault):
    clk = _FakeClock()
    v = _vault(clk)
    gateway.VAULT = v
    v.stash(RUN, TOKEN, subject=ALICE)
    v.mark_awaiting_reauth(RUN, "x")
    _login("svc:supervisor")
    assert _redeem(client, "c1").status_code == 409
    clk.advance(WAIT)
    r = _redeem(client, "c2")
    assert r.status_code == 410
    d = r.json()["detail"]
    assert d["error"] == "session_expired" and d["run_id"] == RUN
    assert "asks again" in d["message"] and TOKEN not in r.text


# -- the supervisor's side ------------------------------------------------------------

def _scripted(monkeypatch, answers):
    posts, sleeps = [], []

    def _post(*a, **k):
        posts.append(1)
        status, cause = answers[min(len(posts) - 1, len(answers) - 1)]
        return _Resp(status, {"detail": {"error": cause, "message": "m"}})

    monkeypatch.setattr(ds.requests, "post", _post)
    monkeypatch.setattr(ds.time, "sleep", lambda s: sleeps.append(s))
    return posts, sleeps


def test_the_supervisor_waits_then_fails_at_once_on_session_expired(monkeypatch):
    posts, sleeps = _scripted(monkeypatch, [
        (409, "awaiting_reauth"), (409, "awaiting_reauth"), (410, "session_expired")])
    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_Ctx(), _Config())
    assert exc.value.cause == "session_expired"
    assert len(posts) == 3 and len(sleeps) == 2


def test_not_found_fails_at_once_with_no_wait(monkeypatch):
    posts, sleeps = _scripted(monkeypatch, [(404, "not_found")])
    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_Ctx(), _Config())
    assert exc.value.cause == "not_found"
    assert len(posts) == 1 and sleeps == []


def test_session_expired_has_a_sentence_that_says_to_ask_again():
    m = ds._CALLER_IDENTITY_MESSAGES["session_expired"]
    assert "ask the question again" in m.lower() and "expired" in m.lower()
