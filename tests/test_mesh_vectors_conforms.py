"""The fleet's `MeshVectors` implementation (`agent_fleet/utils/mesh_vectors.py`), against the SDK's own conformance suite and the
properties the suite cannot reach.

**RUN THE SDK'S ARM FIRST AND DO NOT REIMPLEMENT IT.** `check_offline` asserts what the contract
requires of every implementation — a service identity refused, every operation returning
`MeshResult`, only declared modes emitted — and it refuses an empty operation list, because *a
conformance run over zero operations is a green that proves nothing*. What this file adds is the
part specific to THIS implementation: the marker's three states, the degradation marker, and the
domain filter's two shapes.

**THE FIXTURES COME IN PAIRS ON PURPOSE.** The rule the SDK exports as
`assert_fixture_discriminates` is the one this lane kept paying for: *a fixture is a legal input
that happens to make two behaviours identical.* An empty store cannot tell answered-nothing from
failed-silently; a matching marker cannot tell a real check from a vacuous self-comparison. So
every arm below that asserts a refusal has a companion asserting the non-refusal, and they are
built to differ in exactly the dimension under test.

Run: uv run --frozen pytest tests/test_mesh_vectors_conforms.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from iagent_mesh.conformance import check_offline  # noqa: E402
from iagent_mesh.interfaces import Initiator, ServiceIdentityRefused  # noqa: E402
from iagent_mesh.results import MeshResult  # noqa: E402

from agent_fleet.utils.mesh_vectors import (  # noqa: E402
    MODES,
    MarkerMismatch,
    WeaviateVectors,
)

PERSON = Initiator(subject="alice@example.com", kind="person")
SERVICE = Initiator(subject="svc:indexer", kind="service")

_MODEL, _DIM = "nomic-embed-text", 768


class _Obs:
    """What `observe_query_embedding` returns — served identity and vector from one response."""

    def __init__(self, served=_MODEL, dim=_DIM):
        self.served, self.requested, self.dimension = served, _MODEL, dim
        self.vector = tuple([0.0] * dim)


class _Query:
    def __init__(self, rows, scores=None):
        self._rows = rows
        # THE SCORES LIVE BESIDE THE PROPERTIES, because that is where the driver puts them: a
        # Weaviate object carries `properties` and `metadata` as separate attributes, and a double
        # that folded the score into the properties dict would make the implementation's own
        # property-collision branch unreachable — the seal would be measuring the double.
        # `None` means "this object has no metadata at all", the scoreless-config shape.
        self._scores = list(scores) if scores is not None else None
        self.last = None

    def _resp(self, **kw):
        self.last = kw
        # THE DOUBLE WITHHOLDS WHAT WAS NOT ASKED FOR, and this line is load-bearing. It did not,
        # at first: it attached metadata unconditionally, and the two mutants that DELETE
        # `return_metadata=` from the implementation's queries both stayed GREEN — the double was
        # the only thing supplying the property under test, so the whole set of score arms was
        # measuring the fixture. A double that answers a question the driver would have refused
        # turns every arm above it into a decoration.
        asked = kw.get("return_metadata") is not None
        objs = []
        for i, r in enumerate(self._rows):
            if self._scores is None or not asked:
                md = None
            else:
                s = self._scores[i] if i < len(self._scores) else None
                md = type("M", (), {"score": s})
            objs.append(type("O", (), {"properties": r, "metadata": md}))
        return type("R", (), {"objects": objs})

    def hybrid(self, **kw):
        return self._resp(kind="hybrid", **kw)

    def near_vector(self, **kw):
        # THE DRIVER'S NEAR_VECTOR SHAPE, not a convenient one: `score` comes back 0.0 (NOT None)
        # whatever was asked, and certainty/distance arrive only when the query asked for them.
        # Engine W banked the 0.0 on 2026-06-28 (real hits at MATCH=0%), so a reader that took
        # `score` here would read every hit as unranked — and this double makes that visible.
        self.last = dict(kind="near_vector", **kw)
        rm = kw.get("return_metadata")
        asked = getattr(rm, "kw", {}) if rm is not None else {}
        objs = []
        for i, r in enumerate(self._rows):
            s = None if self._scores is None or i >= len(self._scores) else self._scores[i]
            if s is None or rm is None:
                md = None
            else:
                md = type("M", (), {
                    "score": 0.0,
                    "certainty": s if asked.get("certainty") else None,
                    "distance": (1.0 - s) * 2 if asked.get("distance") else None,
                })
            objs.append(type("O", (), {"properties": r, "metadata": md}))
        return type("R", (), {"objects": objs})

    def bm25(self, **kw):
        return self._resp(kind="bm25", **kw)


class _Meta:
    """The injected `MetadataQuery`-alike. Records that it was asked for, and for WHAT."""

    calls: list = []

    def __init__(self, **kw):
        type(self).calls.append(kw)
        self.kw = kw


class _Collections:
    def __init__(self, rows, present=True, scores=None):
        self._q, self._present = _Query(rows, scores), present

    def exists(self, _name):
        return self._present

    def get(self, _name):
        return type("H", (), {"query": self._q})


class _Client:
    def __init__(self, rows=(), present=True, scores=None):
        self.collections = _Collections(list(rows), present, scores)


class _Filters:
    """Records what was built instead of building it — the rule is which branches exist."""

    calls: list = []

    @classmethod
    def by_property(cls, name, length=False):
        cls.calls.append(("by_property", name, length))
        return type(
            "P", (), {
                "equal": staticmethod(lambda v: ("equal", name, v)),
                "contains_any": staticmethod(lambda v: ("contains_any", name, tuple(v))),
            },
        )

    @classmethod
    def any_of(cls, parts):
        cls.calls.append(("any_of", len(parts)))
        return ("any_of", tuple(parts))

    @classmethod
    def all_of(cls, parts):
        cls.calls.append(("all_of", len(parts)))
        return ("all_of", tuple(parts))


def _impl(*, rows=(), present=True, marker=None, embed=None, oldest=None, report=None,
          scores=None):
    return WeaviateVectors(
        client=_Client(rows, present, scores),
        embed=embed or (lambda _t: _Obs()),
        filters=_Filters,
        metadata=_Meta,
        fetch_marker=(lambda _c: marker),
        oldest_object_unix_ms=(lambda _c: oldest),
        report=report,
    )


# ── the SDK's own arm ───────────────────────────────────────────────────────────────────────


def test_the_SDK_conformance_suite_passes():
    """THE CONTRACT'S OWN CHECK. If this and the file below ever disagree, this one is right."""
    impl = _impl(rows=[{"uri": "x"}])
    check_offline(
        impl,
        operations=[
            ("nominate", lambda i: impl.nominate(i, collection="OntologyClass", text="q")),
            ("collection_present", lambda i: impl.collection_present(i, collection="Predicate")),
        ],
        declared_modes=MODES,
    )


def test_a_service_identity_is_refused_by_BOTH_operations():
    """Explicit, because `check_offline` would also pass an implementation that refused for the
    wrong reason — and because the refusal must not depend on parsing the subject."""
    impl = _impl(rows=[{"uri": "x"}])
    for call in (
        lambda: impl.nominate(SERVICE, collection="OntologyClass", text="q"),
        lambda: impl.collection_present(SERVICE, collection="OntologyClass"),
    ):
        with pytest.raises(ServiceIdentityRefused):
            call()
    # THE CONTROL: a person is not refused, or "refuses a service" is satisfied by refusing all.
    assert impl.nominate(PERSON, collection="OntologyClass", text="q").outcome == "answered"


# ── whether, and how ────────────────────────────────────────────────────────────────────────


def test_an_empty_result_and_a_FAILURE_are_different_outcomes():
    """The pair that cannot be told apart by a list. Both fixtures are legal inputs; they differ
    only in whether the substrate answered."""
    answered_nothing = _impl(rows=[])
    assert answered_nothing.nominate(PERSON, collection="OntologyClass", text="q").outcome == "empty"

    class _Boom(_Client):
        def __init__(self):
            super().__init__()
            self.collections.get = lambda _n: (_ for _ in ()).throw(RuntimeError("weaviate down"))

    failing = WeaviateVectors(
        client=_Boom(), embed=lambda _t: _Obs(), filters=_Filters, metadata=_Meta,
        fetch_marker=lambda _c: None
    )
    out = failing.nominate(PERSON, collection="OntologyClass", text="q")
    assert out.outcome == "failed"
    assert "weaviate down" in (out.detail or "")


def test_a_DEGRADED_retrieval_is_marked_bm25_and_still_answers():
    """Sixty-seven days of BM25-only with nothing in any result saying so is what this asserts
    against. The degradation must survive into the RETURN, not a log line."""
    def _explode(_t):
        raise RuntimeError("embedding gateway down")

    out = _impl(rows=[{"uri": "x"}], embed=_explode).nominate(
        PERSON, collection="OntologyClass", text="q"
    )
    assert out.outcome == "answered" and out.mode == "bm25"


def test_the_HEALTHY_path_is_marked_hybrid():
    """The control for the arm above: if `mode` were hardcoded to bm25 both would pass."""
    out = _impl(rows=[{"uri": "x"}]).nominate(PERSON, collection="OntologyClass", text="q")
    assert out.mode == "hybrid"


# ── the marker's three states ───────────────────────────────────────────────────────────────


def _marker(model=_MODEL, dim=_DIM, version=None):
    return {
        "collection": "OntologyClass", "model": model, "version": version,
        "dimension": dim, "written_by": "doc-tools", "collection_created_unix_ms": 1,
    }


def test_a_MATCHING_marker_opens():
    out = _impl(rows=[{"uri": "x"}], marker=_marker()).nominate(
        PERSON, collection="OntologyClass", text="q"
    )
    assert out.outcome == "answered"


def test_a_MISMATCHING_marker_REFUSES_and_names_BOTH():
    """A refusal that names one side sends the reader to the wrong repo."""
    out = _impl(rows=[{"uri": "x"}], marker=_marker(model="other-model")).nominate(
        PERSON, collection="OntologyClass", text="q"
    )
    assert out.outcome == "failed"
    assert "other-model" in (out.detail or "") and _MODEL in (out.detail or "")


def test_an_ABSENT_marker_OPENS_and_reports_the_gap_ONCE():
    """THE STATE THAT BITES. Readers land before writers, so absent is the normal early case —
    and silently treating it as matching is the vacuous self-comparison the property exists to
    prevent. It must open, and it must say so."""
    said: list[str] = []
    impl = _impl(rows=[{"uri": "x"}], marker=None, report=said.append)
    assert impl.nominate(PERSON, collection="OntologyClass", text="q").outcome == "answered"
    assert impl.nominate(PERSON, collection="OntologyClass", text="q").outcome == "answered"
    gaps = [m for m in said if "GAP" in m]
    assert len(gaps) == 1, f"the gap must be reported ONCE per collection, got {len(gaps)}"


def test_a_DIMENSION_disagreement_refuses_even_when_the_model_matches():
    """Two witnesses for one field: the marker's claim and the vector we produced."""
    out = _impl(rows=[{"uri": "x"}], marker=_marker(dim=1024)).nominate(
        PERSON, collection="OntologyClass", text="q"
    )
    assert out.outcome == "failed" and "1024" in (out.detail or "")


def test_the_embedding_model_is_the_SERVED_identity_not_the_constant():
    impl = _impl(rows=[{"uri": "x"}], embed=lambda _t: _Obs(served="actually-served"))
    impl.nominate(PERSON, collection="OntologyClass", text="q")
    assert impl.embedding_model == "actually-served"


# ── the domain filter's two shapes ──────────────────────────────────────────────────────────


def test_the_PREDICATE_filter_keeps_domain_agnostic_rows_and_the_CLASS_filter_does_not():
    """ADR-0009's OR-branch is load-bearing — 27 of 129 predicates carry no domains — and the
    class collection needs none, because all 21,547 rows carry one. One rule, two property shapes,
    and asserting them together is what stops a future 'simplification' collapsing them."""
    _Filters.calls = []
    _impl(rows=[]).nominate(PERSON, collection="Predicate", text="q", domains=["MAINTENANCE"])
    assert ("any_of", 2) in _Filters.calls, "the predicate side lost its domain-agnostic branch"
    assert ("by_property", "domains", True) in _Filters.calls, "the length filter is the branch"

    _Filters.calls = []
    _impl(rows=[]).nominate(PERSON, collection="OntologyClass", text="q", domains=["MAINTENANCE"])
    assert ("any_of", 2) not in _Filters.calls, "the class side has no agnostic branch to add"


def test_an_UNSCOPED_call_applies_no_filter_on_either_collection():
    for collection in ("Predicate", "OntologyClass"):
        impl = _impl(rows=[])
        impl.nominate(PERSON, collection=collection, text="q", domains=())
        assert impl._client.collections._q.last["filters"] is None


# ── the environment must be the declaration ─────────────────────────────────────────────────


def test_the_IMPORTED_SDK_IS_THE_PINNED_ARTIFACT_not_a_working_tree():
    """FOUND THE HARD WAY, 2026-09-15: this suite was validating another lane's UNCOMMITTED code.

    `iagent_mesh` resolves through an editable install — `_editable_impl_iagent_mesh.pth` in
    site-packages pointing at a git checkout somebody else is actively editing — so a green here
    proved something about their working tree at that instant, not about the artifact this repo
    pins. It surfaced as a `DeprecationWarning` naming a function that exists in **no commit, no
    branch and no tag**: only in their unsaved edits.

    **THE CHECK IS NOT "an editable install exists".** An editable checkout sitting exactly at the
    pinned tag, clean, IS the pinned artifact and there is nothing to report — failing on that
    would be a seal firing on a healthy environment, which is how seals get deleted. What makes a
    green meaningless is the imported code DIFFERING from the declaration, and that is what this
    asserts: HEAD at the pin, and `iagent_mesh/` clean.

    Red locally where it is true, green in CI where the pin is installed. A true red beats a false
    green — the only arm in this file about the RUN rather than the code.
    """
    import subprocess

    import iagent_mesh

    where = Path(iagent_mesh.__file__).resolve().parent.parent
    if not (where / ".git").exists():
        return  # installed from the pin, nothing to check

    pin_text = (_REPO / "agent_fleet" / "ontology_service" / "pyproject.toml").read_text("utf-8")
    pinned = next(
        (ln.rsplit("@", 1)[-1].strip().strip('",') for ln in pin_text.splitlines()
         if "iagent-mesh @" in ln),
        None,
    )
    assert pinned, "could not read the iagent-mesh pin out of engine-o's pyproject"

    def _git(*a):
        return subprocess.run(
            ["git", "-C", str(where), *a], capture_output=True, text=True, timeout=60
        ).stdout.strip()

    head, at_pin = _git("rev-parse", "HEAD"), _git("rev-parse", f"{pinned}^{{commit}}")
    dirty = _git("status", "--porcelain", "--", "iagent_mesh")

    problems = []
    if head != at_pin:
        problems.append(f"HEAD {head[:12]} is not the pinned tag {pinned} ({at_pin[:12]})")
    if dirty:
        problems.append("iagent_mesh/ has uncommitted changes: " + dirty)
    assert not problems, (
        f"iagent_mesh is imported from the WORKING TREE at {where}, and it does not match "
        f"this repo's declaration ({pinned}): " + "; ".join(problems) + ". Every green in "
        "this file is a statement about that tree, not about the pinned artifact. Stash or "
        "commit the edits, check out the pin, or install it non-editable."
    )


def test_the_predicate_this_module_COMPILES_AGAINST_exists():
    """MOVED 2026-09-17 to `marker_predates_collection`, the name introduced at `v0.9.2`.

    (Said as WHERE rather than as "the fleet pin": the pin moved to v0.9.3 on 2026-09-19 and
    the rename stayed where it was. A version named as the current pin goes stale on the next
    one, silently, in a file nobody edits.)

    This arm previously pinned `marker_is_stale` as the name compiled against, so that the day it
    went the failure would say which name to move to. It went the other way — the replacement
    arrived first and this lane was the live consumer the expand/contract interval existed for, so
    the move is deliberate rather than forced.

    **IT NOW ASSERTS THE OLD NAME IS NOT WHAT WE CALL**, which is the half that keeps the alias
    contractable: if anything here drifts back onto `marker_is_stale`, the SDK cannot remove it.
    """
    import agent_fleet.utils.mesh_vectors as mv
    from iagent_mesh.interfaces import marker_predates_collection

    assert callable(marker_predates_collection)

    src = (_REPO / "agent_fleet" / "utils" / "mesh_vectors.py").read_text("utf-8")
    tree = __import__("ast").parse(src)
    called = {
        n.func.id
        for n in __import__("ast").walk(tree)
        if isinstance(n, __import__("ast").Call) and isinstance(n.func, __import__("ast").Name)
    }
    assert "marker_predates_collection" in called, "the module no longer calls the current name"
    assert "marker_is_stale" not in called, (
        "this module is back on the deprecated alias — the SDK cannot contract it while a caller "
        "remains, and this lane is the caller the interval was opened for"
    )


# ── the retrieval score: asked for, attached, and never overwriting the store's own ─────────


def _explode(_t):
    raise RuntimeError("embedding gateway down")


#: EVERY QUERY SHAPE THE READER CAN ISSUE, derived from its two inputs: the REQUEST (`mode=`) and
#: whether the embed answered. Four cells, and each names the query it must reach, what it must
#: ask the driver for, what it must REPORT, and the score that must land on the row. The table
#: replaces an arm that said "score=True on every search": true of hybrid and bm25, and false of
#: near_vector, whose `score` is 0.0 whatever is asked.
_SHAPES = [
    # request,       embed,     query kind,     metadata asked,                         reported
    ("hybrid",       None,      "hybrid",       {"score": True},                        "hybrid"),
    ("vector_only",  None,      "near_vector",  {"certainty": True, "distance": True},  "hybrid"),
    ("hybrid",       _explode,  "bm25",         {"score": True},                        "bm25"),
    ("vector_only",  _explode,  "bm25",         {"score": True},                        "bm25"),
]


@pytest.mark.parametrize(
    "request_mode,embed,kind,asked,reported", _SHAPES,
    ids=[f"{r}-{'embed' if e is None else 'no-embed'}" for r, e, *_ in _SHAPES],
)
def test_EVERY_query_shape_requests_its_metadata_and_lands_the_score(
    request_mode, embed, kind, asked, reported
):
    """A score never asked for arrives as None from a perfectly healthy cluster, so this asserts the
    REQUEST (built AND sent), then the row.

    BUILDING THE REQUEST IS NOT MAKING IT: asserting only on `_Meta.calls` once left both
    delete-the-kwarg mutants green. What the driver reads is the kwarg on the query it received.
    And the degraded path is the one that gets forgotten — a bm25 search still ranks, and it is the
    branch a caller is on while the gateway is down, precisely when someone is reading scores.
    """
    _Meta.calls.clear()
    impl = _impl(rows=[{"uri": "x"}], scores=[0.7], embed=embed)
    out = impl.nominate(PERSON, collection="OntologyClass", text="q", mode=request_mode)
    sent = impl._client.collections._q.last
    assert sent["kind"] == kind, f"mode={request_mode!r} reached {sent['kind']!r}, not {kind!r}"
    assert _Meta.calls == [asked], f"{kind} asked the driver for {_Meta.calls!r}, not {asked!r}"
    assert isinstance(sent.get("return_metadata"), _Meta), (
        f"the {kind} query was issued without the metadata it had just built: {sent!r}"
    )
    assert out.mode == reported
    assert out.rows[0]["score"] == pytest.approx(0.7), (
        f"the {kind} branch did not land the similarity on `score`: {out.rows[0]!r}"
    )


def test_the_DEFAULT_request_is_the_SDKs_vector_only():
    """The SDK's default is `vector_only`. Engine-o never takes it (see the next arm); a caller
    that does must get near_vector, not the hybrid this reader ran before 0.9.8."""
    impl = _impl(rows=[{"uri": "x"}], scores=[0.7])
    impl.nominate(PERSON, collection="OntologyClass", text="q")
    assert impl._client.collections._q.last["kind"] == "near_vector"


def test_ENGINE_O_asks_for_hybrid_at_EVERY_nominate_call():
    """THE RANKING ENGINE-O SHIPS IS HYBRID, and 0.9.8 moved the default under it.

    The population is DERIVED: every call to an attribute named `nominate` in engine-o's
    main.py, counted before it is judged, so a third call site joins the check by existing.
    """
    import ast

    src = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text("utf-8")
    calls = [
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "nominate"
    ]
    assert len(calls) >= 2, f"found {len(calls)} nominate calls; the derivation lost its population"
    for c in calls:
        kw = {k.arg: k.value for k in c.keywords}
        assert isinstance(kw.get("mode"), ast.Constant) and kw["mode"].value == "hybrid", (
            f"main.py:{c.lineno} calls nominate without mode=\"hybrid\" — it would take the SDK "
            "default, vector_only, and change engine-o's ranking"
        )


def test_a_request_mode_OUTSIDE_the_vocabulary_is_the_callers_defect():
    with pytest.raises(ValueError, match="bm25"):
        _impl(rows=[{"uri": "x"}]).nominate(PERSON, collection="OntologyClass", text="q", mode="bm25")


@pytest.mark.parametrize("md,expected", [
    ({"score": 0.0, "certainty": 0.8, "distance": 0.4}, 0.8),   # certainty wins
    ({"score": 0.0, "certainty": None, "distance": 0.25}, 0.75),  # 1 - distance
    ({"score": 0.0, "certainty": None, "distance": 1.5}, 0.0),    # floored, never negative
    ({"score": 0.9, "certainty": None, "distance": None}, None),  # score is NEVER read here
], ids=["certainty", "distance", "floored", "score-ignored"])
def test_a_near_vector_hit_s_similarity_never_reads_the_zero_score(md, expected):
    from agent_fleet.utils.mesh_vectors import _similarity

    assert _similarity(type("M", (), md)) == expected


# ── metadata_filters (SDK 0.9.8): scalar = equal, set/sequence = membership, AND-ed ─────────


def _filters_sent(metadata_filters, domains=()):
    _Filters.calls.clear()
    impl = _impl(rows=[{"uri": "x"}])
    out = impl.nominate(
        PERSON, collection="DocumentChunks", text="q", domains=domains,
        metadata_filters=metadata_filters,
    )
    return out, impl._client.collections._q.last


def test_a_SCALAR_filter_is_exact_match_and_a_STRING_is_a_scalar():
    """The string half is the trap: a str is a Sequence to Python, and membership in its
    characters would match `T`, `M`, `-` and `1` for `{"doc_id": "TM-1"}`."""
    _out, sent = _filters_sent({"doc_id": "TM-1"})
    assert sent["filters"] == ("equal", "doc_id", "TM-1")


@pytest.mark.parametrize("members", [{"a", "b"}, ["a", "b"], ("a", "b"), frozenset({"a", "b"})],
                         ids=["set", "list", "tuple", "frozenset"])
def test_a_SET_or_SEQUENCE_filter_is_membership(members):
    _out, sent = _filters_sent({"verb_iris": members})
    op, prop, got = sent["filters"]
    assert (op, prop, sorted(got)) == ("contains_any", "verb_iris", ["a", "b"])


def test_filters_AND_with_the_domain_scope_and_with_each_other():
    """One `all_of` over every part. The domain scope stays a part, so a caller's filter can only
    narrow what its entitlement already allowed, never replace it."""
    _out, sent = _filters_sent({"doc_id": "TM-1", "page_number": 3}, domains=["SUSTAINMENT"])
    op, parts = sent["filters"]
    assert op == "all_of"
    assert set(parts) == {
        ("equal", "domain", "SUSTAINMENT"),
        ("equal", "doc_id", "TM-1"),
        ("equal", "page_number", 3),
    }


def test_NO_filters_builds_exactly_the_filter_it_always_did():
    """The control for the arm above: no all_of when there is one part, None when there are none."""
    _out, sent = _filters_sent({}, domains=["SUSTAINMENT"])
    assert sent["filters"] == ("equal", "domain", "SUSTAINMENT")
    _out, sent = _filters_sent({})
    assert sent["filters"] is None


def test_an_EMPTY_membership_set_is_an_EMPTY_answer_without_a_search():
    out, sent = _filters_sent({"verb_iris": set()})
    assert out.outcome == "empty"
    assert sent is None, f"a search was issued for a filter nothing can match: {sent!r}"


@pytest.mark.parametrize("bad", [None, {"nested": 1}], ids=["None", "mapping"])
def test_a_filter_value_with_no_filter_meaning_is_REFUSED_naming_the_key(bad):
    with pytest.raises(ValueError, match="doc_id"):
        _filters_sent({"doc_id": bad})


def test_the_signature_carries_EVERY_parameter_the_installed_SDK_declares():
    """PARITY WITH WHATEVER SDK IS INSTALLED, as a superset. At the fleet pin (no `mode` on the
    Protocol) this asserts the old parameters; against ca's 0.9.8 branch it asserts `mode` and
    `metadata_filters` too, with the SDK's own defaults. Run it on that tree to prove the caller."""
    import inspect

    from iagent_mesh.interfaces import MeshVectors

    ours = inspect.signature(WeaviateVectors.nominate).parameters
    for name, p in inspect.signature(MeshVectors.nominate).parameters.items():
        assert name in ours, f"the SDK's nominate declares {name!r} and this reader does not"
        assert ours[name].kind == p.kind, f"{name!r}: {ours[name].kind} vs the SDK's {p.kind}"
        if p.default is not inspect.Parameter.empty:
            assert ours[name].default == p.default, (
                f"{name!r} defaults to {ours[name].default!r}; the SDK says {p.default!r}"
            )


def test_the_metadata_score_LANDS_ON_THE_ROW_under_the_key_the_incumbent_uses():
    """`score`, a float, one per row, in order. The incumbent pool builder spells it exactly this
    way, and the flag-parity seal compares the two pools row for row."""
    out = _impl(
        rows=[{"uri": "a", "label": "A"}, {"uri": "b", "label": "B"}],
        scores=[0.66, 0.41],
    ).nominate(PERSON, collection="OntologyClass", text="q")
    assert out.outcome == "answered"
    assert [r["score"] for r in out.rows] == [0.66, 0.41]
    assert all(isinstance(r["score"], float) for r in out.rows)


def test_a_SCORELESS_response_still_carries_the_key_as_None():
    """The control for the arm above, differing in exactly what the guard decides on: the object
    has NO metadata at all, which is the pure-BM25-on-a-scoreless-config shape.

    The key must still be present. A missing key makes "not ranked" and "never asked" the same
    shape downstream, which is the three-states-collapsed-to-two defect one field over.
    """
    out = _impl(rows=[{"uri": "a"}], scores=None).nominate(
        PERSON, collection="OntologyClass", text="q"
    )
    row = out.rows[0]
    assert "score" in row, "the key was dropped when the response carried no metadata"
    assert row["score"] is None


def test_a_STORED_score_property_WINS_and_the_collision_is_reported():
    """The refusing side. A collection may own a property called `score`, and overwriting it would
    replace the store's datum with a ranking artifact of one query, under a name that gives the
    reader no way to tell which they hold."""
    said: list[str] = []
    out = _impl(
        rows=[{"uri": "a", "score": 3}],
        scores=[0.9],
        report=said.append,
    ).nominate(PERSON, collection="OntologyClass", text="q")
    assert out.rows[0]["score"] == 3, "the retrieval score overwrote the stored property"
    # THE CHANNEL IS SHARED AND THE FIRST MESSAGE IS NOT THIS ONE. `report` also carries the
    # marker-gap warning, which fires first on every fixture without a marker — asserting on
    # `said[0]` passed here for the wrong reason and reds the companion arm below for the wrong
    # reason too. The subset is selected by its PRODUCER, not by its position.
    collisions = [m for m in said if "_search(" in m and "DROPPED" in m]
    assert collisions, (
        f"the collision was silent — a dropped datum that says nothing is the defect class "
        f"(channel carried: {said!r})"
    )
    assert "score" in collisions[0], collisions


def test_the_NON_COLLIDING_row_is_the_companion_that_keeps_that_arm_honest():
    """Its pair. If the implementation simply never wrote the score, the arm above would pass —
    so this one differs in exactly one thing: the row carries no `score` property, and nothing is
    reported.
    """
    said: list[str] = []
    out = _impl(rows=[{"uri": "a"}], scores=[0.9], report=said.append).nominate(
        PERSON, collection="OntologyClass", text="q"
    )
    assert out.rows[0]["score"] == 0.9
    collisions = [m for m in said if "_search(" in m and "DROPPED" in m]
    assert collisions == [], (
        f"a row with no score property reported a collision anyway: {collisions!r}"
    )


def test_the_metadata_factory_IS_REQUIRED_at_construction():
    """Measured, because a claim about what would go wrong is a mutant owed a run.

    The parameter has no default ON PURPOSE. A default of None would let a caller omit it and get
    rows that look complete and carry no ranking: invisible at construction, invisible in the row
    shape (the key is present either way), and visible only as an empty column in a panel nobody
    is reading at the time. This asserts the omission is a TypeError at the one site that can
    still fix it.
    """
    with pytest.raises(TypeError) as exc:
        WeaviateVectors(client=_Client(), embed=lambda _t: _Obs(), filters=_Filters)
    assert "metadata" in str(exc.value), str(exc.value)
