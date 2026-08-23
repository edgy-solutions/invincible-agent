"""`plan_dependency_neighborhood` — traversal, NOT constraint evaluation.

WHY A THIRTEENTH VERB RATHER THAN A PARAMETER ON THE TWELFTH. Ruled 2026-08-22 after Lane 2
found two intents with nowhere to route. `plan_dependency_violations` EVALUATES A CONSTRAINT
over the dependency data; "what does P5 depend on?" TRAVERSES it. Different question, different
answer shape, and `mesh:ConstraintViolationSet` is honestly the wrong output type for "P5's
predecessors, satisfied or not" — stretching one verb across both is the borrowed-shape defect
that this repo keeps paying for in other registries.

THE ARM THIS VERB EXISTS FOR — the confident blank. Measured on the seed today:
`plan_dependency_violations` returns **[]**, because nothing is currently violated. So a
question routed there answers "what blocks P5?" with silence, and silence reads as "nothing
depends on P5" rather than "P5's three predecessors are all satisfied". Those are different
facts and only one of them is true. **A project with predecessors and no violations must return
its predecessors.**

AN EMPTY NEIGHBOURHOOD IS STILL A REAL ANSWER, and it is a THIRD case that must not collapse
into either of the others: P1 is a root — it genuinely has no predecessors. That is an honest
empty, distinct from "P99 is not in the model" (which RAISES) and from "P5 has predecessors,
all satisfied" (which returns rows).
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


@pytest.fixture
def state():
    return build_seed()


def test_it_declares_its_own_output_type():
    """ADR-0030: one verb, one fixed output type. A verb sharing another's output type would
    make the selector unable to tell their answers apart."""
    assert measures.OUTPUT_URI["plan_dependency_neighborhood"] == \
        "http://invincible-agent/mesh#DependencyNeighborhoodSet"


def test_the_premise_holds_the_seed_has_no_violations_today(state):
    """POSITIVE CONTROL for the arm below. If the seed ever gains a violation, the
    confident-blank test stops testing what it claims to test — it would pass because the
    violations verb found something, not because this verb traverses."""
    assert measures.plan_dependency_violations(state) == [], \
        "the seed now has violations; the confident-blank arm below no longer isolates traversal"


def test_a_project_with_no_violations_still_returns_its_predecessors(state):
    """THE ARM THE VERB EXISTS FOR.

    P5 depends on P3 (D4, FS +14) and nothing is violated. The truthful answer to 'what does
    P5 wait on' is 'P3, satisfied' — never a blank.
    """
    out = measures.plan_dependency_neighborhood(state, project_id="P5", direction="upstream")
    ids = [n["id"] for n in out["neighbors"]]
    assert ids == ["P3"], f"expected P5's predecessor, got {ids}"
    assert out["neighbors"][0]["status"] == "satisfied"
    assert out["neighbors"][0]["dep_type"] == "FS"
    assert out["neighbors"][0]["lag_days"] == 14


def test_upstream_and_downstream_are_different_questions(state):
    """P2 is downstream of P1 and upstream of P3 and P4. A verb that conflated the two would
    answer 'what does this block' with 'what blocks this'."""
    up = measures.plan_dependency_neighborhood(state, project_id="P2", direction="upstream")
    down = measures.plan_dependency_neighborhood(state, project_id="P2", direction="downstream")
    assert [n["id"] for n in up["neighbors"]] == ["P1"]
    assert sorted(n["id"] for n in down["neighbors"]) == ["P3", "P4"]


def test_a_root_returns_an_honest_empty_not_an_error(state):
    """P1 has no predecessors. That is an ANSWER — 'nothing blocks this' — and it must be
    distinguishable from the model not knowing the project."""
    out = measures.plan_dependency_neighborhood(state, project_id="P1", direction="upstream")
    assert out["neighbors"] == []
    assert out["project_id"] == "P1"


def test_an_unknown_project_RAISES_rather_than_returning_empty(state):
    """The NotInModel discipline. An empty row set for an unknown project renders as 'nothing
    depends on it', which is a false statement about a project that does not exist."""
    with pytest.raises(measures.NotInModel):
        measures.plan_dependency_neighborhood(state, project_id="P99", direction="upstream")


def test_an_unknown_direction_RAISES(state):
    """Same reasoning as group_by/color_by on plan_schedule: a direction the verb cannot
    traverse is a question outside the model, not an empty result."""
    with pytest.raises(measures.NotInModel):
        measures.plan_dependency_neighborhood(state, project_id="P5", direction="sideways")


def test_it_carries_the_subject_and_direction_it_was_asked_about(state):
    """The payload names its own question. A renderer that had to infer 'upstream' from the
    caller's request would be a second place holding the same fact."""
    out = measures.plan_dependency_neighborhood(state, project_id="P5", direction="upstream")
    assert out["project_id"] == "P5"
    assert out["direction"] == "upstream"
    assert isinstance(out["project_name"], str) and out["project_name"]


def test_phase_ends_traverse_too(state):
    """D9 is phase->phase. `interval_of` handles both ends so a dependency between a phase and
    a project is not a special case — the traversal must not quietly drop non-project ends."""
    out = measures.plan_dependency_neighborhood(
        state, project_id="I2-P4", direction="upstream", kind="phase")
    assert [n["id"] for n in out["neighbors"]] == ["I2-P2"]
    assert out["neighbors"][0]["kind"] == "phase"


def test_every_neighbor_carries_a_status_from_a_closed_vocabulary(state):
    """A status the renderer has never seen cannot be styled, and an absent one reads as
    satisfied — the confident blank one level down."""
    allowed = {"satisfied", "violated", "unresolvable"}
    for pid in ("P2", "P3", "P5", "P7", "P12"):
        for direction in ("upstream", "downstream"):
            out = measures.plan_dependency_neighborhood(state, project_id=pid, direction=direction)
            for n in out["neighbors"]:
                assert n["status"] in allowed, f"{pid}/{direction}: {n['status']!r}"
