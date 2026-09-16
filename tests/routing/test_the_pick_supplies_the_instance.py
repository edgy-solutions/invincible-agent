"""ASK, BIND, DISPATCH — the picked instance must make the turn instance-shaped.

MEASURED 2026-09-14, the empty `finProgramBrief` card. The sequence was ask (correct, rendered,
one option offered) -> pick -> a `failed` artifact, 0 bytes, 191 ms, with

    resolved_intent  {"refused_slots": [], "accepted_slots": {"program_id": "NP-MERIDIAN"}}
    excluded         [{"uri": "mesh:finProgramBrief", "gate": "arity", ...}]

**The slot the ask was asking for was bound, and the verb was then flagged `needs_instance`.**

WHERE IT COMES FROM, and it is not the gate. `_pre_resolved_from_ask` builds the pick's route
from **the ask artifact's** `resolved_intent`, copying `subject_instance_id` straight out of it.
The ask is by construction the turn where no instance was named, so that field is necessarily
empty there — and it rides forward onto the turn that finally supplies one. The picked value
goes to the chain's bound slots, which nothing promotes. `query_is_set = not subject_instance_id`
therefore reports SET on the answer turn, forever.

THIS IS NOT SPECIFIC TO A GRAPH VERB. Any verb with `arity: single` answered through an ask is
reached by the same path — the graph host only surfaced it because both its ratified rows force
`arity: single` (a required referent slot). The blast radius is the routing path, not an engine.

── WHY THE CONTROL IS THE TEST ─────────────────────────────────────────────────────────────
    defect:   the referent slot IS bound (the pick)      -> must NOT flag
    control:  nothing is bound (the original ask)        -> MUST flag

Without the second, every assertion here is satisfied by a rule that never flags anything —
which would restore the H06 defect this gate was rewritten to fix, while looking like a pass.

Run: uv run --frozen pytest tests/routing/test_the_pick_supplies_the_instance.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from iagent_pure.verb_eligibility import filter_verbs_by_arity, turn_is_set_shaped

_ROW = _REPO / "policy" / "graphs" / "fin_program_brief.yaml"


def _verb_from_the_ratified_row() -> dict:
    """The compat record as the routing path sees it, built FROM THE SHIPPED ROW.

    Not a hand-written fixture: the claim is about this verb's declared contract, and a
    fixture that invented its own slots could agree with a rule that disagrees with the row.
    `slots` arrives as JSON TEXT because a Neo4j property may not be a list of maps — the
    same projection `decode_declarations` exists to undo.
    """
    row = yaml.safe_load(_ROW.read_text(encoding="utf-8"))
    return {
        "verb_iri": row["verb"],
        "arity": row["arity"],
        "slots": json.dumps(row["slots"]),
    }


def test_the_row_still_forces_single_arity():
    """If this row stops being single-arity the rest of the file proves nothing — it would
    pass against a gate that never flags, because there would be nothing to flag."""
    v = _verb_from_the_ratified_row()
    assert v["arity"] == "single", f"the subject of this seal is no longer single-arity: {v}"
    referents = [
        s for s in yaml.safe_load(_ROW.read_text(encoding="utf-8"))["slots"]
        if s.get("referent") and s.get("required")
    ]
    assert referents, "no required referent slot — the instance has no declared carrier"


# ── the control, first, because it is what gives the defect test meaning ────────────────

def test_the_ASK_turn_IS_set_shaped():
    """THE POSITIVE CONTROL. The original ask names no instance and binds nothing, so the
    verb must still be flagged — otherwise the gate has simply stopped working and the H06
    defect (a set query dispatching to a single-asset verb) comes back."""
    v = _verb_from_the_ratified_row()
    assert turn_is_set_shaped("", v, set()) is True

    kept, flagged = filter_verbs_by_arity([v], turn_is_set_shaped("", v, set()))
    assert [f["verb_iri"] for f in flagged] == [v["verb_iri"]], (
        "the ask turn did not flag a single-arity verb whose instance was never named"
    )
    assert kept and kept[0].get("needs_instance") is True


# ── the defect ─────────────────────────────────────────────────────────────────────────

def test_the_PICK_turn_is_NOT_set_shaped():
    """THE LOAD-BEARING ROW. `program_id` is the slot the ask asked for and the pick bound."""
    v = _verb_from_the_ratified_row()
    bound = {"program_id"}

    assert turn_is_set_shaped("", v, bound) is False, (
        "the turn that bound the verb's required referent slot still reads as SET. This is "
        "the measured defect: the verb is flagged needs_instance FOR THE REASON THE ASK HAD "
        "JUST BEEN ANSWERED."
    )

    _kept, flagged = filter_verbs_by_arity([v], turn_is_set_shaped("", v, bound))
    assert flagged == [], f"the picked instance did not clear the arity flag: {flagged}"


def test_a_DIRECTLY_resolved_instance_still_clears_it():
    """The path that already worked must keep working — a question naming the instance
    outright never reached the ask at all."""
    v = _verb_from_the_ratified_row()
    assert turn_is_set_shaped("NP-MERIDIAN", v, set()) is False


# ── what must NOT satisfy it ───────────────────────────────────────────────────────────

def test_binding_a_NON_REFERENT_slot_does_not_supply_an_instance():
    """Otherwise the rule degrades to "any bound slot means instance-shaped", which would
    dispatch a single-asset verb against a set query the moment an optional filter was
    filled — the exact silent dispatch the gate exists to prevent."""
    v = {
        "verb_iri": "mesh:finProgramBrief",
        "arity": "single",
        "slots": json.dumps([
            {"name": "program_id", "required": True,
             "referent": "http://invincible-agent/fin#Program"},
            {"name": "fiscal_year", "required": False, "type": "string"},
        ]),
    }
    assert turn_is_set_shaped("", v, {"fiscal_year"}) is True


def test_unknown_bound_slots_are_not_read_as_an_instance():
    """`None` means "nothing known to be bound". Every other gate fails in this direction."""
    v = _verb_from_the_ratified_row()
    assert turn_is_set_shaped("", v, None) is True


# ── THE SECOND CALLER — an engine with a CATALOGUE, not a ratified row ──────────────────
#
# A fix on a shared path asserted on one caller is asserted on a SAMPLE. `finProgramBrief`
# gets its declarations from `policy/graphs/*.yaml`; engine-cost derives its own from a
# signature. If the rule only works for one of those, it works for the caller I happened to
# measure.
#
# AND THE SECOND CALLER FOUND SOMETHING THE FIRST COULD NOT. See the arity census below.

def _cost_lot_verb_slots() -> list[dict]:
    """The REAL declarations engine-cost registers, from the engine's own module."""
    import sys as _sys
    if str(_REPO) not in _sys.path:
        _sys.path.insert(0, str(_REPO))
    from agent_fleet.cost_agent import slots as cost_slots

    return cost_slots.slots_for("cost_lot_breakdown")


def test_the_rule_holds_for_a_CATALOGUE_sourced_verb():
    """Same rule, a different declaration SOURCE and a different slot TYPE.

    `program_id` is a string from a ratified row; `lot` is an INTEGER derived from a Python
    signature. A rule that happened to depend on either would pass one and fail the other.

    ARITY IS SUPPLIED BY THIS TEST, and that is not cosmetic — see the census below. Engine-cost
    does not declare arity at all, so this row proves the RULE for a catalogue-sourced verb and
    does NOT prove the live path for engine-cost. Those are different claims and the next test
    is what keeps them apart.
    """
    decls = _cost_lot_verb_slots()
    lot = next((d for d in decls if d["name"] == "lot"), None)
    assert lot is not None, f"engine-cost's lot slot is gone: {decls}"
    assert lot.get("required") and lot.get("referent"), (
        f"lot is no longer a required referent — this caller no longer exercises the rule: {lot}"
    )

    verb = {"verb_iri": "mesh:costLotBreakdown", "arity": "single",
            "slots": json.dumps(decls)}

    assert turn_is_set_shaped("", verb, {"lot"}) is False, (
        "the picked lot did not make the turn instance-shaped for a catalogue-sourced verb"
    )
    # The control travels with it, exactly as for the first caller.
    assert turn_is_set_shaped("", verb, set()) is True


def test_engine_cost_DECLARES_NO_ARITY_so_its_live_half_is_dark():
    """THE CENSUS, and it is why the test above hand-supplies `arity`.

    MEASURED 2026-09-14 at the registration site, not by the absence of a function name:
    `agent_fleet/utils/mesh_registration.py` takes `arity: Optional[str] = None`, and
    engine-cost's `register_engine_to_mesh(...)` call in `cost_agent/main.py` does not pass it.
    All six cost verbs therefore register `arity = null`, which `filter_verbs_by_arity` reads as
    "never flag".

        planning_agent   HAS arity_for   -> declares arity
        graph_host       ratified row    -> declares arity
        cost_agent       none            -> null
        finance_agent    none            -> null
        safety_agent     none            -> null

    **So the arity gate is inert for three of the four engines** — six cost verbs carry a
    REQUIRED REFERENT slot (`lot`) and none of them can ever be flagged `needs_instance`. The
    ask/pick defect this file seals is invisible there, not absent: the slot layer still asks,
    so it degrades to the pre-flag behaviour rather than failing loudly.

    THIS TEST FAILS WHEN SOMEONE FIXES THAT, deliberately. The day engine-cost declares arity,
    the row above should stop hand-supplying it and read the real value — otherwise it quietly
    becomes a test of a literal the system does not emit, which is the defect
    `DISPOSAL_REMOVED`'s own docstring records one module over.

    ── AND DECLARING ARITY HERE SWITCHES ON TWO BEHAVIOURS, NOT ONE ─────────────────────────
    Read this before adding `arity_for` to engine-cost. One line will enable, for all six
    verbs at once:

      1. THE FLAG. `filter_verbs_by_arity` starts marking them `needs_instance` on set-shaped
         turns — the ask this seal exists for, which is the intended gain.
      2. THE PROMOTION, and its reach is wider. The pick's referent binding is promoted into
         `subject_instance_id`, which `dynamic_supervisor.py:1679-1690` threads onto the
         GENERALIST FALLBACK as `resolved_instance_id` — the branch whose own log line says
         "Engine A will NOT re-resolve". Verified at that line 2026-09-14, not taken on
         report.

    The promotion is gated on the declaration precisely so three engines do not acquire (2) as
    a side effect of a fourth being fixed. Declaring arity opts this engine in to BOTH. That is
    the right trade — but it is a routing change on six verbs, not a slot annotation, and it
    should be made deliberately rather than discovered in a diff.

    Re-run the census:
        grep -rn "def arity_for" agent_fleet/*/slots.py
        grep -n "arity=" agent_fleet/cost_agent/main.py
    """
    import sys as _sys
    if str(_REPO) not in _sys.path:
        _sys.path.insert(0, str(_REPO))
    from agent_fleet.cost_agent import slots as cost_slots

    assert not hasattr(cost_slots, "arity_for"), (
        "engine-cost now derives arity. GOOD — two things follow. (1) Delete the "
        'hand-supplied `"arity": "single"` in '
        "test_the_rule_holds_for_a_CATALOGUE_sourced_verb and read the declared value, so "
        "that row tests what the engine actually registers. (2) Confirm the six verbs were "
        "meant to opt in to the INSTANCE PROMOTION as well as the flag — it reaches the "
        "generalist fallback, where Engine A stops re-resolving. See this test's docstring."
    )
    main_src = (_REPO / "agent_fleet" / "cost_agent" / "main.py").read_text(encoding="utf-8")
    assert "arity=" not in main_src, (
        "engine-cost's registration now passes arity. GOOD — the live half of this seal "
        "becomes provable for a second engine. Check the promotion consequence in this "
        "test's docstring before shipping: six verbs gain it at once."
    )
