"""Hop 2 probes — projector apply against real substrate.

Closes gate 4 of docs/plans/projector-build-plan.md (commit 0eda9f7),
§3.6 + §5. Four phases per the planning doc, all RED-first per
[[pre-written-fixtures-must-fail-first]].

Phases:
  A — basic propagation (insert → projected row)
  B — update propagation (Neo4j status flip → projected row updates)
  C — restart drain (kill projector; new write; restart; cursor honored)
  D — orthogonal-field + watermark-advanced co-required
      (the load-bearing one — durability_status-ONLY flip at Neo4j,
       BOTH propagation AND watermark advance asserted; the Cypher
       fixture mutates ONLY durability_status + watermark; do NOT use
       the writer's bundle-MERGE path or the green is hollow per
       [[verify-subtle-acceptance-by-inspection]] + the architect's
       specific guardrail.)

Run (with sandbox port-forwards in place):
    kubectl -n sandbox port-forward svc/iagent-neo4j 17687:7687 &
    kubectl -n sandbox port-forward svc/iagent-postgresql 15432:5432 &
    PROBE_NEO4J_PASSWORD=changeme-neo4j-sandbox \\
    PROBE_PG_DSN=postgresql://iagent:changeme-iagent-sandbox@localhost:15432/iagent \\
    uv run pytest tests/test_hop2_projector_apply.py -v

The probe spawns the projector loop in-process against the
port-forwarded substrate (no in-cluster deploy required for the probe
to fire — see the planning prompt's "kubectl-logs OR local-equivalent
stderr" allowance for liveness).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

import psycopg2
import psycopg2.extras
import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from src.iagent.answer_artifact_writer import (
    AnswerArtifactBundle,
    AnswerArtifactWriter,
    DurabilityStatus,
)


# ── Substrate connection knobs ──

_NEO4J_URI = os.getenv("PROBE_NEO4J_URI", "bolt://localhost:17687")
_NEO4J_USERNAME = os.getenv("PROBE_NEO4J_USERNAME", "neo4j")
_NEO4J_PASSWORD = os.getenv("PROBE_NEO4J_PASSWORD", "changeme-neo4j-sandbox")
_PG_DSN = os.getenv(
    "PROBE_PG_DSN",
    "postgresql://iagent:changeme-iagent-sandbox@localhost:15432/iagent",
)


def _neo4j_driver_or_skip():
    try:
        driver = GraphDatabase.driver(
            _NEO4J_URI,
            auth=(_NEO4J_USERNAME, _NEO4J_PASSWORD),
            connection_timeout=2.0,
        )
        driver.verify_connectivity()
        return driver
    except (ServiceUnavailable, Exception) as exc:
        pytest.skip(
            f"Neo4j unreachable at {_NEO4J_URI}: {exc}. "
            "Run port-forward and ensure PROBE_NEO4J_PASSWORD is set."
        )


def _pg_or_skip():
    try:
        conn = psycopg2.connect(_PG_DSN, connect_timeout=2)
        conn.close()
        return _PG_DSN
    except Exception as exc:
        pytest.skip(
            f"Postgres unreachable at {_PG_DSN}: {exc}. "
            "Run port-forward and ensure migration applied."
        )


@contextmanager
def _pg_conn() -> Iterator["psycopg2.extensions.connection"]:
    conn = psycopg2.connect(_PG_DSN)
    try:
        yield conn
    finally:
        conn.close()


# ── Fixtures: bundle, projector loop, neo4j purge ──


def _make_bundle(artifact_id: str, *, status: str = "complete") -> AnswerArtifactBundle:
    return AnswerArtifactBundle(
        id=artifact_id,
        question_text=f"hop2 probe — {artifact_id}",
        message_id=f"msg-hop2-{uuid.uuid4().hex[:6]}",
        valid_as_of=int(time.time() * 1000),
        status=status,
        produced_by={
            "actor_type": "agent",
            "actor_id": "iagent-engine-a",
            "version": "0.1.0",
            "endpoint": "http://iagent-engine-a:8082",
        },
        produced_for={
            "user_id": "test-user-7d",
            "is_authenticated": True,
            "user_persona": None,
            "entitled_domains": None,
        },
        resolved_intent={
            "subject_uri": "mesh:Engine_A",
            "verb_iri": "mesh:retrieveKnowledge",
            "parameters": {},
        },
        routing={
            "action": {
                "iri": "mesh:retrieveKnowledge",
                "owner_persona": "DATA_STEWARD",
            },
            "about": {"uri": "mesh:Engine_A"},
        },
        sources=[
            {
                "uri": (
                    "urn:li:dataset:"
                    "(urn:li:dataPlatform:datahub,engine_a,PROD)"
                ),
                "type": "dataset",
                "label": "engine_a dataset",
                "snippet": "owner_persona: DATA_STEWARD",
            }
        ],
        graph_trace=[],
        rendered_output={
            "components": [
                {"archetype": "ANSWER_TEXT", "text": "DATA_STEWARD"}
            ],
            "archetype": "ANSWER_TEXT",
        },
        derived_from_artifact_id=None,
    )


def _purge(driver, artifact_id: str) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (a:AnswerArtifact {id: $id}) DETACH DELETE a",
            id=artifact_id,
        )
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM answer_artifact_projection WHERE id = %s",
                (artifact_id,),
            )
        conn.commit()


def _read_projection(artifact_id: str) -> Optional[Dict[str, Any]]:
    with _pg_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM answer_artifact_projection WHERE id = %s",
                (artifact_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def _read_cursor() -> Dict[str, int]:
    with _pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_applied_watermark, last_apply_at, apply_count "
                "FROM projector_cursor WHERE id = 1"
            )
            row = cur.fetchone()
            assert row is not None, "projector_cursor row missing"
            return {
                "last_applied_watermark": int(row[0]),
                "last_apply_at": int(row[1]),
                "apply_count": int(row[2]),
            }


def _build_loop():
    """Build an ApplyLoop pointed at the port-forwarded substrate."""
    from src.iagent.projector.apply_loop import ApplyLoop

    return ApplyLoop(
        neo4j_uri=_NEO4J_URI,
        neo4j_user=_NEO4J_USERNAME,
        neo4j_password=_NEO4J_PASSWORD,
        postgres_dsn=_PG_DSN,
        poll_interval_seconds=0.25,
        batch_limit=100,
    )


# ────────────────────────────────────────────────────────────────────
# Phase A — basic propagation (@projection-row-appears)
# ────────────────────────────────────────────────────────────────────


def test_phase_a_projection_row_appears() -> None:
    """RED-first reason: before the projector module + migration land,
    the row never appears (table doesn't exist OR no loop applies it).
    GREEN reason: projector applies it; row exists; cursor advanced.
    """
    _pg_or_skip()
    driver = _neo4j_driver_or_skip()
    artifact_id = f"urn:li:answerArtifact:phaseA-{uuid.uuid4().hex[:8]}"
    try:
        _purge(driver, artifact_id)
        writer = AnswerArtifactWriter(driver=driver, max_retries=2)
        bundle = _make_bundle(artifact_id, status="complete")
        result = writer.write_sync(bundle)
        assert result.success, f"write failed: {result.error!r}"

        # Drive one apply batch (cuts the 250ms poll wait).
        loop = _build_loop()
        applied = loop.apply_once()
        assert applied >= 1, "projector apply_once did not apply any row"
        loop.close()

        row = _read_projection(artifact_id)
        assert row is not None, "projection row missing after apply"
        assert row["status"] == "complete"
        assert row["durability_status"] == DurabilityStatus.DURABLE
        assert row["watermark"] > 0
        assert row["routing"] is not None
        assert row["rendered_output"] is not None
        assert row["question_text"] == bundle.question_text
        # sources JSONB round-trips
        srcs = row["sources"]
        assert isinstance(srcs, list) and len(srcs) >= 1
        assert "datahub" in (srcs[0].get("uri") or "")

        cursor = _read_cursor()
        assert cursor["last_applied_watermark"] >= row["watermark"]
    finally:
        _purge(driver, artifact_id)
        driver.close()


# ────────────────────────────────────────────────────────────────────
# Phase B — update propagation (@projection-row-updates)
# ────────────────────────────────────────────────────────────────────


def test_phase_b_projection_row_updates() -> None:
    """RED-first reason: an insert-only projector would advance the row
    once and never re-apply on subsequent watermark bumps; updated_at
    and watermark would not advance.
    """
    _pg_or_skip()
    driver = _neo4j_driver_or_skip()
    artifact_id = f"urn:li:answerArtifact:phaseB-{uuid.uuid4().hex[:8]}"
    try:
        _purge(driver, artifact_id)
        writer = AnswerArtifactWriter(driver=driver, max_retries=2)
        bundle = _make_bundle(artifact_id, status="complete")
        writer.write_sync(bundle)

        loop = _build_loop()
        loop.apply_once()

        row1 = _read_projection(artifact_id)
        assert row1 is not None
        wm1 = row1["watermark"]
        updated_at1 = row1["updated_at"]

        # Issue a follow-up write — same bundle, replay-as-update.
        time.sleep(0.01)
        result2 = writer.write_sync(bundle)
        assert result2.success
        assert result2.watermark > wm1, (
            "writer didn't bump watermark on replay — Hop 1 broken, "
            "Hop 2 test inapplicable"
        )

        loop.apply_once()
        row2 = _read_projection(artifact_id)
        assert row2 is not None
        assert row2["watermark"] > wm1, (
            f"projection watermark {row2['watermark']} did not advance "
            f"past {wm1} — update propagation broken"
        )
        assert row2["updated_at"] >= updated_at1, (
            "updated_at did not advance on the second apply"
        )
        loop.close()
    finally:
        _purge(driver, artifact_id)
        driver.close()


# ────────────────────────────────────────────────────────────────────
# Phase C — restart drain (@projector-resumes-from-cursor)
# ────────────────────────────────────────────────────────────────────


def test_phase_c_projector_resumes_from_cursor() -> None:
    """RED-first reason: a projector that resets last_applied_watermark
    to 0 on startup would re-apply A AND apply B — apply_count after
    restart would jump by more than 1.

    GREEN reason: cursor read at startup; only B applied on restart;
    apply_count incremented by exactly 1.
    """
    _pg_or_skip()
    driver = _neo4j_driver_or_skip()
    artifact_a = f"urn:li:answerArtifact:phaseC-A-{uuid.uuid4().hex[:8]}"
    artifact_b = f"urn:li:answerArtifact:phaseC-B-{uuid.uuid4().hex[:8]}"
    try:
        _purge(driver, artifact_a)
        _purge(driver, artifact_b)
        writer = AnswerArtifactWriter(driver=driver, max_retries=2)

        # Apply A through projector instance 1.
        writer.write_sync(_make_bundle(artifact_a, status="complete"))
        loop1 = _build_loop()
        loop1.apply_once()
        cursor_after_a = _read_cursor()
        wm_a = _read_projection(artifact_a)["watermark"]
        assert (
            cursor_after_a["last_applied_watermark"] >= wm_a
        ), "cursor didn't advance after A"
        apply_count_after_a = cursor_after_a["apply_count"]

        # Kill loop1.
        loop1.close()

        # Write B while no projector is running. B's watermark > A's.
        writer.write_sync(_make_bundle(artifact_b, status="complete"))
        # Confirm Postgres does NOT yet have B (no projector ran).
        assert _read_projection(artifact_b) is None, (
            "B leaked into projection without a projector running"
        )

        # Start a NEW projector (loop2). Its constructor reloads the
        # cursor from Postgres; if it didn't, last_applied_watermark
        # would be 0 in memory and it would re-apply A (apply_count
        # would jump by 2 here).
        loop2 = _build_loop()
        applied = loop2.apply_once()
        loop2.close()
        # Exactly one new row applied — B. (A's watermark is below the
        # cursor; the poll query skipped A.)
        assert applied == 1, (
            f"projector applied {applied} rows on restart; expected 1 "
            f"(B). Cursor not honored — A was re-applied."
        )

        row_b = _read_projection(artifact_b)
        assert row_b is not None, "B not projected after restart"
        cursor_final = _read_cursor()
        assert cursor_final["last_applied_watermark"] >= row_b["watermark"]
        # apply_count grew by exactly 1 (only B applied).
        assert (
            cursor_final["apply_count"] == apply_count_after_a + 1
        ), (
            f"apply_count jumped from {apply_count_after_a} to "
            f"{cursor_final['apply_count']} — projector re-applied A on "
            f"restart instead of resuming from cursor"
        )
    finally:
        _purge(driver, artifact_a)
        _purge(driver, artifact_b)
        driver.close()


# ────────────────────────────────────────────────────────────────────
# Phase D — orthogonal field + watermark advance co-required
# ────────────────────────────────────────────────────────────────────
#
# THE LOAD-BEARING PROBE. Read the architect's guardrail in the
# planning prompt:
#
# "A Phase D fixture that does a full-bundle MERGE would advance the
# watermark FOR THE WRONG REASON — full-replay advances the watermark
# because EVERYTHING changed, not because the durability-only-update
# path advanced it. That green is hollow. The fixture MUST mutate ONLY
# the durability_status column at Neo4j."
#
# The Cypher below is the load-bearing acceptance criterion. INSPECT
# IT before trusting GREEN per [[verify-subtle-acceptance-by-inspection]].
#
# Mutated fields at Neo4j (orthogonal-update fixture):
#   a.durability_status  ← 'durable'  (the orthogonal field)
#   a.watermark          ← <bumped>   (required by Decision 3 Option C
#                                      — every UPDATE bumps watermark)
# UN-mutated fields (the inspection contract):
#   a.status             stays 'complete'
#   a.rendered_output    stays unchanged
#   a.routing_inline     stays unchanged
#   a.updated_at         stays unchanged (intentionally — we don't
#                          touch it so the post-apply row's
#                          updated_at proves the projector's apply,
#                          not the fixture's mutation)
#   (all other props)    untouched
#
# The two co-required assertions:
#   A. Projection durability_status flipped to 'durable' (propagation
#      caught the orthogonal field; the projector did NOT collapse
#      durability_status into status).
#   B. Projection watermark STRICTLY advanced past its pre-flip value
#      (Decision 3 Option C: the projector copied the new watermark
#      column even on a durability-only update — vestigial-watermark
#      trap caught).
# ────────────────────────────────────────────────────────────────────


# This Cypher is the load-bearing fixture. The architect's guardrail
# says: this MUST mutate ONLY durability_status and watermark. Any
# additional SET clause here would invalidate the test.
PHASE_D_ORTHOGONAL_UPDATE_CYPHER = """
MERGE (s:WatermarkSequence {key: 'answer_artifact'})
ON CREATE SET s.value = 0
SET s.value = s.value + 1
WITH s.value AS new_watermark
MATCH (a:AnswerArtifact {id: $id})
SET a.durability_status = 'durable',
    a.watermark = new_watermark
RETURN a.watermark AS watermark,
       a.durability_status AS durability_status,
       a.status AS status
""".strip()


def test_phase_d_orthogonal_field_and_watermark_advance() -> None:
    """RED-first reasons:
      1. Before the projector exists: durability_status never updates;
         Assertion A fails.
      2. If the projector exists but its UPSERT branches on status
         (skip-if-only-durability-changed): Assertion A still fails.
      3. If the projector applies updates but keeps the OLD watermark:
         Assertion B fails (the vestigial-watermark trap).
    """
    _pg_or_skip()
    driver = _neo4j_driver_or_skip()
    artifact_id = f"urn:li:answerArtifact:phaseD-{uuid.uuid4().hex[:8]}"
    try:
        _purge(driver, artifact_id)

        # 1. Set up the "post-delivery, mid-retry" state at Neo4j:
        #    status='complete', durability_status='persistence_pending'.
        #
        #    We write the bundle through the writer first (which lands
        #    durability_status='durable' on success — exactly what we
        #    DON'T want), then immediately flip durability_status back
        #    to 'persistence_pending' WITHOUT touching anything else.
        #    The deliberate setup-flip uses a targeted Cypher so it
        #    parallels the test fixture exactly (no full re-MERGE).
        writer = AnswerArtifactWriter(driver=driver, max_retries=2)
        bundle = _make_bundle(artifact_id, status="complete")
        writer.write_sync(bundle)

        with driver.session() as session:
            # Setup-only flip: durability_status back to pending +
            # bump watermark. ONLY two fields touched.
            session.run(
                """
                MERGE (s:WatermarkSequence {key: 'answer_artifact'})
                ON CREATE SET s.value = 0
                SET s.value = s.value + 1
                WITH s.value AS new_wm
                MATCH (a:AnswerArtifact {id: $id})
                SET a.durability_status = 'persistence_pending',
                    a.watermark = new_wm
                """,
                id=artifact_id,
            )

        # 2. Run one apply so the projection has the
        #    persistence_pending state. We snapshot watermark + state
        #    here as the pre-flip baseline.
        loop = _build_loop()
        loop.apply_once()
        row_before = _read_projection(artifact_id)
        assert row_before is not None
        assert row_before["status"] == "complete"
        assert (
            row_before["durability_status"]
            == DurabilityStatus.PERSISTENCE_PENDING
        )
        wm_before = row_before["watermark"]
        status_before = row_before["status"]
        rendered_before = row_before["rendered_output"]
        routing_before = row_before["routing"]

        # 3. Apply the load-bearing fixture: mutate ONLY
        #    durability_status + watermark at Neo4j. THIS is the
        #    architect-guardrail Cypher.
        with driver.session() as session:
            rec = session.run(
                PHASE_D_ORTHOGONAL_UPDATE_CYPHER, id=artifact_id
            ).single()
        wm_neo4j_after = int(rec["watermark"])
        assert rec["durability_status"] == DurabilityStatus.DURABLE
        assert rec["status"] == "complete"  # status untouched at Neo4j
        assert wm_neo4j_after > wm_before, (
            "Phase D fixture didn't bump the Neo4j watermark — fixture "
            "broken before any projector behavior is asserted"
        )

        # 4. Run apply. Now both co-required assertions must hold.
        loop.apply_once()
        loop.close()

        row_after = _read_projection(artifact_id)
        assert row_after is not None

        # ── Assertion A (orthogonal field propagation) ──
        assert row_after["durability_status"] == DurabilityStatus.DURABLE, (
            f"Assertion A FAILED: durability_status is "
            f"{row_after['durability_status']!r} — the projector did "
            f"not propagate the orthogonal-field flip. Either the "
            f"projector skipped because only durability_status "
            f"changed, OR it collapsed durability_status into status."
        )
        # status MUST still be 'complete' — proof the projector did
        # NOT collapse durability_status into status.
        assert row_after["status"] == status_before, (
            f"Assertion A guard FAILED: status flipped from "
            f"{status_before!r} to {row_after['status']!r}. The "
            f"projector collapsed durability_status into status — the "
            f"two fields are orthogonal per Decision 0's sub-decision."
        )

        # ── Assertion B (watermark STRICTLY advanced on orthogonal
        #    update; vestigial-watermark trap caught) ──
        assert row_after["watermark"] > wm_before, (
            f"Assertion B FAILED: watermark is still {row_after['watermark']} "
            f"(was {wm_before}). The projector applied the "
            f"durability_status change but kept the OLD watermark — "
            f"this is the vestigial-watermark trap per Decision 3 "
            f"Option C / [[verify-subtle-acceptance-by-inspection]]."
        )
        assert row_after["watermark"] == wm_neo4j_after, (
            f"Assertion B guard FAILED: projection watermark "
            f"{row_after['watermark']} != Neo4j watermark "
            f"{wm_neo4j_after}. The projector computed a different "
            f"value instead of copying the column verbatim."
        )

        # Cursor advanced past the new watermark.
        cursor = _read_cursor()
        assert cursor["last_applied_watermark"] >= wm_neo4j_after, (
            f"projector_cursor.last_applied_watermark "
            f"{cursor['last_applied_watermark']} < new watermark "
            f"{wm_neo4j_after} — cursor advance broken on orthogonal "
            f"update"
        )

        # Inspection by-eye: the non-mutated fields stayed put.
        assert row_after["rendered_output"] == rendered_before, (
            "rendered_output drifted across the orthogonal update — "
            "the projector touched a field the fixture did not"
        )
        assert row_after["routing"] == routing_before, (
            "routing drifted across the orthogonal update"
        )
    finally:
        _purge(driver, artifact_id)
        driver.close()
