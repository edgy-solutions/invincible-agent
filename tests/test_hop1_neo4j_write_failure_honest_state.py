"""Hop 1 Probe 2 — @neo4j-write-failure-honest-state.

The load-bearing probe for Decision-0's sub-decision (decouple-with-honest-
failure-state). Written BEFORE the implementation per
[[pre-written-fixtures-must-fail-first]]. Predicted-RED reason: the module
`src.iagent.answer_artifact_writer` does not exist yet, so the import fails.
After implementation, the GREEN must hold for BOTH assertions A and B
(a one-legged green is hollow per [[fixture-must-exercise-paths]]).

This probe is intentionally a fault-injection unit-shape test, not a
full-sandbox SSE flow test. Probe 2's contract is the DECOUPLING and the
HONEST RECORDED STATE — both are properties of the writer module under a
fault-injected Neo4j driver, independent of whether the SSE generator is
streaming. The decoupling has to hold from the writer's perspective; the
streaming flow is unchanged from Hop 0.

Run:
    uv run pytest tests/test_hop1_neo4j_write_failure_honest_state.py -v

Plan reference: c:/Users/cnogr/git/invincible-agent/docs/plans/projector-build-plan.md
commit 0eda9f7, §3.1 Decision 0 sub-decision, §4 Probe 2, §3.6 gate 3.
"""
from __future__ import annotations

import asyncio
import time

import pytest


# These imports MUST FAIL pre-implementation. The expected-RED reason is
# specifically that `src.iagent.answer_artifact_writer` does not exist yet.
# If the import succeeds without the module existing, that's the
# premise-shift to investigate first (something snuck in).
from src.iagent.answer_artifact_writer import (  # noqa: E402
    AnswerArtifactBundle,
    AnswerArtifactWriter,
    DurabilityStatus,
)


class _ExplodingNeo4jDriver:
    """A stand-in Neo4j driver that ALWAYS raises on session()."""

    class _ServiceUnavailable(Exception):
        pass

    def session(self):  # noqa: D401 — sync API, drives the writer's sync path
        raise self._ServiceUnavailable("simulated: Neo4j is unreachable")

    def close(self):
        pass


def _make_bundle(artifact_id: str, message_id: str) -> AnswerArtifactBundle:
    """Construct the canonical Probe-2 bundle."""
    return AnswerArtifactBundle(
        id=artifact_id,
        question_text=(
            "what is engine A's owner_persona for retrieveKnowledge?"
        ),
        message_id=message_id,
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
                "uri": "urn:li:dataset:(urn:li:dataPlatform:datahub,engine_a,PROD)",
                "type": "dataset",
                "label": "engine_a dataset",
                "snippet": "owner_persona: DATA_STEWARD",
            }
        ],
        graph_trace=[],
        rendered_output={
            "components": [{"archetype": "ANSWER_TEXT", "text": "DATA_STEWARD"}],
            "archetype": "ANSWER_TEXT",
        },
        derived_from_artifact_id=None,
    )


@pytest.mark.asyncio
async def test_probe2_delivery_decoupled_and_honest_recorded_state() -> None:
    """Both legs co-required: A) delivery decoupled, B) honest recorded state.

    Predicted-RED reason (before implementation): ImportError on
    `src.iagent.answer_artifact_writer`. After implementation:
    GREEN with BOTH assertions held.
    """
    artifact_id = "urn:li:answerArtifact:probe2-test-001"
    message_id = "msg-hop1-fail-002"
    bundle = _make_bundle(artifact_id, message_id)

    exploding_driver = _ExplodingNeo4jDriver()

    # Tight retry budget so the test finishes in seconds (production tunes
    # this from env vars; the writer accepts overrides for testability).
    writer = AnswerArtifactWriter(
        driver=exploding_driver,
        max_retries=2,
        backoff_seconds=0.05,
    )

    # ── SIMULATED DELIVERY (decoupling under test) ──
    # In production cortex-bff yields stream_end FIRST and then dispatches
    # the writer on a separate retryable track. Here we record a
    # delivery-completion timestamp before the dispatch, then verify that
    # the dispatch did not raise back into our hands and did not block
    # delivery. Both: dispatch is awaited but on its own task so we can
    # measure that the writer's failure does NOT propagate.
    delivery_completed_at = time.monotonic()

    # The writer's contract: never raise out of dispatch_async, regardless
    # of Neo4j health. The failure must show up as honest recorded state,
    # not as an exception to the caller. This is the decoupling.
    write_task = asyncio.create_task(writer.dispatch_async(bundle))

    # Delivery's already done; we wait for the writer task to finish
    # exhausting its retries.
    try:
        await asyncio.wait_for(write_task, timeout=10.0)
    except Exception as exc:  # pragma: no cover — would fail Assertion A
        pytest.fail(
            f"Assertion A VIOLATED — dispatch_async raised back to caller "
            f"(this is the coupling mistake the decouple-shape forbids): {exc}"
        )

    # ── ASSERTION A: DELIVERY DECOUPLED ──
    # In a real SSE flow, delivery happened before dispatch even started.
    # Here we verify the writer's failure didn't propagate; the caller
    # (which would be the SSE generator) is free to have yielded
    # stream_end already. The decoupling holds.
    assert writer.last_dispatch_raised is False, (
        "Assertion A VIOLATED — writer.last_dispatch_raised is True, meaning "
        "the failure propagated to the caller. Delivery would be coupled to "
        "Neo4j health, which is the dual-write failure mode Decision 0's "
        "sub-decision forbids."
    )

    # ── ASSERTION B: HONEST RECORDED STATE ──
    # After retries exhausted, the artifact's durability_status must be
    # `persistence_failed`. This is NOT silent absence; the registry
    # records the failure explicitly. The registry is the per-process
    # local fallback queue (shape 1 in the planning prompt) — a graceful
    # interim that the Restate successor formalizes via the journal.
    record = writer.get_durability_record(artifact_id)
    assert record is not None, (
        "Assertion B VIOLATED — no durability record for the artifact. The "
        "failure was silently dropped (dual-write failure mode one layer "
        "below where Decision 1 just rejected it). The honest-recorded-"
        "state shape REQUIRES an explicit recorded value."
    )
    assert record["durability_status"] == DurabilityStatus.PERSISTENCE_FAILED, (
        f"Assertion B VIOLATED — durability_status is "
        f"{record['durability_status']!r}, not 'persistence_failed'. "
        f"The retry budget exhausted but the writer did not transition "
        f"to the terminal failure state."
    )

    # Sanity: the registry should also record the attempts (provenance of
    # the failure — how many tries, last error). Caller may inspect.
    assert record["attempts"] >= 1, (
        "Assertion B sanity check — no recorded attempts; the writer "
        "never even tried."
    )

    # delivery_completed_at is just here to make the decoupling visible
    # in the test reading; it asserts nothing on its own. The real test
    # of decoupling is that `dispatch_async` did not raise back to us.
    _ = delivery_completed_at


@pytest.mark.asyncio
async def test_probe2_pending_state_visible_during_retry_window() -> None:
    """Sibling probe: while the retry window is still open, the durability
    record shows `persistence_pending`, not silent absence.

    This catches a regression where the implementation skips recording
    the in-flight state entirely (jumping straight from "absent" to
    "persistence_failed" only at exhausted retries).
    """
    artifact_id = "urn:li:answerArtifact:probe2-test-002"
    message_id = "msg-hop1-fail-003"
    bundle = _make_bundle(artifact_id, message_id)

    exploding_driver = _ExplodingNeo4jDriver()

    # Long backoff so we can observe the pending state mid-retry.
    writer = AnswerArtifactWriter(
        driver=exploding_driver,
        max_retries=5,
        backoff_seconds=0.5,
    )

    write_task = asyncio.create_task(writer.dispatch_async(bundle))

    # Sleep just past the first attempt so the writer is mid-retry-loop.
    await asyncio.sleep(0.1)

    record = writer.get_durability_record(artifact_id)
    assert record is not None, (
        "Pending state was not recorded at delivery time. The "
        "decouple-with-honest-failure-state shape REQUIRES "
        "persistence_pending to be set IMMEDIATELY at delivery, not "
        "derived from absence."
    )
    assert record["durability_status"] == DurabilityStatus.PERSISTENCE_PENDING, (
        f"In-flight durability_status was "
        f"{record['durability_status']!r}, not 'persistence_pending'."
    )

    # Drain the task before exiting.
    try:
        await asyncio.wait_for(write_task, timeout=10.0)
    except Exception:
        pass
