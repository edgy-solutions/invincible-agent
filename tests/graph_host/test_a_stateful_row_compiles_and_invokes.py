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
    assert d["durable_across_restarts"] is False
    assert "fin_program_brief" in d["stateful_graphs"]
    assert d["saver"] == "in-memory"
