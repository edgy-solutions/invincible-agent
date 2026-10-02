"""THE DEFAULT ITSELF, AND EVERY CLAIM MADE ABOUT IT.

THE DEFAULT IS ON, RULED BY MEASUREMENT 2026-10-01. The dispatch was "flip the default on;
three-fire census; if any row moves, flip back". The census fired both arms in-process against the
sandbox stores for every walk-census row, three times each: 21 rows x 2 routes, no error, no fire
unstable within an arm, and NOT ONE ROW MOVED -- same ids, same order, same scores, same mode. The
mesh arm served all 63 on-fires on both routes, every pool held 10 rows, and the pools differed
across rows, so that zero was a census that could have moved and did not
(`docs/measurements/class-pool-flag-default-on-census-2026-10-01.md`). The literal is `"true"`.

WHY THIS FILE EXISTS. `ONTOLOGY_CLASS_POOL_VIA_MESH` is the route-migration flag, and the repo states
its default in prose in many places -- the pilot reports' headers, comments in `main.py`, and the
parity seals' own docstrings. Until this file, **nothing checked any of them.**
The parity seal (`test_the_migrated_route_returns_the_same_rows.py`) is not that check and cannot
be: it `monkeypatch.setattr`s the flag for both arms by design, which is exactly right for parity
and exactly why the module-level DEFAULT is invisible to it.

THAT WAS MEASURED, NOT ASSUMED. With the default flipped to `"true"` in the artifact, the whole
suite was fired three times: 38 failed / 988 passed / 117 skipped, the same three times, and the
failure IDENTITIES were byte-identical to the three-fire flag-off baseline -- not one row moved.
That is not evidence the default is safe to move. It is evidence that **no arm's outcome depended
on the default**, because every test reader monkeypatches it and the single consumer
(`class_pool_with_mode`) reads a module global fixed at import. A census whose population cannot
move reports a clean result it never looked at. This file is the arm that moves.

SO A FLIP OF THE DEFAULT COSTS SOMETHING, IN BOTH DIRECTIONS. The 2026-10-01 flip measured it:
`"false"` to `"true"` red three arms and named ten prose homes. Flipping back now reds
`test_the_DEFAULT_is_read_from_the_ARTIFACT_and_it_is_on`, reds the resolve arm, and reds
`test_EVERY_CLAIM_about_the_default_agrees_with_the_artifact` once per prose home -- which is the
point: a correction has as many homes as the claim had, and the red names them. For the dated
measurement under `docs/measurements/` the fix is a dated correction line plus ONE change of tense:
the window census reads any polarity near the flag's name as a present-tense claim, so a correction
placed beside the old "default off" decides as undecided and stays red. The old claim is restated as
its literal and when it was measured, which keeps the history and states no polarity. That is what
the 2026-10-01 flip did in three files. The red is the notification, not a verdict on the history.

THE CLAIM CENSUS IS DECIDED ON CONTENT, and its undecided bucket FAILS. A window that mentions the
flag and a polarity word my parser cannot assign a direction to is red, naming the text, because an
unparsed claim reads as an absent one. `test_the_POLARITY_PARSER_decides_all_three_ways` is that
parser's positive control -- without it, "every claim agrees" could be a parser that always agrees.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE_O = "agent_fleet/ontology_service/main.py"
FLAG = "ONTOLOGY_CLASS_POOL_VIA_MESH"

#: Lines either side of a flag mention that count as the same claim. The pilot report's header
#: wraps "default / off, and it stays off" across a line break and `main.py`'s mode-field comment
#: says "off-by-default" two lines below the mention, so a one-line window would miss both.
WINDOW = 3

#: This file necessarily contains both polarity words (they are its subject matter), so it is the
#: one file excluded from its own census -- derived from `__file__`, never typed, and the census
#: cannot be hollowed out by the exclusion because `test_the_CLAIM_POPULATION_is_not_empty`
#: requires claims in at least two files outside `tests/`.
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()

#: WHAT IS AND IS NOT A CLAIM ABOUT THE DEFAULT. `main.py:1287` reads "ONTOLOGY_CLASS_POOL_VIA_MESH
#: is on and this request carries no user_email ... or run with the flag off" -- a runtime
#: diagnostic raised INSIDE the on-branch, where "is on" is true by construction and "the flag off"
#: is an instruction to the operator. It states nothing about the default and must not be in the
#: population; a bare `is on|off` form put it there on this file's first run, decided both ways at
#: once, and was red. So every form below carries a DEFAULT-indicator: `default`, `defaults to`,
#: `by default`, `stays`, or the parenthetical `which is` that asserts the flag's settled state.
_OFF_FORMS = (
    r"\bdefault\W{0,4}off\b",
    r"\boff[-\s]by[-\s]default\b",
    r"\bdefaults?\s+to\s+\W{0,2}off\b",
    r"\bwhich is\s+\W{0,2}off\b",
    r"\bstays\s+\W{0,2}off\b",
)
_ON_FORMS = (
    r"\bdefault\W{0,4}on\b",
    r"\bon[-\s]by[-\s]default\b",
    r"\bdefaults?\s+to\s+\W{0,2}on\b",
    r"\bwhich is\s+\W{0,2}on\b",
    r"\bstays\s+\W{0,2}on\b",
)
#: A window holding a default-indicator AND a polarity word AND no decided form is UNDECIDED, which
#: is a red. It is how a reworded claim announces itself instead of dropping out of the population
#: silently -- and it is what caught the runtime message above.
_DEFAULT_HINT = r"\bdefaults?\b|\bby default\b|\bwhich is\b|\bstays\b"
_POLARITY_WORD = r"\b(?:on|off)\b"


def _decide(window: str) -> str:
    """`off`, `on`, `undecided`, or `not-a-claim` for one window of text."""
    low = window.lower()
    off = any(re.search(p, low) for p in _OFF_FORMS)
    on = any(re.search(p, low) for p in _ON_FORMS)
    if off and not on:
        return "off"
    if on and not off:
        return "on"
    if off and on:
        return "undecided"
    if re.search(_DEFAULT_HINT, low) and re.search(_POLARITY_WORD, low):
        return "undecided"
    return "not-a-claim"


def _tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.split("\0") if p and not p.endswith((".pyc", ".lock", ".png", ".svg"))]


def _claims() -> list[tuple[str, int, str, str]]:
    """Every (path, line, verdict, window) where the tree states a polarity for this flag."""
    found: list[tuple[str, int, str, str]] = []
    for rel in _tracked_text_files():
        if rel == SELF:
            continue
        try:
            lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines):
            if FLAG not in line:
                continue
            window = "\n".join(lines[max(0, i - WINDOW) : i + WINDOW + 1])
            verdict = _decide(window)
            if verdict != "not-a-claim":
                found.append((rel, i + 1, verdict, window))
    return found


def _flag_assignment() -> tuple[ast.Assign, str, str, tuple[str, ...]]:
    """The module-level assignment, destructured -- or an AssertionError naming the new shape.

    A refactor to some `_env_bool(...)` helper reds here rather than passing quietly, because a
    seal on a default that cannot see the default is worse than no seal.
    """
    src = (ROOT / ENGINE_O).read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == FLAG for t in n.targets)
    ]
    assert len(hits) == 1, f"expected exactly 1 module-level assignment to {FLAG}, found {len(hits)}"
    node = hits[0]
    shape = ast.unparse(node.value)
    cmp_ = node.value
    assert isinstance(cmp_, ast.Compare) and len(cmp_.ops) == 1 and isinstance(cmp_.ops[0], ast.In), (
        f"{FLAG}'s mechanism changed and this seal no longer reads it; re-derive it from: {shape}"
    )
    lower = cmp_.left
    assert (
        isinstance(lower, ast.Call)
        and isinstance(lower.func, ast.Attribute)
        and lower.func.attr == "lower"
    ), f"expected a `.lower()` call on the left of the membership test; got: {shape}"
    getenv = lower.func.value
    assert (
        isinstance(getenv, ast.Call)
        and isinstance(getenv.func, ast.Attribute)
        and getenv.func.attr == "getenv"
        and len(getenv.args) == 2
        and all(isinstance(a, ast.Constant) for a in getenv.args)
    ), f"expected `os.getenv(<key>, <default>)` with two literal arguments; got: {shape}"
    truthy = cmp_.comparators[0]
    assert isinstance(truthy, ast.Tuple) and all(
        isinstance(e, ast.Constant) for e in truthy.elts
    ), f"expected a literal tuple of truthy strings; got: {shape}"
    return node, getenv.args[0].value, getenv.args[1].value, tuple(e.value for e in truthy.elts)


def test_the_getenv_KEY_is_the_flag_name_so_the_flag_is_settable_at_all():
    """A key that does not match the variable makes the flag unsettable: a guard that cannot fire,
    inverted -- the deployment sets an env var nothing reads and the default rules forever."""
    _, key, _, _ = _flag_assignment()
    assert key == FLAG, f"the env var read is {key!r} but the flag is named {FLAG!r}"


def test_the_DEFAULT_is_read_from_the_ARTIFACT_and_it_is_on():
    """The default and the truthy set both come out of the AST. Neither is restated here: a seal
    that retypes the value it is sealing agrees with itself, not with the code."""
    _, _, default, truthy = _flag_assignment()
    assert default.lower() in tuple(t.lower() for t in truthy), (
        f"{FLAG}'s default literal is {default!r}, which the module's own truthy set {truthy!r} "
        f"reads as OFF. Every caller that does not set the variable is back on the incumbent arm, "
        f"which the 2026-10-01 census ruled against. If this flip back is intended, say which row "
        f"moved, and the prose homes named by "
        f"test_EVERY_CLAIM_about_the_default_agrees_with_the_artifact must move with it."
    )


def test_the_DEFAULT_RESOLVES_to_True_when_the_environment_is_silent(monkeypatch):
    """The literal being falsey is not the same claim as the expression evaluating to False: the
    `.lower() in (...)` parse is between them. This evaluates the artifact's own expression with
    the variable removed, so a truthy set that lost its `"true"` entry reds here."""
    monkeypatch.delenv(FLAG, raising=False)
    node, _, _, _ = _flag_assignment()
    expr = ast.Expression(body=node.value)
    ast.fix_missing_locations(expr)
    resolved = eval(compile(expr, f"<{ENGINE_O}:{node.lineno}>", "eval"), {"os": os})  # noqa: S307
    assert resolved is True, (
        f"with {FLAG} unset, the artifact's own expression resolves to {resolved!r}"
    )


def test_the_POLARITY_PARSER_decides_all_three_ways():
    """The control for the census below. A parser that never returns `on` would make "every claim
    agrees" vacuous forever, and one that never returns `undecided` would let a reworded claim drop
    out of the population silently."""
    assert _decide(f"`{FLAG}`, DEFAULT OFF. What this file asserts") == "off"
    assert _decide(f"forks on {FLAG}, which is OFF, so this line's behaviour") == "off"
    assert _decide(f"A field only the off-by-default arm populated ({FLAG})") == "off"
    assert _decide(f"`{FLAG}`, **default\noff, and it stays off** · **Seal:**") == "off"
    assert _decide(f"`{FLAG}` is now DEFAULT ON for every caller") == "on"
    assert _decide(f"{FLAG} defaults to on in the sandbox values file") == "on"
    assert _decide(f"    if {FLAG}:") == "not-a-claim"
    # The runtime diagnostic at main.py:1287, in shape: raised inside the on-branch, so "is on" is
    # true by construction and "the flag off" is an instruction. Not a claim about the default.
    assert (
        _decide(
            f'"{FLAG} is on and this request carries no user_email. The mesh read is attributed '
            f'to a person or it is not made. Thread identity to /resolve, or run with the flag off."'
        )
        == "not-a-claim"
    )
    assert _decide(f"the {FLAG} default was settled elsewhere") == "not-a-claim"
    assert _decide(f"{FLAG} defaults to off in prod and defaults to on in the sandbox") == "undecided"
    assert _decide(f"{FLAG}: which is off, and it stays on") == "undecided"
    assert _decide(f"{FLAG} -- the default here, off or on, was never written down") == "undecided"


#: MEASURED 2026-09-27: the files stating this flag's default, found by `_claims()` at five sites
#: in four files -- `main.py` twice, the two dated measurements, the parity seal's docstring. This
#: count is itself a claim with a date on it, so it moves when the census does. It is the ratchet a
#: consumer-derived population needs: the census is blind to its own subject DRAINING AWAY -- a
#: window narrowed to 0, the self-exclusion widened to all of `tests/`, a home reworded until it
#: states no polarity -- and each of those leaves the agreement arm green over a smaller set. A new
#: file making an agreeing claim is fine and does not red; a listed file going silent does.
CLAIM_FLOOR = frozenset(
    {
        ENGINE_O,
        "docs/measurements/route-migration-pilot-class-pool-2026-09-27.md",
        "docs/measurements/class-pool-flag-default-three-fire-2026-09-27.md",
        "docs/measurements/class-pool-flag-default-on-census-2026-10-01.md",
        "tests/test_the_migrated_route_returns_the_same_rows.py",
    }
)


def test_the_CLAIM_POPULATION_is_not_empty():
    """`_claims()` walking `git ls-files` is itself a population that can go quietly empty -- a
    window narrowed, a regex tightened, the flag renamed. Then the agreement arm passes having
    examined nothing."""
    claims = _claims()
    files = {rel for rel, _, _, _ in claims}
    assert len(claims) >= 5, f"only {len(claims)} claim(s) about {FLAG}'s default were found: {claims!r}"
    assert not (CLAIM_FLOOR - files), (
        f"these files stated {FLAG}'s default when this seal was written and no longer do, so the "
        f"agreement arm is now examining a smaller set than it was built for: "
        f"{sorted(CLAIM_FLOOR - files)}. Either the claim moved (re-measure CLAIM_FLOOR and say so) "
        f"or the census stopped reaching it (WINDOW, SELF, or the polarity forms)."
    )
    assert len(files - {f for f in files if f.startswith("tests/")}) >= 2, (
        f"claims about the default were found in {sorted(files)}; the census is supposed to reach "
        f"the engine source and the measurement record, not just the suite"
    )


def test_EVERY_CLAIM_about_the_default_agrees_with_the_artifact():
    """Every prose statement of this flag's default, decided on content against the AST. The
    undecided bucket fails: an unparsed claim reads as an absent one."""
    _, _, default, truthy = _flag_assignment()
    artifact = "on" if default.lower() in tuple(t.lower() for t in truthy) else "off"
    wrong = [(rel, ln, v) for rel, ln, v, _ in _claims() if v != artifact]
    assert not wrong, (
        f"the artifact's default is {artifact.upper()} (literal {default!r}), and these homes "
        f"disagree or cannot be parsed -- each one needs the correction, and for a dated file "
        f"under docs/measurements/ that means a dated correction line, not a rewrite: "
        + ", ".join(f"{rel}:{ln} says {v}" for rel, ln, v in wrong)
    )


@pytest.mark.parametrize("phrase", ["monkeypatch.setattr", FLAG])
def test_the_PARITY_SEAL_still_monkeypatches_the_flag_which_is_why_this_file_is_separate(phrase):
    """The premise of this whole file: the parity seal sets the flag explicitly, so it measures the
    two arms and never the default. If that ever stops being true, these two files overlap and this
    one's docstring is wrong about why it exists."""
    parity = (ROOT / "tests/test_the_migrated_route_returns_the_same_rows.py").read_text(
        encoding="utf-8"
    )
    assert f'monkeypatch.setattr(main, "{FLAG}"' in parity, (
        "the parity seal no longer sets the flag explicitly; re-read what each file now measures"
    )
    assert phrase in parity
