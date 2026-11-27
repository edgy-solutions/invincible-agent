"""A DURABLE ANSWER THAT STOPS MOVING ENDS IN THE FAILURE CARD, WITHIN A BOUND (architect, 2026-11-27).

Before: the stream's one deadline was 3600 ticks of 0.25 s. It counts ticks, not time, so reads
that hang stretch it without limit; and when it did run out, the stream ended in
`ui_payload_timeout`, which names neither the step nor the trace id. A typed question sat at its
second stage for over five minutes with no answer and no card.

Now: on the durable path, a run that does not move for `IAGENT_DURABLE_STALL_S` of wall time
ends in the failure card naming the step it is in and the trace id. Movement is read by high
water marks, so two views of the run taking turns are not movement; a run paused for its person
is waiting, not stalled.

DRIVEN THROUGH THE REAL ``_generate_dagster_stream_inner`` with a real ``DurableAnswers`` on a
mock transport. The clock is the stream's own `_stall_clock`, advanced by every sleep and, in one
case, by every read. THE CONTROL is a run that keeps moving for longer than the bound and then
succeeds: it delivers its answer and no card.

Run:  uv run --frozen python -m pytest tests/perf/test_a_stalled_durable_answer_ends_with_a_card.py -q
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.perf.test_a_failed_run_ends_with_a_card import (  # noqa: F401  (fixtures by name)
    TRACE, _RealAsyncClient, _drive, _of, _parse, base, stubbed_stream,
)

import iagent.gateway as gw  # noqa: E402
from src.iagent.durable_answers import DurableAnswers  # noqa: E402

_REAL_SLEEP = asyncio.sleep
STALL_S = 60
POLL_S = 0.25
ANSWER = {"components": [{"archetype": "TABLE", "marker": "answer"}]}
PLAN = {"stepKey": "create_task_plan", "status": "SUCCESS", "startTime": 0.0, "endTime": 1.0}
STUCK = {"stepKey": "locate_subject", "status": "RUNNING", "startTime": 1.0, "endTime": None}


@pytest.fixture
def clock(base, monkeypatch):
    """The stream's clock, advanced by its sleeps (the `base` fixture's sleep advances nothing)."""
    t = {"now": 0.0}

    async def _sleep(s=0, *a, **k):
        t["now"] += s
        await _REAL_SLEEP(0)

    monkeypatch.setattr(gw.asyncio, "sleep", _sleep)
    # raising=False: at code with no stall bound the tests fail on what the stream does, not here
    monkeypatch.setattr(gw, "_stall_clock", lambda: t["now"], raising=False)
    monkeypatch.setenv("IAGENT_DURABLE_STALL_S", str(STALL_S))
    return t


def _durable(monkeypatch, snapshot, *, read_cost_s=0.0, clock=None):
    """A real DurableAnswers whose snapshot is `snapshot(now, reads)`; each read may cost time."""
    launched, reads = {}, {"n": 0}

    def h(req):
        if req.url.path.endswith("/run/send"):
            launched["body"] = json.loads(req.content or b"null")
            return httpx.Response(202, json={})
        reads["n"] += 1
        if clock is not None:
            clock["now"] += read_cost_s
        snap = snapshot(clock["now"] if clock else 0.0, reads["n"])
        snap.setdefault("trace_id", (launched.get("body") or {}).get("trace_id"))
        return httpx.Response(200, json=snap)

    monkeypatch.setattr(gw, "_DURABLE_ANSWERS", DurableAnswers(
        "http://r:8080", snapshot_ttl_s=0,
        client_factory=lambda: _RealAsyncClient(transport=httpx.MockTransport(h))))
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "durable")
    return reads


def _stuck(now, n):
    return {"status": "STARTED", "events": [], "steps": [PLAN, STUCK], "result": None}


def _assert_stall_card(blob, bundles):
    pairs = _parse(blob)
    finals = _of(pairs, "final_payload")
    assert len(finals) == 1, blob[-2000:]
    comps = finals[0]["components"]
    assert len(comps) == 1 and comps[0]["archetype"] == "KNOWLEDGE_DOCUMENT"
    md = comps[0]["markdown_content"]
    assert "locate_subject" in md and TRACE in md, md
    errs = _of(pairs, "pipeline_error")
    assert len(errs) == 1, errs
    assert errs[0]["cause"] == "answer_run_stalled"
    assert errs[0]["failed_step"] == "locate_subject"
    assert errs[0]["trace_id"] == TRACE
    assert "ui_payload_timeout" not in blob
    assert bundles[-1]["status"] == "failed"


# -- the seal ---------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_durable_run_that_stops_moving_ends_in_the_card_naming_its_step_within_the_bound(
    base, clock, monkeypatch
):
    _durable(monkeypatch, _stuck, clock=clock)
    blob = await _drive()
    _assert_stall_card(blob, base["bundles"])
    assert STALL_S <= clock["now"] <= STALL_S + 2 * POLL_S, clock["now"]


@pytest.mark.asyncio
async def test_a_run_whose_every_read_is_refused_ends_in_the_card_within_the_bound(
    base, clock, monkeypatch
):
    """Lane 1's evidence (2026-11-27): every progress read refused with 400, each refusal
    swallowed, the question spinning with no card. A refused read is no movement seen. Nothing
    can be read, so the card says the step was not recorded and names this stream's trace id."""
    _durable(monkeypatch, _stuck, clock=clock)  # sets the env; the transport is replaced below
    monkeypatch.setattr(gw, "_DURABLE_ANSWERS", DurableAnswers(
        "http://r:8080", snapshot_ttl_s=0,
        client_factory=lambda: _RealAsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(202, json={}) if req.url.path.endswith("/run/send")
            else httpx.Response(400, text="Bad Request")))))
    blob = await _drive()
    pairs = _parse(blob)
    finals = _of(pairs, "final_payload")
    assert len(finals) == 1, blob[-2000:]
    md = finals[0]["components"][0]["markdown_content"]
    assert "not recorded" in md and TRACE in md, md
    errs = _of(pairs, "pipeline_error")
    assert len(errs) == 1 and errs[0]["cause"] == "answer_run_stalled", errs
    assert errs[0]["trace_id"] == TRACE and "failed_step" not in errs[0], errs[0]
    assert "ui_payload_timeout" not in blob
    assert base["bundles"][-1]["status"] == "failed"
    assert STALL_S <= clock["now"] <= STALL_S + 2 * POLL_S, clock["now"]


@pytest.mark.asyncio
async def test_reads_that_take_time_do_not_stretch_the_bound(base, clock, monkeypatch):
    """The bound is wall time: a tick whose reads take 10 s does not count as 0.25 s."""
    _durable(monkeypatch, _stuck, read_cost_s=10.0, clock=clock)
    blob = await _drive()
    _assert_stall_card(blob, base["bundles"])
    # one tick's reads past the bound at most (status, progress, events, steps, failure, payload)
    assert clock["now"] <= STALL_S + 10 * 10.0, clock["now"]


@pytest.mark.asyncio
async def test_two_views_taking_turns_are_not_movement(base, clock, monkeypatch):
    """The live view (ahead) and the durable snapshot (behind) answer by turns, a tick each."""
    def turns(now, n):
        if round(now / POLL_S) % 2:
            return {"status": "STARTED", "events": [{"e": 1}, {"e": 2}], "steps": [PLAN, STUCK],
                    "result": None}
        return {"status": "STARTED", "events": [{"e": 1}], "steps": [PLAN], "result": None}

    _durable(monkeypatch, turns, clock=clock)
    blob = await _drive()
    _assert_stall_card(blob, base["bundles"])
    assert clock["now"] <= STALL_S + 2 * POLL_S, clock["now"]


@pytest.mark.asyncio
async def test_the_card_names_the_step_the_watch_saw_when_the_last_read_does_not(
    base, clock, monkeypatch
):
    """The view that showed the step stops showing it (it is read from the one behind): the card
    names the step the watch saw in progress, not "not recorded"."""
    def drops(now, n):
        steps = [PLAN, STUCK] if now < 10 else [PLAN]
        return {"status": "STARTED", "events": [], "steps": steps, "result": None}

    _durable(monkeypatch, drops, clock=clock)
    blob = await _drive()
    _assert_stall_card(blob, base["bundles"])


@pytest.mark.asyncio
async def test_a_run_paused_for_its_person_is_waiting_not_stalled(base, clock, monkeypatch):
    """Ruled 2026-11-03: the pause does not count. Stuck and watched for 30 s, paused for 200 s,
    then stuck again: the card comes a full bound after the pause ends, not as it ends."""
    _durable(monkeypatch, _stuck, clock=clock)
    monkeypatch.setattr(gw.VAULT, "state",
                        lambda rid: "awaiting_reauth" if 30 <= clock["now"] < 230 else "live")
    blob = await _drive()
    _assert_stall_card(blob, base["bundles"])
    # the last paused tick restarts the clock, so the card is one bound after it, a tick or so early
    assert 230 + STALL_S - 2 * POLL_S <= clock["now"] <= 230 + STALL_S + 2 * POLL_S, clock["now"]


# -- the control ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_CONTROL_a_run_that_keeps_moving_past_the_bound_delivers_its_answer(
    base, clock, monkeypatch
):
    """A step every 10 s for 3 bounds, then SUCCESS: never stalled, so no card."""
    def moving(now, n):
        done = [{"stepKey": f"execute_subtask[{i}]", "status": "SUCCESS", "endTime": float(i)}
                for i in range(int(now // 10))]
        if now >= 3 * STALL_S:
            return {"status": "SUCCESS", "events": [], "steps": [PLAN, *done],
                    "result": {"payload": ANSWER, "referenced_uris": []}}
        return {"status": "STARTED", "events": [], "steps": [PLAN, *done], "result": None}

    _durable(monkeypatch, moving, clock=clock)
    blob = await _drive()
    pairs = _parse(blob)
    assert _of(pairs, "final_payload") == [ANSWER], blob[-2000:]
    assert _of(pairs, "pipeline_error") == []
    assert clock["now"] >= 3 * STALL_S


def test_the_dagster_path_has_no_stall_bound(monkeypatch):
    monkeypatch.delenv("IAGENT_ANSWER_PATH", raising=False)
    ab = gw._answer_backend()
    assert ab.stall_s is None and ab.progress is None


@pytest.mark.parametrize("raw,want", [("", 300.0), ("90", 90.0), ("0", 300.0), ("x", 300.0)])
def test_the_bound_is_read_from_its_setting(monkeypatch, raw, want):
    monkeypatch.setenv("IAGENT_DURABLE_STALL_S", raw)
    assert gw._durable_stall_s() == want


def test_the_stall_card_names_the_step_the_trace_and_the_wait():
    md = gw._failure_card("locate_subject", TRACE, stalled_s=61)["components"][0]["markdown_content"]
    assert "locate_subject" in md and TRACE in md and "61 seconds" in md
    md = gw._failure_card(None, None, stalled_s=61)["components"][0]["markdown_content"]
    assert "not recorded" in md and "no trace id" in md
