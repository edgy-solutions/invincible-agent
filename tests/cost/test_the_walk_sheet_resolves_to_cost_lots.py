"""The walk sheet IS the test. Four questions that reached the wrong engine, sealed.

On 2026-09-11 the four questions in `docs/measurements/cost-card-walk-sheet.md` were typed
into the UI and none of them reached engine-cost. The classifier was right — `cost:Supplier`
at 0.92, calling "lot 4" a filter rather than the subject — and its answer was discarded,
because the instance pre-step lets a phone-book hit OVERRIDE `resolved_uri` and the only
provider holding a claim on "lot 4" was engine-fin's. It answered `fin:WBSElement` at exactly
0.500 by matching THE BARE DIGIT against `instance_id`; `banana 4` reproduces the hit.

Engine-cost had no `/resolve_instance` at all, so finance's claim stood unopposed. These
seals cover the half this lane owns: **that engine-cost now makes a better claim on its own
lots than any digit-matcher can.**

── WHAT THESE SEALS DO NOT COVER, STATED SO THE GREEN IS NOT OVERREAD ──────────────────
They do NOT prove the four questions route to cost in the deployed mesh. That needs the
registration to reach the graph (a roll and a prime) and the pre-step's scope rule, which is
Lane 1's half. A green here means the PROVIDER answers correctly for the walk sheet's own
phrasings. The remaining claim is `docs/measurements/cost-card-walk-sheet.md` itself, walked
against a rolled engine — declared and resolves are different claims with different
instruments, and this file is the instrument for only the first.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from agent_fleet.cost_agent import instances as I
from agent_fleet.cost_agent.entities import COST
from agent_fleet.cost_agent.seed import build_state

STATE = build_state()
LOT = COST + "ProductionLot"
RATE_TABLE = COST + "RateTable"

_WALK_SHEET = (pathlib.Path(__file__).resolve().parents[2]
               / "docs" / "measurements" / "cost-card-walk-sheet.md")

#: The questions, READ OUT OF THE WALK SHEET rather than retyped here.
#:
#: DERIVED BECAUSE A RETYPED POPULATION IS A SAMPLE. The architect's first question about
#: this failure was "are those two phrasings exactly what the walk sheet says, or your own
#: words?" — which is the whole risk in one sentence. A copy in this file would let the sheet
#: be reworded and the seal keep passing against text nobody asks any more; and a fifth
#: question added to the sheet is covered by the commit that adds it.
_QUESTION = re.compile(r'^> \*\*"(?P<q>[^"]+)"\*\*', re.MULTILINE)


def walk_sheet_questions() -> list[str]:
    return _QUESTION.findall(_WALK_SHEET.read_text(encoding="utf-8"))


def test_the_walk_sheet_still_holds_the_questions_these_seals_are_derived_from():
    """A POSITIVE CONTROL ON THE PARSER, not on the provider.

    Every seal below is parameterized off `walk_sheet_questions()`. If the heading style in
    that document changed, the regex would find NOTHING, every parameterized seal would
    collapse to zero cases, and pytest would report green for a suite that asserted nothing.
    That is the failure this file is most exposed to, so it is checked directly.

    ── FIVE PROMPTS, FOUR QUESTIONS, AND THE COUNT TRACKS PROMPTS ──────────────────────
    It said FOUR until 2026-09-11, when lane/01 split Q5 into two steps on master: the verb
    refuses first (`rate_vintage` is required and the phrasing names none), and the second
    prompt supplies the vintage. **The refusal is a PASS**, so both steps are real prompts a
    walker types and both must resolve to lot 3.

    THE COUNT DOING ITS JOB IS WHY THIS NOTE EXISTS. The merge changed the sheet under a
    seal derived from it, and this assertion is what said so — naming the parsed five rather
    than passing quietly. A `>=` here would have absorbed the change silently, which is the
    whole failure it was written against.
    """
    questions = walk_sheet_questions()
    assert len(questions) == 5, (
        f"expected the walk sheet's five prompts, parsed {len(questions)}: {questions}. "
        f"If the sheet legitimately gained or lost one, update this count — it is here so "
        f"the parser cannot silently match nothing."
    )


def _lot_in(question: str) -> str | None:
    m = re.search(r"\blot (\d+)\b", question)
    return m.group(1) if m else None


@pytest.mark.parametrize("question", walk_sheet_questions())
def test_every_walk_sheet_question_naming_a_lot_binds_THAT_lot_to_cost(question):
    """The acceptance the architect set: the four questions, with `lot` bound to cost.

    ASSERTED ON THE WHOLE QUESTION, not on a pre-extracted "lot 4". Engine O may hand a
    provider the extracted `identifier` or the raw `query`, and a seal that only ever tested
    the tidy form would not notice the untidy one failing. Both are checked — this one is
    the harder half.
    """
    lot = _lot_in(question)
    if lot is None:
        pytest.skip(f"names no lot: {question!r}")

    hits = I.resolve(STATE, question)
    assert hits, f"engine-cost made NO claim on {question!r} — the defect, exactly"

    top = hits[0]
    assert top["class_uri"] == LOT, (
        f"{question!r} resolved to {top['class_uri']} rather than a production lot"
    )
    assert top["instance_id"] == lot, (
        f"{question!r} names lot {lot} and bound lot {top['instance_id']} — a confidently "
        f"WRONG lot, which is worse than no lot"
    )


@pytest.mark.parametrize("question", walk_sheet_questions())
def test_the_extracted_identifier_beats_the_finance_hit_it_lost_to(question):
    """`lot N` on its own must score ABOVE 0.500 — the score that took these questions away.

    NOT MERELY ABOVE THE FLOOR. The finance hit cleared the same `>=` gate at exactly the
    boundary, so "passes the floor" is the property that FAILED here. What has to be true is
    that cost's claim is STRONGER than the digit-match it lost to, or a scope rule that
    prefers by score changes nothing.
    """
    lot = _lot_in(question)
    if lot is None:
        pytest.skip(f"names no lot: {question!r}")

    hits = I.resolve(STATE, f"lot {lot}")
    assert hits and hits[0]["class_uri"] == LOT and hits[0]["instance_id"] == lot
    assert hits[0]["score"] > 0.5, (
        f"'lot {lot}' scored {hits[0]['score']}, which does not beat the 0.500 bare-digit "
        f"hit on fin:WBSElement that these questions were lost to"
    )


def test_the_fourth_question_names_a_rate_table_and_not_a_lot():
    """THE ODD ONE OUT ENCODES A CONSTRAINT, so it is asserted rather than skipped past.

    Three questions name a lot; `what rates are we using in FY2021` names a FISCAL YEAR. A
    provider that answered "lot" for all four would pass every seal above — the lot-naming
    ones by being right, this one by never being asked. That is a seal whose subject and
    instrument share a surface, and it is the shape this file exists to avoid.
    """
    fy = [q for q in walk_sheet_questions() if _lot_in(q) is None]
    assert len(fy) == 1, f"expected exactly one non-lot question, got {fy}"

    hits = I.resolve(STATE, "FY2021")
    assert hits, "engine-cost made no claim on 'FY2021'"
    assert hits[0]["class_uri"] == RATE_TABLE, (
        f"'FY2021' resolved to {hits[0]['class_uri']}, not a rate table"
    )
    assert not any(h["class_uri"] == LOT for h in hits), (
        "'FY2021' offered a production lot — a year is not a lot, and 2021 must not reach "
        "the digit tier"
    )


# ---------------------------------------------------------------------------
# The controls. These are the seals that would have caught the original defect.
# ---------------------------------------------------------------------------

#: NONSENSE THAT RESOLVED. `banana 4` and `xyzzy 4` are not hypothetical inputs — they were
#: run against `finance_agent/main.py::_candidates` on 2026-09-11 and BOTH returned
#: `Program Support` at 0.500, which is how the defect was proven to carry no semantic
#: content. They are permanent controls here: if engine-cost ever answers one, this scorer
#: has regressed into the thing it was written to avoid.
_NONSENSE = ["banana 4", "xyzzy 4", "site 4", "phase 3", "banana", "4 4 4"]


@pytest.mark.parametrize("needle", _NONSENSE)
def test_the_provider_refuses_a_digit_carried_by_a_word_it_does_not_know(needle):
    assert I.resolve(STATE, needle) == [], (
        f"{needle!r} resolved. A digit beside an unknown word is not an identity claim — "
        f"this is the exact input that proved engine-fin's hit was contentless."
    )


def test_a_bare_number_is_refused_unscoped_and_accepted_scoped():
    """The rule stated both ways, because only the pair shows it is a RULE and not a bug.

    An engine whose identifiers are bare integers cannot treat a bare integer as a name, or
    it claims every digit in the fleet. But refusing it outright would break the legitimate
    call — Engine O CAN supply `class_uri`, and when it does, something other than the digit
    established the class. One assertion without the other reads as either over-eagerness or
    a missing feature.
    """
    assert I.resolve(STATE, "4") == [], "a bare '4' with no class is not a name"
    scoped = I.resolve(STATE, "4", LOT)
    assert [c["instance_id"] for c in scoped] == ["4"], scoped
    assert scoped[0]["score"] == 1.0


def test_a_contradicted_number_disqualifies_rather_than_scoring_low():
    """`lot 9` must not offer Lot 4 at all — not even below the floor as a near miss.

    Sharing the word "lot" is enough to reach the overlap tier, where Lot 4 would otherwise
    score 0.6 on the class word alone. Scoring it low would leave a confidently wrong lot one
    threshold change away from being returned.
    """
    for c in I.candidates(STATE, "lot 9"):
        assert c["instance_id"] == "9", f"'lot 9' offered {c['label']} at {c['score']}"


def test_a_lot_that_is_not_in_the_model_resolves_to_NOTHING():
    """`lot 99` must not fall back to Lot 9 — a substring is not an identity."""
    assert I.resolve(STATE, "lot 99") == [], (
        "'lot 99' matched something; the model holds lots "
        f"{STATE.lot_numbers} and 99 is not among them"
    )


def test_every_class_this_engine_routes_on_can_be_found():
    """The boot check, asserted here too, because a boot check only runs at boot.

    Engine F found `unsupported` for a class it ROUTED ON by running the engine rather than
    reading it — and the symptom appears only at an elicitation, never at the engine. This
    is the cheap reproduction that fails in CI instead.
    """
    from agent_fleet.cost_agent.main import _all_subjects

    missing = sorted(_all_subjects() - set(I._RESOLVABLE) - I._NOT_ENUMERABLE)
    assert not missing, (
        f"verbs route on {missing} and nothing can resolve or enumerate them — add them to "
        f"instances._RESOLVABLE, or to _NOT_ENUMERABLE with a stated reason"
    )


def test_enumeration_refuses_an_unheld_class_as_unsupported_not_as_empty():
    """`unsupported` and an empty member list mean different things to the ask.

    An ask reading `members: []` may legitimately offer free text. Reading `unsupported` it
    must not conclude the class is empty — only that this provider does not hold it. The two
    collapsing into one shape is the distinction's whole failure mode.
    """
    out = I.enumerate_class(STATE, COST + "NotAClassThisEngineHolds")
    assert out["outcome"] == "unsupported"
    assert out["members"] == []
    assert COST + "ProductionLot" in out["reason"], (
        "the refusal must name what this provider DOES hold, or a caller cannot tell a "
        "typo from a genuine gap"
    )


def test_too_many_carries_its_count():
    """"Too many" without a number is indistinguishable from "I did not look".

    This engine has nine lots against the fleet's default bound of eight, so the primary
    class answers `too_many` at the default. That is correct by the contract — the bound is
    the CALLER's declaration of what fits — and it is only safe because `count` lets the ask
    raise its own limit rather than fall back to free text.
    """
    out = I.enumerate_class(STATE, LOT, limit=8)
    assert out["outcome"] == "too_many"
    assert out["count"] == len(STATE.lot_numbers) == 9
    assert out["bound"] == 8
    assert I.enumerate_class(STATE, LOT, limit=20)["outcome"] == "members"


def test_the_category_labels_have_not_drifted_from_the_measures_module():
    """`instances` keeps its own copy of the bucket labels. Sealed, since it is a copy.

    Importing `measures._CATEGORY_LABELS` across modules to save four lines is the trade that
    makes a rename silent. The copy is deliberate; this is the half that makes it honest.
    """
    from agent_fleet.cost_agent import measures

    assert I._CATEGORY_LABELS == measures._CATEGORY_LABELS
