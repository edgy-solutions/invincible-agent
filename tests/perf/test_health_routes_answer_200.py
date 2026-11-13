"""Every /health route ANSWERS 200 -- the route is CALLED, not just read.

The census in `test_health_reports_telemetry_misses.py` checks the key is NAMED; this file
CALLS the route, because a response-model mismatch (engine-f, 0.4.86: `-> Dict[str, str]`
over an int `telemetry_misses`) passes a name check and 500s live, and the pod never
becomes Ready.

A. engine-f for real: import its `main` through the shared `stub_modules` harness and GET it.
B. every health route, DERIVED: each handler's return annotation / `response_model=` is
   re-built on a fresh app that returns the real body shape, and called.

Run:  uv run pytest tests/perf/test_health_routes_answer_200.py -q
"""
from __future__ import annotations

import ast
import builtins
import sys
import types
import typing
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import stub_modules
from tests.perf.test_health_reports_telemetry_misses import _FLOOR, _ROOT, _sources, health_handlers

_PRESENTATION_DIR = _ROOT / "agent_fleet" / "presentation_agent"
if str(_PRESENTATION_DIR) not in sys.path:
    sys.path.insert(0, str(_PRESENTATION_DIR))

_BODY = {"status": "ok", "engine": "X", "telemetry_misses": 0}
_NS = {n: getattr(typing, n) for n in ("Dict", "Any", "List", "Optional", "Union")}
_NS.update({k: v for k, v in vars(builtins).items() if not k.startswith("_")})


# --- A. engine-f for real -----------------------------------------------------
def _import_presentation_main():
    stub = types.ModuleType("baml_client")
    stub.b = SimpleNamespace()
    stub.__path__ = []  # a PACKAGE, not a bare module
    with stub_modules({"baml_client": stub}):
        import agent_fleet.presentation_agent.main as m
    return m


def test_engine_f_health_answers_200_with_an_int(monkeypatch):
    m = _import_presentation_main()
    monkeypatch.setattr(m, "emit_misses", lambda: 0)  # the global the handler resolves
    resp = TestClient(m.app, raise_server_exceptions=False).get("/health")
    assert resp.status_code == 200, f"engine-f /health -> {resp.status_code}: {resp.text[:200]}"
    n = resp.json()["telemetry_misses"]
    assert n is None or (isinstance(n, int) and not isinstance(n, bool))


# --- B. every health route, derived -------------------------------------------
def _eval(node: ast.expr | None):
    """(ok, value). Unannotated is (True, None)."""
    if node is None:
        return True, None
    try:
        return True, eval(compile(ast.Expression(node), "<annotation>", "eval"), dict(_NS))
    except Exception:
        return False, None


def _probe_status(annotation, response_model=None, *, has_annotation=True) -> int:
    app = FastAPI()

    def endpoint():
        return dict(_BODY)

    if has_annotation:
        endpoint.__annotations__["return"] = annotation
    kw = {"response_model": response_model} if response_model is not None else {}
    app.get("/health", **kw)(endpoint)
    return TestClient(app, raise_server_exceptions=False).get("/health").status_code


def _declarations(source: str):
    """(route, name, returns node, response_model node) per health handler."""
    wanted = {(r, n) for r, n, _ in health_handlers(source)}
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant)
                    and (dec.args[0].value, node.name) in wanted):
                rm = next((k.value for k in dec.keywords if k.arg == "response_model"), None)
                out.append((dec.args[0].value, node.name, node.returns, rm))
    return out


def _probe_all():
    probed, undecided, bad = [], [], []
    for path in _sources():
        rel = path.relative_to(_ROOT)
        for route, name, returns, rm in _declarations(path.read_text(encoding="utf-8")):
            label = f"{rel}: {route} {name} -> {ast.unparse(returns) if returns else '(unannotated)'}"
            ok1, ann = _eval(returns)
            ok2, model = _eval(rm)
            if not (ok1 and ok2):
                undecided.append(label)
                continue
            probed.append(label)
            status = _probe_status(ann, model, has_annotation=returns is not None)
            if status != 200:
                bad.append(f"{label} [{status}]")
    return probed, undecided, bad


def test_every_health_route_answers_200():
    probed, undecided, bad = _probe_all()
    assert not undecided, "annotations the probe cannot evaluate:\n" + "\n".join(undecided)
    assert len(probed) >= _FLOOR, f"only {len(probed)} handlers probed"
    assert not bad, "health routes that do not answer 200:\n" + "\n".join(bad)


# --- positive control ---------------------------------------------------------
def test_the_probe_500s_on_dict_str_str_and_passes_on_dict_str_any():
    assert _probe_status(typing.Dict[str, str]) == 500
    assert _probe_status(typing.Dict[str, typing.Any]) == 200
