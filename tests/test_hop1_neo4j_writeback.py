"""Hop 1 Probe 1 — happy-path readback by traversal.

Writes an AnswerArtifact bundle through the cortex-bff writer module
against real Neo4j (the sandbox cluster, port-forwarded), then reads it
back BY TRAVERSAL (not by mock) per the planning prompt's
"[[fixture-must-exercise-paths]]" discipline.

Predicted-RED reason (before implementation): the module
`src.iagent.answer_artifact_writer` does not exist yet, so the import
fails. After implementation: GREEN — the AnswerArtifact node + edges
are queryable from Neo4j; idempotent replay holds; the watermark
advanced on the replay-as-update.

Prereq:
    kubectl -n sandbox port-forward svc/iagent-neo4j 17687:7687 &
    NEO4J_PASSWORD=changeme-neo4j-sandbox

Run:
    uv run pytest tests/test_hop1_neo4j_writeback.py -v

Plan reference: c:/Users/cnogr/git/invincible-agent/docs/plans/projector-build-plan.md
commit 0eda9f7, §4 Probe 1, §3.6 gate 3.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

# Predicted-RED reason: this import fails until the writer module exists.
from src.iagent.answer_artifact_writer import (  # noqa: E402
    AnswerArtifactBundle,
    AnswerArtifactWriter,
    DurabilityStatus,
)


_NEO4J_URI = os.getenv("PROBE_NEO4J_URI", "bolt://localhost:17687")
_NEO4J_USERNAME = os.getenv("PROBE_NEO4J_USERNAME", "neo4j")
_NEO4J_PASSWORD = os.getenv("PROBE_NEO4J_PASSWORD", "changeme-neo4j-sandbox")


def _driver_or_skip():
    """Return a verified driver or skip the test if Neo4j is unreachable.

    The Probe 1 contract requires a real Neo4j; if the port-forward isn't
    open, the probe is inapplicable, not failing. Skipping (vs failing) is
    correct here — Probe 2 covers the unreachable-Neo4j case explicitly.
    """
    try:
        driver = GraphDatabase.driver(
            _NEO4J_URI,
            auth=(_NEO4J_USERNAME, _NEO4J_PASSWORD),
            connection_timeout=2.0,
        )
        driver.verify_connectivity()
        return driver
    except (ServiceUnavailable, Exception) as exc:  # pragma: no cover — skip
        pytest.skip(
            f"Neo4j unreachable at {_NEO4J_URI}: {exc}. "
            f"Run `kubectl -n sandbox port-forward svc/iagent-neo4j 17687:7687 &` "
            f"and ensure PROBE_NEO4J_PASSWORD is set."
        )


def _purge(driver, artifact_id: str) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (a:AnswerArtifact {id: $id}) "
            "DETACH DELETE a",
            id=artifact_id,
        )


def _make_bundle(artifact_id: str) -> AnswerArtifactBundle:
    return AnswerArtifactBundle(
        id=artifact_id,
        question_text=(
            "what is engine A's owner_persona for retrieveKnowledge?"
        ),
        message_id="msg-hop1-001",
        valid_as_of=int(time.time() * 1000),
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


def test_probe1_happy_path_traversal_readback() -> None:
    """Write → readback by traversal → assert node + edges + properties.

    Idempotent replay: the second write does NOT duplicate the node;
    the watermark on the row STRICTLY ADVANCES (vestigial-watermark
    trap caught).
    """
    artifact_id = f"urn:li:answerArtifact:probe1-{uuid.uuid4().hex[:8]}"
    driver = _driver_or_skip()
    try:
        _purge(driver, artifact_id)

        writer = AnswerArtifactWriter(
            driver=driver,
            max_retries=3,
            backoff_seconds=0.1,
        )

        bundle = _make_bundle(artifact_id)

        # First write — synchronous so the readback below sees the
        # committed state. The writer module exposes a sync method
        # specifically for probe / repair use; the async dispatch is
        # what the SSE generator uses in production.
        result1 = writer.write_sync(bundle)
        assert result1.success, f"first write failed: {result1.error!r}"
        assert result1.watermark > 0, "watermark not assigned on first write"

        # ── READBACK BY TRAVERSAL ──
        with driver.session() as session:
            rec = session.run(
                """
                MATCH (a:AnswerArtifact {id: $id})
                OPTIONAL MATCH (a)-[:PRODUCED_BY]->(producer:Actor)
                OPTIONAL MATCH (a)-[:PRODUCED_FOR]->(consumer:Actor)
                OPTIONAL MATCH (a)-[r_cites:CITES]->(s:Source)
                RETURN
                  a.id AS id,
                  a.valid_as_of AS valid_as_of,
                  a.durability_status AS durability_status,
                  a.watermark AS watermark,
                  a.status AS status,
                  a.question_text AS question_text,
                  producer.actor_type AS producer_type,
                  producer.actor_id AS producer_id,
                  consumer.user_id AS consumer_user_id,
                  collect(DISTINCT s.uri) AS source_uris
                """,
                id=artifact_id,
            ).single()
        assert rec is not None, "AnswerArtifact node missing after write"
        assert rec["id"] == artifact_id
        assert rec["valid_as_of"] is not None and rec["valid_as_of"] > 0
        assert rec["durability_status"] == DurabilityStatus.DURABLE, (
            f"durability_status is {rec['durability_status']!r}; should be "
            f"'durable' after a successful sync write."
        )
        watermark_after_first = rec["watermark"]
        assert watermark_after_first is not None and watermark_after_first > 0, (
            f"watermark on the row is {watermark_after_first!r}; must be a "
            f"positive int64 per Option C."
        )
        assert rec["status"] == "complete"
        assert rec["producer_type"] == "agent"
        assert rec["producer_id"] == "iagent-engine-a"
        assert rec["consumer_user_id"] == "test-user-7d"
        assert any(
            uri
            and "datahub" in uri
            for uri in rec["source_uris"]
        ), f"CITES edges did not resolve to expected Source: {rec['source_uris']!r}"

        # ── IDEMPOTENT REPLAY ──
        result2 = writer.write_sync(bundle)
        assert result2.success, f"replay write failed: {result2.error!r}"
        assert result2.watermark > watermark_after_first, (
            f"replay watermark {result2.watermark} did NOT advance over "
            f"first-write watermark {watermark_after_first}. "
            f"Vestigial-watermark trap: every UPDATE must bump watermark, "
            f"per Decision 3 Option C and "
            f"[[verify-subtle-acceptance-by-inspection]]."
        )

        with driver.session() as session:
            count_rec = session.run(
                "MATCH (a:AnswerArtifact {id: $id}) RETURN count(a) AS c",
                id=artifact_id,
            ).single()
        assert count_rec["c"] == 1, (
            f"replay created {count_rec['c']} nodes; expected exactly 1. "
            f"Idempotency violated."
        )

        # Confirm the watermark on the node reflects the replay value.
        with driver.session() as session:
            wm_rec = session.run(
                "MATCH (a:AnswerArtifact {id: $id}) RETURN a.watermark AS wm",
                id=artifact_id,
            ).single()
        assert wm_rec["wm"] == result2.watermark, (
            f"node watermark {wm_rec['wm']} != writer-reported "
            f"{result2.watermark}; watermark write was not committed to "
            f"the node."
        )

    finally:
        _purge(driver, artifact_id)
        driver.close()
