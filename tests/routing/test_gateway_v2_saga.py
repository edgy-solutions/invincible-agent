"""Pure-logic tests for the gateway v0.2 registration saga.

These tests exercise the saga's behavior with MOCKED Neo4j + Weaviate
substrate writers, so they run in 0.5s with no cluster. They cover
the §Test gate items the ADR-0006 amendment specifies as load-bearing:

  - **Happy path** (`registered` outcome, both stores written, probe
    succeeded, 200 returned).
  - **Compensation runs to completion** on each partial-failure
    branch (cases #2 and #3 of the matrix). The saga MUST compensate
    the side that wrote and return 503.
  - **Retry budget enforced** — the saga gives up after the deadline,
    not after a fixed attempt count, because the cluster's actual
    failure profile is "a sequence of fast retries during a blip,
    then either resolve or give up."
  - **Compensation failure logs loudly but doesn't fail-the-fail** —
    the saga returns 503 even if the compensation DELETE itself
    raised. This is benign under the conjunctive-read invariant (an
    orphan half-write is unrouted), but the saga's contract is that
    503 means "you can safely retry," and compensation-failed orphans
    don't break that contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_fleet.mesh_registrar import v2_saga


# ---------------------------------------------------------------------------
# Substrate writer mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_substrate(monkeypatch):
    """Patch every v2_substrate function with a Mock the test can drive."""
    calls = {
        "merge_neo4j": MagicMock(return_value=None),
        "upsert_weaviate": MagicMock(return_value=None),
        "probe": MagicMock(return_value={"neo4j": {"endpoint_url": "x"}, "weaviate_uuid": "u"}),
        "compensate_neo4j": MagicMock(return_value=1),
        "compensate_weaviate": MagicMock(return_value=True),
    }
    monkeypatch.setattr(
        v2_saga.substrate, "merge_neo4j_predicate_edge",
        lambda **kw: calls["merge_neo4j"](**kw),
    )
    monkeypatch.setattr(
        v2_saga.substrate, "upsert_weaviate_predicate_row",
        lambda **kw: calls["upsert_weaviate"](**kw),
    )
    monkeypatch.setattr(
        v2_saga.substrate, "probe_both_stores",
        lambda **kw: calls["probe"](**kw),
    )
    monkeypatch.setattr(
        v2_saga.substrate, "compensate_neo4j_predicate_edge",
        lambda **kw: calls["compensate_neo4j"](**kw),
    )
    monkeypatch.setattr(
        v2_saga.substrate, "compensate_weaviate_predicate_row",
        lambda **kw: calls["compensate_weaviate"](**kw),
    )
    return calls


def _kwargs():
    """Common kwargs for the saga."""
    return dict(
        driver=MagicMock(),
        weaviate_client=MagicMock(),
        verb_iri="mesh:testVerb",
        input_uri="mesh:TestInput",
        output_uri="mesh:TestOutput",
        tool_urn="urn:li:mlModel:(...,test_verb,PROD)",
        rel_props={},
        description="desc",
        endpoint_url="http://test:1234",
        owner_persona="TEST",
        domains=["TEST_DOMAIN"],
        cost_class="fast",
        requires_human_approval=False,
        synonyms=[],
        anti_synonyms=[],
        budget_s=2.0,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_registered_200(mock_substrate):
    """All three steps succeed → 200, both written, probe passed,
    no compensation calls."""
    outcome = v2_saga.run_registration_saga(**_kwargs())
    assert outcome.status == "registered"
    assert outcome.http_code == 200
    assert outcome.neo4j_written is True
    assert outcome.weaviate_written is True
    assert outcome.probe is not None
    assert outcome.forward_retry_attempts == 3  # one attempt per step
    # No compensation should have fired.
    assert mock_substrate["compensate_neo4j"].call_count == 0
    assert mock_substrate["compensate_weaviate"].call_count == 0


# ---------------------------------------------------------------------------
# Case #2 — N=S, W=F. Compensate Neo4j; return 503.
# ---------------------------------------------------------------------------


def test_weaviate_failure_compensates_neo4j_and_returns_503(mock_substrate):
    """The saga's case-#2 path: Neo4j MERGE succeeds, Weaviate upsert
    fails on every retry → compensate the Neo4j edge → 503."""
    mock_substrate["upsert_weaviate"].side_effect = RuntimeError("Weaviate down")
    outcome = v2_saga.run_registration_saga(**_kwargs())
    assert outcome.status == "compensated"
    assert outcome.http_code == 503
    assert mock_substrate["compensate_neo4j"].call_count == 1
    # Weaviate compensation should NOT fire — nothing wrote.
    assert mock_substrate["compensate_weaviate"].call_count == 0
    assert "Weaviate upsert failed" in outcome.reason
    # neo4j_written flips to False once compensated — the caller's
    # mental model is "nothing remains."
    assert outcome.neo4j_written is False


# ---------------------------------------------------------------------------
# Case #3 — N=F, W not attempted. No compensation needed.
# ---------------------------------------------------------------------------


def test_neo4j_failure_returns_503_with_no_compensation_needed(mock_substrate):
    """Neo4j MERGE fails → nothing wrote → no compensation. The fact
    that the saga is sequential (N before W) means a Neo4j-only
    failure path doesn't require Weaviate cleanup."""
    mock_substrate["merge_neo4j"].side_effect = RuntimeError("Neo4j down")
    outcome = v2_saga.run_registration_saga(**_kwargs())
    assert outcome.status == "compensated"
    assert outcome.http_code == 503
    assert outcome.neo4j_written is False
    assert outcome.weaviate_written is False
    # No compensation calls at all — there's nothing to undo.
    assert mock_substrate["compensate_neo4j"].call_count == 0
    assert mock_substrate["compensate_weaviate"].call_count == 0
    assert "Neo4j merge failed" in outcome.reason


# ---------------------------------------------------------------------------
# Probe failure — both wrote, probe disagrees. Compensate both.
# ---------------------------------------------------------------------------


def test_probe_failure_compensates_both_stores_and_returns_503(mock_substrate):
    """The probe is the saga's own postcondition test. If it fails,
    BOTH writes claimed success but the substrate disagrees — we
    don't know which one is real, so the conservative play is to
    DELETE both and return 503 against a clean slate."""
    mock_substrate["probe"].side_effect = RuntimeError("Probe disagrees")
    outcome = v2_saga.run_registration_saga(**_kwargs())
    assert outcome.status == "compensated"
    assert outcome.http_code == 503
    assert mock_substrate["compensate_neo4j"].call_count == 1
    assert mock_substrate["compensate_weaviate"].call_count == 1
    assert "Read-back probe failed" in outcome.reason


# ---------------------------------------------------------------------------
# Compensation-failure tolerance
# ---------------------------------------------------------------------------


def test_neo4j_compensation_failure_does_not_fail_the_fail(mock_substrate):
    """The saga's contract on a 503 is "you can safely retry." That
    holds even if the compensation DELETE itself raised — under the
    conjunctive-read invariant, an orphan Neo4j edge without its
    Weaviate row is not in the LLM's constrained enum.

    The compensation MUST log loudly (logger.error) but MUST NOT
    re-raise — the caller still gets a 503 with the original
    failure reason, not a "compensation also failed" hellscape.
    """
    mock_substrate["upsert_weaviate"].side_effect = RuntimeError("Weaviate down")
    mock_substrate["compensate_neo4j"].side_effect = RuntimeError("Neo4j also down")
    outcome = v2_saga.run_registration_saga(**_kwargs())
    # Still 503. Still "compensated" status. The compensation
    # exception was swallowed and logged.
    assert outcome.status == "compensated"
    assert outcome.http_code == 503
    assert "Weaviate upsert failed" in outcome.reason


def test_weaviate_compensation_failure_under_probe_failure(mock_substrate):
    """Probe failure compensates BOTH; if either compensation raises,
    the saga still returns 503 with the original probe failure reason."""
    mock_substrate["probe"].side_effect = RuntimeError("Probe disagrees")
    mock_substrate["compensate_weaviate"].side_effect = RuntimeError("Weaviate compensation died")
    outcome = v2_saga.run_registration_saga(**_kwargs())
    assert outcome.status == "compensated"
    assert outcome.http_code == 503
    assert "Read-back probe failed" in outcome.reason


# ---------------------------------------------------------------------------
# Bounded forward-retry
# ---------------------------------------------------------------------------


def test_step_retries_until_budget_exhausted(mock_substrate):
    """A step that fails persistently retries until the saga's budget
    elapses, then fails the saga. The architect's design: bounded
    forward-retry to absorb transient blips. The retry count grows
    with the budget; the test bounds budget to 0.5s so we can run it
    fast and confirm the retry harness honors the deadline."""
    mock_substrate["upsert_weaviate"].side_effect = RuntimeError("Persistent failure")
    kwargs = _kwargs()
    kwargs["budget_s"] = 0.5
    outcome = v2_saga.run_registration_saga(**kwargs)
    assert outcome.status == "compensated"
    assert outcome.http_code == 503
    # The retry harness must have attempted the failing step more than
    # once before giving up.
    assert mock_substrate["upsert_weaviate"].call_count >= 2
    # And it must have respected the budget.
    assert outcome.elapsed_s <= 1.0
