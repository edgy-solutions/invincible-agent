"""The Predicate writer must DECLARE and WRITE the same named vector space — or neither.

THE DEFECT THIS EXISTS AGAINST, measured by 74 on the live fleet 2026-09-19. A bare
`collections.create` emits a named vector space `default` in the schema while
`insert(vector=[...])` writes to the LEGACY unnamed slot. Both calls succeed. The row then
reports a vector to every instrument that ASKS — `_additional{vector}`, `include_vector`, a
per-URI fetch, a row count — while the space the index is built on holds nothing, so every
targeted search returns zero. The server says so only when asked to USE a vector:

    "explorer: get class: vectorize search vector: nearObject params:
     vector not found for target: default"

It took the entire router down with no log line and no failing seal. `weaviate_hybrid_search`
returned its BM25 half alone, fleet-wide, on both routing collections.

── WHY THIS IS ONE ASSERTION AND NOT TWO ───────────────────────────────────────────────────────
Either edit ALONE IS WORSE THAN NEITHER:

  * declare the space and keep writing a bare list  -> reproduces the original defect exactly
  * write by name into an undeclared space          -> refused by the server

So the two lines are one change, and the thing that must never happen is a tidy-up that
"simplifies" one of them. A test asserting each half separately would pass while they disagree
about the NAME — which is the failure a rename introduces and the one a literal-matching check
cannot see.

**THE NAME IS DERIVED FROM BOTH SITES AND COMPARED**, rather than matched against "default" in
this file. A third copy of the string here would be a third place to forget: the seal would go
green on `default`/`default` while the code had moved to `vec`/`default`. Comparing what the
code actually says is the only form that survives a rename.

Cf. [[every-endpoint-verified-the-join-unasserted]] — both ends correct, the relation between
them asserted nowhere, is the shape that produced this.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

#: (path, human name). Both writers of the Predicate collection. Derived as a pair because
#: `_ensure_predicate_collection`'s own docstring says WHICHEVER writer creates the collection
#: first sets the index — so they must agree, and a fix to one is not a fix.
_WRITERS = [
    (_REPO / "agent_fleet" / "mesh_registrar" / "v2_substrate.py", "registrar"),
    (_REPO / "scripts" / "seed_sandbox_predicates.py", "sandbox seed"),
]


def _declared_space(source: str) -> str | None:
    """The name passed to `Configure.Vectors.self_provided(name=...)`, read from the AST."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "self_provided"):
            continue
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
        if node.args and isinstance(node.args[0], ast.Constant):
            return str(node.args[0].value)
    return None


@pytest.mark.parametrize("path,who", _WRITERS, ids=[w for _, w in _WRITERS])
def test_the_create_site_DECLARES_a_named_vector_space(path: Path, who: str):
    """Half one. A bare create emits `default` implicitly and nothing writes into it."""
    assert path.is_file(), f"{who}: {path} is missing — this seal is pointed at nothing"
    name = _declared_space(path.read_text(encoding="utf-8"))
    assert name, (
        f"{who} ({path.relative_to(_REPO).as_posix()}) creates the Predicate collection with no "
        f"`Configure.Vectors.self_provided(name=...)`. A bare create still emits a named space, "
        f"and writes go to the legacy slot — the rows read as vectorised and retrieve nothing."
    )


def test_THE_TWO_WRITERS_DECLARE_THE_SAME_SPACE():
    """They create ONE collection. Whichever gets there first sets the schema for both."""
    declared = {who: _declared_space(p.read_text(encoding="utf-8")) for p, who in _WRITERS}
    assert len(set(declared.values())) == 1, (
        f"the two Predicate writers declare DIFFERENT vector spaces: {declared}. They create the "
        f"same collection and whichever runs first wins, so the schema would depend on boot order."
    )


def test_THE_REGISTRAR_WRITES_INTO_THE_SPACE_IT_DECLARES():
    """THE JOIN, and the reason this file exists rather than two separate checks.

    Derived from both sites and compared. A rename in one place reds here; a literal match
    against "default" in this file would not.
    """
    path = _REPO / "agent_fleet" / "mesh_registrar" / "v2_substrate.py"
    source = path.read_text(encoding="utf-8")
    declared = _declared_space(source)
    assert declared, "the registrar declares no named space — see the sibling test"

    # The write half: `write_kwargs["vector"] = {"<name>": predicate_vector}`
    m = re.search(
        r'write_kwargs\[\s*["\']vector["\']\s*\]\s*=\s*\{\s*["\']([^"\']+)["\']\s*:',
        source,
    )
    assert m, (
        "the registrar assigns `write_kwargs['vector']` a BARE VALUE, not a {name: vector} map. "
        "That writes the legacy unnamed slot, which is the original defect with the declaration "
        "now making it look fixed."
    )
    written = m.group(1)
    assert written == declared, (
        f"the registrar DECLARES vector space {declared!r} and WRITES into {written!r}. Both "
        f"halves are individually well-formed and they do not meet: the declared space stays "
        f"empty and every targeted search returns nothing, while the rows still read back as "
        f"carrying a vector."
    )


def test_THE_SEED_SCRIPTS_MISSING_VECTOR_IS_RECORDED_NOT_FORGOTTEN():
    """The seed script writes NO vector at all, and that is a DIFFERENT gap from the registrar's.

    Its rows read back as `{'default': []}` and are equally unretrievable — but 74's in-place
    backfill cannot repair them, because there is nothing to relocate. They need a RE-EMBED.

    This asserts the gap is still WRITTEN DOWN where the writer is. A silent gap becomes a
    mystery the next time someone measures retrievability and finds four rows that no backfill
    will fix; the note is what turns that into a known cost.
    """
    path = _REPO / "scripts" / "seed_sandbox_predicates.py"
    source = path.read_text(encoding="utf-8")
    assert "RE-EMBED" in source.upper(), (
        "the seed script's 'writes no vector, needs a re-embed' note is gone. If the write half "
        "was FIXED, delete this test in the same change — a note outliving its gap is a monument "
        "nobody can tell from a live one. If it was merely tidied away, put it back."
    )
