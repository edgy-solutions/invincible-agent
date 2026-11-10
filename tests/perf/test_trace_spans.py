"""lane/perf: one trace per answer. Fake Langfuse client throughout; no network."""
from __future__ import annotations

import asyncio
import contextlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "src"), str(ROOT / "baml_shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from iagent import trace_spans as ts  # noqa: E402

TID = "a" * 32
SID = "b" * 16
TP = f"00-{TID}-{SID}-01"


class FakeSpan:
    def __init__(self, calls, kwargs):
        from opentelemetry import trace as t
        self.kwargs = kwargs
        self.trace_id = (kwargs.get("trace_context") or {}).get("trace_id", "c" * 32)
        self.id = "d" * 16
        self.ended = False
        self.updates = []
        self._otel_span = t.NonRecordingSpan(t.SpanContext(
            int(self.trace_id, 16), int(self.id, 16), False))
        self._calls = calls

    def update(self, **kw):
        self.updates.append(kw)

    def end(self):
        self.ended = True
        self._calls.append("end")


class FakeClient:
    def __init__(self, raise_on=()):
        self.calls = []
        self.spans = []
        self.raise_on = set(raise_on)

    def _maybe(self, what):
        if what in self.raise_on:
            raise RuntimeError(f"fake {what} failure")

    def create_trace_id(self, *, seed=None):
        self._maybe("create_trace_id")
        return "e" * 32

    def start_observation(self, **kw):
        self._maybe("start")
        self.calls.append(("start_observation", kw))
        sp = FakeSpan(self.calls, kw)
        self.spans.append(sp)
        return sp

    @contextlib.contextmanager
    def start_as_current_observation(self, **kw):
        self._maybe("start")
        self.calls.append(("start_current", kw))
        sp = FakeSpan(self.calls, kw)
        self.spans.append(sp)
        try:
            yield sp
        finally:
            self.calls.append("exit")

    def flush(self):
        self.calls.append("flush")
        self._maybe("flush")


@pytest.fixture
def enabled(monkeypatch):
    import langfuse
    client = FakeClient()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setattr(langfuse, "get_client", lambda *a, **k: client)
    attrs = []

    @contextlib.contextmanager
    def fake_propagate(**kw):
        attrs.append(kw)
        yield

    monkeypatch.setattr(langfuse, "propagate_attributes", fake_propagate)
    client.attrs = attrs
    return client


@pytest.fixture
def disabled(monkeypatch):
    import langfuse
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    def boom(*a, **k):
        raise AssertionError("langfuse touched while disabled")

    monkeypatch.setattr(langfuse, "get_client", boom)


# 1. traceparent round trip -------------------------------------------------

def test_traceparent_round_trip():
    assert ts.traceparent_for(TID, SID) == TP
    assert ts.parse_traceparent(TP) == {"trace_id": TID, "parent_span_id": SID}


@pytest.mark.parametrize("bad", [
    "", "garbage", f"01-{TID}-{SID}-01", f"00-{'0' * 32}-{SID}-01",
    f"00-{TID}-{'0' * 16}-01", f"00-{TID[:-1]}-{SID}-01", f"00-{TID}-{SID[:-1]}-01",
    f"00-{'G' * 32}-{SID}-01", f"00-{TID.upper()}-{SID}-01", f"00-{TID}-{SID}", None,
])
def test_parse_rejects_malformed(bad):
    assert ts.parse_traceparent(bad) is None


@pytest.mark.parametrize("a,b", [("", SID), (TID, ""), ("0" * 32, SID), (TID, "0" * 16),
                                 ("xyz", SID), (None, SID)])
def test_traceparent_for_rejects(a, b):
    assert ts.traceparent_for(a, b) == ""


# 2. disabled -----------------------------------------------------------------

def test_step_span_disabled_is_a_noop(disabled):
    ran = []
    with ts.step_span("supervisor.execute_subtask", trace_seed="s", traceparent=TP):
        ran.append(1)
    assert ran == [1]
    assert ts.current_traceparent() == ""


# 3. enabled ------------------------------------------------------------------

def test_step_span_uses_traceparent_parent_and_flushes_once(enabled):
    with ts.step_span("supervisor.execute_subtask", trace_seed="seed", traceparent=TP):
        pass
    kind, kw = enabled.calls[0]
    assert kind == "start_current" and kw["name"] == "supervisor.execute_subtask"
    assert kw["trace_context"] == {"trace_id": TID, "parent_span_id": SID}
    assert enabled.calls.count("flush") == 1
    assert enabled.calls.index("exit") < enabled.calls.index("flush")


def test_step_span_falls_back_to_seed_on_malformed_traceparent(enabled):
    with ts.step_span("supervisor.execute_subtask", trace_seed="seed", traceparent="nonsense"):
        pass
    assert enabled.calls[0][1]["trace_context"] == {"trace_id": "e" * 32}


def test_step_span_no_seed_no_parent(enabled):
    with ts.step_span("supervisor.execute_subtask"):
        pass
    assert enabled.calls[0][1]["trace_context"] is None


def test_body_exception_propagates_unchanged_and_flushes(enabled):
    err = ValueError("boom")
    with pytest.raises(ValueError) as ei:
        with ts.step_span("supervisor.execute_subtask", traceparent=TP):
            raise err
    assert ei.value is err
    assert enabled.calls.count("flush") == 1
    assert enabled.spans[0].updates and enabled.spans[0].updates[0]["level"] == "ERROR"


@pytest.mark.parametrize("raise_on", [("start",), ("flush",), ("create_trace_id",)])
def test_a_raising_client_never_raises_into_the_body(enabled, raise_on):
    enabled.raise_on = set(raise_on)
    ran = []
    with ts.step_span("supervisor.execute_subtask", trace_seed="seed"):
        ran.append(1)
    assert ran == [1]


# 4. request span -------------------------------------------------------------

def test_request_span_enabled(enabled):
    h = ts.open_request_span(name="bff.orchestrate", trace_seed="seed",
                             session_id="sess-1", user_id="alice")
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-01", h.traceparent)
    assert ts.parse_traceparent(h.traceparent)["trace_id"] == "e" * 32
    kind, kw = enabled.calls[0]
    assert kind == "start_observation" and kw["name"] == "bff.orchestrate"
    assert "input" not in kw and "output" not in kw
    assert enabled.attrs == [{"trace_name": "answer", "tags": ["cortex-bff"],
                              "session_id": "sess-1", "user_id": "alice"}]
    ts.close_request_span(h)
    assert enabled.spans[0].ended and enabled.calls.count("flush") == 1
    ts.close_request_span(h)  # idempotent
    assert enabled.calls.count("flush") == 1


def test_request_span_async_close_schedules_flush_without_awaiting(enabled):
    h = ts.open_request_span(name="bff.orchestrate", trace_seed="", session_id="", user_id="")
    scheduled = []

    async def run():
        loop = asyncio.get_running_loop()
        real = loop.run_in_executor

        def spy(executor, fn, *args):
            scheduled.append((executor, fn))
            return real(executor, fn, *args)

        loop.run_in_executor = spy
        await ts.aclose_request_span(h)
        # span ended synchronously, before any flush had a chance to be awaited
        assert enabled.spans[0].ended

    asyncio.run(run())
    assert scheduled == [(None, enabled.flush)]
    assert enabled.calls.count("flush") == 1  # ran in the executor (drained by asyncio.run)


def test_request_span_nothing_content_bearing(enabled):
    q = "what is the secret question text"
    ts.open_request_span(name="bff.orchestrate", trace_seed="t", session_id="s", user_id="u")
    assert q not in repr(enabled.calls) and q not in repr(enabled.attrs)


def test_request_span_disabled(disabled):
    h = ts.open_request_span(name="bff.orchestrate", trace_seed="t", session_id="s", user_id="u")
    assert h.traceparent == ""
    ts.close_request_span(h)
    asyncio.run(ts.aclose_request_span(h))


def test_request_span_failing_client_is_soft(enabled):
    enabled.raise_on = {"start"}
    h = ts.open_request_span(name="bff.orchestrate", trace_seed="t", session_id="s", user_id="u")
    assert h.traceparent == ""
    ts.close_request_span(h)


# 5. taxonomy coverage --------------------------------------------------------

# The string literal right after the call paren, with or without a `name=` kwarg. No leading
# \b: the gateway imports open_request_span under a underscore alias.
_CALL = re.compile(
    r"(?:step_span|step_spanned|open_request_span)\(\s*(?:name\s*=\s*)?[\"']([\w.]+)[\"']", re.S)


def _used_names() -> set[str]:
    names: set[str] = set()
    for base in (ROOT / "src", ROOT / "agent_fleet"):
        for f in base.rglob("*.py"):
            if ".venv" in f.parts or "__pycache__" in f.parts or f.name == "trace_spans.py":
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if "step_span" not in text and "open_request_span(" not in text:
                continue
            names.update(_CALL.findall(text))
    return names


def test_every_emitted_span_name_is_declared():
    from span_taxonomy import SPAN_NAMES, declared
    assert SPAN_NAMES, "taxonomy failed to load"
    used = _used_names()
    expected = {"bff.orchestrate", "supervisor.create_task_plan", "supervisor.execute_subtask",
                "supervisor.synthesize_stateful", "supervisor.generate_ui_payload"}
    # positive control: a scan that finds nothing must fail, not pass
    assert expected <= used, f"scan missed {expected - used}"
    assert [n for n in used if not declared(n)] == []
    for spec in SPAN_NAMES.values():
        assert spec["kind"] in {"request", "stage", "hop", "llm", "store"} and spec["service"]


def test_taxonomy_loader_is_fail_soft(monkeypatch, tmp_path):
    import span_taxonomy
    monkeypatch.setattr(span_taxonomy, "_PATH", str(tmp_path / "missing.yaml"))
    assert span_taxonomy._load() == {}


# 6. supervisor ops -----------------------------------------------------------

def test_supervisor_ops_and_job_unchanged():
    from iagent.defs import dynamic_supervisor as ds
    for name in ("create_task_plan", "execute_subtask", "synthesize_stateful",
                 "generate_ui_payload"):
        assert getattr(ds, name).name == name
    names = {n.name for n in ds.supervisor_query_job.graph.node_defs}
    assert {"create_task_plan", "execute_subtask", "synthesize_stateful",
            "generate_ui_payload"} <= names
    assert ds.SupervisorQueryConfig(user_query="q", thread_id="t", traceparent=TP).traceparent == TP
    assert ds.SupervisorQueryConfig(user_query="q", thread_id="t").traceparent == ""


def test_step_spanned_preserves_generator_and_signature():
    import inspect
    from iagent.defs import dynamic_supervisor as ds
    # @op is outermost, so the wrapped function is reachable through the op definition.
    for name in ("create_task_plan", "execute_subtask", "synthesize_stateful",
                 "generate_ui_payload"):
        fn = getattr(ds, name).compute_fn.decorated_fn
        assert fn.__name__ == name and hasattr(fn, "__wrapped__")
        assert inspect.signature(fn) == inspect.signature(fn.__wrapped__)
    plan = ds.create_task_plan.compute_fn.decorated_fn
    assert inspect.isgeneratorfunction(plan)
    assert inspect.isgeneratorfunction(plan.__wrapped__)
    assert not inspect.isgeneratorfunction(ds.execute_subtask.compute_fn.decorated_fn)


def test_step_spanned_reads_config_by_keyword_and_position(enabled):
    class Cfg:
        trace_id = "t1"
        traceparent = TP

    @ts.step_spanned("supervisor.execute_subtask")
    def op(context, config, x):
        return x

    assert op(None, Cfg(), 5) == 5
    assert op(None, config=Cfg(), x=6) == 6
    assert op(None, object(), 7) == 7  # config without the fields: empty ids, no error
    assert enabled.calls[0][1]["trace_context"] == {"trace_id": TID, "parent_span_id": SID}
    assert enabled.calls[3][1]["trace_context"] == {"trace_id": TID, "parent_span_id": SID}
    assert enabled.calls.count("flush") == 3


def test_step_spanned_generator_runs_inside_the_span(enabled):
    @ts.step_spanned("supervisor.create_task_plan")
    def gen(context, config):
        yield 1
        yield 2

    assert list(gen(None, object())) == [1, 2]
    assert enabled.calls[0][0] == "start_current" and enabled.calls.count("flush") == 1
