"""A resolved task stores the verb that resolved it — not `approved` or `rejected`.

THE DEFECT, found by `iagent-mesh-sdk-ca` during the M3.3 merge:

    status = decision if decision in ("approved", "acknowledged", "redriven") else "rejected"

**Four lines below a docstring that forbids it:** *"`status` carries the DECISION's own vocabulary
rather than being coerced into approved/rejected… a projection that says so is a lie the audit
trail keeps."* The rule was written and not implemented, and the allowlist happened to cover
exactly the verbs that existed when it was typed.

MEASURED against the composed declaration: **thirteen verbs are declared and the allowlist named
three.** `accepted`, `concurred`, `not_concurred`, `returned_for_rework`, `linked`, `new_hazard`,
`dismissed`, `redrafted` and `withdrawn` all stored as **REJECTED** — and under ADR-0051 a risk
ACCEPTANCE recorded as its opposite is the one act whose record IS the evidence.

**WHY NOTHING CAUGHT IT, AND THIS IS THE PART TO CARRY.** The arm meant to catch exactly this —
*"adding a species' verb without teaching the status mapping fails HERE instead of silently
recording it as rejected"* — derived its vocabulary from `_VERBS_BY_KIND`, a code table carrying
one row that never held a safety verb.

> **The seal excluded precisely the species at risk.** A fixture that cannot contain the failing
> case reports green forever, and it had been green for as long as the safety kinds existed.

That is the fixture-supplies-the-input law applied to a seal's own SOURCE rather than its input. So
this file derives its population from the **composed declaration** — seed plus overlay — which is
the same authority the verbs themselves come from, and it fails the moment a declaration adds a
verb the producer cannot store.

Run: uv run --frozen pytest tests/test_the_status_is_the_decision.py -v
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from iagent import human_tasks as ht  # noqa: E402

_HT = _REPO / "src" / "iagent" / "human_tasks.py"
#: The overlay shipped in-repo. Used ONLY to compose a realistic declaration for this seal — the
#: deployment's own overlay is elsewhere, and that is the point: the population must not be the
#: four seeded species, because those are exactly the ones the old allowlist already covered.
_SAMPLE_OVERLAY = _REPO / "policy" / "overlays" / "sample" / "task_kinds"


def _declared_union() -> set[str]:
    """Every verb any declared species accepts, seed AND overlay composed."""
    prev = os.environ.get("TASK_KIND_OVERLAY_DIRS")
    os.environ["TASK_KIND_OVERLAY_DIRS"] = str(_SAMPLE_OVERLAY)
    try:
        ht._declared_kinds.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:
        pass
    try:
        kinds = ht._declared_kinds() or {}
        return {v for k in kinds for v in ht.verbs_for_kind(k)}
    finally:
        if prev is None:
            os.environ.pop("TASK_KIND_OVERLAY_DIRS", None)
        else:
            os.environ["TASK_KIND_OVERLAY_DIRS"] = prev
        try:
            ht._declared_kinds.cache_clear()  # type: ignore[attr-defined]
        except AttributeError:
            pass


def test_THE_POPULATION_IS_PLURAL_AND_REACHES_THE_SAFETY_VERBS():
    """THE FLOOR, and it is the whole construction.

    The superseded arm was green because its population could not contain a safety verb. If this
    one composes to the four seeded species, it is the same blind seal under a new name — so it
    asserts the population actually reaches the verbs that were being mis-stored.
    """
    assert _SAMPLE_OVERLAY.is_dir(), (
        "the sample overlay is gone, so this seal composes to the SEED alone — exactly the "
        "population that could not contain the failing case"
    )
    union = _declared_union()
    assert len(union) >= 8, f"composed only {sorted(union)} — too few to discriminate"
    for verb in ("accepted", "concurred", "returned_for_rework"):
        assert verb in union, (
            f"{verb!r} is not in the composed declaration, so this seal cannot see the species "
            f"the defect was about"
        )


def test_THE_ALLOWLIST_IS_GONE():
    """The literal three-verb coercion, by name. A reader restoring it would be re-introducing a
    silent mis-record, not a simplification."""
    src = _HT.read_text(encoding="utf-8")
    assert 'decision if decision in ("approved", "acknowledged", "redriven")' not in src, (
        "the three-verb allowlist is back: every other declared verb stores as `rejected`, and "
        "a risk acceptance is recorded as its opposite"
    )
    assert re.search(r"^\s*status = decision\s*$", src, re.M), (
        "the status is no longer the decision"
    )


def test_PENDING_IS_REFUSED_because_it_is_the_only_non_terminal_value():
    """THE CONTROL ON THE WIDENING. The docstring's argument for widening is that only `pending`
    is load-bearing — the queue reads it as OPEN. Storing it as a resolution would return a
    resolved task to every queue that skips it, so the one value that must not widen is refused.

    Unreachable through `validate_decision` today, which is why it is asserted: the guard is
    against a future declaration, not against today's callers.
    """
    src = _HT.read_text(encoding="utf-8")
    i = src.index("def mark_task_resolved(")
    body = src[i:i + 3000]
    assert 'if decision == "pending":' in body, (
        "nothing refuses `pending` as a resolution; a species declaring it would silently "
        "return resolved tasks to the open queue"
    )
    assert "raise ValueError" in body


def test_EVERY_DECLARED_VERB_IS_STORABLE():
    """THE PROPERTY, asserted over the population the old arm could not reach.

    Not a list of verbs — the composed declaration itself, so a species added tomorrow with a
    verb nobody taught the producer fails HERE rather than recording as its opposite.
    """
    union = _declared_union()
    src = _HT.read_text(encoding="utf-8")
    i = src.index("def mark_task_resolved(")
    body = src[i:i + 3000]
    coerced = re.search(r'else\s+"rejected"', body)
    assert not coerced, (
        f"a coercion to `rejected` survives in the resolver, so of the {len(union)} declared "
        f"verbs only the listed ones round-trip: {sorted(union)}"
    )


def test_THE_DECISION_COLUMN_WAS_ALWAYS_RIGHT_and_that_bounded_the_damage():
    """Worth asserting because it is why this was recoverable. `decision` stored the true verb
    throughout; only `status` lied. A reader of the audit column had the truth, and no existing
    row needs repair — measured live: zero safety verbs resolved, status and decision agreeing
    in every row.

    If the two ever come from one value, this distinction disappears and a future coercion
    would corrupt both.
    """
    src = _HT.read_text(encoding="utf-8")
    i = src.index("def mark_task_resolved(")
    body = src[i:i + 3000]
    assert "decision = %s" in body, "the decision column is no longer written"
    assert "status = %s" in body, "the status column is no longer written"


@pytest.mark.parametrize("marker", ["thirteen verbs", "ADR-0051", "lie the audit trail keeps"])
def test_THE_REASONING_TRAVELS_WITH_THE_CODE(marker: str):
    """The coercion looked like a tidy normalisation and was a silent mis-record. A later reader
    reaching for `approved`/`rejected` again needs the cost at the line, not in a ruling."""
    # Case-insensitive: the comment writes "THIRTEEN verbs" in caps for emphasis, and a
    # marker that fails on CASE is asserting typography rather than that the reasoning
    # is present.
    assert marker.lower() in _HT.read_text(encoding="utf-8").lower()
