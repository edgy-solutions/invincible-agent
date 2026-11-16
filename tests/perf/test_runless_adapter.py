"""Answers off Dagster: the adapter and the in-process orchestration. No network."""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

from dagster import (AssetMaterialization, DynamicOut, DynamicOutput, Failure, MetadataValue,
                     Output, op)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402
from src.iagent.runless import (LiveSink, RunlessOpContext, metadata_entries, run_answer,  # noqa: E402
                                run_step)
from src.iagent.trace_spans import step_spanned  # noqa: E402
from src.iagent.defs.dynamic_supervisor import SupervisorQueryConfig  # noqa: E402

CFG = {"user_query": "q", "thread_id": "t"}
GATEWAY = (ROOT / "src/iagent/gateway.py").read_text(encoding="utf-8")


def _fetched_value_keys() -> "set[str]":
    body = GATEWAY[GATEWAY.index("async def _get_run_events"):GATEWAY.index("async def _get_step_stats")]
    return set(re.findall(r"\.\.\. on \w+MetadataEntry \{ (\w+) \}", body))


# 1 ------------------------------------------------------------------ metadata_entries
def test_metadata_entries_every_value_class_and_raw_value():
    md = {
        "t": MetadataValue.text("x"), "j": MetadataValue.json({"a": 1}),
        "f": MetadataValue.float(1.5), "i": MetadataValue.int(3), "b": MetadataValue.bool(False),
        "rt": "s", "rj": [1], "rd": {"k": 1}, "rf": 2.5, "ri": 7, "rb": True,
        "md": MetadataValue.md("# hi"),
    }
    got = {e["label"]: e for e in metadata_entries(md)}
    assert got["t"] == {"label": "t", "text": "x"}
    assert got["j"] == {"label": "j", "jsonString": json.dumps({"a": 1})}
    assert got["f"] == {"label": "f", "floatValue": 1.5}
    assert got["i"] == {"label": "i", "intValue": 3}
    assert got["b"] == {"label": "b", "boolValue": False}
    assert got["rt"] == {"label": "rt", "text": "s"}
    assert got["rj"] == {"label": "rj", "jsonString": "[1]"}
    assert got["rd"] == {"label": "rd", "jsonString": '{"k": 1}'}
    assert got["rf"] == {"label": "rf", "floatValue": 2.5}
    assert got["ri"] == {"label": "ri", "intValue": 7}
    assert got["rb"] == {"label": "rb", "boolValue": True}  # not intValue
    assert got["md"] == {"label": "md"}
    keys = {k for e in got.values() for k in e if k != "label"}
    assert len(_fetched_value_keys()) == 5 and keys <= _fetched_value_keys()
    assert metadata_entries(None) == []


# 2 ------------------------------------------------------------------ run_step
@op(out=DynamicOut())
def _gen_op(context):
    context.log_event(AssetMaterialization(asset_key=["roster"], metadata={"n": 2}))
    yield DynamicOutput({"a": 1}, mapping_key="task_0")
    yield DynamicOutput({"b": 2}, mapping_key="task_1")


@op
def _out_op(context, x):
    context.add_output_metadata({"seen": "yes"})
    yield Output({"v": x}, metadata={"referenced_uris": MetadataValue.json(["u"])})


@op
@step_spanned("test.step")
def _spanned_op(context, config: SupervisorQueryConfig):
    return {"ok": True}


@op
def _fail_op(context):
    raise Failure(description="nope", metadata={"n": MetadataValue.int(1)})


@op
def _err_op(context):
    raise ValueError("bad")


@op
def _nonjson_op(context):
    return {"x": object()}


def _rs(o, **kw):
    sink = kw.pop("sink", None) or LiveSink()
    rec = run_step(o, answer_id="A", op_name=o.name, step_key=kw.pop("step_key", o.name),
                   sink=sink, **kw)
    assert json.loads(json.dumps(rec)) == rec
    return rec, sink


def test_run_step_generator_outputs_events_sink():
    rec, sink = _rs(_gen_op)
    assert rec["status"] == "SUCCESS"
    assert rec["outputs"] == [["task_0", {"a": 1}], ["task_1", {"b": 2}]]
    ev = {"assetKey": {"path": ["roster"]}, "metadataEntries": [{"label": "n", "intValue": 2}]}
    assert rec["events"] == [ev] and sink.events == [ev]
    assert sink.steps["_gen_op"]["status"] == "SUCCESS" and "outputs" not in sink.steps["_gen_op"]


def test_run_step_output_and_added_metadata():
    rec, _ = _rs(_out_op, inputs={"x": 5})
    assert rec["value"] == {"v": 5}
    assert {e["label"] for e in rec["output_metadata"]} == {"seen", "referenced_uris"}


def test_run_step_spanned_op_runs_through_wrapper():
    rec, _ = _rs(_spanned_op, config=ds.SupervisorQueryConfig(**CFG))
    assert rec["status"] == "SUCCESS" and rec["value"] == {"ok": True}


def test_run_step_failure_error_and_nonjson():
    rec, _ = _rs(_fail_op)
    assert rec["status"] == "FAILURE" and rec["error"] == "nope"
    assert rec["failure_metadata"] == [{"label": "n", "intValue": 1}]
    rec, _ = _rs(_err_op)
    assert rec["status"] == "FAILURE" and rec["error"] == "ValueError: bad"
    rec, _ = _rs(_nonjson_op)
    assert rec["status"] == "FAILURE" and rec["error"].startswith("NonJsonValue")


# 3 ------------------------------------------------------------------ the real _step_key
def test_real_step_key_and_run_id():
    ctx = RunlessOpContext(answer_id="ans", op_name="execute_subtask",
                           step_key="execute_subtask[task_0]", mapping_key="task_0", sink=LiveSink())
    assert ds._step_key(ctx) == "execute_subtask[task_0]"
    assert getattr(ctx, "run_id") == "ans"


# 4 ------------------------------------------------------------------ the real assert op
def _res(status):
    return {"predicate_verb_iri": "v", "expert_response": {"status": status, "error": "down"}}


def test_real_assert_op_through_run_step():
    rec, _ = _rs(ds.assert_every_engine_answered,
                 inputs={"results": [_res("engine_unreachable"), _res("ok")], "ui_payload": {}})
    assert rec["status"] == "FAILURE"
    assert {"label": "unreachable_subtasks", "intValue": 1} in rec["failure_metadata"]
    rec, _ = _rs(ds.assert_every_engine_answered, inputs={"results": [_res("ok")], "ui_payload": {}})
    assert rec["status"] == "SUCCESS"


# ------------------------------------------------------------------ orchestration (fakes)

STEP_LOG: list = []


def _mk(fn, name):
    cf = type("CF", (), {"decorated_fn": staticmethod(fn)})()
    return type("Op", (), {"name": name, "compute_fn": cf})()


def fake_ops(sleep=0.0, fail_subtask=None, unreachable=False, slow_first=False, hook=None):
    def plan(context, config):
        yield AssetMaterialization(asset_key=["active_agent_roster"])
        for i in range(2):
            yield DynamicOutput({"i": i}, mapping_key=f"task_{i}")

    def sub(context, config, task_def):
        STEP_LOG.append(("sub", task_def["i"]))
        time.sleep(0.35 if (slow_first and task_def["i"] == 0) else sleep)
        if fail_subtask == task_def["i"]:
            raise Failure("sub boom")
        return {"i": task_def["i"], "expert_response": {
            "status": "engine_unreachable" if unreachable else "ok"}}

    def synth(context, config, results):
        STEP_LOG.append(("synth", [r["i"] for r in results]))
        time.sleep(sleep)
        return {"s": 1}

    def render(context, config, results):
        STEP_LOG.append(("render", [r["i"] for r in results]))
        time.sleep(sleep)
        if hook:
            hook(context)
        yield Output({"ui": 1}, metadata={"referenced_uris": MetadataValue.json(["u1"])})

    def check(context, results, ui_payload):
        STEP_LOG.append(("check", ui_payload))
        ds.assert_every_engine_answered.compute_fn.decorated_fn(
            context, results=results, ui_payload=ui_payload)

    return {"create_task_plan": _mk(plan, "create_task_plan"),
            "execute_subtask": _mk(sub, "execute_subtask"),
            "synthesize_stateful": _mk(synth, "synthesize_stateful"),
            "generate_ui_payload": _mk(render, "generate_ui_payload"),
            "assert_every_engine_answered": _mk(check, "assert_every_engine_answered")}


async def _thread_step(name, fn):
    return await asyncio.to_thread(fn)


async def _go(ops, snaps=None, cfg=None):
    STEP_LOG.clear()
    snaps = [] if snaps is None else snaps
    out = await run_answer("ans", cfg or CFG, durable_step=_thread_step, persist=snaps.append,
                           ops=ops, sink=LiveSink())
    return out, snaps


def _keys(out):
    return [s["stepKey"] for s in out["steps"]]


def test_order_and_dagster_step_keys():
    out, _ = asyncio.run(_go(fake_ops()))
    assert out["status"] == "SUCCESS"
    assert _keys(out) == ["create_task_plan", "execute_subtask[task_0]", "execute_subtask[task_1]",
                          "synthesize_stateful", "generate_ui_payload", "assert_every_engine_answered"]
    assert out["result"] == {"payload": {"ui": 1}, "referenced_uris": ["u1"]}
    assert out["events"][0]["assetKey"]["path"] == ["active_agent_roster"]


def test_subtasks_run_in_parallel():
    t0 = time.time()
    out, _ = asyncio.run(_go(fake_ops(sleep=0.4)))
    assert out["status"] == "SUCCESS"
    st = [s for s in out["steps"] if s["stepKey"].startswith("execute_subtask")]
    assert max(s["endTime"] for s in st) - min(s["startTime"] for s in st) < 0.7
    both = [s for s in out["steps"] if s["stepKey"] in ("synthesize_stateful", "generate_ui_payload")]
    assert max(s["endTime"] for s in both) - min(s["startTime"] for s in both) < 0.7
    assert time.time() - t0 < 1.6  # serial would be 0.8 + 0.8 plus overhead


def test_failed_subtask_skips_downstream():
    out, _ = asyncio.run(_go(fake_ops(fail_subtask=1)))
    assert out["status"] == "FAILURE" and out["error"] == "sub boom"
    assert not {"synthesize_stateful", "generate_ui_payload",
                "assert_every_engine_answered"} & set(_keys(out))


def test_assert_failure_keeps_the_payload():
    out, _ = asyncio.run(_go(fake_ops(unreachable=True)))
    assert out["status"] == "FAILURE"
    assert out["result"]["payload"] == {"ui": 1}
    assert "generate_ui_payload" in _keys(out)


# The failure card (ADR-0072 8.1, ruled 2026-11-15) names the failed step and the trace id; the
# BFF reads both from the snapshot's `failed_step` and `trace_id`.
TID = "4bf92f3577b34da6a3ce929d0e0e4736"


def test_failed_snapshot_names_the_failed_step_and_the_trace():
    out, snaps = asyncio.run(_go(fake_ops(fail_subtask=1), cfg={**CFG, "trace_id": TID}))
    assert out["status"] == "FAILURE"
    assert out["failed_step"] == "execute_subtask[task_1]"
    assert out["trace_id"] == TID
    assert all(s["trace_id"] == TID for s in snaps)  # every snapshot, not only the last


def test_failed_check_names_its_step_and_keeps_the_payload():
    out, _ = asyncio.run(_go(fake_ops(unreachable=True), cfg={**CFG, "trace_id": TID}))
    assert out["failed_step"] == "assert_every_engine_answered"
    assert out["result"]["payload"] == {"ui": 1} and out["trace_id"] == TID


def test_success_names_no_failed_step_and_no_trace_without_one():
    out, _ = asyncio.run(_go(fake_ops()))
    assert out["status"] == "SUCCESS" and out["failed_step"] is None
    assert out["trace_id"] is None  # CFG carries no trace id: None, never ""


def test_persist_after_every_stage_and_last_equals_return():
    out, snaps = asyncio.run(_go(fake_ops()))
    assert len(snaps) >= 5 and snaps[-1] == out
    assert all(s["status"] == "STARTED" for s in snaps[:-1])


def test_results_reach_synth_and_render_in_plan_order():
    asyncio.run(_go(fake_ops(slow_first=True)))
    assert ("synth", [0, 1]) in STEP_LOG and ("render", [0, 1]) in STEP_LOG
