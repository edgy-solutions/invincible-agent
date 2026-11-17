"""The admission limit for durable answers (ADR-0072 5, ruled 2026-11-16).

The limit holds under a burst; waiting requests start in arrival order; the queued state reaches
the UI; queue wait is its own span; a waiting answer can be withdrawn. No Restate, no network:
a fake WorkflowContext, an in-memory exporter, and a scripted durable backend behind the real
`_generate_dagster_stream_inner`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.iagent import answer_admission as adm  # noqa: E402
from src.iagent import supervisor_service as svc  # noqa: E402
from src.iagent.answer_admission import AdmissionGate, AdmissionWithdrawn  # noqa: E402
from src.iagent.durable_answers import DurableAnswers  # noqa: E402

from tests.perf.test_runless_adapter import fake_ops  # noqa: E402
from tests.perf.test_supervisor_service import CFG, FakeCtx, _Shared  # noqa: E402
from tests.perf.test_trace_spans import (  # noqa: E402,F401
    PARENT, _isolate_sdk_singletons, mem, one, spans_of)


def _run(coro, timeout: float = 20):
    """asyncio.run with a ceiling: a mutant that deadlocks goes red instead of hanging."""
    return asyncio.run(asyncio.wait_for(coro, timeout))


async def _until(pred, timeout: float = 5.0):
    end = asyncio.get_running_loop().time() + timeout
    while not pred():
        assert asyncio.get_running_loop().time() < end, "condition never held"
        await asyncio.sleep(0.005)


class JCtx(FakeCtx):
    """A fake ctx whose journal OUTLIVES an attempt: `admission` is journaled (run once, then
    replayed from `journal`), the way Restate's ctx.run_typed replays a finished step. The step
    runs inline (no thread) and returns an already-resolved future; every other step is the
    plain FakeCtx behaviour."""

    def __init__(self, key, journal=None):
        super().__init__(key)
        self.journal = {} if journal is None else journal

    def run_typed(self, name, fn, options=None, /, *a, **kw):
        if name != "admission":
            return super().run_typed(name, fn, options, *a, **kw)
        self.runs.append((name, getattr(options, "max_attempts", None)))
        if name not in self.journal:
            self.journal[name] = fn(*a, **kw)
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(self.journal[name])
        return fut

    run = run_typed


def _spin(n: int = 5):
    async def go():
        for _ in range(n):
            await asyncio.sleep(0)
    return go()


@pytest.fixture(autouse=True)
def _fresh_gate():
    adm.reset_gate_for_tests(1, 100)
    yield
    adm.reset_gate_for_tests(1, 100)


# 1. the limit holds under a burst -----------------------------------------------------


def test_the_limit_holds_under_a_burst_at_the_gate():
    async def go():
        gate = AdmissionGate(2)
        live, peak, done = set(), [0], []

        async def one_answer(i):
            await gate.acquire(i)
            live.add(i)
            peak[0] = max(peak[0], len(live))
            assert len(live) <= 2
            for _ in range(4):
                await asyncio.sleep(0)
            live.discard(i)
            gate.release(i)
            done.append(i)

        await asyncio.gather(*(one_answer(f"a{i}") for i in range(12)))
        return peak[0], done, gate.state()

    peak, done, state = _run(go())
    assert peak == 2
    assert sorted(done) == sorted(f"a{i}" for i in range(12))
    assert (state["limit"], state["running"], state["waiting"]) == (2, 0, 0)


def test_the_limit_holds_under_a_burst_through_the_service():
    adm.reset_gate_for_tests(2, 100)
    real = svc.run_answer
    live, peak = [0], [0]

    async def counting(*a, **kw):
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        try:
            await asyncio.sleep(0.01)
            return await real(*a, **kw)
        finally:
            live[0] -= 1

    async def go():
        svc.run_answer = counting
        try:
            return await asyncio.gather(*(
                svc._run_impl(FakeCtx(f"b{i}"), CFG, gather=asyncio.gather, ops=fake_ops())
                for i in range(6)))
        finally:
            svc.run_answer = real

    outs = _run(go())
    assert peak[0] == 2
    assert len(outs) == 6 and all(o["status"] == "SUCCESS" for o in outs)
    st = adm.get_gate().state()
    assert (st["limit"], st["running"], st["waiting"]) == (2, 0, 0)


# 2. arrival order, and no barging -----------------------------------------------------


def test_waiters_are_admitted_in_arrival_order():
    async def go():
        gate = AdmissionGate(1)
        await gate.acquire("holder")
        order, tasks = [], []

        async def waiter(i):
            await gate.acquire(i)
            order.append(i)

        for i in range(8):
            tasks.append(asyncio.create_task(waiter(f"w{i}")))
            await asyncio.sleep(0)  # arrival order is defined
        assert [gate.position(f"w{i}") for i in range(8)] == list(range(1, 9))
        prev = "holder"
        for i in range(8):
            gate.release(prev)
            await _spin()
            prev = f"w{i}"
        gate.release(prev)
        await asyncio.gather(*tasks)
        return order

    assert _run(go()) == [f"w{i}" for i in range(8)]


def test_release_and_acquire_in_one_synchronous_step_queue_the_newcomer():
    async def go():
        gate = AdmissionGate(1)
        await gate.acquire("h")
        head = asyncio.create_task(gate.acquire("head"))
        await asyncio.sleep(0)
        gate.release("h")
        fut = asyncio.ensure_future(gate.acquire("new"))
        # `head` holds already (the handoff), before it has even resumed:
        holds_head = "head" in gate._holders
        await head
        await _spin()
        return holds_head, fut.done(), gate.position("new")

    holds_head, new_done, pos = _run(go())
    assert holds_head and not new_done and pos == 1


# 3. the queued state reaches the UI ---------------------------------------------------


def test_the_snapshot_reads_queued_with_a_place_that_falls_as_holders_release():
    async def go():
        gate = adm.get_gate()
        await gate.acquire("running")
        t1 = asyncio.create_task(svc._run_impl(FakeCtx("q1"), CFG, gather=asyncio.gather, ops=fake_ops()))
        await _until(lambda: gate.position("q1") == 1)
        t2 = asyncio.create_task(svc._run_impl(FakeCtx("q2"), CFG, gather=asyncio.gather, ops=fake_ops()))
        await _until(lambda: gate.position("q2") == 2)
        s1 = await svc.snapshot(_Shared(FakeCtx("q1")))
        s2 = await svc.snapshot(_Shared(FakeCtx("q2")))
        gate.release("running")
        await _until(lambda: gate.position("q2") == 1)   # q1 now runs; q2 is first in line
        s2b = await svc.snapshot(_Shared(FakeCtx("q2")))
        await t1
        await t2
        return s1, s2, s2b

    s1, s2, s2b = _run(go())
    for s in (s1, s2, s2b):
        assert s["status"] == "QUEUED" and s["events"] == [] and s["result"] is None
    assert (s1["queue"]["position"], s1["queue"]["ahead"]) == (1, 0)
    assert (s2["queue"]["position"], s2["queue"]["ahead"]) == (2, 1)
    assert (s2b["queue"]["position"], s2b["queue"]["ahead"]) == (1, 0)
    assert s1["queue"]["limit"] == 1 and s1["queue"]["waiting"] == 2


# the stream: the real poll loop behind a scripted durable backend ----------------------

import iagent.gateway as gw  # noqa: E402
from iagent.identity_vault import IdentityVault  # noqa: E402
from tests.planning.test_seed_panel_gates_and_fallback import stubbed_stream  # noqa: E402,F401

RUN = "run-adm-1"


def _req():
    return gw.InterviewRequest(
        message="how is NP-MERIDIAN's variance", session_id="s-adm-1",
        answering_artifact_id="artifact-1", bound_slots={"program_id": "NP-MERIDIAN"})


class FakeBackend:
    """Snapshots as (status, position-or-None), one per status read."""

    def __init__(self, script, *, max_ticks=900):
        self.script, self.polls, self.withdraws = list(script), 0, []
        self.ns = SimpleNamespace(
            launch=self._launch, status=self._status, queue=self._queue, withdraw=self._withdraw,
            events=self._events, steps=self._events, payload=self._payload,
            poll_s=0, max_ticks=max_ticks)

    def _cur(self):
        return self.script[min(self.polls, len(self.script)) - 1]

    async def _launch(self, *a, **k):
        return RUN

    async def _status(self, rid):
        self.polls += 1
        st = self._cur()[0]
        return {"status": st, **({"busy": {"queue_max": 2}} if st == "BUSY" else {})}

    async def _queue(self, rid):
        status, pos = self._cur()
        return None if pos is None else {"position": pos, "ahead": pos - 1, "limit": 1}

    async def _withdraw(self, rid):
        self.withdraws.append(rid)
        return True

    async def _events(self, rid):
        return []

    async def _payload(self, rid):
        return {"error": "none"}


@pytest.fixture
def harness(stubbed_stream, monkeypatch):  # noqa: F811
    monkeypatch.setattr(gw, "VAULT", IdentityVault())
    monkeypatch.setattr(
        gw, "_pre_resolved_from_ask",
        lambda *a, **k: {"subject_uri": "http://invincible-agent/fin#Program",
                         "subject_instance_id": "NP-MERIDIAN", "subject_instance_label": "",
                         "verb_iri": "mesh:finVarianceAnalysis", "owner_persona": ""})
    real_sleep = asyncio.sleep

    async def _nosleep(_s=0, *a, **k):
        await real_sleep(0)

    monkeypatch.setattr(gw.asyncio, "sleep", _nosleep)

    def use(backend):
        monkeypatch.setattr(gw, "_answer_backend", lambda: backend.ns)
        return backend
    return use


async def _drive(**kw):
    out = []
    agen = gw._generate_dagster_stream_inner(_req(), user_email="alice@example.com", **kw)
    try:
        async for ev in agen:
            out.append(ev)
    except Exception:  # noqa: BLE001 -- the post-loop tail is not this file's subject
        pass
    return "".join(out)


def _events(blob, name):
    got, take = [], False
    for line in blob.splitlines():
        if line.startswith("event:"):
            take = line.split(":", 1)[1].strip() == name
        elif line.startswith("data:") and take:
            got.append(json.loads(line[5:]))
            take = False
    return got


QUEUED_RUN = [("QUEUED", 3), ("QUEUED", 3), ("QUEUED", 2), ("QUEUED", 1), ("STARTED", None),
              ("SUCCESS", None)]


@pytest.mark.asyncio
async def test_the_stream_says_queued_once_per_position_then_admitted_once(harness):
    be = harness(FakeBackend(QUEUED_RUN))
    blob = await _drive()
    queued = _events(blob, "answer_queued")
    assert [q["position"] for q in queued] == [3, 2, 1]
    assert [q["ahead"] for q in queued] == [2, 1, 0]
    assert all(q["run_id"] == RUN for q in queued)
    admitted = _events(blob, "answer_admitted")
    assert len(admitted) == 1 and isinstance(admitted[0]["waited_ms"], int) and admitted[0]["waited_ms"] >= 0
    assert blob.rindex("event: answer_queued") < blob.index("event: answer_admitted")
    assert be.polls == 6 and be.withdraws == []


@pytest.mark.asyncio
async def test_a_queued_answer_is_never_ended_by_the_ceiling(harness):
    script = [("QUEUED", 5)] * 10 + [("STARTED", None), ("SUCCESS", None)]
    be = harness(FakeBackend(script, max_ticks=3))
    blob = await _drive()
    assert be.polls == 12, "the ceiling ended a queued answer"
    assert len(_events(blob, "answer_admitted")) == 1


@pytest.mark.asyncio
async def test_the_dagster_path_emits_no_queue_events(harness, monkeypatch):
    monkeypatch.delenv("IAGENT_ANSWER_PATH", raising=False)
    box = {"n": 0}

    async def _launch(*a, **k):
        return RUN

    async def _status(rid):
        box["n"] += 1
        return {"status": "QUEUED" if box["n"] < 4 else "SUCCESS"}

    monkeypatch.setattr(gw, "_launch_supervisor_job", _launch)
    monkeypatch.setattr(gw, "_get_run_status", _status)
    blob = await _drive()
    assert box["n"] == 4
    assert "answer_queued" not in blob and "answer_admitted" not in blob


def test_the_dagster_namespace_has_inert_queue_and_withdraw(monkeypatch):
    monkeypatch.delenv("IAGENT_ANSWER_PATH", raising=False)
    ab = gw._answer_backend()
    assert _run(ab.queue("r")) is None and _run(ab.withdraw("r")) is False
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "durable")
    dab = gw._answer_backend()
    assert dab.queue.__name__ == "get_queue" and dab.withdraw.__name__ == "withdraw"


# 5. withdraw ---------------------------------------------------------------------------


def test_a_waiting_answer_withdrawn_ends_cancelled_and_leaves_the_queue():
    async def go():
        gate = adm.get_gate()
        await gate.acquire("running")
        ctx = FakeCtx("wd")
        task = asyncio.create_task(svc._run_impl(ctx, CFG, gather=asyncio.gather, ops=fake_ops()))
        await _until(lambda: gate.state()["waiting"] == 1)
        res = await svc.withdraw(_Shared(ctx))
        out = await task
        return res, out, ctx.state["snapshot"], gate.state(), await svc.snapshot(_Shared(ctx))

    res, out, snap, state, after = _run(go())
    assert res == {"withdrawn": True} and out == {"withdrawn": True}
    assert snap["status"] == "CANCELED" and snap["withdrawn"] is True
    assert state["waiting"] == 0 and state["running"] == 1
    assert after["status"] == "CANCELED"


def test_withdrawing_a_holder_returns_false_and_changes_nothing():
    async def go():
        gate = adm.get_gate()
        await gate.acquire("h")
        before = gate.state()
        res = await svc.withdraw(_Shared(FakeCtx("h")))
        return res, before, gate.state(), gate.withdraw("never-seen")

    res, before, after, unknown = _run(go())
    assert res == {"withdrawn": False} and before == after and unknown is False


def test_a_cancelled_waiter_leaves_no_waiter_and_no_leaked_slot():
    async def go():
        gate = AdmissionGate(1)
        await gate.acquire("h")
        w = asyncio.create_task(gate.acquire("w"))
        await asyncio.sleep(0)
        w.cancel()
        with pytest.raises(asyncio.CancelledError):
            await w
        mid = gate.state()
        gate.release("h")
        await asyncio.wait_for(gate.acquire("next"), 1)   # admitted at once
        # cancelled in the very tick the handoff resolved it:
        gate2 = AdmissionGate(1)
        await gate2.acquire("h")
        w2 = asyncio.create_task(gate2.acquire("w2"))
        await asyncio.sleep(0)
        gate2.release("h")
        w2.cancel()
        with pytest.raises(asyncio.CancelledError):
            await w2
        await asyncio.wait_for(gate2.acquire("n2"), 1)
        return mid, gate.state(), gate2.state()

    mid, s1, s2 = _run(go())
    for st in (mid, s1, s2):
        assert (st["running"], st["waiting"]) == (1, 0)


def test_acquire_is_idempotent_per_answer():
    async def go():
        gate = AdmissionGate(1)
        await gate.acquire("a")
        await gate.acquire("a")
        gate.release("a")
        gate.release("a")          # never over-released
        await gate.acquire("b")
        return gate.state()

    st = _run(go())
    assert (st["running"], st["waiting"]) == (1, 0)


@pytest.mark.asyncio
async def test_a_stream_closed_while_queued_withdraws_once(harness):
    be = harness(FakeBackend([("QUEUED", 2), ("QUEUED", 2), ("QUEUED", 1), ("STARTED", None)]))
    agen = gw._generate_dagster_stream_inner(_req(), user_email="alice@example.com")
    async for ev in agen:
        if "event: answer_queued" in ev:
            break
    await agen.aclose()
    for _ in range(5):
        await asyncio.sleep(0)
    assert be.withdraws == [RUN]


@pytest.mark.asyncio
async def test_a_stream_closed_while_started_withdraws_nothing(harness):
    be = harness(FakeBackend([("QUEUED", 1), ("STARTED", None), ("STARTED", None)]))
    agen = gw._generate_dagster_stream_inner(_req(), user_email="alice@example.com")
    async for ev in agen:
        if "event: answer_admitted" in ev:
            break
    await agen.aclose()
    for _ in range(5):
        await asyncio.sleep(0)
    assert be.withdraws == []


def test_the_bff_client_reads_the_queue_and_posts_the_withdraw():
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path.endswith("/snapshot"):
            return httpx.Response(200, json={"status": "QUEUED", "events": [], "steps": [],
                                             "result": None, "queue": {"position": 2, "ahead": 1}})
        if req.url.path.endswith("/withdraw"):
            return httpx.Response(200, json={"withdrawn": True})
        return httpx.Response(500)

    da = DurableAnswers("http://r:8080", snapshot_ttl_s=0.0,
                        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert _run(da.get_queue("x")) == {"position": 2, "ahead": 1}
    assert _run(da.withdraw("x")) is True
    assert "/SupervisorAnswer/x/withdraw" in seen

    def run_state(req):
        return httpx.Response(200, json={"status": "STARTED", "queue": {"position": 1}})
    da2 = DurableAnswers("http://r:8080", snapshot_ttl_s=0.0,
                         client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(run_state)))
    assert _run(da2.get_queue("y")) is None   # not QUEUED: no queue

    def boom(req):
        return httpx.Response(500)
    da3 = DurableAnswers("http://r:8080",
                         client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    assert _run(da3.withdraw("z")) is False


# 4. queue wait is its own span --------------------------------------------------------


def _meta(span, key):
    for k, v in span.attributes.items():
        if k.endswith("metadata." + key) or k.endswith("metadata_" + key) or k == key:
            return json.loads(v) if isinstance(v, str) else v
    raise AssertionError((key, sorted(span.attributes)))


def _traced_cfg(**extra):
    return {**CFG, "trace_id": "t-adm-1", "parent_span_id": PARENT, "session_id": "s-adm", **extra}


def test_queue_wait_is_one_span_with_the_wait_when_held(mem):
    client, exp = mem

    async def go():
        gate = adm.get_gate()
        await gate.acquire("other")
        t = asyncio.create_task(svc._run_impl(FakeCtx("sp1"), _traced_cfg(), gather=asyncio.gather,
                                              ops=fake_ops()))
        for _ in range(4):
            await asyncio.sleep(0.02)
        gate.release("other")
        return await t

    out = _run(go())
    assert out["status"] == "SUCCESS"
    span = one(spans_of(client, exp), "supervisor.queue_wait")
    assert span.parent.span_id == int(PARENT, 16)
    assert span.context.trace_id == int(client.create_trace_id(seed="t-adm-1"), 16)
    assert _meta(span, "waited_ms") > 0
    assert _meta(span, "position_at_entry") == 1 and _meta(span, "limit") == 1


def test_queue_wait_span_is_emitted_when_admitted_at_once(mem):
    client, exp = mem
    _run(svc._run_impl(FakeCtx("sp2"), _traced_cfg(), gather=asyncio.gather, ops=fake_ops()))
    span = one(spans_of(client, exp), "supervisor.queue_wait")
    assert _meta(span, "position_at_entry") == 0


def test_no_trace_id_means_no_queue_wait_span(mem):
    client, exp = mem
    _run(svc._run_impl(FakeCtx("sp3"), CFG, gather=asyncio.gather, ops=fake_ops()))
    assert [s.name for s in spans_of(client, exp) if s.name == "supervisor.queue_wait"] == []


def test_the_scanner_sees_the_queue_wait_call_form():
    from tests.perf.test_trace_spans import _span_names_in
    src = (ROOT / "src/iagent/supervisor_service.py").read_text(encoding="utf-8")
    assert "supervisor.queue_wait" in _span_names_in(src)
    found = _span_names_in('ts.observed_trace(M, v, name="undeclared.queue")\n')
    assert found == {"undeclared.queue"}


# 6. the limit from the environment -----------------------------------------------------


def test_the_limit_from_env(monkeypatch, caplog):
    monkeypatch.delenv("IAGENT_ANSWER_LIMIT", raising=False)
    with caplog.at_level(logging.WARNING, logger="iagent.answer_admission"):
        default = adm.answer_limit_from_env()
    assert default == 1 and any("IAGENT_ANSWER_LIMIT" in r.getMessage() for r in caplog.records)
    for raw in ("", "x", "0", "-1"):
        monkeypatch.setenv("IAGENT_ANSWER_LIMIT", raw)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="iagent.answer_admission"):
            assert adm.answer_limit_from_env() == default, raw
        assert [r for r in caplog.records if repr(raw) in r.getMessage()], raw
    monkeypatch.setenv("IAGENT_ANSWER_LIMIT", "3")
    assert adm.answer_limit_from_env() == 3
    assert adm.reset_gate_for_tests().state()["limit"] == 3   # read when the gate is built
    monkeypatch.setenv("IAGENT_ANSWER_LIMIT", "9")
    assert adm.get_gate().state()["limit"] == 3


# 7. refused at once when the queue is full ----------------------------------------------


class _Recorder:
    """A stand-in for run_answer: records starts, and holds each answer until released."""

    def __init__(self):
        self.starts, self.events = [], {}

    def event(self, aid):
        return self.events.setdefault(aid, asyncio.Event())

    async def __call__(self, answer_id, op_config, **kw):
        self.starts.append(answer_id)
        await self.event(answer_id).wait()
        return {"status": "SUCCESS", "id": answer_id}


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(svc, "run_answer", r)
    return r


def test_a_full_queue_refuses_at_entry_without_an_await():
    gate = AdmissionGate(1, 2)
    assert gate.try_enter("h", 1.0) == "admitted"
    assert gate.try_enter("w1", 2.0) == "queued" and gate.try_enter("w2", 3.0) == "queued"
    assert gate.try_enter("w3", 4.0) == "busy"          # synchronous: no await anywhere
    assert gate.refused("w3") == {"reason": "queue_full", "limit": 1, "queue_max": 2}
    assert gate.position("w3") is None and gate.state()["waiting"] == 2
    assert gate.try_enter("w1", 9.0) == "queued"        # a known answer is not re-checked
    none = AdmissionGate(1, 0)
    assert none.try_enter("a", 1.0) == "admitted" and none.try_enter("b", 2.0) == "busy"


def test_the_fourth_request_is_refused_through_the_service_and_the_waiters_still_run(rec):
    adm.reset_gate_for_tests(1, 2)

    async def go():
        gate = adm.get_gate()
        assert gate.try_enter("h", 1.0) == "admitted"
        tasks = []
        for name in ("w1", "w2"):
            tasks.append(asyncio.create_task(svc._run_impl(JCtx(name), CFG, ops=fake_ops())))
            await _until(lambda n=name: gate.position(n) is not None)
        ctx4 = JCtx("w3")
        out = await asyncio.wait_for(svc._run_impl(ctx4, CFG, ops=fake_ops()), 2)
        held_during = (gate.state()["running"], list(rec.starts))     # nothing released yet
        # a refusal exists before any durable state: the snapshot says BUSY at once
        assert gate.try_enter("w4", 5.0) == "busy"
        early = await svc.snapshot(_Shared(FakeCtx("w4")))
        gate.release("h")
        for n in ("w1", "w2"):
            await _until(lambda n=n: n in rec.starts)
            rec.event(n).set()
        outs = await asyncio.gather(*tasks)
        return out, ctx4.state["snapshot"], held_during, early, outs

    out, snap, held, early, outs = _run(go())
    assert out == {"busy": True}
    assert snap["status"] == "BUSY" and snap["busy"]["reason"] == "queue_full"
    assert snap["busy"]["queue_max"] == 2 and snap["result"] is None
    assert held == (1, [])
    assert early["status"] == "BUSY" and early["busy"]["queue_max"] == 2
    assert rec.starts == ["w1", "w2"] and [o["id"] for o in outs] == ["w1", "w2"]


def test_a_busy_answer_emits_no_queue_wait_span(mem, rec):
    client, exp = mem
    adm.reset_gate_for_tests(1, 0)
    adm.get_gate().try_enter("h", 1.0)
    out = _run(svc._run_impl(JCtx("b1"), _traced_cfg(), ops=fake_ops()))
    assert out == {"busy": True}
    assert [s for s in spans_of(client, exp) if s.name == "supervisor.queue_wait"] == []


# 8. busy reaches the user --------------------------------------------------------------


@pytest.mark.asyncio
async def test_busy_reaches_the_stream_as_one_pipeline_error(harness):
    be = harness(FakeBackend([("BUSY", None)]))
    blob = await _drive()
    # exactly ONE error in the whole stream: the busy refusal, and no generic timeout after it
    errs = _events(blob, "pipeline_error")
    assert len(errs) == 1, errs
    assert "queue is full" in errs[0]["message"] and errs[0]["cause"] == "answer_busy_queue_full"
    assert errs[0]["retryable"] is True and "2" in errs[0]["message"]
    assert "answer_queued" not in blob and "answer_admitted" not in blob
    assert be.polls == 1 and be.withdraws == []


# 9. a restart keeps its original place ---------------------------------------------------


def test_a_restart_re_enters_by_its_first_arrival_at_the_gate():
    async def go():
        gate = AdmissionGate(1, 100)
        gate.try_enter("h", 1.0)
        order, tasks = [], []

        async def enter(aid, at):
            await gate.acquire(aid, at)
            order.append(aid)

        for aid, at in (("w10", 10), ("w20", 20), ("w30", 30), ("r5", 5), ("r25", 25)):
            tasks.append(asyncio.create_task(enter(aid, at)))
            await asyncio.sleep(0)
        assert [gate.position(a) for a in ("r5", "w10", "w20", "r25", "w30")] == [1, 2, 3, 4, 5]
        prev = "h"
        for _ in range(5):
            gate.release(prev)
            await _spin()
            prev = order[-1]
        gate.release(prev)
        await asyncio.gather(*tasks)
        return order

    assert _run(go()) == ["r5", "w10", "w20", "r25", "w30"]


def test_a_restarted_answer_keeps_its_place_and_is_never_refused(mem, monkeypatch):
    client, exp = mem
    adm.reset_gate_for_tests(1, 2)
    starts, attempt = [], {"R": 0}

    async def fake_run_answer(answer_id, op_config, **kw):
        starts.append(answer_id)
        if answer_id == "R":
            attempt["R"] += 1
            if attempt["R"] == 1:
                await asyncio.sleep(60)        # the attempt that is cancelled mid-run
        await fake_run_answer.gate.wait()
        return {"status": "SUCCESS", "id": answer_id}

    monkeypatch.setattr(svc, "run_answer", fake_run_answer)

    async def go():
        fake_run_answer.gate = asyncio.Event()
        gate = adm.get_gate()
        ctx_r = JCtx("R")
        t1 = asyncio.create_task(svc._run_impl(ctx_r, _traced_cfg(), ops=fake_ops()))
        await _until(lambda: gate.state()["running"] == 1 and starts == ["R"])
        await asyncio.sleep(0.02)                    # later arrivals, strictly after R's
        tasks = {}
        for n in ("W1", "W2"):
            tasks[n] = asyncio.create_task(svc._run_impl(JCtx(n), CFG, ops=fake_ops()))
            await _until(lambda n=n: gate.position(n) is not None)
        t1.cancel()                                   # R's attempt dies mid-run
        with pytest.raises(asyncio.CancelledError):
            await t1
        await _until(lambda: starts == ["R", "W1"])   # the slot went to the head waiter
        tasks["W3"] = asyncio.create_task(svc._run_impl(JCtx("W3"), CFG, ops=fake_ops()))
        await _until(lambda: gate.state()["waiting"] == 2)           # the queue is FULL again
        assert gate.state()["waiting"] == gate.state()["queue_max"]
        # attempt 2, the SAME journal: not refused despite the full queue, ahead of W2 and W3
        t2 = asyncio.create_task(svc._run_impl(ctx_r, _traced_cfg(), ops=fake_ops()))
        await _until(lambda: gate.position("R") is not None)
        assert gate.position("R") == 1
        fake_run_answer.gate.set()
        out = await t2
        await asyncio.gather(*tasks.values())
        return out

    out = _run(go())
    assert out["id"] == "R"
    assert starts == ["R", "W1", "R", "W2", "W3"]
    spans = [s for s in spans_of(client, exp) if s.name == "supervisor.queue_wait"]
    assert [_meta(s, "restarted") for s in sorted(spans, key=lambda s: s.start_time)] == [False, True]


# 10. the queue maximum from the environment ---------------------------------------------


def test_the_queue_max_from_env(monkeypatch, caplog):
    monkeypatch.delenv("IAGENT_ANSWER_QUEUE_MAX", raising=False)
    with caplog.at_level(logging.WARNING, logger="iagent.answer_admission"):
        default = adm.answer_queue_max_from_env()
    assert default == 0 and any("IAGENT_ANSWER_QUEUE_MAX" in r.getMessage() for r in caplog.records)
    for raw in ("", "x", "-1"):
        monkeypatch.setenv("IAGENT_ANSWER_QUEUE_MAX", raw)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="iagent.answer_admission"):
            assert adm.answer_queue_max_from_env() == default, raw
        assert [r for r in caplog.records if repr(raw) in r.getMessage()], raw
    monkeypatch.setenv("IAGENT_ANSWER_QUEUE_MAX", "0")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="iagent.answer_admission"):
        assert adm.answer_queue_max_from_env() == 0
    assert caplog.records == []
    monkeypatch.setenv("IAGENT_ANSWER_QUEUE_MAX", "5")
    assert adm.answer_queue_max_from_env() == 5
    assert adm.reset_gate_for_tests().state()["queue_max"] == 5


# =====================================================================================
# AMENDMENT 2 (ruled 2026-11-16): admission comes BEFORE intent extraction. A refused or
# waiting request makes no model call. Driven through the real boundary
# (`generate_dagster_stream`) on the NON-`_pre_resolved` path, the real `DurableAnswers`
# client, the real gate and the real service handlers, with every POST stubbed at the httpx
# level and COUNTED by URL.
# =====================================================================================

ADM_ROUTE = "route_intent"


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("stub", request=None, response=self)


class Mesh:
    """Every POST of the stream, counted by tag, in order; the SupervisorAnswer handlers are the
    REAL ones over the real gate (an in-process service double, never a mock of `release`)."""

    def __init__(self, *, route_status=200, route_body=None):
        self.route_status = route_status
        self.route_body = {"mode": "ONE_SHOT"} if route_body is None else route_body
        self.log: list = []          # ("post", tag, answer_id) and ("ev", event_name), in order
        self.launched: dict = {}

    def n(self, tag):
        return sum(1 for e in self.log if e[0] == "post" and e[1] == tag)

    def client(self, *a, **k):
        return _MeshClient(self)

    async def post(self, url, json=None, headers=None, **kw):
        if "/SupervisorAnswer/" in url:
            _, _, rest = url.partition("/SupervisorAnswer/")
            aid, _, handler = rest.partition("/")
            self.log.append(("post", handler, aid))
            ctx = _Shared(FakeCtx(aid))
            if handler == "run/send":
                self.launched[aid] = json
                return _Resp(200, {})
            if handler == "snapshot" and aid in self.launched:
                return _Resp(200, {"status": "CANCELED", "events": [], "steps": [], "result": None})
            return _Resp(200, await getattr(svc, handler)(ctx))
        if url.endswith("/route_intent"):
            self.log.append(("post", ADM_ROUTE, None))
            return _Resp(self.route_status, self.route_body)
        if "/ProcessInterviewer/" in url:
            self.log.append(("post", url.rsplit("/", 1)[-1], None))
            return _Resp(200, {"is_active": False} if url.endswith("get_status") else {})
        self.log.append(("post", "other:" + url, None))
        return _Resp(200, {})


class _MeshClient:
    def __init__(self, mesh):
        self.mesh = mesh

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return await self.mesh.post(url, **kw)


@pytest.fixture
def mesh_env(stubbed_stream, monkeypatch):  # noqa: F811
    """The durable path against a Mesh; returns `new(**kw) -> Mesh`."""
    monkeypatch.setattr(gw, "VAULT", IdentityVault())
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "durable")
    real_sleep = asyncio.sleep

    async def _nosleep(_s=0, *a, **k):
        await real_sleep(0)

    monkeypatch.setattr(gw.asyncio, "sleep", _nosleep)

    def new(**kw):
        m = Mesh(**kw)
        monkeypatch.setattr(httpx, "AsyncClient", m.client)
        monkeypatch.setattr(gw, "_DURABLE_ANSWERS",
                            DurableAnswers("http://ingress", client_factory=m.client))
        return m
    new.calls = stubbed_stream
    return new


def _plain_req():
    """No answering artifact, no seed panel: the branch that calls /route_intent."""
    return gw.InterviewRequest(message="how is the pump doing", session_id="s-adm-2")


async def _stream(mesh, *, stop=None):
    """Drive the boundary; log every event beside the posts. `stop(ev, mesh)` closes the stream."""
    out = []
    agen = gw.generate_dagster_stream(_plain_req(), user_email="alice@example.com")
    try:
        async for ev in agen:
            out.append(ev)
            for line in ev.splitlines():
                if line.startswith("event:"):
                    mesh.log.append(("ev", line.split(":", 1)[1].strip()))
            if stop is not None and stop(ev, mesh):
                break
    except Exception:  # noqa: BLE001 -- the post-loop tail is not this file's subject
        pass
    finally:
        await agen.aclose()
    for _ in range(10):
        await asyncio.sleep(0)       # the fire-and-forget release / withdraw runs
    return "".join(out)


def _gate_full(holders=("h",), waiters=()):
    gate = adm.get_gate()
    for i, h in enumerate(holders):
        assert gate.try_enter(h, 1.0 + i) == "admitted"
    for i, w in enumerate(waiters):
        assert gate.try_enter(w, 100.0 + i) == "queued"
    return gate


# 1. a refused request causes zero model calls ------------------------------------------


@pytest.mark.asyncio
async def test_a_refused_request_causes_zero_model_calls(mesh_env):
    adm.reset_gate_for_tests(1, 1)
    gate = _gate_full(("h",), ("w",))           # K holders and M waiters: full
    m = mesh_env()
    blob = await _stream(m)
    errs = _events(blob, "pipeline_error")
    assert len(errs) == 1 and errs[0]["cause"] == "answer_busy_queue_full", errs
    assert errs[0]["retryable"] is True and "queue is full" in errs[0]["message"]
    assert m.n(ADM_ROUTE) == 0 and m.n("run/send") == 0
    assert "stream_end" in blob
    assert [b["status"] for b in mesh_env.calls["bundles"]] == ["failed"]   # what BUSY writes
    assert gate.state()["running"] == 1 and gate.state()["waiting"] == 1   # nothing taken


@pytest.mark.asyncio
async def test_control_a_request_with_a_free_slot_makes_one_route_and_one_launch(mesh_env):
    adm.reset_gate_for_tests(1, 1)
    m = mesh_env()
    blob = await _stream(m)
    assert m.n("reserve") == 1 and m.n(ADM_ROUTE) == 1 and m.n("run/send") == 1
    tags = [e[1] for e in m.log if e[0] == "post"]
    assert tags.index("reserve") < tags.index(ADM_ROUTE) < tags.index("run/send")
    assert "answer_queued" not in blob and "answer_admitted" not in blob
    ((rid, body),) = m.launched.items()         # launched under the SAME id, with its arrival
    assert body["reserved_arrived_at"] == adm.get_gate().arrived_at(rid)
    assert m.n("release") == 0                  # launched: `run` owns it, nobody releases


# 2. a waiting request makes no model call until admitted -------------------------------


@pytest.mark.asyncio
async def test_a_waiting_request_makes_no_model_call_until_admitted(mesh_env):
    adm.reset_gate_for_tests(1, 5)
    gate = _gate_full(("h",))
    m = mesh_env()
    task = asyncio.ensure_future(_stream(m))
    await _until(lambda: ("ev", "answer_queued") in m.log)
    for _ in range(20):
        await asyncio.sleep(0)
    assert m.n(ADM_ROUTE) == 0 and m.n("run/send") == 0     # waiting: no model call
    gate.release("h")
    blob = await asyncio.wait_for(task, 10)
    names = [(e[1] if e[0] == "ev" else "post:" + e[1]) for e in m.log]
    assert names.index("answer_admitted") < names.index("post:" + ADM_ROUTE)
    assert m.n(ADM_ROUTE) == 1 and m.n("run/send") == 1
    # the run loop after the launch adds no second pair of queue events
    assert len(_events(blob, "answer_queued")) == 1 and len(_events(blob, "answer_admitted")) == 1


# 3. every non-launch exit releases ------------------------------------------------------


def _assert_given_back(m, gate):
    st = gate.state()
    assert (st["running"], st["waiting"]) == (0, 0), st
    assert m.n("run/send") == 0 and m.n("release") == 1


@pytest.mark.asyncio
async def test_route_intent_failing_releases_the_reservation(mesh_env):
    adm.reset_gate_for_tests(1, 1)
    m = mesh_env(route_status=500)
    blob = await _stream(m)
    assert "route_intent_failed" in blob
    _assert_given_back(m, adm.get_gate())


@pytest.mark.asyncio
async def test_a_conversational_mode_releases_the_reservation(mesh_env):
    adm.reset_gate_for_tests(1, 1)
    m = mesh_env(route_body={"mode": "CONVERSATIONAL"})
    await _stream(m)
    assert m.n("process_message") == 1          # it really took the interview path
    _assert_given_back(m, adm.get_gate())


@pytest.mark.asyncio
async def test_a_stream_closed_after_admission_before_launch_releases_once(mesh_env):
    adm.reset_gate_for_tests(1, 1)
    m = mesh_env()
    await _stream(m, stop=lambda ev, mesh: mesh.n(ADM_ROUTE) == 1)
    assert m.n("withdraw") == 0
    _assert_given_back(m, adm.get_gate())


# 8. closing the stream -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stream_closed_while_reserved_and_queued_withdraws_once(mesh_env):
    adm.reset_gate_for_tests(1, 5)
    gate = _gate_full(("h",))
    m = mesh_env()
    await _stream(m, stop=lambda ev, mesh: "event: answer_queued" in ev)
    assert m.n("withdraw") == 1 and m.n("release") == 0 and m.n(ADM_ROUTE) == 0
    assert gate.state()["waiting"] == 0 and gate.state()["running"] == 1


# 7. the Dagster path never reserves ------------------------------------------------------


@pytest.mark.asyncio
async def test_the_dagster_path_makes_zero_reserve_and_zero_release_calls(mesh_env, monkeypatch):
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "dagster")
    m = mesh_env()
    await _stream(m)
    assert m.n(ADM_ROUTE) == 1
    assert not any("/SupervisorAnswer/" in str(e) for e in m.log)
    assert [e for e in m.log if e[0] == "post" and e[1] in (
        "reserve", "release", "snapshot", "withdraw", "run/send")] == []
    ns = gw._answer_backend()
    assert await ns.reserve("x") is None and await ns.release("x") is False


# 4. the claim ----------------------------------------------------------------------------


def test_run_claims_a_reservation_and_keeps_its_arrival(mem, rec):
    client, exp = mem
    adm.reset_gate_for_tests(1, 2)

    async def go():
        got = await svc.reserve(_Shared(FakeCtx("R1")))
        assert got["decision"] == "admitted"
        again = await svc.reserve(_Shared(FakeCtx("R1")))          # idempotent
        assert again["decision"] == "admitted" and again["arrived_at"] == got["arrived_at"]
        ctx = JCtx("R1")
        task = asyncio.create_task(svc._run_impl(
            ctx, _traced_cfg(reserved_arrived_at=got["arrived_at"]), ops=fake_ops()))
        await _until(lambda: rec.starts == ["R1"])
        gate = adm.get_gate()
        st = (gate.state()["running"], gate.state()["waiting"])
        released = await svc.release(_Shared(FakeCtx("R1")))
        after = gate.state()["running"]
        rec.event("R1").set()
        await task
        return got, ctx.journal["admission"], st, released, after

    got, adj, st, released, after = _run(go())
    assert adj["decision"] == "admitted" and adj["arrived_at"] == got["arrived_at"]
    assert st == (1, 0)                         # no second entry
    assert released == {"released": False} and after == 1      # a claimed place is `run`'s
    (span,) = [s for s in spans_of(client, exp) if s.name == "supervisor.queue_wait"]
    assert _meta(span, "reserved") is True


def test_a_claimed_queued_reservation_waits_from_its_first_arrival(mem, rec):
    client, exp = mem
    adm.reset_gate_for_tests(1, 2)

    async def go():
        gate = adm.get_gate()
        gate.try_enter("h", 1.0)
        got = await svc.reserve(_Shared(FakeCtx("R2")))
        assert got["decision"] == "queued"
        await asyncio.sleep(0.05)               # time passes before `run` starts
        task = asyncio.create_task(svc._run_impl(
            JCtx("R2"), _traced_cfg(reserved_arrived_at=got["arrived_at"]), ops=fake_ops()))
        await _spin()
        assert gate.state()["waiting"] == 1     # still ONE entry: claimed, not re-queued
        gate.release("h")
        await _until(lambda: rec.starts == ["R2"])
        rec.event("R2").set()
        await task

    _run(go())
    (span,) = [s for s in spans_of(client, exp) if s.name == "supervisor.queue_wait"]
    assert _meta(span, "reserved") is True and _meta(span, "waited_ms") >= 50


# 5. the lost reservation -----------------------------------------------------------------


def test_a_lost_reservation_is_never_busy_and_is_placed_by_its_arrival(rec):
    adm.reset_gate_for_tests(1, 1)

    async def go():
        gate = adm.get_gate()
        gate.try_enter("h", 1.0)
        assert gate.try_enter("w1", 10.0) == "queued"          # the queue is FULL
        ctx = JCtx("L")
        task = asyncio.create_task(svc._run_impl(
            ctx, {**CFG, "reserved_arrived_at": 5.0}, ops=fake_ops()))
        await _until(lambda: gate.position("L") is not None)
        placed = (gate.position("L"), gate.position("w1"))
        gate.release("h")
        await _until(lambda: rec.starts == ["L"])
        rec.event("L").set()
        out = await task
        return ctx.journal["admission"], placed, out

    adj, placed, out = _run(go())
    assert adj["decision"] != "busy" and adj["arrived_at"] == 5.0 and "busy" not in out
    assert placed == (1, 2)                     # ahead of the waiter that arrived later


# 6. leases -------------------------------------------------------------------------------


def _clocked(limit=1, queue_max=5):
    t = [0.0]
    return AdmissionGate(limit, queue_max, lease_s=300, waiter_idle_s=30,
                         clock=lambda: t[0]), t


def test_an_unclaimed_holder_expires_at_the_lease_and_its_slot_passes_to_the_head():
    gate, t = _clocked()
    gate.try_enter("h", 1.0)
    gate.try_enter("w", 2.0)
    for tick in range(10, 300, 10):             # a snapshot read keeps the waiter alive
        t[0] = tick
        gate.touch("w")
    assert gate.state()["running"] == 1 and gate.position("w") == 1      # 290 s: still held
    t[0] = 300
    assert gate.state()["running"] == 1 and gate.position("w") is None   # w holds the slot now
    assert gate.admitted_at("w") is not None and gate.arrived_at("w") == 2.0


def test_an_untouched_unclaimed_waiter_leaves_the_queue_and_a_touched_one_stays():
    gate, t = _clocked()
    gate.try_enter("h", 1.0)
    gate.claim("h")
    gate.try_enter("idle", 2.0)
    gate.try_enter("read", 3.0)
    for tick in (10, 20, 29):
        t[0] = tick
        gate.touch("read")
    assert gate.state()["waiting"] == 2
    t[0] = 30
    assert gate.position("idle") is None and gate.position("read") == 1
    for tick in range(40, 400, 10):
        t[0] = tick
        gate.touch("read")
    assert gate.position("read") == 1           # read every few seconds: never expires


def test_a_claimed_holder_never_expires():
    gate, t = _clocked()
    gate.try_enter("h", 1.0)
    gate.claim("h")
    gate.try_enter("w", 2.0)
    gate.claim("w")                             # claimed waiters never expire either
    t[0] = 100_000
    assert gate.state() == {"limit": 1, "queue_max": 5, "running": 1, "waiting": 1}
    assert gate.release_unclaimed("h") is False


def test_the_lease_values_come_from_the_environment(monkeypatch, caplog):
    monkeypatch.delenv("IAGENT_ANSWER_RESERVATION_LEASE_S", raising=False)
    monkeypatch.delenv("IAGENT_ANSWER_WAITER_IDLE_S", raising=False)
    assert (adm.reservation_lease_from_env(), adm.waiter_idle_from_env()) == (300.0, 30.0)
    monkeypatch.setenv("IAGENT_ANSWER_RESERVATION_LEASE_S", "12.5")
    monkeypatch.setenv("IAGENT_ANSWER_WAITER_IDLE_S", "x")
    with caplog.at_level(logging.WARNING, logger="iagent.answer_admission"):
        assert adm.reservation_lease_from_env() == 12.5
        assert adm.waiter_idle_from_env() == 30.0
    assert [r for r in caplog.records if "IAGENT_ANSWER_WAITER_IDLE_S" in r.getMessage()]


# 3b. the client ---------------------------------------------------------------------------


def test_the_bff_client_reserves_releases_and_launches_under_a_given_id():
    seen = []

    class C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            seen.append(url)
            if url.endswith("/reserve"):
                return _Resp(200, {"decision": "queued", "arrived_at": 7.0})
            if url.endswith("/release"):
                return _Resp(200, {"released": True})
            return _Resp(200, {})

    da = DurableAnswers("http://i/", client_factory=C)
    assert _run(da.reserve("a1")) == {"decision": "queued", "arrived_at": 7.0}
    assert _run(da.release("a1")) is True
    assert _run(da.launch({}, answer_id="a1")) == "a1"
    assert seen == ["http://i/SupervisorAnswer/a1/reserve", "http://i/SupervisorAnswer/a1/release",
                    "http://i/SupervisorAnswer/a1/run/send"]

    class Dead(C):
        async def post(self, url, json=None):
            raise RuntimeError("down")

    dead = DurableAnswers("http://i", client_factory=Dead)
    assert _run(dead.reserve("a")) is None and _run(dead.release("a")) is False
