"""The promotion graph and index homes (src/iagent/promotion_stores.py, THE GRAPH / THE INDEXES).

What is pinned here:
  * the graph adapter writes the promotion fact as ONE keyed edge, as the PERSON acting, through
    the SDK graph writer built from `INGEST_FACT_FAMILY` -- and never answers a zero it did not
    read: an unreadable count, a sweep that did not apply, and a node that survives its sweep
    all RAISE;
  * the node-exists read is built FROM the family and binds the id as a parameter;
  * `create_node` goes through the SDK writer's `write_node` (v0.9.6) keyed by the same family's
    `node_label`/`node_key`, is idempotent (a second call answers False and writes nothing --
    the pre-read stays on THIS home even though `write_node` is itself an upsert), refuses a
    malformed ingest_id before any read or write, the `submitted_by` prop is the HOME's own
    initiator subject never a caller-supplied value, and a `write_node` that did not apply
    raises naming the outcome;
  * the rejection sweep now also deletes the node itself, but ONLY IF bare (no relationship of
    any type survives on it) -- a node another family's edge still anchors must survive;
  * the index adapter sweeps the declared collections, which are EMPTY, and refuses rather than
    answering zero the day one is declared;
  * THE CENSUS that keeps the empty declaration true: no module in this repo both names an
    ingest id and writes to Weaviate. Its reach is THIS REPO -- a producer in another repo (the
    doc-tools ingress) is invisible to it, and that is routed, not assumed away.

Run: uv run --frozen pytest tests/test_the_promotion_graph_and_index_homes.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from iagent_mesh.interfaces import (EdgeIdentity, EdgeIdentityFilter, Initiator, MeshResult,
                                    MeshWriteResult, ServiceIdentityRefused)

from src.iagent import promotion, promotion_stores
from src.iagent.promotion_stores import (INGEST_FACT_FAMILY, DeclaredIngestIndexes,
                                         Neo4jIngestGraph)

REPO = Path(__file__).resolve().parents[1]
INGEST_ID = "sha256:" + "ab" * 32
OTHER_ID = "sha256:" + "cd" * 32
BOB = Initiator(subject="bob", kind="person")
FACT = {"promoted_by": "human:bob", "promoted_at": "2026-09-30T20:27:00Z",
        "decision_record_id": "rec-1"}


# ── doubles ───────────────────────────────────────────────────────────────────────────────────

class _Session:
    def __init__(self, driver):
        self._d = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher, **params):
        self._d.reads.append((cypher, params))
        if cypher == promotion_stores._DELETE_BARE_NODE_CYPHER:
            self._d.log.append("node_delete_bare")
        else:
            self._d.log.append("node_read")
        row = None if self._d.node_count is None else {"n": self._d.node_count}
        return type("R", (), {"single": lambda _self: row})()


class _Driver:
    def __init__(self, node_count=0, log=None):
        self.node_count = node_count
        self.reads: list = []
        self.log = log if log is not None else []

    def session(self):
        return _Session(self)


class _Writer:
    """Records every call; answers what the arm configures."""

    def __init__(self, log, **family):
        self.family = family
        self.log = log
        self.calls: list = []
        self.write_result = MeshWriteResult.written()
        self.delete_result = MeshWriteResult.written()
        self.has_result = MeshResult.empty()
        self.write_node_result = MeshWriteResult.written()

    def write_edge(self, initiator, *, identity, payload):
        self.calls.append(("write", initiator, identity, payload))
        self.log.append("write")
        return self.write_result

    def write_node(self, initiator, *, label, id, payload):
        self.calls.append(("write_node", initiator, label, id, payload))
        self.log.append("write_node")
        return self.write_node_result

    def has_edges(self, initiator, *, identity_filter):
        self.calls.append(("has", initiator, identity_filter, None))
        self.log.append("has")
        return self.has_result

    def delete_edges(self, initiator, *, identity_filter):
        self.calls.append(("delete", initiator, identity_filter, None))
        self.log.append("delete")
        return self.delete_result


@pytest.fixture
def home():
    log: list = []
    built: list = []

    def factory(**kw):
        built.append(kw)
        return _Writer(log, **{k: v for k, v in kw.items() if k != "driver"})

    driver = _Driver(log=log)
    graph = Neo4jIngestGraph(driver=driver, initiator=BOB, writer_factory=factory)
    return graph, graph._writer, driver, built, log


# ── THE GRAPH: construction ───────────────────────────────────────────────────────────────────

def test_the_writer_is_built_from_the_WHOLE_family_and_the_driver(home):
    _, _, driver, built, _ = home
    assert built == [{"driver": driver, **INGEST_FACT_FAMILY}]


def test_the_DEFAULT_writer_is_the_SDK_graph_writer():
    graph = Neo4jIngestGraph(driver=None, initiator=BOB)
    assert type(graph._writer).__name__ == "Neo4jGraphWriter"
    assert type(graph._writer).__module__.endswith("mesh_writers.neo4j_graph")


def test_a_SERVICE_initiator_is_refused_BEFORE_any_writer_is_built():
    built: list = []
    with pytest.raises(ServiceIdentityRefused):
        Neo4jIngestGraph(driver=_Driver(), writer_factory=lambda **kw: built.append(kw),
                         initiator=Initiator(subject="cortex-bff", kind="service"))
    assert built == []


def test_a_DELEGATE_is_admitted_on_its_own_subject():
    """The gate is the SDK's write boundary (person or delegate), not a narrower local one."""
    d = Initiator(subject="lane-74", kind="delegate", on_behalf_of="bob")
    graph = Neo4jIngestGraph(driver=_Driver(), initiator=d,
                             writer_factory=lambda **kw: _Writer([], **kw))
    assert graph._initiator is d


# ── THE GRAPH: the node read ──────────────────────────────────────────────────────────────────

def test_the_node_read_is_BUILT_FROM_the_family_and_binds_the_id_as_a_PARAMETER(home):
    graph, _, driver, _, _ = home
    graph.node_exists(INGEST_ID)
    graph.node_exists(OTHER_ID)
    (c1, p1), (c2, p2) = driver.reads
    assert c1 == c2 == promotion_stores._NODE_EXISTS_CYPHER
    assert (p1, p2) == ({"ingest_id": INGEST_ID}, {"ingest_id": OTHER_ID})
    assert INGEST_ID not in c1 and "$ingest_id" in c1
    label, key = INGEST_FACT_FAMILY["node_label"], INGEST_FACT_FAMILY["node_key"]
    assert re.match(rf"MATCH \(n:{label} \{{{key}: \$ingest_id\}}\)\s+RETURN count\(n\) AS n$",
                    c1), c1


@pytest.mark.parametrize("count,expected", [(None, False), (0, False), (1, True), (2, True)])
def test_node_exists_reads_the_count(home, count, expected):
    graph, _, driver, _, _ = home
    driver.node_count = count
    assert graph.node_exists(INGEST_ID) is expected


# ── THE GRAPH: the promotion fact ─────────────────────────────────────────────────────────────

def test_the_fact_is_ONE_SELF_EDGE_keyed_by_the_ingest_id_as_the_person(home):
    graph, writer, _, _, _ = home
    graph.write_fact(INGEST_ID, FACT)
    [(kind, who, identity, payload)] = writer.calls
    assert kind == "write" and who is BOB
    assert identity == EdgeIdentity(subject=INGEST_ID, verb=promotion_stores.PROMOTION_VERB,
                                    object=INGEST_ID, key=INGEST_ID)
    assert payload == FACT and payload is not FACT


def test_a_REPLAY_names_the_SAME_edge(home):
    graph, writer, _, _, _ = home
    graph.write_fact(INGEST_ID, FACT)
    graph.write_fact(INGEST_ID, dict(FACT))
    assert writer.calls[0][2] == writer.calls[1][2]


@pytest.mark.parametrize("result", [
    MeshWriteResult.failed("ENDPOINT_ABSENT: no node"),
    MeshWriteResult.refused("payload names the key"),
    MeshWriteResult.unreachable("down")], ids=lambda r: r.outcome)
def test_a_fact_that_did_not_APPLY_raises_naming_the_outcome(home, result):
    graph, writer, _, _, _ = home
    writer.write_result = result
    with pytest.raises(RuntimeError, match=result.outcome):
        graph.write_fact(INGEST_ID, FACT)


# ── THE GRAPH: node creation ──────────────────────────────────────────────────────────────────

CREATE_KW = dict(kind="pdf", sha256="deadbeef", object_ref="ingress-user/pdf/x/file.pdf",
                 ingested_at="2026-09-30T20:27:00Z")


def test_create_node_calls_write_node_FROM_the_family_with_the_right_label_id_and_payload(home):
    graph, writer, _, _, log = home
    created = graph.create_node(INGEST_ID, **CREATE_KW)
    assert created is True
    assert log == ["node_read", "write_node"]
    kind, who, label, node_id, payload = writer.calls[-1]
    assert kind == "write_node" and who is BOB
    assert label == INGEST_FACT_FAMILY["node_label"]
    assert node_id == INGEST_ID
    assert payload == {
        "kind": "pdf", "sha256": "deadbeef", "object_ref": "ingress-user/pdf/x/file.pdf",
        "submitted_by": "bob", "ingested_at": "2026-09-30T20:27:00Z",
    }


def test_create_node_is_idempotent_the_SECOND_call_answers_False_and_writes_nothing(home):
    graph, writer, driver, _, log = home
    driver.node_count = 1  # already exists
    created = graph.create_node(INGEST_ID, **CREATE_KW)
    assert created is False
    assert log == ["node_read"], "an existing node must never reach write_node"
    assert writer.calls == []


def test_create_node_refuses_a_MALFORMED_ingest_id_before_any_read_or_write(home):
    graph, writer, driver, _, log = home
    with pytest.raises(ValueError, match="INGEST_ID_RE"):
        graph.create_node("not-an-ingest-id", **CREATE_KW)
    assert log == [] and driver.reads == [] and writer.calls == []


def test_create_node_props_carry_the_INITIATORS_subject_not_a_caller_supplied_one(home):
    graph, writer, _, _, _ = home
    graph.create_node(INGEST_ID, **CREATE_KW)
    assert writer.calls[-1][4]["submitted_by"] == graph._initiator.subject == "bob"


@pytest.mark.parametrize("result", [
    MeshWriteResult.failed("boom"),
    MeshWriteResult.refused("payload names the key"),
    MeshWriteResult.unreachable("down")], ids=lambda r: r.outcome)
def test_create_node_raises_naming_the_outcome_when_write_node_did_not_APPLY(home, result):
    graph, writer, _, _, _ = home
    writer.write_node_result = result
    with pytest.raises(RuntimeError, match=result.outcome):
        graph.create_node(INGEST_ID, **CREATE_KW)


def test_promotion_stores_contains_no_raw_MERGE_for_the_ingest_node():
    """SEAL: node creation goes through the SDK writer's `write_node`, never a raw driver MERGE.
    A literal grep, not a parse -- the thing this guards against is exactly a stray Cypher
    string, which a parse-based check could miss as readily as the thing it is checking for."""
    src = (REPO / "src" / "iagent" / "promotion_stores.py").read_text(encoding="utf-8")
    assert "MERGE" not in src, (
        "a raw MERGE reappeared in promotion_stores.py -- the ingest node must be created "
        "through Neo4jGraphWriter.write_node (SDK v0.9.6), not a raw driver write")


# ── THE GRAPH: the rejection sweep ────────────────────────────────────────────────────────────

def test_the_sweep_COUNTS_then_DELETES_then_BARE_NODE_DELETES_then_REREADS(home):
    graph, writer, driver, _, log = home
    writer.has_result = MeshResult.answered([{"k": 1}, {"k": 2}, {"k": 3}])
    assert graph.delete_carrying(INGEST_ID) == 3
    assert log == ["has", "delete", "node_delete_bare", "node_read"]
    assert [c[2] for c in writer.calls] == [EdgeIdentityFilter(key=INGEST_ID)] * 2
    assert all(c[1] is BOB for c in writer.calls)
    assert driver.reads[0][1] == {"ingest_id": INGEST_ID}
    assert driver.reads[1][1] == {"ingest_id": INGEST_ID}


def test_an_EMPTY_count_is_zero_and_the_delete_STILL_runs(home):
    graph, _, _, _, log = home
    assert graph.delete_carrying(INGEST_ID) == 0
    assert log == ["has", "delete", "node_delete_bare", "node_read"]


def test_the_bare_node_delete_is_BUILT_FROM_the_family_and_runs_BEFORE_the_final_reread(home):
    graph, writer, driver, _, _ = home
    writer.has_result = MeshResult.answered([{"k": 1}])
    graph.delete_carrying(INGEST_ID)
    cypher, params = driver.reads[0]
    assert cypher == promotion_stores._DELETE_BARE_NODE_CYPHER
    assert params == {"ingest_id": INGEST_ID}
    label, key = INGEST_FACT_FAMILY["node_label"], INGEST_FACT_FAMILY["node_key"]
    assert re.match(
        rf"MATCH \(n:{label} \{{{key}: \$ingest_id\}}\)\s+WHERE NOT \(n\)--\(\)\s+DELETE n$",
        cypher), cypher


@pytest.mark.parametrize("seen", [MeshResult.failed("boom"), MeshResult.unreachable("down")],
                         ids=lambda r: r.outcome)
def test_an_UNREADABLE_count_raises_and_NOTHING_is_deleted(home, seen):
    graph, writer, _, _, log = home
    writer.has_result = seen
    with pytest.raises(RuntimeError, match=seen.outcome):
        graph.delete_carrying(INGEST_ID)
    assert log == ["has"]


@pytest.mark.parametrize("result", [MeshWriteResult.failed("boom"),
                                    MeshWriteResult.unreachable("down")],
                         ids=lambda r: r.outcome)
def test_a_sweep_that_did_not_APPLY_raises(home, result):
    graph, writer, _, _, log = home
    writer.delete_result = result
    with pytest.raises(RuntimeError, match=result.outcome):
        graph.delete_carrying(INGEST_ID)
    assert log == ["has", "delete"]


def test_a_NODE_that_SURVIVES_its_sweep_RAISES_rather_than_reporting_the_count(home):
    """The writer cannot delete a node; a rejection that left one would report a sweep that did
    not happen."""
    graph, writer, driver, _, _ = home
    writer.has_result = MeshResult.answered([{"k": 1}])
    driver.node_count = 1
    with pytest.raises(RuntimeError, match="still exists after its 1 edge"):
        graph.delete_carrying(INGEST_ID)


def test_with_the_REAL_writer_and_NO_driver_the_sweep_raises_and_never_answers_zero():
    graph = Neo4jIngestGraph(driver=None, initiator=BOB)
    with pytest.raises(RuntimeError, match="unreachable"):
        graph.delete_carrying(INGEST_ID)


def test_the_adapters_carry_every_member_of_the_promotion_protocols():
    for name in ("node_exists", "write_fact", "delete_carrying"):
        assert hasattr(promotion.IngestGraph, name), name
        assert callable(getattr(Neo4jIngestGraph, name)), name
    assert hasattr(promotion.IngestIndexes, "delete_carrying")
    assert callable(DeclaredIngestIndexes.delete_carrying)


# ── THE INDEXES ───────────────────────────────────────────────────────────────────────────────

def test_the_declared_population_is_EMPTY_and_the_sweep_answers_zero():
    assert promotion_stores.INGEST_INDEXED_COLLECTIONS == ()
    assert DeclaredIngestIndexes().delete_carrying(INGEST_ID) == 0


def test_a_DECLARED_collection_is_REFUSED_rather_than_counted_as_zero():
    with pytest.raises(RuntimeError, match="cannot be done"):
        DeclaredIngestIndexes(("UserDrop",)).delete_carrying(INGEST_ID)


# ── THE CENSUS: what keeps the empty declaration true ─────────────────────────────────────────

#: Every Weaviate write spelling: the v4 client, the v3 client, the REST paths, and the fleet's
#: own vectors writer. The ingest-id spelling admits the forms a producer could plausibly choose.
_WEAVIATE_WRITE = re.compile(
    r"\.data\.(?:insert|insert_many|replace|update)\(|\.add_object\(|\.add_data_object\(|"
    r"data_object\.create\(|/v1/(?:objects|batch)\b|\bWeaviateVectorsWriter\b")
_INGEST_ID = re.compile(r"ingest[_-]?id", re.I)
_SKIP = {".venv", "__pycache__", "baml_client", "node_modules"}


def _population(roots=("src", "agent_fleet")):
    for root in roots:
        for f in sorted((REPO / root).rglob("*.py")):
            rel = f.relative_to(REPO)
            if not _SKIP.intersection(rel.parts):
                yield rel.as_posix(), f.read_text(encoding="utf-8", errors="replace")


def _carries(text: str) -> bool:
    return bool(_INGEST_ID.search(text)) and bool(_WEAVIATE_WRITE.search(text))


@pytest.mark.parametrize("form", [
    "coll.data.insert({'ingest_id': i})",
    "coll.data.insert_many(rows)  # ingest_id",
    "coll.data.replace(uuid=u, properties={'ingestId': i})",
    "c.data.update(uuid=u)  # ingest-id",
    "b.add_object(properties={'ingest_id': i})",
    "client.batch.add_data_object(o)  # ingest_id",
    "client.data_object.create(o)  # ingest_id",
    "requests.post(f'{url}/v1/objects')  # ingest_id",
    "requests.post(f'{url}/v1/batch/objects')  # INGEST_ID",
    "WeaviateVectorsWriter(client=c)  # ingest_id",
])
def test_POSITIVE_CONTROL_every_write_form_beside_an_ingest_id_is_caught(form):
    assert _carries(form)


@pytest.mark.parametrize("text", ["coll.data.insert(row)", "ingest_id = x"])
def test_CONTROL_either_half_alone_is_not_a_producer(text):
    assert not _carries(text)


def test_the_census_POPULATION_reaches_what_it_must():
    """Both halves of the cross must find their known members, or an empty answer below means
    the matcher went blind, not that the repo is clean."""
    files = dict(_population())
    writers = {f for f, t in files.items() if _WEAVIATE_WRITE.search(t)}
    named = {f for f, t in files.items() if _INGEST_ID.search(t)}
    assert {"agent_fleet/utils/mesh_writers/weaviate_vectors.py",
            "agent_fleet/mesh_registrar/v2_substrate.py"} <= writers, sorted(writers)
    assert {"src/iagent/promotion.py", "src/iagent/provenance.py",
            "src/iagent/gateway.py"} <= named, sorted(named)


def test_NO_module_in_this_repo_writes_an_ingest_id_into_WEAVIATE():
    """The day a producer appears, this names it -- and INGEST_INDEXED_COLLECTIONS, with an id
    scheme the vectors writer can delete by, becomes that producer's obligation."""
    producers = sorted(f for f, t in _population() if _carries(t))
    assert producers == [], (
        f"{producers} write to Weaviate and name an ingest id: declare the collection in "
        f"promotion_stores.INGEST_INDEXED_COLLECTIONS with a deletable id scheme")
