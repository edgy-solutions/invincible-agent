"""ENGINE-LG REGISTERS WHEN ITS CHECKPOINTER ANSWERS, AND A BOOT THAT MISSED IT RECOVERS IN PLACE.

The durable saver was opened once, in the lifespan. A Postgres missed at boot was caught, kept as
`_SAVER = None` for the pod's life, every `checkpointer: true` row compiled against process
memory, and the graphs registered anyway. The chart's readiness probe reads `/health`, which
answers 200 in that state, so nothing took the pod out of the Service and nothing tried again.
Engine-o had the same shape (`tests/test_engine_o_registers_when_its_stores_answer.py`); this is
the same gate, `mesh_registration.when_stores_answer`, keyed on the checkpointer.

THE REAL LIFESPAN, THE REAL ROWS, A STAND-IN SAVER. `_scrub.scrubbing_saver_class` is replaced by
a class whose `from_conn_string` refuses while the stand-in Postgres is down and counts its opens,
and which is a genuine `InMemorySaver`, so LangGraph's compile accepts it and readiness's identity
check reads it like the real one. The retry thread is never started: `_start_retry` is replaced by
a recorder and each arm runs the captured attempt itself, from a worker thread as production
does, because the attempt reopens on the app's loop and blocks for the answer.

Run: uv run --frozen pytest tests/graph_host/test_engine_lg_registers_when_its_checkpointer_answers.py -v
"""
from __future__ import annotations

import asyncio
import copy
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from tests.graph_host._engine_deps import needs_langgraph

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = _ROOT / "policy" / "graphs"
_GATE = "engine-lg:checkpointer"


class _Postgres:
    """The store the saver opens against: down, up, or hanging until released."""

    def __init__(self) -> None:
        self.up = False
        self.hang: asyncio.Event | None = None
        self.opens = 0


def _saver_class(pg: _Postgres):
    from langgraph.checkpoint.memory import InMemorySaver

    class StandInSaver(InMemorySaver):
        @classmethod
        @asynccontextmanager
        async def from_conn_string(cls, dsn):
            pg.opens += 1
            if pg.hang is not None:
                await pg.hang.wait()
            if not pg.up:
                raise OSError("connection refused")
            yield cls()

        async def setup(self) -> None:
            return None

    return StandInSaver


@pytest.fixture()
def host(monkeypatch):
    """engine-lg reloaded against the real rows, a declared DSN and the stand-in saver, with the
    registration recorded, the retry thread replaced by a list, and the readiness state restored."""
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    monkeypatch.setenv("GRAPH_POLICY_DIR", str(_POLICY))
    monkeypatch.setenv("GRAPH_HOST_POSTGRES_DSN", "postgresql://seal")
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")

    import importlib

    from agent_fleet.graph_host import main as h

    importlib.reload(h)
    pg = _Postgres()
    stand_in = _saver_class(pg)
    monkeypatch.setattr(h._scrub, "scrubbing_saver_class", lambda base: stand_in)
    registered: list = []
    monkeypatch.setattr(h, "_register_all", lambda: registered.append(1))

    # Resolved through a name the module has imported since before the gate, so the arms red
    # rather than error against a host that has no gate.
    mr = sys.modules[h.registration_status.__module__]
    saved = copy.deepcopy(mr._REG_STATE)
    armed: list = []

    def start_retry(component, attempt):
        mr._record(component, mr._REG_RETRYING)
        armed.append((component, attempt))

    monkeypatch.setattr(mr, "_start_retry", start_retry)
    h.seal = type("Seal", (), {"pg": pg, "registered": registered, "armed": armed, "mr": mr,
                               "saver_class": stand_in})
    yield h
    with mr._REG_LOCK:
        mr._REG_STATE.clear()
        mr._REG_STATE.update(saved)


def _stateful(h) -> list:
    return [g for _gid, (m, g) in h._LOADED.items() if m.checkpointer]


def _attempt(h):
    assert [n for n, _a in h.seal.armed] == [_GATE], (
        "no retry armed: a boot that missed the checkpointer is kept for the pod's life")
    return asyncio.to_thread(h.seal.armed[0][1])


# ── the hole, and the recovery ──────────────────────────────────────────────────────────────

@needs_langgraph
@pytest.mark.asyncio
async def test_A_CHECKPOINTER_MISSED_AT_BOOT_HOLDS_THE_REGISTRATION_AND_IS_NAMED(host):
    async with host.lifespan(host.app):
        assert _stateful(host), "the real rows no longer declare a checkpointer; the seal is moot"
        assert host.seal.registered == [], "registered while the declared checkpointer was down"
        assert [n for n, _a in host.seal.armed] == [_GATE]
        st = host.seal.mr.registration_status()
        assert st["components"][_GATE] == host.seal.mr._REG_RETRYING, st
        assert "checkpointer" in (st["last_error"] or ""), st
        # The boot's attempt reports the open that just failed; it does not open a second time.
        assert host.seal.pg.opens == 1


@needs_langgraph
@pytest.mark.asyncio
async def test_WHEN_IT_ANSWERS_THE_ROWS_ARE_RECOMPILED_AGAINST_IT_AND_THEN_REGISTERED(host):
    async with host.lifespan(host.app):
        assert all(type(g.checkpointer) is host.seal.saver_class for g in _stateful(host))
        assert host._SAVER is None

        assert await _attempt(host) is False
        assert host.seal.pg.opens == 2, "a retry did not try the store again"
        assert host.seal.registered == []

        host.seal.pg.up = True
        assert await _attempt(host) is True
        assert host.seal.registered == [1]
        assert host._SAVER is not None and host._SAVER_STATUS["durable"] is True
        assert all(g.checkpointer is host._SAVER for g in _stateful(host)), (
            "the saver reopened but the rows still checkpoint to process memory")
        assert host.checkpointer_readiness()[0] is True


@needs_langgraph
@pytest.mark.asyncio
async def test_THE_POD_RECOVERS_EVEN_WHEN_IT_DOES_NOT_REGISTER(host, monkeypatch):
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "false")
    async with host.lifespan(host.app):
        assert [n for n, _a in host.seal.armed] == [_GATE]
        host.seal.pg.up = True
        assert await _attempt(host) is True
        assert all(g.checkpointer is host._SAVER for g in _stateful(host))
        assert host.seal.registered == [], "registered with MESH_REGISTER_ON_STARTUP off"


@needs_langgraph
@pytest.mark.asyncio
async def test_A_FAILED_RELOAD_IS_NOT_AN_ANSWER(host, monkeypatch):
    """The open sets `durable`; only the reload compiles the rows against the saver. An answer
    keyed on `durable` would register graphs that still checkpoint to memory."""
    real = host.load_graphs
    fail = [True]

    def load_graphs():
        if host._SAVER_STATUS.get("durable") and fail[0]:
            fail[0] = False
            raise RuntimeError("reload refused")
        return real()

    monkeypatch.setattr(host, "load_graphs", load_graphs)
    async with host.lifespan(host.app):
        host.seal.pg.up = True
        assert await _attempt(host) is False
        assert host._SAVER_STATUS["durable"] is True
        assert host.seal.registered == [], "registered on a saver the rows were not compiled against"
        assert host.seal.pg.opens == 2
        assert await _attempt(host) is True
        # The saver that opened is reused; the retry recompiles, it does not open another.
        assert host.seal.pg.opens == 2, "a second saver was opened while the first was durable"
        assert host.seal.registered == [1]
        assert all(g.checkpointer is host._SAVER for g in _stateful(host))


@needs_langgraph
@pytest.mark.asyncio
async def test_A_RELOAD_THAT_COMPILES_AGAINST_MEMORY_IS_NOT_AN_ANSWER(host, monkeypatch):
    """A reload that returns without raising but hands back rows compiled against something
    other than the opened saver (the ordering defect `checkpointer_readiness` names). The saver
    is durable; readiness is not; the answer follows readiness."""
    real = host.load_graphs
    stale = [True]

    def load_graphs():
        if host._SAVER_STATUS.get("durable") and stale[0]:
            stale[0] = False
            return host._LOADED
        return real()

    monkeypatch.setattr(host, "load_graphs", load_graphs)
    async with host.lifespan(host.app):
        host.seal.pg.up = True
        assert await _attempt(host) is False
        assert host._SAVER_STATUS["durable"] is True
        assert host.checkpointer_readiness()[0] is False
        assert host.seal.registered == [], "registered on rows compiled against process memory"
        assert await _attempt(host) is True
        assert host.seal.registered == [1]


@needs_langgraph
@pytest.mark.asyncio
async def test_AN_OPEN_STILL_IN_FLIGHT_IS_NOT_STARTED_AGAIN(host, monkeypatch):
    monkeypatch.setattr(host, "_REOPEN_TIMEOUT_S", 0.2, raising=False)
    async with host.lifespan(host.app):
        host.seal.pg.hang = asyncio.Event()
        assert await _attempt(host) is False
        assert host.seal.pg.opens == 2
        assert await _attempt(host) is False
        assert host.seal.pg.opens == 2, "a second open was started while the first still hung"

        host.seal.pg.up = True
        host.seal.pg.hang.set()
        for _ in range(100):
            if host._SAVER_STATUS["durable"]:
                break
            await asyncio.sleep(0.01)
        assert await _attempt(host) is True
        assert host.seal.registered == [1]


# ── what is not held ─────────────────────────────────────────────────────────────────────────

@needs_langgraph
@pytest.mark.asyncio
async def test_A_CHECKPOINTER_THAT_OPENS_AT_BOOT_REGISTERS_AT_ONCE(host):
    host.seal.pg.up = True
    async with host.lifespan(host.app):
        assert host.seal.registered == [1]
        assert host.seal.armed == []
        assert host.seal.pg.opens == 1
        assert all(g.checkpointer is host._SAVER for g in _stateful(host))


@needs_langgraph
@pytest.mark.asyncio
async def test_NO_DSN_REGISTERS_AT_ONCE_AS_BEFORE(host, monkeypatch):
    """Undeclared is configuration, and `/ready` names the variable. Holding the registration
    would add a second refusal for a store nobody asked for."""
    monkeypatch.delenv("GRAPH_HOST_POSTGRES_DSN")
    async with host.lifespan(host.app):
        assert _stateful(host)
        assert host.seal.registered == [1]
        assert host.seal.armed == []
        assert host.seal.pg.opens == 0


@needs_langgraph
@pytest.mark.asyncio
async def test_NO_STATEFUL_ROW_IS_NOT_HELD_BY_A_SAVER_NOTHING_READS(host, monkeypatch):
    real = host.load_graphs
    monkeypatch.setattr(host, "load_graphs",
                        lambda: {k: v for k, v in real().items() if not v[0].checkpointer})
    async with host.lifespan(host.app):
        assert host._LOADED and not _stateful(host)
        assert host.seal.registered == [1]
        assert host.seal.armed == []
