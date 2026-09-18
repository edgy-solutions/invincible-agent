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


def _fn(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(_MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} is gone from main.py — this seal has lost its subject")


def _returns_empty_container(node: ast.AST) -> int | None:
    """Line of a `return []` / `return {}` / `return list()` inside `node`, if any."""
    for n in ast.walk(node):
        if not isinstance(n, ast.Return):
            continue
        v = n.value
        if isinstance(v, (ast.List, ast.Dict, ast.Set)) and not (
            getattr(v, "elts", None) or getattr(v, "keys", None)
        ):
            return n.lineno
        if (
            isinstance(v, ast.Call)
            and isinstance(v.func, ast.Name)
            and v.func.id in ("list", "dict", "set", "frozenset")
            and not v.args
        ):
            return n.lineno
    return None


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


def test_the_async_wrappers_ADD_NO_handler_of_their_own():
    """Reachability is a property of a path. The rule above is asserted on the sync bodies; a
    `try/except` added to the async wrapper would sit ABOVE them and re-swallow the refusal, and
    every assertion in this file would still pass."""
    for name in ("weaviate_hybrid_search", "predicate_hybrid_search"):
        fn = _fn(name)
        handlers = [h.lineno for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
        assert not handlers, (
            f"{name} grew an exception handler at line(s) {handlers}. The wrapper only hands off "
            f"to a thread; a handler here would absorb the 503 the sync body now raises."
        )
