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
