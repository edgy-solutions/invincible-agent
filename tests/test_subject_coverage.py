"""The boot guard that two engines shipped without, tested on NON-EMPTY cases.

WHY NON-EMPTY IS THE POINT. Engine F's own answer to both questions is `[]`, so comparing the
extracted helper against the engine's previous inline logic proved only that two empty lists are
equal — a vacuous equivalence, and exactly the shape this repo keeps catching. The extraction is
therefore STRUCTURAL: finance now calls these functions, so there is one implementation rather
than two that agree. What needs testing is the implementation itself, on inputs where the answer
is not empty.

WHAT IT PREVENTS, measured on a sibling engine 2026-09-04: a cost question grounds to
`cost#CostCategory` at 0.96, that class has zero verbs, routing falls through to the generalist,
and the answer comes back wearing the caller's persona. Two of five groundable cost classes are
unserved. Engine P has no such check either, and it predates Engine F — so this is not one
engine forgetting, it is a check that existed once and was needed everywhere.
"""
from __future__ import annotations

import pytest

from agent_fleet.utils.subject_coverage import (
    assert_subject_coverage,
    dead_end_classes,
    unroutable_classes,
)

A, B, C, D = "ex#Alpha", "ex#Beta", "ex#Gamma", "ex#Delta"


def test_a_findable_class_with_no_verb_is_a_dead_end():
    assert dead_end_classes(resolvable=[A, B], verb_subjects=[A]) == [B]


def test_a_dead_end_can_be_DECLARED_deliberate_rather_than_fixed():
    """A class that exists only to be drilled INTO is legitimate. The check forces the
    declaration, not a verb — which is why the message names both repairs."""
    assert dead_end_classes(resolvable=[A, B], verb_subjects=[A], no_verb_by_design=[B]) == []


def test_a_verb_subject_nobody_can_find_is_unroutable():
    assert unroutable_classes(verb_subjects=[A, C], resolvable=[A]) == [C]


def test_an_unroutable_subject_can_be_declared_not_enumerable():
    assert unroutable_classes(verb_subjects=[A, C], resolvable=[A], not_enumerable=[C]) == []


def test_the_two_directions_are_INDEPENDENT_and_both_reported():
    """Neither failure is visible from the other's check, which is why there are two.

    A single engine can have a findable class no verb serves AND a verb subject nothing can
    find, at the same time, for unrelated reasons.
    """
    resolvable, subjects = [A, B], [A, C]
    assert dead_end_classes(resolvable=resolvable, verb_subjects=subjects) == [B]
    assert unroutable_classes(verb_subjects=subjects, resolvable=resolvable) == [C]


def test_a_SECONDARY_subject_counts_as_served():
    """⛔ THE FALSE-RED THIS GUARD MUST NOT PRODUCE.

    Engine F registers four verbs against an additional subject (`also_askable_of`), so the
    served set is every subject, not each verb's primary one. Passing only the primaries would
    report a class as a dead end while a verb routes on it — and a check that RAISES on a false
    red stops an engine that was fine, which is worse than the gap it guards.
    """
    assert dead_end_classes(resolvable=[A, B], verb_subjects=[A, B]) == []


def test_it_RAISES_and_the_message_names_the_class_and_both_repairs():
    with pytest.raises(RuntimeError) as e:
        assert_subject_coverage(component="engine-x", resolvable=[A, B], verb_subjects=[A])
    msg = str(e.value)
    assert B in msg, "the message must name the class — an operator should not have to derive it"
    assert "register a verb" in msg and "_NO_VERB_BY_DESIGN" in msg, (
        "both repairs must be named: which one is right is a judgement the check cannot make"
    )


def test_it_raises_on_the_reverse_direction_too_and_names_its_own_repairs():
    with pytest.raises(RuntimeError) as e:
        assert_subject_coverage(component="engine-x", resolvable=[A], verb_subjects=[A, C],
                                resolvable_name="_RESOLVABLE")
    msg = str(e.value)
    assert C in msg and "_RESOLVABLE" in msg and "_NOT_ENUMERABLE" in msg


def test_a_clean_engine_does_not_raise():
    """The positive control. Without it, a guard that raised unconditionally would pass every
    test above."""
    assert_subject_coverage(
        component="engine-x", resolvable=[A, B], verb_subjects=[A, D],
        no_verb_by_design=[B], not_enumerable=[D],
    )


def test_engine_F_still_answers_both_questions_with_nothing():
    """The live engine, through the delegated path. Empty is the CORRECT answer here and this
    assertion is deliberately weak — the strength is in the non-empty cases above."""
    from agent_fleet.finance_agent.main import _dead_end_classes, _unroutable_classes
    assert _dead_end_classes() == []
    assert _unroutable_classes() == []
