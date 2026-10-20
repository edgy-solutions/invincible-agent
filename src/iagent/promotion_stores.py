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

import json
import logging
import os
import re
from typing import Any, Callable, Optional

import psycopg2
from iagent_mesh.interfaces import EdgeIdentity, EdgeIdentityFilter, Initiator

from .decision_record import canonical_json
from .promotion import (INGEST_ID_RE, REJECTED_PREFIX, object_prefix_for,  # noqa: F401
                        quarantine_prefix_for)

try:  # the package layout first; the container's flattened `utils` second (v2_substrate's idiom)
    from agent_fleet.utils.mesh_writers.neo4j_graph import Neo4jGraphWriter
except ImportError:  # pragma: no cover — runtime-dependent import path
    from utils.mesh_writers.neo4j_graph import Neo4jGraphWriter  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()

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
SELECT decision, acted_by, acted_at, record FROM document_decision_record
WHERE record_id = %s OR ingest_id = %s
"""

_RECORD_FOR_SQL = """
SELECT record FROM document_decision_record WHERE ingest_id = %s
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
        decision, by, at = existing[:3]
        # The stored record rides along so a replay can be held to what was recorded (its
        # steward corrections); None when the row did not return it.
        stored = existing[3] if len(existing) > 3 else None
        return {"ok": False, "reason": "immutable_conflict",
                "existing": {"decision": decision, "acted_by": by, "acted_at": int(at),
                             "record": stored}}


    def record_for(self, ingest_id: str) -> Optional[dict]:
        """The stored decision record for `ingest_id`, or None when there is no row. A READ:
        a store fault RAISES (the caller turns it into a 503)."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_RECORD_FOR_SQL, (ingest_id,))
                row = cur.fetchone()
        if row is None:
            return None
        rec = row[0]
        if isinstance(rec, (bytes, bytearray, memoryview)):
            rec = bytes(rec).decode("utf-8")
        if isinstance(rec, str):
            rec = json.loads(rec)
        return rec if isinstance(rec, dict) else None


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
            dest = quarantine_prefix_for(ingest_id) + key[len(prefix):]
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

#: The node's current origin rung, or no row/None when it has none. Built FROM the family.
_ORIGIN_RUNG_CYPHER = (
    f"MATCH (n:{INGEST_FACT_FAMILY['node_label']} "
    f"{{{INGEST_FACT_FAMILY['node_key']}: $ingest_id}})\n"
    f"RETURN n.origin_resolved_by AS rung"
)

#: Rungs a steward attestation never replaces: a record origin outranks it, and an existing
#: steward origin stays as first attested.
_KEPT_RUNGS = {"record": "kept_record", "steward": "kept_steward"}

STEWARD_ATTESTATION = "steward_attestation"

#: Built FROM the family. Deletes the node ONLY IF it carries no relationship of any type --
#: `WHERE NOT (n)--()` is untyped and undirected on purpose, so an edge from ANY other family
#: (not just PROMOTION) still anchors the node and this never fires against it.
_DELETE_BARE_NODE_CYPHER = (
    f"MATCH (n:{INGEST_FACT_FAMILY['node_label']} "
    f"{{{INGEST_FACT_FAMILY['node_key']}: $ingest_id}})\n"
    f"WHERE NOT (n)--()\n"
    f"DELETE n"
)

# -- ROW EDITS: the steward's corrections applied to THIS notice's SUBJECT_TO edges -------------
# Component nodes are SHARED across notices (keyed on mpn alone): only this notice's edge is ever
# deleted or written, never a node. The domain is a label, so it is validated before it is
# interpolated.
_DOMAIN_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

_NOTICE_COUNT_CYPHER = (
    "MATCH (n:SustainmentNotice:{domain}) WHERE n.provenance_ingest_id = $ingest_id\n"
    "RETURN count(n) AS n"
)
_DELETE_EDGE_CYPHER = (
    "MATCH (c:Component:{domain} {{mpn: $mpn}})-[r:SUBJECT_TO]->(n:SustainmentNotice:{domain})\n"
    "WHERE n.provenance_ingest_id = $ingest_id\n"
    "DELETE r\n"
    "RETURN count(*) AS n"
)
_NOTICE_MPNS_CYPHER = (
    "MATCH (n:SustainmentNotice:{domain}) WHERE n.provenance_ingest_id = $ingest_id\n"
    "OPTIONAL MATCH (c:Component:{domain})-[:SUBJECT_TO]->(n)\n"
    "RETURN count(DISTINCT n) AS notices, collect(c.mpn) AS mpns"
)
_REMOVE_EDGES_CYPHER = (
    "MATCH (c:Component:{domain})-[r:SUBJECT_TO]->(n:SustainmentNotice:{domain})\n"
    "WHERE n.provenance_ingest_id = $ingest_id AND c.mpn IN $mpns\n"
    "DELETE r\n"
    "RETURN count(*) AS n"
)
_WRITE_EDGE_CYPHER = (
    "MATCH (n:SustainmentNotice:{domain}) WHERE n.provenance_ingest_id = $ingest_id\n"
    "MERGE (c:Component:{domain} {{mpn: $mpn}})\n"
    "MERGE (c)-[r:SUBJECT_TO]->(n)\n"
    "SET r.obtained_via = $obtained_via, r.corrected_by = $corrected_by,\n"
    "    r.extracted_value = $extracted_value, r.evidence = $evidence,\n"
    "    r.record_id = $record_id, r.disposition = $disposition, r.reason = $reason"
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

    def origin_rung(self, ingest_id: str) -> str | None:
        """The node's `origin_resolved_by`, or None (no such node, or no origin written). A read
        that raises propagates: an unknown rung is not an absent one."""
        with self._driver.session() as session:
            row = session.run(_ORIGIN_RUNG_CYPHER, ingest_id=ingest_id).single()
        value = row["rung"] if row is not None else None
        return value if isinstance(value, str) and value else None

    def attest_origin(self, ingest_id: str, *, owner_domain: str, record_id: str) -> str:
        """Record a steward's attestation of the document's origin. Returns "written",
        "kept_record" or "kept_steward".

        The ONE writer of this origin, for the promotion act and the backfill alike. Never
        downgrades or overwrites: a node already at `origin_resolved_by` "record" or "steward"
        is left alone; only no rung, or "unresolved", is written. The rung is the SDK's own
        `Origin.resolved_by="steward"`; the ruling's name (`steward_attestation`) rides in the
        evidence, citing the decision record. No `origin_program`: a steward attests a domain.
        """
        kept = _KEPT_RUNGS.get(self.origin_rung(ingest_id))
        if kept:
            return kept
        from iagent_mesh.systems_of_record import Origin  # noqa: PLC0415

        evidence = f"{STEWARD_ATTESTATION}:{record_id}"
        Origin(owner_domain=owner_domain, resolved_by="steward", evidence=(evidence,))
        result = self._writer.write_node(
            self._initiator, label=INGEST_FACT_FAMILY["node_label"], id=ingest_id,
            payload={"origin_owner_domain": owner_domain, "origin_resolved_by": "steward",
                     "origin_evidence": evidence})
        if result.outcome != "written":
            raise RuntimeError(
                f"origin attestation for {ingest_id}: {result.outcome}: {result.detail}")
        return "written"

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

    def notice_mpns(self, ingest_id: str, *, domain: str) -> Optional[list]:
        """READ: the exact `mpn` of every Component with a SUBJECT_TO edge to this ingest's
        notice. None when no such notice node exists; [] for a notice with no edges."""
        if not isinstance(domain, str) or not _DOMAIN_RE.match(domain):
            raise ValueError(f"domain {domain!r} does not match {_DOMAIN_RE.pattern}")
        with self._driver.session() as session:
            row = session.run(_NOTICE_MPNS_CYPHER.format(domain=domain),
                              ingest_id=ingest_id).single()
        if row is None or int(row["notices"]) < 1:
            return None
        return [m for m in row["mpns"] if isinstance(m, str)]

    def remove_notice_edges(self, ingest_id: str, mpns: list, *, domain: str) -> int:
        """Delete THIS notice's SUBJECT_TO edge for each exact mpn: `DELETE r` only, never a
        node (Components are shared across notices). Zero matches is a converged replay."""
        if not isinstance(domain, str) or not _DOMAIN_RE.match(domain):
            raise ValueError(f"domain {domain!r} does not match {_DOMAIN_RE.pattern}")
        if not mpns:
            return 0
        with self._driver.session() as session:
            row = session.run(_REMOVE_EDGES_CYPHER.format(domain=domain),
                              mpns=list(mpns), ingest_id=ingest_id).single()
        return int(row["n"]) if row is not None else 0

    def apply_row_edits(self, ingest_id: str, row_edits: list, *, domain: str,
                        record_id: str) -> dict:
        """Apply a steward's row edits to THIS notice's SUBJECT_TO edges (the graph must be true
        on its own, not filtered at read). deleted: remove the part's edge. corrected: remove the
        extracted part's edge, write the corrected part's with obtained_via=steward-corrected.
        added: write the part's edge. header_corrected is NOT applied (named in `not_applied`).
        Every statement is a MERGE or a DELETE of a matched edge, so a re-run converges."""
        if not isinstance(domain, str) or not _DOMAIN_RE.match(domain):
            raise ValueError(f"domain {domain!r} does not match {_DOMAIN_RE.pattern}")
        out = {"deleted": 0, "corrected": 0, "added": 0, "not_applied": []}
        edits = [e for e in (row_edits or []) if isinstance(e, dict)]
        applicable = [e for e in edits if e.get("op") in ("deleted", "corrected", "added")]
        out["not_applied"] = [e.get("field") for e in edits if e.get("op") == "header_corrected"]
        if not applicable:
            return out
        fmt = {"domain": domain}
        with self._driver.session() as session:
            row = session.run(_NOTICE_COUNT_CYPHER.format(**fmt), ingest_id=ingest_id).single()
            if row is None or int(row["n"]) < 1:
                raise RuntimeError(
                    f"no SustainmentNotice:{domain} carries provenance_ingest_id {ingest_id}; "
                    f"the row edits cannot be applied")
            for e in applicable:
                op = e["op"]
                if op in ("deleted", "corrected"):
                    r = session.run(_DELETE_EDGE_CYPHER.format(**fmt),
                                    mpn=e["mpn"], ingest_id=ingest_id).single()
                    if op == "deleted":
                        out["deleted"] += int(r["n"]) if r is not None else 0
                if op in ("corrected", "added"):
                    target = e["corrected_value"] if op == "corrected" else e["mpn"]
                    session.run(
                        _WRITE_EDGE_CYPHER.format(**fmt), ingest_id=ingest_id, mpn=target,
                        obtained_via="steward-corrected",
                        corrected_by=e.get("corrected_by"),
                        extracted_value=e.get("extracted_value"),
                        evidence=e.get("evidence"), record_id=record_id,
                        disposition=e.get("disposition"), reason=e.get("reason"))
                    out[op] += 1
        return out



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
