"""No hot-path module reads a global name the module does not define.

WHAT THIS EXISTS FOR, and it is the worst failure of 2026-09-14. A one-word slip inside the
gateway's SSE generator:

    for k, v in dict(bound_slots or {}).items()          # the name in that scope is
    for k, v in dict(request.bound_slots or {}).items()  # `request.bound_slots`

`bound_slots` is a parameter of `dispatch_pre_resolved`, and the enclosing coroutine here is
`generate_dagster_stream`, where the pick lives on `request`. So the name resolved to nothing, and
at the moment a user picked from a menu the generator raised `NameError` **inside an SSE stream**.

**THE STREAM ENDED. NOTHING ELSE HAPPENED.** No route decision, no materializations, no artifact —
not `failed`, not `complete`, nothing. The rail showed no new row at all. The failure-recording
arc built that same evening could not see it, because there was no record TO write a cause onto:

> **A dispatch that can exit without writing is the one shape the whole failure-recording arc
> cannot see.** You cannot record an absence.

**AND EVERY TEST WAS GREEN.** 591 routing tests passed on the commit that shipped it. The seals in
that suite match SOURCE STRINGS, and `dict(bound_slots or {})` is a perfectly good string; nothing
executes `generate_dagster_stream`, which needs a live request, an authenticated user and a
reachable Dagster. A check that reads code cannot resolve a name, and the one thing that resolves
names is running it.

**WHY `symtable` AND NOT AN AST WALK.** The first attempt collected `ast.Name` loads and compared
against module globals — and produced twelve hits, of which ten were nested functions closing over
an ENCLOSING FUNCTION'S locals. `symtable` classifies those as FREE rather than GLOBAL, which is
exactly the distinction the naive walk lacks. An instrument with a 10-in-12 false-positive rate
gets muted, and a muted check is a deleted one.

Run: uv run --frozen pytest tests/test_no_undefined_global_names.py -v
"""
from __future__ import annotations

import builtins
import importlib
import symtable
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

#: The modules a user's turn actually travels through. Not the whole tree: this check's value is
#: that it is TRUSTED, and a sweep over everything would surface conditional-import noise until
#: somebody stopped reading it. Extend deliberately.
_MODULES: dict[str, str] = {
    "iagent.gateway": "src/iagent/gateway.py",
    "iagent.direct_dispatch": "src/iagent/direct_dispatch.py",
    "iagent.defs.dynamic_supervisor": "src/iagent/defs/dynamic_supervisor.py",
    "iagent_pure.slot_acceptance": "src/iagent_pure/slot_acceptance.py",
    "iagent_pure.verb_eligibility": "src/iagent_pure/verb_eligibility.py",
}

#: Names that ARE global-and-undefined at module scope and legitimately so, each with its reason.
#: An exclusion list with reasons is auditable; one without is the list nobody can read.
_ALLOWED: dict[str, str] = {
    "compile_workflow": (
        "imported inside a branch in generate_dagster_stream, so it is never bound at module "
        "scope; the import is guarded by the same condition as its use"
    ),
    "pysqlite3": "conditional import behind a try/except for environments that ship it",
}


def _undefined_globals(mod_name: str, rel: str) -> list[str]:
    """Names a function READS as a global that the imported module does not define.

    `symtable` is the authority rather than an AST walk: a variable captured from an enclosing
    function is FREE, not GLOBAL, and conflating the two makes this check unusable.
    """
    mod = importlib.import_module(mod_name)
    known = set(dir(mod)) | set(dir(builtins))
    src = (_REPO / rel).read_text(encoding="utf-8")
    found: list[str] = []

    def walk(table, path: str) -> None:
        for sym in table.get_symbols():
            name = sym.get_name()
            if sym.is_global() and not sym.is_assigned() and name not in known:
                if name not in _ALLOWED:
                    found.append(f"{path}: {name}")
        for child in table.get_children():
            walk(child, f"{path}/{child.get_name()}")

    top = symtable.symtable(src, rel, "exec")
    walk(top, top.get_name())
    return sorted(set(found))


def test_THE_MODULE_LIST_IS_PLURAL():
    """A floor. An empty or shrunken list makes every assertion below vacuous, which is how a
    check like this goes quiet without anybody noticing it stopped covering the hot path."""
    assert len(_MODULES) >= 4
    for rel in _MODULES.values():
        assert (_REPO / rel).is_file(), f"{rel} moved; this seal no longer covers it"


def test_THE_DETECTOR_FINDS_A_PLANTED_UNDEFINED_NAME(tmp_path):
    """POSITIVE CONTROL, and it is the reason the result below means anything.

    It also proves the closure case is NOT flagged — the false positive that made the first
    attempt unusable. A detector that cannot tell a free variable from an undefined one reports
    ten wrong answers for every right one, and then gets muted.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "def outer():\n"
        "    captured = 1\n"
        "    def inner():\n"
        "        return captured      # FREE, must not be flagged\n"
        "    return inner\n"
        "def broken():\n"
        "    return not_a_name_anywhere   # GLOBAL and undefined, must be flagged\n",
        encoding="utf-8",
    )
    hits: list[str] = []

    def walk(t, path):
        for s in t.get_symbols():
            if s.is_global() and not s.is_assigned() and s.get_name() not in dir(builtins):
                hits.append(s.get_name())
        for c in t.get_children():
            walk(c, path)

    top = symtable.symtable(probe.read_text(encoding="utf-8"), "probe.py", "exec")
    walk(top, "top")
    assert "not_a_name_anywhere" in hits, "the detector cannot see a planted undefined global"
    assert "captured" not in hits, (
        "a closure variable was flagged as undefined — the detector conflates FREE with GLOBAL "
        "and would bury a real hit under false ones"
    )


@pytest.mark.parametrize("mod,rel", sorted(_MODULES.items()))
def test_NO_UNDEFINED_GLOBAL_NAMES(mod: str, rel: str):
    """THE SEAL. A name that resolves to nothing raises only when the line runs — and inside an
    SSE generator that means the stream ends and no artifact is ever written."""
    undefined = _undefined_globals(mod, rel)
    assert not undefined, (
        f"{rel} reads {len(undefined)} global name(s) the module does not define:\n  "
        + "\n  ".join(undefined)
        + "\n\nEach raises NameError when its line executes. In a request path that means a "
          "silent stream end with NO artifact — not failed, not complete — which no failure "
          "recording can capture. Fix the name, or add it to _ALLOWED with its reason."
    )


def test_EVERY_ALLOWANCE_NAMES_A_REASON():
    """An allowance with an empty reason is a silenced failure wearing a decision's clothes."""
    for name, why in _ALLOWED.items():
        assert why and why.strip(), f"{name} is allowed with no reason"
