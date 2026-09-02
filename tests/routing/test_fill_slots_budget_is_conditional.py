"""A MANDATORY SLOT DOES NOT REFINE, so its extraction budget cannot be the refinement one.

THE DEFECT (measured 2026-09-02, work cluster). The `/fill_slots` budget was one number, 20s,
justified by a comment that reads: "a slot REFINES a question that will still be answered
without it, so a slow extractor must cost the user a default, never a timeout."

True for spoken-OPTIONAL. **Exactly inverted for spoken-MANDATORY** — without the slot the verb
cannot run, so a timeout does not cost a default, it converts a fully-specified question into
an elicitation.

    "why are we over budget on Notional Program Meridian"
      -> routed finVarianceAnalysis 0.96
      -> engine-o extracted program_id="Notional Program Meridian" at 0.95, 200 OK
      -> supervisor had already given up at 20s
      -> user asked "which Program?" about a question that named the program

Every Engine F verb has a spoken-mandatory slot, so all six became asks and no card drew. The
extraction was CORRECT and ARRIVED; the caller had stopped listening. See
docs/plans/a-mandatory-slot-does-not-refine.md.

THE RULING: conditional budget on the routed verb's own slot census. Derived from the
declarations the verb already publishes, so a verb that gains a mandatory slot gets the longer
budget with no second place to update.

WHAT THIS FILE DOES NOT CLAIM. A longer budget makes the timeout rare; it does not make `{}`
honest. A genuine failure still returns the same empty dict as a successful extraction from a
question that named nothing — identical shape, opposite meaning. That is a change to the ask
disposition's input, not to this budget, and the last test here pins the boundary so the
residue is not mistaken for fixed.

Run: uv run --frozen pytest tests/routing/test_fill_slots_budget_is_conditional.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.defs.dynamic_supervisor import (  # noqa: E402
    _FILL_SLOTS_TIMEOUT_MANDATORY_S,
    _FILL_SLOTS_TIMEOUT_S,
    _fill_slots_budget,
)


def _slot(name, kind, **extra):
    return {"name": name, "kind": kind, "type": "str", **extra}


# ── the census ──────────────────────────────────────────────────────────────

def test_a_spoken_mandatory_slot_buys_the_long_budget():
    """THE REGRESSION. Engine F's shape: one slot the speaker must name."""
    decls = [_slot("program_id", "spoken-mandatory", referent="fin:Program")]
    assert _fill_slots_budget(decls) == _FILL_SLOTS_TIMEOUT_MANDATORY_S


def test_all_optional_slots_keep_the_short_budget():
    """Engine P's planSchedule shape. The original reasoning is SOUND here and must survive —
    a verb that runs fine on defaults should not make a user wait."""
    decls = [_slot("scope_initiative_id", "spoken-optional"),
             _slot("group_by", "spoken-optional", default="initiative")]
    assert _fill_slots_budget(decls) == _FILL_SLOTS_TIMEOUT_S


def test_one_mandatory_among_many_optional_is_enough():
    """The census is ANY, not majority: one un-runnable slot makes the whole call
    un-runnable, however many optional ones surround it."""
    decls = [_slot("a", "spoken-optional"), _slot("b", "spoken-optional"),
             _slot("c", "spoken-mandatory"), _slot("d", "spoken-optional")]
    assert _fill_slots_budget(decls) == _FILL_SLOTS_TIMEOUT_MANDATORY_S


def test_route_supplied_kinds_do_NOT_buy_the_long_budget():
    """THE ONE THAT WOULD QUIETLY WIDEN IT. `handle` and `ceremony` are resolved by the
    dispatcher from the store — no speaker ever names them, so a slow extractor cannot make a
    question un-runnable for want of one. Counting them would give every verb the long budget
    and silently undo the conditionality."""
    decls = [_slot("baseline_state", "handle"), _slot("scenario_name", "ceremony")]
    assert _fill_slots_budget(decls) == _FILL_SLOTS_TIMEOUT_S


# ── degradation, in the conservative direction ──────────────────────────────

def test_absent_or_unreadable_declarations_fall_back_to_the_SHORT_budget():
    """Conservative, matching every other degradation on this path. An unknown census must
    not buy the long budget — that would make the exception the default."""
    for decls in (None, [], "not-a-list", [None], [{"no": "kind"}], 42):
        assert _fill_slots_budget(decls) == _FILL_SLOTS_TIMEOUT_S, decls


# ── the boundary this change does NOT cross ─────────────────────────────────

def test_the_long_budget_is_longer_than_the_short_one():
    """Trivial, and worth pinning: an env override that inverted them would restore the
    defect while every other test here still passed."""
    assert _FILL_SLOTS_TIMEOUT_MANDATORY_S > _FILL_SLOTS_TIMEOUT_S


def test_the_budget_exceeds_the_observed_failure():
    """The measurement that produced this fix: a correct extraction returned AFTER 20s. A
    budget that did not clear the observed case would be a number chosen for comfort."""
    assert _FILL_SLOTS_TIMEOUT_MANDATORY_S > 20.0
