"""The run's own trace and session reach the subject, verb and slots legs, from the config.

Seals the path from the run's config to the three legs (gov on #544: mutants Q9, Q10 and Q11
survived). `test_the_routing_legs_join_the_trace.py` drives each leg directly, handing it the
trace; this file starts from a real `SupervisorQueryConfig` carrying the trace and drives the
real `execute_subtask` body, so the hand-offs between the op and `_classify_route`, between
`_classify_route` and `_resolve_subject`, and between the op and `_fill_slots_from_query` are
all exercised unstubbed. Only the network and the compat-walk are doubled.

Run:  uv run python -m pytest tests/routing/test_the_runs_trace_reaches_the_three_legs.py -q
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
TRACE = "trace-from-the-run"
SESSION = "session-from-the-run"
VERB = "urn:v:one"


class _Stop(BaseException):
    """Ends the run right after the slot filler."""


class _Ctx:
    run_id = "run-1"

    def __init__(self):
        self.log = logging.getLogger("test.runs.trace.context")

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


_SLOT = {"name": "part", "type": "string", "required": True}


@pytest.fixture
def run(monkeypatch):
    calls: list[dict] = []

    def post(url, json=None, timeout=None, **kw):
        calls.append({"url": url, "headers": kw.get("headers") or {}})
        if url.endswith("/resolve"):
            body = {"resolved_uri": "urn:x:Subject", "confidence_score": 0.95,
                    "reasoning": "r", "provenance": {}, "candidates": []}
        elif url.endswith("/classify_predicate"):
            body = {"resolved_verb_iri": VERB, "confidence_score": 0.95, "reasoning": "r",
                    "classify_called": True, "candidate_verb_iris": [VERB],
                    "predicate": {"verb_iri": VERB, "endpoint": "http://engine.invalid/x",
                                  "domains": ["MAINTENANCE"]}}
        elif url.endswith("/fill_slots"):
            body = {"slots": {}}
        else:
            raise _Stop(f"unexpected POST {url}")
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    def _no_mint(*_a, **_k):
        raise AssertionError("mint_supervisor_token was called: a leg acted as the service")

    def _stop(*_a, **_k):
        raise _Stop("after the filler")

    monkeypatch.setattr(ds.requests, "post", post)
    monkeypatch.setattr("agent_fleet.utils.service_identity.mint_supervisor_token", _no_mint)
    monkeypatch.setattr(ds, "_caller_token_for", lambda _c, who, _leg: TOKEN if who else "")
    monkeypatch.setattr(ds, "_find_compatible_verbs", lambda *a, **k: (
        [{"verb_iri": VERB, "endpoint_url": "http://engine.invalid/x",
          "domains": ["MAINTENANCE"], "required_args": [], "slots": [_SLOT]}], None))
    monkeypatch.setattr(ds, "_log_subtask_route_assets", lambda *a, **k: None)
    monkeypatch.setattr(ds, "accept_slots", _stop)

    config = ds.SupervisorQueryConfig(
        user_query="how concentrated is purchasing on lot 4",
        user_email="alice@example.com",
        entitled_domains=["MAINTENANCE"],
        thread_id="thread-1",
        trace_id=TRACE,
        session_id=SESSION,
    )
    task = {"sub_query": "how concentrated is purchasing on lot 4"}
    try:
        ds.execute_subtask.compute_fn.decorated_fn(_Ctx(), config, task)
    except _Stop:
        pass
    return calls


@pytest.mark.parametrize("fragment", ["/resolve", "/classify_predicate", "/fill_slots"])
def test_the_runs_trace_and_session_reach_the_leg(run, fragment):
    trace_h, session_h = _names()
    got = [c for c in run if c["url"].endswith(fragment)]
    assert len(got) == 1, f"expected one {fragment} call, saw {[c['url'] for c in run]}"
    h = got[0]["headers"]
    assert h.get(trace_h) == TRACE, f"{fragment}: the run's trace id did not arrive"
    assert h.get(session_h) == SESSION, f"{fragment}: the run's session id did not arrive"
