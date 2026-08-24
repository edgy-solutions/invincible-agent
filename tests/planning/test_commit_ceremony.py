"""`plan_commit_scenario` — the commit ceremony. Beat 6.

THE DEGENERATE SINGLE-APPROVER CASE of the review flow, per the 2026-08-22 ruling. A
DecisionArtifact is structurally *a disposition record with a planning payload*: the ops are
the disposed items, the rationale is the override-reason, the alternatives are the
considered-set. `requested_by` and `acted_by` are the same person here — that is what makes it
degenerate — and Phase 7's multi-party version adds AUDIENCES to a flow that already names one,
rather than translating a lookalike into the real thing.

WHERE EACH PIECE LIVES, and it is not arbitrary. `PlanStore.commit` already existed and its
docstring named the caller it was waiting for: *"The DECISION ARTIFACT is the caller's
responsibility and the commit ceremony blocks without a rationale — that gate lives at the
route, not here, because this class must stay a store."* So:

  * the RATIONALE CHECK is pure and runs FIRST (`check_rationale`);
  * the ARTIFACT BUILDER is pure (`plan_commit_scenario`), so its shape is testable with no
    store and no route;
  * the MUTATION is the route's, sequenced between them.

THE ARM THAT MATTERS MOST IS ATOMICITY. A ceremony that refuses AFTER applying ops would leave
baseline changed by a decision the system declined to record — worse than having no gate,
because the plan would move with no artifact saying who moved it or why. The refusal is
therefore tested against BASELINE VERSION, not just against the exception.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.planning_agent import measures  # noqa: E402
from agent_fleet.planning_agent.seed import build_seed  # noqa: E402
from agent_fleet.planning_agent.state import PlanStore, SetCost  # noqa: E402

# The disposition vocabulary the DECISION_RECORD contract composes by reference.
# Mirrored here rather than imported because it crosses to cortex-ui at RUNTIME, not compile
# time — the same cross-repo limit test_planning_classes_are_declared states about archetypes.
DISPOSED_KEYS = [
    "task_id", "kind", "task_state", "audience", "requested_by", "subject_ref",
    "acted_by", "acted_at", "decision", "comment",
]


@pytest.fixture
def store():
    return PlanStore(build_seed())


@pytest.fixture
def scenario(store):
    sc = store.fork("S-commit", "commit ceremony fixture")
    store.append_op("S-commit", SetCost(project_id="P1", kind="capex",
                                        period="FY26-Q3", amount=500_000.0))
    return store.scenario("S-commit")


def test_it_declares_its_own_output_type():
    assert measures.OUTPUT_URI["plan_commit_scenario"] == \
        "http://invincible-agent/mesh#DecisionArtifact"


# ── the rationale gate ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "   ", "\t", "\n  \n"])
def test_a_blank_or_WHITESPACE_rationale_is_refused(bad):
    """`"   "` passes a truthiness check and says nothing. That is the shape that defeats a
    naive `if rationale:` gate, and the ceremony's entire point is that the reason EXISTS."""
    with pytest.raises(measures.NotInModel):
        measures.check_rationale(bad)


def test_a_real_rationale_passes():
    """Positive control. A gate that refuses everything is not a gate."""
    measures.check_rationale("Accepted the Q3 slip to protect Site B's absorption limit.")


def test_a_REFUSED_ceremony_LEAVES_BASELINE_UNTOUCHED(store, scenario):
    """THE ATOMICITY ARM.

    Refusing after applying would move the plan by a decision the system declined to record —
    no artifact, no actor, no reason, and a changed baseline. Tested on the VERSION, because
    an exception alone says nothing about what was written before it was raised.
    """
    before = store.version_of("baseline")
    with pytest.raises(measures.NotInModel):
        measures.check_rationale("   ")
    assert store.version_of("baseline") == before
    assert not store.scenario("S-commit").archived, "a refused ceremony must not archive"


# ── the artifact ─────────────────────────────────────────────────────────────────────────

def _artifact(store, sc, **over):
    kwargs = dict(
        scenario_id=sc.scenario_id,
        scenario_name=sc.name,
        rationale="Accepted the Q3 slip to protect Site B.",
        actor="alice@example.com",
        ops=sc.ops,
        baseline_version=store.version_of("baseline") + 1,
    )
    kwargs.update(over)
    return measures.plan_commit_scenario(**kwargs)


def test_the_artifact_carries_every_disposition_key(store, scenario):
    """COMPOSED, NOT PARALLEL. DECISION_RECORD's contract composes DISPOSED_TASK_FIELD by
    reference; an artifact missing one of its required keys refuses at the card with
    'decision is missing its actor' and the beat dies on stage."""
    art = _artifact(store, scenario)
    missing = [k for k in DISPOSED_KEYS if k not in art["decision"]]
    assert not missing, f"artifact's decision is missing {missing}"


def test_requested_by_and_acted_by_are_the_SAME_person(store, scenario):
    """What DEGENERATE means, made explicit. Phase 7 splits these; today they are one, and a
    reader who sees them differ should know something changed."""
    d = _artifact(store, scenario)["decision"]
    assert d["requested_by"] == d["acted_by"] == "alice@example.com"
    assert d["task_state"] == "approved"
    assert d["decision"] == "approved"


def test_the_rationale_lands_in_COMMENT(store, scenario):
    """`comment` is the disposition family's override-reason field. Putting the rationale
    anywhere else would make DECISION_RECORD's blocking rule unenforceable."""
    d = _artifact(store, scenario, rationale="Protecting Site B.")["decision"]
    assert d["comment"] == "Protecting Site B."


def test_the_ops_are_the_DISPOSED_ITEMS(store, scenario):
    art = _artifact(store, scenario)
    assert len(art["ops"]) == len(scenario.ops) == 1
    assert art["ops"][0]["op"] == "set_cost"
    assert art["ops"][0]["project_id"] == "P1"


def test_acted_at_is_present_and_sortable(store, scenario):
    """`acted_at` is a FACT, not a valid_as_of stamp — DECISION_RECORD does not recompute, so
    this is the only time it is ever written."""
    d = _artifact(store, scenario)["decision"]
    assert d["acted_at"] and d["acted_at"][:4].isdigit(), d["acted_at"]


def test_alternatives_and_question_trail_ride_when_supplied(store, scenario):
    art = _artifact(
        store, scenario,
        alternatives=[{"label": "Defer to Q4", "considered": True, "note": "breaks D4"}],
        question_trail=[{"q": "what blocks P5", "verb": "mesh:planDependencyNeighborhood"}],
    )
    assert art["alternatives"][0]["considered"] is True
    assert art["question_trail"][0]["verb"] == "mesh:planDependencyNeighborhood"


def test_they_default_to_EMPTY_not_absent(store, scenario):
    """The card reads them; absent keys and empty lists render differently, and 'no
    alternatives were considered' is a real statement about a decision."""
    art = _artifact(store, scenario)
    assert art["alternatives"] == []
    assert art["question_trail"] == []


def test_a_commit_with_no_ops_is_refused(store):
    """A decision that disposed nothing is not a decision — the same rule DECISION_RECORD's
    contract states as `minOps: 1`."""
    store.fork("S-empty", "no ops")
    with pytest.raises(measures.NotInModel):
        measures.plan_commit_scenario(
            scenario_id="S-empty", scenario_name="no ops",
            rationale="valid reason", actor="alice@example.com",
            ops=[], baseline_version=1,
        )


# ── the store half, sequenced ────────────────────────────────────────────────────────────

def test_a_SUCCESSFUL_commit_moves_baseline_and_archives(store, scenario):
    """The other side of atomicity: when it does go through, it goes all the way through."""
    before = store.version_of("baseline")
    measures.check_rationale("Accepted the Q3 slip.")
    version = store.commit("S-commit")
    assert version > before
    assert store.scenario("S-commit").archived
    assert store.version_of("baseline") == version
