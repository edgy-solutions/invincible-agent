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


def test_ordinary_approvals_are_untouched():
    """The default vocabulary is correct for a task that IS a decision — this change must not
    make every other task species stricter."""
    ht = _ht()
    for kind in ("workflow_ack", "access_request", "grouped_review", "pcn_disposition"):
        ht.validate_decision(kind, "approved")
        ht.validate_decision(kind, "rejected")
        with pytest.raises(ht.InvalidDecisionForKind):
            ht.validate_decision(kind, "acknowledged", "reason")


def test_an_unregistered_kind_keeps_the_approve_reject_default():
    """The default stays approve/reject — deliberately. The triage lesson is NOT 'default to
    nothing'; it is that a default must not assert semantics the task may not have, which is
    handled by registering species that differ, and (UI side) by an archetype that refuses to
    guess affordances."""
    ht = _ht()
    assert ht.verbs_for_kind("some_future_kind") == frozenset({"approved", "rejected"})


# ── reason-required is a MEANING requirement, not a form nicety ────────────
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
    assert "acknowledged" in body and "redriven" in body


def test_every_declared_verb_survives_the_status_mapping():
    """Derived from the vocabulary rather than hand-listed, so adding a species' verb without
    teaching the status mapping fails HERE instead of silently recording it as 'rejected'."""
    ht = _ht()
    src = (_ROOT / "src" / "iagent" / "human_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def mark_task_resolved"):]
    body = body[:body.index("with _pg_connect")]
    declared = set()
    for verbs in list(ht._VERBS_BY_KIND.values()) + [ht._DEFAULT_VERBS]:
        declared |= set(verbs)
    for verb in declared - {"rejected"}:
        assert verb in body, (
            f"verb {verb!r} is declared for some task kind but the status mapping in "
            f"mark_task_resolved does not mention it — it would be stored as 'rejected'"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
