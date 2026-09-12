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
        # COMPARED AS SETS, AND THAT IS A FINDING RATHER THAN A CONVENIENCE. The composer does
        # not preserve declared order: `[accepted, rejected, returned_for_rework]` comes back as
        # `['returned_for_rework', 'accepted', 'rejected']`. Asserting order would be asserting an
        # implementation detail the SDK does not guarantee, and the seal would break on an
        # unrelated change. Recorded because cortex renders buttons FROM `accepts`, so **button
        # order is not expressible in a declaration today** — if it ever needs to be, that is an
        # SDK change and not something a row can say.
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
