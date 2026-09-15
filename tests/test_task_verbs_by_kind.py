"""TASK VERBS ARE PART OF A TASK'S MEANING — a wrong verb is REFUSED, not stored.

THE BUG THIS CLOSES (seen live 2026-07-31, screenshot). The triage task — "Notice
PCN-2683-CROPFAIL could not be prepared for review" — rendered with **Approve / Reject**,
because `extraction_refusal` was an unregistered kind and the registry's honest default is
`APPROVAL_TASK`.

Approve… the failure? The task's semantics are DISPOSITION OF A BROKEN INPUT, not a decision
on a proposal. And the cost is not awkward wording: whichever button is clicked records a
decision the data cannot represent. `acted_by: alice, decision: approved` on an extraction
failure is provenance nonsense — and ADR-0034's decision records would archive it IMMUTABLY,
as evidence, into the corpus that governs vendor promotion. Fix the verbs before the first
real click, or the trust work starts on a polluted corpus it cannot clean.

The sharper reading of the default, worth keeping: it was honest about LABELS ("TASK") and
dishonest about AFFORDANCES (`APPROVAL_TASK`). A label that says nothing is harmless; an
affordance that says nothing still offers buttons.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_task_verbs_by_kind.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ht():
    try:
        from src.iagent import human_tasks  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"human_tasks not importable here: {type(e).__name__}: {e}")
    return human_tasks


# ── the vocabulary is per species ──────────────────────────────────────────

_OVERLAY = _ROOT / "policy" / "overlays" / "sample" / "task_kinds"


def _composed(monkeypatch):
    """Make the composed set KNOWABLE for a test that asks about a species.

    After the M3.3 cutover there is no code table behind an unresolvable overlay, so a test that
    asks what a DOMAIN species accepts must say where the domain rows are — otherwise it is
    asking a question the process is right to refuse. The seeded species need nothing; this is
    for the arms that name a domain kind.
    """
    ht = _ht()
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(_OVERLAY))
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setattr(ht, "_SEED_ROWS_CACHE", None, raising=False)
    return ht


def test_a_triage_task_refuses_approve_and_reject():
    """THE REGRESSION. These are the two verbs the card actually offered, and both must be
    refused at the write — the UI is where the bug was seen, the API is where it is FIXED, so
    a future card (or a curl) cannot reintroduce it."""
    ht = _ht()
    for wrong in ("approved", "rejected"):
        with pytest.raises(ht.InvalidDecisionForKind) as exc:
            ht.validate_decision("extraction_refusal", wrong, "some comment")
        assert "cannot represent" in str(exc.value)


@pytest.mark.parametrize("verb", ["acknowledged", "redriven"])
def test_a_triage_task_accepts_its_own_verbs(verb):
    ht = _ht()
    ht.validate_decision("extraction_refusal", verb, "parts entered in the legacy system")


def test_ordinary_approvals_are_untouched(monkeypatch):
    """The ordinary vocabulary is correct for a task that IS a decision — no change here may make
    every other species stricter.

    THE CLAIM SURVIVED THE CUTOVER; ITS FIXTURE DID NOT. These verbs used to come from a code
    table and now come from declared rows, so the arm needs the composed set to be KNOWABLE
    before it can ask about `pcn_disposition` — a domain species whose row is in the overlay.
    Failing here without the overlay was the gate working, not the claim breaking.
    """
    ht = _composed(monkeypatch)
    for kind in ("workflow_ack", "access_request", "grouped_review", "pcn_disposition"):
        ht.validate_decision(kind, "approved")
        ht.validate_decision(kind, "rejected")
        with pytest.raises(ht.InvalidDecisionForKind):
            ht.validate_decision(kind, "acknowledged", "reason")


def test_an_unregistered_kind_NO_LONGER_gets_a_default(monkeypatch):
    """⛔ INVERTED AT THE M3.3 CUTOVER. This arm asserted the opposite and was right to.

    It read: "the default stays approve/reject — deliberately. The triage lesson is NOT 'default
    to nothing'; it is that a default must not assert semantics the task may not have."

    That reasoning held while a code table was the fallback for kinds no declaration covered.
    The tables are gone, so there is nothing left to default FROM — and the ruled answer for a
    species the seed does not carry, under a knowable set, is that it accepts nothing. **The
    claim was not wrong; its premise was deleted.** Kept inverted rather than removed, because
    an arm that vanishes takes its reasoning with it and the next person re-derives the default.
    """
    ht = _composed(monkeypatch)
    assert ht.verbs_for_kind("some_future_kind") == (), (
        "an undeclared species was handed verbs — the code-table default is back"
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_acknowledge_without_a_reason_is_refused(blank):
    """"Parts entered in the legacy system" and "notice withdrawn by the vendor" are entirely
    different facts about the pipeline. A bare acknowledgement erases the difference — and the
    difference is exactly the evidence ADR-0034's corpus needs. The reason field is also v1 of
    key-it-in: it covers the honest cases before the manual-entry lane exists."""
    ht = _ht()
    with pytest.raises(ht.InvalidDecisionForKind) as exc:
        ht.validate_decision("extraction_refusal", "acknowledged", blank)
    assert "REQUIRES a reason" in str(exc.value)


def test_redrive_does_not_require_a_reason():
    """Re-drive states its own reason by being re-drive: the underlying issue is fixed, try
    again. Demanding prose there is friction without information."""
    _ht().validate_decision("extraction_refusal", "redriven", "")


# ── the projection must not LIE about what happened ────────────────────────
def test_status_is_not_coerced_into_rejected():
    """An acknowledged triage task was NOT rejected, and a projection row that says so is a
    lie the audit trail keeps forever. `pending` is the only status queue queries depend on,
    so widening the terminal vocabulary is safe — while coercing is not."""
    ht = _ht()
    src = (_ROOT / "src" / "iagent" / "human_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def mark_task_resolved"):]
    body = body[:body.index("with _pg_connect")]
    assert '"approved" if decision == "approved" else "rejected"' not in body, (
        "the old coercion is back: every non-approval becomes 'rejected', so an acknowledged "
        "extraction failure is recorded as a rejection"
    )
    # ⛔ THIS ASSERTED THE ALLOWLIST CONTAINED `acknowledged` AND `redriven`. That was the right
    # check against a PARTIAL widening — the fix of the day it was written, which named the
    # verbs that existed then. It is superseded rather than wrong: there is no allowlist now,
    # so those words do not appear, and the property is stronger without them.
    #
    # THE ALLOWLIST WAS THE DEFECT, NOT ITS CONTENTS. Measured 2026-09-15 against the composed
    # declaration: THIRTEEN verbs declared, three named. Every safety verb — `accepted`,
    # `concurred`, `returned_for_rework` and the rest — stored as REJECTED, and a risk
    # acceptance recorded as its opposite is the one act under ADR-0051 whose record IS the
    # evidence. Widening a list verb-by-verb only ever covers the species someone remembered.
    assert "status = decision" in body, (
        "the status is no longer taken from the decision, so some vocabulary is being imposed "
        "on it again"
    )
    assert "else \"rejected\"" not in body, (
        "a coercion to 'rejected' survives in any form; the declaration is the only source of "
        "what a species accepts and the projection must record what it was given"
    )
    # The one value that must NOT widen, because the queue reads it as OPEN.
    assert 'if decision == "pending":' in body


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LIVE DEFECT, PRE-EXISTING, NOT MINE TO FIX — declared rather than hidden. "
        "`mark_task_resolved` maps `status = decision if decision in (approved, acknowledged, "
        "redriven) else 'rejected'`, so EVERY safety verb (accepted, concurred, not_concurred, "
        "returned_for_rework, linked, new_hazard, dismissed) is stored as 'rejected' — a risk "
        "ACCEPTANCE recorded as its opposite. Identical on origin/master before this cutover. "
        "The fix is cross-repo: cortex-ui's card types task_state as "
        "pending|approved|rejected|expired, so new statuses need that contract to move first. "
        "STRICT so the day it is fixed this XPASSes, fails, and forces the marker's removal."
    ),
)
def test_every_declared_verb_survives_the_status_mapping():
    """Derived from the vocabulary rather than hand-listed, so adding a species' verb without
    teaching the status mapping fails HERE instead of silently recording it as 'rejected'.

    AND ITS OLD SOURCE IS WHY NOBODY SAW THE DEFECT. It derived from `_VERBS_BY_KIND`, which
    carried one row and never held a safety verb — so the arm whose whole purpose was "a new
    verb must not be silently recorded as rejected" **excluded exactly the species at risk**.
    A fixture that cannot contain the failing case reports green forever. Re-sourced to the
    declared rows, it found the defect on its first run."""
    ht = _ht()
    src = (_ROOT / "src" / "iagent" / "human_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def mark_task_resolved"):]
    body = body[:body.index("with _pg_connect")]
    # DERIVED FROM THE DECLARED ROWS, not from a code table — same property, new source. The
    # point of the arm is unchanged: adding a species' verb without teaching the status mapping
    # must fail HERE rather than silently record the decision as "rejected".
    import yaml  # noqa: PLC0415

    declared = set()
    for d in (_ROOT / "policy" / "task_kinds", _OVERLAY):
        for f in sorted(d.glob("*.yaml")):
            row = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            declared |= set(row.get("accepts") or ())
    assert declared, "derived no verbs from the declarations — the source moved, not the property"
    for verb in declared - {"rejected"}:
        assert verb in body, (
            f"verb {verb!r} is declared for some task kind but the status mapping in "
            f"mark_task_resolved does not mention it — it would be stored as 'rejected'"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
