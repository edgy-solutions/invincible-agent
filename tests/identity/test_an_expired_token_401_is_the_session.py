"""AN ENGINE'S 401 FOR AN EXPIRED TOKEN IS NAMED AS THE SESSION, NOT AS AN OUTAGE (2026-11-24).

Today a non-refusal 401 goes through ``raise_for_status`` and reads ``engine_unreachable``. When
the caller token the call carried is itself past its ``exp``, the engine did answer, and the
honest name is the expired session. A live token, or no token, is unchanged; a refusal-bearing
401 still travels as a refusal.

Run:  uv run --frozen python -m pytest tests/identity/test_an_expired_token_401_is_the_session.py -q
"""
from __future__ import annotations

import base64
import json as _json
import time

import pytest

from src.iagent.defs import dynamic_supervisor as ds
from tests.test_the_supervisor_relays_an_engine_refusal import (  # noqa: F401
    _Ctx, _refusal_body, _response, _returning,
)

SERVICE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.SVC-SUPERVISOR.signature"


def _jwt(exp):
    def b(o):
        return base64.urlsafe_b64encode(_json.dumps(o).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'none'})}.{b({'exp': exp})}.sig"


def _drive(monkeypatch, post, caller_token, *, person="alice@example.com"):
    monkeypatch.setattr(
        "agent_fleet.utils.service_identity.mint_supervisor_token",
        lambda *a, **k: SERVICE_TOKEN, raising=False,
    )
    monkeypatch.setattr(ds, "_redeem_caller_token", lambda *a, **k: caller_token)
    monkeypatch.setattr(ds, "_classify_route", lambda *a, **k: (
        ds._ROUTING_MATCHED,
        {"verb_iri": "mesh:queryKnowledgeGraph", "endpoint": "http://engine-e/q",
         "owner_persona": "AUDITOR", "domains": ["MAINTENANCE"], "score": 0.99},
        {},
    ))
    monkeypatch.setattr(ds.requests, "post", post)
    config = ds.SupervisorQueryConfig(
        user_query="q", user_email=person, user_persona="AUDITOR",
        entitled_domains=["MAINTENANCE"], thread_id="t", trace_id="tr", session_id="s",
    )
    return ds.execute_subtask.compute_fn.decorated_fn(_Ctx(), config, {"sub_query": "q"})


def _plain_401():
    return _response(401, {"detail": "Token expired"})


def test_a_401_with_an_expired_caller_token_is_the_session(monkeypatch):
    er = _drive(monkeypatch, _returning(_plain_401()),
                _jwt(time.time() - 30))["expert_response"]
    assert er["status"] == "caller_identity_unavailable"
    assert er["reason"] == "session_expired"
    assert er["message"] == ds._CALLER_IDENTITY_MESSAGES["session_expired"]


def test_CONTROL_a_401_with_a_live_caller_token_is_unchanged(monkeypatch):
    er = _drive(monkeypatch, _returning(_plain_401()),
                _jwt(time.time() + 600))["expert_response"]
    assert er["status"] == "engine_unreachable" and er["reason"] == "transport_failure"


def test_CONTROL_a_401_with_no_caller_token_is_unchanged(monkeypatch):
    er = _drive(monkeypatch, _returning(_plain_401()), "", person="")["expert_response"]
    assert er["status"] == "engine_unreachable"


def test_CONTROL_a_non_401_with_an_expired_token_is_unchanged(monkeypatch):
    er = _drive(monkeypatch, _returning(_response(500, {"detail": "boom"})),
                _jwt(time.time() - 30))["expert_response"]
    assert er["status"] == "engine_unreachable"


def test_a_401_refusal_with_an_expired_token_still_travels_as_a_refusal(monkeypatch):
    er = _drive(monkeypatch, _returning(_response(401, _refusal_body())),
                _jwt(time.time() - 30))["expert_response"]
    assert er["refused"] is True and er.get("status") != "caller_identity_unavailable"
