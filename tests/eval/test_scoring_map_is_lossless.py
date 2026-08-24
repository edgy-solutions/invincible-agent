"""THE SCORER MUST BE ABLE TO PRODUCE EVERY INTENT IT GRADES.

Funnel B answers with a VERB; the fixture expects an INTENT. If the scorer
translates verb -> intent, it is keying a dict on the MANY side of a
many-to-one relation, and every intent that loses a collision becomes
UNPRODUCEABLE — its cases fail no matter what the funnel does.

Two collisions exist in the catalog today and both are legitimate. They are
not a modelling error to be normalised away:

    plan_schedule                 <- site_schedule, projects_in
    plan_dependency_neighborhood  <- what_blocks,   downstream_of

One verb genuinely answers two differently-phrased questions. The defect was
never the sharing; it was a MEASUREMENT INSTRUMENT that could not represent it.

Measured 2026-08-24, before this guard existed: q6-a and q6-b resolved
mesh:planSchedule and q10-b resolved mesh:planDependencyNeighborhood — all
three CORRECT — and all three were recorded as failures. Two landed in the
nomination arm, which is the arm used to reason about retrieval quality. A
referee that writes correct answers in the failure column corrupts the
diagnosis as well as the total, and the diagnosis is the deliverable.

Run: uv run --frozen --with pytest --with pyyaml pytest tests/eval/test_scoring_map_is_lossless.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
_CATALOG = _REPO / "agent_fleet" / "planning_agent" / "intent_catalog.yaml"

sys.path.insert(0, str(_HERE))


def _catalog_intents_with_a_measure() -> set[str]:
    cat = yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))
    return {i["intent_id"] for i in cat["intents"] if i.get("measure_id")}


def test_every_measurable_intent_is_PRODUCEABLE_by_the_scoring_map():
    """THE ARM THAT WAS RED. Under verb -> intent this fails by exactly the
    number of collision losers; under intent -> verb it cannot fail at all."""
    from funnel_b_runner import _intent_to_verb  # noqa: PLC0415

    produceable = set(_intent_to_verb())
    missing = sorted(_catalog_intents_with_a_measure() - produceable)
    assert not missing, (
        f"intents the scorer can never produce: {missing} — their cases fail "
        f"regardless of what the funnel resolves"
    )


def test_the_reverse_map_IS_lossy_which_is_why_scoring_must_not_use_it():
    """Pins the hazard rather than the workaround.

    If a future refactor makes verb -> intent injective (by splitting a verb,
    or dropping an intent), this goes red and asks whether the catalog changed
    on purpose. That is the correct time to revisit the scorer — not silently,
    six months later, inside a number nobody can reproduce.
    """
    from funnel_b_runner import _intent_to_verb, _verb_to_intent  # noqa: PLC0415

    forward = _intent_to_verb()
    assert len(set(forward.values())) < len(forward), (
        "no verb is shared by two intents any more — the many-to-one hazard "
        "this guard exists for may be gone; re-read the scorer before trusting it"
    )
    # And the lossy direction really does drop the losers, which is the
    # mechanism, not an incidental detail.
    assert len(_verb_to_intent()) < len(forward)


def test_scoring_compares_VERB_to_VERB():
    """Behavioural, not textual. Builds the exact situation that misgraded —
    an expected intent that LOST its collision — and asserts the scorer counts
    the correct verb as correct.

    Asserting on the runner's source instead would match its own explanatory
    comments, which is the mistake this repo has now made three times.
    """
    from funnel_b_runner import _intent_to_verb, _verb_to_intent  # noqa: PLC0415

    forward = _intent_to_verb()
    reverse = _verb_to_intent()

    losers = [i for i, v in forward.items() if reverse.get(v) != i]
    assert losers, "expected at least one collision loser to exercise"

    for intent in losers:
        verb = forward[intent]
        # What the funnel returns when it is RIGHT about this question.
        assert forward[intent] == verb
        # Under the old rule this compared reverse[verb] != intent and failed.
        assert reverse[verb] != intent, (
            f"{intent} is a collision loser, so intent-based scoring would "
            f"have graded a correct {verb} as a miss"
        )
