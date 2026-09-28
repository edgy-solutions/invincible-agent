"""THE SECOND MIGRATED ROUTE'S SEAL — engine-o's verb lookup, incumbent arm v. `WeaviateVectors`.

A SECOND ROUTE MOVED (`/search_predicates` and `/classify_predicate`, which share one search),
behind the SAME flag as the first, `ONTOLOGY_CLASS_POOL_VIA_MESH`, DEFAULT OFF. The class pool
proved the shared implementation can serve one caller; `nominate`'s own docstring says `domains` is
a SEQUENCE because "both live call sites scope by an entitlement LIST", and this is the second of
those two call sites finally arriving through the interface instead of around it.

**WHAT THIS FILE ASSERTS THAT THE CLASS SEAL DOES NOT.** The class pool's projection was four keys
and was duplicated deliberately, so its equality arms compared two independent expressions. This
route's projection is fourteen keys with an anti-synonym penalty, two JSON-string tolerances and a
re-rank, and it is SHARED (`_predicate_row`, `_predicate_ranked`) precisely because two copies would
drift. That choice moves the defect class: a defect in shared code sits identically on both sides of
every equality arm and is invisible to all of them — measured on this lane at item 3, where
reverting ONE arm of the `definition` repair reddened 22 arms and reverting BOTH reddened 4 with the
parity arms silent. So the shared projection is sealed by arms that assert its VALUES (the penalty's
arithmetic, the floor at zero, both serializations, the re-rank order, a scoreless row sorting last)
and by an arm that there is no SECOND implementation of it. The parity arms are still here; they are
just not what defends the shared half.

**THE DIFFERENCES, REPORTED RATHER THAN SMOOTHED OVER.** A blank `user_email` is refused by the mesh
arm with a 400 and served by the incumbent (neither request model carried a person before this
change). A row owning its own `score` property is read differently by the two arms, and no Predicate
row has ever carried one, so the behaviour is PINNED rather than aligned by guess. And the mesh arm
CASE-FOLDS the entitlement scope where the incumbent passes it verbatim — a difference no caller can
currently reach, because both routes upper-case before calling, which this file asserts as the thing
that makes it unreachable.

Run: uv run --frozen pytest tests/test_the_migrated_predicate_route_returns_the_same_rows.py -v
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_CENSUS = _REPO / "docs" / "measurements" / "walk-census.yaml"
_ENGINE_O = _REPO / "agent_fleet" / "ontology_service" / "main.py"


# ── the census, as the population ───────────────────────────────────────────────────────────


def _census_rows() -> list[dict]:
    rows = yaml.safe_load(_CENSUS.read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if r.get("question") and r.get("domains")]


_ROWS = _census_rows()
_IDS = [r["id"] for r in _ROWS]


def test_the_POPULATION_is_the_census_and_is_not_empty():
    """AN ANCHOR COUNT, for the same reason the class seal carries one: a parametrized arm over an
    empty list is green without running once, and a derivation that matches nothing looks exactly
    like twenty questions that agree.

    A floor rather than an exact count, so a NEW census question does not teach the next person to
    delete the seal.
    """
    assert len(_ROWS) >= 20, f"the census population thinned to {len(_ROWS)} rows: {_IDS}"
    assert len(_IDS) == len(set(_IDS)), "duplicate census ids — the parametrization would collide"
    assert all(r.get("user") for r in _ROWS), (
        "a census row carries no user; the mesh arm attributes its read to a person and the parity "
        "comparison would be measuring a refusal against a success"
    )


# ── the harness: main.py, with its heavy imports stubbed ────────────────────────────────────


#: This name was NOT in `sys.modules` before the install, so undoing means DELETING it rather than
#: restoring a None that would then shadow the real package.
_ABSENT = object()

#: What `_install_stubs()` changed in `sys.modules`, and what was there before it.
_FOOTPRINT: dict[str, object] = {}


def _load_main():
    """Load engine-o's `main.py` through the stub harness that already exists for it, then PUT
    `sys.modules` BACK.

    THE STUBS ARE IMPORTED, NOT RETYPED — `tests/test_predicate_hybrid_search.py` already stubs
    rdflib / weaviate / neo4j / baml_client for this module and documents a live trap in doing so.
    THE LOADER, by contrast, IS A SECOND COPY of the one in
    `tests/test_the_migrated_route_returns_the_same_rows.py`, and that is deliberate: sharing it
    would mean sharing its module-level `_FOOTPRINT`, so two seal files would be mutating one record
    of what to restore, in whichever order pytest collected them. Two independent copies of a
    twenty-line restore cannot do that. **A THIRD copy is the point at which it becomes a helper** —
    a threshold rather than an intention, because "we should extract this" has no expiry.

    The install is UNDONE because reusing a harness reuses its global effects: co-collecting that
    harness with `tests/routing/test_a_vector_is_written_where_the_search_looks.py` reds two of that
    file's arms, a pre-existing defect at HEAD that the class seal reproduced exactly by importing it.
    """
    spec = importlib.util.spec_from_file_location(
        "_predicate_stub_harness_2", str(_REPO / "tests" / "test_predicate_hybrid_search.py")
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)

    before = dict(sys.modules)
    harness._install_stubs()
    footprint = [k for k, v in sys.modules.items() if before.get(k) is not v]
    _FOOTPRINT.update({k: before.get(k, _ABSENT) for k in footprint})

    try:
        spec = importlib.util.spec_from_file_location(
            "ontology_main_predicate_migration_test", str(_ENGINE_O)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        # IN `finally`: a load that raises would otherwise leave the stubs installed for every file
        # collected after this one, and the failures they caused would be attributed to them.
        for name, prior in _FOOTPRINT.items():
            if prior is _ABSENT:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


@pytest.fixture(scope="module")
def main():
    return _load_main()


# ── the store: one scripted Predicate collection, served to whichever arm asks ───────────────


class _Meta:
    def __init__(self, score):
        self.score = score


class _Obj:
    def __init__(self, props, score):
        self.properties = props
        self.metadata = _Meta(score)


class _Resp:
    def __init__(self, objects):
        self.objects = objects


class _Query:
    """Records every call, so the arms can be compared on what they ASKED as well as on what they
    returned. Two arms agreeing on rows while sending different filters agree by luck.

    **THE DOUBLE IGNORES `limit` AND `filters`**, which is not a shortcut but the reason the
    same-query arm below exists: the class pilot's `domain scope dropped` mutant left all twenty row
    -equality arms green because a scripted store serves the same rows whatever it is handed. Row
    identity against a double therefore cannot detect a scope change, and only the recorded call can.
    """

    def __init__(self, objs, boom=False):
        self._objs, self._boom = objs, boom
        self.calls: list[dict] = []

    def _go(self, kind, **kw):
        if self._boom:
            raise RuntimeError("weaviate down mid-query")
        self.calls.append({"kind": kind, **kw})
        return _Resp(self._objs)

    def hybrid(self, **kw):
        return self._go("hybrid", **kw)

    def bm25(self, **kw):
        return self._go("bm25", **kw)


class _Collections:
    def __init__(self, objs, exists=True, boom=False):
        self._q = _Query(objs, boom)
        self._exists = exists

    def exists(self, _n):
        return self._exists

    def get(self, _n):
        return type("H", (), {"query": self._q})


class _Client:
    def __init__(self, objs=(), exists=True, boom=False):
        self.collections = _Collections(list(objs), exists, boom)

    @property
    def calls(self):
        return self.collections._q.calls


class _Obs:
    """What `observe_query_embedding` returns: the SERVED identity plus the vector."""

    def __init__(self, dim=8):
        self.served = self.requested = "nomic-embed-text"
        self.dimension = dim
        self.vector = tuple([0.1] * dim)


def _wire(main, monkeypatch, client, *, embed_fails=False):
    """Point both arms at one store and one embedding, and count which entry point each uses."""
    counts = {"embed_query": 0, "observe_query_embedding": 0}

    def _embed_query(text):
        counts["embed_query"] += 1
        if embed_fails:
            raise RuntimeError("embedding gateway down")
        return [0.1] * 8

    def _observe(text, timeout=30.0):
        counts["observe_query_embedding"] += 1
        if embed_fails:
            raise RuntimeError("embedding gateway down")
        return _Obs()

    monkeypatch.setattr(main, "_WEAVIATE_CLIENT", client)
    monkeypatch.setattr(main, "embed_query", _embed_query)
    monkeypatch.setattr(main, "observe_query_embedding", _observe)
    return counts


#: THE QUERY THE FIXTURE ROWS ARE BUILT AGAINST. The anti-synonym penalty is a Jaccard overlap
#: between this text's tokens and a candidate's anti-synonyms, so the rows below are not "some rows"
#: — each one's anti-synonyms were chosen against THIS string to reach a named branch, and the
#: values the arms assert were measured, not predicted.
_QUERY = "forecast the maintenance budget"


def _scripted():
    """Seven rows, one per shape the shared projection must handle — chosen by branch, not by taste.

    `plain` (no anti-synonyms, penalty inapplicable), `penalised` (overlap 0.5 on a 0.80 score →
    0.55), `json_anti` (BOTH lists arriving as JSON STRINGS, doc-tools' other serialization, and it
    must score exactly like `penalised`), `scoreless` (no retrieval score at all — sorts last and
    must not raise), `bare` (every optional key ABSENT, which is a different read from present-and
    -null), `floored` (overlap large enough that the penalty would go negative), and `broken_json`
    (an unparseable string, which must degrade to an empty list rather than propagate a ValueError).
    """
    return [
        _Obj(
            {
                "verb_iri": "mesh:plain",
                "verb_local": "plain",
                "input_uri": "i",
                "output_uri": "o",
                "endpoint_url": "http://e",
                "owner_persona": "ENGINEER",
                "domains": ["MAINTENANCE"],
                "cost_class": "cheap",
                "requires_human_approval": False,
                "description": "a plain row",
                "verb_synonyms": ["p"],
                "verb_anti_synonyms": [],
            },
            0.90,
        ),
        _Obj(
            {
                "verb_iri": "mesh:penalised",
                "verb_local": "penalised",
                "domains": [],
                "verb_anti_synonyms": ["forecast budget"],
                "verb_synonyms": [],
                "description": "overlaps the query",
            },
            0.80,
        ),
        _Obj(
            {
                "verb_iri": "mesh:json_anti",
                "verb_local": "json_anti",
                "domains": ["MAINTENANCE"],
                "verb_anti_synonyms": '["forecast budget"]',
                "verb_synonyms": '["a", "b"]',
                "description": "json-string shapes",
            },
            0.80,
        ),
        _Obj(
            {
                "verb_iri": "mesh:scoreless",
                "verb_local": "scoreless",
                "domains": ["MAINTENANCE"],
                "verb_anti_synonyms": [],
                "verb_synonyms": [],
            },
            None,
        ),
        _Obj({"verb_iri": "mesh:bare"}, 0.10),
        _Obj(
            {
                "verb_iri": "mesh:floored",
                "verb_local": "floored",
                "domains": ["MAINTENANCE"],
                "verb_anti_synonyms": ["forecast the maintenance budget for next quarter"],
                "verb_synonyms": [],
                "description": "overlap big enough to floor",
            },
            0.05,
        ),
        _Obj(
            {
                "verb_iri": "mesh:broken_json",
                "verb_local": "broken_json",
                "domains": ["MAINTENANCE"],
                "verb_anti_synonyms": "{not json",
                "verb_synonyms": "{not json",
                "description": "unparseable serialization",
            },
            0.20,
        ),
    ]


def _mesh_rows(objs):
    """The same store answer as `nominate` hands its caller: properties PLUS a `score` key.

    Used only by the arms that drive `_predicate_row` directly. The parity arms drive the real
    `nominate` through the real client double, so nothing here stands in for the implementation.
    """
    return [dict(o.properties, score=o.metadata.score) for o in objs]


def _pool(main, monkeypatch, *, on, domains=("MAINTENANCE",), query=_QUERY, limit=10,
          user_email="person@example.com", objs=None, exists=True, boom=False,
          embed_fails=False):
    """One arm's pool, through the FORK, so the flag is what selects the path under test."""
    client = _Client(_scripted() if objs is None else objs, exists=exists, boom=boom)
    counts = _wire(main, monkeypatch, client, embed_fails=embed_fails)
    monkeypatch.setattr(main, "ONTOLOGY_CLASS_POOL_VIA_MESH", on)
    rows = asyncio.run(
        main.predicate_hybrid_search(
            query=query,
            entitled_domains=list(domains),
            limit=limit,
            user_email=user_email,
        )
    )
    return rows, counts, client


# ── THE RULING: the flag changes no rows ────────────────────────────────────────────────────


@pytest.mark.parametrize("row", _ROWS, ids=_IDS)
def test_the_FLAG_CHANGES_NO_ROWS_for_any_census_question(main, monkeypatch, row):
    """The flag on and off, one store, one census question, same candidate rows.

    The census questions are the population for the same reason the class seal uses them: they are
    the questions this fleet asks every morning, so an identity that holds for them is a claim about
    what would actually change. The verb pool is what the supervisor ranks and thresholds, so a row
    or a score that moved here moves a routing decision.
    """
    q = row["question"]
    doms = [d for d in (row.get("domains") or []) if d]
    off_rows, _, _ = _pool(main, monkeypatch, on=False, query=q, domains=doms)
    on_rows, _, _ = _pool(main, monkeypatch, on=True, query=q, domains=doms)

    assert off_rows == on_rows, (
        f"{row['id']}: the flag changed the verb pool.\n  off: {off_rows}\n  on:  {on_rows}"
    )
    assert off_rows, "the fixture returned no rows — an empty pool compares equal to anything"


def test_the_FLAG_SELECTS_A_DIFFERENT_CODE_PATH(main, monkeypatch):
    """THE CONTROL FOR EVERY EQUALITY ARM ABOVE, and without it they are decorations.

    A mesh arm that fell through to the incumbent, or a flag read at import and never re-read, would
    make every comparison above compare one path with itself: identical rows, permanently green,
    nothing migrated. The arms enter the embedding through different functions — `embed_query` for
    the incumbent, `observe_query_embedding` for the mesh arm, which needs the SERVED model identity
    for its marker check — so the counters say which path ran.
    """
    _, off_counts, _ = _pool(main, monkeypatch, on=False)
    _, on_counts, _ = _pool(main, monkeypatch, on=True)

    assert off_counts == {"embed_query": 1, "observe_query_embedding": 0}, off_counts
    assert on_counts == {"embed_query": 0, "observe_query_embedding": 1}, on_counts


@pytest.mark.parametrize(
    "domains,label",
    [
        (["MAINTENANCE"], "one-domain"),
        (["MAINTENANCE", "PRODUCTION_COST"], "two-domains"),
        ([], "no-domains-unfiltered"),
    ],
)
def test_the_two_arms_also_send_the_SAME_QUERY(main, monkeypatch, domains, label):
    """Same rows out is not the same question in — and on THIS route the question is an entitlement
    boundary, because the predicate filter is an OR that deliberately keeps domain-agnostic verbs
    visible to scoped callers (27 of 129 predicates carry no domains).

    One case per filter SHAPE the builder can take, not the first N census rows: unscoped (no
    filter), and scoped, where both arms must compose the same `any_of` of `contains_any` and the
    length-zero branch.
    """
    _, _, off_client = _pool(main, monkeypatch, on=False, domains=domains)
    _, _, on_client = _pool(main, monkeypatch, on=True, domains=domains)

    def _shape(calls):
        out = []
        for c in calls:
            d = dict(c)
            md = d.pop("return_metadata", None)
            # The metadata objects are different INSTANCES by construction; what must match is
            # what was asked FOR.
            d["return_metadata_kw"] = getattr(md, "kw", None)
            d["vector"] = "present" if d.get("vector") else d.get("vector")
            out.append(d)
        return out

    assert _shape(off_client.calls) == _shape(on_client.calls), (
        f"{label}: the arms issued different queries.\n"
        f"  off: {_shape(off_client.calls)}\n  on:  {_shape(on_client.calls)}"
    )


# ── the difference no caller can reach, and the two lines that make it unreachable ───────────


def test_THE_KNOWN_DIFF_the_mesh_arm_CASE_FOLDS_the_entitlement_scope(main, monkeypatch):
    """`WeaviateVectors._domain_filter` upper-cases the scope; this route's incumbent passes it to
    `contains_any` verbatim. So a LOWER-CASE scope produces two different queries.

    PINNED AS A DIFFERENCE, not aligned: aligning it would mean editing the incumbent's filter
    inside a migration that is supposed to change nothing, which is the one change no parity arm can
    see. The direction is why it is worth an arm at all — against an upper-case store the mesh arm
    matches rows the incumbent would have missed, and a migration that widens what a caller may see
    is the ADR-0025 boundary, not a formatting difference.
    """
    _, _, off_client = _pool(main, monkeypatch, on=False, domains=["maintenance"])
    _, _, on_client = _pool(main, monkeypatch, on=True, domains=["maintenance"])

    def _scope(client):
        assert client.calls, "no query was issued, so there is no scope to compare"
        f = client.calls[-1]["filters"]
        # the stub Filter composes plain tuples: ("any_of", [("contains_any", "domains", [...]), ...])
        assert f and f[0] == "any_of", f
        return f[1][0]

    assert _scope(off_client) == ("contains_any", "domains", ["maintenance"]), _scope(off_client)
    assert _scope(on_client) == ("contains_any", "domains", ["MAINTENANCE"]), _scope(on_client)


def test_the_ROUTES_upper_case_the_scope_which_is_what_makes_that_DIFF_unreachable(main):
    """THE OTHER HALF, and the half that actually protects the deployment.

    The arm above proves the two searches disagree on a lower-case scope. Whether that disagreement
    can ever HAPPEN is a fact about the callers, and it lives two frames away from either search: a
    branch proved unreachable needs the reason recorded beside the consumer the reachability depends
    on, or the next reader re-derives it or, worse, deletes the line.

    Both routes reaching this search normalise first — `/search_predicates` calls it "defensive:
    domains arrive uppercase from the auth layer but a mis-cased POST still scopes correctly". This
    arm is derived from the source, so a route added WITHOUT that normalisation reds here and names
    itself, and the answer is then to normalise it rather than to widen this set.

    **WHAT THIS ARM FOLLOWS, AND WHY IT IS NOT THE FUNCTION'S TEXT.** The first draft asked whether
    an upper-casing comprehension appeared anywhere in the calling function, and a mutant walked
    through it: LEAVE the comprehension where it is and hand the call `request.entitled_domains`
    instead of the normalised local. All 52 arms stayed green. That mutant is not contrived — a
    normalised local and a raw request field, one line apart under similar names, is how this gets
    written by accident, and it is exactly the edit that makes the case-fold difference REACHABLE
    while every other arm here reports parity.

    So what is followed is the VALUE handed to `entitled_domains=` and, when that value is a name,
    every binding of that name in the function. All of them must upper-case: a name normalised on one
    branch and not another is normalised on neither.
    """
    tree = ast.parse(_ENGINE_O.read_text(encoding="utf-8"))
    callers: dict[str, tuple[str, bool]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and ast.unparse(n.func).split(".")[-1] == "predicate_hybrid_search"
        ]
        if not calls:
            continue

        passed = next(
            (kw.value for c in calls for kw in c.keywords if kw.arg == "entitled_domains"), None
        )
        assert passed is not None, (
            f"{fn.name} calls predicate_hybrid_search without naming entitled_domains, so the scope "
            "is positional or absent and this arm cannot follow it to the call"
        )
        expr = ast.unparse(passed)

        if isinstance(passed, ast.Name):
            bindings = [
                ast.unparse(node.value)
                for node in ast.walk(fn)
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == passed.id for t in node.targets)
            ]
            # No binding inside this function means the value arrived from somewhere this arm cannot
            # follow, which it must report rather than silently approve.
            ok = bool(bindings) and all(".upper()" in b for b in bindings)
            expr = f"{expr} <- {bindings or ['(bound outside this function)']}"
        else:
            ok = ".upper()" in expr

        callers[fn.name] = (expr, ok)

    assert set(callers) == {"search_predicates", "classify_predicate"}, (
        f"the set of callers of predicate_hybrid_search changed: {sorted(callers)}. A new caller is "
        "a new place the case-fold difference could become reachable; normalise its scope the way "
        "the two existing routes do, then name it here."
    )
    bad = {k: v[0] for k, v in callers.items() if not v[1]}
    assert not bad, (
        f"these callers do not hand the migrated predicate search an upper-cased scope: {bad}. With "
        "the flag on, an un-normalised lower-case scope is matched by the mesh arm and missed by the "
        "incumbent — a scope widening that row identity cannot see, because a scripted store serves "
        "the same rows whatever filter it is handed."
    )


# ── failure, emptiness, and the difference between them ─────────────────────────────────────


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_a_MID_QUERY_FAILURE_is_a_503_on_both_arms(main, monkeypatch, on):
    """RULED 2026-09-14 for this route by name: an empty list from the predicate search means NO
    PREDICATE MATCHED, and the supervisor falls back to the generalist on it. A substrate outage
    returned as `[]` is therefore a confident no-match under a false diagnosis — the same defect the
    class route has, one route over.
    """
    with pytest.raises(main.HTTPException) as exc:
        _pool(main, monkeypatch, on=on, boom=True)
    assert exc.value.status_code == 503, exc.value.status_code


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_an_EMPTY_STORE_is_NOT_a_failure_on_either_arm(main, monkeypatch, on):
    """Its companion, differing in exactly what the guard decides on: the store ANSWERS, with
    nothing. `[]` here is a real answer and the caller's fallback is correct on it, which is the
    whole reason the arm above must not return the same shape."""
    rows, _, client = _pool(main, monkeypatch, on=on, objs=[])
    assert rows == [], rows
    assert client.calls, "the store was never asked, so 'empty' was not measured"


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_an_ABSENT_COLLECTION_returns_an_empty_list_on_both_arms(main, monkeypatch, on):
    """No collection is not a failed query: nothing was retrieved because there was nothing to
    retrieve from, and both arms answer `[]` without asking."""
    rows, _, client = _pool(main, monkeypatch, on=on, exists=False)
    assert rows == [], rows
    assert client.calls == [], f"a query was issued against an absent collection: {client.calls}"


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_the_BM25_DEGRADATION_still_answers_on_both_arms(main, monkeypatch, on):
    """A failed embedding degrades to BM25 on both arms rather than refusing — and the pool is still
    ranked, because the anti-synonym penalty is computed from the BM25 score exactly as it is from
    the hybrid one. The fleet ran sixty-seven days BM25-only with nothing in any result saying so;
    what is asserted here is that the degradation ANSWERS, and the mesh arm reports it."""
    rows, _, client = _pool(main, monkeypatch, on=on, embed_fails=True)
    assert rows, "a degraded retrieval must still answer — BM25 is a degradation, not an outage"
    assert [c["kind"] for c in client.calls] == ["bm25"], client.calls


def test_THE_KNOWN_DIFF_a_blank_user_email_is_refused_by_the_mesh_arm_only(main, monkeypatch):
    """THE ONE BEHAVIOURAL CHANGE OF THIS MIGRATION, and the item that has to be settled before any
    default moves.

    `nominate` refuses a service initiator, so the mesh arm needs a person — and neither
    `SearchPredicatesRequest` nor `ClassifyPredicateRequest` carried one before this change, so a
    caller that has not learned the field gets a 400 with the flag on. The blank is REFUSED rather
    than minted: `Initiator(subject="", kind="person")` would pass the interface's check while being
    exactly what that check exists to stop.
    """
    rows, _, _ = _pool(main, monkeypatch, on=False, user_email="")
    assert rows, "the incumbent has never read identity and must be unaffected"

    with pytest.raises(main.HTTPException) as exc:
        _pool(main, monkeypatch, on=True, user_email="")
    assert exc.value.status_code == 400, exc.value.status_code
    assert "user_email" in str(exc.value.detail), exc.value.detail


def test_the_REQUEST_MODELS_BOTH_carry_the_person_and_BOTH_hand_it_on(main):
    """The 400 above is only reachable if the field exists and the routes forward it. Derived from
    the module rather than typed: a model that loses the field, or a route that stops passing it,
    turns every request into an anonymous one — served silently with the flag off, and refused many
    frames from the omission with it on.
    """
    for model in ("SearchPredicatesRequest", "ClassifyPredicateRequest"):
        cls = getattr(main, model)
        assert "user_email" in cls.model_fields, f"{model} lost its user_email field"
        assert cls.model_fields["user_email"].default == "", (
            f"{model}.user_email no longer defaults to the empty string; a non-blank default would "
            "make the mesh arm's refusal unreachable and attribute reads to a literal"
        )

    tree = ast.parse(_ENGINE_O.read_text(encoding="utf-8"))
    passed = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).split(".")[-1] == "predicate_hybrid_search"
            ):
                kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
                passed[fn.name] = kw.get("user_email")
    assert passed == {
        "search_predicates": "request.user_email",
        "classify_predicate": "request.user_email",
    }, (
        f"a caller of the migrated predicate search stopped handing the identity on: {passed}. "
        "Every parameter on this chain defaults to the empty string, so a dropped keyword is not a "
        "TypeError, not a log line, and not a failure anywhere — it is a silently anonymous read."
    )


# ── the shared projection, sealed on its VALUES because parity cannot see it ─────────────────


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_the_ANTI_SYNONYM_PENALTY_reduces_the_score_by_ALPHA_TIMES_OVERLAP(main, monkeypatch, on):
    """The arithmetic, not the presence of the field. A penalty pass that computed the overlap and
    then applied nothing would leave every parity arm green and every score wrong, on both arms at
    once, because the projection is SHARED.

    Measured against the default alpha read from the module, never restated: a seal that hard-codes
    0.50 asserts a number this file invented rather than the one the engine uses.
    """
    rows, _, _ = _pool(main, monkeypatch, on=on)
    by_iri = {r["verb_iri"]: r for r in rows}
    alpha = main._ANTI_SYN_PENALTY_ALPHA

    hit = by_iri["mesh:penalised"]
    assert hit["raw_score"] == pytest.approx(0.80), hit
    assert hit["anti_synonym_overlap"] == pytest.approx(0.5), hit
    assert hit["score"] == pytest.approx(0.80 - alpha * 0.5), hit

    clean = by_iri["mesh:plain"]
    assert clean["anti_synonym_overlap"] == 0.0, clean
    assert clean["score"] == clean["raw_score"] == pytest.approx(0.90), clean


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_the_PENALTY_FLOORS_AT_ZERO_and_never_goes_NEGATIVE(main, monkeypatch, on):
    """A negative score is not a worse candidate, it is a sort key nobody designed: the scoreless
    rows sort at -1.0, so a candidate penalised past zero would rank BELOW a row that was never
    scored at all."""
    rows, _, _ = _pool(main, monkeypatch, on=on)
    floored = {r["verb_iri"]: r for r in rows}["mesh:floored"]
    assert floored["raw_score"] == pytest.approx(0.05), floored
    assert floored["anti_synonym_overlap"] > 0.1, floored
    assert floored["score"] == 0.0, floored
    assert all((r["score"] is None) or r["score"] >= 0.0 for r in rows), rows


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_BOTH_SERIALIZATIONS_of_the_synonym_lists_are_TOLERATED(main, monkeypatch, on):
    """doc-tools writes these fields as a list or as a JSON STRING depending on which sync ran, and
    a string that is silently treated as a list of CHARACTERS would compute an overlap against
    single letters — a wrong penalty rather than an error.

    The row carrying both fields as JSON strings must come out identical to the row carrying them as
    lists, and an UNPARSEABLE string must degrade to empty rather than propagate a ValueError into a
    routing decision.
    """
    rows, _, _ = _pool(main, monkeypatch, on=on)
    by_iri = {r["verb_iri"]: r for r in rows}

    assert by_iri["mesh:json_anti"]["anti_synonym_overlap"] == pytest.approx(
        by_iri["mesh:penalised"]["anti_synonym_overlap"]
    ), (by_iri["mesh:json_anti"], by_iri["mesh:penalised"])
    assert by_iri["mesh:json_anti"]["score"] == pytest.approx(by_iri["mesh:penalised"]["score"])
    assert by_iri["mesh:json_anti"]["verb_synonyms"] == ["a", "b"], by_iri["mesh:json_anti"]

    broken = by_iri["mesh:broken_json"]
    assert broken["verb_synonyms"] == [], broken
    assert broken["anti_synonym_overlap"] == 0.0, broken
    assert broken["score"] == broken["raw_score"] == pytest.approx(0.20), broken


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_the_POOL_is_RERANKED_by_the_ADJUSTED_score(main, monkeypatch, on):
    """Without the re-rank the order is still the store's, and a penalty on the top-1 changes
    nothing — the supervisor reads `[0]`. The store hands these rows back in a deliberately
    different order from the one they must come out in."""
    rows, _, _ = _pool(main, monkeypatch, on=on)
    served = [o.properties["verb_iri"] for o in _scripted()]
    got = [r["verb_iri"] for r in rows]

    assert got != served, "the pool came back in the store's order, so nothing re-ranked it"
    scores = [(-1.0 if r["score"] is None else r["score"]) for r in rows]
    assert scores == sorted(scores, reverse=True), list(zip(got, scores))
    assert got[0] == "mesh:plain", got
    assert got[-1] == "mesh:scoreless", got


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_a_SCORELESS_row_SORTS_LAST_rather_than_raising(main, monkeypatch, on):
    """A row with no retrieval score at all reaches the sort key as None. The key substitutes -1.0
    for it, and the row still appears — dropping it would be a candidate lost to a ranking
    artifact, and raising would take a routing decision down over one unscored row."""
    rows, _, _ = _pool(main, monkeypatch, on=on)
    tail = rows[-1]
    assert tail["verb_iri"] == "mesh:scoreless", rows
    assert tail["score"] is None and tail["raw_score"] is None, tail
    assert len(rows) == len(_scripted()), "a row was dropped from the pool"


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_a_ROW_MISSING_EVERY_OPTIONAL_KEY_still_meets_the_row_CONTRACT(main, monkeypatch, on):
    """`bare` carries only a `verb_iri`. The supervisor reads `endpoint`, `domains` and
    `owner_persona` off every row it ranks, so a row that omits keys rather than defaulting them is
    a KeyError several frames away from the store that produced it."""
    rows, _, _ = _pool(main, monkeypatch, on=on)
    bare = {r["verb_iri"]: r for r in rows}["mesh:bare"]
    assert bare["endpoint"] == "" and bare["verb_type"] == "", bare
    assert bare["domains"] == [] and bare["verb_synonyms"] == [], bare
    assert bare["owner_persona"] is None and bare["cost_class"] is None, bare
    assert bare["requires_human_approval"] is False, bare
    assert bare["description"] == "", bare
    full = {r["verb_iri"]: r for r in rows}["mesh:plain"]
    assert set(bare) == set(full), (set(full) - set(bare), set(bare) - set(full))


def test_the_PROJECTION_HAS_NO_SECOND_IMPLEMENTATION(main):
    """THE ARM THAT PAYS FOR SHARING. The projection is shared so it cannot drift; this is what
    stops a second copy appearing later and drifting anyway.

    The census is the DIAGNOSTIC KEY, not the function name: `anti_synonym_overlap` is a key no
    other row in this engine carries, so a second builder of predicate rows — a new route, a
    copy-paste into a helper — shows up as a second occurrence of it. Derived from the source with
    an anchor count, because a matcher that matches nothing is the same green as agreement.
    """
    src = _ENGINE_O.read_text(encoding="utf-8")
    assert src.count('"anti_synonym_overlap":') == 1, (
        f'"anti_synonym_overlap" is written as a row key {src.count(chr(34) + "anti_synonym_overlap" + chr(34) + ":")} '
        "times; the predicate row is built in more than one place and the two copies will drift"
    )

    tree = ast.parse(src)
    callers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Call)
                and ast.unparse(node.func).split(".")[-1] == "_predicate_row"
            ):
                callers.add(fn.name)
    assert callers == {"_predicate_hybrid_search_sync", "_predicate_pool_via_mesh_sync"}, (
        f"the callers of the shared projection are {sorted(callers)}; both arms of the migration "
        "must go through it, or the parity arms are comparing two expressions again and the value "
        "arms above only cover one of them"
    )


def test_THE_KNOWN_DIFF_a_row_owning_a_score_PROPERTY_is_read_differently(main, monkeypatch):
    """A `Predicate` row has never carried a `score` property, so this is PINNED rather than
    aligned — the same treatment the class pilot gave a `uri`-less row.

    `WeaviateVectors._search` keeps a STORED `score` and drops the retrieval one, reporting the
    collision rather than raising; the incumbent ignores any stored `score` and always reports the
    retrieval one. Whichever way it is settled, this arm reds and names the decision.
    """
    objs = [_Obj({"verb_iri": "mesh:collides", "score": 0.11, "domains": []}, 0.99)]

    off_rows, _, _ = _pool(main, monkeypatch, on=False, objs=objs)
    on_rows, _, _ = _pool(main, monkeypatch, on=True, objs=objs)

    assert off_rows[0]["score"] == pytest.approx(0.99), off_rows
    assert on_rows[0]["score"] == pytest.approx(0.11), on_rows
    assert off_rows != on_rows, "the pinned difference disappeared — settle it, do not delete it"


# ── the harness leaves nothing behind ───────────────────────────────────────────────────────


def test_the_STUB_INSTALL_LEAVES_NO_FOOTPRINT_in_sys_modules(main):
    """The load is the point of this arm, and `main` is requested only to force it to have happened.

    A leaked stub is not a failure here — it is a failure in whichever file pytest collects next,
    attributed to that file. The class seal found exactly that defect at HEAD by reusing this same
    harness, so a second reuse owes the same check.
    """
    assert _FOOTPRINT, "nothing was recorded as installed, so this arm asserts nothing"
    leaked = [
        name for name, prior in _FOOTPRINT.items()
        if (name in sys.modules) is not (prior is not _ABSENT)
        or (prior is not _ABSENT and sys.modules.get(name) is not prior)
    ]
    assert not leaked, f"the stub harness left {leaked} behind in sys.modules"
