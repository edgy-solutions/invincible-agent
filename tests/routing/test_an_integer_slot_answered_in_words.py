"""A SPOKEN ANSWER IS TEXT — an integer slot must not reach a measure as a string.

MEASURED 2026-09-08, walking the first INTEGER slot this system has ever been asked. Every
prior walk used string slots (`capability_id: "C8"`, `program_id: "NP-MERIDIAN"`), so this
had never fired.

`lot` is declared `{"name": "lot", "type": "integer", "kind": "spoken-mandatory"}`. The typed
answer "1" travelled to engine-cost unchanged; its model is a dict keyed by int, so
`lots["1"]` raised KeyError and the card read:

    Refused: not_in_model
    Reason: lot 1 is not in the model; known lots are [1, 2, 3, 4, 5, 6, 7, 8, 9].

**A refusal that lists the value it just rejected.** Accurate from inside the code — the
types are invisible in the message — and nonsense to a reader, who then goes looking for a
data problem that does not exist. That is the expensive part: not the failure, the direction
it sends someone.

THE COERCION QUESTION, because this module deliberately refuses to coerce elsewhere. The
collection case declines to wrap a bare string as `[value]` because that GUESSES AT STRUCTURE
and the guess is wrong the moment a speaker names two periods. `int("1")` guesses at nothing.
So the two cases genuinely differ, and the tests below assert that they differ rather than
asserting each in isolation.

Run: uv run --frozen pytest tests/routing/test_an_integer_slot_answered_in_words.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent_pure.slot_acceptance import WRONG_SHAPE, accept_slots  # noqa: E402

_INT_DECL = [{"name": "lot", "type": "integer", "required": True, "kind": "spoken-mandatory"}]
_LIST_DECL = [{"name": "periods", "type": "list[str]", "required": True,
               "kind": "spoken-mandatory"}]


# ── the three outcomes, called rather than grepped ──────────────────────────

def test_an_integral_string_is_parsed():
    """THE DEFECT. "1" and 1 are the same answer; only one of them indexes the model."""
    a = accept_slots({"lot": "1"}, _INT_DECL)
    assert a.params == {"lot": 1}
    assert [r.reason for r in a.refusals] == []
    assert isinstance(a.params["lot"], int), "still a string — the engine will KeyError"


def test_surrounding_whitespace_and_negatives_are_handled():
    """A person typing into a box produces both."""
    assert accept_slots({"lot": "  7 "}, _INT_DECL).params == {"lot": 7}
    assert accept_slots({"lot": "-3"}, _INT_DECL).params == {"lot": -3}


def test_a_non_integral_string_is_REFUSED_not_guessed():
    """The third value. Passing it through is what produced a self-contradicting refusal from
    the engine; guessing at it would be worse."""
    for bad in ("abc", "1.0", "1_000", "", "  "):
        a = accept_slots({"lot": bad}, _INT_DECL)
        assert a.params == {}, f"{bad!r} was accepted"
        assert [r.reason for r in a.refusals] == [WRONG_SHAPE], f"{bad!r} refused wrongly"


def test_float_and_underscore_forms_are_refused_on_purpose():
    """`.isdigit()` rather than try/except around `int()`. A lot number is an IDENTIFIER, not
    an arithmetic expression: `int("1_000")` silently returns 1000 and `int("１")` accepts a
    full-width digit. Both would be the router deciding what someone meant."""
    assert accept_slots({"lot": "1_000"}, _INT_DECL).params == {}
    assert accept_slots({"lot": "1.0"}, _INT_DECL).params == {}


def test_a_value_that_is_ALREADY_an_int_is_untouched():
    """The control on the coercion itself. An API caller supplying the right type must not be
    re-parsed, and a rule that only worked on strings would break them."""
    a = accept_slots({"lot": 4}, _INT_DECL)
    assert a.params == {"lot": 4} and not a.refusals


# ── the choice, and the fixture that distinguishes it ───────────────────────

def test_INTEGERS_COERCE_WHERE_COLLECTIONS_REFUSE():
    """THE CHOICE THIS FILE DEFENDS, asserted so that the fixture can tell it from the
    alternative — `invincible-agent-91`'s technique: a seal defending "this rule rather than
    the obvious one" must show its own data separates the two.

    The obvious alternative is a single uniform rule — coerce everything, or refuse
    everything. This asserts they DIVERGE on the same input shape: a bare string given to an
    integer slot is parsed, and a bare string given to a collection slot is refused.

    They diverge because the reasons differ. `[value]` invents a structure and is wrong the
    moment someone names two periods; `int("1")` invents nothing. If a future change made
    both behave alike, one of those two arguments has been lost and this goes red.
    """
    as_int = accept_slots({"lot": "1"}, _INT_DECL)
    as_list = accept_slots({"periods": "FY26-Q4"}, _LIST_DECL)

    assert as_int.params == {"lot": 1}, "the integer rule stopped coercing"
    assert as_list.params == {}, "the collection rule started coercing"
    # the control on the choice: same input SHAPE, opposite outcomes
    assert bool(as_int.refusals) != bool(as_list.refusals), (
        "both slot kinds now behave identically for a bare string — the distinction between "
        "guessing at structure and parsing a number has collapsed"
    )
