"""A turn that bound its referent says so — and only where a validator has seen the value.

THE GAP THIS CLOSES. `turn_is_set_shaped` taught the arity GATE to read the chain's bound slots.
It did not write the RECORD. So the NP-MERIDIAN turn stopped being wrongly flagged and still
projected `instance_resolved: false` with an empty `instance_identifier` — **a resolved turn
reporting as unresolved.**

**AND NOTHING COULD SEE IT.** `instance_resolved` is `bool(md.get("subject_instance_id"))` and the
arity gate reads the same field, so the two agreed — and were wrong together. A record can be
self-consistent and false (R-056), which is exactly the case a consistency check is blind to.

**PROMOTION IS GATED ON PROVENANCE, NOT ON SHAPE, AND THAT IS THE WHOLE RULING.**
`subject_instance_id` does not stop at the projection: it reaches the generalist fallback as
`resolved_instance_id`, and **Engine A does NOT re-resolve it.** So promoting a value means an
engine acts on a string no validator checked — unless one already did:

    picked    a menu THIS SYSTEM enumerated at the hop that bound it   -> PROMOTED
    filled    extracted by the slot filler, resolving against the graph -> PROMOTED
    supplied  sent by an API caller with the request                    -> REFUSED
    spoken    typed to a RESPEAK ask, no menu existed                   -> EXCLUDED, undecided

`spoken` is the fourth of four and the ruling named three. It is excluded **while undecided**
rather than assigned to whichever set it fell into first — not promoting is the conservative arm,
because it leaves today's behaviour where Engine A re-resolves.

Run: uv run --frozen pytest tests/routing/test_the_record_reports_the_instance_it_bound.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from iagent_pure.verb_eligibility import (
    NON_PROMOTABLE_SLOT_SOURCES,
    PROMOTABLE_SLOT_SOURCES,
    promotable_instance_from_slots,
)

_REPO = Path(__file__).resolve().parents[2]
_SUP = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_GW = _REPO / "src" / "iagent" / "gateway.py"

#: The verb from the measured failure: one slot, required AND a referent, which is the
#: conjunction that forces `arity: single`.
_FIN_BRIEF = {
    "verb_iri": "fin:finProgramBrief",
    "arity": "single",
    "slots": [{"name": "program_id", "required": True, "referent": "fin:Program"}],
}


def _bound(source: str, value: str = "NP-MERIDIAN") -> dict:
    return {"program_id": {"value": value, "source": source, "hop": 1}}


# ── THE RULING, ARM BY ARM ──────────────────────────────────────────────────────────────────

def test_THE_MEASURED_TURN_a_picked_referent_is_promoted():
    """NP-MERIDIAN, chosen from a menu this system offered. The record must report it."""
    got = promotable_instance_from_slots(_FIN_BRIEF, _bound("picked"))
    assert got is not None, (
        "a value picked from an offered menu was not promoted — the turn that named the "
        "instance still projects instance_resolved: false"
    )
    assert got[0] == "NP-MERIDIAN" and got[1] == "program_id" and got[2] == "picked"


def test_A_FILLED_REFERENT_IS_PROMOTED():
    """Extracted from the question by the slot filler, which resolves against the graph."""
    assert promotable_instance_from_slots(_FIN_BRIEF, _bound("filled"))[0] == "NP-MERIDIAN"


def test_A_CALLER_SUPPLIED_ID_IS_REFUSED_and_this_is_the_arm_with_teeth():
    """THE ONE SOURCE NO VALIDATOR HAS SEEN.

    Promoting it would put an unchecked caller string into the field Engine A reads as
    `resolved_instance_id` and acts on WITHOUT re-resolving. Refusing leaves the field empty,
    which is what makes Engine A re-resolve — so this assertion is the whole safety argument.
    """
    assert promotable_instance_from_slots(_FIN_BRIEF, _bound("supplied")) is None, (
        "a caller-supplied id was promoted. Engine A will read it as a resolved instance and "
        "skip re-resolution — acting on a string nothing validated."
    )


def test_SPOKEN_IS_EXCLUDED_WHILE_UNDECIDED_not_silently_sorted():
    """The fourth source, which the ruling did not reach. Excluded, with its reason recorded."""
    assert promotable_instance_from_slots(_FIN_BRIEF, _bound("spoken")) is None
    assert "spoken" in NON_PROMOTABLE_SLOT_SOURCES
    assert "UNDECIDED" in NON_PROMOTABLE_SLOT_SOURCES["spoken"], (
        "`spoken` must record that it is pending a ruling. An exclusion that reads as a "
        "decision is the plausible-negative shape: indistinguishable from one somebody made."
    )


def test_AN_UNKNOWN_SOURCE_IS_NOT_A_DEFAULT():
    """A fifth source added upstream must not be promoted by falling through — the same rule
    `_accumulated_slots` applies one layer up, where an unknown source is refused rather than
    admitted as `supplied`."""
    assert promotable_instance_from_slots(_FIN_BRIEF, _bound("telepathy")) is None


# ── THE CONTROLS ────────────────────────────────────────────────────────────────────────────

def test_A_VERB_WITH_NO_REQUIRED_REFERENT_PROMOTES_NOTHING():
    """Three engines of four declare no arity. Promotion must be as free-by-construction as the
    gate is, and for the same declared reason."""
    no_ref = {"verb_iri": "cost:summariseSpend",
              "slots": [{"name": "period", "required": True}]}
    assert promotable_instance_from_slots(no_ref, {"period": {"value": "Q4", "source": "picked"}}) is None


def test_AN_OPTIONAL_REFERENT_IS_NOT_THE_INSTANCE_SLOT():
    """`required` AND `referent` is the conjunction that forces `arity: single`. Reading either
    alone would promote from a slot that does not identify the subject."""
    opt = {"verb_iri": "x:v", "slots": [{"name": "p", "required": False, "referent": "x:C"}]}
    assert promotable_instance_from_slots(opt, {"p": {"value": "V", "source": "picked"}}) is None


def test_AN_EMPTY_OR_MISSING_BINDING_PROMOTES_NOTHING():
    for slots in ({}, None, {"program_id": {"value": "", "source": "picked"}},
                  {"program_id": {"source": "picked"}}, {"other": {"value": "X", "source": "picked"}}):
        assert promotable_instance_from_slots(_FIN_BRIEF, slots) is None, slots


def test_EVERY_KNOWN_SOURCE_IS_IN_EXACTLY_ONE_SET():
    """THE PARTITION. A source in neither set is decided by whichever branch it reaches first,
    and a source in both is a contradiction nobody reads."""
    overlap = PROMOTABLE_SLOT_SOURCES & set(NON_PROMOTABLE_SLOT_SOURCES)
    assert not overlap, f"sources in BOTH sets: {sorted(overlap)}"
    for src, why in NON_PROMOTABLE_SLOT_SOURCES.items():
        assert why and why.strip(), f"{src} is excluded with no reason"


def test_THE_JOIN_the_partition_covers_the_whole_vocabulary():
    """THE INVARIANT BETWEEN TWO DECLARATIONS, which is the kind nothing else checks.

    ⛔ THIS READ THE CONSTANTS OUT OF `gateway.py` BY REGEX AND WENT RED WHEN THEY MOVED —
    correctly. The vocabulary was declared in gateway, and then the writer needed it and so did
    the promotion rule; three copies of four names is how a rename makes a feature stop
    SILENTLY, with the reader refusing every row as "unknown source" and reporting a clean
    empty chain. It now lives in `iagent_pure.slot_acceptance`, the one door every binding
    passes through, and this seal imports the object instead of parsing for it.

    The floor is what caught the move: it refused to quantify over an empty set rather than
    passing vacuously, which is the whole reason a floor is written before the assertion.
    """
    from iagent_pure.slot_acceptance import SLOT_SOURCES

    assert len(SLOT_SOURCES) >= 4, f"the vocabulary shrank to {SLOT_SOURCES}"
    known = set(PROMOTABLE_SLOT_SOURCES) | set(NON_PROMOTABLE_SLOT_SOURCES)
    missing = set(SLOT_SOURCES) - known
    assert not missing, (
        f"slot source(s) {sorted(missing)} are neither promoted nor excluded. Add each to "
        f"PROMOTABLE_SLOT_SOURCES or to NON_PROMOTABLE_SLOT_SOURCES with its reason — never "
        f"leave one undecided, because whichever branch it reaches first will decide it."
    )
    stale = known - set(SLOT_SOURCES)
    assert not stale, (
        f"{sorted(stale)} is partitioned here but is no longer a declared source — a rename "
        f"upstream would make promotion silently stop happening"
    )


# ── THE WIRING ──────────────────────────────────────────────────────────────────────────────

def _src(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_THE_SITE_CALLS_IT_and_an_existing_instance_still_wins():
    """A correct helper nothing calls is the shape this repo keeps meeting."""
    src = _src(_SUP)
    assert "promotable_instance_from_slots(" in src, (
        "the pre-resolved site never calls the promotion — the record still reports a bound "
        "turn as unresolved"
    )
    assert "_pre_instance or (_promoted[0] if _promoted else \"\")" in src, (
        "the record does not prefer an instance the ask genuinely carried. Overwriting a "
        "resolved subject with a slot value is this defect in the other direction."
    )
    assert "if not _pre_instance:" in src, (
        "promotion is attempted even when the subject is already resolved"
    )


@pytest.mark.parametrize("marker", ["Engine A does NOT re-resolve", "picked", "supplied"])
def test_THE_REASON_TRAVELS_WITH_THE_CODE(marker: str):
    """The provenance gate is not self-evident from the call. A later reader simplifying this
    to "promote whatever is bound" would be making a security change believing it a cleanup, so
    the blast radius is recorded at the site rather than only in the ruling."""
    raw = _SUP.read_text(encoding="utf-8")
    assert marker in raw, f"the site no longer explains {marker!r}"


# ── BOTH PRE-RESOLVED SITES, AND THE ENUMERATION IS THE POINT ───────────────────────────────
#
# ⛔ THE FIRST VERSION OF THIS FIX LANDED IN THE SUPERVISOR ONLY, and the supervisor's
# pre-resolved branch is the FALLBACK. A pick-answer reaches `dispatch_pre_resolved` first
# (`gateway.py` calls it when `_pre_resolved` is truthy), so the site that was measured is the
# site that was left broken. The ruling said "the pre-resolved site"; there are TWO, and
# reading that as one is a filed defect treated as a census.
#
# The reachability check is what caught it — not any test, all of which were green.

_DD = _REPO / "src" / "iagent" / "direct_dispatch.py"


def test_THE_FAST_PATH_GATE_READS_THE_BOUND_SLOTS():
    """direct_dispatch is the path a pick-answer actually takes."""
    src = _src(_DD)
    assert "turn_is_set_shaped(instance_id, _cv, _bound_names)" in src, (
        "the fast path still gates on the ask's empty subject. This is the site the defect was "
        "MEASURED on; fixing only the supervisor fixes the fallback and leaves the live path."
    )
    assert "filter_verbs_by_arity(verbs, not instance_id)" not in src, (
        "the old whole-list boolean gate is still there"
    )


def test_THE_FAST_PATH_PROMOTES_INTO_THE_RECORD():
    """Both of this module's record sites write `instance_id`, so promoting it once fixes both
    — which is why the promotion goes on the variable and not on each call."""
    src = _src(_DD)
    assert "promotable_instance_from_slots(truth, chain_slots or {})" in src, (
        "the fast path never promotes, so its record still reports a bound turn as unresolved"
    )
    assert "if not instance_id:" in src, (
        "promotion is attempted even when the ask genuinely carried an instance"
    )


def test_BOTH_SITES_USE_THE_SAME_PREDICATE_not_two_opinions():
    """One rule, one implementation. Two sites each deciding 'did this turn name an instance'
    with their own logic is how three engines ended up with three behaviours — and neither
    site's tests would show the drift."""
    for path, name in ((_DD, "direct_dispatch"), (_SUP, "dynamic_supervisor")):
        src = _src(path)
        assert "turn_is_set_shaped(" in src, f"{name} does not use the shared gate predicate"
        assert "promotable_instance_from_slots(" in src, (
            f"{name} does not use the shared promotion predicate"
        )
