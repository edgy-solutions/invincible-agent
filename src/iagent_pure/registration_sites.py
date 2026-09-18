"""Who calls `register_engine_to_mesh`, and which verbs they declare — derived by AST.

ONE DERIVATION, TWO READERS, AND THAT IS THE POINT. `scripts/version_census.py` needs it to
attribute a live verb to a declaration; `tests/test_reregister_covers_every_registering_engine.py`
needs it to decide which engines must appear in the re-register list. Those are different
questions over **the same population**, and they had two implementations that disagreed.

**BOTH IMPLEMENTATIONS WERE BLIND, EACH IN ITS OWN WAY, AND THAT IS WHY THIS EXISTS.**

Measured 2026-09-17 while making the census report standing state:

    the census matched `"verb": "mesh:X"` and NOT the keyword form `verb="mesh:X"`
        -> 13 live verbs reported UNDECLARED, one of them (`mesh:analyzeDataset`) sitting in
           `agent_fleet/data_analyst/main.py:165`, A FILE THE CENSUS ALREADY WALKED
    both matched the helper's NAME and not its ALIAS
        -> the gateway does `from utils.mesh_registration import register_engine_to_mesh as
           _register_verb`, so every registration it makes was invisible to both
    the seal walked `agent_fleet/<one dir>/*.py` only
        -> `src/iagent/gateway.py` registers two verbs and is in neither the re-register list
           nor the waiver, because it was never in the population

> **A source-text pattern cannot see the form the source actually takes.** Three spellings, three
> blind spots, one law: an instrument that knows one spelling reports the others as absent, with
> total confidence and no error.

So this parses. An alias is resolved from the module's own imports, a call is matched by the names
`register_engine_to_mesh` is bound to in THAT module, and the verb is read from the `verb=` keyword
or from a `"verb":` dict entry — because engines genuinely use both.

**IT DELIBERATELY DOES NOT GUESS.** A call whose `verb=` is not a literal — built from a variable,
a loop, an f-string — is reported in `unresolved` rather than dropped. A registration this module
cannot read is a fact its callers need; silently omitting it is how a population becomes a sample.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

_HELPER = "register_engine_to_mesh"


@dataclass
class RegistrationSites:
    """What one tree declares, and what it could not read."""

    #: verb iri -> the file that registers it (first writer wins, matching census semantics)
    verbs: "dict[str, str]" = field(default_factory=dict)
    #: files that call the helper at all, whatever the call says
    registering_files: "set[str]" = field(default_factory=set)
    #: `file: reason` for a call this module could not resolve to a literal verb
    unresolved: "dict[str, str]" = field(default_factory=dict)


def _local_names(tree: ast.AST) -> "set[str]":
    """Every local name `register_engine_to_mesh` is bound to in this module.

    THE ALIAS IS NOT COSMETIC: the gateway registers under `_register_verb`, so a matcher keyed
    on the bare name walks that file and sees nothing at all.
    """
    names = {_HELPER}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == _HELPER and a.asname:
                    names.add(a.asname)
        elif isinstance(node, ast.Assign):
            # `_register = register_engine_to_mesh` — rebinding without an import alias.
            v = node.value
            if isinstance(v, ast.Name) and v.id in names:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
    return names


def scan(paths: "list[Path]", *, root: "Path | None" = None) -> RegistrationSites:
    """Read every registration call in `paths`.

    `root` only shortens the recorded file names; it changes nothing about what is found.
    """
    out = RegistrationSites()
    for path in paths:
        if "__pycache__" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _HELPER not in text:
            # Cheap reject BEFORE parsing. Safe because an alias must still name the helper in
            # its import statement to exist at all — the alias hides the CALL, never the import.
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        where = str(path.relative_to(root)).replace("\\", "/") if root else str(path)
        names = _local_names(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if fn not in names:
                continue
            out.registering_files.add(where)

            verb = None
            for kw in node.keywords:
                if kw.arg == "verb" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    verb = kw.value.value
                elif kw.arg is None and isinstance(kw.value, ast.Dict):
                    # `**payload` where payload is a literal dict carrying "verb".
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if isinstance(k, ast.Constant) and k.value == "verb" \
                                and isinstance(v, ast.Constant) and isinstance(v.value, str):
                            verb = v.value
            if verb:
                out.verbs.setdefault(verb, where)
            else:
                # NAMED, NOT DROPPED. A call whose verb is computed is a registration this
                # module cannot attribute, and its caller needs to know that rather than
                # receive a quietly shorter list.
                out.unresolved.setdefault(where, "verb= is not a string literal")
    return out


def python_files(*roots: Path) -> "list[Path]":
    """Every `.py` under the given roots, recursively, `__pycache__` excluded.

    RECURSIVE ON PURPOSE. The seal's old walk was `agent_fleet/<dir>/*.py` — one level — and
    `src/iagent/gateway.py` registers two verbs from outside `agent_fleet` entirely.
    """
    files: "list[Path]" = []
    for r in roots:
        if r.is_dir():
            files.extend(p for p in sorted(r.rglob("*.py")) if "__pycache__" not in str(p))
    return files
