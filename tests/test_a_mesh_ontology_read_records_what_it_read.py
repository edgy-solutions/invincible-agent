"""THE FOUR OUTCOMES ARE FOUR DIFFERENT ANSWERS, AND EVERY ONE OF THEM LEAVES A TRAIL.

`agent_fleet/ontology_service/mesh_ontology.py` implements the SDK's `MeshOntology` Protocol over
Jena. This seal is offline by construction: every arm injects the POST, so the transport outcome is
chosen rather than hoped for — an unreachable store, a 4xx, a 5xx and a 200 with an unreadable body
are all states a live substrate will not produce on demand, and a seal that can only reach the
happy one has checked the half that was never in doubt.

── WHY THE SDK'S OWN CHECKER RUNS HERE, RATHER THAN MY RESTATEMENT OF IT ─────────────────────
`check_offline` / `check_live` are imported and driven, not paraphrased. A local re-implementation
of a contract is a second declaration of it, and the two go out of agreement at the first edit
nobody mirrored. `check_live` gets doubles for both fixtures because what it actually needs is a
substrate that IS reachable and holds nothing versus one that cannot be reached — a distinction a
double makes exactly and a cluster makes by luck.

── THE ARM THAT MUTATION CANNOT REACH FROM THE LOGIC ─────────────────────────────────────────
`test_every_outcome_records_EXACTLY_ONE_provenance_line` is parametrised over all four outcomes
because the recording sits at a single exit (`_read`) and that is a WIRING property. Deleting the
`_record` call reds all four; moving the call next to three of the four returns reds the fourth.
Asserting only the answered path would pass an implementation whose failures are invisible, which
is the state the provenance property exists to end.

── AND THE GUARDS ASSERT THEY FIRED BEFORE THE QUERY EXISTED, NOT MERELY THAT THEY FIRED ─────
A refusal that happens after the POST is still a refusal and still passes an outcome check. So the
IRI arm and the service-identity arm both assert the injected POST recorded ZERO calls, against a
control in the same file where a clean IRI and a person identity produce exactly one. A guard that
rejects the result of a query it already sent has leaked the query.

Run: uv run --frozen pytest tests/test_a_mesh_ontology_read_records_what_it_read.py -v
"""
from __future__ import annotations

import inspect
import json

import pytest

from agent_fleet.ontology_service.mesh_ontology import (
    JenaMeshOntology,
    _checked_iri,
)
from iagent_mesh import Initiator, MeshResult
from iagent_mesh.conformance import check_live, check_offline
from iagent_mesh.interfaces import ServiceIdentityRefused

ENDPOINT = "http://ontology.invalid/ds/sparql"
THING = "http://invincible-agent/mesh#Thing"
PERSON = Initiator(subject="lane-74-seal", kind="person")
SERVICE = Initiator(subject="engine-o-worker", kind="service")


# ── the double ───────────────────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text

    def json(self):
        # httpx raises on an unparseable body; ValueError is what the implementation catches, and
        # `json.JSONDecodeError` IS a ValueError, so this double fails the same way the real one does.
        return json.loads(self.text)


class _Post:
    """Records every call, so an arm can assert a query was never sent."""

    def __init__(self, status: int = 200, text: str = "", raises: bool = False) -> None:
        self._status, self._text, self._raises = status, text, raises
        self.calls: list[dict] = []

    def __call__(self, url, *, data, headers):
        self.calls.append({"url": url, "data": data, "headers": headers})
        if self._raises:
            raise OSError("connection refused")
        return _Resp(self._status, self._text)


def _ask_json(boolean: bool) -> str:
    return json.dumps({"head": {}, "boolean": boolean})


TURTLE = (
    "@prefix mesh: <http://invincible-agent/mesh#> .\n"
    "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    'mesh:Thing a owl:Class ; rdfs:label "Thing" ; mesh:universalReferent "true" .\n'
)


# ── the SDK's own checker ────────────────────────────────────────────────────────────────────


def test_the_SDKs_offline_conformance_arm_passes():
    impl = JenaMeshOntology(ENDPOINT, post=_Post(raises=True))
    check_offline(
        impl,
        operations=[
            ("ask", lambda i: impl.ask(i, iri=THING)),
            ("construct", lambda i: impl.construct(i, subject=THING)),
        ],
        declared_modes=impl.MODES,
    )


def test_the_SDKs_live_conformance_arm_passes_on_a_FRESH_reader():
    """The reader is a fresh instance on purpose.

    An instance that has already read has a non-empty trail whatever this arm's own read does, so
    handing `check_live` the provenance of a used object is a check that cannot fail. `fresh` has
    read nothing, so a non-empty trail can only have come from the call the checker itself made.
    """
    fresh = JenaMeshOntology(ENDPOINT, post=_Post(text=_ask_json(False)))
    dead = JenaMeshOntology(ENDPOINT, post=_Post(raises=True))
    assert fresh.provenance() == (), "the fresh instance was not fresh"

    check_live(
        fresh,
        operation="ask",
        call_reachable_empty=lambda: fresh.ask(PERSON, iri=THING),
        call_unreachable=lambda: dead.ask(PERSON, iri=THING),
        read_provenance=fresh.provenance,
    )


# ── the outcomes ─────────────────────────────────────────────────────────────────────────────


def test_a_reachable_store_that_holds_nothing_is_empty_and_an_unreachable_one_is_NOT():
    """`empty` means asked-and-absent; `unreachable` means could-not-ask. Both arms in one test
    because the claim is that they DIFFER — either alone passes an implementation that collapses
    them onto whichever outcome that arm expects."""
    reachable = JenaMeshOntology(ENDPOINT, post=_Post(text=_ask_json(False)))
    unreachable = JenaMeshOntology(ENDPOINT, post=_Post(raises=True))

    absent = reachable.ask(PERSON, iri=THING)
    down = unreachable.ask(PERSON, iri=THING)

    assert absent.outcome == "empty", absent.detail
    assert absent.detail is None
    assert down.outcome == "unreachable", down.outcome
    assert down.detail and "OSError" in down.detail
    assert absent.outcome != down.outcome


def test_a_4xx_is_FAILED_and_a_5xx_is_UNREACHABLE():
    """The store answering and rejecting is our defect; the store not answering is not.

    This split is not cosmetic and the implementation had it wrong first: a malformed ASK came back
    400 and was reported as "the store is unreachable" about a store that had just answered twice
    in the same second. A classification that turns a query bug into an infrastructure symptom
    sends the next person to the network.
    """
    refused = JenaMeshOntology(ENDPOINT, post=_Post(status=400, text="Parse error")).ask(
        PERSON, iri=THING
    )
    broken = JenaMeshOntology(ENDPOINT, post=_Post(status=503, text="unavailable")).ask(
        PERSON, iri=THING
    )

    assert refused.outcome == "failed", refused.outcome
    assert "400" in (refused.detail or "")
    assert broken.outcome == "unreachable", broken.outcome
    assert "503" in (broken.detail or "")


def test_a_200_with_an_unreadable_body_is_FAILED_not_EMPTY():
    """The store answered and we could not read it. Reporting that as an absence would let a
    proxy's HTML error page stand in for "this class does not exist"."""
    result = JenaMeshOntology(ENDPOINT, post=_Post(text="<html>login</html>")).ask(
        PERSON, iri=THING
    )
    assert result.outcome == "failed", result.outcome
    assert "sparql-results+json" in (result.detail or "")


def test_ask_answers_with_the_IRI_it_resolved():
    """`answered` with no rows is forbidden by the result type, and the IRI is the only honest
    row: it says WHICH subject the yes is about, which a bare True does not."""
    result = JenaMeshOntology(ENDPOINT, post=_Post(text=_ask_json(True))).ask(PERSON, iri=THING)
    assert result.outcome == "answered"
    assert result.rows == (THING,)


# ── the recording, at the single exit ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "outcome,post",
    [
        ("answered", _Post(text=_ask_json(True))),
        ("empty", _Post(text=_ask_json(False))),
        ("failed", _Post(status=400, text="Parse error")),
        ("unreachable", _Post(raises=True)),
    ],
)
def test_every_outcome_records_EXACTLY_ONE_provenance_line(outcome, post):
    """All four, because the recording is a WIRING property, not a logic one.

    `_read` records at the one exit every outcome returns through. A record placed next to each
    return instead would pass three of these arms and fail the fourth, and the one it forgot would
    be indistinguishable from a read that never happened.
    """
    impl = JenaMeshOntology(ENDPOINT, post=post)
    result = impl.ask(PERSON, iri=THING)
    assert result.outcome == outcome, f"fixture drifted: {result.outcome} {result.detail}"

    trail = impl.provenance()
    assert len(trail) == 1, trail
    line = trail[0]
    assert line.startswith("ask ")
    assert f"target={THING}" in line
    assert f"outcome={outcome}" in line
    assert f"initiator={PERSON.subject}" in line, line


def test_the_trail_is_bounded_so_a_long_lived_pod_does_not_grow_one():
    impl = JenaMeshOntology(ENDPOINT, post=_Post(text=_ask_json(False)), provenance_limit=3)
    for _ in range(10):
        impl.ask(PERSON, iri=THING)
    assert len(impl.provenance()) == 3


# ── the refusals, and that they happen BEFORE a query exists ─────────────────────────────────


def test_a_service_identity_is_refused_and_NO_QUERY_IS_SENT():
    post = _Post(text=_ask_json(True))
    impl = JenaMeshOntology(ENDPOINT, post=post)

    with pytest.raises(ServiceIdentityRefused):
        impl.ask(SERVICE, iri=THING)
    assert post.calls == [], "the refusal came after the query — the query leaked"
    assert impl.provenance() == (), "recorded a read that never happened"

    # THE CONTROL. Without it a guard refusing every identity passes the arm above.
    assert impl.ask(PERSON, iri=THING).outcome == "answered"
    assert len(post.calls) == 1


@pytest.mark.parametrize(
    "bad",
    [
        "http://x/a> ?p ?o } ; DROP ALL ; ASK {<http://y",
        "http://x/ a",
        "http://x/\na",
        'http://x/"a',
    ],
)
def test_an_IRI_the_grammar_FORBIDS_is_refused_before_a_query_exists(bad):
    """An IRI goes inside `<...>`, which makes it a parameter crossing into an embedded language.
    A `>` closes the bracket early and the remainder is parsed as SPARQL. The refusal raises rather
    than sanitising: a silently rewritten IRI reads a DIFFERENT subject and answers about it."""
    post = _Post(text=_ask_json(True))
    impl = JenaMeshOntology(ENDPOINT, post=post)

    with pytest.raises(ValueError):
        impl.ask(PERSON, iri=bad)
    with pytest.raises(ValueError):
        impl.construct(PERSON, subject=bad)
    assert post.calls == [], "a forbidden IRI reached the store"


def test_the_IRI_guard_ACCEPTS_the_ordinary_case():
    """The control for the arm above, and the reason it is a separate test: a guard that rejects
    everything satisfies every injection arm ever written."""
    assert _checked_iri(THING, argument="iri") == THING
    post = _Post(text=_ask_json(True))
    JenaMeshOntology(ENDPOINT, post=post).ask(PERSON, iri=THING)
    assert len(post.calls) == 1


def test_the_graph_argument_is_guarded_TOO():
    """The named-graph IRI is interpolated into the same brackets and is the argument a caller is
    likelier to build from configuration than from a literal."""
    post = _Post(text=_ask_json(True))
    with pytest.raises(ValueError):
        JenaMeshOntology(ENDPOINT, post=post).ask(
            PERSON, iri=THING, graph="http://g/> ?x ?y ?z } ASK {<http://h"
        )
    assert post.calls == []


# ── construct returns terms, not text ────────────────────────────────────────────────────────


def test_construct_rows_are_TYPED_TERMS_not_strings():
    """The Protocol's reason for CONSTRUCT over SELECT is that the SELECT executor drops term
    types. Rows of Turtle text would move the parse to every consumer and lose the types at the
    first one that called `str()`."""
    from rdflib import Literal, URIRef

    result = JenaMeshOntology(ENDPOINT, post=_Post(text=TURTLE)).construct(PERSON, subject=THING)

    assert result.outcome == "answered", result.detail
    assert len(result.rows) == 3
    subjects = {s for s, _, _ in result.rows}
    assert subjects == {URIRef(THING)}
    assert any(isinstance(o, URIRef) for _, _, o in result.rows)
    assert any(isinstance(o, Literal) for _, _, o in result.rows)


def test_construct_over_a_subject_with_no_triples_is_EMPTY():
    result = JenaMeshOntology(ENDPOINT, post=_Post(text="")).construct(PERSON, subject=THING)
    assert result.outcome == "empty", result.detail


def test_construct_over_UNPARSEABLE_turtle_is_FAILED():
    result = JenaMeshOntology(ENDPOINT, post=_Post(text="this is not turtle {{{")).construct(
        PERSON, subject=THING
    )
    assert result.outcome == "failed", result.outcome
    assert "Turtle" in (result.detail or "")


# ── the shape the Protocol fixed ─────────────────────────────────────────────────────────────


def test_no_mode_is_emitted_and_MODES_is_EMPTY():
    """`MODES = ()` and the result type says `mode` is absent for a read with only one way to
    answer. A helpful-looking `mode="sparql"` reds the conformance checker — correctly, because a
    consumer cannot anticipate a mode nobody declared."""
    assert JenaMeshOntology.MODES == ()
    impl = JenaMeshOntology(ENDPOINT, post=_Post(text=_ask_json(True)))
    assert impl.ask(PERSON, iri=THING).mode is None
    assert JenaMeshOntology(ENDPOINT, post=_Post(text=TURTLE)).construct(
        PERSON, subject=THING
    ).mode is None


def test_the_operations_are_SYNC_because_the_Protocol_is():
    """engine-o's own `_run_ask` / `_run_construct_turtle` in `main.py` are `async`, so the
    obvious "reuse what is there" is the one thing that cannot be done. Asserting against the
    Protocol rather than a hardcoded expectation means this arm tracks the contract, not my memory
    of it."""
    from iagent_mesh.interfaces import MeshOntology

    for name in ("ask", "construct"):
        contract = inspect.iscoroutinefunction(getattr(MeshOntology, name))
        mine = inspect.iscoroutinefunction(getattr(JenaMeshOntology, name))
        assert mine == contract, f"{name}: Protocol async={contract}, implementation async={mine}"


def test_it_satisfies_the_Protocol_and_returns_the_Protocols_result_type():
    from iagent_mesh.interfaces import MeshOntology

    impl = JenaMeshOntology(ENDPOINT, post=_Post(text=_ask_json(True)))
    assert isinstance(impl, MeshOntology)
    assert isinstance(impl.ask(PERSON, iri=THING), MeshResult)


def test_there_is_NO_WRITE_HALF():
    """Not an omission. The update endpoint derivation used elsewhere in this engine
    (`endpoint.replace("/sparql", "/update")`) is a NO-OP against a `.../ds/query` address, so a
    write posts `update=` to the query endpoint and the store rejects it — and the Protocol
    declares two operations. A write added here without that derivation being fixed would look
    like a capability and behave like a 400."""
    public = {n for n in dir(JenaMeshOntology) if not n.startswith("_")}
    assert public == {"MODES", "ask", "construct", "provenance"}, sorted(public)
