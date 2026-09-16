"""Every `register_*_to_mesh(...)` call in the fleet must BIND to the helper it calls.

THE FAILURE IT CATCHES, AND WHY NOTHING ELSE DOES. A registration call with a keyword the helper
does not accept raises `TypeError` — at startup, inside the `except Exception` that every engine
wraps its registration loop in. The engine then boots, serves `/health`, answers when addressed
by name, and is **never routed to**, because it registered nothing. The guard prints
`REGISTRATION FAILED` and sets `registration_incomplete`, so it is loud in a log nobody is
reading at the time. Static typing does not catch it (these are dynamic kwargs), unit tests do
not catch it (the loop is in a lifespan), and a healthy-looking pod does not show it.

THREE KEYWORDS ONCE DRIFTED IN A SHIPPED ENGINE — `endpoint` for `endpoint_url`, `synonyms` for
`verb_synonyms`, `anti_synonyms` for `verb_anti_synonyms` — and were repaired three commits
later. This seal exists so the next one is a red in the suite rather than a conversation between
two people reading two different trees.

**A RED BELONGS TO A SHA, NOT A DIRECTORY.** That exchange cost a message round because the
finding was measured in a worktree that was behind master and reported as a fact about the fleet.
A check that runs in CI against a known commit removes the whole class of argument — which is the
real reason to prefer a seal over a careful reader.

WHAT THIS CANNOT SEE, stated rather than left as coverage: a call whose keywords are supplied by
`**kwargs` at runtime. Those are reported as UNCHECKABLE and fail this seal rather than passing
quietly — an unbindable call and an unreadable one are different states, and only one of them is
safe to ignore.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_fleet.utils.mesh_registration import (  # noqa: E402
    register_engine_to_mesh, register_presentation_to_mesh,
)

HELPERS = {
    "register_engine_to_mesh": register_engine_to_mesh,
    "register_presentation_to_mesh": register_presentation_to_mesh,
}

#: The floor, and it is set CLOSE to the real number on purpose. An AST walk that matches nothing
#: passes every assertion below, and a population of zero is how this kind of check goes quiet —
#: a helper rename, a refactor into a wrapper, a move out of `agent_fleet/`. But a LOW floor is
#: barely better than none: a floor of 4 over a population of 40 cannot tell "all present" from
#: "nine tenths missing", which is a shape this repo has already paid for.
#:
#: DERIVED, NOT GUESSED: 40 call sites across 13 engines, measured 2026-09-15 at `15f0429` by
#: running `_call_sites()`. Pinned a little below so retiring one verb is not a red, and the
#: failure prints the delta and the per-file counts so a drop is legible rather than a bare
#: inequality.
MINIMUM_CALL_SITES = 35


def _call_sites():
    """-> (file, lineno, helper_name, kwarg_names, has_star_kwargs) for every call in the tree."""
    for path in sorted(ROOT.joinpath("agent_fleet").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in HELPERS:
                continue
            kwargs = [k.arg for k in node.keywords if k.arg is not None]
            starred = any(k.arg is None for k in node.keywords)
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            yield rel, node.lineno, name, kwargs, starred


def test_the_walk_still_finds_the_registration_calls():
    """THE FLOOR, ASSERTED FIRST because every other test here passes on an empty population."""
    sites = list(_call_sites())
    by_file: dict[str, int] = {}
    for rel, _lineno, *_rest in sites:
        by_file[rel] = by_file.get(rel, 0) + 1
    assert len(sites) >= MINIMUM_CALL_SITES, (
        f"found {len(sites)} registration call sites against a floor of {MINIMUM_CALL_SITES} — "
        f"short by {MINIMUM_CALL_SITES - len(sites)}. The walk has stopped seeing calls it used "
        f"to see (a helper rename, a wrapper, a move out of agent_fleet/), and every assertion "
        f"in this file now passes on whatever is left. Per file: {by_file}")


def test_every_registration_call_binds_to_its_helper():
    """A keyword the helper does not accept is a verb that never registers."""
    problems = []
    for rel, lineno, helper_name, kwargs, starred in _call_sites():
        sig = inspect.signature(HELPERS[helper_name])
        if starred:
            problems.append(
                f"  {rel}:{lineno} {helper_name}(**kwargs) — UNCHECKABLE statically. The "
                f"keywords are assembled at runtime, so this seal cannot say whether they bind.")
            continue
        unknown = [k for k in kwargs if k not in sig.parameters]
        if unknown:
            problems.append(
                f"  {rel}:{lineno} {helper_name} passes {unknown}, which it does not accept. "
                f"Every call raises TypeError and the verb never registers.")
            continue
        try:
            sig.bind(**{k: None for k in kwargs})
        except TypeError as exc:
            problems.append(f"  {rel}:{lineno} {helper_name} does not bind: {exc}")
    if problems:
        pytest.fail(
            "registration calls that cannot succeed — the engine boots, reports healthy, and is "
            "never routed to:\n" + "\n".join(problems))


def test_the_bind_check_can_say_no():
    """THE CONTROL. Both directions, because each fails silently in its own way.

    A checker that only ever saw correct calls has not been shown able to reject one; a checker
    that rejected everything would be indistinguishable from one that works, until it blocked a
    correct call nobody could fix.
    """
    sig = inspect.signature(register_engine_to_mesh)

    good = ["name", "description", "verb", "input_uri", "output_uri", "endpoint_url"]
    assert all(k in sig.parameters for k in good), (
        "the helper's own parameter names have changed; this control's reference point is stale "
        "and the positive direction proves nothing")
    sig.bind(**{k: None for k in good})  # must not raise

    for wrong in ("endpoint", "synonyms", "anti_synonyms"):
        assert wrong not in sig.parameters, (
            f"{wrong!r} is now an accepted parameter — the historical defect this seal was "
            f"written for is no longer a defect, and its docstring is misleading")

    with pytest.raises(TypeError):
        sig.bind(**{k: None for k in good[:-1]})  # endpoint_url missing — required


def test_the_walk_reads_calls_the_grep_would_miss():
    """A control on the INSTRUMENT, not the data: the walk must see a call written across lines
    and one reached through an attribute, since both are how a real call site is spelled."""
    src = (
        "register_engine_to_mesh(\n"
        "    name='x',\n"
        "    endpoint_url='y',\n"
        ")\n"
        "mod.register_presentation_to_mesh(name='z')\n"
    )
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in HELPERS:
                found.append((name, [k.arg for k in node.keywords]))
    assert len(found) == 2, f"the walk missed a spelling of the call: {found}"
    assert found[0][1] == ["name", "endpoint_url"], "multi-line kwargs were not collected"
    assert found[1][0] == "register_presentation_to_mesh", "an attribute call was not seen"
