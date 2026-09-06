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

import json
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


# ---------------------------------------------------------------------------------------
# THE ANSWER SIDE — pick validation and the re-route
#
# Added 2026-08-30 after the SPO-interview read (`[[spo-interview-reuse-for-elicitation]]`)
# found that menu integrity was enforced at CONSTRUCTION and not at ACCEPTANCE.
# ---------------------------------------------------------------------------------------

from iagent_pure.slot_disposition import (  # noqa: E402
    BIND,
    RESPEAK,
    PickRefused,
    resolve_ask,
    validate_pick,
)


def _card(slots_for, measure, **over):
    d = decide_disposition(
        accepted=over.pop("accepted", {}), declared=slots_for(measure),
        resolution=over.pop("resolution", {}), enumerate_class=over.pop("enumerate_class", None),
    )
    return ask_card(d, verb_iri="v", sub_query=over.pop("sub_query", "q"),
                    accepted=over.pop("card_accepted", {}))


def test_THE_GAP_a_fabricated_pick_is_refused(slots_for):
    """THE MEASURED HOLE THIS CLOSES. Before this existed:

        accept_slots({"project_id": "TOTALLY-MADE-UP"}, ...) -> ACCEPTED, zero refusals

    because an instance slot declares `type: str` with no `values`, so the declaration-side
    guard has no vocabulary to test membership against. A menu was offered and nothing
    checked that the answer came from it."""
    card = _card(slots_for, "plan_capability_path",
                 enumerate_class=_members(("C1", "Billing"), ("C2", "Invoicing")))
    assert card["options"]
    with pytest.raises(PickRefused):
        resolve_ask(card, "TOTALLY-MADE-UP")


def test_a_pick_from_the_menu_BINDS_and_merges(slots_for):
    """The happy path, and the merge is the part that matters: `execute_subtask` reads
    `spoken = dict(config.slots or {})` and only fills when that is EMPTY, so a re-route
    pre-binding only the answered slot would suppress filling of every slot the first turn
    already got right. The card carries them; the re-route re-issues all of them."""
    card = _card(slots_for, "plan_dependency_neighborhood",
                 accepted={"direction": "upstream", "kind": "phase"},
                 card_accepted={"direction": "upstream", "kind": "phase"},
                 enumerate_class=_members(("P1", "Wave 1"), ("P2", "Wave 2")))
    r = resolve_ask(card, "P2")
    assert r.action == BIND
    assert r.slots == {"direction": "upstream", "kind": "phase", "project_id": "P2"}


def test_a_FREE_TEXT_answer_is_RESPOKEN_and_never_bound(slots_for):
    """THE DISTINCTION THAT KEEPS THE HOLE CLOSED WHERE THERE IS NO MENU.

    Both live ask cases fall to free text today (`too_many` on Capability's 9 and Project's
    14 against bound 8). A free-text answer is WORDS, not an identifier — binding
    `project_id="Wave 1 Cutover"` directly is the same fabricated-pick hole with a human's
    typing in it, and it reaches the engine as a 422.

    So it re-enters for RESOLUTION and the filler and resolver run on it exactly as they
    would on any question. Nothing enters a verb unresolved.

    UPDATED 2026-09-05 (the rewrite fold). This used to assert the answer was IN `r.query`,
    because `resolve_ask` composed `"<phrase> (<slot>: <answer>)"`. That composed string
    became what a person read on the rail — `Provide the current funding status.
    (program_id: meridian)`, machine syntax presented as the user's question. Ruled: nothing
    is composed. The phrase stays byte-equal and the answer travels as a FIELD, so the
    assertion moves from "inside the query" to "beside it". The property under test is
    unchanged: a free-text answer is never BOUND, and it does reach resolution."""
    card = _card(slots_for, "plan_dependency_neighborhood",
                 sub_query="what does it depend on", enumerate_class=_too_many(14))
    assert card["options"] == []
    r = resolve_ask(card, "Wave 1 Cutover")
    assert r.action == RESPEAK
    assert "project_id" not in r.slots                  # NOT bound
    assert r.spoken_answer == "Wave 1 Cutover"          # carried for resolution
    assert r.slot == "project_id"                       # and it knows which slot it answers
    assert r.query == "what does it depend on"          # the phrase, byte-equal
    assert "Wave 1 Cutover" not in r.query              # never concatenated


def test_an_empty_answer_is_not_a_pick(slots_for):
    card = _card(slots_for, "plan_capability_path", enumerate_class=_members(("C1", "Billing")))
    for bad in ("", "   ", None):
        with pytest.raises(PickRefused):
            resolve_ask(card, bad)


def test_validate_pick_refuses_hard_but_suggests_closest(slots_for):
    """Suggest-closest-but-refuse-hard, verbatim from the SPO interview's behaviour: naming
    near misses helps a caller correct itself, and refusing anyway is what stops a model
    smuggling a fabricated pick past the gate."""
    opts = [{"value": "BP1", "label": "Order to Cash"}]
    assert validate_pick("BP1", opts) == "BP1"
    with pytest.raises(PickRefused) as e:
        validate_pick("BP", opts)
    assert "BP1" in str(e.value)


def test_MIRROR_agrees_with_the_spo_interview_it_was_copied_from():
    """PINNED, NOT IMPORTED, and the reason is packaging rather than preference: engine
    images do not ship `iagent_pure` — `ontology_service` mirrors `decode_declarations` for
    exactly this reason and says so — so an import in either direction breaks an image.

    The same trade `SLOT_KINDS` already makes with the planning package. This test is what
    makes the copy honest: both must accept an exact match and both must REFUSE anything
    else, so the two cannot silently diverge on the property that matters."""
    si = pytest.importorskip("agent_fleet.restate_analyst.spo_interview")

    theirs = [{"uri": "idp:Alpha", "label": "Alpha"}, {"uri": "idp:Beta", "label": "Beta"}]
    mine = [{"value": "idp:Alpha", "label": "Alpha"}, {"value": "idp:Beta", "label": "Beta"}]

    assert si.validate_pick("idp:Alpha", theirs) == validate_pick("idp:Alpha", mine)

    with pytest.raises(si.PickRefused):
        si.validate_pick("idp:Gamma", theirs)
    with pytest.raises(PickRefused):
        validate_pick("idp:Gamma", mine)


def test_END_TO_END_a_real_menu_a_validated_pick_and_a_reroute(slots_for):
    """THE WHOLE SERVER-SIDE PATH, on substrate-verified data.

    `process_id` and `tech_id` are the two spoken-mandatory slots whose classes fall UNDER
    the menu bound, so they are the only ones that produce a real menu today — and until
    2026-08-30 nobody had ever asked. Probed live against engine-p's `/enumerate_instances`
    on that date, recorded in `docs/measurements/enumerate-probe-2026-08-30.md`:

        BusinessProcess  -> members, count=2   BP1 "Order to Cash", BP2 "Plan to Produce"
        Technology       -> members, count=5   T1..T5
        Capability       -> too_many, count=9   (bound 8)
        Project          -> too_many, count=14  (bound 8)

    The members below are that response. If the seed changes this test goes stale rather
    than wrong — the assertion is on the PATH, and the provenance is stated so a future
    reader knows which half is measured and which half is composed.

    No corpus case exercises `plan_process_evolution` with an absent slot, so this is
    coverage of a built path rather than evidence of a measured one — the same distinction
    the disambiguation test carries."""
    enumerate_bp = _members(("BP1", "Order to Cash"), ("BP2", "Plan to Produce"))

    # 1. the ask — a real menu, from the substrate
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_process_evolution"),
        resolution={}, enumerate_class=enumerate_bp,
    )
    assert d.action == ASK and d.slot == "process_id"
    assert d.option_source == SRC_ENUMERATION
    assert d.free_text_reason is None            # a menu exists, so free text is FORBIDDEN
    assert [o.value for o in d.options] == ["BP1", "BP2"]

    # 2. the card the surface will render — and the prose that stands in until it exists
    card = ask_card(d, verb_iri="mesh:planProcessEvolution",
                    sub_query="how has it evolved", accepted={})
    assert "Order to Cash" in card["message"]

    # 3. a fabricated answer is REFUSED — the hole this section closed
    with pytest.raises(PickRefused):
        resolve_ask(card, "BP99")

    # 4. a real pick BINDS, and the result is dispatchable as-is
    r = resolve_ask(card, "BP1")
    assert r.action == BIND
    assert r.slots == {"process_id": "BP1"}

    # 5. and the merged slots survive the declaration guard they will actually meet —
    #    `config.slots` outranks the filler, so THIS is what reaches the verb.
    from iagent_pure.slot_acceptance import accept_slots
    acc = accept_slots(r.slots, slots_for("plan_process_evolution"))
    assert acc.params == {"process_id": "BP1"} and not acc.refusals


def test_the_menu_bound_default_agrees_with_the_providers():
    """TWO DEFAULTS OVER ONE ENV VAR, AND THEY MUST NOT DIVERGE.

    `ENUMERATE_MENU_BOUND` is read by the provider (which decides `members` vs `too_many`)
    and by this module (which truncates resolver candidates). The bound is a fact about
    READERS, so it is the same number in both places by definition — and if the defaults
    drift, the disposition and the provider disagree about what a menu IS, silently, in the
    direction of offering a list one of them thinks is too long.

    Pinned rather than shared because the provider lives in an engine package this pure
    module must not import — the same trade as `SLOT_KINDS` and `validate_pick`."""
    from iagent_pure import slot_disposition as pure
    engine = pytest.importorskip("agent_fleet.planning_agent.main")
    assert pure.MENU_BOUND == engine._MENU_BOUND


def test_a_menu_never_offers_the_same_option_TWICE(slots_for):
    """FOUND BY THE ELICITATION CORPUS, run 1. `"what does the Module Build depend on"`
    resolved `mixed` with candidates [P3, P4, P3] and the menu offered P3 twice.

    Every option routed, so menu integrity in its narrow reading held — and a person
    reading "Finance Module Build" twice is looking at a broken menu. The resolver may
    legitimately return one instance more than once (several providers, or one provider
    matching on two fields); making the MENU unique is the consumer's job.

    FIRST OCCURRENCE WINS, because candidates arrive ranked and dropping the earlier copy
    would silently demote a candidate the resolver scored higher."""
    P = IDP + "Project"
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_dependency_neighborhood"),
        resolution={"project_id": {
            "outcome": "mixed", "spoken": "Module Build",
            "candidates": [
                {"instance_id": "P3", "class_uri": P, "label": "Finance Module Build"},
                {"instance_id": "P4", "class_uri": P, "label": "Procurement Module Build"},
                {"instance_id": "P3", "class_uri": P, "label": "Finance Module Build"},
            ],
        }},
        enumerate_class=None,
    )
    values = [o.value for o in d.options]
    assert values == ["P3", "P4"], f"duplicate or reordered: {values}"


# ---------------------------------------------------------------------------------------
# THE CORTEX WALK'S FINDINGS, 2026-09-03 — three producer-side defects a fixture missed
# ---------------------------------------------------------------------------------------

from iagent_pure.slot_disposition import (  # noqa: E402
    SLOT_ELICITATION_URI,
    validate_bound_slots,
)


def test_ABSTAIN_DOES_NOT_WEAR_THE_ASKS_STATUS(slots_for):
    """THE DEFECT THE SEAL WOULD HAVE PASSED THROUGH. `ask_card` emitted
    `status: "slot_elicitation"` for BOTH `ask` and `abstain`, so a surface switching on
    status draws an options field on an abstain — which says *nothing was run and there is
    nothing to choose from*.

    The seal written against it asserted "never renders on a non-ask status" and would have
    been GREEN while the defect shipped, because the status it named does not discriminate the
    case it meant. Two statuses now, so a consumer switching on EITHER `status` or
    `disposition` is correct — the producer's half, which makes the wrong lever unavailable
    rather than merely discouraged."""
    d_abstain = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"),
        resolution={"capability_id": {"outcome": "empty", "spoken": "Nonesuch", "candidates": []}},
        enumerate_class=_members(("C1", "Billing")),
    )
    assert d_abstain.action == ABSTAIN
    abstain_card = ask_card(d_abstain, verb_iri="v", sub_query="q", accepted={})

    d_ask = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"), resolution={},
        enumerate_class=_members(("C1", "Billing")),
    )
    ask = ask_card(d_ask, verb_iri="v", sub_query="q", accepted={})

    assert abstain_card["status"] != ask["status"], "abstain wears the ask's status"
    assert abstain_card["status"] == "slot_abstain"
    assert ask["status"] == "slot_elicitation"
    # and the abstain has nothing to choose from, which is the whole point
    assert abstain_card["options"] == []


def test_the_ask_carries_a_TYPED_SUBJECT_so_an_archetype_can_be_selected(slots_for):
    """Without an output class the ask had no subject, the presentation agent had nothing to
    select an archetype from, and every ask landed on KNOWLEDGE_DOCUMENT — a correct
    disposition rendered as the wrong thing, with nothing broken in either component.

    `mesh:SlotElicitation` is declared `rdfs:subClassOf mesh:Response` in `mesh_system.ttl`,
    which also keeps it out of the grounding pool: response shapes are not subjects anyone
    asks about."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"), resolution={},
        enumerate_class=_members(("C1", "Billing")),
    )
    card = ask_card(d, verb_iri="v", sub_query="q", accepted={})
    assert card["output_uri"] == SLOT_ELICITATION_URI
    assert SLOT_ELICITATION_URI.endswith("#SlotElicitation")


def test_the_too_many_COUNT_is_a_field_and_not_only_prose(slots_for):
    """PRESENCE-IS-NOT-CONTENT IN A FIELD. The count reached the card only inside `message`,
    so a surface wanting to say "14 projects" had to parse an English sentence.

    `truncated_from` did not cover it: that counts what was CUT, and `too_many` cuts nothing
    because the provider returns no members at all. Two different numbers, and the one a
    reader wants was the missing one."""
    d = decide_disposition(
        accepted={}, declared=slots_for("plan_dependency_neighborhood"),
        resolution={}, enumerate_class=_too_many(14),
    )
    assert d.total_count == 14
    assert d.truncated_from == 0, "nothing was truncated — the provider sent no members"
    card = ask_card(d, verb_iri="v", sub_query="q", accepted={})
    assert card["total_count"] == 14


# ---------------------------------------------------------------------------------------
# bound_slots — the BIND transport's server half
# ---------------------------------------------------------------------------------------

def test_bound_slots_are_validated_against_a_RECOMPUTED_menu(slots_for):
    """The menu is recomputed rather than echoed or held. A client that can send the pick can
    send a menu permitting it, so an echo is self-certifying; holding it between turns is the
    lifetime the stateless re-route exists to avoid."""
    ok, refused, _res = validate_bound_slots(
        {"capability_id": "C2"}, declared=slots_for("plan_capability_path"),
        enumerate_class=_members(("C1", "Billing"), ("C2", "Invoicing")),
    )
    assert ok == {"capability_id": "C2"} and refused == []


def test_a_bound_slot_NOT_on_the_recomputed_menu_is_refused(slots_for):
    ok, refused, _res = validate_bound_slots(
        {"capability_id": "C99"}, declared=slots_for("plan_capability_path"),
        enumerate_class=_members(("C1", "Billing"), ("C2", "Invoicing")),
    )
    assert ok == {} and refused and "C99" in refused[0]


def test_a_bound_slot_with_NO_MENU_is_refused_rather_than_trusted(slots_for):
    """THE GAP IS DELIBERATE AND THIS IS THE TEST THAT SAYS SO. A `too_many` class offered
    nothing, so nothing can be validated as having been offered. Accepting it here would be
    the fabricated-pick hole with an extra hop; free text belongs on the RESPEAK path, where
    the value re-enters as words and the resolver adjudicates it."""
    ok, refused, _res = validate_bound_slots(
        {"project_id": "P5"}, declared=slots_for("plan_dependency_neighborhood"),
        enumerate_class=_too_many(14),
    )
    assert ok == {}
    assert refused and "no_menu" in refused[0]


def test_bound_slots_cannot_reach_a_route_supplied_slot(slots_for):
    """The boundary `accept_slots` exists for, restated at this new door: a caller supplying
    `baseline_state` is not answering an ask, they are supplying the evidence the answer is
    computed from."""
    ok, refused, _res = validate_bound_slots(
        {"baseline_state": "anything"}, declared=slots_for("plan_diff"), enumerate_class=None,
    )
    assert ok == {} and refused and "route-supplied" in refused[0]


def test_bound_slots_fail_CLOSED_on_unreadable_declarations():
    ok, refused, _res = validate_bound_slots({"x": "y"}, declared="not json", enumerate_class=None)
    assert ok == {} and refused


def test_the_fallback_renders_the_ask_rather_than_silence(slots_for):
    """THE REGRESSION STAMPING THE CLASS INTRODUCED, sealed against the REAL composer's source.

    `output_uri` made the presentation agent select on it — the fix — and until ELICITATION is
    admitted, selection lands on KNOWLEDGE_DOCUMENT. That fallback composes its body from
    fields on the expert_response and emits the literal "No content available." when it finds
    none. The card emitted none, so the interim was WORSE than the state it replaced: before
    the stamp a user saw "Which program?", after it they saw an empty card. An unregistered
    kind must degrade VISIBLY; this degraded to silence.

    READ FROM THE COMPOSER'S SOURCE, NOT FROM A LIST HERE, and not by importing it either:
    `presentation_agent/main.py` needs `baml_client`, which is not importable from the repo
    root, and the finance suite already reads this same module as text for the same reason.

    The field names are EXTRACTED from `agent_response.get(...)` in the composer, so if it
    ever reads a different key this test fails instead of passing against a stale copy. A
    test asserting `"summary" in card` would be asserting on my own restatement of someone
    else's contract — the mirror problem, in a seal."""
    import ast as _ast
    import pathlib as _pathlib

    src = (_pathlib.Path(__file__).resolve().parents[2]
           / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    fn = next((n for n in _ast.walk(tree)
               if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
               and "No content available" in _ast.dump(n)), None)
    assert fn is not None, "the KNOWLEDGE_DOCUMENT composer moved — find it before trusting this"

    read_keys = {
        node.args[0].value
        for node in _ast.walk(fn)
        if isinstance(node, _ast.Call)
        and isinstance(node.func, _ast.Attribute) and node.func.attr == "get"
        and isinstance(node.func.value, _ast.Name) and node.func.value.id == "agent_response"
        and node.args and isinstance(node.args[0], _ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert read_keys, "could not extract the fields the fallback reads"

    d = decide_disposition(
        accepted={}, declared=slots_for("plan_capability_path"), resolution={},
        enumerate_class=_members(("C1", "Billing"), ("C7", "Integration Platform")),
    )
    card = ask_card(d, verb_iri="mesh:planCapabilityPath",
                    sub_query="what is the capability path", accepted={})

    # The composer ORs its text fields, so supplying ANY one of them is enough to avoid
    # "No content available." — but at least one must be non-empty, which is the property.
    text_keys = {k for k in read_keys if "summary" in k or "text" in k}
    assert text_keys, f"the fallback reads no text field? extracted {sorted(read_keys)}"
    assert any(card.get(k) for k in text_keys), (
        f"the ask supplies none of {sorted(text_keys)} — it would render "
        f"'No content available.' Card keys: {sorted(card)}"
    )
    # and the structured half, so the fenced block carries the options rather than nothing
    for k in read_keys - text_keys:
        assert card.get(k), f"the ask supplies no {k!r}, so the fallback's block is empty"
    assert "C7" in json.dumps(card["structured_data"]), "the options are not in the block"
