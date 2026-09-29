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

#: Weaviate's mutation surface. `.data.<anything>` is already a mutation, so the ATTRIBUTE CHAIN is
#: the load-bearing half of the discriminator and this set is the belt: it catches a write op reached
#: without the `data` accessor spelled at the call site. A write op added to the client lands in the
#: `.data` clause automatically, which is why the future-proofing lives there and not in this list.
_STORE_WRITE_OPS = frozenset({"insert", "insert_many", "replace", "update"})


def _vector_sources(tree: ast.AST) -> list[str]:
    """Every expression this module hands to the STORE as a vector, as source text.

    PARSED, NOT GREPPED, AND IT TOOK TWO GOES TO BE RIGHT — which is the reason for
    `test_the_extractors_find_what_they_are_looking_for` below.

    The first version looked only for a `vector=` KEYWORD ARGUMENT and returned `[]` for both
    writers, because neither passes one: both build a dict and splat it
    (`write_kwargs["vector"] = ...` then `insert(**write_kwargs)`). **A matcher that returns
    zero reads exactly like a finding** — it reported two correctly-fixed files as writing no
    vector at all. Both forms are handled now, and the control proves the matcher can see them.

    ⛔ NARROWED 2026-09-28, AND THE REASON IS NOT THE FILE THAT CAUGHT IT. Until now this collected
    every `vector=` keyword on every call, and the tree-wide arm then required each to be
    `named_vector(...)`. That rule is about a vector handed to WEAVIATE. Three things in this tree
    pass `vector=` to something else:

      * `mesh_vectors.py:314` — `query.hybrid(query=text, vector=vector, ...)`, a SEARCH. It escapes
        today only because that file is not classified as a self-provided creator, so the false red
        was LATENT: it fires the day that file gains a create, and it would have accused a read path.
      * `MeshVectorsWriter.relocate(..., vector=[...])` — the SDK protocol's own parameter name, so
        every legitimate caller of the mesh writers spells it. As shipped, the widened arm reddened
        on any adoption of the very writers it was widened for.
      * a test driving the writer's public API, which is how it was found.

    THE DISCRIMINATOR IS THE CALLEE, NOT A LIST OF FORGIVEN FILES. `.data.<op>` or one of
    `_STORE_WRITE_OPS` is a store write; `.query.<op>` is a read; anything else is a hand-off. **The
    residue is COLLECT, not skip**: a bare-name callee (`_store(vector=...)`) cannot be resolved
    statically and is therefore collected, so a new indirection fails rather than passes. That is
    also why this writer names its internal parameter `embedding` and not `vector`.

    **Skipping a hand-off is safe for one specific reason, and it is not "the callee looks fine".**
    The sweep that consumes this is TREE-WIDE, so the file the vector is handed TO is swept by the
    same rule. The property that makes the skip sound is the population, not the judgment — and if
    the sweep is ever narrowed back to a path list, this must be narrowed with it.
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not any(kw.arg == "vector" for kw in node.keywords):
                continue
            if not _is_store_write(node.func):
                continue
            for kw in node.keywords:
                if kw.arg == "vector":
                    out.append(ast.unparse(kw.value))
        elif isinstance(node, ast.Assign):
            # NO CALLEE TO JUDGE, SO NO NARROWING. This is production's real shape — the dict is
            # built here and splatted into `.data.insert` possibly lines away — and a slot called
            # "vector" in a kwargs dict has no other purpose. Collected unconditionally.
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "vector"):
                    out.append(ast.unparse(node.value))
    return out


def _is_store_write(func: ast.expr) -> bool:
    """Does this callee write to weaviate? UNRESOLVABLE COUNTS AS YES.

    Returning True for what it cannot classify is the whole design: the alternative residue admits
    exactly the indirections nobody has looked at, which is the state every instance of the
    vector-slot defect was found in.
    """
    if isinstance(func, ast.Name):
        return True  # bare call, unresolvable — fail closed
    if not isinstance(func, ast.Attribute):
        return True  # a call on a subscript or a call — also unresolvable
    chain: list[str] = []
    node: ast.expr = func
    while isinstance(node, ast.Attribute):
        chain.append(node.attr)
        node = node.value
    if "data" in chain:
        return True
    # NO `query`/`aggregate` CLAUSE HERE, AND IT WAS WRITTEN AND THEN MEASURED AWAY. The first draft
    # had `if "query" in chain or "aggregate" in chain: return False` to exempt reads. Mutating it to
    # `if False:` changed nothing — 15 passed — because a read callee reaches the line below with
    # `hybrid`/`bm25`/`near_vector` as its final attribute, none of which is a write op, so it is
    # already excluded. The clause could only have fired for a callee whose chain says `query` AND
    # whose final attribute is `insert`/`replace`/`update`, which the client does not have. It was a
    # guard that could not fire, and a line that cannot fire is deleted with its measurement recorded
    # rather than kept as reassurance: reads are excluded by the rule below, not by an exemption.
    return func.attr in _STORE_WRITE_OPS


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


#: The two spellings of the config helper — the second is the seed's local wrapper.
_CONFIG_HELPERS = {"named_vector_config", "_named_vector_config"}

#: A SERVER-SIDE vectorizer, named by its own prefix. THIS IS THE DISCRIMINATING FIELD, and the
#: obvious alternative is not: `vectorizer_config=` is a keyword that BOTH arrangements produce —
#: `named_vector_config()`'s fallback form returns exactly that key holding `NamedVectors.none`. So
#: keying on the keyword's presence would call every self-provided writer a delegated one. What
#: separates them is which vectorizer is named: a real module (`text2vec_ollama`) embeds server-side;
#: `none`/`self_provided` declares that the caller supplies the vector.
_SERVER_VECTORIZER = re.compile(r"^(?:text2vec|multi2vec|img2vec|ref2vec)_")


def _create_calls(tree: ast.AST) -> list[ast.Call]:
    """The `<...>.collections.create(...)` calls themselves, not just how many."""
    return [node for node in ast.walk(tree)
            if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "create"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "collections")]


def _creates_declaring_nothing(tree: ast.AST) -> list[str]:
    """Create calls that say NOTHING about vectorization, by the collection name they pass.

    PER CALL, not per file, and that is the point. A file already carrying one correct create can
    gain a second bare one and stay green under any file-level check — which is not hypothetical:
    the writer this seal was extended for creates two collections, a vector collection and its
    metadata carrier, and only the first is what anyone would think to look at.
    """
    bare: list[str] = []
    for node in _create_calls(tree):
        declared = False
        for kw in node.keywords:
            if kw.arg is None:  # a `**splat` — the helper's form
                value = kw.value
                if isinstance(value, ast.Call):
                    name = getattr(value.func, "id", getattr(value.func, "attr", ""))
                    if name in _CONFIG_HELPERS:
                        declared = True
            elif kw.arg in {"vector_config", "vectorizer_config"}:
                declared = True
        if not declared:
            bare.append(next((ast.unparse(k.value) for k in node.keywords if k.arg == "name"), "?"))
    return bare


def _server_vectorizers(tree: ast.AST) -> list[str]:
    """Every server-side vectorizer this module configures, by name."""
    return sorted({name for name in _called_names(tree) if _SERVER_VECTORIZER.match(name)})


def _vector_arrangement(tree: ast.AST) -> str:
    """Which of the two LEGAL arrangements this module uses — or that it is undecided.

    `self-provided`  the caller embeds and passes the vector; needs the named space declared
                     at every create and `named_vector()` at every write.
    `delegated`      the store embeds; the caller passes no vector, and declaring a
                     self-provided space here would DISABLE the vectorizer it depends on.
    `undecided`      neither shape is evident. **This must fail.** An unclassifiable creator is
                     the state every instance of this defect was in before it was found, and an
                     admission rule whose residue is "allow" admits exactly them.
    """
    called = _called_names(tree)
    # PASSING A VECTOR AT ALL is what makes a module self-providing — not calling the helper. Keying
    # this on `named_vector` alone classified the defect's own shape (`vector=v`, a bare list) as
    # UNDECIDED, which is a red, but a red saying "cannot determine the arrangement" about a file
    # whose arrangement is perfectly clear and wrong. The arm below can only demand the helper of a
    # file it has recognised as self-providing.
    self_provided = (bool(called & _CONFIG_HELPERS) or "named_vector" in called
                     or bool(_vector_sources(tree)))
    delegated = bool(_server_vectorizers(tree))
    if self_provided and delegated:
        return "both"
    if self_provided:
        return "self-provided"
    if delegated:
        return "delegated"
    return "undecided"


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

    # THE NARROWING'S OWN CONTROL, AND IT DIFFERS FROM THE FIXTURE ABOVE IN EXACTLY ONE THING: the
    # CALLEE. Same keyword, same bare value, four receivers. Two must be collected and two must not,
    # so a matcher that simply stopped matching cannot pass this — which is the failure mode a
    # narrowing invites, and the one an "it no longer reds" check would bless.
    callees = ast.parse(
        "col.data.insert(properties=p, vector=[0.1])\n"          # store write   -> collected
        "col.data.update(uuid=u, vector=[0.2])\n"                # store write   -> collected
        "col.query.hybrid(query=t, vector=[0.3], limit=1)\n"     # SEARCH        -> skipped
        "writer.relocate(collection=c, id=i, vector=[0.4])\n"    # hand-off      -> skipped
    )
    assert sorted(_vector_sources(callees)) == ["[0.1]", "[0.2]"], (
        "the narrowed extractor no longer separates a store write from a read and a hand-off — "
        f"got {sorted(_vector_sources(callees))}. Two of these four are the defect this whole file "
        "exists to catch and two are legitimate; a matcher that collects all four reds on every "
        "caller of the mesh writers, and one that collects none is blind to the defect."
    )

    # THE RESIDUE, ASSERTED AS ITS OWN CASE BECAUSE IT IS A DECISION AND NOT A CONSEQUENCE. An
    # unresolvable callee is COLLECTED, so a bare value reached through a helper fails rather than
    # slipping through. Flipping `_is_store_write`'s default to False would leave every other
    # assertion in this file green.
    indirect = ast.parse("_store(uuid=u, vector=[0.9])\n")
    assert _vector_sources(indirect) == ["[0.9]"], (
        "an unresolvable callee must be treated as a store write. The residue of this rule is "
        "COLLECT: a helper named anything at all is exactly how a bare vector would re-enter."
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


def _repo_creators() -> dict[str, ast.AST]:
    """Every module in the tree that CREATES a collection, mapped to its parsed tree."""
    found: dict[str, ast.AST] = {}
    for path in _REPO.rglob("*.py"):
        # `.venv.wsl` IS THE SECOND VIRTUALENV AND IT WAS MISSING FROM THIS SET BY ONE NAME.
        # AGENTS.md ("Running the tests") states the tree carries TWO: `.venv` (Windows) and
        # `.venv.wsl` (Linux, what CI matches). Excluding only the first walked straight into
        # site-packages and reported two DEPENDENCIES as new collection creators —
        # langchain_community/vectorstores/typesense.py and mem0/vector_stores/weaviate.py — so
        # this seal went red over code nobody here writes or ships. A red that names a real file
        # reads as a finding, which is why it survived a full run before being looked at.
        # Matched on a PREFIX rather than added as a third literal: the next venv will be spelled
        # differently again, and an exclusion list that must be extended per name is the defect.
        if any(part == "__pycache__" or part == "node_modules" or part.startswith(".venv")
               for part in path.parts):
            continue
        try:
            # THE CODE FORM, NOT THE PHRASE. A text match on `collections.create(` reported
            # three files on the first run — `weaviate_utils.py`, the retrieval probe, and THIS
            # SEAL — every one of them merely discussing the mechanism in a comment. Searching
            # for a mechanism by name finds the prose about it.
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            if _creates_collections(tree):
                found[path.relative_to(_REPO).as_posix()] = tree
        except (OSError, SyntaxError):
            continue
    return found


def test_every_creator_in_the_tree_declares_how_it_vectorizes():
    """THE ALLOW-LIST IS GONE, BECAUSE AN ALLOW-LIST'S POPULATION IS EVERY NAME THAT COULD BE ADDED.

    This arm used to sweep the tree and compare what it found against three hand-written paths, one
    of them admitted by the prose reason "manuals; not a routing collection". That is an exemption
    nothing checks: the seal could be retired for any future file by appending one line, and the
    appending is the easy half of adding a broken writer.

    **The excuse turned out to be true and mis-stated, which is why it had to be read rather than
    trusted.** `seed_weaviate_manuals.py` is not safe because manuals are not routing — a manuals
    collection searched by vector has this defect in exactly the same way. It is safe because it
    uses a SERVER-SIDE vectorizer (`text2vec_ollama`), so it never supplies a vector at all, and
    `named_vector_config()` there would be actively wrong: it declares `self_provided`, which would
    switch off the vectorizer the collection is built on. The rule this file enforces everywhere
    else does not apply to it, and now the seal says which rule applies where instead of which
    files are forgiven.

    So there is nothing left to append to. Two arrangements are legal, they are told apart by which
    VECTORIZER is named, and anything unclassifiable FAILS — an admission rule whose residue is
    "allow" admits precisely the files nobody has looked at.
    """
    creators = _repo_creators()
    assert len(creators) >= 3, (
        f"the sweep found only {sorted(creators)} — it found three creators when written, so a "
        f"shorter list means the walk or the AST matcher has stopped seeing them, not that the "
        f"fleet stopped creating collections"
    )

    # (1) PER CALL: every create says something about vectorization. This is the assertion a
    # file-level check cannot make, and the one a second create in an existing file slips past.
    silent = {path: bare for path, tree in creators.items()
              if (bare := _creates_declaring_nothing(tree))}
    assert not silent, (
        f"collection create(s) that declare no vector configuration at the call: {silent}. A bare "
        f"create emits an IMPLICIT space named {VECTOR_SPACE!r} that a positional vector= never "
        f"writes to — the rows then read back as vectorised and no vector search can find one. "
        f"Pass **named_vector_config() if this code supplies its own vectors, or a vectorizer_config "
        f"if the store should embed for it."
    )

    # (2) PER FILE: which arrangement, and does the file's own code match it. TWO assertions and
    # not one, because `undecided` and `both` are opposite defects and a shared message describes
    # neither: one file says nothing about how it vectorizes, the other says two contradictory
    # things. The first draft merged them and reported a file that configures text2vec AND declares
    # self_provided as "cannot be determined", which is exactly wrong — it can be determined, and
    # the answer is that the two cancel.
    undecided = [p for p, t in creators.items() if _vector_arrangement(t) == "undecided"]
    assert not undecided, (
        f"creator(s) whose vector arrangement cannot be determined: {undecided}. Each must either "
        f"self-provide (call named_vector_config() at the create and named_vector() at the write) "
        f"or delegate to a server-side vectorizer and pass no vector. A creator that does neither "
        f"legibly is the state every instance of this defect was found in, which is why the "
        f"residue of this rule is FAIL and not allow."
    )

    contradictory = {p: _server_vectorizers(t) for p, t in creators.items()
                     if _vector_arrangement(t) == "both"}
    assert not contradictory, (
        f"creator(s) that configure a server-side vectorizer AND self-provide: {contradictory}. "
        f"`named_vector_config()` declares `self_provided`/`none`, which switches the vectorizer "
        f"OFF — so the collection ends up with no vectors at all rather than the wrong ones, and "
        f"the failure looks like an embedding outage instead of a schema decision. Exactly one side "
        f"may own the vector."
    )

    # (3) SELF-PROVIDED FILES ONLY. There is deliberately no `delegated` branch here: the two
    # assertions it would want — "does not call the config helper", "passes no vector" — are TRUE BY
    # CONSTRUCTION of `_vector_arrangement`, which only returns `delegated` when both already hold.
    # They were written, and the mutant that should have fired them fired `both` above instead,
    # which is how a born-dead pair announces itself. The real content of that branch is the
    # `contradictory` assertion; two more statements restating its premise is not a second check.
    for path, tree in creators.items():
        if _vector_arrangement(tree) != "self-provided":
            continue
        assert _called_names(tree) & _CONFIG_HELPERS, (
            f"{path} writes its own vectors but never calls named_vector_config() — the write "
            f"addresses a space the create never declared. Reachable: a create can satisfy (1) "
            f"with an explicit `vectorizer_config` and still never declare the named space."
        )
        for expr in _vector_sources(tree):
            # NO ESCAPE FOR `vector=None`. The first draft of this arm carried `or expr == "None"`
            # for the vectorless-by-waiver case, written before checking: the writer OMITS the key
            # rather than passing None, so the excuse admitted a shape nothing produces. An unused
            # exemption is still a door.
            assert expr.startswith("named_vector("), (
                f"{path} passes vector={expr} — a bare value lands in the LEGACY slot, which no "
                f"search targets, while still reading back as a vector"
            )


def test_the_arrangement_classifier_separates_the_shapes_it_claims_to():
    """POSITIVE CONTROL ON THE NEW INSTRUMENT, on the four shapes the arm decides between.

    The arm above is three "assert not <collection>" statements. A classifier that returned
    `self-provided` for everything, or a `_creates_declaring_nothing` that found nothing ever,
    makes all three pass over any tree at all — and the file's existing extractor control exists
    because that already happened once here.
    """
    self_provided = ast.parse(
        "c.collections.create(name='A', **named_vector_config())\n"
        "col.data.insert(properties=p, vector=named_vector(v))\n"
    )
    delegated = ast.parse(
        "c.collections.create(name='B',"
        " vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_ollama(model=m))\n"
        "with col.batch.dynamic() as b:\n    b.add_object(properties=p)\n"
    )
    # The defect itself: a create that declares nothing, and a write that supplies a bare list.
    bare = ast.parse("c.collections.create(name='C')\ncol.data.insert(properties=p, vector=v)\n")
    # `Vectorizer.none` is NOT a server-side vectorizer and NOT a declared named space. It is the
    # shape that looks configured and is not, which is why `undecided` may not mean `allow`.
    pretend = ast.parse(
        "c.collections.create(name='D')\ncfg = wvc.config.Configure.Vectorizer.none()\n"
    )

    assert _vector_arrangement(self_provided) == "self-provided"
    assert _vector_arrangement(delegated) == "delegated", (
        "a real vectorizer reads as delegated — if this says self-provided, the discriminator has "
        "gone back to keying on the vectorizer_config KEYWORD, which both arrangements emit"
    )
    assert _vector_arrangement(bare) == "self-provided", "a bare vector= is a self-provided write"
    assert _vector_arrangement(pretend) == "undecided", (
        "Vectorizer.none() must not read as delegated: nothing embeds, and the create declares "
        "no named space either"
    )

    assert _creates_declaring_nothing(self_provided) == []
    assert _creates_declaring_nothing(delegated) == []
    assert _creates_declaring_nothing(bare) == ["'C'"], (
        "the per-call check cannot see a create that declares nothing, so every arm that relies "
        "on it is vacuous"
    )
    assert _creates_declaring_nothing(pretend) == ["'D'"], (
        "a vectorizer built OUTSIDE the create call is not a declaration AT the create"
    )
    assert _server_vectorizers(delegated) == ["text2vec_ollama"]
    assert _server_vectorizers(pretend) == [], "Vectorizer.none is not a server-side vectorizer"
