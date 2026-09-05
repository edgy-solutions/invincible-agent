"""THE ARITY OF `_resolve_subject`'s RETURN, DERIVED — not transcribed into a comment.

WHY THIS FILE EXISTS. `tests/test_tier3_urn_propagation.py` carries a note:

    THIS PIN WAS STALE FOR THREE WEEKS. f9a9be0 grew the tuple and did not update this
    assertion, so the file has been red since 2026-07-10 and the redness was read past as
    "the usual failures".

That note is doing a seal's job. It worked twice — the 7th element in July, the 8th on
2026-09-05 — and both times it worked by a human reading prose at the moment of editing, which
is the mechanism that failed the first time. **A comment that must be read to be obeyed is not
a guard.**

WHAT IS ACTUALLY DERIVED HERE: the arity comes from the SOURCE — every `return` in
`_resolve_subject` — and everything else is checked against it. Nothing in this file states a
number, so growing the tuple cannot leave a literal behind for someone to notice later.

THE INVARIANT THAT MATTERS MOST is that the ERROR return and the happy return agree. They are
~200 lines apart, the error path is the one nobody exercises by hand, and a caller unpacking N
names against an N-1 tuple raises ValueError deep inside routing — surfacing as an infra error
on a query that merely could not reach engine-o.

Run: uv run --frozen pytest tests/routing/test_resolve_subject_tuple_arity.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SUP_PATH = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_SUP = _SUP_PATH.read_text(encoding="utf-8")
_FN = "_resolve_subject"


def _return_arities() -> list[int]:
    """Every `return (...)` inside _resolve_subject, as element counts."""
    tree = ast.parse(_SUP)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == _FN
    )
    return [
        len(n.value.elts)
        for n in ast.walk(fn)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)
    ]


def _arity() -> int:
    ar = _return_arities()
    assert ar, f"{_FN} has no tuple returns — this seal's premise changed"
    return ar[0]


# ── the function agrees with itself ─────────────────────────────────────────

def test_every_return_path_has_the_same_arity():
    """THE ERROR PATH AND THE HAPPY PATH, ~200 lines apart. A caller unpacking N names
    against an N-1 tuple raises ValueError deep in routing, and it surfaces as an infra
    error on a query whose only problem was that engine-o was unreachable."""
    ar = _return_arities()
    assert len(set(ar)) == 1, (
        f"{_FN} returns tuples of differing length {sorted(set(ar))} — every return path "
        f"must have the same shape"
    )


def test_there_is_more_than_one_return_to_compare():
    """Non-vacuity: one return trivially agrees with itself and proves nothing about the
    divergence this file exists to catch."""
    assert len(_return_arities()) >= 2


# ── every consumer agrees with the function ─────────────────────────────────

def _direct_unpack_arities(src: str) -> list[int]:
    """`(a, b, c) = _resolve_subject(...)` — the unpack written against the call itself."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        f = node.value.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name != _FN:
            continue
        for t in node.targets:
            if isinstance(t, ast.Tuple):
                out.append(len(t.elts))
    return out


def test_the_supervisors_own_unpack_matches():
    got = _direct_unpack_arities(_SUP)
    assert got, "no direct unpack of _resolve_subject found in the supervisor"
    for n in got:
        assert n == _arity(), (
            f"the supervisor unpacks {n} names from a {_arity()}-element return"
        )


def _consumer_files() -> list[Path]:
    """Test files that call _resolve_subject — the ones a tuple growth breaks."""
    return [
        p for p in (_REPO / "tests").rglob("test_*.py")
        if _FN in p.read_text(encoding="utf-8")
        and p.name != Path(__file__).name
    ]


def test_there_are_consumers_to_check():
    """If this ever finds none, the seal has stopped guarding anything and should be
    deleted rather than left green."""
    assert _consumer_files(), "no test file consumes _resolve_subject"


def test_no_consumer_states_a_stale_arity():
    """THE EXACT STALENESS THE COMMENT DESCRIBES. `assert len(result) == 7` against an
    8-element return is the failure that sat red for three weeks; now it is derived."""
    bad = []
    for p in _consumer_files():
        for m in re.finditer(r"len\(result\)\s*==\s*(\d+)", p.read_text(encoding="utf-8")):
            if int(m.group(1)) != _arity():
                bad.append(f"{p.name}: len(result) == {m.group(1)}")
    assert not bad, f"arity is {_arity()}; stale pins: {bad}"


def test_no_consumer_unpacks_the_wrong_number_of_names():
    """`_, _, _, x, _, _, _ = result` is the same staleness without a number in it — and it
    is the form that broke on 2026-09-05, three sites of it, none carrying a literal for a
    grep to find."""
    bad = []
    for p in _consumer_files():
        src = p.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Name) and node.value.id == "result"):
                continue
            for t in node.targets:
                if isinstance(t, ast.Tuple) and len(t.elts) != _arity():
                    bad.append(f"{p.name}:{node.lineno} unpacks {len(t.elts)}")
    assert not bad, f"arity is {_arity()}; wrong unpacks: {bad}"


# ── the comment that did this job keeps its warning ─────────────────────────

def test_the_original_note_is_still_there():
    """Not redundant with the seal — the note explains WHY the discipline exists, and a
    future editor deleting it as 'covered by a test now' loses the story of how a red suite
    got read past for three weeks. The seal enforces; the note teaches."""
    tier3 = _REPO / "tests" / "test_tier3_urn_propagation.py"
    assert "STALE FOR THREE WEEKS" in tier3.read_text(encoding="utf-8")
