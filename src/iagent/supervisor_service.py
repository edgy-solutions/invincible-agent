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
"""
from __future__ import annotations

import logging
from typing import Any

import restate
from fastapi import FastAPI
from restate import WorkflowContext, WorkflowSharedContext
from restate.context import RunOptions

from src.iagent.runless import drop_live, live_sink, peek_live, run_answer

logger = logging.getLogger("iagent.supervisor_service")

supervisor_answer = restate.Workflow("SupervisorAnswer")


async def _gather_values(*futures: Any) -> list:
    """`restate.gather` waits (deterministically) and returns the futures; read each result."""
    done = await restate.gather(*futures)
    return [await f for f in done]


async def _run_impl(ctx: WorkflowContext, op_config: dict, *, gather=_gather_values,
                    ops: dict | None = None) -> dict:
    answer_id = ctx.key()

    def durable_step(name: str, fn):
        # max_attempts=1: a step that raised already recorded a FAILURE (run_step never
        # raises); a retry would replay side effects (engine calls, vault redeems).
        return ctx.run_typed(name, fn, RunOptions(max_attempts=1))

    def persist(snapshot: dict) -> None:
        ctx.set("snapshot", snapshot)

    try:
        return await run_answer(answer_id, op_config, durable_step=durable_step, persist=persist,
                                gather=gather, ops=ops, sink=live_sink(answer_id))
    finally:
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
    durable = await ctx.get("snapshot")
    return _merge_snapshot(durable, peek_live(ctx.key()))


app = FastAPI(title="supervisor-answer")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


app.mount("/restate", restate.app(services=[supervisor_answer]))
