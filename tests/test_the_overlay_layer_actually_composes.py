"""The overlay branch runs — composition, tombstones, and the error that proves it ran.

ADR-0036's composition was called fleet-wide and **had never executed with an overlay**.
Measured 2026-09-12 by `invincible-agent-28` and confirmed independently:

    find . -type d -name "*overlay*"              -> nothing
    GRAPH_OVERLAY_DIRS (graph_host/main.py:78)    default ""
      set in values.yaml / any configmap?         NO

So `compose(seed, overlays)` ran with zero overlays on every deployment that has ever existed.
**The seed path was well covered; the overlay path was a branch nothing took** — and both of
this week's task-kind defects were reading a seed as if it were the whole set:

    NOT IN `_VERBS_BY_KIND`     ≠ NOT DECLARED
    NOT IN `policy/task_kinds/` ≠ NOT DECLARED     (would have killed 18 of 55 live rows)

WHY THE TOMBSTONE IS THE LOAD-BEARING TEST HERE. Composition returning the right rows is
consistent with the overlay being read *or* with the seed simply being returned — a passing
merge cannot distinguish them when the overlay only ADDS. **A tombstone for a key the seed does
not ship is an ERROR, and a seed-only read cannot produce that error.** It is the cheapest
proof the overlay branch executed rather than being skipped.

AND THE TOMBSTONE IS EXERCISED HERE RATHER THAN SHIPPED. A `deleted: true` row in
`policy/overlays/sample/` would delete a real platform species from every deployment that
points at the sample — the sample would be a live deletion wearing a fixture's clothes. So the
shipped sample only ADDS (`pcn_disposition`), and deletion is proven in a fixture.

Run: uv run --frozen pytest tests/test_the_overlay_layer_actually_composes.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SEED = _REPO / "policy" / "task_kinds"
_SAMPLE = _REPO / "policy" / "overlays" / "sample" / "task_kinds"

tk = pytest.importorskip("iagent_mesh.task_kinds", reason="the SDK is not importable here")


def _row(path: Path, kind: str, *, accepts=("approved", "rejected"), deleted=False) -> None:
    if deleted:
        path.write_text(f"kind: {kind}\ndeleted: true\n", encoding="utf-8")
        return
    path.write_text(
        f"kind: {kind}\n"
        f"renders_as:\n  badge: ACT\n  title: {kind}\n  archetype: APPROVAL_TASK\n"
        f"accepts: [{', '.join(accepts)}]\n",
        encoding="utf-8",
    )


def _kinds(result) -> set[str]:
    return {str(getattr(k, "kind", "") or "") for k in result} - {""}


# ---------------------------------------------------------------------------------------
# The shipped sample
# ---------------------------------------------------------------------------------------

def test_the_sample_overlay_EXISTS_and_is_labelled():
    """It is a fixture and must read as one. A sample that reads as production data is worse
    than no sample."""
    assert _SAMPLE.is_dir(), f"{_SAMPLE} does not exist — the overlay layer has no location"
    rows = sorted(_SAMPLE.glob("*.yaml"))
    assert rows, f"{_SAMPLE} is empty — an overlay nothing declares exercises nothing"
    for r in rows:
        assert "SAMPLE" in r.read_text(encoding="utf-8"), (
            f"{r.name} is not labelled SAMPLE in-file; a reader cannot tell the fixture from "
            f"the thing"
        )


def test_the_sample_declares_the_species_the_platform_ALREADY_RUNS():
    """`pcn_disposition` is minted live at `dispatch_plan.py:107` and had 16 rows in sandbox.
    It is absent from the seed BECAUSE the design requires it, so it is the real first customer
    of this mechanism rather than an invented one."""
    composed = _kinds(tk.compose(_SEED, [_SAMPLE]))
    assert "pcn_disposition" in composed, f"composed set is {sorted(composed)}"


def test_the_shipped_sample_only_ADDS_and_deletes_NOTHING():
    """A `deleted: true` row here would delete a real species from every deployment pointing at
    the sample — a live deletion wearing a fixture's clothes."""
    for r in _SAMPLE.glob("*.yaml"):
        assert "deleted:" not in r.read_text(encoding="utf-8"), (
            f"{r.name} carries a tombstone. The sample must only ADD; deletion is exercised in "
            f"a fixture, not shipped."
        )
    seeded = _kinds(tk.compose(_SEED, []))
    composed = _kinds(tk.compose(_SEED, [_SAMPLE]))
    assert seeded <= composed, (
        f"the sample overlay REMOVED {sorted(seeded - composed)} from the composed set"
    )


# ---------------------------------------------------------------------------------------
# The branch actually runs — proven by an error a seed-only read cannot produce
# ---------------------------------------------------------------------------------------

def test_AN_OVERLAY_ROW_MAY_DECLARE_A_VERB_THE_SEED_NEVER_HEARD_OF(tmp_path):
    """FULL REPLACEMENT BY KEY, not a field-level merge — the property ADR-0051's safety kinds
    depend on, and the one most likely to be quietly lost in a merge-shaped implementation.

    R-004(e) makes the safety acceptance verb `accepted` rather than the seed's `approved`.
    """
    _row(tmp_path / "risk_acceptance.yaml", "risk_acceptance", accepts=("accepted", "rejected"))
    composed = {k.kind: k for k in tk.compose(_SEED, [tmp_path])}
    assert "risk_acceptance" in composed
    got = set(composed["risk_acceptance"].accepts)
    assert "accepted" in got, (
        f"the overlay declared `accepted` and the composed row has {sorted(got)} — a verb the "
        f"structural seed never heard of did not survive composition"
    )
    assert "approved" not in got, (
        f"the seed's `approved` leaked into an overlay row that did not declare it: "
        f"{sorted(got)}. That is a field-level MERGE, not a replacement, and it would silently "
        f"widen every domain species."
    )


def test_A_TOMBSTONE_REMOVES_A_SEEDED_KIND(tmp_path):
    """Deletion by statement, not by forking the seed file."""
    seeded = sorted(_kinds(tk.compose(_SEED, [])))
    victim = seeded[0]
    _row(tmp_path / f"{victim}.yaml", victim, deleted=True)
    composed = _kinds(tk.compose(_SEED, [tmp_path]))
    assert victim not in composed, f"the tombstone did not remove {victim!r}: {sorted(composed)}"
    assert len(composed) == len(seeded) - 1, (
        f"the tombstone removed more than its own key: {sorted(set(seeded) - composed)}"
    )


def test_A_TOMBSTONE_FOR_AN_UNSEEDED_KEY_IS_AN_ERROR(tmp_path):
    """THE PROOF THE BRANCH RAN, and the reason this test is the point of the file.

    A tombstone that silently matches nothing is indistinguishable from one that worked, so a
    deployment would carry a deletion it never made. And **a seed-only read cannot raise this**
    — which makes it the cheapest evidence that `compose` consulted the overlay at all, rather
    than returning the seed and being believed.
    """
    _row(tmp_path / "never_seeded_anywhere.yaml", "never_seeded_anywhere", deleted=True)
    with pytest.raises(Exception) as exc:
        tk.compose(_SEED, [tmp_path])
    assert "never_seeded_anywhere" in str(exc.value), (
        f"the error does not name the key it could not delete: {exc.value}"
    )


def test_CONTROL_an_EMPTY_overlay_composes_to_exactly_the_seed(tmp_path):
    """THE CONTROL. Without it, every assertion above is consistent with `compose` mangling the
    seed — and an empty overlay directory is the shape a deployment uses to CLAIM it has no
    domain species, so it must be exactly a no-op rather than approximately one."""
    assert _kinds(tk.compose(_SEED, [tmp_path])) == _kinds(tk.compose(_SEED, []))
