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

import importlib.metadata
import inspect
import json

import pytest

from agent_fleet.ontology_service.mesh_ontology import (
    JenaMeshOntology,
    _checked_iri,
)
import iagent_mesh.conformance as _conformance
from iagent_mesh import Initiator, MeshResult
from iagent_mesh.conformance import check_live, check_offline
from iagent_mesh.interfaces import ServiceIdentityRefused

#: `check_ontology_contract` is the SDK's MeshOntology arm. It is on the SDK's `lane/ca` and is NOT
#: in the pinned `v0.9.3`, so it is bound by `getattr` rather than imported: an import would make
#: this whole FILE uncollectable under the current pin, and an uncollectable file is a nonzero exit
#: that no named arm explains. Bound here, absent means one skip with a ratchet on it (see
#: `test_the_SDKs_ontology_arm_runs_the_moment_the_pin_carries_it`) and present means it RUNS — a
#: broken SDK arm must red, never skip.
_ONTOLOGY_ARM = getattr(_conformance, "check_ontology_contract", None)

#: The exact installed version measured to lack the arm. The skip is excused against THIS STRING and
#: not against "the SDK doesn't have it yet", because the second excuse never expires.
_PIN_WITHOUT_THE_ONTOLOGY_ARM = "0.9.3"

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

#: `TURTLE` ABOVE CANNOT TEST TERM TYPES AND THAT IS WHY IT DIDN'T. Every one of its objects is an
#: IRI or a plain string literal, and a plain string literal is byte-identical to itself with its
#: type stripped — so a `construct` that dropped every datatype and every language tag passes on it.
#: It went unnoticed until the SDK's ontology arm refused the fixture outright for exactly this.
#:
#: `xsd:date` and `@en`, MEASURED, NOT CHOSEN. Turtle has native syntax for `xsd:integer`,
#: `xsd:decimal`, `xsd:double` and `xsd:boolean`, and rdflib's writer uses it: `"42"^^xsd:integer`
#: comes back out as bare `42`, with no `^^` for a reader to match on. Still typed to a parser, and
#: invisible to one. The four abbreviating types and the ones that keep their marker were measured
#: rather than recalled; `xsd:date` and a language tag keep theirs.
_PREFIXES = (
    "@prefix mesh: <http://invincible-agent/mesh#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .\n"
)
TYPED_TERMS = ('"2026-09-26"^^xsd:date', '"hello"@en')
TYPED_TURTLE = _PREFIXES + (
    'mesh:Thing rdfs:label "hello"@en ; mesh:asOf "2026-09-26"^^xsd:date .\n'
)
#: THE CONTROL, and it must differ in exactly what the guard decides on. Same subject, same
#: predicates, same LEXICAL FORMS (`hello`, `2026-09-26`) — differing only in whether those forms
#: carry a type. Anything else different and a passing arm would not tell us which difference it saw.
UNTYPED_TURTLE = _PREFIXES + 'mesh:Thing rdfs:label "hello" ; mesh:asOf "2026-09-26" .\n'


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


def test_the_SDKs_ontology_arm_runs_the_moment_the_pin_carries_it():
    """`check_ontology_contract` — driven, not paraphrased, the same as `check_offline` above.

    IT IS NOT IN THE PINNED SDK. It lives on the SDK's `lane/ca`, 18 commits ahead of the SDK's
    master and untagged, while `pyproject.toml` pins `@v0.9.3` — deliberately a tag, because a
    floating ref would let one SDK commit change every engine's auth behaviour at rebuild. So this
    arm cannot import it and cannot run it yet.

    WHAT THE SKIP IS EXCUSED AGAINST IS A MEASURED VERSION, NOT A STORY. "The SDK doesn't have it
    yet" never expires; `0.9.3` does. If the pin advances and the arm is still missing, the
    `assert` below reds and says so, rather than skipping quietly into a release that was supposed
    to carry it. And when the arm IS present it runs unconditionally — a broken SDK arm must red,
    not skip, which is why this is a runtime branch and not a `skipif` on the import.

    The arm's own findings against this implementation have already been acted on: it red on
    `construct` returning `tuple` rows, and it was RIGHT (see
    `test_a_typed_term_SURVIVES_the_wire_as_turtle_text_and_DIES_as_rdflib_triples`). Its fixture
    refusal — a typed term carrying neither datatype nor language tag cannot discriminate — is what
    caught `TURTLE` being unable to test the property it was being used for.

    ONE LEG OF IT IS WEAK OFFLINE AND SAYING SO IS PART OF THE ARM. `construct` returns the store's
    Turtle verbatim, so with an injected POST the "typed terms appear in the Turtle" check largely
    re-reads this file's own fixture. What makes the property non-trivial is the round trip, and that
    is asserted separately above rather than left to this arm to imply.

    THAT WEAK LEG WAS CLOSED LIVE 2026-09-28, out of tree, because a documented limit is a claim and
    a claim is owed a run. `check_ontology_contract` was driven from the SDK's working tree against
    THIS implementation talking to the sandbox's real Fuseki: `ask` present → `answered`, absent →
    `empty`, `construct` → 5032 characters of Turtle with term types intact. It PASSED, and 5 of 5
    positive controls failed as required (absent raises; absent answers; types stripped; empty
    `typed_terms`; an undiscriminating fixture term). See
    `docs/measurements/mesh-ontology-conformance-live-2026-09-28.md`.

    AND THE FIXTURE'S TYPES ARE NOT THE STORE'S. `TYPED_TERMS` above is `xsd:date` and `@en`; the
    sandbox store emits `@en-US`, `xsd:anyURI`, `xsd:integer` and `xsd:boolean`, and no `xsd:date`
    at all. That does not weaken the offline arm — its property is discrimination between a typed
    form and its own stripped twin, which holds for any type — but it does mean the offline fixture
    is not evidence about the production serializer. The live run is.
    """
    if _ONTOLOGY_ARM is None:
        installed = importlib.metadata.version("iagent-mesh")
        assert installed == _PIN_WITHOUT_THE_ONTOLOGY_ARM, (
            f"iagent-mesh is {installed}, past the {_PIN_WITHOUT_THE_ONTOLOGY_ARM} that was "
            f"measured to lack `check_ontology_contract`, and the arm is STILL absent. Either the "
            f"release that was meant to carry it did not, or it was renamed — find out which "
            f"instead of skipping"
        )
        pytest.skip(
            f"`check_ontology_contract` is not in iagent-mesh {installed}; it is on the SDK's "
            f"lane/ca, untagged. This arm runs itself as soon as the pin carries it"
        )

    absent = "http://invincible-agent/mesh#NothingAtAll"

    class _Router:
        """ASK and CONSTRUCT answered off the same double, keyed on the query VERB.

        Keyed on the query and not on call order: an order-keyed double makes the checker's own
        call sequence part of the fixture, and the checker is free to reorder its calls.
        """

        def __init__(self) -> None:
            self.calls: list[str] = []

        def __call__(self, url, *, data, headers):
            query = data["query"]
            self.calls.append(query)
            if query.startswith("ASK"):
                return _Resp(200, _ask_json(absent not in query))
            return _Resp(200, TYPED_TURTLE)

    impl = JenaMeshOntology(ENDPOINT, post=_Router())
    _ONTOLOGY_ARM(
        impl,
        call_ask_present=lambda: impl.ask(PERSON, iri=THING),
        call_ask_absent=lambda: impl.ask(PERSON, iri=absent),
        call_construct=lambda: impl.construct(PERSON, subject=THING),
        typed_terms=TYPED_TERMS,
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


# ── construct returns Turtle TEXT, because that is the only shape whose types reach a consumer ─


def test_construct_rows_are_TURTLE_TEXT():
    """The anchor. Rows are `str`, and they are the store's own Turtle rather than a re-serialization.

    This arm and the one below REPLACE `test_construct_rows_are_TYPED_TERMS_not_strings`, which
    asserted the opposite and whose docstring argued for it: that Turtle text "would move the parse
    to every consumer and lose the types at the first one that called `str()`". That argument was
    never run against the wire. When it was, it came out backwards — see the next arm.
    """
    result = JenaMeshOntology(ENDPOINT, post=_Post(text=TYPED_TURTLE)).construct(
        PERSON, subject=THING
    )

    assert result.outcome == "answered", result.detail
    assert all(isinstance(row, str) for row in result.rows), [type(r).__name__ for r in result.rows]
    joined = "\n".join(result.rows)
    for term in TYPED_TERMS:
        assert term in joined, f"{term!r} missing from the rows: {joined!r}"


def test_a_typed_term_SURVIVES_the_wire_as_turtle_text_and_DIES_as_rdflib_triples():
    """THE SEAL DEFENDS A CHOICE, so it asserts the REJECTED shape fails where the shipped one holds.

    Mutation testing cannot find this one: both shapes are `answered` with non-empty rows, and every
    per-row check passes on either. The difference only appears one hop later. `MeshResult` is
    returned by a FastAPI service, so a consumer reads it after `model_dump_json`, and pydantic
    serializes an `rdflib.term.Literal` by its LEXICAL FORM — `"hello"@en` becomes `"hello"`.

    The two fixtures carry identical lexical forms and differ only in whether they are typed, so
    "serializes identically" can only mean the type is not on the wire.
    """
    from rdflib import Graph

    def as_triples(turtle: str) -> str:
        """The rejected shape, built the way the old implementation built it.

        SORTED, and the first version was not. An `rdflib.Graph` is set-backed, so `tuple(parsed)`
        comes out in an arbitrary order and two graphs built from two fixtures can serialize
        differently for no reason but iteration order. That made this control FLAKY in the direction
        that looks like success: it reported the two fixtures as distinguishable — the opposite of
        what it is here to establish — and one mutation run died on it and appeared to be caught.
        A comparison of serialized JSON over an unordered collection is not a comparison of content.
        """
        parsed = Graph()
        parsed.parse(data=turtle, format="turtle")
        return MeshResult.answered(rows=tuple(sorted(parsed))).model_dump_json()

    def as_shipped(turtle: str) -> str:
        return (
            JenaMeshOntology(ENDPOINT, post=_Post(text=turtle))
            .construct(PERSON, subject=THING)
            .model_dump_json()
        )

    # THE REJECTED SHAPE: the type is gone, and the two fixtures are indistinguishable on the wire.
    assert as_triples(TYPED_TURTLE) == as_triples(UNTYPED_TURTLE), (
        "rdflib triple rows now survive serialization with their types — if this is real, the "
        "reason construct() returns text is gone and the choice should be re-made, not patched"
    )

    # THE SHIPPED SHAPE: they differ, and the difference is exactly the type marker.
    assert as_shipped(TYPED_TURTLE) != as_shipped(UNTYPED_TURTLE)

    # AND THE MARKER IS STILL THERE AFTER A FULL ROUND TRIP, which is the claim a consumer relies
    # on. Serializing alone would leave the read side untested, and the read side is where a
    # `tuple` row silently became a `list`.
    back = MeshResult.model_validate_json(as_shipped(TYPED_TURTLE))
    joined = "\n".join(back.rows)
    for term in TYPED_TERMS:
        assert term in joined, f"{term!r} did not survive the round trip: {joined!r}"


def test_the_rows_are_the_STORES_OWN_turtle_and_not_a_RE_SERIALIZATION():
    """Verbatim, byte-exact — because a round trip through a serializer can only subtract spellings.

    ADDED BECAUSE THE MUTANT WAS QUIET. Replacing `rows=(body.text,)` with
    `rows=(parsed.serialize(format="turtle"),)` passed all 27 arms. `construct`'s docstring argues
    for verbatim on the grounds that rdflib's Turtle writer abbreviates the four datatypes Turtle has
    native syntax for, and an argument nobody ran is exactly what put the wrong row type in this
    method for as long as it was there. A hazard I write down is a mutant I owe a run.

    `xsd:integer` ON PURPOSE, and it is the one datatype the arms above must NOT use. Those assert
    that a type SURVIVES, and `"42"^^xsd:integer` survives re-serialization semantically while
    vanishing lexically — bare `42` in Turtle IS an integer. That makes it useless for a
    substring-matched survival check and perfect for a FIDELITY check: it is a spelling only
    pass-through preserves.
    """
    body = (
        "@prefix mesh: <http://invincible-agent/mesh#> .\n"
        "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .\n"
        'mesh:Thing mesh:instanceCount "42"^^xsd:integer .\n'
    )
    result = JenaMeshOntology(ENDPOINT, post=_Post(text=body)).construct(PERSON, subject=THING)

    assert result.outcome == "answered", result.detail
    assert result.rows == (body,), result.rows
    assert '"42"^^xsd:integer' in result.rows[0], (
        "the store's own spelling was rewritten — a serializer ran over the response and dropped "
        "the explicit datatype in favour of Turtle's native integer syntax"
    )


def test_construct_over_a_PREFIX_ONLY_body_is_EMPTY_not_ANSWERED():
    """A body that parses to zero triples is `empty`, not a row of text with nothing in it.

    The store answering with a prefix block and no statements is the shape that distinguishes
    "returned text" from "returned a subgraph", and it is why the implementation still parses: the
    emptiness decision belongs to this method, not to every consumer that has to count triples to
    find out whether it got an answer.
    """
    result = JenaMeshOntology(ENDPOINT, post=_Post(text=_PREFIXES)).construct(PERSON, subject=THING)
    assert result.outcome == "empty", f"{result.outcome}: {result.rows!r}"
    assert result.rows == ()


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
