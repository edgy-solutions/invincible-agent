"""`lot` bound to 3, `rate_vintage` asked: exactly two chips, scoped by lot.

TWO CHANGES, ONE CLAIM, AND THIS IS THE SEAL THAT KEEPS THEM TOGETHER. `rate_vintage` had no
`referent` in `agent_fleet/cost_agent/slots.py`, so the disposition never enumerated it at all
— no referent, no option ladder, no chips, full stop. Giving it a referent alone would reach
the ladder and draw the CLASS-WIDE menu (`test_the_vintage_menu_is_scoped_to_the_lot.py`'s
whole point): twelve ids in the form `<fy>-<vintage>` against a slot that accepts a bare
`<vintage>`, refused by the verb on ten of twelve picks. `narrowed_by: ["lot"]` is what lets
`slot_disposition.decide_disposition` tell a SCOPED menu from a class-wide one wearing its
clothes — the comparison is `declared_scope ∩ offered` against the provider's own `scoped_by`.

Both halves are read from the fleet's real declaration, not restated here:

    referent     `slots._REFERENT_KIND["rate_vintage"]`
    narrowed_by  `slots._NARROWED_BY["rate_vintage"]`, itself derived from
                 `instances._SCOPED_BY_SLOT[COST+"RateTable"]` — one source, so a lot that
                 stops scoping, or a class that stops being enumerable, moves every reader at
                 once instead of leaving this file's expectation stale.

THE ENUMERATOR IS A THIN ADAPTER, NOT A DOUBLE. `tests/routing/test_a_menu_says_what_scoped_it`
proves the DISPOSITION's half of the contract against a scripted body; this file proves the
whole chain from `slots.slots_for` through the REAL `instances.enumerate_class` against the
REAL seeded state (`seed.build_state()`) reaches the same two chips `measures.options_for`
would accept — the same join `test_the_scoped_menu_and_the_ROUTE_agree_about_what_is_available`
makes for the HTTP route, made here for the in-process disposition path.

Run: uv run pytest tests/cost/test_lot_3_offers_exactly_two_vintage_chips.py -v
"""
from __future__ import annotations

import pytest

from agent_fleet.cost_agent import instances, measures, slots
from agent_fleet.cost_agent.seed import build_state, check_consistency
from iagent_mesh.graph_manifest import SlotDecl
from iagent_pure.slot_disposition import ASK, FT_CLASS_WIDE, SRC_ENUMERATION, decide_disposition

RATE_TABLE = "http://invincible-agent/cost#RateTable"

#: Lot 3 is fiscal year 2021. Read from the engine's own computation rather than typed twice —
#: `test_the_vintage_menu_is_scoped_to_the_lot.LOT_3_VINTAGES` writes the literal deliberately,
#: as the fixture that would catch a seed change; this file instead asserts the DISPOSITION
#: agrees with `options_for`, which is the join this seal exists to make.
LOT = 3


@pytest.fixture(scope="module")
def state():
    s = build_state()
    check_consistency(s)
    return s


def _real_enumerator(state):
    """`class_uri, bound_slots -> provider body`, calling the REAL `instances.enumerate_class`
    on the REAL seeded state. Not a double: the whole point is that nothing between
    `slots_for`'s declaration and the engine's own enumeration door is scripted."""
    def _call(class_uri: str, *, bound_slots=None) -> dict:
        return instances.enumerate_class(state, class_uri, bound_slots=bound_slots)
    return _call


def _class_wide_enumerator(state):
    """THE CONTROL (arm d): a provider that answers the class whole, ignoring `bound_slots`
    entirely and never setting `scoped_by` — exactly what engine-cost looked like before
    `instances._SCOPED_BY_SLOT` existed, and exactly what a provider ignoring the slot still
    looks like today. If `narrowed_by` ever stopped doing its job, THIS is the enumerator that
    would start drawing a menu again."""
    def _call(class_uri: str, *, bound_slots=None) -> dict:
        members = instances.members_of(state, class_uri)
        return {"outcome": "members", "members": members, "count": len(members)}
    return _call


def _mandatory_rate_vintage_verbs() -> list[str]:
    """EVERY verb where `rate_vintage` is spoken-mandatory, derived from the declarations
    `slots_for` actually emits — not a literal list of three names. `decide_disposition` only
    ever asks about a `spoken-mandatory` slot (`mandatory_slots` filters on `kind`), so a verb
    declaring `rate_vintage` `spoken-optional` (`cost_rate_assumptions`) is correctly excluded:
    walking it here would assert a chip count for a turn that never asks."""
    out = []
    for fn_name in measures.VERBS:
        for decl in slots.slots_for(fn_name):
            if decl["name"] == "rate_vintage" and decl["kind"] == "spoken-mandatory":
                out.append(fn_name)
    return out


def test_the_mandatory_population_is_not_a_sample():
    """THE FLOOR. If the derivation above ever matched nothing, every parametrised arm below
    would pass over an empty set and report green for a seal that asserted nothing."""
    verbs = _mandatory_rate_vintage_verbs()
    assert verbs, "no verb declares rate_vintage spoken-mandatory — the derivation broke"
    assert set(verbs) == {"cost_lot_breakdown", "cost_rate_comparison", "cost_price_composition"}, (
        f"the mandatory population is {sorted(verbs)}; FACTS said these three by name — a "
        f"fourth or a missing one is a decision, not a silent pass"
    )


@pytest.mark.parametrize("fn_name", _mandatory_rate_vintage_verbs())
def test_lot_3_asks_rate_vintage_with_exactly_the_two_vintages(fn_name, state):
    """Arm (a)/(b): drive the real disposition with the real declarations for every verb that
    declares `rate_vintage` mandatory, `lot` already bound to 3."""
    decls = slots.slots_for(fn_name)
    accepted = {"lot": "3"}

    # THE DECLARED SCOPE, CHECKED DIRECTLY — the real provider in `instances.py` already
    # narrows by lot on its own, so the chip assertions below would stay green even with
    # `narrowed_by` missing from the declaration (that is what the CLASS-WIDE CONTROL below
    # is for). The declaration is the half this arm is actually sealing: without it, a
    # provider that ever stops scoping is a class-wide menu nothing refuses.
    rv_decl = next(d for d in decls if d["name"] == "rate_vintage")
    assert rv_decl.get("narrowed_by") == ["lot"], (
        f"{fn_name}: rate_vintage declares narrowed_by={rv_decl.get('narrowed_by')!r}, not "
        f"['lot'] — the scope is not recorded on the declaration"
    )

    disp = decide_disposition(
        accepted=accepted, declared=decls, enumerate_class=_real_enumerator(state),
    )

    expected = measures.options_for(state, fn_name, "rate_vintage", {"lot": LOT})
    assert expected is not None, f"{fn_name}: the engine cannot compute lot 3's vintages at all"

    assert disp.action == ASK, f"{fn_name}: expected an ask, got {disp.action!r} ({disp!r})"
    assert disp.slot == "rate_vintage", f"{fn_name}: asked about {disp.slot!r}, not rate_vintage"
    ids = [o.value for o in disp.options]
    assert ids == list(expected), (
        f"{fn_name}: the ask offers {ids}, and the engine computes {list(expected)} for lot 3"
    )
    assert ids == ["2021-02-01", "2021-08-01"], (
        f"{fn_name}: expected exactly the two lot-3 vintages, got {ids}"
    )
    assert disp.option_source == SRC_ENUMERATION, (
        f"{fn_name}: options came from {disp.option_source!r}, not the enumeration door"
    )
    assert disp.scoped_by == ("lot",), (
        f"{fn_name}: scoped_by is {disp.scoped_by!r} — the menu must record that IT was the "
        f"slot that narrowed it"
    )


def test_the_opening_turn_asks_for_lot_not_rate_vintage(state):
    """Arm (c). `lot` precedes `rate_vintage` in every verb signature and both are mandatory,
    so on an empty turn the FIRST unfilled mandatory slot is `lot` — the ask must not jump ahead
    to a slot whose scoping input was never supplied."""
    decls = slots.slots_for("cost_rate_comparison")

    disp = decide_disposition(
        accepted={}, declared=decls, enumerate_class=_real_enumerator(state),
    )

    assert disp.action == ASK
    assert disp.slot == "lot", f"the opening ask is for {disp.slot!r}, not lot"


def test_an_enumerator_blind_to_bound_slots_draws_no_chips(state):
    """Arm (d), THE CONTROL. A provider that enumerates the class whole and never reports
    `scoped_by` must be refused by `decide_disposition`'s class-wide guard — `cost#RateTable`
    holds more members than lot 3 accepts, in a form (`<fy>-<vintage>`) the verb refuses
    outright, so a menu built from it would be worse than free text."""
    decls = slots.slots_for("cost_rate_comparison")

    disp = decide_disposition(
        accepted={"lot": "3"}, declared=decls, enumerate_class=_class_wide_enumerator(state),
    )

    assert disp.action == ASK
    assert disp.slot == "rate_vintage"
    assert disp.options == (), (
        f"a class-wide enumerator produced chips ({disp.options!r}); the class-wide guard did "
        f"not fire"
    )
    assert disp.free_text_reason == FT_CLASS_WIDE, (
        f"free_text_reason is {disp.free_text_reason!r}, not {FT_CLASS_WIDE!r} — a class-wide "
        f"answer to a scoped slot must be named, not silently accepted as a menu"
    )


@pytest.mark.parametrize("fn_name", list(measures.VERBS))
def test_every_referent_carrying_slot_validates_through_the_sdk(fn_name):
    """Arm (e). `iagent_mesh.graph_manifest.SlotDecl` (pinned SDK v0.9.5) is the runtime guard
    for both fields this file depends on: a referent only legal on a spoken slot, and
    `narrowed_by` forbidding an empty list. Every declaration this engine emits — not only
    `rate_vintage`'s — must construct one without raising."""
    for decl in slots.slots_for(fn_name):
        SlotDecl(**decl)  # raises on an ill-formed declaration; the assertion IS the call
