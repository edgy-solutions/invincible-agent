"""Engine S resolves `HAZ-1003` — and refuses to be the fleet's phone book.

**WHY IT EXISTS, MEASURED 2026-09-14.** The safety walk asked *"draft a risk assessment for
HAZ-1003"* and got *"you named a specific item, but no provider in the mesh recognizes it."* The
identifier was in this engine's own fixture the whole time. **Registration is not resolution**: a
verb that takes a hazard is unreachable by name until something claims that class's identifiers,
and nothing did.

── THE OTHER HALF, WHICH IS THE ONE THAT DAMAGES NEIGHBOURS ────────────────────────────────────
A provider that scores generously does not merely answer badly — it **displaces correct answers
from other engines**, because a phone-book hit overrides a classifier's `resolved_uri`. engine-fin
matched the bare digit in "lot 4" against an `instance_id`, returned **0.500**, and beat a correct
**0.92** cost answer; `banana 4` reproduced it. Safety identifiers are prefixed, which makes the
temptation smaller and the rule no less necessary:

    A BARE NUMBER IS NOT A NAME unless the caller supplies the class.

So this file asserts both directions, and **the abstentions are the load-bearing half**. A seal
that only checked `HAZ-1003` resolves would pass on a provider that also claims `1003`, `4`, and
every word in every hazard description — which is the defect, not the feature.
"""
from __future__ import annotations

import pytest

from agent_fleet.safety_agent import entities, instances

_HAZARD = "http://internal/sustainment/safety#Hazard"
_WORK_ORDER = "http://internal/maintenance#WorkOrder"


def test_the_fixture_is_not_empty_so_nothing_here_is_vacuous():
    """THE FLOOR. Every assertion below quantifies over the fixture; an empty one would make the
    abstention tests pass by having nothing to match."""
    assert entities.HAZARDS, "no hazards in the fixture"
    assert any(h.hazard_id == "HAZ-1003" for h in entities.HAZARDS), (
        "HAZ-1003 is not in the fixture — this seal is testing a different subject than the walk"
    )


# ---------------------------------------------------------------------------
# IT RESOLVES
# ---------------------------------------------------------------------------

def test_the_exact_identifier_resolves_at_the_top():
    got = instances.resolve("HAZ-1003")
    assert got, "HAZ-1003 resolves to nothing — this is the walk's failure, unfixed"
    assert got[0]["instance_id"] == "HAZ-1003"
    assert got[0]["score"] == 1.0
    assert got[0]["class_uri"] == _HAZARD


def test_the_identifier_inside_a_spoken_sentence_resolves():
    """THE SHAPE THE WALK ACTUALLY SENT. The supervisor does not hand a provider a bare id; it
    hands it what the person said. A provider that only matched exact strings would pass the test
    above and fail the walk identically."""
    got = instances.resolve("draft a risk assessment for HAZ-1003")
    assert got and got[0]["instance_id"] == "HAZ-1003", got


def test_a_class_hint_narrows_rather_than_widens():
    assert instances.resolve("HAZ-1003", _HAZARD)
    assert instances.resolve("HAZ-1003", "http://internal/sustainment/safety#WriteUp") == []


# ---------------------------------------------------------------------------
# IT ABSTAINS — the half that protects every other engine
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("identifier", ["1003", "4", "banana 4", "", "   ", "the"])
def test_it_abstains_rather_than_claiming_a_bare_or_empty_token(identifier):
    """`banana 4` IS THE REGRESSION CASE BY NAME, carried from the cost defect rather than
    re-derived. `1003` is its safety-shaped twin: matching the numeric tail of a prefixed
    identifier is the same behaviour one naming convention along."""
    assert instances.resolve(identifier) == [], (
        f"{identifier!r} resolved — this provider would displace other engines' correct answers, "
        "which is the defect the bare-number rule exists for"
    )


def test_a_single_shared_word_is_not_a_name_match():
    """Token overlap is scaled BELOW the floor unless it is substantial. One word in common
    between a question and a hazard description is not an identification."""
    word = entities.HAZARDS[0].description.split()[0]
    assert instances.resolve(word) == [], (
        f"a single word ({word!r}) from a description resolved as an instance"
    )


def test_the_floor_is_the_thing_being_asserted_not_a_coincidence():
    """THE CONTROL FOR THE ABSTENTIONS. If `resolve` returned [] for everything, every test above
    would pass — so a real identifier must still get through, and the floor must be the reason the
    others do not."""
    assert instances.RESOLVE_FLOOR == 0.5
    assert instances.resolve("HAZ-1003"), "the resolver returns nothing for anything"
    assert instances._score("1003", {"identifier": "HAZ-1003", "label": "x"}) < instances.RESOLVE_FLOOR


# ---------------------------------------------------------------------------
# ENUMERATION — three named outcomes
# ---------------------------------------------------------------------------

def test_a_held_class_enumerates_its_members():
    out = instances.enumerate_class(_HAZARD)
    assert out["outcome"] == "members"
    assert out["count"] == len(entities.HAZARDS)
    assert {m["identifier"] for m in out["members"]} == {h.hazard_id for h in entities.HAZARDS}


def test_an_unheld_class_is_UNSUPPORTED_and_never_an_empty_list():
    """THE DISCRIMINANT. A class this provider does not hold and a class it holds zero members of
    are different facts; collapsing them offers "no options" for a question nobody asked it."""
    out = instances.enumerate_class(_WORK_ORDER)
    assert out["outcome"] == "unsupported", out
    assert "members" not in out, "an unsupported class answered with a member list"
    # A refusal that names only what failed makes the next attempt another guess.
    assert out["supported"], "the refusal does not say what this provider does hold"
    assert _HAZARD in out["supported"]


def test_too_many_is_reserved_for_a_class_larger_than_a_menu():
    """Asserted by driving the bound rather than by reading the default, because the defect this
    guards against was a bound of 8 against nine members — a refusal designed to protect an ask
    becoming the reason the ask had nothing to show."""
    assert instances.enumerate_class(_HAZARD, limit=1)["outcome"] == "too_many"
    assert instances.enumerate_class(_HAZARD, limit=25)["outcome"] == "members", (
        "the engine's largest class does not fit the default bound — `too_many` would fire on a "
        "class that is menu-sized, which is the engine-cost defect repeated"
    )


def test_work_orders_are_UNCLAIMED_deliberately_and_this_records_it():
    """A DECISION, NOT A GAP, and asserted so it cannot become one silently.

    `assessDeferralRisk` takes a work order, so "assess the deferral risk for WO-3001" fails to
    resolve exactly as HAZ-1003 did. This engine does not claim the class: work orders are the
    MAINTENANCE plane's, and claiming them because they sit in this fixture would be an ownership
    decision made by convenience. If a later ruling gives Engine S that class, this test is the
    one that must change — which is the point of writing the refusal down.
    """
    assert instances.enumerate_class(_WORK_ORDER)["outcome"] == "unsupported"
    assert instances.resolve("WO-3001") == []
