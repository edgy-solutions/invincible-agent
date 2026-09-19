"""A `checkpointer: true` row must COMPILE, INVOKE, and actually carry a saver.

MEASURED LIVE 2026-09-14 on the NP-MERIDIAN walk, after routing and the instance promotion
were both clean and the dispatch reached this engine with the right params:

    500  http://iagent-engine-lg:8098/graphs/fin_program_brief
    AttributeError: 'StateGraph' object has no attribute 'ainvoke'   (main.py:273)

`load_graphs` read

    graph.compile() if not m.checkpointer else graph

**treating a checkpointer as a SUBSTITUTE for compiling rather than an ARGUMENT to it.** Every
row declaring `checkpointer: true` was stored as a BUILDER, and `ainvoke` exists only on the
compiled graph. `fin_program_brief` is the first such row to be invoked live;
`cost_lot_costing_review` declares `checkpointer: false` and took the working arm, which is why
a two-graph host shipped with one of its two arms broken.

── WHY EVERY EXISTING SEAL IN THIS DIRECTORY WAS GREEN ──────────────────────────────────────
`test_the_host_enforces_the_row.py` replaces the loaded graph with `_stub_graph(...)`, whose
whole job is to define `ainvoke` so the HOST's behaviour is what gets measured. **The stub
supplied exactly the attribute that was missing.** A fixture standing in for the subject cannot
fail on the subject's defect — so the fix is sealed here against the REAL compiled objects, and
the invoke is exercised for real rather than stubbed.

── AND THE SECOND DEFECT, WHICH OUTLIVES THE FIRST ──────────────────────────────────────────
Compiling in both arms clears the 500 and would leave `checkpointer: true` attached to NOTHING.
That is the shape this host already paid for once with `refusal` — a row declaring behaviour
that nothing implements, green everywhere. So the saver is asserted PRESENT and asserted to
WORK, not merely to have been survived.

Run: uv run --frozen pytest tests/graph_host/test_a_stateful_row_compiles_and_invokes.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import operator

# FROM `typing`, NOT `typing_extensions`, and the difference is not stylistic. Both graphs this
# seal exercises import them from `typing` (requires-python is >=3.12,<3.13, where both have been
# stdlib for several releases), and `typing_extensions` is named by no pyproject in the tree.
# `test_every_import_is_a_declared_dependency` reds on it: the distribution arrives transitively
# today and leaves without notice tomorrow.
#
# A FIXTURE THAT IMPORTS WHAT ITS SUBJECT DOES NOT is also a small version of the stub problem
# this very seal was written about — the test's state type would be built by a different
# mechanism than the graphs'.
from typing import Annotated, TypedDict

from tests.graph_host._engine_deps import needs_langgraph


class _SealState(TypedDict):
    """Module scope, not function scope: `from __future__ import annotations` defers these
    strings and langgraph resolves them against the DEFINING module's globals. A TypedDict
    declared inside the test body raises `NameError: Annotated` at compile time."""

    seen: Annotated[list, operator.add]

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = _ROOT / "policy" / "graphs"


@pytest.fixture()
def loaded(monkeypatch):
    """The REAL rows through the REAL loader. No stubs: the defect lived in this function."""
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    monkeypatch.setenv("GRAPH_POLICY_DIR", str(_POLICY))
    monkeypatch.delenv("MESH_REGISTER_ON_STARTUP", raising=False)

    import importlib

    from agent_fleet.graph_host import main as host

    importlib.reload(host)
    host._LOADED = host.load_graphs()
    return host


@needs_langgraph
def test_both_checkpointer_dispositions_are_present(loaded):
    """POSITIVE CONTROL, first. With every row on one side of the branch, the assertions below
    cannot tell "both arms compile" from "the only arm that exists compiles" — which is exactly
    how this shipped: the false arm worked and nothing exercised the true one."""
    decls = {gid: m.checkpointer for gid, (m, _g) in loaded._LOADED.items()}
    assert set(decls.values()) >= {True, False}, (
        f"the admitted rows no longer cover both checkpointer dispositions: {decls}. The "
        f"compile branch cannot be shown correct in both arms, only in one."
    )


@needs_langgraph
def test_EVERY_admitted_graph_is_invocable(loaded):
    """DERIVED OVER ALL ROWS, never a named one. The defect was arm-shaped: naming
    `fin_program_brief` here would pass the day a third stateful row is added and missed."""
    not_invocable = {
        gid: type(g).__name__
        for gid, (_m, g) in loaded._LOADED.items()
        if not hasattr(g, "ainvoke")
    }
    assert not not_invocable, (
        f"admitted but not invocable: {not_invocable}. An uncompiled builder has no `ainvoke` "
        f"and returns 500 on first call — which is what shipped."
    )


@needs_langgraph
def test_a_STATEFUL_row_actually_CARRIES_a_saver(loaded):
    """The second defect. `compile()` in both arms would satisfy the test above and leave the
    declaration attached to nothing."""
    stateful = [(gid, g) for gid, (m, g) in loaded._LOADED.items() if m.checkpointer]
    assert stateful, "no row declares a checkpointer — this seal has no subject"
    for gid, g in stateful:
        assert getattr(g, "checkpointer", None), (
            f"{gid} declares `checkpointer: true` and its compiled graph carries no saver. "
            f"The row would be honoured by nothing, exactly as `refusal` once was."
        )


@needs_langgraph
def test_a_STATELESS_row_is_NOT_given_one(loaded):
    """The control for the row above: "every graph gets a saver" would pass it while making
    the row's declaration meaningless in the other direction."""
    for gid, (m, g) in loaded._LOADED.items():
        if not m.checkpointer:
            assert not getattr(g, "checkpointer", None), (
                f"{gid} declares `checkpointer: false` and was given a saver anyway"
            )


@needs_langgraph
@pytest.mark.asyncio
async def test_the_hosts_own_compile_path_RUNS_and_REMEMBERS(loaded):
    """END TO END, OFFLINE. Asserting a saver is attached does not prove it works — this
    invokes a graph through the host's own `_saver_for` + compile path twice on one thread and
    reads the state back, which is the claim `checkpointer: true` actually makes."""
    from langgraph.graph import END, START, StateGraph

    b = StateGraph(_SealState)
    b.add_node("step", lambda s: {"seen": ["x"]})
    b.add_edge(START, "step")
    b.add_edge("step", END)

    m, _g = loaded._LOADED["fin_program_brief"]
    graph = b.compile(checkpointer=loaded._saver_for(m))
    cfg = {"configurable": {"thread_id": "seal-thread"}}

    first = await graph.ainvoke({"seen": []}, config=cfg)
    second = await graph.ainvoke({"seen": []}, config=cfg)

    assert first["seen"] == ["x"]
    assert second["seen"] == ["x", "x"], (
        f"the second call on the same thread did not see the first's state: {second}. The "
        f"saver is attached but not persisting, which a presence check cannot distinguish."
    )


@needs_langgraph
def test_health_REPORTS_durability_rather_than_implying_it(loaded):
    """A caller reading `checkpointer: true` off a manifest would reasonably assume the state
    survives a restart. It does not — the DSN is unwired and the saver is in-process. That is
    tolerable; leaving it to be inferred is not."""
    d = loaded.checkpointer_durability()
    assert "fin_program_brief" in d["stateful_graphs"]
    # NO DSN IN A TEST PROCESS, so this is the undeclared state — and it must report NOT READY
    # rather than merely flagging a boolean. R-012: the read that ACTS is readiness.
    assert d["saver"] == "in-process"
    assert d["durable_across_restarts"] is False
    assert d["ready"] is False, (
        "a row declaring `checkpointer: true` served from process memory reported READY. The "
        "boolean alone is the log line nobody greps."
    )
    assert loaded._CHECKPOINT_DSN_ENV in (d["detail"] or ""), (
        f"the reason does not name the variable to set: {d['detail']!r}"
    )


# ── R-012's THREE STATES ────────────────────────────────────────────────────────────────
#
# "durable or fail" would be a two-state rule and would refuse readiness on a host whose rows
# are all stateless — an engine that needs no checkpointer reporting itself unready for not
# having one. The middle state is the one a two-state rule gets wrong.

@needs_langgraph
def test_no_stateful_rows_and_no_DSN_is_READY(loaded, monkeypatch):
    """THE MIDDLE STATE. Without this row, "stateful and undeclared fails" is indistinguishable
    from "undeclared fails", which would take a perfectly correct stateless host out of its
    Service."""
    stateless = {gid: e for gid, e in loaded._LOADED.items() if not e[0].checkpointer}
    assert stateless, "no stateless row admitted — this state has no fixture"
    monkeypatch.setattr(loaded, "_LOADED", stateless)
    ok, detail = loaded.checkpointer_readiness()
    assert ok is True, f"a host with no stateful rows was refused readiness: {detail}"


@needs_langgraph
def test_stateful_rows_and_no_DSN_is_NOT_READY_and_NAMES_THE_VARIABLE(loaded):
    """R-012 literally: a missing declaration fails readiness, naming the variable. A default
    would convert a configuration error into a promise silently broken at the next restart."""
    ok, detail = loaded.checkpointer_readiness()
    assert ok is False
    assert loaded._CHECKPOINT_DSN_ENV in detail["reason"], (
        f"the refusal does not say what to set: {detail}"
    )
    assert "fin_program_brief" in detail["stateful_graphs"]


@needs_langgraph
def test_a_DECLARED_but_UNREACHABLE_DSN_is_a_DIFFERENT_refusal(loaded, monkeypatch):
    """Declared-and-broken is not the same failure as never-declared and needs a different fix.
    One refusal for both would send a reader to `graphHost.env` when the variable is already
    there and the database is refusing connections."""
    monkeypatch.setitem(loaded._SAVER_STATUS, "dsn_configured", True)
    monkeypatch.setitem(loaded._SAVER_STATUS, "open_error", "OperationalError: refused")
    ok, detail = loaded.checkpointer_readiness()
    assert ok is False
    assert "UNREACHABLE" in detail["checkpointing"]
    assert "refused" in detail["reason"], f"the underlying error was dropped: {detail}"


@needs_langgraph
def test_a_DURABLE_saver_is_READY(loaded, monkeypatch):
    """The positive control for all three above — otherwise "not ready" passes unconditionally."""
    # `_SAVER` IS TAKEN FROM THE COMPILED GRAPHS, which is what a correctly ordered boot
    # produces: the saver opened first, then compiled against. Setting `durable` without it
    # is the MISORDERED state, and the ordering invariant refuses that — correctly, which is
    # how this row was caught when the invariant landed.
    held = next(g.checkpointer for _gid, (m, g) in loaded._LOADED.items() if m.checkpointer)
    monkeypatch.setattr(loaded, "_SAVER", held)
    monkeypatch.setitem(loaded._SAVER_STATUS, "durable", True)
    monkeypatch.setitem(loaded._SAVER_STATUS, "kind", "postgres")
    ok, _detail = loaded.checkpointer_readiness()
    assert ok is True


# ── THE SHARED-THREAD COLLISION ─────────────────────────────────────────────────────────

@needs_langgraph
def test_a_STATEFUL_graph_REFUSES_a_call_with_no_thread(loaded):
    """The old config read `request.thread_id or graph_id`, so every caller omitting a thread
    checkpointed into ONE thread named after the graph. Harmless-looking on process memory;
    against a durable saver the next caller resumes the previous caller's brief."""
    from fastapi.testclient import TestClient

    c = TestClient(loaded.app)
    r = c.post("/graphs/fin_program_brief", json={"params": {"program_id": "PGM-001"}},
               headers={"Authorization": "Bearer t", "X-Originator-Email": "a@b.c"})
    assert r.status_code == 422, f"a stateful graph accepted a call with no thread: {r.status_code}"
    assert "thread_id" in r.json()["detail"]


@needs_langgraph
def test_a_STATELESS_graph_still_TOLERATES_no_thread(loaded):
    """THE CONTROL. "Every call needs a thread_id" would pass the row above while breaking every
    caller of a graph that writes no state — a cost the declaration does not justify."""
    from fastapi.testclient import TestClient

    class _G:
        async def ainvoke(self, state, config=None):
            return {"summary": "ran"}

    m, _g = loaded._LOADED["cost_lot_costing_review"]
    assert not m.checkpointer
    loaded._LOADED["cost_lot_costing_review"] = (m, _G())
    c = TestClient(loaded.app)
    r = c.post("/graphs/cost_lot_costing_review",
               json={"params": {"lot": 1, "rate_vintage": "2026-Q1"}},
               headers={"Authorization": "Bearer t", "X-Originator-Email": "a@b.c"})
    assert r.status_code == 200, f"a stateless graph was made to supply a thread: {r.text[:200]}"


# ── THE RULED SEAL: a stateful row RESUMES ITS THREAD IN A SECOND PROCESS ────────────────

_DSN = os.environ.get("GRAPH_HOST_POSTGRES_DSN")

needs_dsn = pytest.mark.skipif(
    not _DSN,
    reason=(
        "GRAPH_HOST_POSTGRES_DSN is not set. A SKIP HERE IS NOT A PASS: every row above runs "
        "on process memory and proves the saver is ATTACHED and WORKS IN ONE PROCESS. What is "
        "unverified without a DSN is the only claim durability actually makes — that a thread "
        "written by one pod is readable by another."
    ),
)


@needs_dsn
def test_a_thread_written_by_ONE_saver_RESUMES_in_ANOTHER():
    """Driven by an explicit Runner rather than `pytest.mark.asyncio` — see `_run_on_a_loop_psycopg_can_use`."""
    _run_on_a_loop_psycopg_can_use(_resume_body())


def _run_on_a_loop_psycopg_can_use(coro) -> None:
    """Run `coro` on a loop psycopg's async path accepts.

    WINDOWS ONLY, AND IT IS THE HARNESS NOT THE ENGINE. psycopg refuses
    `ProactorEventLoop`, which is Windows' default; engine-lg runs on Linux where the default
    is already a selector loop, so this never fires in the pod. Recorded rather than worked
    around silently: a seal that cannot run where a developer invokes it is a seal that gets
    marked skip and then believed.
    """
    import asyncio
    import sys

    factory = None
    if sys.platform == "win32":
        import selectors

        def factory():  # noqa: E306
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(coro)


async def _resume_body():
    """THE CLAIM `checkpointer: true` MAKES, and the one an in-process saver cannot support.

    A second `AsyncPostgresSaver` over the same DSN is what a second pod IS — a distinct
    instance with its own connection. In-memory passes every other row in this file and fails
    this one, which is the whole point of writing it separately.
    """
    from contextlib import AsyncExitStack

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.graph import END, START, StateGraph

    thread = f"resume-seal-{os.getpid()}"
    cfg = {"configurable": {"thread_id": thread}}

    def _build():
        b = StateGraph(_SealState)
        b.add_node("step", lambda s: {"seen": ["x"]})
        b.add_edge(START, "step")
        b.add_edge("step", END)
        return b

    async with AsyncExitStack() as s1:
        saver1 = await s1.enter_async_context(AsyncPostgresSaver.from_conn_string(_DSN))
        await saver1.setup()
        first = await _build().compile(checkpointer=saver1).ainvoke({"seen": []}, config=cfg)
        assert first["seen"] == ["x"]

    # saver1 is CLOSED here — the first "pod" is gone.
    async with AsyncExitStack() as s2:
        saver2 = await s2.enter_async_context(AsyncPostgresSaver.from_conn_string(_DSN))
        second = await _build().compile(checkpointer=saver2).ainvoke({"seen": []}, config=cfg)

    assert second["seen"] == ["x", "x"], (
        f"a second saver over the same DSN did not see the first's thread: {second}. The state "
        f"did not survive the process, which is the only thing durability claims."
    )


# ── THE ORDERING IS LOAD-BEARING, NOT TIDY ──────────────────────────────────────────────
#
# `load_graphs` COMPILES each stateful row against whatever `_saver_for` returns at that
# moment. Open the saver AFTER compilation and every graph carries an InMemorySaver while
# `_SAVER_STATUS` says durable: the engine reports durability it does not have, readiness
# passes, and the loss appears only as a thread that will not resume, on a restart, in
# production.
#
# THAT IS THE `registered 3/3` SHAPE FOR DURABILITY — a status derived from the ATTEMPT rather
# than the RESULT. A seal on the LIFESPAN alone would pin today's line order and say nothing
# about what the graphs hold; these assert the OBJECTS, so a future refactor that reorders is
# caught by what it produces rather than by how it reads.

@needs_langgraph
@pytest.mark.asyncio
async def test_the_lifespan_opens_the_saver_BEFORE_it_compiles(loaded, monkeypatch):
    """IDENTITY, NOT TRUTHINESS. An InMemorySaver is perfectly truthy, so
    `assert graph.checkpointer` passes against the misordered host — the defect this exists
    for. Only `is _SAVER` separates them."""
    from langgraph.checkpoint.memory import InMemorySaver

    sentinel = InMemorySaver()

    async def _fake_open(stack):
        loaded._SAVER = sentinel
        loaded._SAVER_STATUS.update({"kind": "postgres", "durable": True,
                                     "dsn_configured": True, "open_error": None})

    monkeypatch.setattr(loaded, "_open_saver", _fake_open)
    monkeypatch.delenv("MESH_REGISTER_ON_STARTUP", raising=False)

    async with loaded.lifespan(loaded.app):
        stateful = [(gid, g) for gid, (m, g) in loaded._LOADED.items() if m.checkpointer]
        assert stateful, "no stateful row admitted — this seal has no subject"
        for gid, g in stateful:
            assert getattr(g, "checkpointer", None) is sentinel, (
                f"{gid} was compiled against a checkpointer that is not the opened saver. The "
                f"saver was opened after load_graphs, so it is held by nothing while the "
                f"engine reports durable."
            )


@needs_langgraph
def test_reporting_durable_while_compiled_against_something_else_is_NOT_READY(loaded,
                                                                              monkeypatch):
    """The runtime half. The seal above catches the ordering in THIS repo's lifespan; this
    catches the same divergence however it arises — a second entry point, a route-C host, a
    reload that recompiles without reopening."""
    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr(loaded, "_SAVER", InMemorySaver())      # "opened" saver
    monkeypatch.setitem(loaded._SAVER_STATUS, "durable", True)
    monkeypatch.setitem(loaded._SAVER_STATUS, "kind", "postgres")
    # _LOADED still holds graphs compiled against a DIFFERENT saver — the misordered state.

    ok, detail = loaded.checkpointer_readiness()
    assert ok is False, (
        "the engine reported READY while its stateful graphs hold a checkpointer that is not "
        "the opened saver. That is a durability claim nothing backs."
    )
    assert "REPORTED DURABLE" in detail["checkpointing"]
    assert "before load_graphs" in detail["reason"].lower() or \
           "BEFORE load_graphs" in detail["reason"]


@needs_langgraph
def test_the_matching_case_is_READY(loaded, monkeypatch):
    """THE CONTROL. Without it, the row above is satisfied by a readiness check that refuses
    every durable host — which would pass while making durability unreachable."""
    # The correctly ordered state, taken from the objects rather than reconstructed: every
    # stateful graph already holds the saver `load_graphs` compiled it against, so declaring
    # THAT one open is exactly what a saver-opened-first boot leaves behind.
    held = {g.checkpointer for _gid, (m, g) in loaded._LOADED.items() if m.checkpointer}
    assert len(held) == 1, f"stateful graphs hold {len(held)} different savers: {held}"
    monkeypatch.setattr(loaded, "_SAVER", held.pop())
    monkeypatch.setitem(loaded._SAVER_STATUS, "durable", True)

    ok, detail = loaded.checkpointer_readiness()
    assert ok is True, f"a correctly-ordered durable host was refused readiness: {detail}"
