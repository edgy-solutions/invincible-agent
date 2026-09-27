"""RULED 2026-09-14 — a mid-query Weaviate failure is a REFUSAL, never an empty success.

THE CONSUMER IS WHAT MAKES THIS URGENT, and it is worse than "the caller cannot tell". Both
searches used to `return []` on any exception. `/resolve` reads that empty list, prints
**"WEAVIATE COLD START DETECTED"**, falls back to `_SPARQL_MAINTENANCE_CLASSES`, and answers from
the MAINTENANCE ontology. So a transient Weaviate error produced a confident WRONG-DOMAIN answer
under a banner naming a diagnosis that was false — not a missing answer, a wrong one.

ADR-0009 already forbids exactly this: Weaviate is **required routing infrastructure** and
`/search_predicates` returns 503 when it is unavailable *"rather than silently degrading to
exact-match"*. The route honours that for an absent client or collection; these two handlers were
the hole underneath it — the same failure one frame down, answered with an empty success.

**AN EMPTY RESULT STILL MEANS WHAT IT MEANT.** Cold start still reaches the graph fallback; "no
predicate matched" is still an empty list. Only the FAILURE is separated out, which is the entire
distinction being drawn.

WHY THIS SEAL IS STRUCTURAL, corrected 2026-09-14: I first wrote that `main.py` "cannot be
imported by any test". **It can.** `tests/test_predicate_hybrid_search.py` stubs rdflib, weaviate
and baml_client and imports it — and reversing that file's `test_hybrid_exception_returns_empty`
is what disproved the claim I had put in three files. Importing costs a stub harness; it is not
impossible.

So the BEHAVIOURAL half of this rule lives there, beside the harness, rather than duplicating it.
What is asserted HERE is what behaviour cannot reach: that no handler ANYWHERE in those functions
returns an empty container, and that the async wrappers add no handler of their own. Asserted over
the PARSED SOURCE — which also means it cannot be fooled by a comment quoting the code it replaced,
the way a grep would be.

Run: uv run --frozen pytest tests/test_a_substrate_failure_is_not_an_empty_result.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_MAIN = _REPO / "agent_fleet" / "ontology_service" / "main.py"

#: The two the ruling names. Both are the sync bodies — the async wrappers only hand off to a
#: thread, so a handler added there would be a third place for this defect to live.
_RULED = ("_weaviate_hybrid_search_sync", "_predicate_hybrid_search_sync")

#: THE THIRD REFUSING BODY, added 2026-09-26 with the `ONTOLOGY_CLASS_POOL_VIA_MESH` arm. It is
#: deliberately NOT in `_RULED`: it holds no driver, so it has neither the `try/except` nor the
#: BM25 fallback the three parametrized arms assert on, and putting it there would red two of them
#: for having the correct shape. It gets its own arm asserting the same RULING, and it belongs in
#: the derived caller population below — a handler above it swallows a 503 just as effectively.
_MESH_ARM = "_class_pool_via_mesh_sync"


def _fn(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from main.py — this seal has lost its subject")


def _is_empty_container(v: ast.AST | None) -> bool:
    """Is this expression an empty container LITERAL or an empty builtin constructor call?"""
    if isinstance(v, (ast.List, ast.Dict, ast.Set)) and not (
        getattr(v, "elts", None) or getattr(v, "keys", None)
    ):
        return True
    return (
        isinstance(v, ast.Call)
        and isinstance(v.func, ast.Name)
        and v.func.id in ("list", "dict", "set", "frozenset")
        and not v.args
    )


def _returns_empty_container(node: ast.AST) -> int | None:
    """Line of a `return []` / `return {}` / `return list()` inside `node`, if any.

    **AND OF A `return [], mode`.** The ruled functions' return type became `(rows, mode)` on
    2026-09-26, which DEMOTED this detector without touching it: it only ever looked at the
    returned expression itself, so a handler writing `return [], "bm25"` — an empty success with a
    retrieval mode stapled on, the same defect under a new spelling — walked straight past it. The
    seal would have stayed green and reported the ruling held.

    Only ONE LEVEL of tuple is unwrapped, deliberately. The subject is a function's own return
    SHAPE; a container nested inside an element of that tuple is somebody else's payload, not this
    rule's empty success. Peel the spine, not the arguments.
    """
    for n in ast.walk(node):
        if not isinstance(n, ast.Return):
            continue
        v = n.value
        if _is_empty_container(v):
            return n.lineno
        if isinstance(v, ast.Tuple) and any(_is_empty_container(e) for e in v.elts):
            return n.lineno
    return None


def test_the_DETECTOR_sees_an_empty_container_inside_a_returned_tuple():
    """THE POSITIVE CONTROL FOR THE MATCHER, because a detector that finds nothing and a subject
    with nothing to find are the same green.

    The shapes are parsed here rather than looked for in `main.py`: what is under test is the REACH
    of `_returns_empty_container`, and the file under seal is supposed to contain none of them. The
    last two are the negatives — a non-empty tuple return must NOT be flagged, or the widening
    would red every healthy projection in the module and get reverted as noise.
    """
    handler = ast.parse(
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception:\n"
        "        return [], None\n"
    )
    assert _returns_empty_container(handler) is not None, "the tuple form is still invisible"
    for src, want in (
        ("def f():\n    return []\n", True),
        ("def f():\n    return [], 'bm25'\n", True),
        ("def f():\n    return list(), None\n", True),
        ("def f():\n    return rows, mode\n", False),
        ("def f():\n    return [{'uri': 'x'}], 'hybrid'\n", False),
    ):
        got = _returns_empty_container(ast.parse(src)) is not None
        assert got is want, f"detector said {got} for {src!r}"


@pytest.mark.parametrize("name", _RULED)
def test_no_exception_handler_returns_an_EMPTY_SUCCESS(name):
    """THE RULING. A handler that returns an empty container makes a failure indistinguishable
    from a legitimate no-match — and downstream, indistinguishable from a cold start."""
    fn = _fn(name)
    offenders = [
        h.lineno
        for h in ast.walk(fn)
        if isinstance(h, ast.ExceptHandler) and _returns_empty_container(h) is not None
    ]
    assert not offenders, (
        f"{name} converts an exception into an empty success at handler line(s) {offenders}. "
        f"/resolve reads an empty list as WEAVIATE COLD START and answers from the maintenance "
        f"ontology, so this returns a wrong answer rather than no answer."
    )


@pytest.mark.parametrize("name", _RULED)
def test_the_handler_REFUSES_with_503(name):
    """THE POSITIVE HALF. Removing the empty return is satisfied by swallowing the exception
    entirely, or by letting it surface as an unlabelled 500. ADR-0009 asks for a 503, which says
    *the substrate is unavailable* rather than *the service is broken*."""
    fn = _fn(name)
    raises = []
    for h in ast.walk(fn):
        if not isinstance(h, ast.ExceptHandler):
            continue
        for n in ast.walk(h):
            if not (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)):
                continue
            func = n.exc.func
            if isinstance(func, ast.Name) and func.id == "HTTPException":
                codes = [
                    kw.value.value
                    for kw in n.exc.keywords
                    if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
                ]
                raises.extend(codes)
    assert 503 in raises, (
        f"{name} does not refuse with a 503 from its exception handler; it raises {raises or 'nothing'}"
    )


@pytest.mark.parametrize("name", _RULED)
def test_the_EMBED_FALLBACK_is_untouched(name):
    """THE CONTROL, and it is the one that keeps this fix from being a different change.

    An embedding-gateway failure falls back to BM25 — a DEGRADATION, not a substrate failure — and
    that path must still exist. If this assertion ever fails, someone has collapsed two different
    failures into one refusal, and the fleet loses search entirely whenever LiteLLM hiccups.

    (The BM25 fallback being SILENT is a separate, ruled defect: the retrieval mode belongs in the
    return. That is the interface's half, not this one.)
    """
    fn = _fn(name)
    calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "bm25"
    ]
    assert calls, f"{name} no longer has a BM25 fallback for an embed failure"


def _callers_of_the_sync_bodies() -> dict[str, list[int]]:
    """Every function in `main.py` that names one of the refusing sync bodies, and its handlers.

    **DERIVED, BECAUSE THE HAND-TYPED VERSION WENT STALE THE DAY A THIRD WRAPPER ARRIVED.** This
    was a literal `("weaviate_hybrid_search", "predicate_hybrid_search")`, and on 2026-09-26
    `class_pool_with_mode` was added ABOVE both of them as `/resolve`'s fork point — a new frame in
    exactly the position this arm exists to guard, invisible to it, and nothing about adding it
    would have prompted anyone to edit a tuple in a different file.

    The population is every function whose body REFERENCES a refusing body by name. That spelling
    covers `asyncio.to_thread(_weaviate_hybrid_search_sync, ...)`, where the callee is an argument
    rather than the called expression, and it is what the wrappers actually do.
    """
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    refusing = set(_RULED) | {_MESH_ARM}
    found: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in refusing:
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        if names & refusing:
            found[node.name] = [
                h.lineno for h in ast.walk(node) if isinstance(h, ast.ExceptHandler)
            ]
    return found


def test_the_wrappers_ADD_NO_handler_of_their_own():
    """Reachability is a property of a path. The rule above is asserted on the sync bodies; a
    `try/except` added to a frame ABOVE them would re-swallow the refusal, and every other
    assertion in this file would still pass.
    """
    callers = _callers_of_the_sync_bodies()
    offenders = {n: h for n, h in callers.items() if h}
    assert not offenders, (
        f"a frame above the refusing sync bodies grew an exception handler: {offenders}. These "
        f"wrappers only hand off to a thread; a handler here would absorb the 503 the sync body "
        f"raises, and the rest of this file cannot see it."
    )


def test_the_DERIVED_population_still_contains_the_frames_it_was_written_for():
    """AN ANCHOR COUNT, because a derivation that silently matches NOTHING is the same green as a
    clean module. If the wrappers are ever renamed or the call moves behind an indirection the
    name-reference rule cannot see, this reds and says the population went empty or thin — rather
    than the arm above quietly guarding a set of zero.
    """
    callers = _callers_of_the_sync_bodies()
    assert "weaviate_hybrid_search" in callers, sorted(callers)
    assert "predicate_hybrid_search" in callers, sorted(callers)
    assert "class_pool_with_mode" in callers, (
        f"the /resolve fork point is not in the derived population: {sorted(callers)}"
    )
    assert len(callers) >= 3, sorted(callers)


def test_the_MESH_ARM_refuses_rather_than_returning_an_empty_pool():
    """THE SAME RULING ON THE OTHER ARM'S SHAPE, which is why it is not in `_RULED`.

    The three parametrized arms above assume the DRIVER shape: a `try/except` around a Weaviate
    call, with a BM25 fallback inside it. The mesh arm holds no driver — it reads a `MeshResult`
    whose `outcome` already distinguishes answered / empty / failed / unreachable, so its refusal
    lives in an `if`, not a handler, and it has no `bm25` call of its own to control. Forcing it
    into `_RULED` would red two arms for having the right shape.

    What must hold is the ruling itself: the two FAILURE outcomes raise, and `empty` does not.
    """
    fn = _fn(_MESH_ARM)
    src = ast.get_source_segment(_MAIN.read_text(encoding="utf-8"), fn) or ""
    assert '"failed"' in src and '"unreachable"' in src, (
        f"{_MESH_ARM} no longer distinguishes the failure outcomes; a MeshResult.failed read as an "
        f"empty pool is the cold-start misdiagnosis this whole file is about"
    )
    codes = [
        kw.value.value
        for n in ast.walk(fn)
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
        and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "HTTPException"
        for kw in n.exc.keywords
        if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)
    ]
    assert 503 in codes, f"{_MESH_ARM} raises {codes or 'nothing'}, never a 503"
