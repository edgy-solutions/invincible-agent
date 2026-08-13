"""META-GUARD — every guard that declares a scope must be able to READ that scope.

THE DEFECT THIS GENERALISES (2026-08-11). `test_no_legacy_dns_references` declared `doc-tools` in
`SCANNED_DIRS` for months. doc-tools is a SIBLING REPO (`../doc-tools`), not a subdirectory, so
the walker's `if not base.exists(): continue` skipped it in silence — and the guard passed green
while asserting coverage of a tree it had never opened. **The forbidden pattern was in fact live
there**: `doc_tools/assets/semantic_linker.py` defaulted `ONTOLOGY_SVC_URL` to
`ontology-agent-svc.default.svc.cluster.local`, which does not resolve in the current cluster.
One declared-and-unread directory, one real offender, zero alarms.

**A disproved guard is worse than a missing one.** A missing guard is a known gap. A disproved
guard is a false CLAIM of coverage, and the claim is what stops anyone looking.

THAT REPAIR WAS SCOPED TO ONE NAME. Fixing `SCANNED_DIRS` in one file left the general question
unasked: *which other guards assert coverage they cannot deliver?* Per
`[[naming-a-class-is-not-a-guard]]`, naming that class in a document prevents nothing — only a
check that fails does. This is that check.

WHAT IT ASSERTS: for every module-level scope constant in the test tree (named `*_DIRS`,
`*_ROOTS`, `*_TREES`, `*_PATHS`), every directory it names must EXIST in this repo. A name that
resolves as a SIBLING but not as a subdirectory is called out specifically, because that was the
actual mistake and it is the one that looks correct to a reader — `doc-tools` was not a typo, it
was a real tree one level up.

WHAT IT DOES NOT ASSERT: that a guard's scope is WIDE ENOUGH. Declared-and-unread (this) and
declared-too-narrow (not this) are different defects; the first is a lie, the second is a
judgement. Conflating them would make this guard argue about scope decisions it cannot evaluate,
and a guard that argues gets relaxed.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TESTS = _ROOT / "tests"

#: Constants whose value is a collection of directory names this repo should contain.
#: Keyed on the naming convention rather than on content, so a new guard following the
#: convention is covered the day it lands rather than when someone remembers to add it here.
_SCOPE_SUFFIXES = ("_DIRS", "_ROOTS", "_TREES", "_PATHS")

#: Values that are legitimately not repo-relative directories.
_NOT_A_DIR_HINT = ("*", "?", "://", "{", "}", " ")


def _looks_like_a_scope_name(name: str) -> bool:
    return name.isupper() and name.endswith(_SCOPE_SUFFIXES)


def _scope_constants():
    """Yield (file, const_name, [values]) for every module-level scope constant in tests/."""
    for path in sorted(_TESTS.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in tree.body:  # MODULE LEVEL only — a local is not a declared scope
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name) or not _looks_like_a_scope_name(target.id):
                    continue
                if not isinstance(node.value, (ast.Tuple, ast.List)):
                    continue
                values = [
                    e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
                if values:
                    yield path, target.id, values


def _candidate_dirs(values):
    """Filter to values that are plausibly repo-relative directory names."""
    out = []
    for v in values:
        if not v or v.startswith(".") or any(h in v for h in _NOT_A_DIR_HINT):
            continue
        if (_ROOT / v).is_file():  # a declared FILE is a different thing, and it exists
            continue
        out.append(v)
    return out


def test_the_sweep_finds_something_to_check():
    """A meta-guard over an empty set passes vacuously — the exact failure it exists to catch,
    turned on itself. If the naming convention changes, this fails rather than going quiet."""
    found = list(_scope_constants())
    assert found, (
        "no scope constants found in tests/ — either the naming convention moved, or this "
        "guard is now checking nothing and reporting success"
    )


def test_every_declared_guard_scope_EXISTS():
    """The general form of the doc-tools defect."""
    missing = []
    for path, name, values in _scope_constants():
        for d in _candidate_dirs(values):
            if not (_ROOT / d).is_dir():
                missing.append(f"{path.relative_to(_ROOT)}::{name} -> {d!r}")

    assert not missing, (
        "guard(s) declare a scope that does not exist in this repo. A walker that skips a "
        "missing root passes green while claiming coverage it never had — the disproved-guard "
        "defect, which is worse than a missing guard because the claim stops anyone looking.\n\n"
        + "\n".join(f"    - {m}" for m in missing)
    )


def test_no_declared_scope_names_a_SIBLING_repo():
    """The mistake pinned by SHAPE, because it did not look like a mistake.

    `doc-tools` was not a typo — it was a real tree at `../doc-tools`, which is exactly why it
    read as correct to everyone who saw the list. Scanning a sibling requires it checked out at
    a known path and revision: a different mechanism, not something bought by naming a string in
    a tuple. See `[[check-from-the-consumers-side]]`.
    """
    siblings = []
    for path, name, values in _scope_constants():
        for d in _candidate_dirs(values):
            if not (_ROOT / d).is_dir() and (_ROOT.parent / d).is_dir():
                siblings.append(f"{path.relative_to(_ROOT)}::{name} -> {d!r} (../{d} exists)")

    assert not siblings, (
        "guard scope(s) name a SIBLING REPO rather than a subdirectory of this repo:\n\n"
        + "\n".join(f"    - {s}" for s in siblings)
        + "\n\nCross-repo scanning needs the sibling checked out at a known path and revision. "
          "Naming it here buys a false claim of coverage, which this project already shipped once."
    )


def test_a_phantom_scope_would_be_CAUGHT(monkeypatch):
    """BREAK-ON-PURPOSE. A leg of a litany that has never gone red is not yet a check.

    Injects a scope constant that cannot exist and asserts the checker reports it — proving the
    detector fires, rather than proving only that today's scopes happen to be clean.
    """
    real = _scope_constants

    def _with_phantom():
        yield from real()
        yield (_TESTS / "test_synthetic.py", "_SCANNED_DIRS", ["no-such-tree-xyzzy"])

    monkeypatch.setattr(
        "tests.routing.test_guard_scopes_are_real._scope_constants", _with_phantom, raising=False
    )
    globals()["_scope_constants"] = _with_phantom
    try:
        with pytest.raises(AssertionError, match="no-such-tree-xyzzy"):
            test_every_declared_guard_scope_EXISTS()
    finally:
        globals()["_scope_constants"] = real
