"""ADR-0033's `route | ask | abstain`, against the acceptance pre-registered before it existed.

THE PARTITION IS THE TEST PLAN, and it was written down before this module did. Run 5 of the
48-case battery left a residue of 3 MISSED / 0 WRONG / 0 EXTRA, and the pre-registration said
the trigger must fire on exactly one of the three. The negative half is the load-bearing half:
`E04` and `C04` are GENUINE misses of information the user supplied, and both must still route,
because both miss only spoken-OPTIONAL slots where a default is a legitimate answer.

    E05  misses project_id       spoken-MANDATORY  -> ASK
    E04  misses direction        spoken-optional   -> ROUTE
    C04  misses site_id, window  spoken-optional   -> ROUTE

A feature that catches all the residue has the wrong trigger.

DECLARATIONS ARE READ FROM THE LIVE ENGINE, NOT TRANSCRIBED. `slots_for()` derives them from
`inspect.signature`, and a fixture copy here would be the fifth hand-kept list this repo has
paid for. If a signature changes, these tests must move with it or fail — that is the point.
"""
from __future__ import annotations

import pytest

from iagent_pure.slot_disposition import (
    ABSTAIN,
    ASK,
    FREE_TEXT_REASONS,
    ROUTE,
    SRC_ENUMERATION,
    SRC_NONE,
    SRC_RESOLUTION,
    ask_card,
    ask_message,
    decide_disposition,
)

IDP = "http://invincible-agent/idp#"


@pytest.fixture(scope="module")
def slots_for():
    from agent_fleet.planning_agent.slots import slots_for as _s
    return _s


def _members(*pairs):
    return lambda _cls: {
        "outcome": "members",
        "count": len(pairs),
        "members": [{"instance_id": i, "label": l} for i, l in pairs],
    }


def _too_many(count):
    return lambda _cls: {"outcome": "too_many", "count": count, "bound": 8, "members": []}


# ---------------------------------------------------------------------------------------
# 5a — MUST ASK
# ---------------------------------------------------------------------------------------

def test_A1_H06_a_required_slot_named_nowhere_asks(slots_for):
    """`"what is the capability path"` — the phrase names no capability and the verb needs
    one. This case grades CORRECT in the filler's corpus (`expect: {}`, `got: {}`: the filler
    was right not to invent) AND must ask. **Filler-correct and disposition-complete are
    different predicates** — the filler's job is to not invent, the disposition's is to
    notice what is absent, and this is the seam `ask` occupies."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"),
        resolution={}, enumerate_class=None,
    )
    assert d.action == ASK
    assert d.slot == "capability_id"
    assert d.reason == "slot-unfilled"


def test_A2_E05_a_name_that_resolved_to_the_wrong_kind_asks(slots_for):
    """`"what does the ERP Modernization project depend on"` — resolves to `I1`, an
    Initiative, against a slot declaring `#Project`. The fill REMOVES it rather than passing
    the name through, so the slot is absent and the ask fires.

    ASSERTED ON THE REPORTED OUTCOME, NOT ON THE ABSENCE OF A VALUE. `H06` and `E05` are both
    `got: {}`; a test keying on emptiness passes for both and means neither. That is the
    neighbour-assertion trap, and the whole reason the harness had to start recording
    `resolution`."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_dependency_neighborhood"),
        resolution={"project_id": {
            "outcome": "wrong_class", "spoken": "ERP Modernization project",
            "instance_id": None,
            "candidates": [{"instance_id": "I1", "class_uri": IDP + "Initiative",
                            "label": "ERP Modernization"}],
        }},
        enumerate_class=_too_many(14),
    )
    assert d.action == ASK
    assert d.slot == "project_id"
    assert d.reason == "wrong_class"          # NOT "slot-unfilled" — the shapes differ
    assert d.spoken == "ERP Modernization project"


def test_A2_the_cross_class_candidate_is_EVIDENCE_and_never_an_OPTION(slots_for):
    """THE CORRECTION THE BUILD FOUND. `/fill_slots` synthesises a candidate from the winner
    so every non-empty outcome carries one — but `wrong_class` is BY DEFINITION a candidate
    whose class is not the slot's referent, so **a `wrong_class` outcome can never supply a
    menu for its own slot.** Offering `I1` for `project_id` would 422 with the user's own
    click behind it, which is exactly the failure the tri-state exists to prevent.

    So the candidate becomes CONTEXT and the menu comes from the option ladder."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_dependency_neighborhood"),
        resolution={"project_id": {
            "outcome": "wrong_class", "spoken": "ERP Modernization project",
            "candidates": [{"instance_id": "I1", "class_uri": IDP + "Initiative",
                            "label": "ERP Modernization"}],
        }},
        enumerate_class=_too_many(14),
    )
    assert "I1" not in [o.value for o in d.options]
    assert d.option_source != SRC_RESOLUTION
    assert d.found == "ERP Modernization"          # kept, as context
    assert "ERP Modernization" in ask_message(d)   # and said out loud


def test_A3_a_missing_mandatory_slot_is_an_ask_and_not_a_400(slots_for):
    """The live failure this whole disposition replaces:

        400 bad params ... missing 1 required keyword-only argument: 'project_id'

    a Python signature error rendered to a person who asked about phases. **The assertion is
    on the DISPOSITION, not on the text** — a 400 whose message reads better is still a 400."""
    d = decide_disposition(
        accepted={"direction": "upstream", "kind": "phase"},
        declared=slots_for("plan_dependency_neighborhood"),
        resolution={}, enumerate_class=None,
    )
    assert d.action == ASK and d.slot == "project_id"


def test_same_class_candidates_ARE_a_menu(slots_for):
    """The disambiguation path proper — ADR-0033 #2's ORIGINAL option source, needing no new
    substrate. NO CORPUS CASE REACHES IT TODAY (every referent case in run 5 resolved `exact`
    or came back `wrong_class`), so it is exercised by fixture and that is stated rather than
    hidden: this is coverage of a built path, not evidence of a measured one."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_dependency_neighborhood"),
        resolution={"project_id": {
            "outcome": "fuzzy", "spoken": "cutover",
            "candidates": [{"instance_id": "P1", "class_uri": IDP + "Project", "label": "Wave 1 Cutover"},
                           {"instance_id": "P2", "class_uri": IDP + "Project", "label": "Wave 2 Cutover"}],
        }},
        enumerate_class=None,
    )
    assert d.action == ASK
    assert d.option_source == SRC_RESOLUTION
    assert [o.value for o in d.options] == ["P1", "P2"]


def test_enumeration_supplies_the_menu_when_the_provider_can(slots_for):
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"), resolution={},
        enumerate_class=_members(("C1", "Billing"), ("C2", "Invoicing")),
    )
    assert d.option_source == SRC_ENUMERATION
    assert [o.value for o in d.options] == ["C1", "C2"]


# ---------------------------------------------------------------------------------------
# 5b — MUST STILL ROUTE SILENTLY. The guardrail, and the harder half.
# ---------------------------------------------------------------------------------------

def test_E04_a_genuine_miss_on_an_OPTIONAL_slot_still_routes(slots_for):
    """`"what phases feed into P7"` — fills `project_id` and `kind`, misses `direction`
    ("feed into" as a paraphrase for upstream). A REAL miss of information the user supplied,
    and it must still route: `direction` is spoken-optional and its default IS the answer.

    `E04` was an ask case two runs ago and is not one now, because the filler fixed it. That
    is the success mode, and `ask_on_present_in_phrase` is the counter that keeps it
    distinguishable from a trigger that broke."""
    d = decide_disposition(
        accepted={"project_id": "P7", "kind": "phase"},
        declared=slots_for("plan_dependency_neighborhood"),
        resolution={"project_id": {"outcome": "exact", "instance_id": "P7"}},
        enumerate_class=None,
    )
    assert d.action == ROUTE


def test_C04_two_optional_misses_still_route(slots_for):
    """`"how loaded is site S1 in FY26-Q2"` — the known non-deterministic case, missing both
    optional slots. An ask here would make run-to-run flakiness user-visible as a question,
    which is the worst possible form for it to take."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_site_load"), resolution={}, enumerate_class=None,
    )
    assert d.action == ROUTE


@pytest.mark.parametrize("fn", [
    "plan_funding_gap", "plan_schedule", "plan_cost_curve", "plan_maturity_grid",
    "plan_site_load", "plan_diff", "plan_coverage_gap", "plan_dependency_violations",
    "plan_session_changes", "plan_commit_scenario",
])
def test_verbs_with_no_mandatory_slot_can_never_ask(fn, slots_for):
    """37 of the 48 corpus cases run on verbs like these. THE ANTI-CLIPPY PROPERTY IS
    STRUCTURAL, not a tuned threshold: `decide_disposition` walks only spoken-mandatory
    declarations, so on a verb that declares none the trigger is unreachable by construction.

    `plan_commit_scenario` is in the list deliberately — it is the ceremony, whose parameters
    arrive by a governed UI flow. Asking a user to speak them is asking them to compose a
    governance record in a sentence."""
    assert decide_disposition(
        accepted={}, declared=slots_for(fn), resolution={}, enumerate_class=None,
    ).action == ROUTE


def test_a_filled_mandatory_slot_is_never_asked_about(slots_for):
    """ADR-0033 #4's guardrail in its plainest form: exact/unique short-circuits before any
    ask fires. *A system that asks when it knows is worse than one that guesses when it
    doesn't.*"""
    d = decide_disposition(
        accepted={"capability_id": "C1"}, declared=slots_for("plan_capability_path"),
        resolution={"capability_id": {"outcome": "exact", "instance_id": "C1"}},
        enumerate_class=_members(("C1", "Billing")),
    )
    assert d.action == ROUTE


# ---------------------------------------------------------------------------------------
# 5c — MUST STILL ABSTAIN. `ask` is a THIRD disposition, not a replacement for the second.
# ---------------------------------------------------------------------------------------

def test_empty_resolution_abstains_rather_than_offering_an_empty_menu(slots_for):
    """`empty` means the providers answered cleanly and there is no such thing. Asking would
    offer a menu with nothing on it, which fails menu integrity. `instance_resolution.decide`
    split `empty` out of `not_specific` so the gate's actions could not hide inside a
    not-found — this is the consumer that needed the distinction."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"),
        resolution={"capability_id": {"outcome": "empty", "spoken": "Nonesuch",
                                      "candidates": []}},
        enumerate_class=_members(("C1", "Billing")),
    )
    assert d.action == ABSTAIN
    assert "Nonesuch" in ask_message(d)


def test_an_enumerable_class_with_no_members_abstains(slots_for):
    """`members: []` is a real answer, and an empty menu is not a menu. Closer to `empty`
    than to a question."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"), resolution={},
        enumerate_class=lambda _c: {"outcome": "members", "count": 0, "members": []},
    )
    assert d.action == ABSTAIN


# ---------------------------------------------------------------------------------------
# TRIPWIRES — premises that expire should FAIL, not wait on someone's memory
# ---------------------------------------------------------------------------------------

def test_TRIPWIRE_free_text_must_carry_a_provider_reason(slots_for):
    """THE EXPIRY ON THE FREE-TEXT INTERIM. ADR-0033 permits free text only where the
    substrate genuinely cannot enumerate — "never as a default, never as a convenience, and
    never because enumeration was not attempted."

    So an ask with no menu must always say WHY, from a closed set. A menuless ask that cannot
    name its reason is the open question this ADR retired, wearing a slot's name.

    Note the reason this is a *reason* check and not a *provider-exists* check: once the
    fan-out lands, a registered provider can still legitimately answer `too_many` (Capability
    has 9 members against a bound of 8), so "a provider exists therefore free text is banned"
    would be wrong. What must never happen is silence."""
    for enumerator in (None,
                       _too_many(400),
                       lambda _c: {"outcome": "unsupported", "reason": "not my class"},
                       lambda _c: {"outcome": "something-new-nobody-declared"}):
        d = decide_disposition(
            accepted={}, declared=slots_for("plan_capability_path"),
            resolution={}, enumerate_class=enumerator,
        )
        assert d.action == ASK
        if not d.options:
            assert d.option_source == SRC_NONE
            assert d.free_text_reason in FREE_TEXT_REASONS, (
                f"a menuless ask with no reason: {d}"
            )


def test_TRIPWIRE_one_ask_per_dispatch_holds_only_while_verbs_have_one_mandatory_slot():
    """ADR-0033 #3 bounds the exchange at one turn, and the stateless re-route was chosen on
    the measured basis that no verb declares more than one spoken-mandatory slot — so
    held-promise's population is zero and building for it would be inventing a lifetime.

    THE GRADUATION CONDITION IS THIS ASSERTION, not a roadmap line. The day a verb declares
    two, this fails and the pending-state choice re-opens on evidence rather than taste."""
    from agent_fleet.planning_agent import measures
    from agent_fleet.planning_agent.slots import slots_for as _s

    worst = {}
    for name in dir(measures):
        if not name.startswith("plan_"):
            continue
        n = len([d for d in _s(name) if d.get("kind") == "spoken-mandatory"])
        if n:
            worst[name] = n
    assert worst, "no verb declares a mandatory slot — the census has changed"
    assert max(worst.values()) == 1, (
        f"multi-slot elicitation has arrived ({worst}) — re-open the pending-state choice: "
        "stateless re-route vs. held-promise"
    )


# ---------------------------------------------------------------------------------------
# The card contract — the re-route's mechanism
# ---------------------------------------------------------------------------------------

def test_the_card_carries_the_accepted_slots_so_the_reroute_MERGES(slots_for):
    """THE SHARP EDGE, AND WHY THE CARD LOOKS LIKE THIS. `execute_subtask` reads
    `spoken = dict(config.slots or {})` and only fills when that is empty. A re-route
    pre-binding ONLY the answered slot would therefore suppress filling of every other slot
    the first turn already got right — `direction` and `kind` here.

    Carrying the accepted set back means the re-route re-issues `{**accepted, slot: chosen}`
    and makes NO second model call, so the second turn cannot parse the phrase differently
    than the first did. The re-route is reconstructed, never re-parsed."""
    accepted = {"direction": "upstream", "kind": "phase"}
    d = decide_disposition(
        accepted=accepted, declared=slots_for("plan_dependency_neighborhood"),
        resolution={}, enumerate_class=None,
    )
    card = ask_card(d, verb_iri="mesh:planDependencyNeighborhood",
                    sub_query="what phases does I1-P1 depend on upstream", accepted=accepted)
    assert card["accepted_slots"] == accepted
    assert card["status"] == "slot_elicitation"
    assert card["slot"] == "project_id"
    assert card["message"]          # the honest fallback stands alone until the card lands


def test_every_offered_option_is_the_value_the_verb_takes(slots_for):
    """MENU INTEGRITY (ADR-0033 #2 / ADR-0032, verbatim): every offered option must route
    successfully when chosen. So an option's `value` is always the id or literal the verb
    accepts, never a display string — the label is for the reader, the value is for the verb."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"), resolution={},
        enumerate_class=_members(("C1", "Billing"), ("C2", "Invoicing")),
    )
    card = ask_card(d, verb_iri="v", sub_query="q", accepted={})
    assert [o["value"] for o in card["options"]] == ["C1", "C2"]
    assert all(o["value"] and o["label"] for o in card["options"])


# ---------------------------------------------------------------------------------------
# Bounds and failure posture
# ---------------------------------------------------------------------------------------

def test_candidates_are_truncated_to_the_menu_bound_and_say_so(slots_for):
    """The triage's 19-candidate abstention is the motivating case: 19 is not a menu.
    Truncation is legitimate for RESOLVER candidates because they are scored and arrive
    ranked — ADR-0033 #2's own "top-k from resolveInstance". It is NOT legitimate for
    enumeration, which has no ranking, and that is why the enumerator answers `too_many`
    instead of sending its first eight."""
    cands = [{"instance_id": f"P{i}", "class_uri": IDP + "Project", "label": f"P{i}"}
             for i in range(19)]
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_dependency_neighborhood"),
        resolution={"project_id": {"outcome": "not_specific", "spoken": "wave",
                                   "candidates": cands}},
        enumerate_class=None, menu_bound=8,
    )
    assert len(d.options) == 8
    assert d.truncated_from == 19
    assert "of 19" in ask_message(d)


def test_a_broken_enumerator_degrades_to_free_text_and_never_raises(slots_for):
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"), resolution={},
        enumerate_class=lambda _c: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert d.action == ASK and d.free_text_reason in FREE_TEXT_REASONS


def test_unreadable_declarations_fail_SAFE_toward_route():
    """An `ask` interrupts a flow that currently completes, so a bug in this module must not
    be able to invent an interruption. Same trade `_fill_slots_from_query` makes when it
    returns honest-empty on every failure."""
    for bad in (None, "", "not json", "[]", 12345):
        assert decide_disposition(
            accepted={}, declared=bad, resolution={}, enumerate_class=None,
        ).action == ROUTE
