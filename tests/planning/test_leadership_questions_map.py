"""The 17 leadership questions -> verb map. Gate 0's last open item.

WHAT THIS FILE IS. `docs/plans/portfolio-review-workshop-tool.md` carries the mapping in the
VERB direction (each verb lists the Q-numbers it answers). Gate 0 asks for it in the QUESTION
direction, "with any unanswerable question flagged, not fudged" -- because a verb-keyed table
cannot show a GAP. A question nobody wrote a verb for simply does not appear in it.

Written as a test rather than a document so it cannot drift: renaming a verb, changing an
output type, or adding a thirteenth verb without placing it fails here.

THE LIMIT OF THIS SEAL, STATED UP FRONT.

The customer's question TEXT is customer material and is never pasted into this repo (the
C-series scrub rule). So the shapes below are GENERIC restatements derived from the verb
definitions in the plan -- which means this file can prove:

  * STRUCTURAL COVERAGE -- every Q1..Q17 has exactly one verb placed against it;
  * NON-DRIFT -- every verb named here exists, with a declared output type.

and it CANNOT prove:

  * SEMANTIC FIT -- that the verb actually answers the question as the customer asked it.

That check needs the source list and a human, and it is the one that matters most. Deriving
each question's shape FROM the verb it is mapped to is circular by construction: it would let
a fudged row look correct here forever. So the circularity is named rather than hidden, and
`test_the_semantic_check_is_owed` keeps it visible instead of letting this file read as a
closed gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.planning_agent import main as _main  # noqa: E402
from agent_fleet.planning_agent import measures  # noqa: E402

_MESH = "http://invincible-agent/mesh#"

# Q-number -> (verb, generic shape). Q-NUMBERS ONLY; no customer wording.
# Sourced from the verb table in docs/plans/portfolio-review-workshop-tool.md section 2.3.
QUESTION_MAP: dict[str, tuple[str, str]] = {
    "Q1":  ("mesh:planProcessEvolution",     "how an operational activity changes across plateaus"),
    "Q2":  ("mesh:planProcessEvolution",     "which abilities enable that change, and their trajectory"),
    "Q3":  ("mesh:planMaturityGrid",         "ability maturity per location against target, as of a date"),
    "Q4":  ("mesh:planSchedule",             "what is planned when, as intervals"),
    "Q5":  ("mesh:planSchedule",             "the same rows pivoted by strategy / ability / target"),
    "Q6":  ("mesh:planSchedule",             "which rows carry a risk flag"),
    "Q7":  ("mesh:planCapabilityPath",       "which work advances one ability, ordered and weighted"),
    "Q8":  ("mesh:planTechFootprint",        "what a technical component enables and participates in"),
    "Q9":  ("mesh:planSiteLoad",             "concurrent change-load per location per period"),
    "Q10": ("mesh:planDependencyNeighborhood", "what determines sequencing — the neighbours on either side, each with its state"),
    "Q11": ("mesh:planSiteLoad",             "which locations exceed their saturation threshold"),
    "Q12": ("mesh:planCostCurve",            "time-phased spend per period"),
    "Q13": ("mesh:planFundingGap",           "required minus committed, per group"),
    "Q14": ("mesh:planFundingGap",           "the same split by funding kind"),
    "Q15": ("mesh:planFundingGap",           "who is under-committed"),
    "Q16": ("mesh:planCostCurve",            "spend against the governed cap line"),
    "Q17": ("mesh:planCostCurve",            "where the plan is over that cap"),
}

# Questions with NO verb. Empty is the honest answer TODAY and must stay honest: a question
# that turns out unanswerable belongs here BY NUMBER, never quietly reassigned to a verb that
# nearly fits. Reassigning is exactly the "fudged row" Gate 0 names.
UNANSWERABLE: dict[str, str] = {}

# Verbs that answer no numbered question. Not a gap -- they serve the interaction model rather
# than the question list, and saying so stops a later reader "fixing" the map by inventing
# question numbers for them.
NOT_QUESTION_DRIVEN = {
    "mesh:planCoverageGap":    "rev3 B4 absence query -- processes/abilities no initiative touches",
    "mesh:planDiff":           "Phase 3 scenario diffs -- answers about a CHANGE, not the plan",
    "mesh:planSessionChanges": "INV-4 -- the session's own op log",
    # RE-HOMED 2026-08-22 and the reason is worth keeping: the plan's section 2.3 mapped Q10
    # to this verb, and the MAPPING was right while the VERB was wrong. Q10 asks what
    # DETERMINES SEQUENCING -- a traversal. This verb evaluates which constraints are
    # currently BREACHED, which is a different question and one the seventeen do not ask.
    # It stays load-bearing: plan_diff never suppresses violations under a materiality floor,
    # and seeded tension (b) is its trap. Answering no numbered question is not the same as
    # answering nothing.
    "mesh:planDependencyViolations":
        "evaluates breaches, not sequencing -- feeds plan_diff and seeded tension (b); Q10 "
        "asks what determines sequencing and now routes to the traversal verb",
}

# Verbs that DO answer numbered questions, whose numbers are not establishable from this repo.
#
# THIS BUCKET EXISTS TO AVOID A COMFORTABLE LIE. `planDependencyNeighborhood` was commissioned
# because Lane 2 found intents with nowhere to route, and the pre-registered gate risk was
# "~6 of 51 cases" -- 51 being 17 questions x 3 phrasings, so 6 cases is TWO QUESTIONS. The
# evidence therefore says this verb serves two numbered questions.
#
# Filing it under NOT_QUESTION_DRIVEN would assert the opposite of what the evidence says, and
# mapping it to Q-numbers I picked would be inventing the answer. The customer's question text
# never enters this repo (C-series), so WHICH two is not knowable here -- it belongs to whoever
# holds the source list.
#
# Entries here must name who owns the answer, and the seal below keeps the bucket small so it
# cannot become a parking lot.
# EMPTIED 2026-08-22, the same day it was created, by the operator answering from the source
# list: both intents serve Q10. `what_blocks` IS the predecessor traversal section 2.3 already
# mapped to Q10; `downstream_of` is Q10's inverse reading -- sequencing runs both directions --
# and no distinct row in the seventeen names it separately.
#
# So the gate arithmetic revises DOWN: not "~6 cases, two questions" but Q10's three phrasings
# plus whatever Lane 2 authors for the downstream reading. Left in place, empty, because the
# mechanism earned its keep -- the alternative was filing a verb under a bucket asserting the
# opposite of the evidence.
AWAITING_QUESTION_NUMBER: dict[str, str] = {}


def _verbs() -> dict[str, dict]:
    return {v["verb"]: v for v in _main.VERBS}


def test_all_seventeen_questions_are_placed():
    """Every Q1..Q17 is either mapped to a verb or explicitly listed as unanswerable."""
    expected = {f"Q{i}" for i in range(1, 18)}
    placed = set(QUESTION_MAP) | set(UNANSWERABLE)
    assert placed == expected, (
        f"questions neither mapped nor flagged: {sorted(expected - placed)}\n"
        f"unexpected question ids: {sorted(placed - expected)}"
    )
    overlap = set(QUESTION_MAP) & set(UNANSWERABLE)
    assert not overlap, f"{sorted(overlap)} is both mapped and flagged unanswerable"


def test_every_mapped_verb_actually_exists():
    """THE DRIFT SEAL. A map naming a verb that no longer exists is worse than no map."""
    known = _verbs()
    missing = sorted({v for v, _ in QUESTION_MAP.values() if v not in known})
    assert not missing, (
        f"the question map names verbs Engine P does not register: {missing}\n"
        f"registered: {sorted(known)}"
    )


def test_every_verb_is_accounted_for():
    """Coverage in the other direction -- a new verb must be PLACED, not merely added.

    Without this, a thirteenth verb lands and the map still passes while silently describing
    a smaller system than the one that ships.
    """
    mapped = {v for v, _ in QUESTION_MAP.values()}
    accounted = mapped | set(NOT_QUESTION_DRIVEN) | set(AWAITING_QUESTION_NUMBER)
    unplaced = sorted(set(_verbs()) - accounted)
    assert not unplaced, (
        f"verbs neither mapped to a question nor declared not-question-driven: {unplaced}.\n"
        f"Place each one: give it a Q-number, or say why it answers none."
    )


def test_declared_not_question_driven_verbs_are_real():
    """Positive control: the exemption list cannot quietly cover a verb that was deleted."""
    known = _verbs()
    stale = sorted(v for v in NOT_QUESTION_DRIVEN if v not in known)
    assert not stale, f"NOT_QUESTION_DRIVEN names verbs that no longer exist: {stale}"


def test_every_mapped_verb_has_a_declared_output_type():
    """ADR-0030: a verb answers with ONE fixed output type.

    A question mapped to a verb with no declared output_uri is a row that cannot render,
    which is a fudge with extra steps.
    """
    known = _verbs()
    for q, (verb, _shape) in sorted(QUESTION_MAP.items()):
        fn = known[verb]["fn"]
        uri = measures.OUTPUT_URI.get(fn)
        assert uri and uri.startswith(_MESH), f"{q} -> {verb} has no mesh output_uri ({uri!r})"


def test_no_two_questions_share_a_verb_by_accident():
    """Sharing IS legitimate -- Q13/Q14/Q15 are three angles on one measure.

    This asserts the sharing is DELIBERATE by requiring each shared question to describe a
    different angle; two identical shapes on one verb means a question was parked, not
    answered.
    """
    by_verb: dict[str, list[str]] = {}
    for _q, (verb, shape) in QUESTION_MAP.items():
        by_verb.setdefault(verb, []).append(shape)
    for verb, shapes in by_verb.items():
        assert len(shapes) == len(set(shapes)), (
            f"{verb} carries duplicate question shapes {shapes} -- two questions mapped to one "
            f"verb must ask different things of it, or one of them is parked."
        )


@pytest.mark.xfail(
    reason="OWED: needs the source question list and a human. See module docstring.",
    strict=True,
)
def test_the_semantic_check_is_owed():
    """FAILS ON PURPOSE, and must keep failing until a human checks the mapping.

    Structural coverage is not semantic fit. Every assertion above would still pass if a verb
    were mapped to a question it cannot answer, because the question shapes here were derived
    FROM the verbs. `strict=True` means this flips to a failure the moment someone marks it
    passing without doing the work -- the gate closes deliberately or not at all.
    """
    raise AssertionError("semantic fit unverified -- a human must read the 17 questions against this map")


def test_the_awaiting_bucket_stays_small_and_named():
    """A holding bucket becomes a parking lot the moment nobody counts it.

    Each entry must name who owns the answer, and there must be few of them — if this grows,
    the map has stopped describing the question list and started excusing itself from it.
    """
    known = _verbs()
    assert len(AWAITING_QUESTION_NUMBER) <= 2, (
        f"{len(AWAITING_QUESTION_NUMBER)} verbs are awaiting a question number. That is no "
        f"longer a gap, it is an unmapped catalogue."
    )
    for verb, why in AWAITING_QUESTION_NUMBER.items():
        assert verb in known, f"AWAITING_QUESTION_NUMBER names a verb that does not exist: {verb}"
        assert "operator" in why or "Lane" in why, (
            f"{verb}'s entry does not name who owns the answer: {why!r}"
        )
