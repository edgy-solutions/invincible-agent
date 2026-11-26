"""The subject, verb and slots legs join the run's trace, and speak with no new credential.

Architect ruling 2026-11-24: "The supervisor sends trace headers on the subject, verb and slots
calls, so they join the same trace as intent and plan."

THE HAZARD this file seals: `_telemetry_headers` mints a SERVICE token when no caller token is
given. These three legs sent a bearer only for a person's run; swapping in `_telemetry_headers`
would make them act as the service when no person is behind the run (the 2026-11-19 delegation
ruling forbids it). So each leg carries the trace names and the SAME Authorization as before.

Run:  uv run python -m pytest tests/routing/test_the_routing_legs_join_the_trace.py -q
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import httpx
import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402

TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE.signature"
TRACE = "trace-abc"
SESSION = "session-xyz"


class _Ctx:
    run_id = "run-1"

    def __init__(self):
        self.log = logging.getLogger("test.legs.context")

        class _Op:
            name = "execute_subtask"
        self.op = _Op()

    def get_mapping_key(self):
        return "task_0"

    def add_output_metadata(self, *_a, **_k):
        pass

    def log_event(self, *_a, **_k):
        pass


def _names():
    """The trace/session header NAMES, taken from `_telemetry_headers` itself (not retyped)."""
    stub = type("C", (), {"trace_id": "t", "session_id": "s"})()
    h = ds._telemetry_headers(stub, caller_token="x")
    trace = next(k for k, v in h.items() if v == "t")
    session = next(k for k, v in h.items() if v == "s")
    return trace, session


@pytest.fixture
def net(monkeypatch):
    calls: list[dict] = []

    def post(url, json=None, timeout=None, **kw):
        calls.append({"url": url, "kw": kw, "headers": kw.get("headers")})
        body = {"slots": {}} if url.endswith("/fill_slots") else {
            "resolved_uri": "UNKNOWN", "confidence": 0.0, "reasoning": "x", "verb_iri": "",
            "candidates": []}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(ds.requests, "post", post)

    def _no_mint(*_a, **_k):
        raise AssertionError("mint_supervisor_token was called: a leg acted as the service")

    monkeypatch.setattr("agent_fleet.utils.service_identity.mint_supervisor_token", _no_mint)
    monkeypatch.setattr(ds, "_caller_token_for", lambda _c, who, _leg: TOKEN if who else "")
    return calls


def _resolve(**kw):
    ds._resolve_subject(_Ctx(), "q", "MAINTENANCE", **kw)


def _classify(**kw):
    saved, saved_find = ds._resolve_subject, ds._find_compatible_verbs
    ds._resolve_subject = lambda *a, **k: ("urn:x:S", 0.9, "r", "", [], None, "", [])
    ds._find_compatible_verbs = lambda *a, **k: (
        [{"verb_iri": "urn:v:one", "required_args": []}], None)
    try:
        ds._classify_route(_Ctx(), "q", ["SUSTAINMENT"], "MAINTENANCE", **kw)
    finally:
        ds._resolve_subject, ds._find_compatible_verbs = saved, saved_find


def _fill(**kw):
    ds._fill_slots_from_query(_Ctx(), query="q", verb_iri="urn:v:one", declarations=[], **kw)


LEGS = [("/resolve", _resolve), ("/classify_predicate", _classify), ("/fill_slots", _fill)]
IDS = [leg for leg, _ in LEGS]


def _leg_call(net, fragment):
    got = [c for c in net if c["url"].endswith(fragment)]
    assert len(got) == 1, f"expected one {fragment} call, saw {[c['url'] for c in net]}"
    return got[0]


@pytest.mark.parametrize("fragment,drive", LEGS, ids=IDS)
def test_the_leg_sends_the_trace_and_session_names(net, fragment, drive):
    trace_h, session_h = _names()
    drive(user_email="alice@example.com", trace_id=TRACE, session_id=SESSION)
    h = _leg_call(net, fragment)["headers"]
    assert h[trace_h] == TRACE and h[session_h] == SESSION


@pytest.mark.parametrize("fragment,drive", LEGS, ids=IDS)
def test_a_trace_without_a_session_sends_only_the_trace(net, fragment, drive):
    trace_h, session_h = _names()
    drive(user_email="alice@example.com", trace_id=TRACE)
    h = _leg_call(net, fragment)["headers"]
    assert h[trace_h] == TRACE and session_h not in h


@pytest.mark.parametrize("fragment,drive", LEGS, ids=IDS)
def test_no_person_and_a_trace_sends_no_authorization_and_never_mints(net, fragment, drive):
    """THE DELEGATION SEAL: trace headers ride, a credential never appears for a run with no person."""
    trace_h, _ = _names()
    drive(user_email="", trace_id=TRACE, session_id=SESSION)
    h = _leg_call(net, fragment)["headers"]
    assert h[trace_h] == TRACE
    assert not any(k.lower() == "authorization" for k in h)
    assert not any(k.lower().startswith("x-auth-status") for k in h)


@pytest.mark.parametrize("fragment,drive", LEGS, ids=IDS)
def test_with_a_person_the_authorization_is_the_persons_bearer(net, fragment, drive):
    """The control for the seal above: the bearer is still sent, with the same value."""
    drive(user_email="alice@example.com", trace_id=TRACE, session_id=SESSION)
    h = _leg_call(net, fragment)["headers"]
    assert h["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("fragment,drive", LEGS, ids=IDS)
def test_with_a_person_and_no_trace_the_headers_are_the_bearer_alone(net, fragment, drive):
    drive(user_email="alice@example.com")
    assert _leg_call(net, fragment)["headers"] == {"Authorization": f"Bearer {TOKEN}"}


@pytest.mark.parametrize("fragment,drive", LEGS, ids=IDS)
def test_with_neither_the_call_has_no_headers_kwarg(net, fragment, drive):
    drive(user_email="")
    assert "headers" not in _leg_call(net, fragment)["kw"]
