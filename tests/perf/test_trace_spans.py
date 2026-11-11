"""lane/perf (#327): spans for the BFF, the supervisor and engine-docs /explain on
provenance-telemetry 0.2.1. In-memory exporter throughout; no network."""
from __future__ import annotations

import ast
import asyncio
import inspect
import itertools
import re
import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "src"), str(ROOT / "baml_shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iagent import trace_spans as ts  # noqa: E402

_n = itertools.count()
PARENT = "00f067aa0ba902b7"


@pytest.fixture(autouse=True)
def _isolate_sdk_singletons():
    from langfuse._client.resource_manager import LangfuseResourceManager
    LangfuseResourceManager.reset()
    yield
    LangfuseResourceManager.reset()


@pytest.fixture
def mem(monkeypatch):
    from langfuse import Langfuse
    exp = InMemorySpanExporter()
    pk = f"pk-test-327-{next(_n)}"
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", pk)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("DEPLOY_ENV", raising=False)
    client = Langfuse(public_key=pk, secret_key="sk-test", base_url="http://localhost:1",
                      span_exporter=exp)
    yield client, exp


def spans_of(client, exp):
    client.flush()
    return exp.get_finished_spans()


def one(spans, name):
    found = [s for s in spans if s.name == name]
    assert len(found) == 1, [s.name for s in spans]
    return found[0]


class Cfg:
    def __init__(self, trace_id="", parent_span_id="", session_id=""):
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.session_id = session_id


@pytest.fixture
def flushes(monkeypatch):
    calls = []
    monkeypatch.setattr(ts, "flush", lambda *a, **k: calls.append(1))
    return calls


# 1. request_trace_id ------------------------------------------------------------------

def test_request_trace_id_keeps_a_header_and_mints_otherwise():
    assert ts.request_trace_id("abc-123") == "abc-123"
    seen = set()
    for v in (None, "", "  "):
        minted = ts.request_trace_id(v)
        assert re.fullmatch(r"[0-9a-f]{32}", minted), minted
        seen.add(minted)
    assert len(seen) == 3
    assert ts.request_trace_id(None) != ts.request_trace_id(None)


# 2. mint seal -------------------------------------------------------------------------

def test_orchestrate_mints_through_request_trace_id():
    from iagent import gateway
    src = inspect.getsource(gateway.orchestrate)
    assert "request_trace_id(" in src
    assert 'headers.get("X-Trace-Id", "")' not in src


# 3/4. the BFF span through the keepalive ------------------------------------------------

def _make_inner(seen):
    async def inner():
        seen.append(ts.current_span_id())
        for i in range(3):
            await asyncio.sleep(0)
            yield i
    return inner


def test_bff_span_spans_the_stream_through_keepalive(mem):
    from iagent import gateway
    client, exp = mem
    seen: list = []
    from telemetry import emit_misses
    before = emit_misses()

    async def run():
        return [e async for e in gateway._traced_stream(
            gateway._keepalive_wrap(_make_inner(seen)()),
            trace_id="t-1", session_id="s", authz_id="u")]

    events = asyncio.run(run())
    spans = spans_of(client, exp)
    span = one(spans, "bff.orchestrate")
    assert events == [0, 1, 2]
    assert span.parent is None
    assert span.context.trace_id == int(client.create_trace_id(seed="t-1"), 16)
    assert seen == [format(span.context.span_id, "016x")]
    assert emit_misses() == before


def test_bff_span_survives_a_disconnect(mem):
    from iagent import gateway
    from telemetry import emit_misses
    client, exp = mem
    before = emit_misses()
    seen: list = []

    async def run():
        gen = gateway._traced_stream(
            gateway._keepalive_wrap(_make_inner(seen)()),
            trace_id="t-1", session_id="s", authz_id="u")
        first = await gen.__anext__()
        await gen.aclose()
        return first

    asyncio.run(run())
    assert one(spans_of(client, exp), "bff.orchestrate") is not None
    assert emit_misses() == before


# 5-8. step_spanned ---------------------------------------------------------------------

def _headers(cfg):
    from iagent.defs import dynamic_supervisor as ds
    return ds._telemetry_headers(cfg, caller_token="tok")  # a caller token: no mint, no network


def test_step_spanned_positive(mem, flushes):
    client, exp = mem

    @ts.step_spanned("supervisor.x")
    def op(context, config):
        return _headers(config)

    headers = op(None, Cfg("t-2", PARENT, "s"))
    span = one(spans_of(client, exp), "supervisor.x")
    assert span.parent.span_id == int(PARENT, 16)
    assert span.context.trace_id == int(client.create_trace_id(seed="t-2"), 16)
    assert headers["X-Trace-Id"] == "t-2"
    assert headers["X-Parent-Span-Id"] == format(span.context.span_id, "016x")
    assert len(flushes) == 1


def test_step_spanned_without_a_trace_id_is_a_straight_call(mem, flushes):
    client, exp = mem

    @ts.step_spanned("supervisor.x")
    def op(context, config):
        return ("ran", _headers(config))

    out, headers = op(None, config=Cfg(""))
    assert out == "ran"
    assert "X-Parent-Span-Id" not in headers
    assert spans_of(client, exp) == ()
    assert flushes == []


def test_step_spanned_generator_runs_inside_the_span(mem, flushes):
    client, exp = mem
    seen = []

    @ts.step_spanned("supervisor.g")
    def gen(context, config):
        for i in range(3):
            seen.append(ts.current_span_id())
            yield i

    assert list(gen(None, Cfg("t-4", PARENT))) == [0, 1, 2]
    span = one(spans_of(client, exp), "supervisor.g")
    assert seen == [format(span.context.span_id, "016x")] * 3
    assert len(flushes) == 1


def test_step_spanned_exception_propagates_marked_error(mem, flushes):
    client, exp = mem

    @ts.step_spanned("supervisor.boom")
    def op(context, config):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        op(None, Cfg("t-5", PARENT))
    span = one(spans_of(client, exp), "supervisor.boom")
    assert span.status.status_code == StatusCode.ERROR
    assert len(flushes) == 1


# 9. the four real ops ------------------------------------------------------------------

OPS = ("create_task_plan", "execute_subtask", "synthesize_stateful", "generate_ui_payload")


def test_the_four_real_ops_are_spanned_and_keep_their_shape():
    from iagent.defs import dynamic_supervisor as ds
    for name in OPS:
        fn = getattr(ds, name).compute_fn.decorated_fn
        assert fn.__name__ == name and hasattr(fn, "__wrapped__")
        assert inspect.unwrap(fn) is not fn
        assert inspect.signature(fn) == inspect.signature(fn.__wrapped__)
    names = {n.name for n in ds.supervisor_query_job.graph.node_defs}
    assert set(OPS) <= names
    plan = ds.create_task_plan.compute_fn.decorated_fn
    assert inspect.isgeneratorfunction(plan) and inspect.isgeneratorfunction(plan.__wrapped__)
    assert not inspect.isgeneratorfunction(ds.execute_subtask.compute_fn.decorated_fn)
    assert ds.SupervisorQueryConfig(user_query="q", thread_id="t").parent_span_id == ""


# 10. engine-docs /explain --------------------------------------------------------------

def test_engine_docs_explain_span(mem, monkeypatch):
    from fastapi.testclient import TestClient
    import agent_fleet.docs_agent.main as m
    # the binding must hold the SAME shim object this test reads through
    monkeypatch.setattr(m, "observed_trace", ts.observed_trace)
    monkeypatch.setattr(m, "MAPPING", ts.MAPPING)
    monkeypatch.setattr(m, "build_trace_values", ts.build_trace_values)
    client, exp = mem
    http = TestClient(m.app)
    body = {"fn": "explain", "params": {"subject": "x"}}

    http.post("/explain", json=body,
              headers={"X-Trace-Id": "t-3", "X-Parent-Span-Id": PARENT})
    span = one(spans_of(client, exp), "engine-docs.explain")
    assert span.parent.span_id == int(PARENT, 16)
    assert span.context.trace_id == int(client.create_trace_id(seed="t-3"), 16)

    exp.clear()
    http.post("/explain", json=body)
    assert spans_of(client, exp) == ()
    http.get("/health", headers={"X-Trace-Id": "t-3"})
    assert spans_of(client, exp) == ()


# 11. taxonomy census -------------------------------------------------------------------

def _span_names_in(source: str) -> set:
    found = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        fname = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
        if fname == "observed_trace":
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    found.add(kw.value.value)
        elif fname == "step_spanned" and node.args and isinstance(node.args[0], ast.Constant):
            found.add(node.args[0].value)
    return found


SOURCES = ("src/iagent/gateway.py", "src/iagent/defs/dynamic_supervisor.py",
           "agent_fleet/docs_agent/main.py")


def test_every_emitted_span_name_is_declared():
    from span_taxonomy import SPAN_NAMES, declared
    assert SPAN_NAMES, "taxonomy failed to load"
    used = set()
    for rel in SOURCES:
        used |= _span_names_in((ROOT / rel).read_text(encoding="utf-8"))
    assert len(used) >= 6, used
    assert [n for n in used if not declared(n)] == []
    for spec in SPAN_NAMES.values():
        assert spec["kind"] in {"request", "stage", "hop", "llm", "store"} and spec["service"]


def test_the_scanner_finds_an_undeclared_name():
    from span_taxonomy import declared
    found = _span_names_in('observed_trace(M, v, name="undeclared.x")\n@step_spanned("undeclared.y")\ndef f(): pass\n')
    assert found == {"undeclared.x", "undeclared.y"}
    assert not any(declared(n) for n in found)


def test_taxonomy_loader_is_fail_soft(monkeypatch, tmp_path):
    import span_taxonomy
    monkeypatch.setattr(span_taxonomy, "_PATH", str(tmp_path / "missing.yaml"))
    assert span_taxonomy._load() == {}


# 12. pin census ------------------------------------------------------------------------

_PIN = re.compile(r'"provenance-telemetry([^"]*)"')


def _pins(text: str) -> list:
    return _PIN.findall(text)


def test_every_pyproject_pins_provenance_telemetry_0_2_1():
    files = [ROOT / "pyproject.toml", *sorted((ROOT / "agent_fleet").glob("*/pyproject.toml"))]
    pinned = {}
    for f in files:
        pins = _pins(f.read_text(encoding="utf-8"))
        if pins:
            pinned[f] = pins
    assert len(pinned) >= 8, sorted(str(p) for p in pinned)
    assert {f: p for f, p in pinned.items() if p != ["==0.2.1"]} == {}


def test_the_pin_scanner_sees_a_stale_pin():
    assert _pins('dependencies = ["provenance-telemetry==0.2.0"]') == ["==0.2.0"]
