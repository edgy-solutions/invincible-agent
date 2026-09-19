"""A BARE DIGIT IS NOT A CLAIM — `name_score`'s suffix rule, and the abstention control both ways.

Defect (2) of three behind the lot 4 regression, dispatched to this lane at `006fccf`. Measured
before the fix, against the MPNs the dispatch names: `name_score('4', 'FK1220014') == 0.9`, and the
same for `FNA000074`, `FNC500134`, `FK2500054` — twenty `pcn#Component` candidates at 0.9, each
merely CONTAINING a four. That second class in the claimant set is what made `ambiguous_in_domain`
fire on a question with exactly one exact match.

The suffix rule had one guard — the shorter side is not a descriptor word like *notice* — and none
on LENGTH. `'4'` is not a descriptor token, so it scored.

**BOTH DIRECTIONS, BECAUSE A GUARD THAT KILLS THE CASE THE RULE WAS WRITTEN FOR IS THE
OVER-CONSTRAINED FIX AND THOSE GET REVERTED.** The rule exists for a user typing `44310-31` for
`090-44310-31`; that must still resolve at 0.9, and it is asserted here beside the abstentions.

TWO ROWS HERE ARE NOT IN THE DISPATCH, and both come from running its table before trusting it:

  * `'31'` scores 0.9 against `090-44310-31` — **the dispatch's own must-survive candidate**. Same
    defect, different digit, hiding inside the example chosen to prove the rule was fine.
  * the dispatch's `'44'` row used `090-44310-31`, which does not END in 44, so it abstained
    before the fix as well — **a control that could not fail.** It is asserted here against
    `FK1220044`, which does.

Run: uv run --frozen pytest tests/test_a_short_fragment_is_not_a_suffix_claim.py -v
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.ontology_service.sustainment_instance_match import (  # noqa: E402
    _MIN_SUFFIX_CLAIM_LEN,
    name_score,
)
from agent_fleet.ontology_service.sustainment_instance_provider import (  # noqa: E402
    resolve_sustainment_candidates,
)

#: READ, NEVER RESTATED. The floor is the provider's own declared default; a copy of `0.5` here
#: would be a second declaration that can disagree with the one that decides.
FLOOR = inspect.signature(resolve_sustainment_candidates).parameters["floor"].default

#: The real MPNs from the measurement, plus one ending in `44` and the suffix-rule's own case.
_MPNS = ["FK1220014", "FNA000074", "FNC500134", "FK2500054", "FK1220044", "090-44310-31"]
_ROWS = [
    {"s": f"http://internal/components/{m}", "type": "http://internal/sustainment/pcn#Component"}
    for m in _MPNS
]


def _resolve(term: str):
    return resolve_sustainment_candidates(term, rows=_ROWS)


# -- the defect ------------------------------------------------------------------------------


@pytest.mark.parametrize("mpn", ["FK1220014", "FNA000074", "FNC500134", "FK2500054"])
def test_A_BARE_DIGIT_DOES_NOT_CLAIM_A_PART_NUMBER(mpn):
    """THE REPORTED DEFECT, at the four MPNs it was measured against. Each was 0.9."""
    score = name_score("4", mpn)
    assert score < FLOOR, (
        f"'4' scores {score} against {mpn}, at or above the resolve floor {FLOOR}. Every part "
        f"number ending in four becomes a claimant again, and a second class in the claimant set "
        f"is what made ambiguous_in_domain fire."
    )


def test_THE_SUFFIX_RULE_WOULD_HAVE_FIRED_so_the_guard_is_what_stops_it():
    """THE GUARD IS REACHABLE AND LOAD-BEARING, asserted rather than assumed.

    Without this, a green above is equally consistent with the suffix rule never having matched
    `'4'` at all — in which case the length guard would be an arm that cannot fire and the real
    cause would still be out there. `str.endswith` is the exact predicate the rule uses.
    """
    assert "FK1220014".lower().endswith("4"), "the suffix predicate itself must still match"
    assert len("4") < _MIN_SUFFIX_CLAIM_LEN, "so it is the LENGTH guard, and nothing else, refusing"


@pytest.mark.parametrize(
    "term,candidate,why",
    [
        ("4", "FK1220014", "the reported case"),
        ("44", "FK1220044", "a candidate that ACTUALLY ends in 44 — the dispatch's row could not fail"),
        ("31", "090-44310-31", "found here: the same defect on the dispatch's must-survive candidate"),
        ("the", "090-44310-31", "a descriptor word, already guarded — kept as the control that was"),
    ],
)
def test_SHORT_FRAGMENTS_ABSTAIN(term, candidate, why):
    score = name_score(term, candidate)
    assert score < FLOOR, f"{term!r} vs {candidate!r} scored {score} ({why})"


@pytest.mark.parametrize("term", ["4", "44", "31", "the"])
def test_THE_PROVIDER_RETURNS_NOTHING_not_a_least_bad_match(term):
    """The contract the docstring states and the defect broke: *providers MUST abstain rather than
    return least-bad matches*. Asserted at the PROVIDER, because that is what the router reads —
    a low score that still clears the floor is not an abstention."""
    assert _resolve(term) == [], f"{term!r} produced candidates: {_resolve(term)}"


# -- the case the rule exists for ------------------------------------------------------------


def test_THE_REAL_SUFFIX_CASE_STILL_RESOLVES_AT_0_9():
    """THE ROW THAT MAKES THIS A FIX RATHER THAN A MUTING. A guard that also killed this would be
    the over-constrained version, and those are the ones that get reverted."""
    assert name_score("44310-31", "090-44310-31") == 0.9
    got = _resolve("44310-31")
    assert len(got) == 1 and got[0]["label"] == "090-44310-31", got
    assert got[0]["score"] == 0.9


def test_AN_EXACT_MATCH_IS_STILL_1_0():
    assert name_score("FK1220014", "FK1220014") == 1.0
    assert name_score("fk1220014", "FK1220014") == 1.0, "case-insensitive, as before"


# -- the boundary, pinned in BOTH directions -------------------------------------------------


def test_THE_BOUNDARY_IS_ASSERTED_BOTH_WAYS_so_the_constant_cannot_drift_to_merely_SAFER():
    """A one-sided boundary test lets the constant climb. Four is a CHOICE with a cost on each
    side: three still claims, five refuses a legitimate four-character suffix. Both are asserted,
    so raising it to be "safe" reds instead of silently narrowing what the provider can answer."""
    assert _MIN_SUFFIX_CLAIM_LEN == 4
    assert name_score("0014", "FK1220014") == 0.9, (
        "a suffix exactly at the boundary must still CLAIM — if this reds, the constant went up "
        "and the provider quietly stopped answering things it should"
    )
    assert name_score("014", "FK1220014") != 0.9, (
        "one character below the boundary must not claim — if this reds, the constant went down"
    )


def test_A_THREE_CHARACTER_FRAGMENT_STILL_CLEARS_THE_FLOOR_BY_COINCIDENCE():
    """REPORTED, NOT FIXED, AND PINNED SO IT IS NOT DISCOVERED TWICE.

    `'014'` no longer gets the 0.9 suffix CLAIM — the guard works. But its difflib ratio against
    `FK1220014` is **exactly `0.5`**, the provider admits on `score >= floor`, and it comes back
    with TWO claimants (`FK1220014`, `FNC500134`). That is the ambiguity shape again, one notch
    down: not a confident wrong answer, but not an abstention either.

    Out of scope for this dispatch — extending the guard into the difflib branch is a different
    decision with its own over-constraint risk, and the reported defect is the 0.9 claim. This arm
    records the residue and reds if it changes, in either direction.
    """
    assert name_score("014", "FK1220014") == pytest.approx(0.5)
    assert FLOOR == pytest.approx(0.5), "the coincidence is exactly that these two are equal"
    labels = sorted(c["label"] for c in _resolve("014"))
    assert labels == ["FK1220014", "FNC500134"], labels
