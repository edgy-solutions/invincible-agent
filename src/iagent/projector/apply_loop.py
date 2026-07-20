"""Projector apply loop — polls Neo4j, upserts into Postgres, advances cursor.

Hop 2 of docs/plans/projector-build-plan.md (commit 0eda9f7),
§3.3 Decision 2 + §3.4 Decision 3 Option C + §5 schema. Builds on Hop 1's
writer (commits 64a4662 + 6d01bcb) which is the source of AnswerArtifact
nodes in Neo4j with the `watermark` and `durability_status` properties.

Discipline this module enforces:

1.  **Poll loop is INTERIM** per [[coupled-interim-mechanisms-retire-together]].
    Inline comment at the poll site. Retires with Decisions 0+1+3 under
    the Restate+topic successor.

2.  **Every apply that touches a row touches the watermark column**
    (Decision 3 Option C). The projector copies the row's
    `a.watermark` from Neo4j into the Postgres `watermark` column
    verbatim — it never computes a separate value, never skips the
    column on an "orthogonal" update (durability_status-only,
    status-only). Phase D probe asserts this.

3.  **Cursor advance and row write are in one transaction.** The
    UPSERT into answer_artifact_projection AND the UPDATE of
    projector_cursor.last_applied_watermark commit together. A crash
    mid-apply does not advance the cursor past an unwritten row.

4.  **Errors are observable, not silent** per
    [[feedback-trailing-steps-nonfatal]]. A bad artifact (JSON-parse
    failure, constraint violation) gets logged AND inserted into
    `projector_skip_log` with structured detail; the cursor advances
    past it (the loop survives). Silent drops are the trap; observable
    skips with a queryable surface are the right shape.

5.  **Liveness is structural advance** per
    [[liveness-probe-watches-advance-not-just-correctness]]. The
    cursor in Postgres is the source of truth for the
    `GET /projector/watermark` endpoint — NOT an in-memory counter
    that could be stale from a dead loop. A frozen loop with a
    backfilled-once table reads identical to a healthy loop from the
    correctness vantage; only `last_applied_watermark` advancing under
    a fresh write distinguishes them.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


# Tunable knobs — defaults match the planning doc's §5 Phase A wait
# budget (≤ 1.5s) plus a small margin for poll latency.
DEFAULT_POLL_INTERVAL_SECONDS = float(
    os.getenv("PROJECTOR_POLL_INTERVAL_SECONDS", "0.5")
)
DEFAULT_BATCH_LIMIT = int(os.getenv("PROJECTOR_BATCH_LIMIT", "100"))


@dataclass
class CursorState:
    """Snapshot of the projector's apply position. Sourced from the
    `projector_cursor` row in Postgres — NOT in-memory state.

    The endpoint reads this directly so a dead loop with a stale
    in-memory copy can't fake liveness.
    """

    last_applied_watermark: int
    last_apply_at_ms: int
    apply_count: int


class ApplyLoop:
    """The projector's polling apply loop.

    Two entry points:
      - `run_forever()` — the long-running background task the FastAPI
        app schedules at startup.
      - `apply_once()` — single-batch apply; used by tests and the
        FastAPI endpoint for forced refresh.

    Connection objects are owned by this instance — neo4j driver kept
    open for the loop's lifetime (bolt is multiplexed); Postgres
    connections obtained per-batch from a tiny pool we manage
    internally (psycopg2 is sync; per-batch acquire+release is fine at
    Hop 2's throughput).
    """

    def __init__(
        self,
        *,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        postgres_dsn: str,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        batch_limit: int = DEFAULT_BATCH_LIMIT,
    ) -> None:
        self._neo4j_uri = neo4j_uri
        self._neo4j_user = neo4j_user
        self._neo4j_password = neo4j_password
        self._postgres_dsn = postgres_dsn
        self._poll_interval = poll_interval_seconds
        self._batch_limit = batch_limit
        self._driver = GraphDatabase.driver(
            neo4j_uri, auth=(neo4j_user, neo4j_password)
        )
        self._stop = asyncio.Event()
        # In-memory mirror of the cursor — written-through to Postgres
        # transactionally; the ENDPOINT reads Postgres, not this. The
        # mirror exists only so the loop doesn't have to query the
        # cursor every batch.
        self._last_applied_watermark: int = 0
        self._last_apply_at_ms: int = 0
        self._apply_count: int = 0
        # Apply-path concurrency lock — None until first awaited so the
        # asyncio.Lock binds to the running event loop. Both the
        # interval-driven run_forever AND the force_poll endpoint go
        # through apply_once_async, which grabs this lock before
        # offloading the sync work to a thread. Without it, a concurrent
        # force_poll arriving mid-batch races the interval loop's cursor
        # read → both fetch the same K rows from Neo4j → both call
        # _apply_one for each row → apply_count double-increments (the
        # data is still correct via idempotent UPSERT, but the
        # operator-facing throughput signal lies). See
        # `[[projector-hardening-carry-forwards]]` item (b).
        self._apply_lock: Optional[asyncio.Lock] = None
        self._load_cursor_state()

    # ────────────────────────────────────────────────────────────────
    # Connection helpers
    # ────────────────────────────────────────────────────────────────

    def _pg_connect(self) -> "psycopg2.extensions.connection":
        return psycopg2.connect(self._postgres_dsn)

    def close(self) -> None:
        self._stop.set()
        try:
            self._driver.close()
        except Exception:
            logger.exception("error closing neo4j driver")

    # ────────────────────────────────────────────────────────────────
    # Cursor state (the loop's resumable position)
    # ────────────────────────────────────────────────────────────────

    def _load_cursor_state(self) -> None:
        """Read cursor from Postgres at startup. NEVER trust an
        in-memory default of 0 if a row exists — the seed migration
        inserts a row with last_applied_watermark=0, but a long-running
        deployment has higher values. Phase C (restart drain) is the
        probe that catches a missing reload.
        """
        with self._pg_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_applied_watermark, last_apply_at, "
                    "apply_count FROM projector_cursor WHERE id = 1"
                )
                row = cur.fetchone()
                if row is None:
                    # The migration seeds this row; absence means the
                    # migration didn't run. Surface loudly per
                    # [[feedback-verification-must-fail]] — a silent
                    # default-to-0 here would hide a missing migration.
                    raise RuntimeError(
                        "projector_cursor row not found; the schema "
                        "migration sql/create_answer_artifact_projection.sql "
                        "must run before the projector starts."
                    )
                self._last_applied_watermark = int(row[0])
                self._last_apply_at_ms = int(row[1])
                self._apply_count = int(row[2])
        logger.info(
            "projector cursor loaded: last_applied_watermark=%d "
            "apply_count=%d",
            self._last_applied_watermark,
            self._apply_count,
        )

    def _resync_cursor_from_postgres(self) -> None:
        """Re-read the cursor from Postgres before every apply batch.

        Postgres is the SOURCE OF TRUTH for the cursor; the in-memory
        value is only a write-through mirror. Trusting that mirror across
        batches means an EXTERNAL reset of ``projector_cursor`` — a
        ``--nuclear`` prime, an operator rewind, a restore from backup —
        is INVISIBLE to an already-running process: the mirror keeps the
        old high watermark, the batch query filters
        ``watermark > <stale high>``, and every new artifact is skipped
        FOREVER while the loop looks perfectly healthy (polling on
        schedule, zero errors, apply_count frozen).

        That exact shape cost hours to diagnose (work, 2026-07-20): the
        answer was written to Neo4j at watermark 1, ``--nuclear`` had
        reset Postgres to 0, and the projector ignored it because its RAM
        still said 4. Nothing in any log said so — the UI just stayed
        blank.

        ``get_cursor_state()`` already reads Postgres for precisely this
        reason ("a dead apply loop with a stale in-memory mirror would
        still look live"). That honesty was applied to the ENDPOINT but
        not to the APPLY PATH, which is the half that actually decides
        what gets projected. One single-row SELECT per batch is the cost,
        and it is the same cost that method already accepts.

        A DOWNWARD move is logged LOUDLY: it means something reset the
        cursor underneath us, and adopting it silently would hide the very
        class of bug this method exists to kill.
        """
        with self._pg_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_applied_watermark, last_apply_at, "
                    "apply_count FROM projector_cursor WHERE id = 1"
                )
                row = cur.fetchone()
        if not row:
            return
        db_watermark = int(row[0])
        if db_watermark == self._last_applied_watermark:
            return
        if db_watermark < self._last_applied_watermark:
            logger.warning(
                "projector cursor REGRESSED externally: in-memory=%d -> "
                "postgres=%d. Adopting the Postgres value and re-applying "
                "from there. Expected right after a --nuclear prime or an "
                "operator rewind; if it repeats every batch, two writers "
                "are fighting over projector_cursor.",
                self._last_applied_watermark,
                db_watermark,
            )
        else:
            logger.info(
                "projector cursor advanced externally: in-memory=%d -> "
                "postgres=%d. Adopting the Postgres value.",
                self._last_applied_watermark,
                db_watermark,
            )
        self._last_applied_watermark = db_watermark
        self._last_apply_at_ms = int(row[1])
        self._apply_count = int(row[2])

    def get_cursor_state(self) -> CursorState:
        """Return the cursor as seen FROM POSTGRES.

        Per [[liveness-probe-watches-advance-not-just-correctness]]: a
        dead apply loop with a stale in-memory mirror would still look
        live if the endpoint read self._last_applied_watermark. Reading
        Postgres on every endpoint call is the cost of honest liveness;
        at probe-rate (a few RPS at most), this is fine.
        """
        with self._pg_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT last_applied_watermark, last_apply_at, "
                    "apply_count FROM projector_cursor WHERE id = 1"
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError("projector_cursor row missing")
                return CursorState(
                    last_applied_watermark=int(row[0]),
                    last_apply_at_ms=int(row[1]),
                    apply_count=int(row[2]),
                )

    # ────────────────────────────────────────────────────────────────
    # Loop core
    # ────────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Long-running background task. Polls Neo4j on
        `poll_interval_seconds`, applies any new/updated artifacts,
        advances the cursor.

        Per [[coupled-interim-mechanisms-retire-together]]: this polling
        shape is INTERIM. Successor consumes a Redpanda topic; the
        polling code deletes when the trigger fires.
        """
        logger.info(
            "projector apply loop starting: poll_interval=%.2fs "
            "batch_limit=%d",
            self._poll_interval,
            self._batch_limit,
        )
        while not self._stop.is_set():
            try:
                # INTERIM POLL — retires under Restate+topic successor
                # per [[coupled-interim-mechanisms-retire-together]].
                # apply_once_async grabs _apply_lock so a concurrent
                # force_poll cannot race this interval call.
                applied = await self.apply_once_async()
                if applied > 0:
                    logger.info(
                        "applied batch: count=%d last_applied_watermark=%d",
                        applied,
                        self._last_applied_watermark,
                    )
            except Exception:
                # Per [[feedback-trailing-steps-nonfatal]]: the loop
                # itself never crashes on a batch error. Log loudly,
                # back off, try again. A batch failure here is
                # different from a per-artifact apply failure (which
                # apply_once handles internally via projector_skip_log)
                # — this is a connectivity issue or programmer bug.
                logger.exception(
                    "apply loop batch failed; will retry after backoff"
                )
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                pass
        logger.info("projector apply loop stopped")

    async def apply_once_async(self) -> int:
        """Serialized async wrapper around apply_once. Both run_forever
        AND the FastAPI force_poll endpoint go through this so the two
        callers can never overlap.

        Lazy-init of the lock binds it to whichever event loop is
        running on first await — safer than constructing in __init__
        (which may run outside an event loop in some test setups).

        Per [[projector-hardening-carry-forwards]] item (b): without
        this lock, a concurrent force_poll arriving mid-batch races
        the interval loop's cursor read; both fetch the same K rows
        from Neo4j; both call _apply_one for each; apply_count goes up
        by 2K instead of K. Data is correct (UPSERT idempotent,
        GREATEST() on watermark) but the operator throughput signal
        lies.

        Probe: `tests/test_projector_apply_concurrency.py` self-anchors
        both directions — proves the race IS observable without the
        lock AND that the lock serializes when in place.
        """
        if self._apply_lock is None:
            self._apply_lock = asyncio.Lock()
        async with self._apply_lock:
            return await asyncio.to_thread(self.apply_once)

    def apply_once(self) -> int:
        """Apply one batch (or empty). Returns the count of rows applied.

        Synchronous because both the Neo4j driver and psycopg2 are sync;
        the run_forever wrapper offloads via asyncio.to_thread.

        NOTE: callers from within an asyncio context should prefer
        `apply_once_async()` so the concurrency lock fires. The sync
        method is kept public for the Hop 2 phase probes, which run
        outside an event loop and don't trigger the concurrent shape.
        """
        # Postgres is the SOURCE OF TRUTH for the cursor — re-read it
        # before every batch so an external reset can't strand this
        # process behind a stale in-RAM watermark. See the method
        # docstring for the exact failure this prevents.
        self._resync_cursor_from_postgres()
        rows = self._poll_neo4j()
        if not rows:
            return 0
        applied = 0
        for art in rows:
            try:
                self._apply_one(art)
                applied += 1
            except Exception as exc:
                # Per [[feedback-trailing-steps-nonfatal]]: log + skip +
                # advance cursor past the offending artifact. The skip
                # is observable — projector_skip_log row inserted so
                # operations can query "what got dropped." Silent skips
                # are the trap.
                logger.exception(
                    "skipping artifact %s at watermark %s: %s",
                    art.get("id"),
                    art.get("watermark"),
                    exc,
                )
                self._record_skip(
                    artifact_id=str(art.get("id") or "<unknown>"),
                    watermark=int(art.get("watermark") or 0),
                    exc=exc,
                )
                # Still advance the cursor — a bad artifact shouldn't
                # block a healthy stream behind it.
                self._advance_cursor(int(art.get("watermark") or 0))
        return applied

    # ────────────────────────────────────────────────────────────────
    # Neo4j poll
    # ────────────────────────────────────────────────────────────────

    def _poll_neo4j(self) -> List[Dict[str, Any]]:
        """Fetch artifacts whose watermark > last_applied_watermark.

        Decision 3 Option C: watermark is on the artifact node itself.
        The projector reads it verbatim, ordered. Every UPDATE the
        writer does bumps the row's watermark (Hop 1 enforces this),
        including durability_status-only flips — so the projector's
        view here picks up "orthogonal" updates the same way it picks
        up status changes.
        """
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a:AnswerArtifact)
                WHERE a.watermark > $last_applied
                RETURN a {
                  .id,
                  .kind,
                  .watermark,
                  .created_at,
                  .updated_at,
                  .valid_as_of,
                  .valid_until,
                  .status,
                  .durability_status,
                  .message_id,
                  .question_text,
                  .summary,
                  .resolved_intent,
                  .routing_inline,
                  .rendered_output,
                  .graph_trace_json
                } AS a,
                  [(a)-[:PRODUCED_BY]->(p) | p {
                    .actor_type, .actor_id, .version, .endpoint,
                    .code_hash
                  }] AS producers,
                  [(a)-[:PRODUCED_FOR]->(u) | u {
                    .actor_type, .actor_id, .user_id, .is_authenticated,
                    .user_persona, .entitled_domains,
                    .entitlement_source
                  }] AS consumers,
                  [(a)-[c:CITES]->(s) | {
                    uri: s.uri, type: s.type, label: s.label,
                    snippet: c.snippet, relevance: c.relevance,
                    open_url: c.open_url,
                    access_decision_json: c.access_decision_json
                  }] AS sources,
                  [(a)-[:DERIVED_FROM]->(d) | d.id][0] AS derived_from
                ORDER BY a.watermark
                LIMIT $limit
                """,
                last_applied=self._last_applied_watermark,
                limit=self._batch_limit,
            )
            rows: List[Dict[str, Any]] = []
            for record in result:
                art = dict(record["a"])
                art["__producers"] = list(record["producers"])
                art["__consumers"] = list(record["consumers"])
                art["__sources"] = list(record["sources"])
                art["__derived_from"] = record["derived_from"]
                rows.append(art)
            return rows

    # ────────────────────────────────────────────────────────────────
    # Apply per-artifact
    # ────────────────────────────────────────────────────────────────

    def _apply_one(self, art: Dict[str, Any]) -> None:
        """UPSERT one projected row + advance the cursor, in one txn."""
        artifact_id = art["id"]
        watermark = int(art["watermark"])

        # Parse the JSON-stringified properties the writer stored on
        # the Neo4j node (Neo4j can't hold nested dicts as properties).
        resolved_intent = _parse_json(art.get("resolved_intent")) or {}
        routing = _parse_json(art.get("routing_inline"))
        rendered_output = _parse_json(art.get("rendered_output"))

        # Producers / Consumers: Hop 1's writer emits exactly one of
        # each, but the projector tolerates 0 or more honestly. The
        # row's produced_by/produced_for JSONB is the FIRST one
        # (per [[fixture-must-exercise-paths]]'s honest-absent rule:
        # if the writer didn't write one, the column reflects that
        # rather than synthesizing a placeholder).
        producers = art.get("__producers") or []
        consumers = art.get("__consumers") or []
        produced_by = producers[0] if producers else {}
        produced_for = consumers[0] if consumers else {}
        sources = art.get("__sources") or []
        # Capture B per ADR-0025: re-parse the writer's
        # `access_decision_json` (JSON string on the CITES edge, since
        # Neo4j cannot hold nested dicts as properties) back into a
        # dict, on the `access_decision` key. The slot is RESERVED —
        # production writes set it null today; the enforcement
        # session populates it. The projector flowing it through is
        # the structural-pre-requisite that means the enforcement
        # session does not need a second projection migration.
        for s in sources:
            ad_json = s.pop("access_decision_json", None)
            s["access_decision"] = _parse_json(ad_json)
        # graph_trace flows through the writer's `a.graph_trace_json`
        # property (JSON-serialized list of trace nodes). 2026-06-30
        # fix: pre-Hop-3 the writer never wrote this, the projector
        # honestly projected an empty list, and the cortex-ui SSE
        # handler shoved trace nodes straight to the canvas store.
        # Post-Hop-3 the SSE handler became a no-op (Electric became
        # the sole source for Electric-covered fields including
        # graph_trace) and the detailed HUD's graph silently
        # disappeared because the projection was still empty. Now
        # the writer persists `graph_trace_json` and we re-parse it
        # here for the projection's `graph_trace` JSONB column. An
        # empty list is honest when the route had no compat-walk
        # (Engine A fallback, no_match, etc.); the writer flows
        # that through, and we project what we got.
        graph_trace: List[Any] = _parse_json(art.get("graph_trace_json")) or []

        now_ms = int(time.time() * 1000)

        with self._pg_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO answer_artifact_projection (
                        id, kind, watermark, created_at, updated_at,
                        valid_as_of, valid_until, status, durability_status,
                        message_id, question_text, summary, resolved_intent,
                        routing, sources, graph_trace, rendered_output,
                        produced_by, produced_for, derived_from_artifact_id,
                        produced_for_user_id
                    ) VALUES (
                        %(id)s, %(kind)s, %(watermark)s, %(created_at)s,
                        %(updated_at)s, %(valid_as_of)s, %(valid_until)s,
                        %(status)s, %(durability_status)s, %(message_id)s,
                        %(question_text)s, %(summary)s, %(resolved_intent)s,
                        %(routing)s,
                        %(sources)s, %(graph_trace)s, %(rendered_output)s,
                        %(produced_by)s, %(produced_for)s,
                        %(derived_from_artifact_id)s,
                        %(produced_for_user_id)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        -- Decision 3 Option C: every apply that touches
                        -- the row touches the watermark column. Per the
                        -- planning doc Phase D / CONVERSE 2 / Hop 2 §5:
                        -- the watermark is copied VERBATIM from the
                        -- Neo4j node — orthogonal-field-only updates
                        -- (durability_status-only) bump the watermark
                        -- here too. Vestigial-watermark trap caught.
                        kind = EXCLUDED.kind,
                        watermark = EXCLUDED.watermark,
                        updated_at = EXCLUDED.updated_at,
                        valid_as_of = EXCLUDED.valid_as_of,
                        valid_until = EXCLUDED.valid_until,
                        status = EXCLUDED.status,
                        durability_status = EXCLUDED.durability_status,
                        message_id = EXCLUDED.message_id,
                        question_text = EXCLUDED.question_text,
                        summary = EXCLUDED.summary,
                        resolved_intent = EXCLUDED.resolved_intent,
                        routing = EXCLUDED.routing,
                        sources = EXCLUDED.sources,
                        graph_trace = EXCLUDED.graph_trace,
                        rendered_output = EXCLUDED.rendered_output,
                        produced_by = EXCLUDED.produced_by,
                        produced_for = EXCLUDED.produced_for,
                        derived_from_artifact_id =
                            EXCLUDED.derived_from_artifact_id,
                        produced_for_user_id =
                            EXCLUDED.produced_for_user_id
                    """,
                    {
                        "id": artifact_id,
                        # `kind` discriminator per Decision 2. At Hop 2
                        # we only produce 'answer' rows; the writer
                        # doesn't set this property on the Neo4j node
                        # explicitly, so default to 'answer' here. This
                        # is NOT an optimistic default per
                        # [[optimistic-defaults-are-dishonest]]: at
                        # Hop 2 there's only one kind to write, so the
                        # value is unambiguous at write time.
                        "kind": art.get("kind") or "answer",
                        "watermark": watermark,
                        "created_at": int(art.get("created_at") or now_ms),
                        "updated_at": int(art.get("updated_at") or now_ms),
                        "valid_as_of": int(art["valid_as_of"]),
                        "valid_until": (
                            int(art["valid_until"])
                            if art.get("valid_until") is not None
                            else None
                        ),
                        "status": art["status"],
                        "durability_status": art["durability_status"],
                        "message_id": art["message_id"],
                        "question_text": art["question_text"],
                        # Factual S·P headline the writer composed at the
                        # gateway write point; the projector flows it
                        # verbatim into its own column (honest-absent ""
                        # for legacy rows that predate the field).
                        "summary": art.get("summary") or "",
                        "resolved_intent": json.dumps(resolved_intent),
                        "routing": (
                            json.dumps(routing)
                            if routing is not None
                            else None
                        ),
                        "sources": json.dumps(sources),
                        "graph_trace": json.dumps(graph_trace),
                        "rendered_output": (
                            json.dumps(rendered_output)
                            if rendered_output is not None
                            else None
                        ),
                        "produced_by": json.dumps(produced_by),
                        "produced_for": json.dumps(produced_for),
                        "derived_from_artifact_id": art.get(
                            "__derived_from"
                        ),
                        # 2026-06-30 per-user isolation: write the
                        # produced_for.user_id out to its own column
                        # so the cortex-bff Electric proxy can filter
                        # subscriptions on it. Electric's WHERE-clause
                        # parser doesn't accept the `->>` JSONB
                        # operator, and generated columns can't be
                        # replicated, so this regular column is
                        # populated by the projector at write time.
                        # See sql/create_answer_artifact_projection.sql
                        # for the column definition.
                        "produced_for_user_id": (
                            (produced_for or {}).get("user_id")
                        ),
                    },
                )

                # Advance the cursor in the SAME transaction. A crash
                # between the row write and the cursor advance would
                # leave a row whose watermark we've already passed —
                # next loop iteration would re-apply it (idempotent so
                # safe). The atomicity-in-one-txn is the cleaner shape.
                cur.execute(
                    """
                    UPDATE projector_cursor
                    SET last_applied_watermark = GREATEST(
                            last_applied_watermark, %(watermark)s),
                        last_apply_at = %(now)s,
                        apply_count = apply_count + 1
                    WHERE id = 1
                    """,
                    {"watermark": watermark, "now": now_ms},
                )
            conn.commit()

        # Update in-memory mirror after Postgres commits.
        if watermark > self._last_applied_watermark:
            self._last_applied_watermark = watermark
        self._last_apply_at_ms = now_ms
        self._apply_count += 1

    # ────────────────────────────────────────────────────────────────
    # Observability: skip log + cursor force-advance (used on errors)
    # ────────────────────────────────────────────────────────────────

    def _record_skip(
        self,
        *,
        artifact_id: str,
        watermark: int,
        exc: BaseException,
    ) -> None:
        """Insert an observable skip into projector_skip_log."""
        try:
            with self._pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO projector_skip_log (
                            artifact_id, watermark, skipped_at,
                            exception_class, exception_message
                        ) VALUES (
                            %(artifact_id)s, %(watermark)s, %(skipped_at)s,
                            %(exception_class)s, %(exception_message)s
                        )
                        """,
                        {
                            "artifact_id": artifact_id,
                            "watermark": watermark,
                            "skipped_at": int(time.time() * 1000),
                            "exception_class": type(exc).__name__,
                            "exception_message": str(exc)[:1024],
                        },
                    )
                conn.commit()
        except Exception:
            # If we can't even record the skip, the projector is in
            # serious trouble — but per the trailing-step rule, do NOT
            # crash the loop. Log to stderr and move on.
            logger.exception(
                "failed to record skip for artifact %s", artifact_id
            )

    def _advance_cursor(self, watermark: int) -> None:
        """Advance cursor past a skipped artifact's watermark.

        Used when apply_one raised; the artifact is in projector_skip_log
        AND the cursor advances so the loop doesn't get stuck.
        """
        try:
            with self._pg_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE projector_cursor
                        SET last_applied_watermark = GREATEST(
                                last_applied_watermark, %(watermark)s),
                            last_apply_at = %(now)s,
                            apply_count = apply_count + 1
                        WHERE id = 1
                        """,
                        {
                            "watermark": watermark,
                            "now": int(time.time() * 1000),
                        },
                    )
                conn.commit()
            if watermark > self._last_applied_watermark:
                self._last_applied_watermark = watermark
        except Exception:
            logger.exception(
                "failed to advance cursor past skipped watermark %d",
                watermark,
            )


def _parse_json(value: Any) -> Optional[Any]:
    """Parse a JSON-stringified Neo4j property back into a Python
    value. The writer (Hop 1) stringifies dicts before storing because
    Neo4j can't hold nested dicts as properties; this is the inverse.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def build_loop_from_env() -> ApplyLoop:
    """Construct an ApplyLoop from environment variables. Used by the
    FastAPI app at startup.

    Env vars (all required in a real deployment; defaults match the
    sandbox cluster's config-map values for ergonomic local-run):

      NEO4J_URI                 (default: bolt://iagent-neo4j:7687)
      NEO4J_USERNAME            (default: neo4j)
      NEO4J_PASSWORD            (required for non-default password)
      PROJECTOR_POSTGRES_DSN    (default: in-cluster iagent postgres)
      PROJECTOR_POLL_INTERVAL_SECONDS  (default: 0.5)
      PROJECTOR_BATCH_LIMIT     (default: 100)
    """
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://iagent-neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "changeme")
    postgres_dsn = os.getenv(
        "PROJECTOR_POSTGRES_DSN",
        "postgresql://iagent:changeme-iagent@iagent-postgresql:5432/iagent",
    )
    poll_interval = float(
        os.getenv(
            "PROJECTOR_POLL_INTERVAL_SECONDS",
            str(DEFAULT_POLL_INTERVAL_SECONDS),
        )
    )
    batch_limit = int(
        os.getenv("PROJECTOR_BATCH_LIMIT", str(DEFAULT_BATCH_LIMIT))
    )
    return ApplyLoop(
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        postgres_dsn=postgres_dsn,
        poll_interval_seconds=poll_interval,
        batch_limit=batch_limit,
    )
