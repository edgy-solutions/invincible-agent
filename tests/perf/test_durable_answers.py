"""Answers off Dagster: the BFF client and the gateway seam. httpx MockTransport only."""
import asyncio
import inspect
import json
import logging
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.iagent.durable_answers import DurableAnswers  # noqa: E402


def _client(handler, ttl=0.2):
    calls = []

    def h(req):
        calls.append((req.url.path, json.loads(req.content or b"null")))
        return handler(req)

    da = DurableAnswers("http://r:8080", snapshot_ttl_s=ttl,
                        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(h)))
    return da, calls


SNAP = {"status": "SUCCESS", "events": [{"assetKey": {"path": ["x"]}, "metadataEntries": []}],
        "steps": [{"stepKey": "a", "status": "SUCCESS", "startTime": 1.0, "endTime": 2.0}],
        "result": {"payload": {"ui": 1}, "referenced_uris": ["u"]}}


# 14
def test_launch_posts_and_returns_the_id_or_none():
    da, calls = _client(lambda r: httpx.Response(200, json={}))
    aid = asyncio.run(da.launch({"user_query": "q"}))
    assert calls == [(f"/SupervisorAnswer/{aid}/run/send", {"user_query": "q"})]
    assert len(aid) == 36
    da, _ = _client(lambda r: httpx.Response(500))
    assert asyncio.run(da.launch({})) is None

    def boom(r):
        raise httpx.ConnectError("down")
    da, _ = _client(boom)
    assert asyncio.run(da.launch({})) is None


# 15
def test_one_tick_is_one_request_and_payload_is_fresh():
    async def go():
        da, calls = _client(lambda r: httpx.Response(200, json=SNAP), ttl=0.2)
        await da.get_run_status("a"); await da.get_run_events("a"); await da.get_step_stats("a")
        assert len(calls) == 1
        await asyncio.sleep(0.25)
        await da.get_run_status("a")
        assert len(calls) == 2
        await da.get_ui_payload_output("a"); await da.get_ui_payload_output("a")
        assert len(calls) == 4
    asyncio.run(go())


# 16
def test_mapping_of_snapshots_and_failed_reads():
    async def shapes(snap):
        da, _ = _client(lambda r: httpx.Response(200, json=snap))
        return (await da.get_run_status("a"), await da.get_run_events("a"),
                await da.get_step_stats("a"), await da.get_ui_payload_output("a"))

    st, ev, steps, pl = asyncio.run(shapes(SNAP))
    assert st == {"__typename": "Run", "status": "SUCCESS"} and ev == SNAP["events"]
    assert steps == [{"stepKey": "a", "status": "SUCCESS", "endTime": 2.0}]
    assert pl == {"payload": {"ui": 1}, "referenced_uris": ["u"]}
    fail = {**SNAP, "status": "FAILURE"}
    st, _, _, pl = asyncio.run(shapes(fail))
    assert st["status"] == "FAILURE" and pl["payload"] == {"ui": 1}
    queued = {"status": "QUEUED", "events": [], "steps": [], "result": None}
    st, ev, steps, pl = asyncio.run(shapes(queued))
    assert st["status"] == "QUEUED" and ev == [] and steps == [] and pl == {
        "error": "Durable answer has no UI payload"}
    da, calls = _client(lambda r: httpx.Response(500))

    async def bad():
        return (await da.get_run_status("a"), await da.get_run_events("a"),
                await da.get_step_stats("a"), await da.get_ui_payload_output("a"))
    st, ev, steps, pl = asyncio.run(bad())
    assert st == {} and ev == [] and steps == [] and "error" in pl
    assert len(calls) == 4  # a failed read is not cached


# ------------------------------------------------------------------ gateway
@pytest.fixture(scope="module")
def gw():
    from src.iagent import gateway
    return gateway


def test_answer_path_flag(gw, monkeypatch, caplog):
    monkeypatch.delenv("IAGENT_ANSWER_PATH", raising=False)
    assert gw._answer_path() == "dagster"
    monkeypatch.setenv("IAGENT_ANSWER_PATH", " Durable ")
    assert gw._answer_path() == "durable"
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "restate")
    with caplog.at_level(logging.WARNING):
        assert gw._answer_path() == "dagster"
    assert any("restate" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_dagster_backend_resolves_at_call_time(gw, monkeypatch):
    monkeypatch.delenv("IAGENT_ANSWER_PATH", raising=False)
    ab = gw._answer_backend()
    assert (ab.poll_s, ab.max_ticks) == (1.0, 900)

    async def patched(rid):
        return {"status": "PATCHED"}
    monkeypatch.setattr(gw, "_get_run_status", patched)
    assert asyncio.run(ab.status("r")) == {"status": "PATCHED"}


def test_durable_backend_keeps_the_fifteen_minute_ceiling(gw, monkeypatch):
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "durable")
    ab = gw._answer_backend()
    assert ab.poll_s == 0.25 and ab.max_ticks == 3600 and ab.poll_s * ab.max_ticks == 900


def test_seam_seal_stream_uses_the_backend_only(gw):
    src = inspect.getsource(gw._generate_dagster_stream_inner)
    for name in ("_get_run_status(", "_get_run_events(", "_get_step_stats(",
                 "_get_ui_payload_output(", "_launch_supervisor_job("):
        assert name not in src, name
    assert "_ab.poll_s" in src and "_ab.max_ticks" in src
    assert "_get_run_status(" in inspect.getsource(gw._dagster_run_finished)


def test_open_acceptances_default_is_looked_up_at_call_time(gw, monkeypatch):
    seen = []

    async def fake(rid):
        seen.append(rid)
        return [{"assetKey": {"path": ["active_agent_roster"]}, "metadataEntries": []}]
    monkeypatch.setattr(gw, "_get_run_events", fake)
    asyncio.run(gw._open_acceptances_from_run("r1", {}))
    assert seen == ["r1"]


def test_supervisor_op_config_equals_what_launch_sends(gw, monkeypatch):
    sent = {}

    def h(req):
        sent.update(json.loads(req.content))
        return httpx.Response(200, json="run-1")
    real = httpx.AsyncClient
    monkeypatch.setattr(gw.httpx, "AsyncClient",
                        lambda *a, **k: real(transport=httpx.MockTransport(h)))
    kw = dict(domain="D", user_id="u", user_email="e@x", frontend_id="f", user_persona="P",
              entitled_domains=["D"], entity_refs=["r"], slots={"a": 1}, trace_id="t1",
              session_id="s1", task_plan_json="{}")
    assert asyncio.run(gw._launch_supervisor_job("q", "thr", **kw)) == "run-1"
    want = gw._supervisor_op_config("q", "thr", **kw)
    got = json.loads(sent["variables"]["runConfig"])["ops"]["create_task_plan"]["config"]
    assert got == want


def test_the_durable_launch_carries_the_callers_identity(gw, monkeypatch):
    """The identity-hop seal (test_the_person_reaches_the_migrated_route) traces the Dagster
    launcher only. On the durable path the caller's entitlement key travels through
    `_answer_backend().launch` into the workflow body; this seals that hop."""
    da, calls = _client(lambda r: httpx.Response(200, json={}))
    monkeypatch.setenv("IAGENT_ANSWER_PATH", "durable")
    monkeypatch.setattr(gw, "_DURABLE_ANSWERS", da)
    kw = dict(domain="D", user_id="u", user_email="e@x", frontend_id="f", user_persona="P",
              entitled_domains=["D"], entity_refs=["r"], slots={"a": 1}, trace_id="t1",
              session_id="s1", task_plan_json="{}")
    aid = asyncio.run(gw._answer_backend().launch("q", "thr", **kw))
    [(path, body)] = calls
    assert path == f"/SupervisorAnswer/{aid}/run/send"
    assert body["user_email"] == "e@x"
    assert body == gw._supervisor_op_config("q", "thr", **kw)
