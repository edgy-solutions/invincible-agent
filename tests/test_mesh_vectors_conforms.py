"""Engine-o's `MeshVectors` implementation, against the SDK's own conformance suite and the
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

from agent_fleet.ontology_service.mesh_vectors import (  # noqa: E402
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
    def __init__(self, rows):
        self._rows = rows
        self.last = None

    def _resp(self, **kw):
        self.last = kw
        return type("R", (), {"objects": [type("O", (), {"properties": r}) for r in self._rows]})

    def hybrid(self, **kw):
        return self._resp(kind="hybrid", **kw)

    def bm25(self, **kw):
        return self._resp(kind="bm25", **kw)


class _Collections:
    def __init__(self, rows, present=True):
        self._q, self._present = _Query(rows), present

    def exists(self, _name):
        return self._present

    def get(self, _name):
        return type("H", (), {"query": self._q})


class _Client:
    def __init__(self, rows=(), present=True):
        self.collections = _Collections(list(rows), present)


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


def _impl(*, rows=(), present=True, marker=None, embed=None, oldest=None, report=None):
    return WeaviateVectors(
        client=_Client(rows, present),
        embed=embed or (lambda _t: _Obs()),
        filters=_Filters,
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
        client=_Boom(), embed=lambda _t: _Obs(), filters=_Filters, fetch_marker=lambda _c: None
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
    """MOVED 2026-09-17 to `marker_predates_collection`, the name at the fleet pin `v0.9.2`.

    This arm previously pinned `marker_is_stale` as the name compiled against, so that the day it
    went the failure would say which name to move to. It went the other way — the replacement
    arrived first and this lane was the live consumer the expand/contract interval existed for, so
    the move is deliberate rather than forced.

    **IT NOW ASSERTS THE OLD NAME IS NOT WHAT WE CALL**, which is the half that keeps the alias
    contractable: if anything here drifts back onto `marker_is_stale`, the SDK cannot remove it.
    """
    import agent_fleet.ontology_service.mesh_vectors as mv
    from iagent_mesh.interfaces import marker_predates_collection

    assert callable(marker_predates_collection)

    src = (_REPO / "agent_fleet" / "ontology_service" / "mesh_vectors.py").read_text("utf-8")
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
