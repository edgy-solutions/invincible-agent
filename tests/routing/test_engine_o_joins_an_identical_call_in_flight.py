"""ENGINE O JOINS AN IDENTICAL MODEL CALL THAT IS STILL RUNNING -- architect ruling 2026-10-20.

    "Engine O dedupes identical in-flight calls (prompt hash; a retry joins the running call
     instead of starting another)"

MEASURED 2026-10-20 (sandbox revision 199, Engine O log 03:30-04:16Z): 55 completed
`ClassifyDomainIntent` calls, max 52,553 ms. Engine A re-posted the same prompt 4 and 8 times
while the first call was still running, and Engine O completed every abandoned call. A cache
would have caught none of them, so arm 4 pins that this is NOT one.

The module under test is loaded by path (`agent_fleet/ontology_service/inflight.py` is pure);
the fake inner client is pure asyncio and imports no baml.

Run: uv run --frozen pytest tests/routing/test_engine_o_joins_an_identical_call_in_flight.py -v
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import logging
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DIR = _REPO / "agent_fleet" / "ontology_service"
_MAIN = _DIR / "main.py"


def _load_inflight():
    spec = importlib.util.spec_from_file_location("_inflight_under_test", _DIR / "inflight.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inflight = _load_inflight()


class _Body:
    def __init__(self, kw):
        self._kw = kw

    def raw(self):
        return json.dumps(self._kw, sort_keys=True).encode()


class _Rendered:
    def __init__(self, kw):
        self.body = _Body(kw)


class _Request:
    def __init__(self, fail=False):
        self._fail = fail

    def ClassifyDomainIntent(self, **kw):  # noqa: N802
        if self._fail:
            raise RuntimeError("cannot render")
        return _Rendered(kw)


class _Inner:
    """Counts calls; each call waits on `gate` and then returns a fresh object (or raises)."""

    def __init__(self, fail_render=False):
        self.calls = 0
        self.gate: asyncio.Event | None = None
        self.raises: Exception | None = None
        self.request = _Request(fail=fail_render)
        self.with_options = lambda **kw: self  # CALLABLE and lowercase: must pass through

    async def ClassifyDomainIntent(self, **kw):  # noqa: N802
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.raises is not None:
            raise self.raises
        return {"answer": kw, "n": self.calls}


def _client(inner=None, log=None):
    inner = inner or _Inner()
    return inner, inflight.CoalescingClient(inner, log=log)


async def _settle(n=5):
    for _ in range(n):
        await asyncio.sleep(0)


def test_two_concurrent_identical_calls_make_one_model_call():
    async def go():
        inner, c = _client()
        inner.gate = asyncio.Event()
        t1 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        await _settle()
        t2 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        await _settle()
        inner.gate.set()
        r1, r2 = await asyncio.gather(t1, t2)
        return inner.calls, r1, r2

    calls, r1, r2 = asyncio.run(go())
    assert calls == 1
    assert r1 is r2


def test_different_kwargs_are_different_calls():
    async def go():
        inner, c = _client()
        inner.gate = asyncio.Event()
        t1 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        t2 = asyncio.ensure_future(c.ClassifyDomainIntent(q="y"))
        await _settle()
        inner.gate.set()
        await asyncio.gather(t1, t2)
        return inner.calls

    assert asyncio.run(go()) == 2


def test_the_measured_case_a_retry_joins_a_call_whose_first_caller_went_away():
    async def go():
        inner, c = _client()
        inner.gate = asyncio.Event()
        t1 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        await _settle()
        t1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t1
        t2 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        await _settle()
        inner.gate.set()
        return inner.calls, await t2

    calls, result = asyncio.run(go())
    assert calls == 1, "the retry started a second model call"
    assert result["n"] == 1


def test_it_is_not_a_cache_once_a_call_finishes_the_key_is_gone():
    async def go():
        inner, c = _client()
        await c.ClassifyDomainIntent(q="x")
        between = c.inflight_count()
        await c.ClassifyDomainIntent(q="x")
        return inner.calls, between, c.inflight_count()

    calls, between, after = asyncio.run(go())
    assert between == 0 and after == 0
    assert calls == 2


def test_a_failure_reaches_every_joiner_and_the_next_call_starts_fresh():
    async def go():
        inner, c = _client()
        inner.gate = asyncio.Event()
        inner.raises = ValueError("boom")
        t1 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        await _settle()
        t2 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        await _settle()
        inner.gate.set()
        results = await asyncio.gather(t1, t2, return_exceptions=True)
        first_calls = inner.calls
        inner.raises = None
        await c.ClassifyDomainIntent(q="x")
        return first_calls, results, inner.calls

    first_calls, results, total = asyncio.run(go())
    assert first_calls == 1
    assert all(isinstance(r, ValueError) for r in results)
    assert total == 2


def test_a_request_that_cannot_be_rendered_runs_uncoalesced_and_warns(caplog):
    async def go():
        inner, c = _client(_Inner(fail_render=True), log=logging.getLogger("inflight-test"))
        inner.gate = asyncio.Event()
        t1 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        t2 = asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
        await _settle()
        inner.gate.set()
        await asyncio.gather(t1, t2)
        return inner.calls

    with caplog.at_level(logging.WARNING, logger="inflight-test"):
        calls = asyncio.run(go())
    assert calls == 2
    assert any(r.levelno == logging.WARNING and "cannot render" in r.getMessage()
               for r in caplog.records)


def test_a_lowercase_attribute_passes_through_unchanged():
    inner, c = _client()
    assert c.with_options is inner.with_options
    assert c.request is inner.request


def _module_level_binders(tree):
    """(lineno, node) of every statement that binds the module-level name `b`, not descending
    into function or class bodies."""
    found = []

    def visit(stmts):
        for n in stmts:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "b" for t in n.targets):
                found.append((n.lineno, n))
            elif isinstance(n, ast.ImportFrom) and any(
                    (a.asname or a.name) == "b" for a in n.names):
                found.append((n.lineno, n))
            for field in ("body", "orelse", "finalbody"):
                visit(getattr(n, field, []) or [])
            for h in getattr(n, "handlers", []) or []:
                visit(h.body)

    visit(tree.body)
    return sorted(found, key=lambda x: x[0])


def test_wiring_engine_o_wraps_the_client_last_and_no_function_shadows_it():
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    binders = _module_level_binders(tree)
    init_lines = [ln for ln, n in binders
                  if isinstance(n, ast.Assign) and "init_baml_client" in ast.unparse(n.value)]
    assert init_lines, "the init_baml_client binding of b was not found"
    wraps = [(ln, n) for ln, n in binders
             if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
             and isinstance(n.value.func, ast.Name) and n.value.func.id == "CoalescingClient"
             and n.value.args and isinstance(n.value.args[0], ast.Name)
             and n.value.args[0].id == "b"]
    assert len(wraps) == 1, "b is not re-bound to CoalescingClient(b, ...)"
    assert wraps[0][0] > max(init_lines)
    assert binders[-1][0] == wraps[0][0], "a later module-level statement rebinds b"

    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("baml_client"):
                raise AssertionError(f"{fn.name} imports from baml_client, bypassing the wrap")
            if isinstance(n, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "b" for t in n.targets):
                raise AssertionError(f"{fn.name} assigns a local `b`, shadowing the wrapped client")


def test_each_event_loop_has_its_own_map():
    """A call left running on a dead loop must never be joined from a live one."""
    inner, c = _client()
    inner.gate = asyncio.Event()  # the first call never finishes

    loop1 = asyncio.new_event_loop()
    try:
        async def start():
            asyncio.ensure_future(c.ClassifyDomainIntent(q="x"))
            await _settle()

        loop1.run_until_complete(start())
        assert inner.calls == 1
        inner.gate = None  # calls on the second loop finish at once

        async def again():
            return await asyncio.wait_for(c.ClassifyDomainIntent(q="x"), timeout=2)

        asyncio.run(again())
    finally:
        loop1.close()
    assert inner.calls == 2
