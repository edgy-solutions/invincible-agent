"""The lifespan names each `_registration_calls` key, so a new key must be named there too.

`register_engine_to_mesh` used to take `**_call`, which `test_registration_calls_bind_to_the_helper`
cannot check. Named arguments let that seal bind them, and open a hole `**` didn't have: a key added
to the list and not to the call is dropped silently, and the verb registers without it. This test
closes that hole.

The URL is built at the call, not in the list: `endpoint_url=f"{base}/measure/{_call['fn']}"`. A seal
that reads source (safety's `test_engine_scope_exists_in_policy`) can then see the verb in the path;
`_call['endpoint_url']` hid it.
"""
from __future__ import annotations

import ast
import pathlib

from agent_fleet.finance_agent import main as engine


def _the_registration_under_the_loop() -> tuple[ast.For, ast.Call]:
    tree = ast.parse(pathlib.Path(engine.__file__).read_text(encoding="utf-8"))
    for loop in ast.walk(tree):
        if not isinstance(loop, ast.For) or not isinstance(loop.iter, ast.Call):
            continue
        if getattr(loop.iter.func, "id", None) != "_registration_calls":
            continue
        for node in ast.walk(loop):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "register_engine_to_mesh":
                return loop, node
    raise AssertionError("no register_engine_to_mesh call under a _registration_calls loop")


def _keys_the_lifespan_passes() -> set[str]:
    loop, call = _the_registration_under_the_loop()
    return {
        sub.slice.value
        for kw in call.keywords
        for sub in ast.walk(kw.value)
        if isinstance(sub, ast.Subscript) and getattr(sub.value, "id", None) == loop.target.id
    }


def test_every_key_of_every_registration_call_reaches_the_helper():
    passed = _keys_the_lifespan_passes()
    calls = engine._registration_calls()
    assert calls
    for call in calls:
        assert set(call) == passed, call["verb"]


def test_the_verb_is_in_the_path_at_the_call():
    loop, call = _the_registration_under_the_loop()
    url = next(kw.value for kw in call.keywords if kw.arg == "endpoint_url")
    assert ast.unparse(url) == 'f"{base}/measure/{' + loop.target.id + "['fn']}\"", ast.unparse(url)
    served = {v["fn"] for v in engine.VERBS} | set(engine.DECLARED)
    fns = {c["fn"] for c in engine._registration_calls()}
    assert fns <= served, fns - served
