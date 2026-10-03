"""The concrete stores behind `promotion.act` (ADR-0041 Open §1, ruled 2026-09-30).

ALL FOUR EXIST. `promotion.PromotionStores` names four: the decision ledger, the graph, the
indexes and the objects. Two of them could not be built before the fleet's SDK v0.9.5 writers;
what each one can and cannot reach is stated beside it, because two of the four answer for less
than their names promise (THE GRAPH and THE INDEXES, below).

THE LEDGER is the approval plane's Postgres, beside `human_task_projection` (same DSN, same
psycopg2 discipline as human_tasks.py; the async gateway wraps calls in run_in_threadpool). One
row per document: `record_id` is derived from the `ingest_id`, and both are unique, so a second
decision is an `immutable_conflict` that returns what was decided, by whom and when. The record
is stored as its canonical JSON text, so the bytes that were decided on are the bytes kept.
Nothing here updates or deletes a row: a rejection sweeps the document, never its record.

THE OBJECTS are the `/ingest` seam's S3 directory for the document. A rejection MOVES it to
`rejected/<ingest_id>/`, keeping each key's path below the directory. Every object is copied
before any is deleted, so a failure part-way leaves the originals in place, and a retry copies
again over the same keys and finishes the deletes.

THE GRAPH goes through the SDK graph writer (`Neo4jGraphWriter`, `INGEST_FACT_FAMILY`), as the
PERSON who acted -- never a service identity. The promotion fact is ONE keyed edge from the
ingest artifact node to itself, carrying the three fact properties; its identity is
`(ingest_id, "promotion", ingest_id, key=ingest_id)`, so a replay with the stored actor and time
merges onto the same edge. The node-exists check is a parameterised READ, because `has_edges`
cannot see a node that has no edges yet. The sweep is the writer's key-only delete, which by the
family's fixed type and identity properties reaches no other family's edges.
THE WRITER CAN NOW CREATE A NODE -- `write_node` (SDK v0.9.6, opened 2026-10-01 specifically for
this call) -- but NOT delete one; the SDK shipped only what Lane 1 asked for, same as `has_edges`
followed `write_edge`/`delete_edges` rather than arriving pre-emptively. `create_node` therefore
goes through `write_node`, pinned past v0.9.5 to the sha that adds it (see this repo's root
`pyproject.toml`, `# TODO(0.9.6)`), while the re-read with `node_exists` BEFORE calling it stays
on THIS home: `write_node` is an upsert, and the pre-check is what keeps a retried `/ingest` from
silently overwriting an existing node's original `submitted_by`/`ingested_at` -- `write_node`'s
own contract has no "already existed" signal to report that from. `/ingest` calls `create_node`
best-effort, for a new arrival (a failure is logged, never raised; promotion of a document with
no node still answers 409 `ingest_node_absent` rather than 503). `delete_carrying` still deletes
the bare node itself through a raw driver call after its edge sweep (no `delete_node` exists on
the SDK writer to move this onto), but ONLY IF no relationship of ANY type remains on it
(`_DELETE_BARE_NODE_CYPHER`) -- a node another family's edge still anchors must survive
untouched. The re-read after that conditional delete still RAISES if the node persists: a
rejection that left the document's node in the graph would report a sweep that did not finish.

THE INDEXES sweep `INGEST_INDEXED_COLLECTIONS`, which is EMPTY, and the emptiness is measured
rather than assumed: no module in this repo writes a row carrying an `ingest_id` into Weaviate
(census: tests/test_the_promotion_graph_and_index_homes.py). The day a producer appears, the
census goes red and names it. A declared collection cannot be swept yet -- the vectors writer
deletes by caller-supplied id, and no producer has said which ids a document's rows carry -- so a
non-empty declaration RAISES rather than answering a zero it did not measure.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

import psycopg2
from iagent_mesh.interfaces import EdgeIdentity, EdgeIdentityFilter, Initiator

from .decision_record import canonical_json
from .promotion import INGEST_ID_RE, object_prefix_for

try:  # the package layout first; the container's flattened `utils` second (v2_substrate's idiom)
    from agent_fleet.utils.mesh_writers.neo4j_graph import Neo4jGraphWriter
except ImportError:  # pragma: no cover — runtime-dependent import path
    from utils.mesh_writers.neo4j_graph import Neo4jGraphWriter  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()

REJECTED_PREFIX = "rejected/"

_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS document_decision_record (
    record_id TEXT PRIMARY KEY,
    ingest_id TEXT NOT NULL UNIQUE,
    decision TEXT NOT NULL,
    acted_by TEXT NOT NULL,
    acted_at BIGINT NOT NULL,
    record TEXT NOT NULL
);
"""

_INSERT_SQL = """
INSERT INTO document_decision_record (record_id, ingest_id, decision, acted_by, acted_at, record)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
RETURNING record_id
"""

_EXISTING_SQL = """
SELECT decision, acted_by, acted_at FROM document_decision_record
WHERE record_id = %s OR ingest_id = %s
"""


class DecisionLedgerConfigError(RuntimeError):
    """The ledger was asked to operate without its DSN. Same posture as HumanTaskConfigError."""


def _pg_connect():
    if not _PG_DSN:
        raise DecisionLedgerConfigError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def configured() -> bool:
    return bool(_PG_DSN)


def apply_migration() -> None:
    """Create document_decision_record if absent. Called at cortex-bff startup."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


class PgDecisionLedger:
    """`promotion.DecisionLedger` over Postgres. A store fault is an answer, not a raise."""

    def __init__(self, connect: Callable[[], Any] = _pg_connect):
        self._connect = connect

    def append(self, record: dict, *, acted_by: str, acted_at: int) -> dict:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(_INSERT_SQL, (record["record_id"], record["request_key"],
                                              record["outcome"], acted_by, acted_at,
                                              canonical_json(record)))
                    inserted = cur.fetchone()
                    existing = None
                    if inserted is None:
                        cur.execute(_EXISTING_SQL, (record["record_id"], record["request_key"]))
                        existing = cur.fetchone()
                conn.commit()
        except Exception as exc:  # noqa: BLE001 — reported, and `act` refuses on it
            logger.warning("decision ledger append failed for %s: %s",
                           record.get("record_id"), exc)
            return {"ok": False, "reason": "unreachable", "detail": str(exc)[:300]}
        if inserted is not None:
            return {"ok": True}
        if existing is None:
            return {"ok": False, "reason": "conflict_unreadable"}
        decision, by, at = existing
        return {"ok": False, "reason": "immutable_conflict",
                "existing": {"decision": decision, "acted_by": by, "acted_at": int(at)}}


class S3Quarantine:
    """`promotion.IngestObjects` over the seam's bucket."""

    def __init__(self, client_factory: Callable[[], Any], bucket: str):
        self._client = client_factory
        self._bucket = bucket

    def quarantine(self, ingest_id: str, object_ref: str) -> list:
        prefix = object_prefix_for(ingest_id, object_ref)
        if prefix is None:
            raise ValueError(f"object_ref {object_ref!r} is not the seam's key for {ingest_id}")
        s3 = self._client()
        keys: list = []
        token = None
        while True:
            kw = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            page = s3.list_objects_v2(**kw)
            keys += [o["Key"] for o in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                break
            token = page["NextContinuationToken"]
        moved = []
        for key in keys:
            dest = f"{REJECTED_PREFIX}{ingest_id}/{key[len(prefix):]}"
            s3.copy_object(Bucket=self._bucket, Key=dest,
                           CopySource={"Bucket": self._bucket, "Key": key})
            moved.append(dest)
        for key in keys:
            s3.delete_object(Bucket=self._bucket, Key=key)
        return moved


# ── THE GRAPH ─────────────────────────────────────────────────────────────────────────────────

#: The promotion family. Its node label and key are what the ingest node will be created under;
#: the relationship type is FIXED, so a key-only sweep cannot cross into another family's edges.
INGEST_FACT_FAMILY = {
    "node_label": "IngestArtifact",
    "node_key": "ingest_id",
    "relationship_type": "PROMOTION",
    "verb_property": "verb",
    "key_property": "ingest_id",
}
PROMOTION_VERB = "promotion"

#: Built FROM the family, so the read and the writer cannot name two different nodes.
_NODE_EXISTS_CYPHER = (
    f"MATCH (n:{INGEST_FACT_FAMILY['node_label']} "
    f"{{{INGEST_FACT_FAMILY['node_key']}: $ingest_id}})\n"
    f"RETURN count(n) AS n"
)

#: Built FROM the family. Deletes the node ONLY IF it carries no relationship of any type --
#: `WHERE NOT (n)--()` is untyped and undirected on purpose, so an edge from ANY other family
#: (not just PROMOTION) still anchors the node and this never fires against it.
_DELETE_BARE_NODE_CYPHER = (
    f"MATCH (n:{INGEST_FACT_FAMILY['node_label']} "
    f"{{{INGEST_FACT_FAMILY['node_key']}: $ingest_id}})\n"
    f"WHERE NOT (n)--()\n"
    f"DELETE n"
)


class Neo4jIngestGraph:
    """`promotion.IngestGraph` over the property graph. Every write is the acting person's.

    Also owns NODE CREATION (`create_node`, below, now through the SDK writer's `write_node`,
    v0.9.6) and the bare-node delete inside `delete_carrying` (still a raw driver call -- the SDK
    ships no `delete_node`), even though neither is a `promotion.IngestGraph` protocol member:
    this class already owns the family (`INGEST_FACT_FAMILY`), the node read
    (`_NODE_EXISTS_CYPHER`), and is already constructed with the acting PERSON's `Initiator`
    (`require_person_or_delegate`, enforced below) -- so the node's own operations belong here,
    layered on top of the writer rather than duplicated beside it.
    """

    def __init__(self, *, driver: Any, initiator: Initiator,
                 writer_factory: Callable[..., Any] = Neo4jGraphWriter):
        initiator.require_person_or_delegate("promotion.graph")
        self._driver = driver
        self._initiator = initiator
        self._writer = writer_factory(driver=driver, **INGEST_FACT_FAMILY)

    def node_exists(self, ingest_id: str) -> bool:
        with self._driver.session() as session:
            row = session.run(_NODE_EXISTS_CYPHER, ingest_id=ingest_id).single()
        return row is not None and int(row["n"]) > 0

    def create_node(self, ingest_id: str, *, kind: str, sha256: str, object_ref: str,
                     ingested_at: str, dropped_by_authz_id: str | None = None) -> bool:
        """Create the ingest node for a NEW arrival. Returns True if this call created it, False
        if it already existed (idempotent: a retried /ingest, or a concurrent one, must not
        double-create or raise).

        Goes through the SDK writer's `write_node` (v0.9.6) rather than a raw driver upsert --
        `Neo4jGraphWriter` is no longer edges-only (ruled 2026-09-30; amended 2026-10-01 when
        `write_node` opened v0.9.6 scope specifically for this call). The re-read with
        `node_exists` BEFORE calling it is kept even though `write_node` is itself an upsert: it
        is what makes this method's OWN contract -- created vs already-existed -- true, and what
        keeps a retried /ingest from overwriting a node's original `submitted_by`/`ingested_at`
        with a later caller's values, which an unconditional upsert would do silently.

        Props are deliberately narrow and all scalar: `kind`, `sha256`, `object_ref`,
        `submitted_by` (THIS home's own `initiator.subject` -- the acting person, never a
        caller-supplied value), `ingested_at`, and `dropped_by_authz_id` (ruling 1 -- the
        caller-supplied authz_id, kept flat/scalar because the SDK graph writer's payload must
        be all-primitive; never the JWT `sub`).
        """
        if not INGEST_ID_RE.match(ingest_id):
            raise ValueError(f"ingest_id {ingest_id!r} does not match promotion.INGEST_ID_RE")
        if self.node_exists(ingest_id):
            return False
        props = {
            "kind": kind,
            "sha256": sha256,
            "object_ref": object_ref,
            "submitted_by": self._initiator.subject,
            "ingested_at": ingested_at,
            "dropped_by_authz_id": dropped_by_authz_id,
        }
        result = self._writer.write_node(
            self._initiator, label=INGEST_FACT_FAMILY["node_label"], id=ingest_id, payload=props)
        if not result.applied:
            raise RuntimeError(
                f"ingest node create for {ingest_id}: {result.outcome}: {result.detail}")
        return True

    def write_fact(self, ingest_id: str, fact: dict) -> None:
        result = self._writer.write_edge(
            self._initiator,
            identity=EdgeIdentity(subject=ingest_id, verb=PROMOTION_VERB, object=ingest_id,
                                  key=ingest_id),
            payload=dict(fact))
        if not result.applied:
            raise RuntimeError(f"promotion fact for {ingest_id}: {result.outcome}: {result.detail}")

    def delete_carrying(self, ingest_id: str) -> int:
        scope = EdgeIdentityFilter(key=ingest_id)
        seen = self._writer.has_edges(self._initiator, identity_filter=scope)
        if seen.outcome == "empty":
            count = 0
        elif seen.outcome == "answered":
            count = len(seen.rows)
        else:  # a count nobody could read is not a zero
            raise RuntimeError(f"graph sweep count for {ingest_id}: {seen.outcome}: {seen.detail}")
        result = self._writer.delete_edges(self._initiator, identity_filter=scope)
        if not result.applied:
            raise RuntimeError(f"graph sweep for {ingest_id}: {result.outcome}: {result.detail}")
        # Lane 74's B2: now that `create_node` (above) puts nodes in the graph, every rejection
        # would otherwise leave an orphan node behind -- and every later promotion attempt on
        # ANY document would then answer 503 promotion_effect_incomplete instead of the honest
        # 409 ingest_node_absent. Delete the node ONLY IF it carries no relationship of any type;
        # one from another family must still anchor it (`_DELETE_BARE_NODE_CYPHER`'s own
        # comment).
        with self._driver.session() as session:
            session.run(_DELETE_BARE_NODE_CYPHER, ingest_id=ingest_id)
        if self.node_exists(ingest_id):
            raise RuntimeError(
                f"the ingest node for {ingest_id} still exists after its {count} edge(s) were "
                f"swept and the bare-node delete ran against it: a node survives only if it "
                f"still carries an edge of another family, which this sweep must not cross")
        return count


# ── THE INDEXES ───────────────────────────────────────────────────────────────────────────────

#: Collections holding rows that carry a user-drop document's `ingest_id`. EMPTY BY MEASUREMENT
#: (module docstring); the census in tests/test_the_promotion_graph_and_index_homes.py is what
#: keeps this line true.
INGEST_INDEXED_COLLECTIONS: tuple = ()


class DeclaredIngestIndexes:
    """`promotion.IngestIndexes` over the collections declared to carry an `ingest_id`."""

    def __init__(self, collections: tuple = INGEST_INDEXED_COLLECTIONS):
        self._collections = tuple(collections)

    def delete_carrying(self, ingest_id: str) -> int:
        if self._collections:
            raise RuntimeError(
                f"{list(self._collections)} are declared to carry {ingest_id}, and the vectors "
                f"writer deletes only by a caller-supplied id that no producer has declared; "
                f"the index sweep cannot be done, so it is refused rather than counted as zero")
        return 0
