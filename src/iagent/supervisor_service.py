"""SupervisorAnswer: one live answer as one Restate workflow, in place of a Dagster run.

Run as `uvicorn src.iagent.supervisor_service:app` -- the control-plane image (the one cortex-bff
runs in; `.github/docker/Dockerfile.agent`, whole-repo copy, PYTHONPATH=/app) imports the gateway
as `src.iagent.gateway`, so this module is `src.iagent.supervisor_service`. The Restate admin
registers `<this service>/restate`.

Importing this module does NOT import the supervisor (`run_answer` does, lazily), so the health
route and the registration come up without the fleet's clients.

The BFF reaches it through `src/iagent/durable_answers.py`:
  POST /SupervisorAnswer/{answer_id}/run/send   -> the workflow
  POST /SupervisorAnswer/{answer_id}/snapshot   -> the poll read
  POST /SupervisorAnswer/{answer_id}/withdraw   -> take a still-waiting answer out of the queue

At most IAGENT_ANSWER_LIMIT answers run at once (`answer_admission`, ADR-0072 5); the rest wait
in arrival order, and their snapshot reads QUEUED with their place.
"""
from __future__ import annotations

import logging
import time
from contextlib import nullcontext
from typing import Any

import restate
from fastapi import FastAPI
from restate import WorkflowContext, WorkflowSharedContext
from restate.context import RunOptions

from src.iagent import trace_spans as ts
from src.iagent.answer_admission import AdmissionWithdrawn, get_gate
from src.iagent.runless import drop_live, live_sink, peek_live, run_answer

logger = logging.getLogger("iagent.supervisor_service")

supervisor_answer = restate.Workflow("SupervisorAnswer")


async def _gather_values(*futures: Any) -> list:
    """`restate.gather` waits (deterministically) and returns the futures; read each result."""
    done = await restate.gather(*futures)
    return [await f for f in done]


def _enter(answer_id: str) -> dict:
    now = time.time()
    return {"arrived_at": now, "decision": get_gate().try_enter(answer_id, now)}


async def _run_impl(ctx: WorkflowContext, op_config: dict, *, gather=_gather_values,
                    ops: dict | None = None) -> dict:
    answer_id = ctx.key()

    def durable_step(name: str, fn):
        # max_attempts=1: a step that raised already recorded a FAILURE (run_step never
        # raises); a retry would replay side effects (engine calls, vault redeems).
        return ctx.run_typed(name, fn, RunOptions(max_attempts=1))

    def persist(snapshot: dict) -> None:
        ctx.set("snapshot", snapshot)

    # Admission (ADR-0072 5). The decision is JOURNALED first: on a replay the stored dict comes
    # back and `_enter` does not run, so a restarted answer keeps its first arrival time and its
    # "admitted"/"queued" decision, and is never re-checked against a full queue.
    adm = await ctx.run_typed("admission", lambda: _enter(answer_id), RunOptions(max_attempts=1))
    gate = get_gate()
    if adm["decision"] == "busy":
        refused = gate.refused(answer_id) or {"reason": "queue_full", **gate.state()}
        busy = {"reason": refused["reason"], "limit": refused.get("limit"),
                "queue_max": refused.get("queue_max")}
        persist({"status": "BUSY", "events": [], "steps": [], "result": None, "busy": busy})
        return {"busy": True}

    # The wait is its own span, emitted on every answer (even one admitted at once), metadata only.
    arrived_at = adm["arrived_at"]
    restarted = not gate.knows(answer_id)
    if restarted:
        gate.reenter(answer_id, arrived_at)
    position_at_entry = gate.position(answer_id) or 0
    limit = gate.state()["limit"]
    t0 = time.monotonic()
    trace_id = op_config.get("trace_id") or ""
    span = (ts.observed_trace(
        ts.MAPPING,
        ts.build_trace_values(trace_id=trace_id, session_id=op_config.get("session_id") or None,
                              engine="supervisor", verb="supervisor.queue_wait"),
        name="supervisor.queue_wait",
        parent_span_id=op_config.get("parent_span_id") or None,
    ) if trace_id else nullcontext())
    try:
        try:
            with span:
                try:
                    await gate.acquire(answer_id, arrived_at)
                finally:
                    ts.annotate_span(position_at_entry=position_at_entry, limit=limit,
                                     waited_ms=int((time.monotonic() - t0) * 1000),
                                     restarted=restarted)
        except AdmissionWithdrawn:
            persist({"status": "CANCELED", "events": [], "steps": [], "result": None,
                     "withdrawn": True})
            return {"withdrawn": True}
        return await run_answer(answer_id, op_config, durable_step=durable_step, persist=persist,
                                gather=gather, ops=ops, sink=live_sink(answer_id))
    finally:
        # A suspended or cancelled attempt leaves nothing behind: its queue place or its slot.
        gate.leave(answer_id)
        drop_live(answer_id)


@supervisor_answer.main()
async def run(ctx: WorkflowContext, op_config: dict) -> dict:
    return await _run_impl(ctx, op_config)


def _merge_snapshot(durable: dict | None, live) -> dict:
    """The durable snapshot, unless the in-process live view is AHEAD of it (more events, or a
    step the durable one lacks): then serve the live events and steps, status STARTED."""
    if live is not None:
        events, steps = live.view()
    else:
        events, steps = [], {}
    if durable is None:
        if not events and not steps:
            return {"status": "QUEUED", "events": [], "steps": [], "result": None}
        return {"status": "STARTED", "events": events, "steps": list(steps.values()),
                "result": None}
    have = {s["stepKey"] for s in durable.get("steps", [])}
    ahead = len(events) > len(durable.get("events", [])) or any(k not in have for k in steps)
    if ahead:
        return {**durable, "status": "STARTED", "events": events, "steps": list(steps.values())}
    return durable


# I (to verify on sandbox): (1) that a shared handler can run while `run` is mid-flight and
# see state, here the in-process live sink rather than Restate state, since ctx.set inside
# `run` is only visible after the journal entry; (2) the single-replica assumption behind the
# live sink: with two replicas the snapshot may land on the one not running the answer, and
# then only the durable (per-stage) snapshot is served.
@supervisor_answer.handler()
async def snapshot(ctx: WorkflowSharedContext) -> dict:
    gate = get_gate()
    pos = gate.position(ctx.key())
    if pos is not None:
        return {"status": "QUEUED", "events": [], "steps": [], "result": None,
                "queue": {"position": pos, "ahead": pos - 1, **gate.state()}}
    durable = await ctx.get("snapshot")
    refused = gate.refused(ctx.key())
    if refused is not None and durable is None:
        # Refused at entry: say so at once, without waiting for the journal.
        return {"status": "BUSY", "events": [], "steps": [], "result": None, "busy": refused}
    return _merge_snapshot(durable, peek_live(ctx.key()))


@supervisor_answer.handler()
async def withdraw(ctx: WorkflowSharedContext) -> dict:
    return {"withdrawn": get_gate().withdraw(ctx.key())}


app = FastAPI(title="supervisor-answer")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


app.mount("/restate", restate.app(services=[supervisor_answer]))
