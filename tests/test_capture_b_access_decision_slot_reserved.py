"""Capture B probe — reserved access_decision slot on Source / CITES.

ADR-0025 §"Capture B — Reserved `access_decision` slot on Source /
CITES". The slot is part of the type today, null in all production
writes, no consumer reads it. Reserving the slot now means the
enforcement session that follows does NOT need a second migration
through writer + Neo4j + projector + Postgres + Electric + cortex-ui
to land the captured decision.

Five-layer survival (six inspection points), each verified by this
probe per `[[verify-subtle-acceptance-by-inspection]]`:

  Layer 1 — writer JSON serialization (answer_artifact_writer.py)
  Layer 2 — Neo4j round-trip (edge property)
  Layer 3 — projector re-parse (projector/apply_loop.py)
  Layer 4 — Postgres JSONB
  Layer 5 — Electric hydration (cortex-ui/src/lib/electric.ts)
  Layer 6 — cortex-ui Source type acceptance (type-level)

This probe exercises Layers 1-3 against real Neo4j (Layers 4-6 are
covered by static type-acceptance + integration when the projector
runs against Postgres). The point is: the field round-trips as
expected (populated and null shapes both).

RED-first per `[[pre-written-fixtures-must-fail-first]]`:

  Predicted RED reasons:
    Layer 1: writer's CITES MERGE does not set c.access_decision_json
             → Cypher write succeeds, the edge property is missing
             → readback returns None for access_decision
    Layer 3: projector's Cypher RETURN map omits the field
             → projector writes a sources JSONB without access_decision

  Predicted GREEN (after implementation):
    Populated access_decision round-trips through all layers.
    Null access_decision also round-trips as null (the reserved
    slot's default state).

Run:
    uv run pytest tests/test_capture_b_access_decision_slot_reserved.py -v

Prereq for the Neo4j round-trip leg:
    kubectl -n sandbox port-forward svc/iagent-neo4j 17687:7687 &
    NEO4J_PASSWORD=changeme-neo4j-sandbox

Plan reference:
    docs/adr/ADR-0025-instance-plane-access-control-as-provenance.md
    docs/plans/projector-build-plan.md §3.6 footnote
"""
from __future__ import annotations

import json
import os
import time
import uuid

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from src.iagent.answer_artifact_writer import (  # noqa: E402
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
            f"Run `kubectl -n sandbox port-forward svc/iagent-neo4j "
            f"17687:7687 &` and set PROBE_NEO4J_PASSWORD."
        )


def _purge(driver, artifact_id: str) -> None:
    with driver.session() as session:
        session.run(
            "MATCH (a:AnswerArtifact {id: $id}) DETACH DELETE a",
            id=artifact_id,
        )


# A populated access_decision matching the ADR's documented shape.
_POPULATED_DECISION = {
    "outcome": "filter",
    "policy_version": "v0.0.0-capture-b-probe",
    "attributes_considered": {
        "subject": ["clearance", "projects_worked"],
        "resource": ["classification", "owning_contract"],
        "environment": ["time_of_day"],
    },
    "filters_applied": {
        "columns_redacted": ["pii_email"],
        "rows_filtered_by": "region = 'US-EAST'",
    },
    "decided_at": 1719440000000,
}


def _make_bundle_with_source(
    artifact_id: str, *, access_decision
) -> AnswerArtifactBundle:
    """Bundle with one Source carrying the documented access_decision
    shape. `access_decision=None` exercises the reserved-slot's
    null default; a populated dict exercises the round-trip.
    """
    src = {
        "uri": (
            f"urn:li:dataset:(urn:li:dataPlatform:datahub,"
            f"capture_b_probe_{uuid.uuid4().hex[:8]},PROD)"
        ),
        "type": "dataset",
        "label": "capture_b probe dataset",
        "snippet": "access-decision provenance probe",
    }
    if access_decision is not None:
        src["access_decision"] = access_decision
    return AnswerArtifactBundle(
        id=artifact_id,
        question_text="capture B reserved access_decision slot probe",
        message_id="msg-capture-b-001",
        valid_as_of=int(time.time() * 1000),
        status="complete",
        produced_by={
            "actor_type": "agent",
            "actor_id": "capture-b-probe",
        },
        produced_for={
            "user_id": "test-capture-b",
            "is_authenticated": True,
            "user_persona": None,
            "entitled_domains": None,
            # Capture A: explicit so the writer doesn't fall back.
            "entitlement_source": "fallback",
        },
        resolved_intent={},
        routing=None,
        sources=[src],
        graph_trace=[],
        rendered_output=None,
        derived_from_artifact_id=None,
    )


def test_layer_1_2_3_populated_access_decision_roundtrips_to_neo4j() -> None:
    """Predicted-RED reason: the writer's CITES MERGE does not set
    `c.access_decision_json`, so the property is missing on the edge;
    the readback returns None.

    Predicted-GREEN: the populated access_decision round-trips through
    the writer's JSON serialization into a Neo4j edge property, and
    the readback parses it back to a dict matching `_POPULATED_DECISION`.

    This covers Layers 1 (writer) + 2 (Neo4j round-trip). Layer 3
    (projector re-parse) is covered by the next test and the
    existing Hop 2 integration tests.
    """
    artifact_id = f"urn:li:answerArtifact:capture-b-{uuid.uuid4().hex[:8]}"
    driver = _driver_or_skip()
    try:
        _purge(driver, artifact_id)
        writer = AnswerArtifactWriter(
            driver=driver, max_retries=2, backoff_seconds=0.1
        )
        bundle = _make_bundle_with_source(
            artifact_id, access_decision=_POPULATED_DECISION
        )
        result = writer.write_sync(bundle)
        assert result.success, (
            f"Capture B write failed: {result.error!r}"
        )

        # Read the CITES edge property back by traversal.
        with driver.session() as session:
            rec = session.run(
                """
                MATCH (a:AnswerArtifact {id: $id})-[c:CITES]->(s:Source)
                RETURN c.access_decision_json AS ad_json,
                       s.uri AS source_uri
                """,
                id=artifact_id,
            ).single()
        assert rec is not None, (
            "AnswerArtifact + CITES edge missing after write — "
            "writer did not even create the relationship."
        )
        ad_json = rec["ad_json"]
        assert ad_json is not None, (
            "CITES.access_decision_json is None after writing a "
            "populated decision. Layer 1 (writer) did not pick up the "
            "Source's access_decision field. ADR-0025 §Capture B "
            "requires the writer's CITES MERGE to set this property."
        )
        parsed = json.loads(ad_json)
        assert parsed == _POPULATED_DECISION, (
            f"access_decision round-tripped CORRUPTED: {parsed!r} != "
            f"{_POPULATED_DECISION!r}"
        )
    finally:
        _purge(driver, artifact_id)
        driver.close()


def test_layer_1_2_null_access_decision_roundtrips_as_null() -> None:
    """The reserved slot's default state — null. Production writes
    set `access_decision: null` always (per ADR-0025 §Non-goals:
    enforcement is its own session). The probe asserts that an
    unpopulated decision round-trips as null at the edge property
    layer — not absent, not undefined, not an empty dict, NULL.

    Predicted-RED reason: same as the populated leg — if Layer 1
    isn't wired, the property is missing. Once wired, both legs
    pass.

    Predicted-GREEN: the edge has the property and it's null.
    """
    artifact_id = (
        f"urn:li:answerArtifact:capture-b-null-{uuid.uuid4().hex[:8]}"
    )
    driver = _driver_or_skip()
    try:
        _purge(driver, artifact_id)
        writer = AnswerArtifactWriter(
            driver=driver, max_retries=2, backoff_seconds=0.1
        )
        bundle = _make_bundle_with_source(
            artifact_id, access_decision=None
        )
        result = writer.write_sync(bundle)
        assert result.success

        with driver.session() as session:
            rec = session.run(
                """
                MATCH (a:AnswerArtifact {id: $id})-[c:CITES]->(s:Source)
                RETURN c.access_decision_json AS ad_json
                """,
                id=artifact_id,
            ).single()
        assert rec is not None
        # Null at the edge property layer is the documented reserved
        # state. The field on the type is `access_decision?: ... | null`;
        # the writer translates a missing/None source field to a null
        # edge property.
        assert rec["ad_json"] is None, (
            f"Expected null access_decision_json for reserved slot's "
            f"default state; got {rec['ad_json']!r}. Layer 1 may be "
            f"writing an empty-dict or empty-string by mistake."
        )
    finally:
        _purge(driver, artifact_id)
        driver.close()


def test_layer_3_projector_cypher_map_returns_access_decision() -> None:
    """Layer 3 (projector re-parse): the projector's Cypher RETURN
    map must include `c.access_decision_json` so the field rides
    through into the `sources` JSONB written to Postgres.

    This probe inspects the projector module's apply_loop source
    code by import + textual inspection — it does NOT need Postgres.
    The textual check is the cheapest way to assert "the projector
    knows about this field"; the integration that follows
    (Hop 2 tests + Electric hydration) propagates from there.

    Predicted-RED reason: the projector's poll_neo4j Cypher does
    not name `c.access_decision_json` in the CITES projection.
    Predicted-GREEN: it does.
    """
    from src.iagent import projector  # noqa: F401
    from src.iagent.projector import apply_loop

    src = open(apply_loop.__file__, "r", encoding="utf-8").read()

    # Search for the CITES projection that the projector uses to
    # materialize sources. ADR-0025 §Capture B requires this map to
    # name the access_decision_json field so it survives into the
    # `sources` JSONB.
    assert "access_decision_json" in src, (
        "projector/apply_loop.py source does not reference "
        "`access_decision_json`. Layer 3 (projector re-parse) is "
        "not wired for the reserved slot. ADR-0025 §Capture B "
        "requires the projector's Cypher RETURN map to include the "
        "edge property so the field rides through to Postgres JSONB."
    )


def test_layer_6_cortex_ui_source_type_declares_access_decision() -> None:
    """Layer 6 (cortex-ui Source type acceptance): the type
    declaration in cortex-ui/src/api/types.ts must declare
    `access_decision` on the `Source` interface.

    This is a textual check on the type-source file — the cheapest
    durable test for the type-level acceptance. TypeScript
    compilation is the real proof; this check fires the moment
    someone deletes the slot.

    Predicted-RED reason: cortex-ui/src/api/types.ts does not
    declare `access_decision` on `Source`. Predicted-GREEN: it does.
    """
    # The cortex-ui repo lives in a sibling directory; resolve via
    # the standard layout used elsewhere in the codebase.
    candidates = [
        os.path.join(
            os.path.dirname(__file__),
            "..", "..", "cortex-ui", "src", "api", "types.ts",
        ),
        os.path.join(
            "c:\\", "Users", "cnogr", "git", "cortex-ui", "src", "api",
            "types.ts",
        ),
    ]
    found = None
    for c in candidates:
        if os.path.isfile(c):
            found = c
            break
    if found is None:
        pytest.skip(
            f"cortex-ui/src/api/types.ts not found at any of "
            f"{candidates!r}; Layer 6 inspection inapplicable."
        )
    src = open(found, "r", encoding="utf-8").read()
    assert "access_decision" in src, (
        "cortex-ui/src/api/types.ts does not declare "
        "`access_decision` on `Source`. Layer 6 (cortex-ui Source "
        "type) is not wired for the reserved slot. ADR-0025 §Capture "
        "B requires this slot on the Source interface."
    )
