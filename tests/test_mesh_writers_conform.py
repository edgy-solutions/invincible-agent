"""Conformance for this fleet's two ``iagent_mesh`` writers (SDK v0.9.5), plus what it cannot reach.

Run: uv run --frozen pytest tests/test_mesh_writers_conform.py -v
Live: IAGENT_WRITER_SCRATCH=1 with NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD and/or
      WEAVIATE_HTTP_HOST/WEAVIATE_GRPC_HOST set — writes ONLY a uniquely named scratch Neo4j label
      and scratch Weaviate collections, and tears them down.

## WHAT IS SEALED OFFLINE AND WHAT ONLY THE LIVE ARMS CAN SEAL

``check_writer_offline`` proves the gate every writer shares (a bare service RAISES, a person and
a delegate are admitted, every write returns a ``MeshWriteResult``). The arms after it drive
hand-written doubles, which prove the writer's LOGIC — refuse-not-strip, the failure split, that
no request field reaches the query text — and say nothing about whether the call the writer makes
is one the store ACCEPTS. ``apoc.merge.relationship`` is checked for its arguments, never for
existing; ``collections.create(**named_vector_config(), ...)`` for its shape, never for whether
weaviate-client takes those keywords together.

That is the live half's job. ``check_graph_writer_contract``, ``..._has_edges_contract`` and
``..._key_only_delete_contract`` need a store that actually keys edges, so they run ONLY live, and
they run against the registrar's own predicate-family configuration with one thing changed: the
node label, which is a scratch label nothing else reads.

## THE READ SIDE OF THE GRAPH ARM IS DERIVED FROM ``Neo4jGraph.edge()``, WITH TWO SUBSTITUTIONS

The SDK arm reads back through ``MeshGraph.edge()``. The fleet's ``edge()`` cannot serve it
unmodified, for two reasons that are each a finding rather than a fixture choice:

* it is hard-wired to ``OntologyClass``, and a scratch run may not touch the production label;
* it ends ``LIMIT 1`` — it RESOLVES the cheapest edge rather than enumerating them — so the SDK's
  "one verb, two keys, two edges" read can never return 2 rows through it, whatever the writer did.

So the live arm takes ``edge()``'s own query text and substitutes exactly those two things, each
anchor-counted, so a change to the reader breaks this arm loudly instead of drifting from it. The
``LIMIT 1`` mismatch between the SDK arm and the fleet reader is routed to ca.
"""

from __future__ import annotations

import datetime
import importlib
import inspect
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence

import pytest
from iagent_mesh.conformance import (
    ConformanceFailure,
    assert_fixture_discriminates,
    check_graph_writer_contract,
    check_graph_writer_has_edges_contract,
    check_graph_writer_key_only_delete_contract,
    check_graph_writer_write_node_contract,
    check_vectors_writer_contract,
    check_vectors_writer_delete_contract,
    check_writer_marker,
    check_writer_offline,
)
from iagent_mesh.interfaces import (
    MESH_COLLECTION_META,
    EdgeIdentity,
    EdgeIdentityFilter,
    Initiator,
    ServiceIdentityRefused,
)
from iagent_mesh.results import MeshResult

from agent_fleet.utils.mesh_writers.neo4j_graph import ENDPOINT_ABSENT, Neo4jGraphWriter
from agent_fleet.utils.mesh_writers.weaviate_vectors import (
    WeaviateVectorsWriter,
    _row_uuid,  # the writer's OWN id derivation: a test that recomputes it can diverge
)
from agent_fleet.utils.weaviate_utils import VECTOR_SPACE, named_vector_config

_PERSON = Initiator(subject="test-person", kind="person")
_SERVICE = Initiator(subject="test-service", kind="service")
_DELEGATE = Initiator(subject="test-delegate", kind="delegate", on_behalf_of="test-person")

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
        #: COUNTED SEPARATELY FROM `embedded`, and that separation is the point. A counter on
        #: `embed()` alone cannot see an `identity()` call — and `identity()` is not free: on the
        #: real `FleetEmbedder` it is a live request to the embed endpoint. An arm that proves
        #: "relocate does not embed" while relocate calls `identity()` every time is an arm that
        #: measures the cheaper half of the claim.
        self.identity_calls = 0

    def embed(self, text: str) -> Sequence[float]:
        self.embedded.append(text)
        if self.fail:
            raise RuntimeError("stub embedder refuses")
        return [0.5] * _STUB_DIM

    def identity(self) -> tuple[str, Optional[str], int]:
        self.identity_calls += 1
        return (self.model, None, _STUB_DIM)

    def touches(self) -> tuple[int, int]:
        """Every way this embedder can be reached, as one comparable pair."""
        return (len(self.embedded), self.identity_calls)


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

    def delete_by_id(self, uuid: Any) -> bool:  # noqa: A002
        self._c.calls.append(("delete", uuid, None, None))
        return self._c.rows.pop(uuid, None) is not None


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
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def single(self) -> Any:
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


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
        return _StubResult(list(self._d.rows))


class _StubDriver:
    def __init__(self, *, rows: Optional[list] = None, raises: BaseException = None) -> None:
        self.rows = [{"n": 1}] if rows is None else rows
        self.raises = raises
        self.queries: list[tuple[str, dict]] = []

    def session(self) -> _StubSession:
        return _StubSession(self)


#: THE REAL EXCEPTION, IMPORTED. A hand-written `class _ServiceUnavailable(Exception)` has the
#: `__name__` `_ServiceUnavailable`, so the writer's name-match never fires on it — the first draft
#: of this file did exactly that. Only the driver's own class can catch a rename in neo4j.
from neo4j.exceptions import ServiceUnavailable as _ServiceUnavailable  # noqa: E402


def _local(verb: str) -> str:
    return verb.split(":", 1)[-1]


#: A generic family for the offline arms: a type DERIVED from the verb, as the predicate family's
#: is, because that is the case where the type is computed from request data.
_FAMILY = dict(node_label="OntologyClass", node_key="uri", relationship_type=_local,
               verb_property="iri", key_property="_tool_urn")

_IDENTITY = EdgeIdentity(subject="urn:a", verb="mesh:relatesTo", object="urn:b", key="urn:tool:1")


def _graph(driver: Any = None, **over: Any) -> Neo4jGraphWriter:
    return Neo4jGraphWriter(driver=_StubDriver() if driver is None else driver,
                            **{**_FAMILY, **over})


# ── the shared offline conformance, both writers ─────────────────────────────────────────────────

def test_graph_writer_offline_conformance():
    writer = _graph()
    check_writer_offline(
        writer,
        operations=[
            ("write_edge", lambda i: writer.write_edge(i, identity=_IDENTITY)),
            ("delete_edges", lambda i: writer.delete_edges(
                i, identity_filter=EdgeIdentityFilter(key="urn:tool:1"))),
            ("write_node", lambda i: writer.write_node(i, label="OntologyClass", id="urn:a",
                                                        payload={"kind": "pdf"})),
        ],
    )


def test_has_edges_keeps_the_same_gate_and_answers_a_MeshResult():
    """`has_edges` returns a `MeshResult`, so `check_writer_offline` (which demands a
    `MeshWriteResult`) cannot carry it; its three-way gate is asserted here instead."""
    driver = _StubDriver(rows=[])
    writer = _graph(driver)
    f = EdgeIdentityFilter(key="urn:tool:1")
    with pytest.raises(ServiceIdentityRefused):
        writer.has_edges(_SERVICE, identity_filter=f)
    assert driver.queries == [], "a refused identity reached the store"
    assert isinstance(writer.has_edges(_DELEGATE, identity_filter=f), MeshResult)
    assert isinstance(writer.has_edges(_PERSON, identity_filter=f), MeshResult)


def test_vectors_writer_offline_conformance():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    check_writer_offline(
        writer,
        operations=[
            ("write", lambda i: writer.write(i, collection="Scratch", id="row-1", text="hello")),
            ("relocate", lambda i: writer.relocate(
                i, collection="Scratch", id="row-1", vector=[0.5] * _STUB_DIM)),
            ("delete", lambda i: writer.delete(i, collection="Scratch", id="row-1")),
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


def test_relocate_after_a_write_touches_the_embedder_zero_times():
    """A relocate takes a PRECOMPUTED vector, so it has no business reaching the embed endpoint.

    The first draft called ``identity()`` on every relocate for the dimension to check against,
    which on ``FleetEmbedder`` is a live request: a relocate would then FAIL while the embed
    endpoint was down, reporting ``unreachable`` about a service it did not need, and would spend a
    round trip per call on a number that does not move. The writer now uses the dimension it
    OBSERVED when it last stored a vector.

    Asserted on ``touches()``, both channels, because the interesting call was never ``embed()``.
    """
    client = _StubClient()
    embedder = _StubEmbedder()
    writer = WeaviateVectorsWriter(client=client, embedder=embedder)
    writer.write(_PERSON, collection="Scratch", id="row-1", text="hello")

    before = embedder.touches()
    assert writer.relocate(
        _PERSON, collection="Scratch", id="row-1", vector=[0.9] * _STUB_DIM).outcome == "written"
    assert embedder.touches() == before, (
        f"relocate reached the embedder: (embed, identity) went {before} -> {embedder.touches()}"
    )


def test_the_observed_dimension_still_refuses_a_mismatch_without_asking_the_embedder():
    """The guard must survive being made cheaper — the memo REPLACES the probe, it does not
    replace the check. A relocate at the wrong dimension is still refused, and still without a
    call, so the saving cannot have come from skipping the comparison."""
    client = _StubClient()
    embedder = _StubEmbedder()
    writer = WeaviateVectorsWriter(client=client, embedder=embedder)
    writer.write(_PERSON, collection="Scratch", id="row-1", text="hello")

    before = embedder.touches()
    result = writer.relocate(
        _PERSON, collection="Scratch", id="row-1", vector=[0.1] * (_STUB_DIM + 1))
    assert result.outcome == "refused", result
    assert str(_STUB_DIM) in result.detail
    assert embedder.touches() == before


def test_a_relocate_before_any_write_falls_back_to_the_probe_rather_than_guessing():
    """The fallback path is REACHABLE and is not a constant.

    Nothing has been stored, so no dimension has been observed. The writer must ask rather than
    assume a number — a dimension invented in this module would be the fleet's next locally
    invented default — and the arm proves the ask happens by counting it.
    """
    client = _StubClient()
    embedder = _StubEmbedder()
    writer = WeaviateVectorsWriter(client=client, embedder=embedder)
    # `**named_vector_config()` ON A DOUBLE, WHERE IT CHANGES NO BEHAVIOUR, FOR TWO REASONS.
    #
    # (1) THE SEAL THIS COMMIT'S SIBLING WIDENED CAUGHT THIS LINE, and it was right to. That arm
    # (`tests/routing/test_a_vector_is_written_where_the_search_looks.py`) sweeps every
    # `collections.create` in the tree and refuses any that declares no vector configuration,
    # deliberately WITHOUT an exemption list — because an allow-list's population is every name that
    # could be added to it, and "it's only a test double" is exactly the excuse that would retire it.
    # A static walk cannot tell a real client from a stub, and the field that would discriminate is
    # the one nobody would keep accurate. So the call conforms instead of the seal excusing it.
    #
    # (2) INDEPENDENTLY, A DOUBLE FED A CALL PRODUCTION NEVER MAKES IS A WEAKER DOUBLE. The writer's
    # own creates pass `**named_vector_config()` (weaviate_vectors.py:391, :424). A stub exercised
    # with a bare create is being asked to accept a shape the real client is never handed, which is
    # how a double comes to prove the writer against a store that would have refused it.
    client.collections.create(name="Scratch", **named_vector_config())
    client.collections.by_name["Scratch"].rows[_row_uuid("Scratch", "row-1")] = ({}, None)

    assert embedder.touches() == (0, 0)
    result = writer.relocate(
        _PERSON, collection="Scratch", id="row-1", vector=[0.1] * (_STUB_DIM + 1))
    assert result.outcome == "refused", result
    assert embedder.identity_calls == 1, "the dimension was not asked for — was it assumed?"
    assert embedder.embedded == [], "a relocate embedded something"


# ── the SDK's own vectors arms, against the double ──────────────────────────────────────────────

def _vectors_pair(client: Any, **kw: Any):
    good = _StubEmbedder()
    writer = WeaviateVectorsWriter(client=client, embedder=good, **kw)
    failing = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder(fail=True), **kw)
    return writer, failing, good


def _run_vectors_contracts(client: Any, collection: str, contains: Any, **kw: Any) -> None:
    """The SDK's write/relocate and delete arms. Shared by the offline and the live run, so the
    two differ in the client alone."""
    writer, failing, good = _vectors_pair(client, **kw)
    assert writer.write(_PERSON, collection=collection, id="row-1", text="hello").outcome == "written"
    check_vectors_writer_contract(
        call_write_with_failing_embedder=lambda: failing.write(
            _PERSON, collection=collection, id="row-f", text="t"),
        call_write_with_failing_embedder_opted_out=lambda: failing.write(
            _PERSON, collection=collection, id="row-g", text="t", vector_required=False),
        call_relocate_matching_dimension=lambda: writer.relocate(
            _PERSON, collection=collection, id="row-1", vector=[0.25] * _STUB_DIM),
        call_relocate_wrong_dimension=lambda: writer.relocate(
            _PERSON, collection=collection, id="row-1", vector=[0.25] * (_STUB_DIM + 1)),
        # BOTH ways the embedder can be reached, not only `embed()` — see `_StubEmbedder.touches`.
        embed_call_count=lambda: sum(good.touches()),
    )
    check_vectors_writer_delete_contract(
        call_write=lambda: writer.write(_PERSON, collection=collection, id="row-d", text="bye"),
        call_delete_written=lambda: writer.delete(_PERSON, collection=collection, id="row-d"),
        call_delete_never_written=lambda: writer.delete(
            _PERSON, collection=collection, id="never-written"),
        contains_after_delete=lambda: contains(collection, "row-d"),
    )


def test_the_sdk_vectors_contracts_hold_against_the_double():
    client = _StubClient()
    _run_vectors_contracts(
        client, "Scratch",
        lambda c, i: _row_uuid(c, i) in client.collections.by_name[c].rows)


# ── delete ──────────────────────────────────────────────────────────────────────────────────────

def test_delete_addresses_the_SAME_uuid_the_write_used_and_nothing_else():
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    writer.write(_PERSON, collection="S", id="keep", text="a")
    writer.write(_PERSON, collection="S", id="drop", text="b")
    assert writer.delete(_PERSON, collection="S", id="drop").outcome == "written"
    rows = client.collections.by_name["S"].rows
    assert _row_uuid("S", "drop") not in rows
    assert _row_uuid("S", "keep") in rows, "the delete reached a row it did not name"


def test_a_delete_on_an_absent_collection_is_written_and_CREATES_nothing():
    """Idempotent, and the trace of removing nothing is nothing — not an empty, marker-stamped
    collection that a create-on-demand would leave behind."""
    client = _StubClient()
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    assert writer.delete(_PERSON, collection="Never", id="x").outcome == "written"
    assert client.collections.by_name == {}


def test_a_delete_with_an_empty_argument_is_refused_before_the_store():
    client = _StubClient()
    client.collections = _ExplodingCollections(AssertionError("the store was touched"))
    writer = WeaviateVectorsWriter(client=client, embedder=_StubEmbedder())
    for kw in ({"collection": "", "id": "x"}, {"collection": "S", "id": "  "}):
        assert writer.delete(_PERSON, **kw).outcome == "refused", kw


def test_a_delete_splits_transport_from_store():
    gone = _StubClient()
    gone.collections = _ExplodingCollections(
        type("WeaviateConnectionError", (Exception,), {})("no route"))
    broken = _StubClient()
    broken.collections = _ExplodingCollections(ValueError("the store said no"))
    a = WeaviateVectorsWriter(client=gone, embedder=_StubEmbedder()).delete(
        _PERSON, collection="S", id="x")
    b = WeaviateVectorsWriter(client=broken, embedder=_StubEmbedder()).delete(
        _PERSON, collection="S", id="x")
    assert (a.outcome, b.outcome) == ("unreachable", "failed")


def test_the_marker_carrier_is_the_sdks_by_default_and_the_callers_when_named():
    default = _StubClient()
    WeaviateVectorsWriter(client=default, embedder=_StubEmbedder()).write(
        _PERSON, collection="S", id="r", text="t")
    named = _StubClient()
    WeaviateVectorsWriter(client=named, embedder=_StubEmbedder(),
                          meta_collection="ScratchMeta").write(
        _PERSON, collection="S", id="r", text="t")
    assert MESH_COLLECTION_META in default.collections.by_name
    assert "ScratchMeta" in named.collections.by_name
    assert MESH_COLLECTION_META not in named.collections.by_name, (
        "a named carrier still stamped the shared one — a scratch run would leave a marker for a "
        "collection it is about to delete")


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
    assert _graph().write_edge(_PERSON, identity=_IDENTITY).outcome == "written"
    gone = _graph(_StubDriver(raises=_ServiceUnavailable("bolt down")))
    assert gone.write_edge(_PERSON, identity=_IDENTITY).outcome == "unreachable"
    # APOC absent, a constraint violation: the store was asked and said no. `failed`.
    refused_by_store = _graph(_StubDriver(
        raises=type("ClientError", (Exception,), {})("no procedure apoc.merge")))
    out = refused_by_store.write_edge(_PERSON, identity=_IDENTITY)
    assert out.outcome == "failed" and "apoc" in out.detail.lower(), out
    # The same split on the delete and existence paths.
    f = EdgeIdentityFilter(key="urn:tool:1")
    assert gone.delete_edges(_PERSON, identity_filter=f).outcome == "unreachable"
    assert refused_by_store.delete_edges(_PERSON, identity_filter=f).outcome == "failed"
    assert gone.has_edges(_PERSON, identity_filter=f).outcome == "unreachable"
    assert refused_by_store.has_edges(_PERSON, identity_filter=f).outcome == "failed"


@pytest.mark.parametrize("rows", [[], [{"n": 0}]], ids=["no-record", "zero-merged"])
def test_a_missing_endpoint_is_failed_and_NAMED_so_a_caller_can_tell_it_from_a_fault(rows):
    out = _graph(_StubDriver(rows=rows)).write_edge(_PERSON, identity=_IDENTITY)
    assert out.outcome == "failed", out
    assert out.detail.startswith(f"{ENDPOINT_ABSENT}:"), out.detail
    # THE CONTROL: a store fault is ALSO `failed`, and must NOT carry the prefix — the prefix is
    # the only thing that lets the registrar file one as `unresolved` and raise on the other.
    fault = _graph(_StubDriver(raises=ValueError("boom"))).write_edge(_PERSON, identity=_IDENTITY)
    assert fault.outcome == "failed" and not fault.detail.startswith(ENDPOINT_ABSENT), fault


def test_a_delete_matching_nothing_is_written():
    out = _graph(_StubDriver(rows=[{"n": 0}])).delete_edges(
        _PERSON, identity_filter=EdgeIdentityFilter(key="urn:none"))
    assert out.outcome == "written", out


def test_has_edges_answers_rows_and_says_empty_when_there_are_none():
    row = {"subject": "urn:a", "verb": "mesh:relatesTo", "object": "urn:b", "key": "urn:tool:1"}
    f = EdgeIdentityFilter(key="urn:tool:1")
    found = _graph(_StubDriver(rows=[row])).has_edges(_PERSON, identity_filter=f)
    none = _graph(_StubDriver(rows=[])).has_edges(_PERSON, identity_filter=f)
    assert (found.outcome, none.outcome) == ("answered", "empty")
    assert list(found.rows) == [row]


# ── nothing a caller sends reaches the query text ──────────────────────────────────────────────

_HOSTILE = "x`]->() DETACH DELETE n //"


def test_no_request_field_is_ever_interpolated_on_any_path():
    """The strongest property this writer has, asserted on all three paths and all four fields —
    including the relationship TYPE, which a derived-type family computes from the verb and which
    plain Cypher cannot parameterise in a pattern."""
    driver = _StubDriver()
    writer = _graph(driver, relationship_type=lambda v: v)  # the type IS the hostile verb
    ident = EdgeIdentity(subject=_HOSTILE + "s", verb=_HOSTILE + "v", object=_HOSTILE + "o",
                         key=_HOSTILE + "k")
    filt = EdgeIdentityFilter(subject=ident.subject, verb=ident.verb, object=ident.object,
                              key=ident.key)
    writer.write_edge(_PERSON, identity=ident, payload={"note": _HOSTILE})
    writer.delete_edges(_PERSON, identity_filter=filt)
    writer.has_edges(_PERSON, identity_filter=filt)
    assert len(driver.queries) == 3
    for cypher, params in driver.queries:
        assert _HOSTILE not in cypher and "DETACH" not in cypher, cypher
        assert params["rel_type"] == ident.verb, "the type must arrive as a parameter"
    w_params = driver.queries[0][1]
    assert (w_params["subject"], w_params["object"]) == (ident.subject, ident.object)
    assert w_params["identity"] == {"iri": ident.verb, "_tool_urn": ident.key}
    for _cypher, params in driver.queries[1:]:
        assert (params["subject"], params["object"], params["verb"], params["edge_key"]) == (
            ident.subject, ident.object, ident.verb, ident.key)


@pytest.mark.parametrize("field", ["node_label", "node_key", "verb_property", "key_property"])
def test_config_that_reaches_the_query_text_is_refused_at_CONSTRUCTION(field):
    with pytest.raises(ValueError, match="identifier"):
        _graph(**{field: "uri` WITH 1 AS x //"})
    # The control: the legal value of the same field is accepted, or the arm passes for the
    # wrong reason.
    assert isinstance(_graph(**{field: "Legal_Name1"}), Neo4jGraphWriter)


def test_a_writer_whose_verb_and_key_are_one_property_is_refused():
    with pytest.raises(ValueError, match="one property"):
        _graph(verb_property="iri", key_property="iri")


# ── write_node: an UPSERT, the opposite of write_edge's key-grants-multiplicity rule ────────────

def test_write_node_is_a_single_MERGE_keyed_by_label_and_id_not_two_different_writes():
    """The `_StubDriver` is stateless — it cannot show a second write landing on the first node —
    so this proves the UPSERT structurally instead, the same way the SDK's own
    `check_graph_writer_write_node_contract` proves it against a real store: two calls at the SAME
    (label, id) with DIFFERING payloads must emit the IDENTICAL Cypher text (one `MERGE`, no
    `ON CREATE`/`ON MATCH` branch to pick between) and the SAME `id` parameter — only `props`
    differs. A writer that appended (write_edge's rule) or branched on existence would show up
    here as either two distinct query texts or a second `id`."""
    driver = _StubDriver()
    writer = _graph(driver)
    first = writer.write_node(_PERSON, label="OntologyClass", id="urn:a", payload={"kind": "pdf"})
    second = writer.write_node(_PERSON, label="OntologyClass", id="urn:a",
                               payload={"kind": "docx"})
    assert first.outcome == second.outcome == "written"
    assert len(driver.queries) == 2
    (c1, p1), (c2, p2) = driver.queries
    assert c1 == c2, "the SAME (label, id) must produce the SAME query text on every call"
    assert "MERGE" in c1 and "ON CREATE" not in c1 and "ON MATCH" not in c1
    assert p1["id"] == p2["id"] == "urn:a"
    assert p1["props"] != p2["props"], "the SECOND write's payload must be the one that travels"
    assert p1["props"]["kind"] == "pdf" and p2["props"]["kind"] == "docx"


def test_a_hostile_label_is_refused_before_the_store():
    driver = _StubDriver()
    out = _graph(driver).write_node(_PERSON, label=_HOSTILE, id="urn:a")
    assert out.outcome == "refused", out
    assert driver.queries == [], "a refused label reached the store"


def test_a_legal_label_is_accepted_the_CONTROL_for_the_hostile_one_above():
    driver = _StubDriver()
    out = _graph(driver).write_node(_PERSON, label="Legal_Name1", id="urn:a")
    assert out.outcome == "written", out
    assert "Legal_Name1" in driver.queries[0][0]


def test_write_node_an_empty_id_is_refused_before_the_store():
    driver = _StubDriver()
    out = _graph(driver).write_node(_PERSON, label="OntologyClass", id="   ")
    assert out.outcome == "refused", out
    assert driver.queries == []


def test_write_node_no_request_field_reaches_the_query_text_except_the_validated_label():
    """Mirrors `test_no_request_field_is_ever_interpolated_on_any_path` for the one write_node
    adds: `label` legitimately reaches the query text (validated against `_SAFE_IDENTIFIER` first,
    see `_graph.write_node`'s docstring) — `id` and the payload never do, both staying PARAMETERS."""
    driver = _StubDriver()
    writer = _graph(driver)
    out = writer.write_node(_PERSON, label="OntologyClass", id=_HOSTILE + "id",
                            payload={"note": _HOSTILE})
    assert out.outcome == "written", out
    cypher, params = driver.queries[0]
    assert _HOSTILE not in cypher and "DETACH" not in cypher, cypher
    assert params["id"] == _HOSTILE + "id", "id must arrive as a parameter, verbatim"
    assert params["props"]["note"] == _HOSTILE


def test_a_node_payload_naming_the_node_key_property_is_REFUSED():
    """`_FAMILY`'s node_key is `uri` — identity for write_node comes from the call's own `id`
    argument, never from the payload riding beside it, same rule `write_edge` enforces for its
    verb/key properties."""
    driver = _StubDriver()
    out = _graph(driver).write_node(_PERSON, label="OntologyClass", id="urn:a",
                                    payload={"uri": "other"})
    assert out.outcome == "refused", out
    assert driver.queries == []


# ── identity is identity; payload rides beside it ───────────────────────────────────────────────

def test_identity_is_the_merge_key_and_is_also_written_as_properties():
    driver = _StubDriver()
    _graph(driver).write_edge(_PERSON, identity=_IDENTITY, payload={"cost_class": "fast"})
    _cypher, p = driver.queries[0]
    assert p["identity"] == {"iri": _IDENTITY.verb, "_tool_urn": _IDENTITY.key}
    # On CREATE, apoc sets only the props map — so identity must be in it, or the readers that
    # filter on `r.iri`/`r._tool_urn` would never see the edge.
    assert p["props"] == {"cost_class": "fast", "iri": _IDENTITY.verb,
                          "_tool_urn": _IDENTITY.key}
    assert p["rel_type"] == "relatesTo"


@pytest.mark.parametrize("prop", ["iri", "_tool_urn"])
def test_a_payload_naming_an_identity_property_is_REFUSED(prop):
    driver = _StubDriver()
    out = _graph(driver).write_edge(_PERSON, identity=_IDENTITY, payload={prop: "other"})
    assert out.outcome == "refused", out
    assert driver.queries == []


@pytest.mark.parametrize("payload", [
    {"m": {"nested": 1}},
    {"m": None},
    {"m": [[1]]},
    {"m": [1, "a"]},
    {"m": [True, 1]},
    {"": "x"},
    {1: "x"},
], ids=["map", "none", "nested-list", "mixed-list", "bool-int-list", "blank-key", "int-key"])
def test_a_payload_the_store_cannot_hold_is_REFUSED_WHOLE_never_stripped(payload):
    driver = _StubDriver()
    out = _graph(driver).write_edge(
        _PERSON, identity=_IDENTITY, payload={"keep": "me", **payload})
    assert out.outcome == "refused", out
    assert driver.queries == [], "a refusal reached the store — `refused` means before it"


def test_the_payload_neo4j_CAN_hold_lands_with_its_types_intact():
    """THE CONTROL for the refusals above, and the registrar's real shape: lists and a bool."""
    payload = {"s": "x", "i": 3, "f": 0.5, "b": False, "domains": ("a", "b"), "empty": [],
               "synonyms": ["one"]}
    driver = _StubDriver()
    assert _graph(driver).write_edge(_PERSON, identity=_IDENTITY, payload=payload).outcome \
        == "written"
    props = driver.queries[0][1]["props"]
    assert props["domains"] == ["a", "b"] and props["b"] is False and props["empty"] == []


def test_an_identity_that_is_not_an_EdgeIdentity_is_refused_before_the_store():
    driver = _StubDriver()
    writer = _graph(driver)
    assert writer.write_edge(_PERSON, identity=dict(_IDENTITY)).outcome == "refused"
    assert writer.delete_edges(_PERSON, identity_filter={"key": "k"}).outcome == "refused"
    assert driver.queries == []


# ── the family discriminator: why a key-only sweep cannot cross families ────────────────────────

def _where_line(cypher: str) -> str:
    (line,) = [ln for ln in cypher.splitlines() if ln.startswith("WHERE ")]
    return line


@pytest.mark.parametrize("path", ["delete_edges", "has_edges"])
def test_the_family_discriminator_is_UNCONDITIONAL_on_both_filter_paths(path):
    """Both identity properties must be PRESENT on every edge a filter path can touch, whatever the
    filter binds. Derived from the writer's own configuration, never restated: a family whose verb
    property is `verb_iri` must be discriminated on `verb_iri`."""
    for family in (_FAMILY, {**_FAMILY, "relationship_type": "PARAMETERISED_BY",
                             "verb_property": "verb_iri"}):
        driver = _StubDriver(rows=[])
        writer = _graph(driver, **family)
        getattr(writer, path)(_PERSON, identity_filter=EdgeIdentityFilter(key="k"))
        where = _where_line(driver.queries[0][0])
        assert where == (f"WHERE mesh_r.{family['verb_property']} IS NOT NULL "
                         f"AND mesh_r.{family['key_property']} IS NOT NULL"), where


def test_a_derived_type_narrows_only_when_the_verb_is_bound_and_a_fixed_type_always():
    derived = _StubDriver(rows=[])
    _graph(derived).delete_edges(_PERSON, identity_filter=EdgeIdentityFilter(key="k"))
    _graph(derived).delete_edges(_PERSON, identity_filter=EdgeIdentityFilter(verb="mesh:v"))
    fixed = _StubDriver(rows=[])
    _graph(fixed, relationship_type="PARAMETERISED_BY").delete_edges(
        _PERSON, identity_filter=EdgeIdentityFilter(key="k"))
    assert [q[1]["rel_type"] for q in derived.queries] == [None, "v"]
    assert fixed.queries[0][1]["rel_type"] == "PARAMETERISED_BY"


# ── the gate RAISES, on every operation of both writers ─────────────────────────────────────────

def test_a_service_identity_RAISES_and_does_not_return_a_refused_result():
    """Held separately from the conformance arm so a change to the SDK's suite cannot silently
    retire the one property this layer exists for. A ``refused`` is a value, and a caller that
    drops it has silently made an unauthorized write disappear."""
    graph = _graph()
    vectors = WeaviateVectorsWriter(client=_StubClient(), embedder=_StubEmbedder())
    f = EdgeIdentityFilter(key="k")
    for call in (
        lambda: graph.write_edge(_SERVICE, identity=_IDENTITY),
        lambda: graph.delete_edges(_SERVICE, identity_filter=f),
        lambda: graph.has_edges(_SERVICE, identity_filter=f),
        lambda: graph.write_node(_SERVICE, label="OntologyClass", id="urn:a"),
        lambda: vectors.write(_SERVICE, collection="S", id="r", text="t"),
        lambda: vectors.relocate(_SERVICE, collection="S", id="r", vector=[0.1] * _STUB_DIM),
        lambda: vectors.delete(_SERVICE, collection="S", id="r"),
    ):
        with pytest.raises(ServiceIdentityRefused):
            call()
    # AND THE STORE WAS NEVER TOUCHED. A raise after the write would be a refusal in name only.
    assert graph._driver.queries == []  # noqa: SLF001
    assert vectors._client.collections.by_name == {}  # noqa: SLF001


def test_a_delegate_is_admitted_where_a_service_is_not():
    """Asserted as a DIFFERENCE: the two fixtures differ in exactly `on_behalf_of`."""
    assert_fixture_discriminates(
        "delegate vs service", _DELEGATE, _SERVICE, describe=lambda i: i.on_behalf_of)
    writer = WeaviateVectorsWriter(client=_StubClient(), embedder=_StubEmbedder())
    assert writer.write(_DELEGATE, collection="S", id="r", text="t").outcome == "written"
    assert _graph().write_edge(_DELEGATE, identity=_IDENTITY).outcome == "written"
    assert _graph().write_node(_DELEGATE, label="OntologyClass", id="urn:a").outcome == "written"
    with pytest.raises(ServiceIdentityRefused):
        writer.write(_SERVICE, collection="S", id="r", text="t")
    with pytest.raises(ServiceIdentityRefused):
        _graph().write_node(_SERVICE, label="OntologyClass", id="urn:a")


def _the_transport_modules():
    """Each driver's exception module beside the name set its writer matches on.

    THE MODULE COMES FROM `sys.modules`, NEVER FROM AN ATTRIBUTE OF ITS PACKAGE. `import
    neo4j.exceptions` binds `neo4j` and then reads `.exceptions` off it, and a package that was
    re-imported while its submodule stayed cached has no such attribute. Measured 2026-10-01:
    `tests/routing/test_adr0019_pipeline_integrity.py` pops `sys.modules["neo4j"]` at import and
    re-imports the driver, so this seal went red in the full suite and green alone, with
    `AttributeError: module neo4j has no attribute exceptions`. `importlib.import_module` returns
    the cached entry and does not read the package's attribute.
    """
    from agent_fleet.utils.mesh_writers import neo4j_graph, weaviate_vectors

    return (
        (importlib.import_module("neo4j.exceptions"), neo4j_graph._TRANSPORT),          # noqa: SLF001
        (importlib.import_module("weaviate.exceptions"), weaviate_vectors._TRANSPORT),  # noqa: SLF001
    )


def test_every_transport_name_the_writers_match_on_is_a_real_exception():
    """A NAME-MATCHED SET IS A SET OF STRINGS, AND A TYPO IN ONE IS A GUARD THAT CANNOT FIRE."""
    for module, names in _the_transport_modules():
        assert names, f"{module.__name__}: the transport set is empty"
        for name in names:
            resolved = getattr(module, name, None)
            assert isinstance(resolved, type) and issubclass(resolved, BaseException), (
                f"{module.__name__}.{name} is not an exception class — a transport failure will "
                f"be reported as a store failure for as long as the name is wrong")



@pytest.mark.parametrize("package", ["neo4j", "weaviate"])
def test_the_transport_seal_survives_a_package_without_its_submodule_attribute(monkeypatch, package):
    """The state the full suite leaves, made in-process: the submodule cached in `sys.modules`,
    the package object without the attribute. The seal must still read the names it checks."""
    import sys

    importlib.import_module(f"{package}.exceptions")
    monkeypatch.delattr(sys.modules[package], "exceptions", raising=False)
    test_every_transport_name_the_writers_match_on_is_a_real_exception()

# ── the live half: scratch only, torn down ──────────────────────────────────────────────────────

_LIVE = bool(os.environ.get("IAGENT_WRITER_SCRATCH"))
_LIVE_GRAPH = _LIVE and bool(os.environ.get("NEO4J_URI"))
_LIVE_VECTORS = _LIVE and bool(os.environ.get("WEAVIATE_HTTP_HOST"))

_SCRATCH_URIS = [f"urn:mesh-writer-scratch:{n}" for n in ("s1", "o1", "s2", "o2")]


def _scratch_prefix(toplevel: Path | None = None, today: datetime.date | None = None) -> str:
    """`MeshWriterScratch_<lane>_<yyyymmdd>_`: every scratch name the live arms create carries the
    lane that wrote it and the day, so a census of either store can attribute a residue without
    this file's help. DERIVED, never typed: the lane is the worktree directory's `ia-NN` suffix
    (the charter's worktree<->lane mapping), the date is the run's own."""
    top = toplevel or Path(__file__).resolve().parents[1]
    m = re.fullmatch(r"ia-([0-9a-z]+)", top.name)
    lane = m.group(1) if m else "master"
    return f"MeshWriterScratch_{lane}_{(today or datetime.date.today()):%Y%m%d}_"


def test_the_scratch_prefix_names_the_lane_and_the_day():
    day = datetime.date(2026, 9, 30)
    assert _scratch_prefix(Path("/x/ia-74"), day) == "MeshWriterScratch_74_20260930_"
    assert _scratch_prefix(Path("/x/invincible-agent"), day) == "MeshWriterScratch_master_20260930_"
    # a Neo4j label and a Weaviate collection name both accept it unquoted
    assert re.fullmatch(r"[A-Z][A-Za-z0-9_]*", _scratch_prefix(Path("/x/ia-5f"), day) + "ab12")


def _scratch_edge_reader(driver: Any, label: str):
    """``Neo4jGraph.edge()``'s own query with exactly two substitutions, each anchor-counted —
    see the module docstring for why each is a finding and not a fixture choice."""
    from agent_fleet.ontology_service.mesh_graph import Neo4jGraph

    src = inspect.getsource(Neo4jGraph.edge)
    (cypher,) = re.findall(r'"""\s*(MATCH.*?)"""', src, re.S)
    assert cypher.count("OntologyClass") == 2, cypher
    assert cypher.count("LIMIT 1") == 1, cypher
    cypher = cypher.replace("OntologyClass", label).replace("LIMIT 1", "")
    graph = Neo4jGraph(driver=driver)

    def edge(subject: str, verb: str) -> MeshResult:
        return graph._read("edge", cypher, subject=subject, verb=verb)  # noqa: SLF001

    return edge


@pytest.fixture
def scratch_graph():
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ.get("NEO4J_USERNAME", "neo4j"), os.environ["NEO4J_PASSWORD"]))
    label = f"{_scratch_prefix()}{uuid.uuid4().hex[:12]}"
    with driver.session() as s:
        assert s.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"] == 0
        s.run(f"UNWIND $uris AS u CREATE (:{label} {{uri: u}})", uris=_SCRATCH_URIS)
    try:
        yield driver, label
    finally:
        with driver.session() as s:
            s.run(f"MATCH (n:{label}) DETACH DELETE n")
            left = s.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
        driver.close()
        assert left == 0, f"scratch label {label} not torn down: {left} node(s) remain"


def _live_writer(driver: Any, label: str, family: dict) -> Neo4jGraphWriter:
    # THE PRODUCTION FAMILY with one thing changed — the label — so what is proven is the
    # registrar's own configuration, not a configuration written for the test.
    return Neo4jGraphWriter(driver=driver, **{**family, "node_label": label})


@pytest.mark.skipif(not _LIVE_GRAPH, reason="IAGENT_WRITER_SCRATCH + NEO4J_URI unset")
def test_LIVE_the_sdk_graph_arms_hold_on_the_predicate_family(scratch_graph):
    from agent_fleet.mesh_registrar.v2_substrate import PREDICATE_EDGE_FAMILY

    driver, label = scratch_graph
    w = _live_writer(driver, label, PREDICATE_EDGE_FAMILY)
    read = _scratch_edge_reader(driver, label)
    s1, o1, s2, o2 = _SCRATCH_URIS
    verb, other = "mesh:scratchVerb", "mesh:scratchOther"

    def ident(key: str, s: str = s1, v: str = verb, o: str = o1) -> EdgeIdentity:
        return EdgeIdentity(subject=s, verb=v, object=o, key=key)

    check_graph_writer_contract(
        call_write_edge=lambda: w.write_edge(_PERSON, identity=ident("k1")),
        call_read_written_edge=lambda: read(s1, verb),
        call_read_unwritten_edge=lambda: read(s1, other),
        call_write_edge_same_verb_different_key=lambda: w.write_edge(
            _PERSON, identity=ident("k2")),
        call_read_edge_after_both_keys=lambda: read(s1, verb),
        call_delete_edge_by_identity=lambda: w.delete_edges(
            _PERSON, identity_filter=EdgeIdentityFilter(**dict(ident("k1")))),
        call_read_edge_after_delete=lambda: read(s1, verb),
    )
    check_graph_writer_has_edges_contract(
        call_write_edge=lambda: w.write_edge(_PERSON, identity=ident("k3", s=s2, o=o2)),
        call_has_edges_matching=lambda: w.has_edges(
            _PERSON, identity_filter=EdgeIdentityFilter(key="k3")),
        call_has_edges_not_matching=lambda: w.has_edges(
            _PERSON, identity_filter=EdgeIdentityFilter(key="k-never")),
    )
    check_graph_writer_key_only_delete_contract(
        call_write_edge_a=lambda: w.write_edge(_PERSON, identity=ident("shared")),
        call_write_edge_b_same_key_different_triple=lambda: w.write_edge(
            _PERSON, identity=ident("shared", s=s2, v=other, o=o2)),
        call_delete_by_key_only=lambda: w.delete_edges(
            _PERSON, identity_filter=EdgeIdentityFilter(key="shared")),
        call_read_edge_a_after_delete=lambda: w.has_edges(
            _PERSON, identity_filter=EdgeIdentityFilter(subject=s1, verb=verb, key="shared")),
        call_read_edge_b_after_delete=lambda: w.has_edges(
            _PERSON, identity_filter=EdgeIdentityFilter(subject=s2, verb=other, key="shared")),
    )


def _drive_write_node_contract(driver: Any, label: str) -> None:
    """The SDK's `check_graph_writer_write_node_contract`, driven through the INGEST family -- the
    configuration `Neo4jIngestGraph` constructs its writer from -- with one thing changed: the
    label, a scratch one. The introspection answers a payload only when EXACTLY ONE node sits at
    (label, id): a store that appended would make the id reachable as two nodes, and the SDK arm
    has no read of its own that could see that, so the fixture refuses to name either of them."""
    from iagent.promotion_stores import INGEST_FACT_FAMILY

    w = _live_writer(driver, label, INGEST_FACT_FAMILY)
    key = INGEST_FACT_FAMILY["node_key"]
    node_id = "urn:mesh-writer-scratch:node"

    def payload() -> dict | None:
        with driver.session() as s:
            rows = s.run(f"MATCH (n:{label} {{{key}: $id}}) RETURN properties(n) AS p",
                         id=node_id).data()
        if len(rows) != 1:
            return None
        return {k: v for k, v in rows[0]["p"].items() if k != key}

    check_graph_writer_write_node_contract(
        call_write_node=lambda: w.write_node(
            _PERSON, label=label, id=node_id, payload={"kind": "pdf", "stage": "received"}),
        node_payload_after_write=payload,
        call_write_node_again_same_id_different_payload=lambda: w.write_node(
            _PERSON, label=label, id=node_id, payload={"kind": "pdf", "stage": "extracting"}),
        node_payload_after_second_write=payload,
    )


@pytest.mark.skipif(not _LIVE_GRAPH, reason="IAGENT_WRITER_SCRATCH + NEO4J_URI unset")
def test_LIVE_the_sdk_write_node_arm_holds_on_the_ingest_family(scratch_graph):
    """SDK 0.9.6's gate: the fleet's real writer passes `check_graph_writer_write_node_contract`
    against a real store, at the SDK sha the caller ships."""
    driver, label = scratch_graph
    _drive_write_node_contract(driver, label)


_NON_UPSERTS = {
    # appends: the id becomes reachable as two nodes, so the second read names no ONE node
    "append": ("CREATE (n:{label} {{{key}: $id}}) SET n += $props RETURN count(n) AS n",
               "the second write reported success"),
    # keeps the first write: the second payload never lands, so both reads are the same
    "first-write-wins": ("MERGE (n:{label} {{{key}: $id}}) ON CREATE SET n += $props "
                         "RETURN count(n) AS n", "does not discriminate"),
}


@pytest.mark.skipif(not _LIVE_GRAPH, reason="IAGENT_WRITER_SCRATCH + NEO4J_URI unset")
@pytest.mark.parametrize("name", sorted(_NON_UPSERTS))
def test_LIVE_the_write_node_arm_reds_on_each_non_upsert(scratch_graph, monkeypatch, name):
    """The control: the arm above is worth only what it refuses. Each template is a store
    behaviour the SDK contract names as the defect, and the live arm must red on both -- at
    the check that defect reaches, not merely somewhere."""
    from agent_fleet.utils.mesh_writers import neo4j_graph

    assert neo4j_graph._WRITE_NODE.count("MERGE") == 1  # noqa: SLF001 -- the subject replaced
    template, reached = _NON_UPSERTS[name]
    monkeypatch.setattr(neo4j_graph, "_WRITE_NODE", template)
    driver, label = scratch_graph
    with pytest.raises(ConformanceFailure, match=reached):
        _drive_write_node_contract(driver, label)


@pytest.mark.skipif(not _LIVE_GRAPH, reason="IAGENT_WRITER_SCRATCH + NEO4J_URI unset")
def test_LIVE_a_key_only_sweep_cannot_cross_families(scratch_graph):
    """Two families, same endpoints, same key. A key-only delete through one leaves the other's
    edge standing — the discriminator, proven against a store rather than read off a string."""
    from agent_fleet.mesh_registrar.v2_substrate import (
        PARAMETERISED_BY_FAMILY,
        PREDICATE_EDGE_FAMILY,
    )

    driver, label = scratch_graph
    pred = _live_writer(driver, label, PREDICATE_EDGE_FAMILY)
    param = _live_writer(driver, label, PARAMETERISED_BY_FAMILY)
    s1, o1, *_ = _SCRATCH_URIS
    ident = EdgeIdentity(subject=s1, verb="mesh:scratchVerb", object=o1, key="urn:tool:same")
    assert pred.write_edge(_PERSON, identity=ident).outcome == "written"
    assert param.write_edge(_PERSON, identity=ident).outcome == "written"
    key_only = EdgeIdentityFilter(key="urn:tool:same")
    assert pred.delete_edges(_PERSON, identity_filter=key_only).outcome == "written"
    assert pred.has_edges(_PERSON, identity_filter=key_only).outcome == "empty"
    assert param.has_edges(_PERSON, identity_filter=key_only).outcome == "answered", (
        "the predicate family's key-only sweep deleted a PARAMETERISED_BY edge")


@pytest.mark.skipif(not _LIVE_GRAPH, reason="IAGENT_WRITER_SCRATCH + NEO4J_URI unset")
def test_LIVE_an_absent_endpoint_is_named_and_NO_node_is_created(scratch_graph):
    from agent_fleet.mesh_registrar.v2_substrate import PREDICATE_EDGE_FAMILY

    driver, label = scratch_graph
    w = _live_writer(driver, label, PREDICATE_EDGE_FAMILY)
    out = w.write_edge(_PERSON, identity=EdgeIdentity(
        subject=_SCRATCH_URIS[0], verb="mesh:scratchVerb", object="urn:mesh-writer-scratch:nope",
        key="k"))
    assert out.outcome == "failed" and out.detail.startswith(ENDPOINT_ABSENT), out
    with driver.session() as s:
        n = s.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()["n"]
    assert n == len(_SCRATCH_URIS), "a write with an absent endpoint created a node"


@pytest.mark.skipif(not _LIVE_GRAPH, reason="IAGENT_WRITER_SCRATCH + NEO4J_URI unset")
def test_LIVE_the_registrars_payload_shape_round_trips_with_its_types(scratch_graph):
    from agent_fleet.mesh_registrar.v2_substrate import PREDICATE_EDGE_FAMILY

    driver, label = scratch_graph
    w = _live_writer(driver, label, PREDICATE_EDGE_FAMILY)
    s1, o1, *_ = _SCRATCH_URIS
    payload = {"domains": ["a", "b"], "synonyms": [], "requires_human_approval": True,
               "cost_class": "fast", "slots": '[{"name": "x"}]'}
    assert w.write_edge(_PERSON, identity=EdgeIdentity(
        subject=s1, verb="mesh:scratchVerb", object=o1, key="k"), payload=payload).applied
    with driver.session() as s:
        r = s.run(f"MATCH (:{label} {{uri: $s}})-[r]->(:{label}) RETURN properties(r) AS p",
                  s=s1).single()["p"]
    assert {k: r[k] for k in payload} == payload
    assert (r["iri"], r["_tool_urn"]) == ("mesh:scratchVerb", "k")


@pytest.mark.skipif(not _LIVE_VECTORS, reason="IAGENT_WRITER_SCRATCH + WEAVIATE_HTTP_HOST unset")
def test_LIVE_the_sdk_vectors_arms_hold_and_a_written_row_is_retrievable_by_name():
    """Does the client ACCEPT the call the writer makes, and is the space it wrote the space a
    search reaches. Both collections are scratch; the shared marker carrier is never touched."""
    from agent_fleet.utils.weaviate_utils import create_weaviate_client

    client = create_weaviate_client()
    tag = uuid.uuid4().hex[:10]
    collection, meta = f"{_scratch_prefix()}{tag}", f"{_scratch_prefix()}{tag}_meta"
    before = set(client.collections.list_all())
    assert collection not in before and meta not in before
    try:
        _run_vectors_contracts(
            client, collection,
            lambda c, i: client.collections.get(c).data.exists(_row_uuid(c, i)),
            meta_collection=meta)
        handle = client.collections.get(collection)
        row = handle.query.fetch_object_by_id(_row_uuid(collection, "row-1"), include_vector=True)
        # PRESENCE IS NOT THE PROPERTY: the client maps the legacy slot onto `default` on read, so
        # only the consuming operation — a near-vector search in the named space — can tell.
        found = handle.query.near_vector(
            near_vector=row.vector[VECTOR_SPACE], target_vector=VECTOR_SPACE, limit=1)
        assert found.objects and found.objects[0].uuid == _row_uuid(collection, "row-1")
        assert client.collections.get(meta).data.exists(_row_uuid(meta, collection))
    finally:
        try:
            for name in (collection, meta):
                if client.collections.exists(name):
                    client.collections.delete(name)
            after = set(client.collections.list_all())
        finally:
            client.close()
    assert after == before, f"collections changed outside scratch: {sorted(after ^ before)}"
