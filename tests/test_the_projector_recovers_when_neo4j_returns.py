"""THE PROJECTOR RIDES OUT A NEO4J OUTAGE WITHOUT A RESTART -- AND SAYS SO WHEN IT CANNOT.

The 2026-10-04 packet (roll #16) put the projector in the same class as engine-o: started against
a Neo4j that refused bolt, it logged 180 ConnectionRefused, then went silent with 0 restarts, and
was restarted by hand at 01:00. The packet read that as "one connect at startup, no retry after".

THE CODE SAYS OTHERWISE, AND THIS FILE HOLDS IT TO THAT. The driver is built lazily (no
connection at construction); every batch opens its own session; `run_forever` catches a failed
batch, logs it and polls again. So a pod booted during the outage applies once Neo4j answers,
through the same driver it booted with. The live log agrees: the pod the hand restart started at
01:00:34 found no backlog -- its first apply was 01:13:19, count=1 -- so nothing had been waiting
on the old one.

WHAT WAS A HOLE: `/health` -- the kubelet's liveness probe -- answered 200 whatever the apply
task's state. A loop that had ENDED left a pod reporting healthy and applying nothing, which is
the stale shape the packet feared, reached by a different door. It now answers 503 once the task
is done.

Run: uv run --frozen pytest tests/test_the_projector_recovers_when_neo4j_returns.py -v
"""
from __future__ import annotations

import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from iagent.projector import apply_loop as al
from iagent.projector.app import create_app

ART = {"id": "art-1", "watermark": 1}


class _World:
    """Neo4j as the loop sees it: refusing bolt while ``up`` is False, then holding one artifact.
    Postgres holds the cursor at 0 throughout."""

    def __init__(self):
        self.up, self.refusals, self.drivers, self.applied = False, 0, 0, []

    def driver(self, uri, auth):
        self.drivers += 1
        world = self

        class _Driver:
            def session(self):
                if not world.up:
                    world.refusals += 1
                    raise ServiceUnavailable("Couldn't connect (ConnectionRefused)")
                return _Session()

            def close(self):
                pass

        class _Session:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def run(self, query, **params):
                return [{"a": dict(ART), "producers": [], "consumers": [], "sources": [],
                         "derived_from": None}]

        return _Driver()

    @contextlib.contextmanager
    def pg(self):
        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, *a, **k):
                pass

            def fetchone(self):
                return (0, 0, 0)

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return _Cur()

        yield _Conn()


@pytest.fixture
def world(monkeypatch):
    w = _World()
    monkeypatch.setattr(al.GraphDatabase, "driver", w.driver)
    monkeypatch.setattr(al.ApplyLoop, "_pg_connect", lambda self: w.pg().__enter__())
    return w


def _loop(world):
    loop = al.ApplyLoop(neo4j_uri="bolt://neo4j.test", neo4j_user="u", neo4j_password="p",
                        postgres_dsn="dsn", poll_interval_seconds=0.0)
    loop._apply_one = lambda art: world.applied.append(art["id"])
    return loop


async def _until(cond, what):
    for _ in range(2000):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"never: {what}")


@pytest.mark.asyncio
async def test_A_LOOP_BOOTED_WHILE_NEO4J_REFUSES_APPLIES_WHEN_IT_ANSWERS(world):
    """Boot during the outage, refuse several polls, bring Neo4j back: the SAME loop, on the SAME
    driver, applies the waiting artifact. No restart, no reconstruction."""
    loop = _loop(world)
    task = asyncio.create_task(loop.run_forever())
    try:
        await _until(lambda: world.refusals >= 3, "three refused polls")
        assert world.applied == [] and not task.done()
        world.up = True
        await _until(lambda: world.applied, "an apply after Neo4j returned")
    finally:
        loop.close()
        await asyncio.wait({task}, timeout=5)  # its own exception is asserted below, not raised
    assert task.done() and task.exception() is None, task
    assert world.applied[0] == ART["id"]
    assert world.drivers == 1, "recovery went through a new driver, which a running pod never builds"


# ── /health is the liveness probe: it must see an ended loop ────────────────────────────────

class _Loop:
    """The app's view of a loop: a run_forever that ends when told to, or not at all."""

    def __init__(self, ends):
        self.ends, self.stop = ends, asyncio.Event()

    async def run_forever(self):
        if not self.ends:
            await self.stop.wait()

    def close(self):
        self.stop.set()


@pytest.mark.parametrize("ends,status", [(False, 200), (True, 503)], ids=["running", "ended"])
def test_HEALTH_ANSWERS_ONLY_WHILE_THE_APPLY_LOOP_RUNS(monkeypatch, ends, status):
    """The control is the running loop: same app, same probe, differing only in whether the task
    is still running."""
    with TestClient(create_app(loop=_Loop(ends))) as client:
        for _ in range(50):  # let an ending task finish before the probe reads it
            r = client.get("/health")
            if r.status_code == status:
                break
        assert r.status_code == status, r.text
