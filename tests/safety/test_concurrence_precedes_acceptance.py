"""ADR-0051 §5.1 — a Serious or High acceptance cannot exist without a prior `concurred` record.

MIL-STD-882E §4.3.7, verbatim: "The user representative shall be part of this process throughout
the life-cycle of the system and shall provide formal concurrence **before** all Serious and High
risk acceptance decisions." §3.2.49: the user representative is "at a peer level equivalent to the
risk acceptance authority."

**"BEFORE" IS MADE STRUCTURAL, NOT ADVISORY.** A draft of a Serious or High hazard emits only the
CONCURRENCE task; no acceptance request exists for it. The sole route to one is
`acceptance_request_after_concurrence`, which refuses without a disposed `concurred`. A caller
cannot skip the check by not calling it, because there is nothing to skip to.

**THE MUTATION THE RULING NAMES:** opening both tasks at once must go red. That is the design a
reasonable implementer would reach for — gate the acceptance's DISPOSAL on the concurrence — and
it fails invisibly, because both queues look entirely normal while an acceptance sits in an
authority's list with concurrence outstanding.

**THE CONTROL:** Medium reaching `accepted` in one act. Without it this file would pass on an
implementation that simply refused every acceptance, which is not the requirement.
"""
from __future__ import annotations

import pytest

from agent_fleet.safety_agent import entities, matrix, measures

_HIGH_OR_SERIOUS = ("High", "Serious")


@pytest.fixture(autouse=True)
def _clean_cache():
    matrix.reset_cache()
    yield
    matrix.reset_cache()


def _level_of(hazard_id: str):
    d = measures.draft_risk_assessment(hazard_id=hazard_id)
    return None if d.get("refused") else d.get("risk_level")


def _one_hazard_at(levels) -> str:
    for h in entities.HAZARDS:
        if _level_of(h.hazard_id) in levels:
            return h.hazard_id
    pytest.skip(f"no fixture hazard resolves to {levels} — this seal would be vacuous")


# ---------------------------------------------------------------------------
# The requirement
# ---------------------------------------------------------------------------

def test_a_serious_or_high_draft_opens_the_CONCURRENCE_not_the_acceptance():
    """The first task is the concurrence, and the acceptance does not exist yet."""
    hazard_id = _one_hazard_at(_HIGH_OR_SERIOUS)
    draft = measures.draft_risk_assessment(hazard_id=hazard_id)
    assert draft["requires_concurrence"] is True
    rr = draft["review_request"]
    assert rr["kind"].startswith("risk_acceptance_concurrence_"), (
        f"{hazard_id} is {draft['risk_level']} and its first task is {rr['kind']!r} — the "
        "standard requires concurrence BEFORE the acceptance decision"
    )
    assert "concurrence" in rr["audience"]
    assert rr["payload"]["reason_required"] == ["concurred", "not_concurred"]
    # The concurring party is told what their concurrence unblocks. A concurrence whose
    # consequence is invisible is the rubber stamp peer-level exists to prevent.
    assert rr["payload"]["unblocks_acceptance_audience"] == draft["acceptance_audience"]


def test_no_acceptance_request_is_obtainable_without_a_concurred_record():
    """THE CORE ASSERTION. Every non-concurred state refuses, and they refuse DISTINCTLY."""
    hazard_id = _one_hazard_at(_HIGH_OR_SERIOUS)

    undisposed = measures.acceptance_request_after_concurrence(
        hazard_id=hazard_id, concurrence={})
    assert undisposed["refused"] is True
    assert "not yet disposed" in undisposed["reason"]

    declined = measures.acceptance_request_after_concurrence(
        hazard_id=hazard_id,
        concurrence={"decision": "not_concurred", "acted_by": "carol@example.com",
                     "comment": "residual risk not accepted by the user representative"},
    )
    assert declined["refused"] is True
    assert declined["concurrence_decision"] == "not_concurred", (
        "a DECLINED concurrence and an OUTSTANDING one must report differently — one is a "
        "decision the authority must be told about, the other is a step still open"
    )


def test_an_unexplained_concurrence_does_not_unlock_the_acceptance():
    """`concurred` is reason-required on the declaration, and the declaration does not bind at
    runtime yet (R-004(f)) — so it is enforced here too. An acceptance built on an unexplained
    concurrence is exactly the rubber stamp the peer-level requirement exists to stop."""
    hazard_id = _one_hazard_at(_HIGH_OR_SERIOUS)
    out = measures.acceptance_request_after_concurrence(
        hazard_id=hazard_id,
        concurrence={"decision": "concurred", "acted_by": "carol@example.com", "comment": "  "},
    )
    assert out["refused"] is True
    assert "no stated basis" in out["reason"]


def test_a_concurred_record_yields_an_acceptance_carrying_BOTH_names():
    """THE LINEAGE IS THE POINT, NOT THE GATE.

    A gate that blocked the acceptance but left no record would satisfy the ordering and lose the
    thing the ordering exists to produce: "who signed, on what evidence" with two names on it.
    """
    hazard_id = _one_hazard_at(_HIGH_OR_SERIOUS)
    concurrence = {
        "task_id": f"risk-concurrence-{hazard_id}",
        "decision": "concurred",
        "acted_by": "carol@example.com",
        "comment": "Mitigation plan reviewed with the operating squadron; concur.",
    }
    out = measures.acceptance_request_after_concurrence(
        hazard_id=hazard_id, concurrence=concurrence)
    assert out["refused"] is False
    assert out["kind"].startswith("risk_acceptance_")
    assert not out["kind"].startswith("risk_acceptance_concurrence")
    p = out["payload"]
    assert p["concurred_by"] == "carol@example.com"
    assert p["concurrence_basis"] == concurrence["comment"]
    assert concurrence["task_id"] in p["derived_from"], (
        "the acceptance does not cite the concurrence it depends on — the lineage is what makes "
        "the two acts one auditable record rather than two unrelated dispositions"
    )


# ---------------------------------------------------------------------------
# The control, and the mutation
# ---------------------------------------------------------------------------

def test_medium_reaches_acceptance_in_ONE_act():
    """THE CONTROL. Without it this file passes on an implementation that refuses everything.

    The standard requires concurrence for Serious and High and says nothing about Medium or Low.
    Inventing a step where none is required would be as wrong as omitting one where it is.
    """
    hazard_id = _one_hazard_at(("Medium", "Low"))
    draft = measures.draft_risk_assessment(hazard_id=hazard_id)
    assert draft["requires_concurrence"] is False
    rr = draft["review_request"]
    assert rr["kind"].startswith("risk_acceptance_")
    assert "concurrence" not in rr["kind"], (
        f"{hazard_id} is {draft['risk_level']} and was given a concurrence step the standard does "
        "not require"
    )
    assert rr["audience"] == draft["acceptance_audience"]


def test_mutation_opening_both_tasks_at_once_is_caught(monkeypatch):
    """THE MUTATION THE RULING NAMES, run rather than described.

    The plausible wrong design is "open both, gate the disposal". Here it is simulated by making
    the drafter treat NO level as needing concurrence — the acceptance task then materialises for
    a High hazard with no concurrence anywhere, and the first assertion must catch it.
    """
    monkeypatch.setattr(measures, "_CONCURRENCE_LEVELS", frozenset())
    hazard_id = _one_hazard_at(_HIGH_OR_SERIOUS)
    draft = measures.draft_risk_assessment(hazard_id=hazard_id)
    assert draft["requires_concurrence"] is False  # the mutation took effect
    assert draft["review_request"]["kind"].startswith("risk_acceptance_")
    assert "concurrence" not in draft["review_request"]["kind"]
    # ^ This is the state the seal above forbids. Asserting it HERE proves the mutation genuinely
    # produces the forbidden shape, so the forward assertion is discriminating rather than
    # passing because the shape is unreachable.


def test_the_concurrence_levels_are_exactly_the_standards_two():
    """A tailored matrix could add a level; the concurrence set must not acquire it silently.

    Held as level NAMES rather than a rank threshold precisely so a new level inserted above
    Medium does not inherit a requirement the standard never placed on it.
    """
    assert measures._CONCURRENCE_LEVELS == frozenset({"High", "Serious"}), (
        "the concurrence levels no longer match MIL-STD-882E 4.3.7's 'all Serious and High'"
    )
