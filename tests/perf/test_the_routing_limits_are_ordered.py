"""Routing an ask has two limits, and the inner one is the shorter.

perf's step 7 run (2026-11-28): cortex-bff gave up on engine O's /route_intent at 180 s while the
model call it waited on ran on (one took 204 s; BAML's own default lets a call run 300 s). The
architect: "The inner limit has to be shorter than the outer one, so a call can't finish after its
caller has gone. Set the order, and say which settings govern each."

- OUTER, `ROUTE_INTENT_TIMEOUT_S` (180 s): how long cortex-bff waits for /route_intent.
- INNER, `ROUTE_INTENT_MODEL_TIMEOUT_S` (150 s): how long engine O lets ExtractIntent run. It
  stops the model REQUEST (a BAML abort controller), not only engine O's wait: the in-flight
  coalescer shields the call, so cancelling an await would leave it running.

The chart refuses the wrong order (tests/perf/test_the_routing_limits_are_ordered_chart.py). The
same run's other defect, an ask that failed audited `completed`, is sealed here through the real
stream, and by frame in tests/routing/test_the_audit_line_says_an_ask_failed.py.

Run: uv run pytest tests/perf/test_the_routing_limits_are_ordered.py -q
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.perf import test_answer_admission as ta
from tests.perf.test_answer_admission import (  # noqa: F401
    _isolate_sdk_singletons, _plain_req, _stream, adm, gw, mesh_env, stubbed_stream)

_REPO = Path(__file__).resolve().parents[2]
AUDIT = "iagent.audit.orchestrate"


# the outer limit: cortex-bff --------------------------------------------------------------------


@pytest.mark.parametrize("env,want", [({}, 180.0), ({"ROUTE_INTENT_TIMEOUT_S": ""}, 180.0),
                                      ({"ROUTE_INTENT_TIMEOUT_S": "90"}, 90.0),
                                      ({"ROUTE_INTENT_TIMEOUT_S": "2.5"}, 2.5)])
def test_the_outer_limit_reads_its_setting(env, want):
    assert gw._route_intent_timeout_s(env) == want


@pytest.mark.parametrize("raw", ["0", "-5", "soon", "nan"])
def test_the_outer_limit_refuses_a_value_that_is_not_a_positive_number(raw):
    with pytest.raises(ValueError):
        gw._route_intent_timeout_s({"ROUTE_INTENT_TIMEOUT_S": raw})


class _TimedMesh(ta.Mesh):
    """The admission harness's mesh, also recording the timeout of the client that posts /route_intent."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.route_timeouts: list = []

    def client(self, *a, **k):
        mesh, timeout = self, k.get("timeout", a[0] if a else None)

        class _Timed(ta._MeshClient):
            async def post(self, url, **kw):
                if url.endswith("/route_intent"):
                    mesh.route_timeouts.append(timeout)
                return await super().post(url, **kw)
        return _Timed(self)


@pytest.fixture
def timed_mesh(mesh_env, monkeypatch):
    monkeypatch.setattr(ta, "Mesh", _TimedMesh)
    adm.reset_gate_for_tests(1, 1)
    return mesh_env


@pytest.mark.asyncio
async def test_the_bff_waits_for_route_intent_as_long_as_its_setting_says(timed_mesh, monkeypatch):
    monkeypatch.setattr(gw, "_ROUTE_INTENT_TIMEOUT_S", 37.0)
    m = timed_mesh()
    await _stream(m)
    assert m.route_timeouts == [37.0]


@pytest.mark.asyncio
async def test_control_the_default_wait_is_the_outer_default(timed_mesh):
    m = timed_mesh()
    await _stream(m)
    assert m.route_timeouts == [gw._route_intent_timeout_s({})] == [180.0]


# the audit line, through the real stream -----------------------------------------------------


async def _audited(caplog, mesh):
    caplog.set_level(logging.INFO, logger=AUDIT)
    agen = gw._audit_orchestrate_wrap(
        gw.generate_dagster_stream(_plain_req(), user_email="alice@example.com", trace_id=""),
        who="alice@example.com", via="cortex-ui", session_id="s-adm-2")
    blob = "".join([c async for c in agen])
    lines = [r.getMessage() for r in caplog.records
             if r.name == AUDIT and r.getMessage().startswith("orchestrate_access ")]
    return blob, lines


@pytest.mark.asyncio
async def test_an_ask_whose_routing_failed_is_audited_failed(timed_mesh, caplog):
    blob, lines = await _audited(caplog, timed_mesh(route_status=500))
    assert "route_intent_failed" in blob and "stream_end" in blob    # the case perf saw
    (line,) = lines
    assert " outcome=failed:route_intent_failed " in line + " ", line


# the inner limit: engine O ----------------------------------------------------------------------


@pytest.fixture
def eo(monkeypatch):
    mod = pytest.importorskip("agent_fleet.ontology_service.main",
                              reason="ontology_service not importable here")
    monkeypatch.setattr(mod, "ENABLE_AGENTIC_AUTH", False)
    return mod


@pytest.mark.parametrize("env,want", [({}, 150.0), ({"ROUTE_INTENT_MODEL_TIMEOUT_S": ""}, 150.0),
                                      ({"ROUTE_INTENT_MODEL_TIMEOUT_S": "60"}, 60.0)])
def test_the_inner_limit_reads_its_setting(eo, env, want):
    assert eo._route_intent_model_timeout_s(env) == want


@pytest.mark.parametrize("raw", ["0", "-1", "soon", "nan"])
def test_the_inner_limit_refuses_a_value_that_is_not_a_positive_number(eo, raw):
    with pytest.raises(ValueError):
        eo._route_intent_model_timeout_s({"ROUTE_INTENT_MODEL_TIMEOUT_S": raw})


def test_the_defaults_are_in_order(eo):
    assert eo._route_intent_model_timeout_s({}) < gw._route_intent_timeout_s({})


class _Rec:
    def __init__(self):
        self.kw = None

    async def ExtractIntent(self, **kw):  # noqa: N802
        self.kw = kw
        return SimpleNamespace(mode="ONE_SHOT", entity_refs=["pump"], confidence=0.9, reasoning="r")


def test_route_intent_hands_the_model_call_a_controller_set_to_the_inner_limit(eo, monkeypatch):
    from baml_py import AbortController  # noqa: PLC0415
    made = []

    def _spy(*a, **k):
        made.append(k.get("timeout_ms", a[0] if a else None))
        return AbortController(*a, **k)

    rec = _Rec()
    monkeypatch.setattr(eo, "b", rec)
    monkeypatch.setattr(eo, "AbortController", _spy)
    monkeypatch.setattr(eo, "_ROUTE_INTENT_MODEL_TIMEOUT_S", 42.5)
    out = asyncio.run(eo.route_intent(eo.RouteIntentRequest(query="how is the pump doing")))
    assert out.mode == "ONE_SHOT"
    assert made == [42500]
    assert isinstance(rec.kw["baml_options"]["abort_controller"], AbortController)
    assert rec.kw["user_query"] == "how is the pump doing"


async def _silent_model(eo, limit_s):
    """route_intent against a model endpoint that accepts and never answers (a local socket; no
    model anywhere), through engine O's own wrapping: (elapsed, HTTPException, socket events)."""
    from baml_py import ClientRegistry  # noqa: PLC0415
    sys.path.insert(0, str(_REPO / "baml_shared" / "baml_client"))
    from baml_client import b as raw  # noqa: PLC0415
    events = []

    async def handle(reader, writer):
        events.append("accept")
        try:
            while await reader.read(1 << 16):
                pass
        except Exception:  # noqa: BLE001
            pass
        events.append("closed")

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    cr = ClientRegistry()
    cr.add_llm_client(name="Ollama", provider="openai", options={
        "base_url": f"http://127.0.0.1:{port}/v1", "api_key": "x", "model": "m", "temperature": 0})
    cr.add_llm_client(name="MainAgent", provider="fallback", options={"strategy": ["Ollama"]})
    cr.set_primary("MainAgent")
    eo.b = eo.CoalescingClient(eo.GenerationRecordingClient(raw.with_options(client_registry=cr)))
    eo._ROUTE_INTENT_MODEL_TIMEOUT_S = limit_s
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(eo.route_intent(eo.RouteIntentRequest(query="q")), limit_s + 10)
        raise AssertionError("route_intent answered from a socket that never replies")
    except HTTPException as exc:
        err = exc
    elapsed = time.monotonic() - t0
    for _ in range(40):
        if "closed" in events:
            break
        await asyncio.sleep(0.05)
    server.close()
    return elapsed, err, events


@pytest.mark.parametrize("limit_s", [0.5, 2.0])
def test_the_inner_limit_stops_the_model_request_itself(eo, monkeypatch, limit_s):
    monkeypatch.setattr(eo, "b", eo.b)                                 # restored after
    monkeypatch.setattr(eo, "_ROUTE_INTENT_MODEL_TIMEOUT_S", eo._ROUTE_INTENT_MODEL_TIMEOUT_S)
    elapsed, err, events = asyncio.run(_silent_model(eo, limit_s))
    assert err.status_code == 502
    assert f"ROUTE_INTENT_MODEL_TIMEOUT_S={limit_s:g} s" in err.detail, err.detail
    # it ends AT the limit (both arms: the time follows the setting, not a connection error) ...
    assert 0.9 * limit_s <= elapsed < limit_s + 1.5, elapsed
    # ... and the request was stopped: the model's socket saw the client hang up
    assert events == ["accept", "closed"], events
