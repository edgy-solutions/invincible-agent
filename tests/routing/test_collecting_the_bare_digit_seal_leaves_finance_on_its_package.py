"""Collecting the bare-digit seal leaves finance's package engine bound to its package modules.

`tests/routing/test_a_bare_digit_is_not_an_identifier.py` loads `agent_fleet/finance_agent/main.py`
flat, as the image runs it, at COLLECTION time. Finance's modules import their siblings flat first
(`import export`), then fall back to the package (`from agent_fleet.finance_agent import export`). If
that load leaves `agent_fleet/finance_agent` on `sys.path`, or leaves the flat siblings in
`sys.modules`, every later importer of the PACKAGE takes the flat branch. A test that then patches
`agent_fleet.finance_agent.export` patches a module the engine no longer calls. In the order
routing-then-finance, that was 23 reds in tests/finance that finance alone never shows. And a
PACKAGE module imported during that load binds the flat siblings' names: package `measures`
raising the flat `entities.NotInModel` was 5 more, once only the flat modules were removed.

Each arm runs in a fresh interpreter, because the state under test is the process's import state
and this suite's own process has already been shaped by whatever was collected before it.

Run: uv run --frozen pytest tests/routing/test_collecting_the_bare_digit_seal_leaves_finance_on_its_package.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SEAL = "tests.routing.test_a_bare_digit_is_not_an_identifier"

_PROBE = r"""
import json, sys
from pathlib import Path
fin = (Path.cwd() / "agent_fleet" / "finance_agent").resolve()
{first}
flat = sorted(
    n for n, m in list(sys.modules.items())
    if not n.startswith("agent_fleet") and n != "finance_agent_main_under_test"
    and getattr(m, "__file__", None) and Path(m.__file__).resolve().is_relative_to(fin)
)
on_path = any(Path(p or ".").resolve() == fin for p in sys.path)
import agent_fleet.finance_agent.main as engine
from agent_fleet.finance_agent import export
from agent_fleet.finance_agent import entities, measures
stems = {{q.stem for q in fin.glob("*.py")}} | {{d.name for d in fin.iterdir() if (d / "__init__.py").exists()}}
def _flat_name(v):
    n = v.__name__ if isinstance(v, type(sys)) else getattr(v, "__module__", None)
    return isinstance(n, str) and not n.startswith("agent_fleet") and n.split(".")[0] in stems
package_bound_to_flat = sorted(
    f"{{n}}.{{a}}" for n, m in list(sys.modules.items()) if n.startswith("agent_fleet.finance_agent")
    for a, v in list(vars(m).items()) if _flat_name(v)
)
print("PROBE " + json.dumps({{"flat": flat, "on_path": on_path,
                              "engine_calls_package_export": engine.export is export,
                              "package_bound_to_flat": package_bound_to_flat,
                              "measures_raises_package_class":
                                  measures.NotInModel is entities.NotInModel}}))
"""


def _probe(first: str) -> dict:
    r = subprocess.run([sys.executable, "-c", _PROBE.format(first=first)], cwd=_REPO,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"probe failed (rc={r.returncode}):\n{r.stderr[-3000:]}"
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("PROBE ")][-1]
    return json.loads(line[len("PROBE "):])


def test_control_the_package_engine_alone_calls_its_package_export():
    """CONTROL: no seal collected first. If this is red, the assertion below measures nothing."""
    got = _probe("")
    assert got == {"flat": [], "on_path": False, "engine_calls_package_export": True,
                   "package_bound_to_flat": [], "measures_raises_package_class": True}, got


def _assert_finance_is_on_its_package(got: dict) -> None:
    assert got["flat"] == [], (
        f"collecting {_SEAL} left finance modules loaded FLAT in sys.modules: {got['flat']}. "
        f"The next package import of finance binds these instead of its own siblings.")
    assert got["on_path"] is False, (
        f"collecting {_SEAL} left agent_fleet/finance_agent on sys.path, so the next package "
        f"import of finance takes the flat branch.")
    assert got["engine_calls_package_export"] is True, (
        "agent_fleet.finance_agent.main is bound to a flat `export`: a test that patches "
        "agent_fleet.finance_agent.export patches a module the engine does not call.")
    assert got["package_bound_to_flat"] == [], (
        f"after collecting {_SEAL}, package finance modules hold names from FLAT finance "
        f"modules: {got['package_bound_to_flat']}. A test that imports the package's "
        f"`entities.NotInModel` then expects a different class of the same name.")
    assert got["measures_raises_package_class"] is True, (
        "`from agent_fleet.finance_agent import measures` returns a `measures` whose NotInModel "
        "is not agent_fleet.finance_agent.entities.NotInModel: `pytest.raises` of the package "
        "class misses what the engine raises.")


def test_the_seal_collected_first_leaves_no_flat_finance_module_and_no_path_entry():
    _assert_finance_is_on_its_package(_probe(f"import {_SEAL}"))


def test_the_seal_collected_after_the_package_was_imported_leaves_its_attributes_clean():
    """The usual order in a suite: an earlier file already imported `agent_fleet.finance_agent`,
    so the package survives the seal's restore while its children do not. `from pkg import
    child` reads the parent's ATTRIBUTE first, so a child dropped from `sys.modules` but left on
    the parent is still what the next importer gets."""
    _assert_finance_is_on_its_package(_probe(f"import agent_fleet.finance_agent; import {_SEAL}"))
