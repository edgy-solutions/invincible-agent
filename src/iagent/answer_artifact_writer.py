"""AnswerArtifact write authority — Hop 1 of the projector build plan.

This module is the cortex-bff direct-write path to Neo4j for AnswerArtifact
nodes, established by Decision 0 of the plan at commit 0eda9f7:
    docs/plans/projector-build-plan.md

Discipline this module enforces literally:

1.  **Delivery is decoupled from the Neo4j write.** The SSE generator
    yields `stream_end` and only THEN dispatches the writer on a separate
    asyncio task. `dispatch_async` MUST NEVER raise back to the caller —
    Neo4j unreachability is a recorded honest-state, not a delivery
    failure. Per [[feedback-trailing-steps-nonfatal]] and the architect's
    Decision-0 sub-decision ruling.

2.  **`durability_status` is recorded honestly at each transition.**
    - `persistence_pending` set IMMEDIATELY at dispatch time, even before
      the first write attempt (NOT derived from absence).
    - `durable` after a successful write.
    - `persistence_failed` after exhausted retries.

3.  **`watermark` is bumped on every UPDATE.** Decision 3 Option C: the
    watermark is a column on every artifact row, monotonic, sourced from
    a Neo4j sequence node (`WatermarkSequence`). EVERY write (initial
    create, replay-as-update, durability-status flip) bumps the
    sequence and copies the new value onto the artifact node. The
    vestigial-watermark trap per [[verify-subtle-acceptance-by-inspection]]
    is what Probe 1's replay-watermark assertion catches.

4.  **The MERGE is idempotent.** `MERGE (a:AnswerArtifact {id: $id})` is
    keyed on the artifact id; the same id never creates a duplicate
    node. Replay updates `updated_at` and bumps `watermark`.

5.  **Interim mechanisms are labeled.** Per
    [[coupled-interim-mechanisms-retire-together]]: this module's
    direct-write path, the durability_status field, AND the watermark
    column all retire together when the Restate+topic successor lands
    (Decisions 0+1+3 share one trigger). Comments in this file label
    each interim mechanism explicitly so a future reader knows what
    flips at the Restate cutover.

Bootstrap shape: this implementation uses **shape 1 (local fallback
queue)** from the planning prompt — durability records live in an
in-process registry that persists across the retry loop. On
`persistence_pending` we record locally; on success we update Neo4j
and the registry; on exhausted retries we keep the failed record in
the registry. If Neo4j is permanently unreachable, the failure is
visible in the registry indefinitely; when Neo4j returns, a future
operator-triggered replay can re-attempt the write. The Restate
successor formalizes this via the journal.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Enums (as string constants — keeps interop with both Python and
#    serializable JSON painless, matches what the cortex-ui type expects) ──


class DurabilityStatus:
    """Orthogonal to `status`. Records whether the answer has been written
    to Neo4j as the substrate of record.

    DO NOT COLLAPSE INTO `status`. Per the planning doc §3.1 and
    [[verify-subtle-acceptance-by-inspection]]: `status` is the
    pipeline-lifecycle (pending/complete/failed); `durability_status` is
    the substrate-write-state. Two orthogonal facts, two distinct slots.

    INTERIM: This whole concept retires with the Restate successor — the
    durable handler makes the persistence a journal step (exactly-once,
    crash-resumable) instead of a recorded honest-state. Decision 0 of
    the projector build plan.
    """

    PERSISTENCE_PENDING = "persistence_pending"
    DURABLE = "durable"
    PERSISTENCE_FAILED = "persistence_failed"


# ── Bundle (the assembled input the writer takes) ──


@dataclass
class AnswerArtifactBundle:
    """The full bundle cortex-bff hands to the writer.

    Matches the cortex-ui `Artifact` type contract (less the two
    interim-shaped fields `durability_status` and `watermark` which the
    writer assigns itself; the bundle is the upstream's view, the writer
    enforces those two).

    `status` is REQUIRED — no default. Per
    [[optimistic-defaults-are-dishonest]] rule #1 (Option A): a
    multi-valued enum where the writer defaults to the "everything
    succeeded" value silently lies about every failed-and-forgotten
    pipeline. The gateway is the layer that knows the answer's
    lifecycle (it sees `final_payload` AND `_perror`); requiring the
    field at construction forces the gateway to confront the
    decision. A forgotten `status` is a TypeError at construction,
    NOT a silent persist-as-complete.

    Vocabulary matches the cortex-ui Artifact.status field exactly:
    `pending | complete | failed`. The writer accepts any of the
    three; callers SHOULD NOT pass `pending` (per ADR-0023's
    "generation-status is never an artifact property" rule — pending
    is the transient UI-side state before the artifact is born) but
    the writer does not enforce that. Enforcing it would re-create
    the optimistic-default trap one layer over: the rule that
    excludes `pending` does NOT mandate `complete`; both `complete`
    and `failed` are legitimate persisted values, and which one is
    correct depends on what actually happened upstream.
    """

    id: str
    question_text: str
    message_id: str
    valid_as_of: int
    status: str  # REQUIRED — see class docstring.
    produced_by: Dict[str, Any]
    produced_for: Dict[str, Any]
    resolved_intent: Dict[str, Any]
    routing: Optional[Dict[str, Any]]
    sources: List[Dict[str, Any]] = field(default_factory=list)
    graph_trace: List[Dict[str, Any]] = field(default_factory=list)
    rendered_output: Optional[Dict[str, Any]] = None
    derived_from_artifact_id: Optional[str] = None
    valid_until: Optional[int] = None


# ── Result of a write attempt ──


@dataclass
class WriteResult:
    success: bool
    watermark: int = 0
    attempts: int = 0
    error: Optional[str] = None


# ── Writer ──


class AnswerArtifactWriter:
    """Idempotent AnswerArtifact write authority.

    Two entry points:

    - `dispatch_async(bundle)` — the SSE-generator path. NEVER RAISES.
      Records `persistence_pending` immediately, then retries up to
      `max_retries`; transitions to `durable` or `persistence_failed`.
      The retry runs on the asyncio loop with bounded backoff.

    - `write_sync(bundle)` — the probe / repair / batch path. Raises
      on input-shape errors, returns a `WriteResult` on substrate
      outcomes. Used by Probe 1's deterministic readback flow.

    Both paths share the same Cypher MERGE; both bump the watermark on
    every commit.
    """

    def __init__(
        self,
        driver: Any,
        *,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        self._driver = driver
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._registry: Dict[str, Dict[str, Any]] = {}
        self._registry_lock = RLock()
        # Tracks whether the last dispatch_async call raised back to the
        # caller. Probe 2's Assertion A reads this — it MUST remain False
        # under fault injection. If True, delivery has been coupled.
        self.last_dispatch_raised: bool = False

    # ── Registry (the local fallback queue, shape 1 from the prompt) ──

    def _record(
        self,
        artifact_id: str,
        durability_status: str,
        *,
        attempts: int,
        last_error: Optional[str] = None,
    ) -> None:
        with self._registry_lock:
            existing = self._registry.get(artifact_id, {})
            existing.update(
                {
                    "artifact_id": artifact_id,
                    "durability_status": durability_status,
                    "attempts": attempts,
                    "last_error": last_error,
                    "updated_at": int(time.time() * 1000),
                }
            )
            self._registry[artifact_id] = existing

    def get_durability_record(
        self, artifact_id: str
    ) -> Optional[Dict[str, Any]]:
        with self._registry_lock:
            return self._registry.get(artifact_id)

    # ── Public: synchronous write (probe / repair) ──

    def write_sync(self, bundle: AnswerArtifactBundle) -> WriteResult:
        """Synchronous write. Returns a WriteResult; raises only on
        bundle-shape errors (which are programmer errors, not substrate
        errors).

        Used by Probe 1 because it needs deterministic ordering: write,
        then read back. The async dispatch path is for the SSE generator.
        """
        self._record(
            bundle.id, DurabilityStatus.PERSISTENCE_PENDING, attempts=0
        )

        attempt = 0
        last_error: Optional[str] = None
        while attempt < self._max_retries:
            attempt += 1
            try:
                watermark = self._merge_artifact(
                    bundle, DurabilityStatus.DURABLE
                )
                self._record(
                    bundle.id,
                    DurabilityStatus.DURABLE,
                    attempts=attempt,
                )
                return WriteResult(
                    success=True, watermark=watermark, attempts=attempt
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "AnswerArtifact write attempt %d/%d failed for %s: %s",
                    attempt,
                    self._max_retries,
                    bundle.id,
                    last_error,
                )
                self._record(
                    bundle.id,
                    DurabilityStatus.PERSISTENCE_PENDING,
                    attempts=attempt,
                    last_error=last_error,
                )
                if attempt < self._max_retries:
                    time.sleep(self._backoff_seconds)

        # Exhausted retries — record the terminal failure.
        self._record(
            bundle.id,
            DurabilityStatus.PERSISTENCE_FAILED,
            attempts=attempt,
            last_error=last_error,
        )
        return WriteResult(
            success=False, watermark=0, attempts=attempt, error=last_error
        )

    # ── Public: async dispatch (SSE generator path) ──

    async def dispatch_async(self, bundle: AnswerArtifactBundle) -> None:
        """Async, NEVER raises. Drives the durability state machine on a
        background-task-eligible coroutine.

        The SSE generator schedules this via `asyncio.create_task(...)`
        AFTER yielding `stream_end`. Delivery is already done; this
        coroutine's outcome cannot fail delivery. Per the Decision-0
        sub-decision ruling and [[feedback-trailing-steps-nonfatal]].
        """
        self.last_dispatch_raised = False
        try:
            self._record(
                bundle.id,
                DurabilityStatus.PERSISTENCE_PENDING,
                attempts=0,
            )

            attempt = 0
            last_error: Optional[str] = None
            while attempt < self._max_retries:
                attempt += 1
                try:
                    # Neo4j driver is sync; offload to a thread so we
                    # don't block the event loop on bolt I/O.
                    watermark = await asyncio.to_thread(
                        self._merge_artifact,
                        bundle,
                        DurabilityStatus.DURABLE,
                    )
                    self._record(
                        bundle.id,
                        DurabilityStatus.DURABLE,
                        attempts=attempt,
                    )
                    logger.info(
                        "AnswerArtifact %s durable (attempt %d, "
                        "watermark %d)",
                        bundle.id,
                        attempt,
                        watermark,
                    )
                    return
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "AnswerArtifact dispatch attempt %d/%d failed for "
                        "%s: %s",
                        attempt,
                        self._max_retries,
                        bundle.id,
                        last_error,
                    )
                    self._record(
                        bundle.id,
                        DurabilityStatus.PERSISTENCE_PENDING,
                        attempts=attempt,
                        last_error=last_error,
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._backoff_seconds)

            # Exhausted retries — record the terminal failure honestly.
            self._record(
                bundle.id,
                DurabilityStatus.PERSISTENCE_FAILED,
                attempts=attempt,
                last_error=last_error,
            )
            logger.error(
                "AnswerArtifact %s persistence_failed after %d attempts: %s",
                bundle.id,
                attempt,
                last_error,
            )
        except BaseException as exc:  # pragma: no cover — defensive
            # The decoupling contract: never raise back to the caller.
            # If something unexpected went wrong, log it and record the
            # failure state, but DO NOT propagate. Even programmer
            # errors here mustn't fail delivery.
            self.last_dispatch_raised = True
            logger.exception(
                "AnswerArtifact dispatch UNEXPECTED failure for %s; the "
                "decoupling contract held the failure inside dispatch, "
                "but this is a programmer error that needs investigation.",
                bundle.id,
            )
            try:
                self._record(
                    bundle.id,
                    DurabilityStatus.PERSISTENCE_FAILED,
                    attempts=0,
                    last_error=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass

    # ── Cypher core ──

    def _merge_artifact(
        self,
        bundle: AnswerArtifactBundle,
        durability_status: str,
    ) -> int:
        """Single Cypher transaction: bump watermark sequence, MERGE the
        artifact node, MERGE/CREATE the edges. Returns the new
        watermark.

        Idempotent on `id`. Bumps watermark on EVERY call (Decision 3
        Option C: every apply that touches the row bumps the watermark
        column — the vestigial-watermark trap is exactly what skipping
        this on a no-content update produces).
        """
        with self._driver.session() as session:
            return session.execute_write(self._tx_merge, bundle, durability_status)

    @staticmethod
    def _tx_merge(
        tx: Any, bundle: AnswerArtifactBundle, durability_status: str
    ) -> int:
        now_ms = int(time.time() * 1000)
        # Bump the global watermark sequence first. The single-row
        # WatermarkSequence node is the Hop 1 monotonic source; the
        # Restate successor replaces it with the topic offset.
        seq_result = tx.run(
            """
            MERGE (s:WatermarkSequence {key: 'answer_artifact'})
            ON CREATE SET s.value = 0
            SET s.value = s.value + 1
            RETURN s.value AS watermark
            """
        ).single()
        watermark = seq_result["watermark"]

        # MERGE the artifact node.
        # `status` is REQUIRED ON THE BUNDLE — no optimistic default
        # here. Per [[optimistic-defaults-are-dishonest]] (first
        # confirmed instance at this writer's prior commit, see the
        # memory): a writer that defaults `status` to 'complete' would
        # silently persist failed pipelines as durable + complete.
        # The gateway is the layer that knows the lifecycle (it sees
        # `final_payload` AND `_perror`); the bundle's status carries
        # the gateway's explicit signal; the MERGE respects it
        # verbatim. Failure-mode-1 (pipeline failed) persists as
        # `status='failed' + durability_status='durable' +
        # rendered_output=null` — honest.
        #
        # `rendered_output` is similarly written verbatim — if the
        # bundle's rendered_output is None (failed pipeline produced
        # no payload), the column stores null, not an empty placeholder.
        tx.run(
            """
            MERGE (a:AnswerArtifact {id: $id})
            ON CREATE SET
              a.created_at = $now_ms
            SET
              a.status = $status,
              a.updated_at = $now_ms,
              a.valid_as_of = $valid_as_of,
              a.valid_until = $valid_until,
              a.question_text = $question_text,
              a.message_id = $message_id,
              a.resolved_intent = $resolved_intent,
              a.routing_inline = $routing_inline,
              a.rendered_output = $rendered_output,
              a.graph_trace_json = $graph_trace_json,
              a.durability_status = $durability_status,
              a.watermark = $watermark
            """,
            id=bundle.id,
            now_ms=now_ms,
            status=bundle.status,
            valid_as_of=bundle.valid_as_of,
            valid_until=bundle.valid_until,
            question_text=bundle.question_text,
            message_id=bundle.message_id,
            # Neo4j properties can't be nested dicts — serialize the
            # sub-objects to JSON strings. The projector (Hop 2) will
            # re-parse them into JSONB columns.
            resolved_intent=_to_json(bundle.resolved_intent),
            routing_inline=_to_json(bundle.routing),
            rendered_output=_to_json(bundle.rendered_output),
            # graph_trace was on the dataclass since Hop 1 but was
            # never written to Neo4j — the MERGE clause was missing
            # the SET line. Pre-Hop-3 this was masked because the
            # cortex-ui SSE handler shoved `graph_trace` directly
            # into the canvas store, so the GraphTrace HUD component
            # rendered from SSE-supplied data without the projection.
            # Post-Hop-3 the SSE handler is a no-op (Electric became
            # the sole source for Electric-covered fields including
            # graph_trace), and the writer's missing field surfaced
            # as "the detailed HUD's graph disappeared." 2026-06-30:
            # close the gap. JSON-serialized into a single Neo4j
            # property; projector re-parses into the jsonb column.
            graph_trace_json=_to_json(bundle.graph_trace or []),
            durability_status=durability_status,
            watermark=watermark,
        )

        # PRODUCED_BY edge → Actor node. MERGE on (actor_type, actor_id)
        # so two artifacts produced by the same agent share an Actor
        # node (per ADR-0023's open question, we pick the
        # node-properties-shared shape; per-production facts go on the
        # edge if needed).
        producer = bundle.produced_by or {}
        if producer:
            tx.run(
                """
                MATCH (a:AnswerArtifact {id: $id})
                MERGE (p:Actor {
                  actor_type: $actor_type,
                  actor_id: $actor_id
                })
                SET
                  p.version = coalesce($version, p.version),
                  p.endpoint = coalesce($endpoint, p.endpoint),
                  p.code_hash = coalesce($code_hash, p.code_hash)
                MERGE (a)-[:PRODUCED_BY]->(p)
                """,
                id=bundle.id,
                actor_type=producer.get("actor_type", "agent"),
                actor_id=producer.get("actor_id", "pending"),
                version=producer.get("version"),
                endpoint=producer.get("endpoint"),
                code_hash=producer.get("code_hash"),
            )

        # PRODUCED_FOR edge → Actor node. user-side persona slot held
        # nullable per [[pingsso-claim-gap]].
        #
        # Capture A per ADR-0025: `entitlement_source` records WHICH
        # ORIGIN the persona / entitled_domains came from at the
        # moment auth.py read the JWT — "claim" / "fallback" /
        # "partial". The persisted produced_for VALUE is downstream
        # code's view; the origin flag is the audit fact that
        # otherwise would be lost
        # (capture-or-lose-forever per
        # `[[verify-subtle-acceptance-by-inspection]]`).
        #
        # Note: if the caller's bundle does not carry the field
        # (legacy direct-writer call sites), we default to "fallback"
        # at the Cypher layer rather than silently writing null. Per
        # `[[optimistic-defaults-are-dishonest]]`: "fallback" is the
        # failure-revealing default that makes a forgotten origin
        # visible. Production callers thread the field through from
        # the gateway; the legacy default exists only so probe/repair
        # call sites stay compatible.
        consumer = bundle.produced_for or {}
        if consumer:
            tx.run(
                """
                MATCH (a:AnswerArtifact {id: $id})
                MERGE (u:Actor {
                  actor_type: 'user',
                  actor_id: $user_id
                })
                SET
                  u.user_id = $user_id,
                  u.is_authenticated = $is_authenticated,
                  u.user_persona = $user_persona,
                  u.entitled_domains = $entitled_domains,
                  u.entitlement_source = $entitlement_source
                MERGE (a)-[:PRODUCED_FOR]->(u)
                """,
                id=bundle.id,
                user_id=consumer.get("user_id", "unknown"),
                is_authenticated=bool(consumer.get("is_authenticated", False)),
                user_persona=consumer.get("user_persona"),
                entitled_domains=consumer.get("entitled_domains"),
                entitlement_source=consumer.get(
                    "entitlement_source", "fallback"
                ),
            )

        # CITES → Source. MERGE the Source by uri (sources are reusable
        # across artifacts per ADR-0023). MERGE the CITES edge so
        # replay doesn't double-edge.
        #
        # Capture B per ADR-0025: `access_decision` is a RESERVED SLOT
        # on the CITES edge. The slot is part of the type today, null
        # in all production writes, no consumer reads it. Reserving
        # the slot now means the enforcement session does not need a
        # second migration through writer + Neo4j + projector +
        # Postgres + Electric + cortex-ui to land the captured
        # Topaz decision. Neo4j edge properties cannot hold nested
        # dicts, so we serialize to a JSON string property
        # `c.access_decision_json` (mirrors `routing_inline` /
        # `resolved_intent`'s JSON-string-on-Neo4j shape). The
        # projector re-parses it back into a dict in the `sources`
        # JSONB.
        for src in bundle.sources or []:
            uri = src.get("uri")
            if not uri:
                continue
            tx.run(
                """
                MATCH (a:AnswerArtifact {id: $id})
                MERGE (s:Source {uri: $uri})
                SET
                  s.type = coalesce($type, s.type),
                  s.label = coalesce($label, s.label)
                MERGE (a)-[c:CITES]->(s)
                SET
                  c.snippet = $snippet,
                  c.relevance = $relevance,
                  c.open_url = $open_url,
                  c.access_decision_json = $access_decision_json
                """,
                id=bundle.id,
                uri=uri,
                type=src.get("type"),
                label=src.get("label"),
                snippet=src.get("snippet"),
                relevance=src.get("relevance"),
                open_url=src.get("open_url"),
                # Capture B reserved slot: null when not populated.
                # When enforcement lands, the retrieval call site
                # populates this with the Topaz decision record.
                access_decision_json=_to_json(src.get("access_decision")),
            )

        # DERIVED_FROM → AnswerArtifact (lineage). Only when present.
        if bundle.derived_from_artifact_id:
            tx.run(
                """
                MATCH (a:AnswerArtifact {id: $id})
                MERGE (parent:AnswerArtifact {id: $parent_id})
                MERGE (a)-[:DERIVED_FROM]->(parent)
                """,
                id=bundle.id,
                parent_id=bundle.derived_from_artifact_id,
            )

        return watermark


# ── Helpers ──


def _to_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    import json

    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return None


# ── Process-wide writer (gateway integration point) ──
#
# The gateway's SSE generator creates an AnswerArtifactBundle as the
# pipeline events arrive (route_decision → sources → final_payload),
# yields stream_end, then schedules `dispatch_async` on a separate
# asyncio task. The driver is the same `neo4j_driver` the gateway
# already holds for the `/node_details` read path.
#
# Construction is lazy so importing this module does not require a
# Neo4j driver — keeps unit tests / probes isolated from infrastructure
# they shouldn't touch.

_writer_singleton: Optional[AnswerArtifactWriter] = None
_writer_singleton_lock = RLock()


def get_writer() -> Optional[AnswerArtifactWriter]:
    """Return the process-wide writer, constructed on first call.

    Returns None if Neo4j isn't configured (e.g., in tests where the
    gateway is imported without env vars). The gateway's dispatch site
    treats None as "skip the write" — keeps the trailing-step
    non-fatal even if the writer can't even be built.
    """
    global _writer_singleton
    with _writer_singleton_lock:
        if _writer_singleton is not None:
            return _writer_singleton
        try:
            # Local import: avoids forcing every importer of this
            # module to also have neo4j in their environment.
            from neo4j import GraphDatabase

            uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            user = os.getenv("NEO4J_USERNAME", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "changeme")
            driver = GraphDatabase.driver(uri, auth=(user, password))
            max_retries = int(os.getenv("ARTIFACT_WRITER_MAX_RETRIES", "3"))
            backoff = float(
                os.getenv("ARTIFACT_WRITER_BACKOFF_SECONDS", "0.5")
            )
            _writer_singleton = AnswerArtifactWriter(
                driver=driver,
                max_retries=max_retries,
                backoff_seconds=backoff,
            )
            logger.info(
                "AnswerArtifactWriter initialized: uri=%s max_retries=%d "
                "backoff=%.2fs",
                uri,
                max_retries,
                backoff,
            )
            return _writer_singleton
        except Exception as exc:
            logger.warning(
                "AnswerArtifactWriter could not initialize "
                "(trailing-step non-fatal): %s",
                exc,
            )
            return None
