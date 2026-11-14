"""lane/perf: trace headers on the BFF's /route_intent hop, engine-o's parent span, and a
generation observation per analyst model call. In-memory exporter; no network."""
from __future__ import annotations

import ast
import asyncio
import itertools
import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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
    pk = f"pk-test-ri-{next(_n)}"
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", pk)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("DEPLOY_ENV", raising=False)
    client = Langfuse(public_key=pk, secret_key="sk-test", base_url="http://localhost:1",
                      span_exporter=exp)
    yield client, exp


def spans_of(client, exp):
    client.flush()
    return exp.get_finished_spans()


def named(spans, name):
    return [s for s in spans if s.name == name]


def _gateway_trace_headers():
    import iagent.gateway as gw
    return gw._trace_headers


def _span(name="outer"):
    return ts.observed_trace(ts.MAPPING, ts.build_trace_values(trace_id="t-ri"), name=name)


# 1. _trace_headers ---------------------------------------------------------------------

def test_trace_headers_all_three(mem):
    th = _gateway_trace_headers()
    with _span():
        sid = ts.current_span_id()
        h = th("t-ri", "sess-1")
    assert len(sid) == 16
    assert h == {"X-Trace-Id": "t-ri", "X-Parent-Span-Id": sid, "X-Session-Id": "sess-1"}


def test_trace_headers_no_trace_id_is_empty_even_in_span(mem):
    th = _gateway_trace_headers()
    with _span():
        assert th("") == {}
        assert th("", "") == {}


def test_trace_headers_no_ambient_span_no_parent(mem):
    h = _gateway_trace_headers()("t-ri")
    assert h == {"X-Trace-Id": "t-ri"}


# 2. call-site seal ---------------------------------------------------------------------

def _route_intent_posts(source: str) -> list:
    out = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "post" and node.args):
            continue
        a0 = node.args[0]
        if (isinstance(a0, ast.JoinedStr) and a0.values
                and isinstance(a0.values[-1], ast.Constant)
                and str(a0.values[-1].value).endswith("/route_intent")):
            out.append(node)
    return out


def _has_trace_headers(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "headers" and isinstance(kw.value, ast.Call):
            f = kw.value.func
            if (f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)) == "_trace_headers":
                return True
    return False


def test_route_intent_post_sends_trace_headers():
    posts = _route_intent_posts((ROOT / "src/iagent/gateway.py").read_text(encoding="utf-8"))
    assert len(posts) == 1
    assert _has_trace_headers(posts[0])


def test_route_intent_scanner_reports_missing_headers():
    snippet = 'async def f(c):\n    await c.post(f"{U}/route_intent", json={})\n'
    posts = _route_intent_posts(snippet)
    assert len(posts) == 1 and not _has_trace_headers(posts[0])


# 3. engine-o middleware ----------------------------------------------------------------

class _Req:
    def __init__(self, headers):
        self.headers = headers

        class _U:
            path = "/route_intent"
        self.url = _U()


def _run_join(m, headers):
    async def call_next(_r):
        return "ok"
    return asyncio.run(m._telemetry_join(_Req(headers), call_next))


def test_engine_o_joins_callers_parent(mem, monkeypatch):
    import agent_fleet.ontology_service.main as m
    monkeypatch.setattr(m, "observed_trace", ts.observed_trace)
    monkeypatch.setattr(m, "MAPPING", ts.MAPPING)
    monkeypatch.setattr(m, "build_trace_values", ts.build_trace_values)
    client, exp = mem
    assert _run_join(m, {"X-Trace-Id": "t-ri", "X-Parent-Span-Id": PARENT}) == "ok"
    spans = named(spans_of(client, exp), "engine-o /route_intent")
    assert len(spans) == 1
    assert spans[0].parent.span_id == int(PARENT, 16)
    exp.clear()
    assert _run_join(m, {}) == "ok"
    assert spans_of(client, exp) == ()


# 4. instrument_model_calls -------------------------------------------------------------

class _Usage:
    input_tokens = 11
    output_tokens = 7


class _Msg:
    token_usage = _Usage()


class FakeModel:
    model_id = "fake-model-1"

    def __init__(self):
        self.result = _Msg()

    def generate(self, messages, **kw):
        return self.result


class BoomModel(FakeModel):
    def generate(self, messages, **kw):
        raise ValueError("boom")


def test_model_call_is_a_generation_with_usage(mem):
    client, exp = mem
    model = ts.instrument_model_calls(FakeModel(), name="analyst.model")
    with _span("outer"):
        outer_id = int(ts.current_span_id(), 16)
        res = model.generate([{"role": "user", "content": "secret prompt"}])
    assert res is model.result
    gens = named(spans_of(client, exp), "analyst.model")
    assert len(gens) == 1
    a = dict(gens[0].attributes or {})
    assert a["langfuse.observation.type"] == "generation"
    usage = str(a["langfuse.observation.usage_details"])
    assert "11" in usage and "7" in usage
    assert a.get("langfuse.observation.model.name") == "fake-model-1"
    assert not [k for k in a if k.startswith(("langfuse.observation.input",
                                               "langfuse.observation.output"))]
    assert "secret prompt" not in repr(a)
    assert gens[0].parent.span_id == outer_id


def test_model_exception_propagates_and_span_ended(mem):
    client, exp = mem
    model = ts.instrument_model_calls(BoomModel(), name="analyst.model")
    with _span("outer"):
        with pytest.raises(ValueError):
            model.generate([])
    gens = named(spans_of(client, exp), "analyst.model")
    assert len(gens) == 1 and gens[0].end_time is not None


def test_telemetry_failure_never_breaks_the_call(mem, monkeypatch):
    import langfuse
    model = ts.instrument_model_calls(FakeModel(), name="analyst.model")

    def _boom(*_a, **_k):
        raise RuntimeError("no client")
    monkeypatch.setattr(langfuse, "get_client", _boom)
    assert model.generate([]) is model.result


def test_disabled_returns_model_untouched(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    m = FakeModel()
    out = ts.instrument_model_calls(m)
    assert out is m and "generate" not in vars(m)


def test_instrumenting_twice_does_not_double_wrap(mem):
    client, exp = mem
    model = ts.instrument_model_calls(FakeModel(), name="analyst.model")
    model = ts.instrument_model_calls(model, name="analyst.model")
    with _span("outer"):
        model.generate([])
    assert len(named(spans_of(client, exp), "analyst.model")) == 1


def test_generation_nests_across_to_thread(mem):
    client, exp = mem
    model = ts.instrument_model_calls(FakeModel(), name="analyst.model")

    async def go():
        with _span("outer"):
            oid = int(ts.current_span_id(), 16)
            await asyncio.to_thread(model.generate, [])
        return oid
    oid = asyncio.run(go())
    gens = named(spans_of(client, exp), "analyst.model")
    assert len(gens) == 1 and gens[0].parent.span_id == oid


# 5. taxonomy ---------------------------------------------------------------------------

def test_analyst_model_declared():
    from span_taxonomy import SPAN_NAMES, declared
    assert declared("analyst.model")
    assert SPAN_NAMES["analyst.model"] == {"kind": "llm", "service": "restate-analyst"}


# 6. wiring seal ------------------------------------------------------------------------

def test_analyst_instruments_model_before_agent():
    src = (ROOT / "agent_fleet/restate_analyst/main.py").read_text(encoding="utf-8")
    g = src.index("model = get_smolagent_model()")
    a = src.index("ToolCallingAgent(tools=all_tools, model=model)", g)
    assert "model = instrument_model_calls(model" in src[g:a]


class _DeltaUsage:
    def __init__(self, i, o):
        self.input_tokens, self.output_tokens = i, o


class _Delta:
    def __init__(self, i, o):
        self.token_usage = _DeltaUsage(i, o)


class StreamModel(FakeModel):
    def generate_stream(self, messages, **kw):
        # Each delta carries its own share; smolagents sums them.
        yield _Delta(5, 2)
        yield _Delta(6, 5)


def test_stream_usage_accumulates_across_deltas(mem):
    import json
    client, exp = mem
    model = ts.instrument_model_calls(StreamModel(), name="analyst.model")
    with _span("outer"):
        items = list(model.generate_stream([{"role": "user", "content": "x"}]))
    assert len(items) == 2
    gens = named(spans_of(client, exp), "analyst.model")
    assert len(gens) == 1
    usage = json.loads(dict(gens[0].attributes)["langfuse.observation.usage_details"])
    assert usage == {"input": 11, "output": 7}
