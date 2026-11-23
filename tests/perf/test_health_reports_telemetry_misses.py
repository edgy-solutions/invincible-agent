"""Every /health body reports `telemetry_misses` (provenance-telemetry 0.2.0).

The leaf counts spans it failed to export; that count is only useful if an operator can read
it off the service. This census DERIVES the health routes by scanning source -- it does not
list them -- and asserts each handler's body carries the key. A new engine's /health that
omits it reds here, and a scanner that silently finds nothing reds on the floor.

Run:  uv run pytest tests/perf -q
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HEALTH_PATHS = {"/health", "/healthz", "/v1/healthz"}
_KEY = "telemetry_misses"
_FLOOR = 17  # the 17 services measured when this seal was written


def _sources() -> list[Path]:
    return sorted((_ROOT / "agent_fleet").glob("**/main.py")) + [_ROOT / "src" / "iagent" / "gateway.py"]


def health_handlers(source: str) -> list[tuple[str, str, str]]:
    """(route, handler name, handler source) for every `@app|router.get("<health path>")`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "get"
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id in {"app", "router"}
                    and dec.args and isinstance(dec.args[0], ast.Constant)
                    and dec.args[0].value in _HEALTH_PATHS):
                continue
            found.append((dec.args[0].value, node.name, ast.get_source_segment(source, node) or ""))
    return found


def missing_key(source: str) -> list[str]:
    """Handlers in `source` whose body lacks the key."""
    return [f"{route} {name}" for route, name, body in health_handlers(source) if _KEY not in body]


def _census() -> list[tuple[Path, str, str, str]]:
    out = []
    for path in _sources():
        for route, name, body in health_handlers(path.read_text(encoding="utf-8")):
            out.append((path, route, name, body))
    return out


def test_the_census_finds_every_health_route():
    """A floor: a broken scanner cannot pass by finding nothing."""
    found = _census()
    assert len(found) >= _FLOOR, f"only {len(found)} health routes found: {[(p.parent.name, r) for p, r, *_ in found]}"
    services = {p.parent.name for p, *_ in found}
    assert len(services) >= _FLOOR, sorted(services)


def test_every_health_body_reports_telemetry_misses():
    missing = [f"{p.relative_to(_ROOT)}: {r} {n}" for p, r, n, body in _census() if _KEY not in body]
    assert not missing, "health handlers that do not report telemetry_misses:\n" + "\n".join(missing)


def test_the_checker_reports_a_handler_that_lacks_the_key():
    """Positive control: the same checker, run on a source that omits the key, names it."""
    bad = (
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.get('/health')\nasync def health():\n    return {'status': 'ok'}\n"
        "@router.get('/v1/healthz')\ndef healthz():\n    return {'status': 'ok', 'telemetry_misses': 0}\n"
        "@app.get('/other')\ndef other():\n    return {}\n"
    )
    assert missing_key(bad) == ["/health health"]


# --- the shim's emit_misses ---------------------------------------------------
@pytest.fixture
def shim(monkeypatch):
    monkeypatch.syspath_prepend(str(_ROOT / "baml_shared"))
    monkeypatch.delitem(sys.modules, "telemetry", raising=False)
    yield
    sys.modules.pop("telemetry", None)  # never leave a variant imported against a patched leaf


def test_emit_misses_is_none_without_the_leaf(shim, monkeypatch):
    monkeypatch.setitem(sys.modules, "provenance_telemetry", None)  # makes the import raise
    telemetry = importlib.import_module("telemetry")
    assert telemetry._LEAF_AVAILABLE is False
    assert telemetry.emit_misses() is None


def test_emit_misses_is_an_int_with_the_leaf(shim):
    telemetry = importlib.import_module("telemetry")
    assert telemetry._LEAF_AVAILABLE is True
    n = telemetry.emit_misses()
    assert isinstance(n, int) and not isinstance(n, bool)
