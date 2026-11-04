"""WHAT A PAUSED RUN SAYS (cortex-ui docs/specs/run-reauth-card.md, names AGREED 2026-11-03).

A run paused as ``awaiting_reauth`` carries ``paused_call`` and ``instruction`` beside
``run_id`` and ``reason``, in the ``run_awaiting_reauth`` event and in ``GET /me/paused-runs``.
Neither holds a token. A resume clears them.

Run:  .venv/Scripts/python -X utf8 -m pytest tests/identity/test_a_paused_run_says_what_it_needs.py -c pyproject.toml --rootdir=.
"""
from __future__ import annotations

import json
import re

import pytest

from src.iagent import gateway
from src.iagent import identity_exchange
from tests.identity.test_redemption_endpoint import (  # noqa: F401  (fixtures + helpers)
    ALICE, RUN, TOKEN, _NOW, _jwt, _login, _near_expiry_vault, _redeem, _reauth_as,
    client, fresh_vault, seam_unset,
)
from tests.identity.test_the_stream_pauses_for_the_person import (  # noqa: F401
    FRESH, RUN as STREAM_RUN, _drive, harness, stubbed_stream,
)

PAUSED_CALL = "The 'dispatch' call made on your behalf"
INSTRUCTION = "Sign in again to continue this run."
FIELDS = {"run_id", "paused_call", "instruction", "reason"}


def _pause_through_the_route(client, monkeypatch, leg="dispatch"):
    """The real call site: a near-expiry token, no exchange seam, a supervisor redemption."""
    monkeypatch.setattr(identity_exchange.time, "time", lambda: _NOW)
    old = _jwt(exp=_NOW + 10, tag="old")
    v = _near_expiry_vault(old)
    _login("svc:supervisor")
    assert _redeem(client, "c1", leg=leg).status_code == 409
    return v, old


# ── the event ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_event_carries_paused_call_and_instruction(harness):
    v = harness["vault"]

    def script(n):
        if n == 1:
            v.mark_awaiting_reauth(STREAM_RUN, "token_near_expiry_and_not_refreshable",
                                   PAUSED_CALL, INSTRUCTION)
        if n == 30:
            return {"status": "CANCELED"}
        return {"status": "STARTED"}

    harness["script"] = script
    blob = await _drive(harness)
    datas = re.findall(r"event: run_awaiting_reauth\ndata: (.*)\n", blob)
    assert len(datas) == 1, (harness["polls"], re.findall(r"event: (w+)", blob))
    data = json.loads(datas[0])
    assert data == {"run_id": STREAM_RUN, "reason": "token_near_expiry_and_not_refreshable",
                    "paused_call": PAUSED_CALL, "instruction": INSTRUCTION}
    assert "ALICE-STREAM" not in blob


# ── the read ─────────────────────────────────────────────────────────────────────────

def test_the_owner_sees_the_record_and_it_names_the_call(client, monkeypatch):
    _pause_through_the_route(client, monkeypatch)
    _login(ALICE)
    r = client.get("/me/paused-runs")
    assert r.status_code == 200
    assert r.json() == {"paused": [{
        "run_id": RUN, "paused_call": PAUSED_CALL, "instruction": INSTRUCTION,
        "reason": "token_near_expiry_and_not_refreshable"}]}


def test_another_person_gets_an_empty_list(client, monkeypatch):
    _pause_through_the_route(client, monkeypatch)
    _login("mallory@example.com")
    r = client.get("/me/paused-runs")
    assert r.status_code == 200 and r.json() == {"paused": []}


def test_a_service_token_is_refused_403(client, monkeypatch):
    _pause_through_the_route(client, monkeypatch)
    _login("svc:supervisor")
    r = client.get("/me/paused-runs")
    assert r.status_code == 403
    assert r.json()["detail"] == {"error": "service_token_refused", "authz_id": "svc:supervisor"}


def test_nothing_paused_is_an_empty_200(client, fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)  # live, not paused
    _login(ALICE)
    r = client.get("/me/paused-runs")
    assert r.status_code == 200 and r.json() == {"paused": []}


def test_after_a_resume_the_list_is_empty_and_the_text_is_gone(client, monkeypatch):
    v, _ = _pause_through_the_route(client, monkeypatch)
    _reauth_as(ALICE, _jwt(exp=_NOW + 3600, tag="fresh"))
    assert client.post(f"/orchestrate/{RUN}/reauth").status_code == 200
    _login(ALICE)
    assert client.get("/me/paused-runs").json() == {"paused": []}
    # cleared at the entry too, not only hidden by the state filter
    assert v._entries[RUN].paused_call == "" and v._entries[RUN].instruction == ""


def test_a_second_pause_does_not_inherit_the_first_ones_text(fresh_vault):
    fresh_vault.stash(RUN, TOKEN, subject=ALICE)
    fresh_vault.mark_awaiting_reauth(RUN, "r", PAUSED_CALL, INSTRUCTION)
    assert fresh_vault.replace(RUN, FRESH, ALICE)
    fresh_vault.mark_awaiting_reauth(RUN, "r2")
    assert fresh_vault.pause_record(RUN) == {
        "run_id": RUN, "paused_call": "", "instruction": "", "reason": "r2"}


# ── no secret ────────────────────────────────────────────────────────────────────────

def test_no_field_of_the_record_holds_the_token(client, monkeypatch):
    v, old = _pause_through_the_route(client, monkeypatch)
    _login(ALICE)
    body = client.get("/me/paused-runs")
    rec = body.json()["paused"][0]
    assert set(rec) == FIELDS
    for text in (body.text, json.dumps(v.pause_record(RUN))):
        assert old not in text
        assert old.split(".")[1] not in text  # nor its payload segment
