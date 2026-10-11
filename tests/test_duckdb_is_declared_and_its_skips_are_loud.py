"""duckdb is declared in the root agent-fleet extra, and a skip for want of it says so.

WHAT WENT WRONG: 15 `pytest.importorskip("duckdb")` sites skipped silently in every lane venv,
because only the cost engine declared duckdb. A skipped arm reads as nothing at all.

Four arms: the root pin equals the engine's; every importorskip site carries a reason that names
duckdb (the census is an AST walk, not a grep); the summary selector returns the duckdb skips and
only those; and the census's site-finder is controlled on source strings, in both call shapes.
"""
from __future__ import annotations

import ast
import importlib.util
import tomllib
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]

# Loaded by PATH: several `conftest` modules share that name, and `import conftest` finds whichever
# directory pytest put on sys.path first.
_spec = importlib.util.spec_from_file_location("_root_tests_conftest", Path(__file__).with_name("conftest.py"))
_root_conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_root_conftest)
_duckdb_skips = _root_conftest._duckdb_skips


def _duckdb_req(pyproject, extra=None):
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    reqs = (data["project"]["optional-dependencies"][extra] if extra
            else data["project"]["dependencies"])
    found = [r for r in reqs if r.replace(" ", "").lower().startswith("duckdb")]
    assert len(found) == 1, f"{pyproject}: expected one duckdb requirement, found {found}"
    return found[0].replace(" ", "")


def _duckdb_importorskip_sites(src):
    """Every Call to `importorskip` (bare or attribute form) whose first arg is "duckdb"."""
    sites = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if (name == "importorskip" and n.args and isinstance(n.args[0], ast.Constant)
                and n.args[0].value == "duckdb"):
            sites.append(n)
    return sites


def _has_duckdb_reason(call):
    for kw in call.keywords:
        if (kw.arg == "reason" and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str) and "duckdb" in kw.value.value):
            return True
    return False


def test_the_root_extra_pins_the_engines_duckdb():
    root = _duckdb_req(REPO / "pyproject.toml", "agent-fleet")
    engine = _duckdb_req(REPO / "agent_fleet" / "cost_agent" / "pyproject.toml")
    assert root == engine, f"root agent-fleet extra {root!r} != cost_agent {engine!r}"


def test_every_duckdb_importorskip_names_what_goes_unverified():
    population, bare = [], []
    for p in sorted((REPO / "tests").rglob("*.py")):
        for n in _duckdb_importorskip_sites(p.read_text(encoding="utf-8", errors="replace")):
            ident = f"{p.relative_to(REPO).as_posix()}:{n.lineno}"
            population.append(ident)
            if not _has_duckdb_reason(n):
                bare.append(ident)
    assert population, "POSITIVE CONTROL: the census found no importorskip('duckdb') site at all"
    assert not bare, f"importorskip('duckdb') without a reason naming duckdb: {bare}"


def test_the_summary_names_duckdb_skips_and_only_those():
    def rep(path, reason):
        return SimpleNamespace(longrepr=(path, 1, f"Skipped: {reason}"))
    stats = {"skipped": [rep("tests/a.py", "duckdb is not installed in this venv"),
                         rep("tests/b.py", "needs a cluster")]}
    assert _duckdb_skips(stats) == [("tests/a.py", "Skipped: duckdb is not installed in this venv")]
    assert _duckdb_skips({}) == []


def test_the_census_sees_a_bare_importorskip():
    attr = 'import pytest\ndef t():\n    pytest.importorskip("duckdb")\n'
    bare = 'from pytest import importorskip\ndef t():\n    importorskip("duckdb")\n'
    ok = 'def t():\n    pytest.importorskip("duckdb", reason="duckdb is missing")\n'
    for src in (attr, bare):
        sites = _duckdb_importorskip_sites(src)
        assert len(sites) == 1 and not _has_duckdb_reason(sites[0]), src
    sites = _duckdb_importorskip_sites(ok)
    assert len(sites) == 1 and _has_duckdb_reason(sites[0])
