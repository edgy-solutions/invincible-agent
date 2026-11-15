"""Run the five supervisor ops without a Dagster run.

A live answer is a short job: plan, fan out, synthesize and render in parallel, assert. On
Dagster each step pays for a process launch and a poll; here the same op BODIES run
unchanged, in this process, through a context adapter that speaks the few attributes they
use (`run_id`, `log`, `log_event`, `add_output_metadata`, the step key).

This module imports no Restate. `run_answer` takes the durable primitives as arguments
(`durable_step`, `persist`, `gather`), so the same orchestration runs under a Restate
workflow (`src/iagent/supervisor_service.py`) and under plain asyncio in the tests.

The records `run_step` returns are what Restate journals, so they are JSON and nothing else.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

from dagster import (
    AssetMaterialization,
    BoolMetadataValue,
    DynamicOutput,
    Failure,
    FloatMetadataValue,
    IntMetadataValue,
    JsonMetadataValue,
    Output,
    TextMetadataValue,
)

logger = logging.getLogger("iagent.runless")


# --------------------------------------------------------------------------- metadata


def metadata_entries(md: Mapping[str, Any] | None) -> list[dict]:
    """A Dagster metadata dict in the entry shape the BFF's GraphQL read returns.

    The BFF's `_get_run_events` fetches exactly five value fragments (text, json, float, int,
    bool). Any other value type (markdown, path, url...) therefore reached the BFF as a bare
    `{"label"}`; it does here too."""
    out: list[dict] = []
    for k, v in (md or {}).items():
        # Raw values first, the way Dagster normalises them. bool BEFORE int: True is an int.
        if isinstance(v, bool):
            out.append({"label": k, "boolValue": v})
        elif isinstance(v, int):
            out.append({"label": k, "intValue": v})
        elif isinstance(v, float):
            out.append({"label": k, "floatValue": v})
        elif isinstance(v, str):
            out.append({"label": k, "text": v})
        elif isinstance(v, (dict, list)):
            out.append({"label": k, "jsonString": json.dumps(v)})
        elif isinstance(v, BoolMetadataValue):
            out.append({"label": k, "boolValue": v.value})
        elif isinstance(v, IntMetadataValue):
            out.append({"label": k, "intValue": v.value})
        elif isinstance(v, FloatMetadataValue):
            out.append({"label": k, "floatValue": v.value})
        elif isinstance(v, TextMetadataValue):
            out.append({"label": k, "text": v.text})
        elif isinstance(v, JsonMetadataValue):
            out.append({"label": k, "jsonString": json.dumps(v.data)})
        else:
            out.append({"label": k})
    return out


# --------------------------------------------------------------------------- live view


class LiveSink:
    """One answer's live view: events and step records as they happen. Thread-safe, because
    the ops run in executor threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list = []
        self.steps: dict[str, dict] = {}

    def event(self, ev: dict) -> None:
        with self._lock:
            self.events.append(ev)

    def step(self, record: dict) -> None:
        rec = {k: v for k, v in record.items() if k not in ("value", "outputs")}
        with self._lock:
            self.steps[rec["stepKey"]] = rec

    def view(self) -> tuple[list, dict]:
        with self._lock:
            return list(self.events), dict(self.steps)


_LIVE_CAP = 256
_live: "OrderedDict[str, LiveSink]" = OrderedDict()
_live_lock = threading.Lock()


def live_sink(answer_id: str) -> LiveSink:
    """Get or create the sink for an answer. Capped, oldest evicted, so a crashed run cannot
    leak for ever."""
    with _live_lock:
        sink = _live.get(answer_id)
        if sink is None:
            sink = _live[answer_id] = LiveSink()
            while len(_live) > _LIVE_CAP:
                _live.popitem(last=False)
        return sink


def peek_live(answer_id: str) -> LiveSink | None:
    with _live_lock:
        return _live.get(answer_id)


def drop_live(answer_id: str) -> None:
    with _live_lock:
        _live.pop(answer_id, None)


# --------------------------------------------------------------------------- the context


class _PrefixAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[answer={self.extra['answer']} step={self.extra['step']}] {msg}", kwargs


class RunlessOpContext:
    """The slice of Dagster's op context the supervisor ops use. A plain class: an attribute
    the ops do not use is an AttributeError here, not a silent None."""

    def __init__(self, *, answer_id: str, op_name: str, step_key: str,
                 mapping_key: str | None, sink: LiveSink) -> None:
        self.run_id = answer_id
        self.op = SimpleNamespace(name=op_name)
        self._mapping_key = mapping_key
        self._step_key = step_key
        self._sink = sink
        self.log = _PrefixAdapter(logger, {"answer": answer_id, "step": step_key})
        self.step_events: list[dict] = []
        self.output_metadata: list[dict] = []

    def get_mapping_key(self) -> str | None:
        return self._mapping_key

    def get_step_execution_context(self):
        return SimpleNamespace(step=SimpleNamespace(key=self._step_key))

    def log_event(self, event: Any) -> None:
        if isinstance(event, AssetMaterialization):
            ev = {
                "assetKey": {"path": list(event.asset_key.path)},
                "metadataEntries": metadata_entries(event.metadata),
            }
            self.step_events.append(ev)
            self._sink.event(ev)
        else:
            logger.debug("runless: dropped %s event", type(event).__name__)

    def add_output_metadata(self, metadata, output_name=None, mapping_key=None) -> None:
        self.output_metadata.extend(metadata_entries(metadata))


# --------------------------------------------------------------------------- one step


def run_step(op_def, *, answer_id: str, op_name: str, step_key: str,
             mapping_key: str | None = None, config=None, inputs: dict | None = None,
             sink: LiveSink) -> dict:
    """Run one op body and return a JSON record. NEVER raises."""
    start = time.time()
    ctx = RunlessOpContext(answer_id=answer_id, op_name=op_name, step_key=step_key,
                           mapping_key=mapping_key, sink=sink)
    rec: dict = {"stepKey": step_key, "status": "FAILURE", "startTime": start, "endTime": start,
                 "events": [], "output_metadata": [], "value": None, "outputs": [],
                 "error": None, "failure_metadata": []}
    try:
        sink.step({"stepKey": step_key, "status": "RUNNING", "startTime": start, "endTime": None})
    except Exception:  # noqa: BLE001 -- a sink fault must not fail the step
        logger.exception("sink.step failed at start of %s", step_key)
    value: Any = None
    outputs: list = []
    try:
        kwargs = dict(inputs or {})
        if config is not None:
            kwargs["config"] = config
        result = op_def.compute_fn.decorated_fn(ctx, **kwargs)

        def absorb(item: Any) -> None:
            nonlocal value
            if isinstance(item, DynamicOutput):
                outputs.append([mapping_key if item.mapping_key is None else item.mapping_key,
                                item.value])
            elif isinstance(item, Output):
                value = item.value
                ctx.output_metadata.extend(metadata_entries(item.metadata))
            elif isinstance(item, AssetMaterialization):
                ctx.log_event(item)
            else:
                logger.debug("runless: dropped %s from %s", type(item).__name__, step_key)

        if hasattr(result, "__next__"):
            for item in result:
                absorb(item)
        elif isinstance(result, Output):
            absorb(result)
        else:
            value = result
        rec.update(status="SUCCESS", value=value, outputs=outputs)
    except Failure as exc:
        rec.update(error=exc.description, failure_metadata=metadata_entries(exc.metadata))
    except Exception as exc:  # noqa: BLE001 -- the contract is "never raises"
        ctx.log.exception("step failed")
        rec.update(error=f"{type(exc).__name__}: {exc}")
    rec.update(events=ctx.step_events, output_metadata=ctx.output_metadata, endTime=time.time())
    if rec["status"] == "SUCCESS":
        try:
            json.dumps(rec)
        except (TypeError, ValueError) as exc:
            rec.update(status="FAILURE", value=None, outputs=[],
                       error=f"NonJsonValue: {step_key} produced a value Restate cannot journal: {exc}")
    try:
        sink.step(rec)
    except Exception:  # noqa: BLE001
        logger.exception("sink.step failed at end of %s", step_key)
    return rec


# --------------------------------------------------------------------------- the answer


def _default_ops() -> dict:
    # Lazy: the supervisor module is large and drags the fleet's clients in.
    from src.iagent.defs import dynamic_supervisor as ds

    return {
        "create_task_plan": ds.create_task_plan,
        "execute_subtask": ds.execute_subtask,
        "synthesize_stateful": ds.synthesize_stateful,
        "generate_ui_payload": ds.generate_ui_payload,
        "assert_every_engine_answered": ds.assert_every_engine_answered,
    }


def _config(op_config: dict):
    from src.iagent.defs import dynamic_supervisor as ds

    return ds.SupervisorQueryConfig(**op_config)


def _referenced_uris(render: dict) -> list:
    for e in render.get("output_metadata", []):
        if e.get("label") == "referenced_uris" and "jsonString" in e:
            try:
                return json.loads(e["jsonString"])
            except ValueError:
                return []
    return []


async def run_answer(answer_id: str, op_config: dict, *, durable_step, persist,
                     gather=asyncio.gather, ops: dict | None = None,
                     sink: LiveSink | None = None) -> dict:
    """plan -> subtasks (parallel) -> synth + render (parallel) -> assert.

    `durable_step(name, fn)` runs a sync `fn() -> dict` once and returns an awaitable of its
    JSON result; `persist(snapshot)` stores the snapshot (sync or async); `gather` awaits
    several durable_step results at once and returns their values in order."""
    ops = ops or _default_ops()
    sink = sink or live_sink(answer_id)
    make_cfg = _config
    steps: list[dict] = []
    events: list = []
    state: dict = {"status": "STARTED", "t_start": None, "steps": steps, "events": events,
                   "result": None, "error": None}

    def view(rec: dict) -> dict:
        return {k: v for k, v in rec.items() if k not in ("value", "outputs")}

    async def save() -> dict:
        snap = {**state, "steps": list(steps), "events": list(events)}
        r = persist(snap)
        if asyncio.iscoroutine(r) or isinstance(r, asyncio.Future):
            await r
        return snap

    def absorb(recs: list[dict]) -> None:
        for rec in recs:
            steps.append(view(rec))
            events.extend(rec["events"])

    def step(name, op_name, step_key, *, mapping_key=None, inputs=None, with_config=True):
        def fn() -> dict:
            return run_step(ops[op_name], answer_id=answer_id, op_name=op_name,
                            step_key=step_key, mapping_key=mapping_key,
                            config=make_cfg(op_config) if with_config else None,
                            inputs=inputs, sink=sink)
        return durable_step(name, fn)

    async def finish(error: str | None) -> dict:
        state["status"] = "FAILURE"
        state["error"] = error
        return await save()

    t = await durable_step("t_start", lambda: {"t": time.time()})
    state["t_start"] = t["t"]
    await save()

    plan = await step("create_task_plan", "create_task_plan", "create_task_plan")
    absorb([plan])
    if plan["status"] != "SUCCESS":
        return await finish(plan["error"])
    await save()

    tasks = plan["outputs"]
    subs = await gather(*[
        step(f"execute_subtask[{mk}]", "execute_subtask", f"execute_subtask[{mk}]",
             mapping_key=mk, inputs={"task_def": task})
        for mk, task in tasks])
    absorb(list(subs))
    bad = [r for r in subs if r["status"] != "SUCCESS"]
    if bad:
        return await finish(bad[0]["error"])
    results = [r["value"] for r in subs]
    await save()

    synth, render = await gather(
        step("synthesize_stateful", "synthesize_stateful", "synthesize_stateful",
             inputs={"results": results}),
        step("generate_ui_payload", "generate_ui_payload", "generate_ui_payload",
             inputs={"results": results}))
    absorb([synth, render])
    if synth["status"] != "SUCCESS" or render["status"] != "SUCCESS":
        return await finish(synth["error"] if synth["status"] != "SUCCESS" else render["error"])
    state["result"] = {"payload": render["value"], "referenced_uris": _referenced_uris(render)}
    await save()

    check = await step("assert_every_engine_answered", "assert_every_engine_answered",
                       "assert_every_engine_answered", with_config=False,
                       inputs={"results": results, "ui_payload": render["value"]})
    absorb([check])
    if check["status"] != "SUCCESS":
        return await finish(check["error"])
    state["status"] = "SUCCESS"
    return await save()
