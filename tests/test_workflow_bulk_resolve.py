"""PCN/PDN bulk-resolve grouped-review core sealed deterministically (ADR-0029 Case-2 extension).

The dual of the Slice-5 join (1-approval-resolves-N), and its four seals:
  Seal 1  honest funnel — nothing vanishes; auto-disposed items stay countable.
  §3      needs_review (weak extraction provenance) takes NO automated lane, and a resolution
          carries the flag forward — a disposition never launders an unverified MPN read.
  Seal 2  grouped review is per-approver-filtered (existence-oracle at batch scale).
  §5      capture-why on override is structural; a row with no disposition cannot be resolved.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_workflow_bulk_resolve.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.workflow_bulk_resolve import (  # noqa: E402
    PartItem, Override, BulkDecision, ReviewBatch,
    run_funnel, grouped_review, resolve_batch,
)


def _part(mpn, *, relevance=1.0, disp="dispatchLTB", needs_review=False, subject=None):
    return PartItem(mpn=mpn, relevance=relevance, subject=subject,
                    proposed_disposition=disp, needs_review=needs_review)


# ---------------------------------------------------------------------------
# Seal 1 — honest funnel: nothing vanishes, auto-disposed stays countable
# ---------------------------------------------------------------------------

def test_funnel_conserves_every_item():
    items = [_part("A", relevance=0.1),           # filtered (not affected)
             _part("B", relevance=0.9),           # residue
             _part("C", relevance=0.9)]           # auto-disposed
    res = run_funnel(items, relevance_floor=0.5, auto_dispose_when=lambda it: it.mpn == "C")
    assert res.counts()["input"] == 3
    assert len(res.filtered) + len(res.auto_disposed) + len(res.residue) == 3  # conservation
    assert [p.mpn for p in res.filtered] == ["A"]
    assert [p.mpn for p in res.auto_disposed] == ["C"]       # countable, not hidden
    assert [p.mpn for p in res.residue] == ["B"]


def test_auto_disposed_items_are_inspectable():
    """Auto-disposed items are returned in full, not just tallied — honest at business scale."""
    items = [_part(f"P{i}", relevance=0.9) for i in range(50)]
    res = run_funnel(items, relevance_floor=0.5, auto_dispose_when=lambda _it: True)
    assert res.counts()["auto_disposed"] == 50
    assert all(isinstance(p, PartItem) for p in res.auto_disposed)  # the actual items, inspectable


# ---------------------------------------------------------------------------
# §3-rule-1 — weak extraction provenance takes NO automated lane
# ---------------------------------------------------------------------------

def test_needs_review_forced_to_residue_not_auto_disposed():
    """A needs_review part that WOULD auto-dispose is forced to human residue instead — you cannot
    silently archive a part whose MPN you are not sure you read."""
    items = [_part("A", relevance=0.9, needs_review=True)]
    res = run_funnel(items, relevance_floor=0.5, auto_dispose_when=lambda _it: True)
    assert [p.mpn for p in res.residue] == ["A"]
    assert res.auto_disposed == []
    assert [p.mpn for p in res.review_forced] == ["A"]


def test_needs_review_not_filtered_even_below_relevance():
    """An uncertain read must not be dropped as 'not relevant' — the relevance decision itself is
    unreliable when the MPN is unsure. It goes to a human, not the filtered bucket."""
    items = [_part("A", relevance=0.0, needs_review=True)]
    res = run_funnel(items, relevance_floor=0.5)
    assert [p.mpn for p in res.residue] == ["A"] and res.filtered == []


# ---------------------------------------------------------------------------
# Seal 2 — grouped review is per-approver-filtered (existence-oracle at batch scale)
# ---------------------------------------------------------------------------

_RESIDUE = [_part("1"), _part("2"), _part("3"), _part("4")]
# alice can act on 1,2,3 ; bob can act on 3,4
_ACL = {"alice": {"1", "2", "3"}, "bob": {"3", "4"}}
_can_act = lambda who, it: it.mpn in _ACL[who]


def test_two_approvers_get_different_batches_same_notice():
    a = grouped_review(_RESIDUE, "alice", can_act=_can_act)
    b = grouped_review(_RESIDUE, "bob", can_act=_can_act)
    assert {p.mpn for p in a.items} == {"1", "2", "3"}
    assert {p.mpn for p in b.items} == {"3", "4"}          # different size, correctly
    assert "3" in {p.mpn for p in a.items} & {p.mpn for p in b.items}  # shared item both see


def test_items_an_approver_cannot_act_on_are_withheld_not_leaked():
    """bob's batch excludes 1,2 (alice's exclusives) observer-facing; they live only in the audit
    record — existence-oracle closed at batch scale."""
    b = grouped_review(_RESIDUE, "bob", can_act=_can_act)
    assert "1" not in {p.mpn for p in b.items} and "2" not in {p.mpn for p in b.items}
    assert {p.mpn for p in b.audit_withheld} == {"1", "2"}   # audit sees them; the approver does not


def test_grouped_review_fails_closed_on_empty_acl():
    empty = grouped_review(_RESIDUE, "carol", can_act=lambda _w, _i: False)
    assert empty.items == [] and len(empty.audit_withheld) == 4


# ---------------------------------------------------------------------------
# §1 execution grain + §3-rule-2 carry-forward
# ---------------------------------------------------------------------------

def test_one_decision_yields_per_item_idempotent_resolutions():
    batch = ReviewBatch(approver="alice", items=[_part("A"), _part("B")])
    res = resolve_batch(batch, BulkDecision(), notice_fingerprint="PCN23_0120")
    assert len(res) == 2                                   # one action, N resolutions
    assert res[0].idempotency_key == "PCN23_0120:A"        # per-item execution grain
    assert res[1].idempotency_key == "PCN23_0120:B"
    assert all(r.disposition == "dispatchLTB" for r in res)  # accept-all system-proposed


def test_needs_review_cannot_ride_accept_all():
    """The laundering seal: an unverified part is a MANDATORY EXCEPTION. accept-all (an empty/default
    decision) may NOT sweep it in — a human would 'review' it by not noticing it in a batch. It blocks
    the whole batch until individually dispositioned, exactly like a no-disposition row."""
    batch = ReviewBatch(approver="alice", items=[_part("A", needs_review=True)])
    with pytest.raises(ValueError):
        resolve_batch(batch, BulkDecision(), notice_fingerprint="PCN1")


def test_needs_review_resolves_when_individually_dispositioned_and_carries_flag():
    """Handled with an explicit override (the reason records the verification), it resolves AND the
    durable resolution still carries needs_review forward — the extraction's uncertainty is never
    dropped, even once a human has verified it."""
    batch = ReviewBatch(approver="alice", items=[_part("A", disp="dispatchLTB", needs_review=True)])
    decision = BulkDecision(overrides={"A": Override("dispatchLTB", "MPN verified against datasheet")})
    res = resolve_batch(batch, decision, notice_fingerprint="PCN1")
    assert res[0].needs_review is True
    assert res[0].override_reason == "MPN verified against datasheet"


def test_verified_parts_still_ride_accept_all():
    """The seal is specific to unverified parts — a normal part with a proposed disposition still
    resolves on the default path (accept-all is not broken for the common case)."""
    batch = ReviewBatch(approver="alice", items=[_part("A"), _part("B", needs_review=False)])
    res = resolve_batch(batch, BulkDecision(), notice_fingerprint="PCN1")
    assert len(res) == 2 and all(r.needs_review is False for r in res)


# ---------------------------------------------------------------------------
# §5 — capture-why is structural; no-disposition refuses
# ---------------------------------------------------------------------------

def test_override_requires_reason_at_the_type_level():
    """capture-why cannot be skipped: Override has no default reason, so an override without a
    reason is not even constructible."""
    with pytest.raises(TypeError):
        Override(disposition="dispatchAltSourcing")  # type: ignore[call-arg]


def test_override_reason_non_empty_floor_enforced_in_core():
    """The floor is server-side, not just the UI: a blank/whitespace reason is rejected at
    construction. (The core holds ONLY the non-empty floor — reason QUALITY is Decision-D governance,
    not a validation rule in the lifecycle core.)"""
    with pytest.raises(ValueError):
        Override(disposition="dispatchAltSourcing", reason="   ")


def test_override_disposition_and_reason_carried_forward():
    batch = ReviewBatch(approver="alice", items=[_part("A", disp="dispatchLTB")])
    decision = BulkDecision(overrides={"A": Override("dispatchAltSourcing", "second source qualified")})
    res = resolve_batch(batch, decision, notice_fingerprint="PCN1")
    assert res[0].disposition == "dispatchAltSourcing"
    assert res[0].override_reason == "second source qualified"


def test_row_with_no_disposition_and_no_override_refuses():
    batch = ReviewBatch(approver="alice", items=[_part("A", disp=None)])
    with pytest.raises(ValueError):
        resolve_batch(batch, BulkDecision(), notice_fingerprint="PCN1")


def test_no_disposition_but_override_resolves():
    """The exception path: a row the system couldn't propose for is resolvable IF the human
    overrides it (with a reason) — the override supplies the missing disposition."""
    batch = ReviewBatch(approver="alice", items=[_part("A", disp=None)])
    decision = BulkDecision(overrides={"A": Override("dispatchQualification", "manual triage")})
    res = resolve_batch(batch, decision, notice_fingerprint="PCN1")
    assert res[0].disposition == "dispatchQualification" and res[0].override_reason == "manual triage"
