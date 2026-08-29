"""The battery's outcome classifier — the part that must be right before any corpus runs.

WHY THIS IS TESTED HARD AND SEPARATELY. The corpus run produces the number that answers "how
reliable is your routing". If the classifier is wrong, that number is wrong in a way nobody
can see: a wrong fill counted as a miss makes the silent-wrong-answer mode look recoverable,
and a miss counted as correct makes the whole battery decorative.

The classifier is pure, so it can be exercised exhaustively without a model — which is the
same split the rest of this arc uses: prove the deterministic parts, measure the model.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "slot_fill_battery",
    pathlib.Path(__file__).resolve().parents[2] / "scripts" / "slot_fill_battery.py",
)
battery = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(battery)

CORRECT, MISSED, WRONG, EXTRA = (battery.CORRECT, battery.MISSED,
                                 battery.WRONG, battery.EXTRA)


def cls(expected, got):
    return battery.classify(expected, got)[0]


# ── the four classes ─────────────────────────────────────────────────────────

def test_exact_match_is_correct():
    assert cls({"group_by": "initiative"}, {"group_by": "initiative"}) == CORRECT


def test_nothing_expected_and_nothing_filled_is_correct():
    """The case that catches INVENTION, and a corpus without it measures only eagerness.
    "where is funding short" names no parameter; filling one is not a bonus."""
    assert cls({}, {}) == CORRECT


def test_an_absent_expected_slot_is_MISSED():
    """Recoverable: the default applies, or `ask` catches it. The measured `project_id`
    case."""
    assert cls({"project_id": "P1", "direction": "upstream"},
               {"direction": "upstream"}) == MISSED


def test_a_different_value_is_WRONG():
    """The silent-wrong-answer mode: confidently supplying `org` where the speaker said
    initiative."""
    assert cls({"group_by": "initiative"}, {"group_by": "org"}) == WRONG


def test_an_unsupported_slot_being_filled_is_EXTRA():
    """Invention. The speaker named nothing for it, so this is not a wrong VALUE — it is a
    value where there should be none, which on a verb whose default differs produces a
    confidently wrong scope."""
    assert cls({}, {"group_by": "org"}) == EXTRA


# ── the ranking, which is where a classifier quietly goes wrong ──────────────

def test_a_case_that_is_both_wrong_and_missed_reports_WRONG():
    """Worst-first. A case that both invents and omits is a wrong fill, not a mixed result —
    reporting the gentler class would let the mode that matters hide behind the one that
    does not."""
    assert cls({"group_by": "initiative", "window": ["FY26-Q4"]},
               {"group_by": "org"}) == WRONG


def test_extra_outranks_missed():
    """A filler that omits one slot and invents another is worse than one that merely omits:
    the omission degrades to a default, the invention answers a question nobody asked."""
    # `b` is missing and `c` was invented. EXTRA outranks MISSED, so the case reports EXTRA.
    #
    # The first draft of this assertion was `X == WRONG or Y == EXTRA` — a compound that
    # passes if EITHER half holds, which is the "assert on the claim, not its neighbour"
    # defect written into the very file that grades the battery. One claim, one assertion.
    assert cls({"a": 1, "b": 2}, {"a": 1, "c": 3}) == EXTRA
    # ...and each half alone, so the ranking is pinned rather than inferred from the pair.
    assert cls({"a": 1, "b": 2}, {"a": 1}) == MISSED
    assert cls({"a": 1}, {"a": 1, "c": 3}) == EXTRA


def test_the_severity_order_is_the_one_documented():
    assert battery._SEVERITY.index(WRONG) < battery._SEVERITY.index(EXTRA)
    assert battery._SEVERITY.index(EXTRA) < battery._SEVERITY.index(MISSED)
    assert battery._SEVERITY.index(MISSED) < battery._SEVERITY.index(CORRECT)


# ── the container trap, which this project has paid for three times ──────────

def test_a_bare_string_where_a_LIST_was_expected_is_WRONG_not_correct():
    """`"FY26-Q4"` and `["FY26-Q4"]` are not the same answer. The engine iterates the string
    and replies `422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4`. A classifier that
    treated them as equivalent would score the exact defect this arc keeps meeting as a
    pass."""
    assert cls({"window": ["FY26-Q4"]}, {"window": "FY26-Q4"}) == WRONG


def test_a_list_with_the_right_members_in_a_different_order_is_WRONG():
    """Deliberate and worth stating: order-insensitivity is a JUDGMENT about the verb, not a
    property of the classifier. If a corpus author decides order does not matter for a slot,
    the expectation should say so explicitly rather than the comparator guessing."""
    assert cls({"window": ["FY26-Q3", "FY26-Q4"]},
               {"window": ["FY26-Q4", "FY26-Q3"]}) == WRONG


# ── the detail lines, which are what a human reads ───────────────────────────

def test_the_detail_names_the_slot_and_both_values():
    _, detail = battery.classify({"group_by": "initiative"}, {"group_by": "org"})
    line = " ".join(detail)
    assert "group_by" in line and "org" in line and "initiative" in line, (
        "a failure the reader cannot diagnose from the report is a failure they will re-run"
    )


def test_the_battery_file_contains_no_phrasings():
    """THE SEPARATION THAT MAKES THE NUMBER MEAN ANYTHING. An agent that authored both the
    questions and the system under test would be grading its own homework, so the corpus is
    a human's and arrives as data. This asserts the runner stays a vehicle.

    Heuristic but pointed: a question mark inside a string literal in the runner is either a
    phrasing that has crept in or a docstring that should be reworded."""
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "slot_fill_battery.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]          # past the module docstring
    for quote in ('"', "'"):
        for chunk in body.split(quote)[1::2]:
            assert "?" not in chunk, f"a question-shaped string literal in the runner: {chunk[:60]!r}"
