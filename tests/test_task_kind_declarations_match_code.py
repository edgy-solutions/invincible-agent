"""THE CUTOVER SEAL — written BEFORE the cutover, so deleting the code table is safe.

M3.3 retires two hardcoded per-kind tables: this repo's ``_VERBS_BY_KIND`` (what a species may
DO) and cortex-ui's ``taskKindRegistry`` (how it RENDERS). They retire together, because a
served declaration that says how a task renders while a code table still decides what it can do
is the worse half surviving.

This file seals the half that lives here. It asserts the declarations in ``policy/task_kinds/``
say EXACTLY what the code says today — both directions, because containment is not equality:
a declaration set that covers every code row could still add species the code never had, and a
code table could carry a row no declaration mentions. One direction proves neither.

WHAT "SAFE TO DELETE" MEANS. Green here means the declaration is a faithful restatement, so the
day ``_VERBS_BY_KIND`` is deleted the behaviour does not move. On that day this file flips to
reading the declaration ALONE and the comparison arms below are removed — they exist only for
the interval where both are present.

DELIBERATELY NOT SDK-DEPENDENT. ``iagent_mesh.task_kinds`` is pinned in this repo at a version
that predates the module, so a seal importing it would SKIP — and a skipped cutover seal is
indistinguishable from a passing one at exactly the moment it matters. The comparison needs
only the DATA, so it reads the YAML directly. The separate validation arm at the bottom is the
one that legitimately waits on the pin, and it says so out loud rather than skipping quietly.

ONE DIVERGENCE IS DELIBERATE AND IS ASSERTED AS SUCH — the undeclared default. See
``test_the_undeclared_default_is_deliberately_narrowed``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from iagent.human_tasks import _DEFAULT_VERBS, _REASON_REQUIRED, _VERBS_BY_KIND

_DECL_DIR = Path(__file__).resolve().parents[1] / "policy" / "task_kinds"

#: Kinds the CODE table gives non-default verbs to. Every one must be declared, and agree.
#: A kind absent from ``_VERBS_BY_KIND`` rides ``_DEFAULT_VERBS`` — which the declarations
#: restate explicitly per row, because a row that must state its verbs cannot inherit the
#: wrong ones silently.


def _declarations() -> dict[str, dict]:
    rows = {}
    for f in sorted(_DECL_DIR.glob("*.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert raw, f"{f.name} is empty — an empty declared row is not a row"
        rows[raw["kind"]] = raw
    return rows


def test_there_are_declarations_at_all():
    """THE POSITIVE CONTROL. Every comparison below is vacuously true over an empty set, so a
    missing or misplaced directory would turn this whole file green while proving nothing."""
    decls = _declarations()
    assert decls, f"no declarations found under {_DECL_DIR}"
    assert len(decls) >= 4, f"expected the seeded species, found {sorted(decls)}"


def test_no_domain_name_entered_the_platform_seed():
    """GENERIC AT BIRTH, asserted rather than trusted. Domain species belong in a work-side
    overlay; the boundary is structural precisely because nothing here may carry a domain name.
    This is the assertion that keeps it structural once people are adding rows routinely."""
    forbidden = ("pcn", "pdn")
    for kind, raw in _declarations().items():
        blob = yaml.safe_dump(raw).lower()
        for token in forbidden:
            assert token not in blob.replace("unprocessable", ""), (
                f"declaration {kind!r} carries the domain token {token!r} — domain species "
                f"belong in an overlay, not in the platform seed"
            )


def test_every_code_row_is_declared_and_agrees():
    """DIRECTION 1 — the code table is covered by the declarations."""
    decls = _declarations()
    for kind, verbs in _VERBS_BY_KIND.items():
        assert kind in decls, (
            f"_VERBS_BY_KIND declares {kind!r} but no declaration does — deleting the code "
            f"table would silently give this species the default verbs"
        )
        assert frozenset(decls[kind]["accepts"]) == frozenset(verbs), (
            f"{kind!r}: declaration says {sorted(decls[kind]['accepts'])}, "
            f"code says {sorted(verbs)}"
        )


def test_every_declared_kind_not_in_the_code_table_restates_the_default():
    """DIRECTION 2 — the declarations add nothing the code did not do.

    A species absent from ``_VERBS_BY_KIND`` accepts ``_DEFAULT_VERBS`` today. Its declaration
    must say exactly that, in its own row: same behaviour, stated rather than inherited. A row
    that quietly said something else would move behaviour on the day the table is deleted.
    """
    for kind, raw in _declarations().items():
        if kind in _VERBS_BY_KIND:
            continue
        assert frozenset(raw["accepts"]) == frozenset(_DEFAULT_VERBS), (
            f"{kind!r} is not in _VERBS_BY_KIND, so it accepts {sorted(_DEFAULT_VERBS)} today, "
            f"but its declaration says {sorted(raw['accepts'])} — the cutover would move it"
        )


def test_reason_required_agrees_with_the_code():
    """The third code table nobody counts: which verbs are empty without a stated reason."""
    decls = _declarations()
    declared = {
        v
        for raw in decls.values()
        for v in (raw.get("reason_required") or [])
    }
    reachable = {
        v for v in _REASON_REQUIRED
        if any(v in (raw.get("accepts") or []) for raw in decls.values())
    }
    assert declared == reachable, (
        f"reason-required verbs disagree: declarations say {sorted(declared)}, "
        f"code says {sorted(reachable)} (of _REASON_REQUIRED={sorted(_REASON_REQUIRED)})"
    )


def test_reason_required_is_reachable_in_every_row():
    """A reason demanded for a verb the species does not accept is a rule that READS as
    enforced and never fires."""
    for kind, raw in _declarations().items():
        stray = set(raw.get("reason_required") or []) - set(raw["accepts"])
        assert not stray, f"{kind!r} requires a reason for unaccepted verbs {sorted(stray)}"


def test_the_undeclared_default_is_deliberately_narrowed():
    """THE ONE DIVERGENCE, asserted so it is a decision rather than drift.

    Today an UNDECLARED kind gets ``_DEFAULT_VERBS`` here — and the UI hands it Approve/Reject
    too, because its default archetype renders an approval card unconditionally. So this is not
    two safe behaviours being unified; it is a LIVE HOLE on both sides, and the declaration
    model closes it by giving an undeclared species no verbs at all.

    (An earlier version of this docstring said the UI degraded to read-only. It does not. That
    claim came from a comment above the UI's default asserting a no-verb mode that was never
    built — the cause was addressed, the effect never changed, and reading the note instead of
    tracing the render propagated the error into this repo. Traced 2026-09-09.)

    So the cutover CHANGES behaviour here, in the honest direction, and this test is where that
    is written down. It fails the day someone re-widens the default, which would reopen the hole
    silently.
    """
    assert _DEFAULT_VERBS == frozenset({"approved", "rejected"}), (
        "the code default moved — re-read the cutover note before changing this"
    )
    declared_kinds = set(_declarations())
    assert "undeclared" not in declared_kinds, (
        "the undeclared default is a property of the resolver, never a seeded row — a row "
        "named 'undeclared' would make the fallback look declared"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BLOCKED ON THE SDK PIN. iagent_mesh.task_kinds ships after the pinned v0.5.0, so this "
        "arm cannot run yet. STRICT on purpose: the day the pin bumps this XPASSes, strict "
        "turns that into a failure, and whoever bumped it must delete this marker. A plain "
        "skip would sit here green forever and the rows would never get validated at all."
    ),
)
def test_declarations_validate_against_the_sdk_models():
    """The arm that legitimately waits on the SDK pin — and FAILS LOUD, never skips, if the
    module is present but the rows it is responsible for are invalid."""
    from iagent_mesh.task_kinds import load_task_kinds

    kinds = load_task_kinds(_DECL_DIR)
    assert {k.kind for k in kinds} == set(_declarations())
