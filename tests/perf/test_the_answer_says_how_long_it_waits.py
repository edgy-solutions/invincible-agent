"""THE ANSWER SAYS WHEN IT IS WAITING, AND HOW LONG IT WILL WAIT (architect, 2026-11-27).

Before: the `locating` stage started before the run was launched, so the time a question spent
queued, and the time the run took to start, was shown as locating the subject. And the stream's
15-minute limit was never sent: a person could not tell a slow answer from one the server had
given up on, and the limit itself was a count of ticks, so it stretched with every slow read.

Now:
  * `waiting` is the first stage on the run path. It completes when the first step shows, and
    only then does `locating` start. It fails when the run fails or stalls before any step.
  * `answer_timing {run_id, elapsed_ms, expected_ms, deadline_ms}` is sent once after the
    launch, and again whenever counting resumes after queued or paused time (the deadline moved).
  * The limit is 900 s of COUNTED wall time as well as 900 ticks, so `deadline_ms` is true.
  * `expected_ms` is the median duration of the caller's own recorded complete answers.

DRIVEN THROUGH THE REAL ``_generate_dagster_stream_inner`` with a real ``DurableAnswers`` on a
mock transport, on the stream's own clock (`_stall_clock`), as the stall seal does.

Run:  uv run --frozen python -m pytest tests/perf/test_the_answer_says_how_long_it_waits.py -q
"""
from __future__ import annotations

import asyncio
import inspect
import time

import httpx
import pytest

from tests.perf.test_a_failed_run_ends_with_a_card import (  # noqa: F401  (fixtures by name)
    RUN, _RealAsyncClient, _drive, _of, _parse, base, stubbed_stream,
)
from tests.perf.test_a_stalled_durable_answer_ends_with_a_card import (  # noqa: F401
    ANSWER, PLACE, PLAN, POLL_S, QUEUED_S, STALL_S, _durable, _queued_then, _stuck, clock,
)

import iagent.gateway as gw  # noqa: E402
from src.iagent.durable_answers import DurableAnswers  # noqa: E402

EXPECTED = 42_000
CEILING_MS = 900_000


@pytest.fixture
def expected(monkeypatch):
    async def _fake(user_id):
        return EXPECTED

    monkeypatch.setattr(gw, "_expected_ms", _fake, raising=False)
    return _fake


@pytest.fixture
def routed(base, monkeypatch):
    """The run path: no pre-resolved route, intent extraction answers, the run is launched."""
    monkeypatch.setattr(gw, "_pre_resolved_from_ask", lambda *a, **k: {})

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"mode": "ONE_SHOT", "entity_refs": []}

    class _Http:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): return _Resp()

    monkeypatch.setattr(gw.httpx, "AsyncClient", _Http)
    return base


def _sequence(blob):
    """Every event in order, the stages as (`stage`, kind, status)."""
    out = []
    for name, data in _parse(blob):
        if name == "pipeline_stage":
            out.append(("stage", data["kind"], data["status"]))
        else:
            out.append((name, data))
    return out


def _at(seq, kind, status):
    hits = [i for i, e in enumerate(seq) if e == ("stage", kind, status)]
    assert hits, (kind, status, seq)
    return hits


def _moving_until(done_at, t0=0):
    """A run that keeps moving (a step every 10 s from `t0`), and succeeds at `done_at`."""
    def snap(now, n=0):
        done = [{"stepKey": f"execute_subtask[{i}]", "status": "SUCCESS", "endTime": float(i)}
                for i in range(int(max(0, now - t0) // 10))]
        if now >= done_at:
            return {"status": "SUCCESS", "events": [], "steps": [PLAN, *done],
                    "result": {"payload": ANSWER, "referenced_uris": []}}
        return {"status": "STARTED", "events": [], "steps": [PLAN, *done], "result": None}
    return snap


_moving = _moving_until(3 * STALL_S)


def _first_step_at(t, then):
    """No step shows until `t`; then the plan step runs for 10 s; then `then(now, n)`."""
    def snap(now, n):
        if now < t:
            return {"status": "STARTED", "events": [], "steps": [], "result": None}
        if now < t + 10:
            return {"status": "STARTED", "events": [], "result": None, "steps": [
                {"stepKey": "create_task_plan", "status": "RUNNING", "startTime": 1.0,
                 "endTime": None}]}
        return then(now, n)
    return snap


# -- 1-4: the stage ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_waiting_is_the_first_stage_after_understanding_and_locating_waits_for_a_step(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, _first_step_at(20, _moving_until(200)), clock=clock)
    seq = _sequence(await _drive())
    stages = [e for e in seq if e[0] == "stage"]
    i_und = stages.index(("stage", "understanding", "completed"))
    assert stages[i_und + 1] == ("stage", "waiting", "started"), stages
    w_start = _at(seq, "waiting", "started")
    assert len(w_start) == 1, seq
    w_done = _at(seq, "waiting", "completed")[0]
    loc = _at(seq, "locating", "started")[0]
    assert w_start[0] < w_done < loc, seq
    # no locating of any kind before the waiting stage is over
    assert all(i > w_done for i, e in enumerate(seq) if e[:2] == ("stage", "locating")), seq
    assert loc < _at(seq, "choosing_action", "started")[0], seq


@pytest.mark.asyncio
async def test_a_run_queued_after_launch_keeps_waiting_open_until_a_step_runs(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, _queued_then(_moving_until(QUEUED_S + 180, QUEUED_S)), clock=clock)
    seq = _sequence(await _drive())
    admitted = next(i for i, e in enumerate(seq) if e[0] == "answer_admitted")
    queued = next(i for i, e in enumerate(seq) if e[0] == "answer_queued")
    assert queued < admitted
    assert _at(seq, "waiting", "started")[0] < queued
    assert _at(seq, "waiting", "completed")[0] > queued
    assert _at(seq, "locating", "started")[0] > _at(seq, "waiting", "completed")[0]
    assert not [i for i, e in enumerate(seq) if e[:2] == ("stage", "locating") and i < queued], seq


@pytest.mark.asyncio
async def test_a_run_that_fails_before_any_step_fails_the_waiting_stage(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, lambda now, n: {"status": "FAILURE", "events": [], "steps": [],
                                          "result": None}, clock=clock)
    seq = _sequence(await _drive())
    failed = _at(seq, "waiting", "failed")
    assert len(failed) == 1, seq
    assert failed[0] < next(i for i, e in enumerate(seq) if e[0] == "pipeline_error"), seq
    assert ("stage", "locating", "started") not in seq, seq
    assert ("stage", "waiting", "completed") not in seq, seq


@pytest.mark.asyncio
async def test_a_run_that_stalls_before_any_step_fails_the_waiting_stage(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, lambda now, n: {"status": "STARTED", "events": [], "steps": [],
                                          "result": None}, clock=clock)
    seq = _sequence(await _drive())
    err = next(i for i, e in enumerate(seq) if e[0] == "pipeline_error")
    assert seq[err][1]["cause"] == "answer_run_stalled", seq[err]
    assert _at(seq, "waiting", "failed")[0] < err, seq


@pytest.mark.asyncio
async def test_the_direct_path_keeps_locating_where_it_was(base, clock, expected, monkeypatch):
    """A pre-resolved route announces `locating` right after `understanding`, as before. This
    drive's direct dispatch falls back to a run, so `waiting` follows, before the launch."""
    _durable(monkeypatch, _first_step_at(20, _moving_until(200)), clock=clock)
    seq = _sequence(await _drive())
    stages = [e for e in seq if e[0] == "stage"]
    i_und = stages.index(("stage", "understanding", "completed"))
    assert stages[i_und + 1] == ("stage", "locating", "started"), stages
    assert _at(seq, "locating", "started")[0] < _at(seq, "waiting", "started")[0]


def test_the_source_starts_locating_only_on_the_direct_path():
    src = inspect.getsource(gw._generate_dagster_stream_inner)
    lines = [ln.strip() for ln in src.splitlines()]
    want = ["if _pre_resolved:", 'yield _stage("locating", "started")']
    assert any(lines[i + 1:i + 3] == want for i, ln in enumerate(lines)
               if ln == 'yield _stage("understanding", "completed")')


# -- 5-8: answer_timing and the wall ceiling ---------------------------------------------------

@pytest.mark.asyncio
async def test_answer_timing_follows_the_launch_with_the_deadline_and_the_expected_time(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, _first_step_at(20, _moving_until(200)), clock=clock)
    pairs = _parse(await _drive())
    timings = _of(pairs, "answer_timing")
    assert len(timings) == 1, timings
    t = timings[0]
    assert set(t) == {"run_id", "elapsed_ms", "expected_ms", "deadline_ms"}, t
    assert t["expected_ms"] == EXPECTED
    assert t["run_id"]
    assert abs((t["deadline_ms"] - t["elapsed_ms"]) - CEILING_MS) <= 1000 * POLL_S, t
    names = [n for n, _ in pairs]
    assert names.index("answer_timing") < names.index("final_payload")


@pytest.mark.asyncio
async def test_a_run_queued_then_admitted_moves_the_deadline_by_the_queue_time(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, _queued_then(_moving_until(QUEUED_S + 180, QUEUED_S)), clock=clock)
    timings = _of(_parse(await _drive()), "answer_timing")
    assert len(timings) == 2, timings
    moved = timings[1]["deadline_ms"] - timings[0]["deadline_ms"]
    assert abs(moved - QUEUED_S * 1000) <= 4 * 1000 * POLL_S, timings


@pytest.mark.asyncio
async def test_a_run_paused_then_resumed_moves_the_deadline_by_the_pause(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, _moving_until(230 + 60), clock=clock)
    monkeypatch.setattr(gw.VAULT, "state",
                        lambda rid: "awaiting_reauth" if 30 <= clock["now"] < 230 else "live")
    pairs = _parse(await _drive())
    timings = _of(pairs, "answer_timing")
    assert len(timings) == 2, timings
    moved = timings[1]["deadline_ms"] - timings[0]["deadline_ms"]
    assert abs(moved - 200 * 1000) <= 4 * 1000 * POLL_S, timings
    assert _of(pairs, "final_payload") == [ANSWER]


@pytest.mark.asyncio
async def test_the_ceiling_is_counted_wall_time_not_ticks(routed, clock, expected, monkeypatch):
    """Reads that cost 10 s each stretch a tick to a minute; a run that moves every tick never
    stalls. The stream stops at 900 s of wall time, not at 3600 ticks."""
    def every_tick_moves(now, n):
        lo = max(0, n - 12)
        return {"status": "STARTED", "events": [],
                "steps": [{"stepKey": f"execute_subtask[{i}]", "status": "SUCCESS",
                           "endTime": float(i)} for i in range(lo, n)], "result": None}

    reads = _durable(monkeypatch, every_tick_moves, read_cost_s=10.0, clock=clock)
    pairs = _parse(await _drive())
    errs = _of(pairs, "pipeline_error")
    assert [e["cause"] for e in errs] == ["ui_payload_timeout"], errs
    assert 900 <= clock["now"] <= 900 + 15 * 10.0, clock["now"]
    assert reads["n"] < 900, reads


# -- 9-10: the expected time -------------------------------------------------------------------

class _Session:
    def __init__(self, driver):
        self._d = driver

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self._d.calls.append((cypher, params))
        if self._d.error:
            raise self._d.error
        if self._d.hang:
            time.sleep(self._d.hang)
        return [{"duration_ms": d} for d in self._d.rows]


class _Driver:
    def __init__(self, rows=(), error=None, hang=0.0):
        self.rows, self.error, self.hang, self.calls = list(rows), error, hang, []

    def session(self):
        return _Session(self)


def _with_driver(monkeypatch, driver):
    monkeypatch.setattr(gw, "neo4j_driver", driver)
    for k in ("IAGENT_EXPECTED_SAMPLE", "IAGENT_EXPECTED_MIN"):
        monkeypatch.delenv(k, raising=False)


@pytest.mark.asyncio
async def test_expected_is_none_when_too_few_answers_are_recorded(monkeypatch):
    _with_driver(monkeypatch, _Driver(rows=[1000, 2000, 3000, 4000]))
    assert await gw._expected_ms("u-1") is None


@pytest.mark.asyncio
async def test_expected_is_the_median_of_the_callers_recorded_durations(monkeypatch):
    d = _Driver(rows=[9000, 1000, 5000, 3000, 7000, 100_000])
    _with_driver(monkeypatch, d)
    assert await gw._expected_ms("u-1") == 6000  # median of six: (5000 + 7000) / 2
    (cypher, params), = d.calls
    assert params == {"user_id": "u-1", "limit": 50}
    for word in ("PRODUCED_FOR", "complete", "duration_ms"):
        assert word in cypher, cypher
    assert cypher == gw.artifact_reads.RECENT_DURATIONS_CYPHER


@pytest.mark.asyncio
async def test_the_sample_and_minimum_follow_their_settings(monkeypatch):
    d = _Driver(rows=[1000, 2000, 3000])
    _with_driver(monkeypatch, d)
    monkeypatch.setenv("IAGENT_EXPECTED_SAMPLE", "3")
    monkeypatch.setenv("IAGENT_EXPECTED_MIN", "3")
    assert await gw._expected_ms("u-2") == 2000
    assert d.calls[0][1] == {"user_id": "u-2", "limit": 3}


@pytest.mark.asyncio
async def test_expected_is_none_when_the_read_raises(monkeypatch, caplog):
    _with_driver(monkeypatch, _Driver(error=RuntimeError("store down")))
    with caplog.at_level("WARNING"):
        assert await gw._expected_ms("u-1") is None
    assert any("RuntimeError" in r.getMessage() for r in caplog.records), caplog.records


@pytest.mark.asyncio
async def test_expected_is_none_when_the_read_hangs(monkeypatch):
    _with_driver(monkeypatch, _Driver(rows=[1000] * 9, hang=0.6))
    monkeypatch.setattr(gw, "_EXPECTED_READ_TIMEOUT_S", 0.05, raising=False)
    assert await gw._expected_ms("u-1") is None


@pytest.mark.parametrize("setting,fn,default", [
    ("IAGENT_EXPECTED_SAMPLE", "_expected_sample", 50),
    ("IAGENT_EXPECTED_MIN", "_expected_min", 5),
])
@pytest.mark.parametrize("raw,which", [("", "default"), ("7", 7), ("0", "default"),
                                       ("-3", "default"), ("x", "default")])
def test_the_expected_settings_read_with_a_default(monkeypatch, setting, fn, default, raw, which):
    monkeypatch.setenv(setting, raw)
    assert getattr(gw, fn)() == (default if which == "default" else which)


# -- 11: the control ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_CONTROL_a_run_that_keeps_moving_delivers_its_answer_with_one_timing(
    routed, clock, expected, monkeypatch
):
    _durable(monkeypatch, _moving, clock=clock)
    pairs = _parse(await _drive())
    assert _of(pairs, "final_payload") == [ANSWER]
    assert _of(pairs, "pipeline_error") == []
    assert len(_of(pairs, "answer_timing")) == 1


# -- 12-14: every end of the run poll closes an open "waiting" (74's review) -----------------

@pytest.mark.asyncio
async def test_a_launch_that_fails_fails_the_waiting_stage_and_the_error_is_bound_to_it(
    routed, clock, expected, monkeypatch
):
    """The run never started, so nothing was ever being located: `locating` is not shown, and
    the error is bound to `waiting`, the stage that failed."""
    _durable(monkeypatch, _stuck, clock=clock)  # sets the env; the transport is replaced below
    monkeypatch.setattr(gw, "_DURABLE_ANSWERS", DurableAnswers(
        "http://r:8080", snapshot_ttl_s=0,
        client_factory=lambda: _RealAsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(500, text="no")))))
    seq = _sequence(await _drive())
    errs = [e[1] for e in seq if e[0] == "pipeline_error"]
    assert [e["cause"] for e in errs] == ["dagster_launch_failed"], seq
    assert errs[0]["kind"] == "waiting", errs
    err = next(i for i, e in enumerate(seq) if e[0] == "pipeline_error")
    assert _at(seq, "waiting", "started")[0] < _at(seq, "waiting", "failed")[0] < err, seq
    assert not [e for e in seq if e[:2] == ("stage", "locating")], seq
    assert not [e for e in seq if e[0] == "answer_timing"], seq


@pytest.mark.asyncio
async def test_a_run_refused_busy_fails_the_waiting_stage(routed, clock, expected, monkeypatch):
    _durable(monkeypatch, lambda now, n: {"status": "BUSY", "busy": {"queue_max": 3},
                                          "events": [], "steps": [], "result": None}, clock=clock)
    seq = _sequence(await _drive())
    errs = [i for i, e in enumerate(seq) if e[0] == "pipeline_error"]
    assert [seq[i][1]["cause"] for i in errs] == ["answer_busy_queue_full"], seq
    assert _at(seq, "waiting", "failed")[0] < errs[0], seq
    assert ("stage", "waiting", "completed") not in seq, seq


@pytest.mark.asyncio
async def test_the_ceiling_with_no_step_ever_shown_fails_the_waiting_stage(
    routed, clock, expected, monkeypatch
):
    """The run moves (its events grow every read), so the stall bound never fires, but no step
    ever shows: the ceiling ends the stream, and the wait for the run to start failed."""
    _durable(monkeypatch, lambda now, n: {"status": "STARTED", "events": [{"e": i} for i in range(n)],
                                          "steps": [], "result": None},
             read_cost_s=10.0, clock=clock)
    seq = _sequence(await _drive())
    errs = [i for i, e in enumerate(seq) if e[0] == "pipeline_error"]
    assert [seq[i][1]["cause"] for i in errs] == ["ui_payload_timeout"], seq
    failed = _at(seq, "waiting", "failed")
    assert len(failed) == 1 and failed[0] < errs[0], seq
    assert not [e for e in seq if e[:2] == ("stage", "locating")], seq


# -- 15-16: the pre-launch admission queue (#422's wait) ---------------------------------------

from tests.perf.test_answer_admission import (  # noqa: E402,F401  (fixtures by name)
    _Resp, _adm_clock, _gate_full, _stream, _until, adm, mesh_env,
)


def _reasoned(blob):
    """Every event in order; a stage as (`stage`, kind, status, its detail's reason)."""
    return [("stage", d["kind"], d["status"], (d.get("detail") or {}).get("reason"))
            if n == "pipeline_stage" else (n,) for n, d in _parse(blob)]


@pytest.mark.asyncio
async def test_an_answer_queued_for_admission_shows_waiting_from_the_queue_to_its_admission(
        mesh_env, monkeypatch):
    _adm_clock(monkeypatch)          # a clock that never moves: the unreadable bound cannot fire
    adm.reset_gate_for_tests(1, 5)
    gate = _gate_full(("h",))
    m = mesh_env()
    task = asyncio.ensure_future(_stream(m))
    await _until(lambda: ("ev", "answer_queued") in m.log)
    gate.release("h")
    seq = _reasoned(await asyncio.wait_for(task, 10))
    start = seq.index(("stage", "waiting", "started", "queued"))
    done = seq.index(("stage", "waiting", "completed", "queued"))
    assert start < seq.index(("answer_queued",)) < done < seq.index(("answer_admitted",)), seq
    assert ("stage", "waiting", "failed", "queued") not in seq, seq


@pytest.mark.asyncio
async def test_an_admission_wait_that_cannot_be_read_fails_the_waiting_stage(
        mesh_env, monkeypatch):
    clk = _adm_clock(monkeypatch)
    adm.reset_gate_for_tests(1, 5)
    _gate_full(("h",))

    def after(handler, aid, mesh):
        if handler == "snapshot":
            clk["now"] += 1.0
            return _Resp(500, {})
        return None

    m = mesh_env(on_post=after)
    monkeypatch.setattr(gw, "_DURABLE_ANSWERS", DurableAnswers(
        "http://ingress", client_factory=m.client, snapshot_ttl_s=0.0))
    seq = _reasoned(await asyncio.wait_for(_stream(m), 10))
    failed = seq.index(("stage", "waiting", "failed", "queued"))
    assert failed < seq.index(("pipeline_error",)), seq
    assert ("stage", "waiting", "completed", "queued") not in seq, seq
