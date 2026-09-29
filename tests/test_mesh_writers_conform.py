"""Conformance for this fleet's two ``iagent_mesh`` writers, plus what conformance cannot reach.

Run: uv run --frozen pytest tests/test_mesh_writers_conform.py -v

## WHAT IS SEALED HERE AND WHAT IS NOT

``iagent_mesh.conformance.check_writer_offline`` proves the properties every writer Protocol shares
with no substrate: a bare service is refused, a person and a delegate are admitted, every operation
returns a ``MeshWriteResult``. Those are real and they are cheap, and they are also the half that a
stub can prove.

**THE HALF A STUB CANNOT PROVE is that the call the writer makes is a call the client ACCEPTS.**
Every arm below drives a hand-written double, so `collections.create(**named_vector_config(),
inverted_index_config=...)` is checked for its SHAPE and never for whether weaviate-client would
take those keywords together, and `apoc.merge.relationship` is checked for being passed the verb as
a parameter and never for existing in the target database. A fixture controls the logic; it says
nothing about whether the logic still points at anything real.

That gap is why ``test_writers_against_scratch_collections`` exists below, and why it is **skipped by
default**. It writes to a real store, and a store write here is not the agent's to make: it runs only
when ``IAGENT_WRITER_SCRATCH`` names a live substrate, which is a human's act. The arm is written and
unrun rather than absent, so the thing that is missing is a RUN and not a test — an absent live arm
reads as "not needed yet", which is the state this fleet has repeatedly mistaken for verified.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional, Sequence

import pytest
from iagent_mesh.conformance import (
    assert_fixture_discriminates,
    check_writer_marker,
    check_writer_offline,
)
from iagent_mesh.interfaces import MESH_COLLECTION_META, Initiator, ServiceIdentityRefused
from iagent_mesh.write_results import MeshWriteResult

from agent_fleet.utils.mesh_writers.neo4j_graph import Neo4jGraphWriter
from agent_fleet.utils.mesh_writers.weaviate_vectors import WeaviateVectorsWriter
from agent_fleet.utils.weaviate_utils import VECTOR_SPACE

_PERSON = Initiator(subject="test-person", kind="person")
_SERVICE = Initiator(subject="test-service", kind="service")

#: The dimension the stub embedder serves. NOT 768: the production constant would make every
#: dimension assertion below pass whether the writer consults its embedder or its own module
#: constant, which is the precise defect `identity()` exists to prevent. A value nothing else in the
#: tree declares can only have come from the injected embedder.
_STUB_DIM = 11


class _StubEmbedder:
    """An ``Embedder`` that never leaves the process."""

    def __init__(self, *, fail: bool = False, model: str = "stub-embed-model") -> None:
        self.fail = fail
        self.model = model
        self.embedded: list[str] = []

    def embed(self, text: str) -> Sequence[float]:
        self.embedded.append(text)
        if self.fail:
            raise RuntimeError("stub embedder refuses")
        return [0.5] * _STUB_DIM

    def identity(self) -> tuple[str, Optional[str], int]:
        return (self.model, None, _STUB_DIM)


# ── the weaviate double ─────────────────────────────────────────────────────────────────────────

class _StubData:
    def __init__(self, collection: "_StubCollection") -> None:
        self._c = collection

    def exists(self, uuid: Any) -> bool:  # noqa: A002 — the client's own keyword
        return uuid in self._c.rows

    def insert(self, *, uuid: Any, properties: dict, vector: Any = None) -> None:  # noqa: A002
        self._c.calls.append(("insert", uuid, properties, vector))
        self._c.rows[uuid] = (properties, vector)

    def replace(self, *, uuid: Any, properties: dict, vector: Any = None) -> None:  # noqa: A002
        self._c.calls.append(("replace", uuid, properties, vector))
        self._c.rows[uuid] = (properties, vector)

    def update(self, *, uuid: Any, properties: dict = None, vector: Any = None) -> None:  # noqa: A002
        self._c.calls.append(("update", uuid, properties, vector))
        existing = self._c.rows.get(uuid, ({}, None))
        self._c.rows[uuid] = (properties if properties is not None else existing[0], vector)


class _StubCollection:
    def __init__(self, name: str, create_kwargs: dict) -> None:
        self.name = name
        self.create_kwargs = create_kwargs
        self.rows: dict[Any, tuple[dict, Any]] = {}
        self.calls: list[tuple] = []

    @property
    def data(self) -> _StubData:
        return _StubData(self)


class _StubCollections:
    def __init__(self) -> None:
        self.by_name: dict[str, _StubCollection] = {}

    def exists(self, name: str) -> bool:
        return name in self.by_name

    def create(self, *, name: str, **kwargs: Any) -> _StubCollection:
        self.by_name[name] = _StubCollection(name, kwargs)
        return self.by_name[name]

    def get(self, name: str) -> _StubCollection:
        # NO AUTO-CREATE. The real client's `get` on a missing collection followed by `insert` is
        # auto-schema — the very hazard `_ensure_collection` exists to prevent — so a double that
        # quietly created one would make a writer that skipped the create look identical to one
        # that did it properly.
        if name not in self.by_name:
            raise KeyError(f"no collection {name!r}: the writer inserted without creating it")
        return self.by_name[name]


class _StubClient:
    def __init__(self) -> None:
        self.collections = _StubCollections()


class _ExplodingCollections(_StubCollections):
    """Every route into the store raises, to exercise the failure classification."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__()
        self._exc = exc

    def exists(self, name: str) -> bool:
        raise self._exc


# ── the neo4j double ────────────────────────────────────────────────────────────────────────────

class _StubResult:
    def __init__(self, record: Any) -> None:
        self._record = record

    def single(self) -> Any:
        return self._record


class _StubSession:
    def __init__(self, driver: "_StubDriver") -> None:
        self._d = driver

    def __enter__(self) -> "_StubSession":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def run(self, cypher: str, **params: Any) -> _StubResult:
        self._d.queries.append((cypher, params))
        if self._d.raises is not None:
            raise self._d.raises
        return _StubResult(self._d.record)


class _StubDriver:
    def __init__(self, *, record: Any = {"rel_type": "V"}, raises: BaseException = None) -> None:
        self.record = record
        self.raises = raises
        self.queries: list[tuple[str, dict]] = []

    def session(self) -> _StubSession:
        return _StubSession(self)


#: THE REAL EXCEPTION, IMPORTED, AND THE FIRST DRAFT'S HAND-WRITTEN DOUBLE IS WHY.
#:
#: That draft declared `class _ServiceUnavailable(Exception)` under a docstring saying "named to
#: match neo4j.exceptions.ServiceUnavailable" — and its `__name__` was `_ServiceUnavailable`, so the
#: writer's name-match never fired and the arm reported `failed` where it expected `unreachable`. A
#: red, luckily; had the arm asserted `failed` it would have been a permanent false green over a
#: double that cannot represent what it claims to.
#:
#: Importing the driver's own class is strictly stronger anyway. The writer matches these by NAME so
#: it stays importable where the driver is absent, and the risk that creates is precisely NAME DRIFT
#: — a rename in neo4j leaves the writer filing a transport failure as a store failure, silently.
#: Only the real class can catch that, so the test imports what the writer refuses to.
from neo4j.exceptions import ServiceUnavailable as _ServiceUnavailable  # noqa: E402


# ── the shared offline conformance, both writers ─────────────────────────────────────────────────

def test_graph_writer_offline_conformance():
    writer = Neo4jGraphWriter(driver=_StubDriver())
    check_writer_offline(
        writer,
        operations=[
            ("write_edge", lambda i: writer.write_edge(
                i, subject="urn:a", verb="RELATES_TO", object="urn:b")),
        ],
    )


def test_vectors_writer_offline_conformance():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    check_writer_offline(
        writer,
        operations=[
            ("write", lambda i: writer.write(i, collection="Scratch", id="row-1", text="hello")),
            ("relocate", lambda i: writer.relocate(
                i, collection="Scratch", id="row-1", vector=[0.5] * _STUB_DIM)),
        ],
    )


def test_the_marker_this_writer_stamps_is_readable_by_the_contracts_own_reader():
    """``check_writer_marker`` round-trips the marker through the SDK's reader.

    The arguments are DERIVED from the writer and its embedder rather than typed: a hand-written
    ``model="stub-embed-model"`` here would pass while the writer stamped something else entirely.
    """
    embedder = _StubEmbedder()
    writer = WeaviateVectorsWriter(client=_StubClient(), embedder=embedder)
    model, version, dimension = embedder.identity()
    check_writer_marker(
        collection="Scratch",
        model=model,
        dimension=dimension,
        written_by=writer._written_by,  # noqa: SLF001 — the value under test is the one it stamps
        collection_created_unix_ms=1_759_000_000_000,
        version=version,
    )


# ── the vector space, at the create and at every write ──────────────────────────────────────────

def test_the_create_declares_the_named_space_and_the_write_addresses_it():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    assert writer.write(_PERSON, collection="Scratch", id="row-1", text="hello").outcome == "written"

    created = client.collections.by_name["Scratch"].create_kwargs
    # The helper returns `vector_config` on the current client and `vectorizer_config` on the older
    # one; asserting the KEY would pin this test to a client version the fleet does not pin. What
    # matters is that a declaration was made at the create at all.
    assert {"vector_config", "vectorizer_config"} & set(created), (
        f"the create declared no vector configuration: {sorted(created)}"
    )

    _op, _uuid, _props, vector = client.collections.by_name["Scratch"].calls[0]
    assert vector == {VECTOR_SPACE: [0.5] * _STUB_DIM}, (
        f"the write did not address the space by name: {vector!r}. A positional list lands in the "
        f"legacy slot, which reads back as vectorised and which no search can target."
    )


def test_the_replace_path_addresses_the_space_too():
    """INSERT RUNS ONCE ON A COLD STORE; REPLACE RUNS ON EVERY RE-WRITE.

    Its own arm because it is the one that would have been missed — a fix applied only to insert
    works until the first re-ingest and then stops, and the symptom comes back looking like a
    regression somewhere else.
    """
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    writer.write(_PERSON, collection="Scratch", id="row-1", text="first")
    writer.write(_PERSON, collection="Scratch", id="row-1", text="second")

    ops = [c[0] for c in client.collections.by_name["Scratch"].calls]
    assert ops == ["insert", "replace"], f"expected one insert then one replace, got {ops}"
    assert client.collections.by_name["Scratch"].calls[1][3] == {VECTOR_SPACE: [0.5] * _STUB_DIM}


def test_the_same_logical_id_is_one_row_not_two():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    writer.write(_PERSON, collection="Scratch", id="row-1", text="first")
    writer.write(_PERSON, collection="Scratch", id="row-1", text="second")
    rows = {k for k in client.collections.by_name["Scratch"].rows}
    assert len(rows) == 1, f"a caller-supplied id produced {len(rows)} rows"


# ── the marker's home ───────────────────────────────────────────────────────────────────────────

def test_the_marker_goes_in_its_own_collection_not_the_one_it_describes():
    """AND THE SEARCHED COLLECTION MUST NOT CONTAIN IT.

    Two failures in one shape, and the second is the one that would have shipped: a marker row
    inside a searched collection sits in the same BM25 and vector index as the content, so hybrid
    search can return the metadata as an answer chunk.
    """
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    writer.write(_PERSON, collection="Scratch", id="row-1", text="hello")

    assert MESH_COLLECTION_META in client.collections.by_name, (
        f"no {MESH_COLLECTION_META} collection was created, so the marker is nowhere the "
        f"contract's reader looks"
    )
    meta_rows = list(client.collections.by_name[MESH_COLLECTION_META].rows.values())
    assert len(meta_rows) == 1
    marker = meta_rows[0][0]
    assert marker["collection"] == "Scratch"
    assert marker["model"] == _StubEmbedder().model
    assert marker["dimension"] == _STUB_DIM, (
        "the stamped dimension did not come from the injected embedder — a writer stamping its own "
        "module constant agrees with a reader comparing its own module constant while both "
        "disagree with the vectors on disk"
    )
    assert "version" not in marker, (
        'an unversioned model must OMIT version, not store "None" — the reader would read that '
        "literal back as a real version and refuse a collection that is fine"
    )

    assert len(client.collections.by_name["Scratch"].rows) == 1, (
        "the described collection holds more than the one content row — a marker written in here "
        "is a search result"
    )


def test_the_marker_is_stamped_once_and_not_on_every_write():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    for n in range(3):
        writer.write(_PERSON, collection="Scratch", id=f"row-{n}", text="hello")
    meta_calls = client.collections.by_name[MESH_COLLECTION_META].calls
    assert len(meta_calls) == 1, (
        f"the marker was written {len(meta_calls)} times — it is stamped in the same act that "
        f"CREATES the collection, not on every row"
    )


# ── refuse, do not strip ────────────────────────────────────────────────────────────────────────

def test_an_embed_failure_with_no_waiver_is_refused_and_writes_nothing():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder(fail=True))
    result = writer.write(_PERSON, collection="Scratch", id="row-1", text="hello")
    assert result.outcome == "refused", result
    assert "vector_required" in result.detail
    assert "Scratch" not in client.collections.by_name, (
        "REFUSED must mean nothing was touched: the collection was created before the embed was "
        "attempted, so a refusal left a side effect behind"
    )


def test_the_waiver_is_a_named_state_and_says_a_re_embed_is_needed():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder(fail=True))
    result = writer.write(
        _PERSON, collection="Scratch", id="row-1", text="hello", vector_required=False)
    assert result.outcome == "written_without_vector", result
    # A vectorless row cannot be repaired by `relocate` — there is no vector to move — so the
    # detail must send the operator to a re-embed. This is the one state the backfill cannot fix,
    # and a detail that said "relocate" would send them to the tool that cannot work.
    assert "re-embed" in result.detail.lower()
    _op, _uuid, _props, vector = client.collections.by_name["Scratch"].calls[0]
    assert vector is None, f"the waived write still passed a vector: {vector!r}"


def test_the_two_outcomes_are_distinguishable():
    """The fixture must tell the states apart, or every arm above is comparing a thing to itself."""
    client = _StubClient()
    ok = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder()).write(
        _PERSON, collection="A", id="r", text="t")
    waived = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder(fail=True)).write(
        _PERSON, collection="B", id="r", text="t", vector_required=False)
    assert_fixture_discriminates("write outcomes", ok, waived, describe=lambda r: r.outcome)


# ── relocate: the one door for a supplied vector ────────────────────────────────────────────────

def test_relocate_refuses_a_vector_of_the_wrong_dimension():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    writer.write(_PERSON, collection="Scratch", id="row-1", text="hello")
    result = writer.relocate(_PERSON, collection="Scratch", id="row-1", vector=[0.1] * (_STUB_DIM + 1))
    assert result.outcome == "refused", result
    assert str(_STUB_DIM) in result.detail


def test_relocate_on_a_missing_row_is_failed_not_written():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    writer.write(_PERSON, collection="Scratch", id="row-1", text="hello")
    result = writer.relocate(
        _PERSON, collection="Scratch", id="absent", vector=[0.1] * _STUB_DIM)
    assert result.outcome == "failed", result


def test_relocate_addresses_the_space_by_name():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    writer.write(_PERSON, collection="Scratch", id="row-1", text="hello")
    moved = [0.9] * _STUB_DIM
    assert writer.relocate(
        _PERSON, collection="Scratch", id="row-1", vector=moved).outcome == "written"
    op, _uuid, _props, vector = client.collections.by_name["Scratch"].calls[-1]
    assert op == "update"
    assert vector == {VECTOR_SPACE: moved}


# ── the failure split ───────────────────────────────────────────────────────────────────────────

def test_a_transport_error_is_unreachable_and_a_store_error_is_failed():
    """THE SPLIT AN OPERATOR READS TO DECIDE WHERE TO LOOK, so it gets both sides and a control.

    `unreachable` sends someone to a cluster; `failed` sends them to the code or the data. A writer
    that reported one as the other would send them to the wrong place with full confidence.
    """
    unreachable_client = _StubClient()
    unreachable_client.collections = _ExplodingCollections(
        type("WeaviateConnectionError", (Exception,), {})("no route"))
    writer = WeaviateVectorsWriter(client=unreachable_client, embedder=_StubEmbedder())
    out = writer.write(_PERSON, collection="Scratch", id="r", text="t")
    assert out.outcome == "unreachable", out

    failed_client = _StubClient()
    failed_client.collections = _ExplodingCollections(ValueError("the store said no"))
    writer = WeaviateVectorsWriter(client=failed_client, embedder=_StubEmbedder())
    out2 = writer.write(_PERSON, collection="Scratch", id="r", text="t")
    assert out2.outcome == "failed", out2

    # THE CONTROL: the two fixtures differ in exactly one thing — the exception's class NAME — and
    # the guard claims to discriminate on precisely that. Identical outcomes would indict the
    # classifier rather than the fixtures.
    assert_fixture_discriminates("store failure kinds", out, out2, describe=lambda r: r.outcome)


def test_the_graph_writer_splits_transport_from_store_the_same_way():
    reachable = Neo4jGraphWriter(driver=_StubDriver())
    assert reachable.write_edge(
        _PERSON, subject="urn:a", verb="V", object="urn:b").outcome == "written"

    gone = Neo4jGraphWriter(driver=_StubDriver(raises=_ServiceUnavailable("bolt down")))
    assert gone.write_edge(
        _PERSON, subject="urn:a", verb="V", object="urn:b").outcome == "unreachable"

    # APOC absent, a bad label, a constraint violation: all reached the store and were refused
    # there. `failed`, because we asked.
    refused_by_store = Neo4jGraphWriter(
        driver=_StubDriver(raises=type("ClientError", (Exception,), {})("no procedure apoc.merge")))
    out = refused_by_store.write_edge(_PERSON, subject="urn:a", verb="V", object="urn:b")
    assert out.outcome == "failed", out
    assert "apoc" in out.detail.lower()


def test_a_missing_endpoint_is_failed_and_says_so():
    writer = Neo4jGraphWriter(driver=_StubDriver(record=None))
    out = writer.write_edge(_PERSON, subject="urn:a", verb="V", object="urn:missing")
    assert out.outcome == "failed", out
    assert "endpoint" in out.detail.lower()


# ── the injection class, absent by construction ─────────────────────────────────────────────────

def test_the_verb_is_passed_as_a_parameter_and_never_interpolated():
    """The strongest property this writer has, so it is asserted rather than described.

    A Cypher relationship TYPE cannot be parameterised in plain Cypher, which is what makes the
    obvious implementation interpolate the verb. This one passes it to `apoc.merge.relationship` as
    an argument, so a verb carrying Cypher is DATA and there is nothing to escape.
    """
    driver = _StubDriver()
    writer = Neo4jGraphWriter(driver=driver)
    hostile = "V`]->() DETACH DELETE n //"
    writer.write_edge(_PERSON, subject="urn:a", verb=hostile, object="urn:b")

    cypher, params = driver.queries[0]
    assert hostile not in cypher, (
        f"the verb reached the query TEXT: {cypher!r}. Every character of a caller-supplied verb is "
        f"then Cypher, and no validator makes that safe for long."
    )
    assert params["verb"] == hostile, "the verb must arrive as a parameter, unmodified"
    assert "DETACH DELETE" not in cypher


def test_a_non_identifier_label_is_refused_at_construction_not_per_call():
    """CONFIG reaches the query text, so it is checked where it is DECLARED."""
    with pytest.raises(ValueError, match="identifier"):
        Neo4jGraphWriter(driver=_StubDriver(), node_label="OntologyClass) DETACH DELETE (n")
    with pytest.raises(ValueError, match="identifier"):
        Neo4jGraphWriter(driver=_StubDriver(), node_key="uri` WITH 1 AS x //")
    # And the control: a legal label is accepted, or the arm above passes for the wrong reason.
    assert Neo4jGraphWriter(driver=_StubDriver(), node_label="Thing", node_key="iri") is not None


def test_empty_arguments_are_refused_before_the_store_is_touched():
    driver = _StubDriver()
    writer = Neo4jGraphWriter(driver=driver)
    for kwargs in (
        {"subject": "", "verb": "V", "object": "urn:b"},
        {"subject": "urn:a", "verb": "   ", "object": "urn:b"},
        {"subject": "urn:a", "verb": "V", "object": ""},
    ):
        out = writer.write_edge(_PERSON, **kwargs)
        assert out.outcome == "refused", (kwargs, out)
    assert driver.queries == [], (
        "a refusal reached the store — `refused` means declined BEFORE touching it, which is the "
        "whole distinction from `failed`"
    )


def test_a_service_identity_RAISES_and_does_not_return_a_refused_result():
    """Held separately from the conformance arm so a change to the SDK's suite cannot silently
    retire the one property this layer exists for — and it asserts the RAISE, because the first
    draft of both writers returned ``MeshWriteResult.refused`` here and this arm, as first written,
    agreed with them. The conformance suite is what disagreed.

    Why the raise is right: a ``refused`` is a value, and a caller that drops it has silently made
    an unauthorized write disappear. ``MeshWriteResult`` raises on ``bool()`` for that same reason.
    """
    graph = Neo4jGraphWriter(driver=_StubDriver())
    vectors = WeaviateVectorsWriter(client=_StubClient(), embedder=_StubEmbedder())

    with pytest.raises(ServiceIdentityRefused):
        graph.write_edge(_SERVICE, subject="urn:a", verb="V", object="urn:b")
    with pytest.raises(ServiceIdentityRefused):
        vectors.write(_SERVICE, collection="S", id="r", text="t")
    with pytest.raises(ServiceIdentityRefused):
        vectors.relocate(_SERVICE, collection="S", id="r", vector=[0.1] * _STUB_DIM)

    # AND THE STORE WAS NEVER TOUCHED. A raise after the write would be a refusal in name only.
    assert graph._driver.queries == []  # noqa: SLF001
    assert vectors._client.collections.by_name == {}  # noqa: SLF001


def test_a_delegate_is_admitted_where_a_service_is_not():
    """The boundary ruled on 2026-09-27, asserted as a DIFFERENCE rather than as two facts.

    A delegate and a service are both non-person kinds, so a writer that gated on ``kind ==
    "person"`` would refuse both and every per-kind assertion would still read as deliberate. What
    distinguishes them is ``on_behalf_of``, and the two fixtures differ in exactly that.
    """
    delegate = Initiator(subject="d", kind="delegate", on_behalf_of="test-person")
    assert_fixture_discriminates(
        "delegate vs service", delegate, _SERVICE, describe=lambda i: i.on_behalf_of)

    writer = WeaviateVectorsWriter(client=_StubClient(), embedder=_StubEmbedder())
    assert writer.write(delegate, collection="S", id="r", text="t").outcome == "written"
    with pytest.raises(ServiceIdentityRefused):
        writer.write(_SERVICE, collection="S", id="r", text="t")


def test_every_transport_name_the_writers_match_on_is_a_real_exception():
    """A NAME-MATCHED SET IS A SET OF STRINGS, AND A TYPO IN ONE IS A GUARD THAT CANNOT FIRE.

    Both writers classify transport failures by ``type(exc).__name__`` so they stay importable
    without their client libraries. The cost is that a misspelled or renamed entry is indistinguish-
    able from a correct one at read time: it simply never matches, and the failure is filed as
    ``failed`` — sending an operator to the code when the cluster is down. This arm resolves every
    name against the real module, which is the only place the spelling can be checked.
    """
    import neo4j.exceptions
    import weaviate.exceptions

    from agent_fleet.utils.mesh_writers import neo4j_graph, weaviate_vectors

    for module, names in (
        (neo4j.exceptions, neo4j_graph._TRANSPORT),          # noqa: SLF001
        (weaviate.exceptions, weaviate_vectors._TRANSPORT),  # noqa: SLF001
    ):
        assert names, f"{module.__name__}: the transport set is empty, so nothing is ever unreachable"
        for name in names:
            resolved = getattr(module, name, None)
            assert isinstance(resolved, type) and issubclass(resolved, BaseException), (
                f"{module.__name__}.{name} is not an exception class — this writer will never "
                f"classify it as unreachable, and a transport failure will be reported as a store "
                f"failure for as long as the name is wrong"
            )


# ── the live half: written, and not the agent's to run ──────────────────────────────────────────

@pytest.mark.skipif(
    not os.environ.get("IAGENT_WRITER_SCRATCH"),
    reason="writes to a real store; set IAGENT_WRITER_SCRATCH=<weaviate url> to run",
)
def test_writers_against_scratch_collections():
    """THE ARM THE DOUBLES CANNOT REPLACE: does the client ACCEPT the call the writer makes.

    Everything above drives a hand-written double, so it proves the writer's logic and says nothing
    about whether `collections.create(**named_vector_config(), inverted_index_config=...)` is a
    call weaviate-client takes, nor whether the named space is the space a search reaches. Those
    are properties of the substrate and the client version, and the fleet has been wrong about both
    while every offline arm was green.

    Unrun as of 2026-09-28: a store write is not the agent's to make under the standing order, so
    this needs a human to point it at a substrate. It is here so that what is missing is a RUN.
    """
    import weaviate

    url = os.environ["IAGENT_WRITER_SCRATCH"]
    collection = f"ScratchWriterConformance{uuid.uuid4().hex[:8]}"
    client = weaviate.connect_to_local(host=url) if "://" not in url else weaviate.connect_to_custom(url)
    try:
        writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
        assert writer.write(
            _PERSON, collection=collection, id="row-1", text="hello").outcome == "written"

        handle = client.collections.get(collection)
        row = next(iter(handle.iterator(include_vector=True)))
        # PRESENCE IS NOT THE PROPERTY. The client maps the legacy slot onto the name `default` on
        # read, so a row written to the WRONG space still reads back with a vector under the right
        # name. Only the consuming operation can tell, so this ends at a near-vector search.
        found = handle.query.near_vector(
            near_vector=row.vector[VECTOR_SPACE], target_vector=VECTOR_SPACE, limit=1)
        assert found.objects, (
            "the row is not retrievable by the vector it was written with — the space the write "
            "addressed is not the space the search reaches"
        )
    finally:
        try:
            client.collections.delete(collection)
        finally:
            client.close()
