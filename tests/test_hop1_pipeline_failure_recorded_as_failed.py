"""Hop 1 Probe 3 — @pipeline-failure-recorded-as-failed.

Architect-inspection follow-up to the Hop 1 commit `64a4662`. Catches the
optimistic-default trap: the writer used to hardcode `a.status = 'complete'`
on every MERGE, so a pipeline-failure case (gateway's `_perror` branch
fires) would still persist as `status='complete' + durability_status='durable'`.

That is "everything succeeded" written into the substrate-of-record by
default. Per `[[optimistic-defaults-are-dishonest]]` rule #1: the writer
must NOT have a success-flavored default; the bundle's `status` is a
required input. Per the architect's failure-mode-1 ruling: the gateway
sets `status='failed'` when `_perror` fires; the writer respects it; the
substrate carries the honest failure.

Predicted-RED reason (before the narrow fix): the writer would persist
the bundle with `status='complete'` because either (a) the bundle has
no status field, so MERGE uses its hardcoded `complete` default, or
(b) the bundle has a status field set to 'failed' but the writer's
`ON CREATE SET a.status = 'complete'` clause overwrites it. Either
shape means the persisted artifact is `complete` despite a failed
pipeline — the optimistic-default lie.

Predicted-GREEN reason: AnswerArtifactBundle.status is required at
construction; the writer's MERGE uses `a.status = $status` from the
caller's input; the gateway sets 'failed' on `_perror`. The persisted
artifact is `status='failed' + durability_status='durable' +
rendered_output=null`. The substrate records the failure honestly.

All four assertions co-required (B/C/D + decoupling A):
  A — `dispatch_async` does not raise back to the caller (decoupling).
  B — persisted `status = 'failed'`, NOT `'complete'`.
  C — persisted `durability_status = 'durable'` (the Neo4j write
      itself succeeded; the *pipeline* failed, the *write* of the
      failed-pipeline-record succeeded).
  D — persisted `rendered_output` is null (honest about the
      missing payload).

A green that asserts only one is hollow per `[[fixture-must-exercise-paths]]`.

Prereq:
    kubectl -n sandbox port-forward svc/iagent-neo4j 17687:7687 &
    PROBE_NEO4J_PASSWORD=changeme-neo4j-sandbox

Run:
    uv run pytest tests/test_hop1_pipeline_failure_recorded_as_failed.py -v
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from src.iagent.answer_artifact_writer import (
    AnswerArtifactBundle,
    AnswerArtifactWriter,
    DurabilityStatus,
)


_NEO4J_URI = os.getenv("PROBE_NEO4J_URI", "bolt://localhost:17687")
_NEO4J_USERNAME = os.getenv("PROBE_NEO4J_USERNAME", "neo4j")
_NEO4J_PASSWORD = os.getenv("PROBE_NEO4J_PASSWORD", "changeme-neo4j-sandbox")


def _driver_or_skip():
    try:
        driver = GraphDatabase.driver(
            _NEO4J_URI,
            auth=(_NEO4J_USERNAME, _NEO4J_PASSWORD),
            connection_timeout=2.0,
        )
        driver.verify_connectivity()
        return driver
    except (ServiceUnavailable, Exception) as exc:  # pragma: no cover
        pytest.skip(
            f"Neo4j unreachable at {_NEO4J_URI}: {exc}. "
            f"Run `kubectl -n sandbox port-forward "
            f"svc/iagent-neo4j 17687:7687 &`."
        )


def _purge(driver, artifact_id: str) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (a:AnswerArtifact {id: $id}) DETACH DELETE a",
            id=artifact_id,
        )


def _failed_pipeline_bundle(artifact_id: str) -> AnswerArtifactBundle:
    """A bundle in the shape the gateway WOULD produce when the
    `_perror` "Timeout or failed to fetch UI payload" branch fires.

    Failure-mode-1: pipeline failed before final_payload arrived.
    - `status='failed'` — the gateway saw `_perror`, sets it explicitly.
    - `rendered_output=None` — no payload was produced; honest null.
    - Other legs (routing, sources, graph_trace) may or may not have
      fired before the failure; we set them empty here to model the
      worst-case "pipeline died before producing anything."
    """
    return AnswerArtifactBundle(
        id=artifact_id,
        question_text="what is engine A's owner_persona for retrieveKnowledge?",
        message_id="msg-hop1-fail-pipeline-003",
        valid_as_of=int(time.time() * 1000),
        status="failed",  # ← gateway's pipeline-failure signal
        produced_by={
            "actor_type": "agent",
            "actor_id": "pending",  # routing never arrived
        },
        produced_for={
            "user_id": "test-user-7d",
            "is_authenticated": True,
            "user_persona": None,
            "entitled_domains": None,
        },
        resolved_intent={},
        routing=None,
        sources=[],
        graph_trace=[],
        rendered_output=None,  # ← honest null; no payload was produced
        derived_from_artifact_id=None,
    )


@pytest.mark.asyncio
async def test_probe3_pipeline_failure_persists_as_failed_not_complete() -> None:
    """All four legs co-required (A + B + C + D).

    Predicted-RED: writer hardcodes `a.status = 'complete'` so the
    persisted artifact has `status='complete'` despite the bundle
    being a failed-pipeline shape.

    Predicted-GREEN: bundle's status is required; writer respects
    the explicit input; persisted artifact carries the honest failure.
    """
    artifact_id = f"urn:li:answerArtifact:probe3-{uuid.uuid4().hex[:8]}"
    driver = _driver_or_skip()
    try:
        _purge(driver, artifact_id)

        writer = AnswerArtifactWriter(
            driver=driver,
            max_retries=3,
            backoff_seconds=0.1,
        )

        bundle = _failed_pipeline_bundle(artifact_id)

        # The gateway dispatches on a separate task after stream_end.
        # We mimic that here — the writer's dispatch_async contract
        # is "never raise back to caller," which is leg A.
        write_task = asyncio.create_task(writer.dispatch_async(bundle))
        try:
            await asyncio.wait_for(write_task, timeout=10.0)
        except Exception as exc:  # pragma: no cover — fails leg A
            pytest.fail(
                f"Assertion A VIOLATED — dispatch_async raised back to "
                f"caller: {exc}. The decoupling contract was broken."
            )

        # ── ASSERTION A: DELIVERY DECOUPLED ──
        assert writer.last_dispatch_raised is False, (
            "Assertion A VIOLATED — writer.last_dispatch_raised is True. "
            "Delivery would be coupled to Neo4j health."
        )

        # ── READBACK BY TRAVERSAL ──
        with driver.session() as session:
            rec = session.run(
                """
                MATCH (a:AnswerArtifact {id: $id})
                RETURN
                  a.id AS id,
                  a.status AS status,
                  a.durability_status AS durability_status,
                  a.rendered_output AS rendered_output,
                  a.watermark AS watermark
                """,
                id=artifact_id,
            ).single()
        assert rec is not None, (
            "AnswerArtifact node missing after dispatch_async completed. "
            "The write didn't reach Neo4j."
        )

        # ── ASSERTION B: status='failed' (NOT 'complete') ──
        assert rec["status"] == "failed", (
            f"Assertion B VIOLATED — persisted status is "
            f"{rec['status']!r}, expected 'failed'. The "
            f"optimistic-default trap fired: writer overwrote the "
            f"caller's 'failed' input with its hardcoded 'complete'. "
            f"Per [[optimistic-defaults-are-dishonest]] rule #1, the "
            f"writer must require status as explicit input."
        )

        # ── ASSERTION C: durability_status='durable' ──
        # A failed pipeline is still a writable artifact — we WANT to
        # persist the failure. The pipeline failed; the write of the
        # failed-pipeline-record succeeded.
        assert rec["durability_status"] == DurabilityStatus.DURABLE, (
            f"Assertion C VIOLATED — durability_status is "
            f"{rec['durability_status']!r}, expected 'durable'. The "
            f"Neo4j write itself succeeded; the *pipeline* failed but "
            f"the *write* of the failed-pipeline-record must succeed."
        )

        # ── ASSERTION D: rendered_output is null ──
        # The gateway received no payload; the bundle's rendered_output
        # is None; the writer must persist null (not an empty
        # placeholder, not 'pending', not the literal string 'None').
        assert rec["rendered_output"] is None, (
            f"Assertion D VIOLATED — rendered_output is "
            f"{rec['rendered_output']!r}, expected None. The honest "
            f"null about the missing payload was lost."
        )

        # Sanity: watermark was assigned (the write succeeded; Decision 3
        # Option C requires a watermark column on every artifact row).
        assert rec["watermark"] is not None and rec["watermark"] > 0, (
            f"watermark is {rec['watermark']!r}; the write should have "
            f"assigned a positive monotonic value."
        )

    finally:
        _purge(driver, artifact_id)
        driver.close()


def test_probe3_bundle_construction_without_status_is_rejected() -> None:
    """Per `[[optimistic-defaults-are-dishonest]]` rule #1 (Option A): a
    forgotten `status` must be a load-time error, not a silent
    default-to-success. The dataclass declares status as required; any
    construction without it raises TypeError.

    This probe exists so a future caller who tries to skip `status`
    gets a load-time / construction-time failure rather than a silent
    "the default was complete" wrong-write.
    """
    with pytest.raises(TypeError):
        # Intentionally constructing without `status` to assert the
        # required-input shape. The type-checker may flag this; that
        # is the point — the type system AND the runtime both refuse
        # to let status be implicit.
        AnswerArtifactBundle(  # type: ignore[call-arg]
            id="urn:li:answerArtifact:probe3-rejected",
            question_text="will the writer let me forget status?",
            message_id="msg-hop1-construct-test",
            valid_as_of=int(time.time() * 1000),
            produced_by={"actor_type": "agent", "actor_id": "x"},
            produced_for={"user_id": "x", "is_authenticated": True},
            resolved_intent={},
            routing=None,
        )
