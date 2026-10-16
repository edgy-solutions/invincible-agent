"""PN-8802 is both a SafetyCriticalItem and (in engine-o's vocabulary) a pcn#Component. RULED
2026-10-15: a part number is not an identifier namespace; across classes the VERB ASKED settles it
(decide() keeps both class candidates, the router binds the one whose class carries the verb).

Both verbs are DERIVED from registrations, never typed. The safety side is derivable today; the
component side is not registered anywhere in this repo yet (Lane 1's (b) registers
whatFailedOnThisPart on the component class), so the cross-engine arm is SKIPPED until 74's
change lands and the verbs exist to derive.
"""
from __future__ import annotations

import pytest

from agent_fleet.safety_agent import main as safety_main

SAFETY_ITEM = safety_main.SAFETY + "SafetyCriticalItem"
COMPONENT = "http://internal/sustainment/pcn#Component"


def verbs_taking(class_uri):
    """Verb IRIs registered with `class_uri` as input, from this engine's registration list."""
    return {v["verb"] for v in safety_main.VERBS if v["input_uri"] == class_uri}


def test_the_safety_item_verb_is_derivable_from_the_registration():
    assert verbs_taking(SAFETY_ITEM) == {"mesh:whatFailedOnThisPart"}


@pytest.mark.skip(reason=(
    "BLOCKED on lane/74's decide() change (ruling 2026-10-15): same-class tie -> "
    "ambiguous_in_class; cross-class ambiguity kept as both class candidates and settled by the "
    "verb asked; ambiguous_in_domain only when two engines claim the SAME class. Also needs a "
    "sustainment verb registered on pcn#Component, which no registration in this repo carries "
    "yet. Unskip when both land, then walk live after 189."
))
def test_pn_8802_as_bob_the_verb_asked_picks_the_class():
    fracas_only = verbs_taking(SAFETY_ITEM) - verbs_taking(COMPONENT)
    component_only = verbs_taking(COMPONENT) - verbs_taking(SAFETY_ITEM)
    assert fracas_only and component_only, "the two classes cannot be told apart by a verb"
    # bob, PN-8802: any fracas_only verb binds SafetyCriticalItem; any component_only verb binds
    # pcn#Component. Fan the real resolver out (as the HAZ-1004 test does) once 74's decide() lands.
    raise AssertionError("unreachable until decide() keeps both class candidates")
