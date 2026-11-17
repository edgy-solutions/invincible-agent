"""Answers off Dagster: the Restate binding, with a fake WorkflowContext. No Restate runtime."""
import asyncio
import subprocess
import sys
import threading
from pathlib import Path

from dagster import AssetMaterialization, MetadataValue, Output

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.iagent import supervisor_service as svc  # noqa: E402
from src.iagent.runless import live_sink  # noqa: E402

from tests.perf.test_runless_adapter import fake_ops, _mk  # noqa: E402

CFG = {"user_query": "q", "thread_id": "t"}


class FakeCtx:
    def __init__(self, key):
        self._key, self.state, self.runs = key, {}, []

    def key(self):
        return self._key

    def run_typed(self, name, fn, options=None, /, *a, **kw):
        self.runs.append((name, getattr(options, "max_attempts", None)))
        return asyncio.ensure_future(asyncio.to_thread(fn, *a, **kw))

    run = run_typed

    async def get(self, k):
        return self.state.get(k)

    def set(self, k, v):
        self.state[k] = v


def test_run_impl_journals_each_step_once_and_persists():
    ctx = FakeCtx("k1")
    out = asyncio.run(svc._run_impl(ctx, CFG, gather=asyncio.gather, ops=fake_ops()))
    assert out["status"] == "SUCCESS" and ctx.state["snapshot"] == out
    assert all(attempts == 1 for _, attempts in ctx.runs)
    names = [n for n, _ in ctx.runs]
    assert names[0] == "t_start" and "execute_subtask[task_1]" in names
    from src.iagent.runless import peek_live
    assert peek_live("k1") is None  # dropped in finally


def test_snapshot_serves_live_mid_run_then_durable_and_queued():
    started, release = threading.Event(), threading.Event()
    ops = fake_ops()

    def blocking_render(context, config, results):
        context.log_event(AssetMaterialization(asset_key=["mid_run"], metadata={"n": 1}))
        started.set()
        release.wait(5)
        yield Output({"ui": 1})

    ops["generate_ui_payload"] = _mk(blocking_render, "generate_ui_payload")

    async def scenario():
        ctx = FakeCtx("k2")
        task = asyncio.create_task(svc._run_impl(ctx, CFG, gather=asyncio.gather, ops=ops))
        await asyncio.to_thread(started.wait, 5)
        mid = await svc.snapshot(_Shared(ctx))
        release.set()
        final = await task
        after = await svc.snapshot(_Shared(ctx))
        unknown = await svc.snapshot(_Shared(FakeCtx("nope")))
        return mid, final, after, unknown

    mid, final, after, unknown = asyncio.run(scenario())
    assert mid["status"] == "STARTED"
    assert ["mid_run"] in [e["assetKey"]["path"] for e in mid["events"]]
    assert after == final and after["status"] == "SUCCESS"
    assert unknown == {"status": "QUEUED", "events": [], "steps": [], "result": None}


class _Shared:
    """A shared context over another context's state, keyed the same."""
    def __init__(self, ctx):
        self._c = ctx

    def key(self):
        return self._c.key()

    async def get(self, k):
        return await self._c.get(k)


def test_app_imports_serves_healthz_and_does_not_import_the_supervisor():
    from fastapi.testclient import TestClient
    r = TestClient(svc.app).get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}
    code = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); from src.iagent.supervisor_service import app; "
            "assert 'src.iagent.defs.dynamic_supervisor' not in sys.modules; print('clean')")
    p = subprocess.run([sys.executable, "-I", "-c", code], cwd=str(ROOT), capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 0 and "clean" in p.stdout, p.stderr[-800:]
