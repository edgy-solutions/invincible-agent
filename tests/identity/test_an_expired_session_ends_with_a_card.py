"""AN EXPIRED SESSION ENDS WITH A CARD THAT SAYS TO ASK AGAIN (architect, 2026-11-24).

A run paused for re-authentication whose wait ran out has a ``session_expired`` vault entry. When
that run then fails, the stream names the cause ``session_expired`` and, if the run made no card
of its own, delivers the sign-in-expired card. The run's own card is still preferred.

DRIVEN THROUGH THE REAL ``_generate_dagster_stream_inner`` (Dagster backend), reusing the harness
of tests/perf/test_a_failed_run_ends_with_a_card.py. The vault is real, on an injected clock.

Run:  uv run --frozen python -m pytest tests/identity/test_an_expired_session_ends_with_a_card.py -q
"""
from __future__ import annotations

import pytest

import iagent.gateway as gw
from iagent.identity_vault import IdentityVault
from tests.identity.test_identity_vault import _FakeClock
from tests.perf.test_a_failed_run_ends_with_a_card import (  # noqa: F401  (fixtures + helpers)
    ALICE, OWN, RUN, TRACE, _dagster, _drive, _of, _parse, base, stubbed_stream,
)

WAIT = 5


@pytest.fixture
def vault(monkeypatch):
    clk = _FakeClock()
    v = IdentityVault(clock=clk, wall_clock=lambda: 1000.0, reauth_wait_seconds=WAIT)
    monkeypatch.setattr(gw, "VAULT", v)
    return v, clk


def _script(monkeypatch, vault_and_clock, script):
    """Replace the run-status seam with ``script(n, vault, clock) -> status``."""
    v, clk = vault_and_clock
    box = {"polls": 0}

    async def _status(rid):
        box["polls"] += 1
        return {"status": script(box["polls"], v, clk)}

    monkeypatch.setattr(gw, "_get_run_status", _status)
    return box


def _pause_then_expire_then_fail(n, v, clk):
    if n == 1:
        v.mark_awaiting_reauth(RUN, "token_expired_and_not_refreshable")
    if n == 2:
        clk.advance(WAIT)  # the wait runs out; the next tick reads session_expired
    return "FAILURE" if n == 4 else "STARTED"


@pytest.mark.asyncio
async def test_an_expired_session_ends_with_the_sign_in_expired_card(base, vault, monkeypatch):
    _dagster(monkeypatch, status="STARTED")
    _script(monkeypatch, vault, _pause_then_expire_then_fail)
    blob = await _drive()
    pairs = _parse(blob)
    finals = _of(pairs, "final_payload")
    assert len(finals) == 1, blob
    md = finals[0]["components"][0]["markdown_content"]
    assert "Your sign-in expired" in md and "Ask the question again" in md and TRACE in md
    errs = _of(pairs, "pipeline_error")
    assert len(errs) == 1 and errs[0]["cause"] == "session_expired"
    assert errs[0]["trace_id"] == TRACE
    assert "ui_payload_timeout" not in blob
    assert "run_reauth_resumed" not in blob, "expiry is not a resume"


@pytest.mark.asyncio
async def test_a_session_that_expires_between_ticks_is_still_recognised_on_failure(
        base, vault, monkeypatch):
    def script(n, v, clk):
        if n == 1:
            v.mark_awaiting_reauth(RUN, "token_expired_and_not_refreshable")
        if n == 2:
            clk.advance(WAIT)  # expires during this very poll, which reports FAILURE
            return "FAILURE"
        return "STARTED"

    _dagster(monkeypatch, status="STARTED")
    _script(monkeypatch, vault, script)
    pairs = _parse(await _drive())
    assert _of(pairs, "pipeline_error")[0]["cause"] == "session_expired"
    md = _of(pairs, "final_payload")[0]["components"][0]["markdown_content"]
    assert "Your sign-in expired" in md


@pytest.mark.asyncio
async def test_the_runs_own_card_is_delivered_unchanged(base, vault, monkeypatch):
    _dagster(monkeypatch, status="STARTED", payload={"payload": OWN, "referenced_uris": []})
    _script(monkeypatch, vault, _pause_then_expire_then_fail)
    pairs = _parse(await _drive())
    assert _of(pairs, "final_payload") == [OWN]
    assert _of(pairs, "pipeline_error")[0]["cause"] == "session_expired"


@pytest.mark.asyncio
async def test_CONTROL_a_failure_with_no_pause_keeps_the_generic_card_and_the_paths_cause(
        base, vault, monkeypatch):
    _dagster(monkeypatch, status="FAILURE")
    pairs = _parse(await _drive())
    md = _of(pairs, "final_payload")[0]["components"][0]["markdown_content"]
    assert "The answer could not be completed" in md and "sign-in" not in md
    assert _of(pairs, "pipeline_error")[0]["cause"] == "dagster_run_failed"


@pytest.mark.asyncio
async def test_a_paused_run_the_stream_never_waits_for_for_ever(base, vault, monkeypatch):
    def script(n, v, clk):
        if n == 1:
            v.mark_awaiting_reauth(RUN, "token_expired_and_not_refreshable")
        clk.advance(1)  # one second per poll: the bound passes after WAIT polls
        return "STARTED"

    _dagster(monkeypatch, status="STARTED")
    box = _script(monkeypatch, vault, script)
    await _drive()
    assert 900 <= box["polls"] <= 900 + WAIT + 3, box["polls"]


def test_the_expired_card_unit():
    card = gw._failure_card("s", "t`x", session_expired=True)
    md = card["components"][0]["markdown_content"]
    assert md.startswith("# Your sign-in expired")
    assert "Ask the question again." in md and "Trace id: `tx`" in md
    assert "no trace id" in gw._failure_card(None, None, session_expired=True)[
        "components"][0]["markdown_content"]
    assert "could not be completed" in gw._failure_card("s", "t")["components"][0][
        "markdown_content"]
