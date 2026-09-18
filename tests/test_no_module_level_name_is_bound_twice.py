"""A module-level name bound twice, where the second binding ignores the first.

**RULED REPO-WIDE 2026-09-18**, after the class bit twice in two days and the second one was in
the seal-writer's own file. Proposed by Lane 1 (`ia-01/lane/01`), who generalised the per-file
version across the tree and found the second instance; the per-file seal in
`test_every_commit_names_its_lane.py` is retired into this one, so there is **one assertion and
one exclusion list** rather than two of each.

── THE TWO INSTANCES, AND THE SECOND IS THE ARGUMENT ────────────────────────────────────────

**`_EXEMPT`, 2026-09-18.** Master and `lane/91` each grew a definition, 140 lines apart. Git
merged both without a conflict — they never touched — and Python resolved it by last-wins.
Seven exemptions were discarded and a lint reddened on commits it was ruled not to bind. Loud,
at least: it failed.

**`_CORTEX`, the same day, and this one did NOT fail.** The module already bound it to the
cortex-ui **directory** at line 198; I added a binding to a **file inside it** at line 479,
reusing a name I had not checked for. Last-wins made it the file for the whole module, so
`_CORTEX.is_dir()` was permanently False and the `*.contract.ts` scan behind that gate
**never ran again** — 280 lines from the binding that disabled it.

> **It did not fail. It SKIPPED, and announced `"cortex-ui not checked out beside this repo"`
> on a machine where cortex-ui was checked out beside this repo.** The skip's stated reason was
> a claim about the world, and it was false. The file reported green every run.

**A skip is a test that did not run, and its reason is a claim like any other.** Two skips sat
in every run of that file all evening and nobody read the reason, including me, while I was
reading files out of the very directory the message said was absent.

── THE DISCRIMINATOR, WHICH IS A RULE AND NOT A LIST ────────────────────────────────────────

A second binding that **reads the name it rebinds** is a TRANSFORM — `payload = {k: v for k, v
in payload.items() if v is not None}` is one, and flagging it would make this seal noise that
gets silenced. A second binding that **ignores** the first is a COLLISION: nothing carries over,
and the language picks a winner without a word.

Both real instances were collisions; the only transform in the tree is that probe script. So
the rule is derivable rather than enumerated, and the exclusion list below holds exactly what
the rule cannot decide.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where declarations live. Deliberately broad — the two instances were in `tests/` and would be
#: missed by a scan of shipped code only.
_ROOTS = ("src", "agent_fleet", "tests", "scripts", "setup", "policy")

#: Collisions that are known and harmless, each with the reason. NOT a drawer: an entry that
#: stops being a collision FAILS below, so it can only shrink.
_KNOWN: dict[tuple[str, str], str] = {
}


def _collisions() -> list[tuple[str, str, int, int]]:
    """Every module-level name bound more than once where the later binding ignores the earlier.

    Top-level `tree.body` only. A name rebound inside `try`/`except`, `if TYPE_CHECKING`, or a
    version guard is a FALLBACK, which is the pattern this repo uses for flat-versus-packaged
    imports — flagging those would condemn the idiom the containers depend on.
    """
    out: list[tuple[str, str, int, int]] = []
    for r in _ROOTS:
        d = _ROOT / r
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.py")):
            if "__pycache__" in f.parts or ".venv" in f.parts:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue          # not this seal's job to police parseability
            seen: dict[str, int] = {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names = [node.target.id]
                else:
                    continue
                reads = {
                    n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)
                } if node.value is not None else set()
                for name in names:
                    if name in seen and name not in reads:
                        rel = str(f.relative_to(_ROOT)).replace("\\", "/")
                        out.append((rel, name, seen[name], node.lineno))
                    seen[name] = node.lineno
    return out


def test_the_walk_actually_reaches_the_tree():
    """POSITIVE CONTROL. A scan that reached nothing reports no collisions and looks identical
    to a clean tree — the shape this whole seal exists to refuse."""
    count = sum(
        1
        for r in _ROOTS
        if (_ROOT / r).is_dir()
        for f in (_ROOT / r).rglob("*.py")
        if "__pycache__" not in f.parts
    )
    assert count > 400, f"only {count} modules reached; the roots moved and this seal went quiet"


def test_NO_module_level_name_is_SILENTLY_rebound():
    """THE SEAL. A name bound twice where the second ignores the first is a collision the
    language resolves without a word."""
    unknown = [c for c in _collisions() if (c[0], c[1]) not in _KNOWN]
    assert not unknown, (
        "these module-level names are bound twice, and the LATER binding ignores the earlier — "
        "so the language silently picks a winner and everything reading the name gets it:\n  "
        + "\n  ".join(f"{f}:{a},{b}  {n}" for f, n, a, b in unknown)
        + "\n\nTwo of these have already shipped: one discarded seven exemptions and reddened a "
        "lint; the other disabled a cross-repo scan that then SKIPPED with a false reason and "
        "reported green. Rename one, fold them into a single binding, or add the pair to "
        "`_KNOWN` with a reason that says why nothing depends on which one wins."
    )


def test_the_KNOWN_list_ONLY_SHRINKS():
    """THE RATCHET. An entry that is no longer a collision must be deleted, not left standing —
    a list that keeps excusing what nobody needs excused stops being read."""
    live = {(f, n) for f, n, _, _ in _collisions()}
    stale = sorted(k for k in _KNOWN if k not in live)
    assert not stale, (
        f"these are listed as known collisions and are not collisions any more: {stale}. "
        f"Delete them in the commit that fixed them."
    )


def test_a_TRANSFORM_is_not_reported_and_a_COLLISION_is(tmp_path):
    """THE DISCRIMINATOR, CHECKED BOTH WAYS — the half that matters is the second.

    Exempting rebindings that read themselves is what keeps this seal from flagging ordinary
    sequential code. That exemption is only safe if it cannot swallow a real collision, so both
    directions are asserted against a parsed fixture rather than argued for in prose.
    """
    src = (
        "payload = {'a': 1}\n"
        "payload = {k: v for k, v in payload.items() if v}\n"   # TRANSFORM — reads itself
        "TABLE = {'x': 1}\n"
        "TABLE = {'y': 2}\n"                                     # COLLISION — ignores the first
    )
    tree = ast.parse(src)
    seen: dict[str, int] = {}
    flagged: list[str] = []
    for node in tree.body:
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        reads = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
        for name in names:
            if name in seen and name not in reads:
                flagged.append(name)
            seen[name] = node.lineno

    assert flagged == ["TABLE"], (
        f"expected the collision and only the collision; flagged {flagged}. If `payload` "
        f"appears, ordinary sequential code reds and this seal gets silenced; if `TABLE` does "
        f"not, the exemption swallows the defect the seal exists for."
    )


def test_the_per_file_seal_was_RETIRED_into_this_one():
    """ONE ASSERTION, ONE EXCLUSION LIST. The per-file version lived in
    `test_every_commit_names_its_lane.py` and could only ever see its own module — it could not
    have found `_CORTEX`, which was one file over.

    Sealed rather than remembered: leaving both would put an exclusion list in two places, and
    the second one is the one nobody updates.

    ⚠ AND IT SEARCHES FOR THE DEFINITION, NOT THE NAME. The first version matched the bare
    token and reddened against the POINTER COMMENT that names the retired seal — *the instrument
    and its subject share a surface*, so a search for a mechanism by name finds prose about it.
    What must not come back is a `def`, so that is what is searched for.
    """
    other = (_ROOT / "tests" / "test_every_commit_names_its_lane.py").read_text(encoding="utf-8")
    assert "def test_THIS_FILE_DEFINES_ITS_TABLES_EXACTLY_ONCE" not in other, (
        "the per-file duplicate-binding seal is back; it is subsumed by this file, and two "
        "seals asserting one rule means two exclusion lists that disagree"
    )
