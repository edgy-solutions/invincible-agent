"""ADR-0051 seal 6 — the safety declarations carry their own verbs, through the real composition.

WHAT THIS ASSERTS THAT THE PLATFORM'S OWN OVERLAY SEAL DOES NOT. Lane 1's
`test_the_overlay_layer_actually_composes.py` proves the MECHANISM works. This proves the
SAFETY PROPERTY that depends on it: that a domain species can declare verbs the structural seed
has never heard of, and that those verbs survive composition unchanged.

That is the property most likely to be quietly lost in a merge-shaped implementation. A
field-level merge would hand `risk_acceptance_high` the seed's `approved`/`rejected` and look
entirely correct — a queue with working buttons, on the wrong verb, for the one act in this
domain whose word is load-bearing (R-004(e): a risk is ACCEPTED by an authority; `approved` is
the generic seed's verb for generic things).

BOTH DIRECTIONS, because one of them cannot see the failure that matters:
  forward   compose(seed, overlay) CONTAINS the safety kinds with their own verbs
  reverse   compose(seed, []) does NOT — so a green forward cannot be the seed all along

Plus the tombstone control, which is the cheapest proof the composition BRANCH RAN rather than
the seed simply being read: a seed-only read cannot produce a tombstone-for-an-unseeded-key
error, so seeing that error is evidence the overlay was genuinely consulted.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SEED = _REPO / "policy" / "task_kinds"
_OVERLAY = _REPO / "policy" / "overlays" / "sample" / "task_kinds"

compose = pytest.importorskip(
    "iagent_mesh.task_kinds",
    reason="iagent-mesh SDK not installed — seal 6 is VOID, not green, without it",
).compose

#: What `safety.yaml` declares. Written here rather than read from the file, deliberately: a seal
#: that reads its expectation from its subject asserts only that the file parses.
_EXPECTED = {
    "risk_acceptance_high": (
        ["accepted", "rejected", "returned_for_rework"], ["accepted", "rejected"]),
    "risk_acceptance_serious": (
        ["accepted", "rejected", "returned_for_rework"], ["accepted", "rejected"]),
    "risk_acceptance_medium": (
        ["accepted", "rejected", "returned_for_rework"], ["accepted", "rejected"]),
    "risk_acceptance_low": (
        ["accepted", "rejected", "returned_for_rework"], ["accepted", "rejected"]),
    "hazard_link_review": (
        ["linked", "new_hazard", "dismissed"], ["dismissed", "new_hazard"]),
}


def _by_kind(rows):
    return {str(getattr(r, "kind", "")): r for r in rows}


def _verbs(row) -> list[str]:
    return list(getattr(row, "accepts", []) or [])


def _reasons(row) -> list[str]:
    return list(getattr(row, "reason_required", []) or [])


def test_the_seed_alone_does_not_contain_the_safety_kinds():
    """REVERSE DIRECTION, AND IT RUNS FIRST ON PURPOSE.

    If the seed already carried these, every forward assertion below would pass while proving
    nothing about the overlay. This is also the ADR-0036 property in miniature: a domain species
    is absent from the platform seed BECAUSE THE DESIGN REQUIRES IT, not because nobody declared
    it.
    """
    seed_only = _by_kind(compose(_SEED, []))
    assert seed_only, "composing the seed alone named nothing — instrument failure"
    leaked = sorted(set(_EXPECTED) & set(seed_only))
    assert not leaked, (
        f"safety species are in the PLATFORM SEED: {leaked} — a domain name entered "
        "policy/task_kinds/, which its own header forbids"
    )


def test_composition_yields_every_safety_kind_with_its_own_verbs():
    """FORWARD. Each row carries exactly what `safety.yaml` declares — not the seed's defaults."""
    composed = _by_kind(compose(_SEED, [str(_OVERLAY)]))
    missing = sorted(set(_EXPECTED) - set(composed))
    assert not missing, f"composition did not yield the safety species: {missing}"

    for kind, (accepts, reasons) in _EXPECTED.items():
        row = composed[kind]
        # COMPARED AS SETS, AND THIS NOTE HAS AN EXPIRY — READ IT BEFORE TRUSTING IT.
        #
        # Found 2026-09-12: the composer did not preserve declared order.
        # `[accepted, rejected, returned_for_rework]` came back as
        # `['returned_for_rework', 'accepted', 'rejected']`, so asserting order would have been
        # asserting an implementation detail the SDK did not guarantee. It matters because cortex
        # renders buttons FROM `accepts`, and on a risk acceptance the three verbs are not
        # interchangeable.
        #
        # FIXED UPSTREAM THE SAME DAY — `accepts` becomes `tuple[str, ...]` rather than
        # `frozenset[str]` (iagent-mesh-sdk master `d45105e`), a BREAKING change riding a minor.
        #
        # ⚠️ **MY FIRST VERSION OF THIS NOTE NAMED THE WRONG TRIGGER, and the error is worth more
        # than the note.** It said "when the mesh-SDK pin moves off v0.6.0, assert order". The pin
        # DID move — 32 cut v0.7.1 and re-pinned all 31 sites — and on that reading the trigger had
        # fired. It had not: **`d45105e` landed on SDK master AFTER the tag, so v0.7.1 still ships
        # `frozenset`** (verified by composing under the synced v0.7.1, not inferred from the
        # version number). The pin moving was a PROXY for the fix landing, and the two are
        # different events.
        #
        # So the trigger is no longer a comment anybody has to check. `test_the_ordering_tripwire`
        # below ASSERTS THE CURRENT CONTRACT and goes red by itself the moment the SDK starts
        # guaranteeing order — which is the only form of "revisit this later" that cannot go stale,
        # because it does not depend on a reader noticing. A note with a named trigger is worth
        # exactly what the next reader's check of that trigger is worth, and mine was worth
        # nothing until the tripwire existed.
        #
        # `reason_required` below stays a SET PERMANENTLY, and that asymmetry is deliberate in the
        # SDK model rather than an oversight: order is meaningless for a membership test, and the
        # difference now carries information — a surface may read `accepts` as a sequence and must
        # not read `reason_required` as one.
        assert set(_verbs(row)) == set(accepts), (
            f"{kind}: accepts is {sorted(_verbs(row))}, declared {sorted(accepts)}. A field-level "
            "merge would hand it the seed's verbs here and look correct."
        )
        assert set(_reasons(row)) == set(reasons), (
            f"{kind}: reason_required is {sorted(_reasons(row))}, declared {sorted(reasons)}"
        )


def test_accepted_is_a_verb_the_structural_seed_has_never_heard_of():
    """THE PROPERTY R-004(e) DEPENDS ON, asserted directly rather than inferred from the row.

    If the overlay could only narrow the seed's verb set, `accepted` would be unreachable and the
    safety queue would show `approved` — an approval where an acceptance belongs, which is a
    different act with the same buttons.
    """
    seed_verbs = {v for r in compose(_SEED, []) for v in _verbs(r)}
    assert "accepted" not in seed_verbs, (
        "the seed already declares `accepted` somewhere — this seal's premise has changed"
    )
    composed = _by_kind(compose(_SEED, [str(_OVERLAY)]))
    assert "accepted" in _verbs(composed["risk_acceptance_high"])
    assert "approved" not in _verbs(composed["risk_acceptance_high"]), (
        "the safety row carries the seed's `approved` as well as `accepted` — the overlay merged "
        "instead of replacing, and a queue would offer both spellings of one act"
    )


def test_the_seed_rows_are_untouched_by_the_safety_overlay():
    """THE CONTROL FOR THE FORWARD DIRECTION. An overlay that replaced everything would satisfy
    every assertion above while destroying the structural species.

    `grouped_review` is in the seed and the safety overlay says nothing about it, so it must
    come through byte-identical.
    """
    seed_only = _by_kind(compose(_SEED, []))
    composed = _by_kind(compose(_SEED, [str(_OVERLAY)]))
    assert "grouped_review" in seed_only and "grouped_review" in composed
    assert _verbs(composed["grouped_review"]) == _verbs(seed_only["grouped_review"]), (
        "the safety overlay changed a structural species it never mentions"
    )


def test_a_tombstone_for_an_unseeded_kind_is_an_error(tmp_path):
    """THE COMPOSITION-RAN CONTROL, and the cheapest one available.

    A seed-only read CANNOT produce this error, so seeing it is positive evidence that the
    overlay branch executed rather than being skipped. Without a control of this shape, every
    assertion above is consistent with `compose` ignoring its overlay argument and the seed
    happening to contain what was expected.
    """
    ghost = tmp_path / "ghost.yaml"
    ghost.write_text("kind: no_such_species_was_ever_seeded\ndeleted: true\n", encoding="utf-8")
    with pytest.raises(Exception) as exc:
        compose(_SEED, [str(tmp_path)])
    assert "no_such_species_was_ever_seeded" in str(exc.value), (
        "the composition raised, but not about the tombstone — the error may be incidental"
    )


def test_reason_required_is_a_subset_of_accepts_on_every_safety_row():
    """The SDK validates this, so this asserts the DECLARATION is well-formed rather than the
    validator. A row whose reason_required names a verb it does not accept would be a rule that
    can never fire — the guard-that-cannot-fire shape, in data."""
    composed = _by_kind(compose(_SEED, [str(_OVERLAY)]))
    for kind in _EXPECTED:
        row = composed[kind]
        stray = set(_reasons(row)) - set(_verbs(row))
        assert not stray, f"{kind}: reason_required names non-accepted verb(s) {sorted(stray)}"


def test_the_ordering_tripwire():
    """SELF-FIRING: goes red the moment the SDK starts guaranteeing verb order.

    WHY THIS IS A TEST AND NOT A COMMENT. The first version of this file carried a comment saying
    "when the mesh-SDK pin moves off v0.6.0, assert order directly". The pin moved — v0.7.1, all
    31 sites — and on that reading the trigger had fired. **It had not:** the ordering fix landed
    on SDK master AFTER the tag was cut, so v0.7.1 still ships `frozenset`. The comment named a
    PROXY (the pin moved) for the event it cared about (the fix shipped), and the two diverged
    within a day.

    A revisit-later note is worth exactly what the next reader's check of its trigger is worth.
    This asserts the CURRENT contract instead, so the switch announces itself.

    WHEN THIS GOES RED, that is the SDK having shipped the ordered `accepts`. Do three things:
      1. change the `accepts` comparisons above from `set(...) == set(...)` to `list(...) == [...]`
         in the DECLARED order, since order then carries meaning on the card;
      2. leave every `reason_required` comparison as a set — that field stays unordered by
         deliberate SDK design, because order is meaningless for a membership test;
      3. delete this test.
    """
    composed = _by_kind(compose(_SEED, [str(_OVERLAY)]))
    row = composed["risk_acceptance_high"]
    accepts = getattr(row, "accepts")
    assert isinstance(accepts, (frozenset, set)), (
        "`accepts` is no longer a set — the SDK now guarantees verb ORDER, which it did not when "
        "these seals were written. The set comparisons above have silently stopped checking "
        "something the SDK promises. See this test's docstring for the three steps."
    )
    # The other half of the contract, asserted so a change to EITHER field is caught rather than
    # only the one that moved first.
    assert isinstance(getattr(row, "reason_required"), (frozenset, set)), (
        "`reason_required` changed container type — it is specified to stay unordered"
    )


def test_at_least_one_declared_row_can_actually_PROVE_order():
    """THE DISCRIMINATION GUARD for the ordered assertion — from `invincible-agent-65`'s finding.

    They wrote an order seal against `risk_acceptance_high`, whose verbs are
    `[accepted, rejected, returned_for_rework]` — **already alphabetical**, so a composer that
    sorted and a composer that preserved order return the IDENTICAL tuple. The seal passed and
    measured nothing.

    IT IS WORSE IN THIS FILE THAN IN THEIRS. Seven of the eight rows in the sample overlay declare
    alphabetical verb lists:

        risk_acceptance_{high,serious,medium,low}   accepted, rejected, returned_for_rework
        risk_acceptance_concurrence_{high,serious}  concurred, not_concurred, returned_for_rework
        pcn_disposition                             approved, rejected
        hazard_link_review                          linked, new_hazard, dismissed   <- the only one

    **MOST NATURAL VERB LISTS ARE ALPHABETICAL BY ACCIDENT, WHICH IS EXACTLY WHY THIS HIDES.**
    Nobody chooses the order to be sortable; it just is, because `accept` precedes `reject` in
    both meaning and spelling.

    So this asserts the SAMPLE retains a row that can fail. Without it, reordering
    `hazard_link_review`'s verbs alphabetically — a tidy-up nobody would flag in review — would
    silently convert every ordered assertion in this file into decoration, and no seal would say
    so. That is the same shape as the tripwire two tests up: a property that quietly stops being
    checked, with nothing that runs to announce it.
    """
    composed = _by_kind(compose(_SEED, [str(_OVERLAY)]))
    discriminating = {
        kind: accepts
        for kind, (accepts, _reasons) in _EXPECTED.items()
        if list(accepts) != sorted(accepts)
    }
    assert discriminating, (
        "EVERY declared row's verbs are in alphabetical order, so an ordered comparison cannot "
        "distinguish a composer that preserves order from one that sorts. The ordering assertions "
        "in this file are decorative until a row declares a non-alphabetical order — give one of "
        "them the order a card should actually show."
    )
    # And the discriminating row must still be IN the composed set, or the guard passes on a
    # declaration the composition never returned.
    for kind in discriminating:
        assert kind in composed, (
            f"{kind} is the only row that can prove order and it is not in the composed set"
        )
