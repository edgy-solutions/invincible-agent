"""/register_frontend_capabilities must not hold the BFF's event loop.

Measured live on rev 186 (2026-10-10): the handler is `async def` and called the sync
registrar POST once per capability (~49 x 0.42s = ~21s of blocked loop per registration).
Two overlapping registrations exceeded the liveness window and the probe killed the pod.
The emit loop now runs in the threadpool.

Arms: BEHAVIOURAL (a concurrent /health returns while registration is in flight),
THREAD (every emit runs off the loop's thread), COUNTS (control: counts and the failure
warning are unchanged).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from src.iagent import gateway  # noqa: E402

N = 24
SLEEP = 0.05


def _user():
    return type("U", (), {"authz_id": "alice@example.com", "id": "alice@example.com",
                          "sub": "alice@example.com", "email": "alice@example.com",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()


def _body(n=N):
    return {
        "frontend_id": "cortex-ui-test",
        "frontend_version": "t",
        "capabilities": [
            {"archetype": "KNOWLEDGE_DOCUMENT", "subject_uri": f"mesh:Subject{i}",
             "object_uri": "mesh:KnowledgeDocument"}
            for i in range(n)
        ],
    }


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("MESH_REGISTRAR_URL", "http://registrar.invalid")
    gateway.app.dependency_overrides[gateway.get_current_user] = _user
    yield
    gateway.app.dependency_overrides.clear()


def _stub(monkeypatch, outcome=True, seen=None):
    from agent_fleet.utils import mesh_registration as mr

    def _fake(**kw):
        if seen is not None:
            seen.append(threading.get_ident())
        time.sleep(SLEEP)
        return outcome

    monkeypatch.setattr(mr, "_emit_presentation_to_registrar", _fake)


async def _post(client, body):
    return await client.post("/register_frontend_capabilities", json=body)


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),
                             base_url="http://t")


def test_a_concurrent_health_check_is_not_held_by_a_registration(app_env, monkeypatch):
    _stub(monkeypatch)

    async def run():
        async with _client() as c:
            t0 = time.perf_counter()

            async def probe():
                await asyncio.sleep(0.1)  # the registration is in flight by now
                h = await c.get("/health")
                # measured from when the probe WANTED to run: a blocked loop delays even
                # the timer wake-up, so the stall shows in this figure
                return h, time.perf_counter() - t0 - 0.1

            r, (h, health_s) = await asyncio.gather(_post(c, _body()), probe())
            return h, health_s, r, None

    h, health_s, r, _ = asyncio.run(run())
    assert r.status_code == 200 and r.json()["accepted"] == N
    assert h.status_code in (200, 503)
    assert health_s < 0.5, (
        f"/health took {health_s:.2f}s while a {N * SLEEP:.1f}s registration was in flight: "
        "the event loop was blocked"
    )


def test_every_registrar_emit_runs_off_the_event_loop_thread(app_env, monkeypatch):
    seen: list[int] = []
    _stub(monkeypatch, seen=seen)

    async def run():
        loop_tid = threading.get_ident()
        async with _client() as c:
            r = await _post(c, _body())
        return loop_tid, r

    loop_tid, r = asyncio.run(run())
    assert r.status_code == 200
    assert len(seen) == N
    assert all(t != loop_tid for t in seen), "an emit ran on the event-loop thread"


def test_counts_are_unchanged_on_success(app_env, monkeypatch, caplog):
    _stub(monkeypatch)
    caplog.set_level(logging.INFO, logger="iagent.registry.frontend_capabilities")

    async def run():
        async with _client() as c:
            return await _post(c, _body(3))

    r = asyncio.run(run())
    assert r.json()["accepted"] == 3
    ev = [json.loads(x.message) for x in caplog.records if x.message.startswith("{")]
    done = [e for e in ev if e["event"] == "frontend_capabilities_registered"][0]
    assert done["graph_registered_count"] == 3 and done["graph_failed_count"] == 0
    assert not [e for e in ev if e["event"] == "frontend_capabilities_graph_registration_failed"]


def test_one_stubbed_failure_is_counted_and_warned(app_env, monkeypatch, caplog):
    _stub(monkeypatch, outcome=("gateway-unreachable", "x"))
    caplog.set_level(logging.INFO, logger="iagent.registry.frontend_capabilities")

    async def run():
        async with _client() as c:
            return await _post(c, _body(1))

    r = asyncio.run(run())
    assert r.status_code == 200
    ev = [json.loads(x.message) for x in caplog.records if x.message.startswith("{")]
    done = [e for e in ev if e["event"] == "frontend_capabilities_registered"][0]
    assert done["graph_registered_count"] == 0 and done["graph_failed_count"] == 1
    warn = [e for e in ev if e["event"] == "frontend_capabilities_graph_registration_failed"]
    assert warn and warn[0]["failed_count"] == 1
    assert warn[0]["failures"][0]["reason_class"] == "gateway-unreachable"
