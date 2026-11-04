"""The lifespan names each `_registration_calls` key, so a new key must be named there too.

`register_engine_to_mesh` used to take `**_call`, which `test_registration_calls_bind_to_the_helper`
cannot check. Named arguments let that seal bind them, and open a hole `**` didn't have: a key added
to the list and not to the call is dropped silently, and the verb registers without it. This test
closes that hole.
"""
from __future__ import annotations

import ast
import pathlib

from agent_fleet.finance_agent import main as engine


def _keys_the_lifespan_passes() -> set[str]:
    tree = ast.parse(pathlib.Path(engine.__file__).read_text(encoding="utf-8"))
    for loop in ast.walk(tree):
        if not isinstance(loop, ast.For) or not isinstance(loop.iter, ast.Call):
            continue
        if getattr(loop.iter.func, "id", None) != "_registration_calls":
            continue
        for node in ast.walk(loop):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "register_engine_to_mesh":
                return {
                    kw.value.slice.value
                    for kw in node.keywords
                    if isinstance(kw.value, ast.Subscript) and kw.value.value.id == loop.target.id
                }
    raise AssertionError("no register_engine_to_mesh call under a _registration_calls loop")


def test_every_key_of_every_registration_call_reaches_the_helper():
    passed = _keys_the_lifespan_passes()
    calls = engine._registration_calls("http://engine")
    assert calls
    for call in calls:
        assert set(call) == passed, call["verb"]
