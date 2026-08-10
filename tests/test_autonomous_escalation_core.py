"""AUTONOMOUS DISPATCH vs ESCALATION — the pure core, discriminated.

The autonomous path (workflow 2) is "workflow 1 minus `human_await`", with the ruleset's PROPOSAL
standing where the human's submission stood. Two things had to be true for that reuse to be honest,
and both were verified by reading the working path rather than its docstrings:

  * `resolve_batch` ALREADY implements accept-all-with-exceptions — with no override for an MPN it
    takes `it.proposed_disposition`. So the "proposal function" is not a function: it is the EMPTY
    decision, `BulkDecision(overrides={})`, reachable from `raw_decision = {}`.
  * `ItemResolution` carries NO human-only field. `override_reason` is Optional/None; the other
    provenance field is `proposed_by_ruleset` — the policy artifact — which is exactly what an
    autonomous run populates.

THE GRAIN IS THE NOTICE, NOT THE ROW, and that is the correction this file pins. `resolve_batch`
RAISES on the first offending row and returns NO resolutions — "this blocks the whole batch until it
is handled". So a notice dispatches autonomously only when EVERY row is cleanly proposed; one
unverified or undispositioned row escalates the WHOLE notice. Coverage is total, autonomy is
conditional at notice grain, provenance discriminates.

AND THE REFUSAL PRECEDES ANY DISPATCH, which is what makes escalation a pure re-route: a refused
notice has dispatched NOTHING, so nothing has to be compensated or unwound.

Run:  uv run --frozen python -m pytest tests/test_autonomous_escalation_core.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_RA = _ROOT / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.workflow_bulk_resolve import (  # noqa: E402
    BatchRefusal, BulkDecision, ItemResolution, Override, PartItem, ReviewBatch, resolve_batch,
)
from agent_fleet.restate_analyst.review_starter import (  # noqa: E402
    ESCALATION_MARKER, escalation_request_key,
)

_FP = "IPCN25300X"


def _batch(*items) -> ReviewBatch:
    return ReviewBatch(approver="svc:review-starter", items=list(items))


def _clean(mpn="MPN-A", disp="dispatchQualification"):
    return PartItem(mpn=mpn, proposed_disposition=disp, needs_review=False,
                    subject=f"http://internal/components/{mpn}", proposed_by_ruleset="rules@abc")


# THE AUTONOMOUS DECISION. Not a function — the empty case of the existing type.
AUTONOMOUS = BulkDecision(overrides={})


# ===========================================================================
# THE CLEAN PATH — a proposal dispatches, carrying policy provenance
# ===========================================================================
def test_a_fully_clean_notice_resolves_from_PROPOSALS_with_no_human_input():
    res = resolve_batch(_batch(_clean("MPN-A"), _clean("MPN-B")), AUTONOMOUS, notice_fingerprint=_FP)
    assert [r.mpn for r in res] == ["MPN-A", "MPN-B"]
    assert all(r.disposition == "dispatchQualification" for r in res)
    assert all(r.override_reason is None for r in res), "no human override exists on this path"
    assert all(r.proposed_by_ruleset == "rules@abc" for r in res), (
        "the POLICY ARTIFACT that proposed the disposition must survive into the resolution — it is "
        "the audit trail that outlives a ruleset change")


def test_the_idempotency_key_is_the_one_the_dispatcher_already_uses():
    """`notice_fingerprint:mpn` — the per-item exactly-once key the kill-seal proved. Reuse means
    the autonomous path inherits that machinery rather than inventing a weaker one."""
    res = resolve_batch(_batch(_clean("MPN-A")), AUTONOMOUS, notice_fingerprint=_FP)
    assert res[0].idempotency_key == f"{_FP}:MPN-A"


# ===========================================================================
# THE ESCALATION PATH — notice grain, and NOTHING dispatched
# ===========================================================================
def test_ONE_needs_review_row_refuses_the_WHOLE_notice():
    """THE GRAIN CORRECTION. Not "the clean rows dispatch and the flagged one escalates" — the
    entire notice refuses. Which the domain wants: dispositions interact (a replacement decision is
    made in view of another row's last-time-buy), so splitting a notice would hand the reviewer
    partial context and give one notice two interleaved provenances mid-flight."""
    b = _batch(_clean("MPN-A"), PartItem(mpn="MPN-BAD", proposed_disposition="dispatchLTB",
                                         needs_review=True), _clean("MPN-C"))
    with pytest.raises(BatchRefusal) as ei:
        resolve_batch(b, AUTONOMOUS, notice_fingerprint=_FP)
    assert "MPN-BAD" in str(ei.value)
    assert "unverified" in str(ei.value)


def test_a_row_with_NO_disposition_refuses_the_whole_notice():
    b = _batch(_clean("MPN-A"), PartItem(mpn="MPN-NODISP", proposed_disposition=None))
    with pytest.raises(BatchRefusal) as ei:
        resolve_batch(b, AUTONOMOUS, notice_fingerprint=_FP)
    assert "no system-proposed disposition" in str(ei.value)


def test_a_refused_notice_produced_NO_resolutions_at_all():
    """THE ZERO-COMPENSATION PROPERTY, pinned. The refusal precedes any dispatch, so escalation is a
    pure re-route with nothing to unwind — the structural advantage refuse-before-dispatch has over
    a conditional step placed after some steps have already run."""
    b = _batch(_clean("MPN-A"), PartItem(mpn="MPN-BAD", needs_review=True,
                                         proposed_disposition="dispatchLTB"))
    got = None
    try:
        got = resolve_batch(b, AUTONOMOUS, notice_fingerprint=_FP)
    except BatchRefusal:
        pass
    assert got is None, "resolve_batch returned resolutions on a refusal — a partial dispatch is now possible"


def test_the_human_path_can_still_dispatch_the_same_notice_with_an_override():
    """The escalation has somewhere to GO. The identical batch that refuses autonomously resolves
    for a human who dispositions the flagged row explicitly — which is what makes escalation a route
    rather than a dead end."""
    b = _batch(_clean("MPN-A"), PartItem(mpn="MPN-BAD", needs_review=True,
                                         proposed_disposition="dispatchLTB"))
    human = BulkDecision(overrides={"MPN-BAD": Override(disposition="dispatchLTB",
                                                        reason="verified against the PDF table")})
    res = resolve_batch(b, human, notice_fingerprint=_FP)
    assert len(res) == 2
    flagged = next(r for r in res if r.mpn == "MPN-BAD")
    assert flagged.override_reason == "verified against the PDF table"
    assert flagged.needs_review is True, (
        "needs_review must be carried FORWARD even once overridden — a disposition never launders "
        "an unverified read")


# ===========================================================================
# THE TYPE — escalation must not become an error sink
# ===========================================================================
def test_designed_refusals_are_TYPED():
    b = _batch(PartItem(mpn="X", needs_review=True, proposed_disposition="d"))
    with pytest.raises(BatchRefusal):
        resolve_batch(b, AUTONOMOUS, notice_fingerprint=_FP)


def test_the_type_stays_a_ValueError_so_workflow_1_is_UNCHANGED():
    """`evaluate_submission` catches ValueError and maps it to a refused Submission. Subclassing
    keeps BOTH its callers — submit_decision's pre-wake validator and the post-wake check —
    byte-identical. The typing is ADDITIVE; only the autonomous path narrows."""
    assert issubclass(BatchRefusal, ValueError)


def test_a_NON_designed_error_is_NOT_a_BatchRefusal():
    """THE ERROR-SINK GUARD, and the reason the type exists at all. A genuine defect that happens to
    raise ValueError must NOT be escalated — that would convert bugs into human workload, each
    phantom review looking exactly like policy working. The mirror of the retry misclassification:
    there a permanent error was retried sixteen times; here a defect would be filed forever."""
    assert not isinstance(ValueError("some unrelated bug"), BatchRefusal)
    # And the blank-reason override guard is a HUMAN-path refusal, unreachable from the autonomous
    # decision (which carries no overrides) — recorded so its type is a deliberate scope choice.
    with pytest.raises(ValueError) as ei:
        Override(disposition="d", reason="   ")
    assert not isinstance(ei.value, BatchRefusal)


# ===========================================================================
# THE ESCALATED ADMISSION'S IDENTITY — derived, or swallowed
# ===========================================================================
def test_the_escalated_key_DIFFERS_from_the_original():
    """THE LEG-3 COLLISION, in production shape. Same request_key + same approver => the BFF's
    ingress idempotency key is identical => Restate ATTACHES the escalation to the autonomous
    invocation and returns ITS result. The escalation is swallowed and the notice dropped, silently."""
    orig = "epoch|abc123-sustainment/inbound/x/review.json"
    esc = escalation_request_key(orig, "inv_REFUSED123")
    assert esc != orig, "the escalation would dedup onto the admission that just refused it"
    assert ESCALATION_MARKER in esc


def test_the_escalated_key_POINTS_BACK_at_the_refusing_run():
    """Distinct is not enough — a fresh random identity would also be distinct and would lose the
    chain. The record must be able to say WHICH run refused."""
    esc = escalation_request_key("orig-key", "inv_REFUSED123")
    assert "orig-key" in esc and "inv_REFUSED123" in esc


def test_escalating_the_same_run_twice_is_IDEMPOTENT():
    """Restate replays. A derivation that varied per call would mint a SECOND review for one notice
    on replay — the duplicate-into-a-human-queue failure this codebase already refuses elsewhere."""
    a = escalation_request_key("orig", "inv_X")
    b = escalation_request_key("orig", "inv_X")
    assert a == b


def test_escalating_WITHOUT_naming_the_refusing_run_REFUSES():
    """An escalation that cannot name its refusing run collapses onto the original key — i.e. it
    silently becomes the swallowed case. Refuse rather than mint an ambiguous identity."""
    with pytest.raises(ValueError) as ei:
        escalation_request_key("orig", "")
    assert "swallowed" in str(ei.value)


def test_two_DIFFERENT_refusing_runs_yield_different_escalations():
    assert escalation_request_key("orig", "inv_A") != escalation_request_key("orig", "inv_B")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
