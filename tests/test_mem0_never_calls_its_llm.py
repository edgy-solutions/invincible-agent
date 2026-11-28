"""mem0 never calls its own chat model: every mem0 write passes ``infer=False``.

The architect, via Chris, 2026-11-28: the sandbox values point mem0's LLM
(``MEM0_LLM_MODEL: "phi4-16k:14b"``) at the shared small-model server, yet
that server sees only embedding calls from sandbox. "Chris must be told before
that model is ever called on that server, because it would evict another
project's model."

Why it does not fire today is a property of the call sites, not of the
configuration. Read from mem0's own ``Memory`` (mem0ai 2.0.4), its LLM runs on
four paths only:

- ``add(..., infer=True)``: fact extraction. ``infer`` DEFAULTS TO True.
- ``add(..., memory_type="procedural_memory")``: procedural summarisation.
- ``add`` with image content in the messages: vision parsing.
- ``search(..., rerank=True)``, when a reranker is configured.

Every fleet call site passes ``infer=False`` (ADR-0016 r2, Tier 0(b)), and
none passes ``memory_type`` or ``rerank=True``. This seal holds that. A new
``m.add(...)`` that leaves ``infer`` out gets mem0's default and would start
calling the 14 GB model on that server with no config change at all. That is
the surprise this seal exists to stop.

The control (``test_the_checker_refuses_*``) runs the same checker over
sources that break each rule, so a checker that cannot see a call site fails
here rather than passing vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ("agent_fleet", "src")
SKIP_PARTS = {".venv", "__pycache__", "tests", "baml_client", "node_modules"}

# The mem0 entry point. A name bound from it is a mem0 Memory.
FACTORY = "get_mem0_memory"


def _receivers(tree: ast.AST) -> set[str]:
    """Names assigned from ``get_mem0_memory()`` (awaited or not) anywhere in the module."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if isinstance(value, ast.Await):
            value = value.value
        if not (isinstance(value, ast.Call) and _callee_name(value.func) == FACTORY):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                names.add(t.id)
    return names


def _callee_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _is_const(node: ast.AST | None, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value is value


def check_source(source: str, label: str = "<src>") -> tuple[list[str], list[str]]:
    """Return (sites, violations) for mem0 ``add``/``search`` calls in ``source``.

    A site is either a direct call ``m.add(...)`` or a bridged call whose first
    positional argument is the bound method, e.g.
    ``asyncio.to_thread(m.add, ..., infer=False)``. The keywords of that call
    are the ones mem0 receives.
    """
    tree = ast.parse(source)
    recv = _receivers(tree)
    sites: list[str] = []
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = None
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in recv
        ):
            method = node.func.attr
        elif (
            node.args
            and isinstance(node.args[0], ast.Attribute)
            and isinstance(node.args[0].value, ast.Name)
            and node.args[0].value.id in recv
        ):
            method = node.args[0].attr
        if method not in ("add", "search"):
            continue
        where = f"{label}:{node.lineno} {method}"
        sites.append(where)
        if method == "add":
            if not _is_const(_kw(node, "infer"), False):
                bad.append(f"{where}: infer is not the literal False")
            if _kw(node, "memory_type") is not None:
                bad.append(f"{where}: passes memory_type")
        if method == "search" and not (
            _kw(node, "rerank") is None or _is_const(_kw(node, "rerank"), False)
        ):
            bad.append(f"{where}: passes rerank")
    return sites, bad


def _fleet_files() -> list[Path]:
    out: list[Path] = []
    for top in SCAN:
        for p in (ROOT / top).rglob("*.py"):
            if SKIP_PARTS.intersection(p.relative_to(ROOT).parts):
                continue
            out.append(p)
    return out


def _fleet_census() -> tuple[list[str], list[str]]:
    sites: list[str] = []
    bad: list[str] = []
    for p in _fleet_files():
        text = p.read_text(encoding="utf-8")
        if FACTORY not in text:
            continue
        s, b = check_source(text, p.relative_to(ROOT).as_posix())
        sites += s
        bad += b
    return sites, bad


def test_no_mem0_call_in_the_fleet_reaches_its_llm():
    _, bad = _fleet_census()
    assert bad == [], (
        "a mem0 call site can reach mem0's chat model (MEM0_LLM_MODEL). "
        "Chris's word comes first: " + "; ".join(bad)
    )


def test_the_census_sees_both_engines_writes():
    """Non-vacuity: the two known writers (engines A and E) are found as add sites."""
    sites, _ = _fleet_census()
    adds = {s.split(":")[0] for s in sites if s.endswith(" add")}
    assert {
        "agent_fleet/neo4j_expert/service.py",
        "agent_fleet/restate_analyst/main.py",
    } <= adds, sites


_BRIDGED = """
async def f():
    m = await get_mem0_memory()
    await asyncio.to_thread(m.add, messages=[], user_id="u"{extra})
"""


def test_the_checker_passes_infer_false():
    _, bad = check_source(_BRIDGED.format(extra=", infer=False"))
    assert bad == []


def test_the_checker_refuses_a_bridged_add_without_infer():
    sites, bad = check_source(_BRIDGED.format(extra=""))
    assert len(sites) == 1 and len(bad) == 1, (sites, bad)


def test_the_checker_refuses_a_direct_add_with_infer_true():
    src = "m = get_mem0_memory()\nm.add([], infer=True)\n"
    assert len(check_source(src)[1]) == 1


def test_the_checker_refuses_a_procedural_add():
    src = "m = get_mem0_memory()\nm.add([], infer=False, memory_type='procedural_memory')\n"
    assert len(check_source(src)[1]) == 1


def test_the_checker_refuses_a_reranked_search():
    src = "m = get_mem0_memory()\nm.search('q', rerank=True)\nm.search('q')\n"
    sites, bad = check_source(src)
    assert len(sites) == 2 and len(bad) == 1, (sites, bad)
