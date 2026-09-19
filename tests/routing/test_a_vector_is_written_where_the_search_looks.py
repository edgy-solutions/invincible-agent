"""A vector must land in the space the search TARGETS, and only one operation can tell.

THE DEFECT THIS SEALS, measured live 2026-09-19. A bare `collections.create(name, properties)`
on weaviate-client 4.21.0 emits a NAMED vector space `default`; a positional
`insert(vector=[...])` writes the LEGACY unnamed slot. The named space — the only target a search
can name — stays empty, and the store answers:

    nearObject(self) -> "vectorize search vector: vector not found for target: default"

on a row whose vector reads back as `{'default': '768 dims'}`. `OntologyClass` and `Predicate`
were both in that state, so every routing decision in the fleet was silently BM25-only.

## WHY THIS FILE MAY NEVER ASSERT PRESENCE

`obj.vector["default"]` IS TRUE ON A BROKEN ROW. The client maps the legacy slot onto the name
`default` when reading it back, so a presence check reads a 768-dim vector under the exact name
the search fails on. 24,924 of 26,239 live rows "had a vector" and not one could be found by one.

**So every arm here ends at the CONSUMING operation.** An object is its own nearest neighbour or
the space it was written to is not the space that is indexed. There is no cheaper check that
works, and the cheap ones all pass.

## WHAT IS SEALED WHERE

The live-substrate half is `tests/sandbox_e2e/_probe_retrieval_seam.py` and the census
retrievability line — they need a cluster and cannot go red in CI. **This file seals the
DECLARATION half, which can be wrong while the substrate is perfectly healthy**: that both
writers name the same space, that neither passes a bare list, and that the replace path carries
the same shape as insert.

Run: uv run --frozen pytest tests/routing/test_a_vector_is_written_where_the_search_looks.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agent_fleet.utils.weaviate_utils import VECTOR_SPACE, named_vector, named_vector_config

_REPO = Path(__file__).resolve().parents[2]
_REGISTRAR = _REPO / "agent_fleet" / "mesh_registrar" / "v2_substrate.py"
_SEED = _REPO / "scripts" / "seed_sandbox_predicates.py"

#: Every writer of a Predicate vector. DERIVED-ADJACENT AND DELIBERATELY SHORT: these are the two
#: creators the architect named, and `test_no_other_writer_has_appeared` below refuses to let the
#: pair go stale silently — a hand-written list of a population is a sample until something
#: enumerates it.
_PREDICATE_WRITERS = (_REGISTRAR, _SEED)


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------

def test_the_space_is_named_once():
    """One declaration. Two spellings of the name is the same defect one layer up — the day
    they diverge, two writers disagree about where the vectors live and nothing says so."""
    assert VECTOR_SPACE == "default", (
        "the live collections index a space called 'default'; changing this constant without "
        "migrating every existing row makes the new rows unfindable instead of the old ones"
    )


def test_named_vector_addresses_the_space():
    assert named_vector([1.0, 2.0]) == {VECTOR_SPACE: [1.0, 2.0]}


def test_named_vector_passes_None_through_rather_than_wrapping_it():
    """WRITING NO VECTOR IS A LEGITIMATE STATE and must stay distinguishable from writing one.

    The registrar deliberately writes a row without a vector when the embed gateway is down, so
    a registration is not blocked on the LLM stack. `{"default": None}` would be a third thing:
    a claim to have written a vector, with nothing in it. It also matters for the repair — a
    vectorless row needs a RE-EMBED, not a relocation, and is the one case a backfill cannot fix.
    """
    assert named_vector(None) is None


def test_the_config_helper_returns_kwargs_not_a_value():
    """The two client forms use DIFFERENT PARAMETER NAMES (`vector_config` vs
    `vectorizer_config`). A helper returning only the value pushes that difference back onto
    every call site, which is where one of them gets it wrong."""
    cfg = named_vector_config()
    assert isinstance(cfg, dict) and len(cfg) == 1
    assert set(cfg) <= {"vector_config", "vectorizer_config"}, cfg


def test_the_fallback_form_is_reachable_on_the_pinned_range():
    """THE FALLBACK IS REAL CODE, NOT DECORATION, and this says why in a way that survives.

    `pyproject.toml` pins `weaviate-client>=4.5.4,<5.0` — a RANGE — and `Configure.Vectors` is a
    later 4.x addition. A deployment at the floor of that range takes the `NamedVectors` branch,
    so it must exist for whichever client is actually installed here.
    """
    import weaviate.classes as wvc

    has_new = hasattr(getattr(wvc.config.Configure, "Vectors", None), "self_provided")
    has_old = hasattr(getattr(wvc.config.Configure, "NamedVectors", None), "none")
    assert has_new or has_old, (
        "neither named-vector form exists on the installed client — `named_vector_config` "
        "cannot declare a space, and a bare create would silently reintroduce the defect"
    )
    pin = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "weaviate-client>=4.5.4" in pin, (
        "the pin moved; re-check which create-form the FLOOR of the new range supports"
    )


# ---------------------------------------------------------------------------
# Both writers, both operations
# ---------------------------------------------------------------------------

def _vector_sources(tree: ast.AST) -> list[str]:
    """Every expression this module writes as a vector, as source text.

    PARSED, NOT GREPPED, AND IT TOOK TWO GOES TO BE RIGHT — which is the reason for
    `test_the_extractors_find_what_they_are_looking_for` below.

    The first version looked only for a `vector=` KEYWORD ARGUMENT and returned `[]` for both
    writers, because neither passes one: both build a dict and splat it
    (`write_kwargs["vector"] = ...` then `insert(**write_kwargs)`). **A matcher that returns
    zero reads exactly like a finding** — it reported two correctly-fixed files as writing no
    vector at all. Both forms are handled now, and the control proves the matcher can see them.
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "vector":
                    out.append(ast.unparse(kw.value))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "vector"):
                    out.append(ast.unparse(node.value))
    return out


def _creates_collections(tree: ast.AST) -> int:
    """Count of `<...>.collections.create(...)` CALLS — the code form, not the phrase.

    A text search for `collections.create(` matches every comment ABOUT the mechanism, and this
    change adds several. The first version of the repo sweep below reported three files as new
    creators when all three merely discuss it, including this seal itself.
    """
    n = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "collections"):
            n += 1
    return n


def _called_names(tree: ast.AST) -> set[str]:
    """Every function actually CALLED, by name. `embed_query` in a comment saying 'not
    embed_query' is not a call, and the first version of that assertion failed on its own
    explanation of why it exists."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
    return names


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_the_extractors_find_what_they_are_looking_for():
    """POSITIVE CONTROL ON THIS FILE'S OWN INSTRUMENTS, and it is not ceremony.

    Every assertion below is of the form "the source does NOT contain X" or "the source contains
    only good X". An extractor that silently matches nothing makes all of them pass — or, as
    happened here, fail for a reason that has nothing to do with the code under test. So the
    extractors are exercised on a fixture whose answers are known.
    """
    fixture = ast.parse(
        "col = c.collections.create(name='X')\n"
        "col.data.insert(properties=p, vector=named_vector(v))\n"
        "w = {}\n"
        "w['vector'] = named_vector(v2)\n"
        "col.data.replace(**w)\n"
        "z = embed_document('t')\n"
        "# vector= in a comment, collections.create( in a comment, embed_query in a comment\n"
    )
    # SORTED: `ast.walk` is breadth-first, so the subscript assignment surfaces before the
    # nested call. Order is not a property this seal cares about, and asserting it would make
    # the control fail for a reason that says nothing about the code under test.
    assert sorted(_vector_sources(fixture)) == ["named_vector(v)", "named_vector(v2)"], (
        "the vector extractor misses one of the two forms the writers actually use"
    )
    assert _creates_collections(fixture) == 1, "the create counter miscounts"
    assert "embed_document" in _called_names(fixture)
    assert "embed_query" not in _called_names(fixture), (
        "the call extractor is matching comment text, which is how the first version of "
        "test_the_seed_actually_embeds_now failed on its own docstring"
    )


@pytest.mark.parametrize("path", _PREDICATE_WRITERS, ids=lambda p: p.name)
def test_no_writer_passes_a_bare_vector(path: Path):
    """THE DEFECT ITSELF: a positional list lands in the legacy slot, which nothing searches.

    Every `vector=` must go through `named_vector(...)`. A literal dict would also work and is
    refused anyway — the point of the helper is that the space is spelled ONCE.
    """
    exprs = _vector_sources(_tree(path))
    assert exprs, f"{path.name} writes no vector at all — see the seed's own second defect"
    for expr in exprs:
        assert expr.startswith("named_vector("), (
            f"{path.name} passes vector={expr} — a bare value lands in the LEGACY slot and the "
            f"row becomes unfindable by vector while still reading back as vectorised"
        )


@pytest.mark.parametrize("path", _PREDICATE_WRITERS, ids=lambda p: p.name)
def test_every_creator_declares_the_space(path: Path):
    """The WRITE half alone is not the fix. A bare create leaves the space implicit, so a future
    client default can move it out from under a correctly-addressed write."""
    tree = _tree(path)
    creates = _creates_collections(tree)
    assert creates, f"{path.name} creates no collection — has this seal's target moved?"
    declared = _called_names(tree).intersection({"named_vector_config", "_named_vector_config"})
    assert declared, (
        f"{path.name} has {creates} collections.create( call(s) and never calls "
        f"named_vector_config() — a create without it emits an IMPLICIT space, and a future "
        f"client default can then move it out from under a correctly-addressed write"
    )


def test_the_replace_path_is_covered_and_not_just_insert():
    """ITS OWN ARM, BECAUSE IT IS THE ONE THAT WOULD HAVE BEEN MISSED.

    `insert` runs once on a cold store; `replace` runs on EVERY re-registration. A fix applied
    only to insert works until the first roll and then stops — and the symptom would return
    looking like a regression in something else entirely. Measured as its own scratch arm
    (ArmE/ArmF) rather than assumed to follow from insert.
    """
    src = _REGISTRAR.read_text(encoding="utf-8")
    assert "data.replace(**write_kwargs)" in src and "data.insert(**write_kwargs)" in src, (
        "the registrar no longer shares one `write_kwargs` between replace and insert — if they "
        "have been split, BOTH need the named vector and this seal must check both"
    )
    # One dict, built once, used by both — so the vector shape cannot differ between them.
    assert len(_vector_sources(_tree(_REGISTRAR))) == 1, (
        "more than one vector write in the registrar: the single-write_kwargs invariant this "
        "seal relies on has gone, and each site now needs its own assertion"
    )

    seed = _SEED.read_text(encoding="utf-8")
    assert "collection.data.replace(**write)" in seed and "collection.data.insert(**write)" in seed, (
        "the seed no longer shares one `write` mapping between replace and insert"
    )


def test_the_seed_actually_embeds_now():
    """The seed's SECOND defect, which was only ever latent: it dropped the collection and wrote
    rows with no vector, and registration always happened to rewrite them (135/135 vectored when
    measured). A defect covered for by a neighbour is still a defect."""
    called = _called_names(_tree(_SEED))
    assert "embed_document" in called, "the seed writes rows with no vector again"
    assert "embed_query" not in called, (
        "the seed CALLS embed_query — a Predicate row is CORPUS and the read path embeds the "
        "QUERY. The asymmetric task prefixes are the contract; the wrong helper silently splits "
        "the embedding space and fails exactly like the defect this file seals"
    )


def test_the_seed_imports_the_space_rather_than_respelling_it():
    """Two writers of one collection must not each carry their own copy of the name."""
    src = _SEED.read_text(encoding="utf-8")
    assert "from agent_fleet.utils.weaviate_utils import" in src
    assert not re.search(r'name\s*=\s*["\']default["\']', src), (
        "the seed spells the space name locally — that is a second declaration of one thing"
    )


def test_no_other_writer_has_appeared():
    """A HAND-WRITTEN PAIR IS A SAMPLE UNTIL SOMETHING ENUMERATES IT.

    Sweeps the repo for any other `collections.create(` and requires it to be a known one. A
    third creator added tomorrow fails here rather than silently reintroducing the defect in a
    file this seal never heard of.
    """
    known = {
        "agent_fleet/mesh_registrar/v2_substrate.py",   # Predicate — sealed above
        "scripts/seed_sandbox_predicates.py",           # Predicate — sealed above
        "scripts/seed_weaviate_manuals.py",             # manuals; not a routing collection
    }
    found = set()
    for path in _REPO.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "node_modules"} for part in path.parts):
            continue
        try:
            # THE CODE FORM, NOT THE PHRASE. A text match on `collections.create(` reported
            # three files on the first run — `weaviate_utils.py`, the retrieval probe, and THIS
            # SEAL — every one of them merely discussing the mechanism in a comment. Searching
            # for a mechanism by name finds the prose about it.
            if _creates_collections(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
                found.add(path.relative_to(_REPO).as_posix())
        except (OSError, SyntaxError):
            continue
    stray = sorted(found - known)
    assert not stray, (
        f"new collection creator(s) this seal does not cover: {stray}. If any of them stores "
        f"vectors, it needs named_vector_config() at the create and named_vector() at the "
        f"write, or its rows will read back as vectorised and be unfindable by vector."
    )
