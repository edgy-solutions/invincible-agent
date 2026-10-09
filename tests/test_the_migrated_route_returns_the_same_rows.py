"""THE ROUTE MIGRATION PILOT'S SEAL — engine-o's class lookup, incumbent arm v. `WeaviateVectors`.

ONE ROUTE MOVED (`/resolve`), behind `ONTOLOGY_CLASS_POOL_VIA_MESH`, DEFAULT ON since 2026-10-01. What this file
asserts is the only thing that makes a flag a migration rather than a second implementation: for
the questions the fleet actually asks, **both arms return the same rows**, and both say how they
retrieved them.

**THE POPULATION IS THE CENSUS, DERIVED FROM `docs/measurements/walk-census.yaml`.** Not a
hand-picked query, and not a fixture invented here: the census rows are the questions whose answers
this fleet reads every morning, so a row identity that holds for them is a claim about what would
actually change. A fixture of my own choosing would control the LOGIC and say nothing about whether
the logic still points at the questions anyone asks.

**THE PARITY ARM NEEDS ITS OWN CONTROL AND HAS ONE.** If the flag selected the same code twice — a
mesh arm that quietly delegated, a flag read once at import and never re-read — every equality
assertion below would pass, vacuously and forever. So `test_the_FLAG_SELECTS_A_DIFFERENT_CODE_PATH`
counts which embedding entry point each arm calls: the incumbent calls `embed_query`, the mesh arm
calls `observe_query_embedding` (it needs the SERVED model identity for the marker check, which is
the whole reason that function exists). Different counters moving is the proof that the rows being
compared came from two different paths.

WHAT IS *NOT* ASSERTED HERE, and is reported instead: the two arms are NOT identical on a blank
`user_email` (the mesh arm refuses with a 400 — a read attributed to nobody), and the mesh arm's
`.get("uri")` does not raise where the incumbent's `properties["uri"]` would. Both are measured
below as DIFFERENCES rather than smoothed over, because a migration whose diff nobody wrote down is
a migration nobody can review.

Run: uv run --frozen pytest tests/test_the_migrated_route_returns_the_same_rows.py -v
"""
from __future__ import annotations

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


# ── the census, as the population ───────────────────────────────────────────────────────────


def _census_rows() -> list[dict]:
    rows = yaml.safe_load(_CENSUS.read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if r.get("question") and r.get("domains")]


_ROWS = _census_rows()
_IDS = [r["id"] for r in _ROWS]


def test_the_POPULATION_is_the_census_and_is_not_empty():
    """AN ANCHOR COUNT. A derivation that matches nothing is the same green as twenty questions
    that agree — and a parametrized arm over an empty list passes without running once.

    It asserts a floor rather than an exact count on purpose: rows get added, and a seal that reds
    on a NEW census question would teach the next person to delete the seal. A DROP to zero, or a
    row that lost its question or its domains, is what this catches.
    """
    assert len(_ROWS) >= 20, f"the census population thinned to {len(_ROWS)} rows: {_IDS}"
    assert len(_IDS) == len(set(_IDS)), "duplicate census ids — the parametrization would collide"
    assert all(r.get("user") for r in _ROWS), (
        "a census row carries no user; the mesh arm attributes its read to a person and the "
        "parity comparison would be measuring a refusal against a success"
    )


# ── the harness: main.py, with its heavy imports stubbed ────────────────────────────────────


#: Sentinel: this name was NOT in `sys.modules` before the install, so undoing means DELETING it
#: rather than restoring a None that would then shadow the real package.
_ABSENT = object()

#: What `_install_stubs()` changed in `sys.modules`, and what was there before it — recorded so the
#: install can be undone. Populated by `_load_main()`; asserted by the leak arm at the end.
_FOOTPRINT: dict[str, object] = {}


def _load_main():
    """Load engine-o's `main.py` reusing the stub harness that already exists for it, then PUT
    `sys.modules` BACK.

    THE STUBS ARE IMPORTED, NOT RETYPED. `tests/test_predicate_hybrid_search.py` already stubs
    rdflib / weaviate / neo4j / baml_client for exactly this module, and it documents a live trap in
    doing so (another test file installs a MagicMock `weaviate`, whose auto-generated `.classes`
    shadows the stub). A second hand-written copy would drift, and the copy that drifts is the one
    that stops loading the module for a reason nobody can see.

    **AND REUSING A HARNESS REUSES ITS GLOBAL EFFECTS.** Measured, not assumed: co-collecting the
    predicate seal with `tests/routing/test_a_vector_is_written_where_the_search_looks.py` reds two
    of that file's arms (`test_the_config_helper_returns_kwargs_not_a_value`,
    `test_the_fallback_form_is_reachable_on_the_pinned_range`) — both green when it runs alone. That
    is a PRE-EXISTING defect at HEAD, and importing the harness here reproduced it exactly, which is
    how it was found: `tests/routing/` alone went from 38 failures to 40 the moment these files were
    collected together, with the same 38 identities underneath.

    So the install is UNDONE. The footprint is derived by comparing `sys.modules` across
    `_install_stubs()` — the names it actually replaced or added, never a typed list that would go
    stale the next time the harness stubs one more package. Modules imported by `main.py` itself are
    outside the footprint by construction (it is taken before the load) and are left alone.

    `main.py` keeps working after the restore because its module globals already hold direct
    references to the stub objects; only the `sys.modules` table is put back.
    """
    spec = importlib.util.spec_from_file_location(
        "_predicate_stub_harness", str(_REPO / "tests" / "test_predicate_hybrid_search.py")
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)

    before = dict(sys.modules)
    try:
        # The install sits INSIDE the try whose `finally` puts the footprint back, so the restore
        # is visible in this file's own code (tests/test_the_stub_harness_puts_sys_modules_back.py).
        sys.modules.update(harness._stub_doubles())
        footprint = [k for k, v in sys.modules.items() if before.get(k) is not v]
        _FOOTPRINT.update({k: before.get(k, _ABSENT) for k in footprint})

        spec = importlib.util.spec_from_file_location(
            "ontology_main_migration_test",
            str(_REPO / "agent_fleet" / "ontology_service" / "main.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        # IN `finally`. A load that raises would otherwise leave the stubs installed for every file
        # collected after this one, and the failure they caused would be attributed to them.
        for name, prior in _FOOTPRINT.items():
            if prior is _ABSENT:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior


@pytest.fixture(scope="module")
def main():
    return _load_main()


# ── the store: one scripted collection, served to whichever arm asks ────────────────────────


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
    """Records every call, so the two arms can be compared on what they ASKED as well as on what
    they returned. Two arms agreeing on rows while sending different filters agree by luck."""

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


def _scripted():
    """The store's answer. FIVE ROWS, and each `definition` variant is a shape the projection must
    not change — chosen by mutation, not by taste.

    A first draft of the mesh projection wrote `r.get("definition", "") or ""`. That agrees with the
    incumbent on a present definition AND on an empty-string one, so a fixture carrying only those
    two calls the arms equal when they are not. It differs only on a **stored null**, where the
    incumbent's `.get("definition", "")` passes `None` straight through, and on a **missing key**,
    where both must produce `""`. Both rows are here so the equality arms can see the difference;
    the `None` reaching the wire was a pool-builder defect in its own right, reported rather than
    quietly repaired inside a migration that was supposed to change nothing.

    REPAIRED 2026-09-28, on both arms and outside that migration, with the value arms and the
    `_enum_description` arms further down this file. This sentence is updated rather than deleted
    because the fixture's SHAPE is still what it says: five `definition` variants chosen by mutation,
    and the stored-null row is now load-bearing for the repair as well as for the equality.

    A FRESH LIST PER CALL. Every `_Obj` is handed to both arms in turn, and a shared mutable fixture
    is how the second arm starts passing because the first consumed something.
    """
    return [
        _Obj({"uri": "mesh:ProductionCost", "label": "Production Cost",
              "definition": "cost accumulated against a lot"}, 0.66),
        _Obj({"uri": "mesh:LaborRate", "label": "Labor Rate",
              "definition": "rate applied to labor hours"}, 0.41),
        _Obj({"uri": "mesh:Lot", "label": "Lot", "definition": ""}, 0.20),
        _Obj({"uri": "mesh:StoredNull", "label": "Stored Null", "definition": None}, 0.11),
        _Obj({"uri": "mesh:NoDefinitionKey", "label": "No Definition Key"}, None),
    ]


def _pool(main, monkeypatch, row, *, on, client=None, embed_fails=False):
    client = client if client is not None else _Client(_scripted())
    counts = _wire(main, monkeypatch, client, embed_fails=embed_fails)
    monkeypatch.setattr(main, "ONTOLOGY_CLASS_POOL_VIA_MESH", on)
    rows, mode = asyncio.run(
        main.class_pool_with_mode(
            query=row["question"],
            domain=None,
            domains=list(row["domains"]),
            limit=10,
            user_email=row.get("user") or "",
        )
    )
    return rows, mode, counts, client


# ── THE RULING: the flag changes no rows ────────────────────────────────────────────────────


@pytest.mark.parametrize("row", _ROWS, ids=_IDS)
def test_the_FLAG_CHANGES_NO_ROWS_for_any_census_question(main, monkeypatch, row):
    """`ONTOLOGY_CLASS_POOL_VIA_MESH` on and off, one store, one census question, same rows.

    Row for row, key for key, including the score and including the None `description` a row with
    an empty definition yields — the projection was aligned expression for expression against the
    incumbent's for this reason, and the one place a draft differed (`or ""`) was found by this
    comparison rather than by reading.
    """
    off_rows, off_mode, _, off_client = _pool(main, monkeypatch, row, on=False)
    on_rows, on_mode, _, on_client = _pool(main, monkeypatch, row, on=True)

    assert off_rows == on_rows, (
        f"{row['id']}: the flag changed the pool.\n  off: {off_rows}\n  on:  {on_rows}"
    )
    assert off_mode == on_mode == "hybrid", (off_mode, on_mode)
    assert off_rows, "the fixture returned no rows — an empty pool compares equal to anything"


def _filter_shape_cases():
    """One case per FILTER SHAPE the pool builder can take, not the first N census rows.

    `sed -n` on either arm shows three branches — no domains (`filters = None`), exactly one
    (`by_property("domain").equal`), more than one (`.contains_any`) — and **all 20 census rows
    carry exactly one domain**, so the census population reaches ONE of the three. Parametrizing
    over `_ROWS[:3]` would have run the same branch three times and read as coverage.

    So the census supplies the real single-domain case (first by id, for determinism, since all 20
    are the same shape), and the other two are SYNTHETIC and labelled as such: no question anyone
    asks reaches them today, and a branch nothing compares is a branch where the arms may already
    disagree. Each case's id says which branch it is buying.
    """
    single = min(_ROWS, key=lambda r: r["id"])
    return [
        pytest.param(single, id=f"one-domain-census[{single['id']}]"),
        pytest.param(
            dict(single, id="synthetic-two-domains", domains=["PRODUCTION_COST", "SUPPLY_CHAIN"]),
            id="two-domains-SYNTHETIC-contains_any",
        ),
        pytest.param(
            dict(single, id="synthetic-no-domains", domains=[]),
            id="no-domains-SYNTHETIC-unfiltered",
        ),
    ]


@pytest.mark.parametrize("row", _filter_shape_cases())
def test_the_two_arms_also_send_the_SAME_QUERY(main, monkeypatch, row):
    """Same rows out is not the same question in. Two arms that agree on the pool while scoping
    differently agree only because the fixture is small — the domain filter is where a migration
    silently widens or narrows what a caller may see, and it is the ADR-0025 boundary.
    """
    _, _, _, off_client = _pool(main, monkeypatch, row, on=False)
    _, _, _, on_client = _pool(main, monkeypatch, row, on=True)

    def _shape(calls):
        out = []
        for c in calls:
            d = dict(c)
            md = d.pop("return_metadata", None)
            # The metadata objects are different INSTANCES by construction; what must match is
            # what was asked for.
            d["return_metadata_kw"] = getattr(md, "kw", None)
            d["vector"] = "present" if d.get("vector") else d.get("vector")
            out.append(d)
        return out

    assert _shape(off_client.calls) == _shape(on_client.calls), (
        f"{row['id']}: the arms issued different queries.\n"
        f"  off: {_shape(off_client.calls)}\n  on:  {_shape(on_client.calls)}"
    )


def test_the_FLAG_SELECTS_A_DIFFERENT_CODE_PATH(main, monkeypatch):
    """THE CONTROL FOR EVERY EQUALITY ARM ABOVE, and without it they are decorations.

    A mesh arm that fell through to the incumbent, or a flag read at import and never re-read,
    would make every comparison above compare one path with itself: identical rows, permanently
    green, nothing migrated. The two arms enter the embedding through DIFFERENT functions —
    `embed_query` for the incumbent, `observe_query_embedding` for the mesh arm, which needs the
    served model identity for its marker check — so the counters say which one ran.
    """
    row = _ROWS[0]
    _, _, off_counts, _ = _pool(main, monkeypatch, row, on=False)
    _, _, on_counts, _ = _pool(main, monkeypatch, row, on=True)

    assert off_counts == {"embed_query": 1, "observe_query_embedding": 0}, off_counts
    assert on_counts == {"embed_query": 0, "observe_query_embedding": 1}, on_counts


# ── THE MODE, and the degradation it exists to announce ─────────────────────────────────────


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_the_mode_reports_BM25_when_the_vector_arm_contributed_nothing(main, monkeypatch, on):
    """The packet's second seal. A degraded retrieval is a MARKED success, never an unmarked one:
    the fleet ran sixty-seven days BM25-only with nothing in any result saying so.

    Both arms, one vocabulary. A field only one arm populated would make the flag the only way to
    learn the mode.
    """
    rows, mode, _, client = _pool(main, monkeypatch, _ROWS[0], on=on, embed_fails=True)
    assert mode == "bm25", f"a failed embedding was reported as {mode!r}"
    assert rows, "the degraded path must still answer — BM25 is a degradation, not an outage"
    assert [c["kind"] for c in client.calls] == ["bm25"], client.calls


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_the_HEALTHY_mode_is_hybrid_on_both_arms(main, monkeypatch, on):
    """Its companion, differing in exactly what the guard decides on: the embedding SUCCEEDS. If
    `mode` were hardcoded to "bm25" the arm above would pass on both arms and mean nothing."""
    rows, mode, _, client = _pool(main, monkeypatch, _ROWS[0], on=on)
    assert mode == "hybrid", mode
    assert [c["kind"] for c in client.calls] == ["hybrid"], client.calls
    assert rows


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_NO_RETRIEVAL_ATTEMPTED_is_a_third_state_and_not_bm25(main, monkeypatch, on):
    """An absent collection is not a degraded search. `/resolve` reads an empty pool as a cold
    start and answers from the graph, which is correct here — what must not happen is that the
    result claims a retrieval mode for a retrieval that never ran."""
    rows, mode, _, _ = _pool(
        main, monkeypatch, _ROWS[0], on=on, client=_Client(_scripted(), exists=False)
    )
    assert rows == []
    assert mode is None, f"no retrieval was attempted, but the mode says {mode!r}"


# ── THE REFUSAL, on both arms: the ruling this pilot must not weaken ─────────────────────────


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_a_MID_QUERY_FAILURE_is_a_503_on_both_arms(main, monkeypatch, on):
    """RULED 2026-09-14, and the most important parity in this file. An empty list here would reach
    `/resolve`, print "WEAVIATE COLD START DETECTED" and answer from the MAINTENANCE ontology — a
    confident wrong-domain answer under a banner naming a false diagnosis.

    The two arms reach it differently: the incumbent from its own `except`, the mesh arm from
    `MeshResult.failed`, whose `outcome` carries the distinction the bare list cannot. Same 503.
    """
    with pytest.raises(Exception) as exc:
        _pool(main, monkeypatch, _ROWS[0], on=on, client=_Client(_scripted(), boom=True))
    assert getattr(exc.value, "status_code", None) == 503, repr(exc.value)


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_an_EMPTY_STORE_is_not_a_failure_on_either_arm(main, monkeypatch, on):
    """The companion to the arm above, and the reason it is not over-strict: a store that answers
    with zero objects still means cold start, still returns an empty pool, and must NOT refuse.
    Collapsing these two would take routing down every time a domain has no classes yet."""
    rows, mode, _, _ = _pool(main, monkeypatch, _ROWS[0], on=on, client=_Client([]))
    assert rows == []
    assert mode == "hybrid", (
        f"the search ran and matched nothing, so the mode is what it searched WITH, not None "
        f"(got {mode!r})"
    )


# ── THE DIFFS, measured rather than smoothed over ───────────────────────────────────────────


def test_THE_KNOWN_DIFF_a_blank_user_email_is_refused_by_the_mesh_arm_only(main, monkeypatch):
    """THE ONE BEHAVIOURAL DIFFERENCE THE FLAG INTRODUCES, asserted so it is reviewed rather than
    discovered.

    `ResolveRequest.user_email` defaults to `""`, and the incumbent has never read it. The mesh arm
    attributes every read to a person and refuses a blank subject — provenance nobody can be asked
    about. So a caller that reaches `/resolve` without threading identity gets a 400 with the flag
    on and a pool with it off. That is a REAL difference in what the route accepts, it is the
    reason the default stays off, and it is exactly what the migration report has to say out loud.
    """
    row = dict(_ROWS[0], user="")
    rows, mode, _, _ = _pool(main, monkeypatch, row, on=False)
    assert rows, "the incumbent arm should be indifferent to a blank user_email"

    with pytest.raises(Exception) as exc:
        _pool(main, monkeypatch, row, on=True)
    assert getattr(exc.value, "status_code", None) == 400, repr(exc.value)
    assert "user_email" in str(getattr(exc.value, "detail", "")), exc.value


def test_THE_KNOWN_DIFF_a_uri_less_row_raises_on_one_arm_and_not_the_other(main, monkeypatch):
    """The second measured difference, and the one that would otherwise be found in production.

    The incumbent projects `obj.properties["uri"]` and RAISES on a row without one — landing in its
    own handler, which turns it into the 503 above. The mesh arm projects `.get("uri")` and emits a
    None-uri candidate instead. Neither is obviously right (a uri-less OntologyClass row has never
    been observed), so the behaviour is PINNED here rather than aligned by guess: whichever way it
    is later settled, this arm reds and names the decision.
    """
    bad = _Client([_Obj({"label": "no uri here", "definition": "x"}, 0.5)])
    with pytest.raises(Exception) as exc:
        _pool(main, monkeypatch, _ROWS[0], on=False, client=bad)
    assert getattr(exc.value, "status_code", None) == 503, repr(exc.value)

    bad2 = _Client([_Obj({"label": "no uri here", "definition": "x"}, 0.5)])
    rows, _mode, _, _ = _pool(main, monkeypatch, _ROWS[0], on=True, client=bad2)
    assert rows == [{"uri": None, "label": "no uri here", "description": "x", "score": 0.5}], rows


# ── the harness's own footprint, put back ───────────────────────────────────────────────────


def test_the_STUB_INSTALL_LEAVES_NO_FOOTPRINT_in_sys_modules(main):
    """THIS FILE MUST NOT DECIDE ANOTHER FILE'S RESULT, and that is measured rather than intended.

    The reused harness replaces real packages in `sys.modules` (`weaviate` and its `classes`
    submodule, `rdflib`, `neo4j`, `baml_client`). Left installed, every file collected after this one
    imports the stub instead of the package — which is a defect that reads as the LATER file's, in a
    suite run nobody will bisect. It is the reason `tests/routing/` showed 40 failures beside these
    files and 38 alone.

    Takes the `main` fixture so the load has definitely happened: asserting the table is clean before
    anything touched it is a green that means nothing.
    """
    assert _FOOTPRINT, (
        "the footprint is empty, so either the harness stubbed nothing or it was derived after the "
        "install — and this arm would then pass without the restore existing at all"
    )
    for name, prior in _FOOTPRINT.items():
        if prior is _ABSENT:
            assert name not in sys.modules, f"{name} was absent before the install and is still set"
        else:
            assert sys.modules.get(name) is prior, f"{name} still points at the stub"


def test_the_FOOTPRINT_names_the_packages_the_module_under_test_actually_needs(main):
    """The companion. A restore over an empty or accidental footprint is not a restore, and the arm
    above cannot tell the difference — so this one says WHAT was restored, derived from the stubbed
    names rather than from a list typed here.

    `weaviate` is the one that matters: it is the package both pool arms call through, so if it is
    not in the footprint the stub was never installed and every equality assertion in this file ran
    against something else.
    """
    roots = {n.split(".")[0] for n in _FOOTPRINT}
    assert "weaviate" in roots, sorted(roots)
    assert any(n.startswith("weaviate.classes") or n == "weaviate.classes" for n in _FOOTPRINT), (
        f"`wvc.query.Filter` and `wvc.query.MetadataQuery` are read off the `classes` submodule, "
        f"and it is not in the footprint: {sorted(_FOOTPRINT)}"
    )


# ── THE POOL-BUILDER DEFECT, now repaired: a stored null is not a description ───────────────
#
# §2.3 of the pilot report filed this and deliberately did not fix it: the mesh projection was
# aligned to the incumbent's `.get("definition", "")` EXPRESSION FOR EXPRESSION, including the
# `None` a stored-null property yields, because row identity was the thing the flag's seal
# asserted and a repair smuggled into a migration is the one change no arm above could see.
#
# It is now outside that migration and repaired on BOTH arms at once, so the equality arms stay
# green and cannot see the fix either -- which is exactly why these arms assert the VALUE. The
# fixture needs nothing new: `mesh:StoredNull` and `mesh:NoDefinitionKey` were put there by the
# mutation that found the draft's `or ""`, and they are the two rows that separate the readings.
#
# THAT CLAIM IS MEASURED, NOT ASSUMED, AND THE NUMBERS RUN THE WRONG WAY ROUND. Reverting ONE arm of
# the repair reds 22: the 2 value arms for that side, plus all 20 parametrizations of
# `test_the_FLAG_CHANGES_NO_ROWS_for_any_census_question`, because a one-sided change is a parity
# difference and parity is what that arm is for. Reverting BOTH -- the state this repair replaced --
# leaves parity SILENT and reds exactly 4, the value arms below. A defect sitting identically on both
# sides of an equality seal is invisible to it however many ways it is parametrized.


def _by_uri(rows: list[dict], uri: str) -> dict:
    hit = [r for r in rows if r.get("uri") == uri]
    assert len(hit) == 1, f"expected exactly one {uri} row in the pool, got {len(hit)}: {rows!r}"
    return hit[0]


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_a_STORED_NULL_definition_reaches_the_wire_as_a_STRING(main, monkeypatch, on):
    """`{"definition": None}` in the store must not become `description=None` on the wire.

    A `.get("definition", "")` does not defend against this: the default applies to a MISSING key,
    never to a key whose stored value is null. The `None` then reaches an f-string eight frames
    later and renders the word "None" into a BAML enum description -- a defect that never raises,
    never logs, and is visible only as a class the model was told is called "Stored Null: None".
    """
    rows, _mode, _counts, _client = _pool(main, monkeypatch, _ROWS[0], on=on)
    row = _by_uri(rows, "mesh:StoredNull")
    assert row["description"] is not None, (
        f"a stored-null definition reached the wire as None on the "
        f"{'mesh' if on else 'incumbent'} arm: {row!r}"
    )
    assert row["description"] == ""


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_a_MISSING_definition_key_still_reaches_the_wire_as_a_STRING(main, monkeypatch, on):
    """The neighbour that ALREADY worked, and the control for the repair above.

    It shares the arm's population and its gate and differs only in what the guard decides on -- a
    key that is absent rather than a key whose value is null. A repair that broke it would mean the
    fix had changed the defaulting rule rather than the null handling.
    """
    rows, _mode, _counts, _client = _pool(main, monkeypatch, _ROWS[0], on=on)
    assert _by_uri(rows, "mesh:NoDefinitionKey")["description"] == ""


@pytest.mark.parametrize("on", [False, True], ids=["incumbent", "mesh"])
def test_NO_row_in_the_pool_carries_a_NON_STRING_description(main, monkeypatch, on):
    """The class, not the instance that bit us. A defence aimed only at `mesh:StoredNull` would be
    a defence of one fixture row; the pool builder's contract is that `description` is a string for
    EVERY row it emits, whatever the store held."""
    rows, _mode, _counts, _client = _pool(main, monkeypatch, _ROWS[0], on=on)
    assert rows, "an empty pool satisfies every claim below vacuously"
    offenders = [r for r in rows if not isinstance(r.get("description"), str)]
    assert not offenders, f"these rows left the pool builder with a non-string description: {offenders!r}"


# ── AND THE CONSUMER, because "" is not the end of it ───────────────────────────────────────


def test_the_ENUM_DESCRIPTION_omits_the_separator_when_there_is_no_definition(main):
    """Repairing the builder turns `"Stored Null: None"` into `"Stored Null: "`, which is the SAME
    defect one character shorter: filler in a BAML prompt.

    This fleet already ruled on it, at `_get_active_ontology_classes`, where an absent definition
    renders as NOTHING and the comment gives the reason -- 'No definition available.' repeated
    across hundreds of classes is pure token noise and teaches the model to pattern-match the
    filler instead of the names. The enum builder is the same question and gets the same answer.
    """
    assert main._enum_description("Stored Null", "") == "Stored Null"
    assert main._enum_description("Stored Null", None) == "Stored Null"
    assert main._enum_description("Stored Null", "   ") == "Stored Null"


def test_the_ENUM_DESCRIPTION_keeps_both_when_there_IS_a_definition(main):
    """The accepting side. An over-strict helper that dropped every definition would satisfy the
    arm above and quietly strip the ontology's meaning out of the prompt."""
    assert (
        main._enum_description("Production Cost", "cost accumulated against a lot")
        == "Production Cost: cost accumulated against a lot"
    )


def test_the_ENUM_DESCRIPTION_HELPER_has_no_second_implementation(main):
    """A census, because this rendering had TWO copies before the helper existed and a third would
    be written the same way. Derived from the AST: no f-string in the module may join a label and a
    description with `": "` outside the helper itself.

    ITS POPULATION IS DELIBERATELY WIDER THAN THE NEXT ARM'S, AND THE ASYMMETRY IS MEASURED. The next
    arm requires the helper only at `tb.OntologyClass` receivers, because that is where a label and a
    definition are known to travel together. This one bans the SHAPE module-wide, wherever it appears
    and on whatever enum -- a mutant that gave `tb.Predicate` a `f"{label}: {description}"` builder
    reds here and nowhere else, which is the intended reading: a second enum growing that pair is the
    same defect arriving somewhere new, and the ruling it would diverge from is not enum-specific.
    """
    import ast

    src = Path(main.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    helper = [
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_enum_description"
    ]
    assert len(helper) == 1, "expected exactly one `_enum_description` definition"
    helper_range = range(helper[0].lineno, (helper[0].end_lineno or helper[0].lineno) + 1)

    copies = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or node.lineno in helper_range:
            continue
        text = ast.unparse(node)
        if "label" in text and "description" in text and ": " in text:
            copies.append((node.lineno, text))
    assert not copies, (
        "a label/description rendering was written again instead of calling `_enum_description`; "
        f"the ruling it is about to diverge from lives at `_get_active_ontology_classes`: {copies!r}"
    )


def test_EVERY_enum_value_description_is_BUILT_BY_the_helper(main):
    """The other direction. The census above is blind to a call site that renders the pair some way
    that is not an f-string, so this one fixes the population from the consumer's end.

    THE POPULATION IS THE `OntologyClass` ENUM AND ONLY IT, DERIVED FROM THE RECEIVER. A first draft
    took every `add_value(...).description(...)` in the module and red on six sites that are not this
    defect at all: `tb.Predicate` (a registered predicate's own sentence, and the abstain option's
    prose), `tb.PersonaTarget` and `tb.Domain` (legacy prompt tables), `tb.Intent`. None of them
    carries a label and a definition, so a label/definition helper is the wrong shape for them and a
    red there would have been a false one. The narrowing is by the enum's TYPE rather than by a list
    of line numbers, so a third `OntologyClass` builder is caught and a fourth `Predicate` one is
    not.
    """
    import ast

    src = Path(main.__file__).read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "description"
        and isinstance(node.func.value, ast.Call)
        and isinstance(node.func.value.func, ast.Attribute)
        and node.func.value.func.attr == "add_value"
        and isinstance(node.func.value.func.value, ast.Attribute)
        and node.func.value.func.value.attr == "OntologyClass"
    ]
    assert len(calls) >= 2, (
        f"expected at least the two known OntologyClass enum builders, found {len(calls)} -- if the "
        f"enum was renamed, this census is now looking at nothing"
    )
    strays = [
        (c.lineno, ast.unparse(c.args[0]) if c.args else "<no argument>")
        for c in calls
        if not (
            c.args
            and isinstance(c.args[0], ast.Call)
            and isinstance(c.args[0].func, ast.Name)
            and c.args[0].func.id == "_enum_description"
        )
    ]
    assert not strays, f"these enum descriptions bypass `_enum_description`: {strays!r}"


def test_the_ENUM_DESCRIPTION_handles_an_ABSENT_LABEL_the_same_way(main):
    """The sibling written in the same act, which is the hardest home to find.

    `label` is read with `.get` one line from where `definition` is, out of the same store rows, so
    it can be a stored null for exactly the same reason -- and a helper that guarded only the
    definition would render `"None: cost accumulated against a lot"`, which is the original defect
    with the fields swapped. Fixing one field and calling the class handled is how this defect got a
    second generation in the first place.
    """
    assert main._enum_description(None, "cost accumulated against a lot") == "cost accumulated against a lot"
    assert main._enum_description("", "rate applied to labor hours") == "rate applied to labor hours"
    assert main._enum_description(None, None) == ""
    assert main._enum_description("  ", "  ") == ""
