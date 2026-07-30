"""CONCURRENCY SEAL — the multiplayer review case, OBSERVED not argued.

A grouped review fans out to EVERY entitled actor in its audience (register_task
materializes one row per actor) and ANY ONE of them acts for the team. That makes
two reviewers submitting the same batch a routine event, not an exotic race — and
before this seal, "no double-dispatch because the durable promise is write-once"
was an argument BY CONSTRUCTION. The standing rule for those: observed, not
trusted ([[feedback_seals_proven_to_bite]]).

Three dishonest outcomes existed for the loser of the race:
  1. misleading 404 "task_not_found"        (it existed; a teammate settled it)
  2. hollow `accepted: true, rows_resolved: 0`  (WORST — the reviewer walks away
     believing their overrides landed, when nothing was applied)
  3. silently discarded work                 (their drafted overrides thrown away)
All three now converge on ONE honest outcome: 409 + acted_by/acted_at, drafts kept.

This file seals the WORKFLOW half (restate env):
  * exactly ONE promise resolve across two concurrent submits  -> exactly ONE wake
    -> exactly ONE fan-out (no double-dispatch of qualification tasks);
  * the second submit is REFUSED as `already_resolved`, never re-validated into a
    hollow acceptance;
  * a positive control proves the guard (not something else) is doing the work.
The 409-provenance half (`get_task_resolution`: winner identity + caller-scoping so
it can't become an existence oracle) is sealed in test_human_tasks_recipients.py,
which runs in the env that actually carries psycopg2 — test-env == image-env, so the
seal is split along the real dependency boundary rather than overlaying deps.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest --with pytest-asyncio \
        pytest ../../tests/test_grouped_review_concurrency.py -v
      (the restate SDK is a FROZEN dep of the restate_analyst project — test-env == image-env;
       only the pytest tooling is overlaid)
"""
from __future__ import annotations


import sys
from pathlib import Path
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent_fleet" / "restate_analyst"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agent_fleet.restate_analyst import grouped_review_workflow  # noqa: E402
from agent_fleet.restate_analyst.workflow_bulk_resolve import PartItem, ReviewBatch  # noqa: E402

_SUBMIT = grouped_review_workflow.submit_decision.__wrapped__

_FINGERPRINT = "IPCN25300X"
_MPN = "NSR01L30NXT5G"


# ── fakes: ONE shared state dict, so the workflow's ctx.set is visible to both
#    submitters — the whole point (a per-context copy would fake the seal green).
class _SharedPromise:
    def __init__(self, rec, name):
        self._rec, self._name = rec, name

    async def resolve(self, value):
        self._rec.append((self._name, value))


class FakeSharedContext:
    """WorkflowSharedContext stand-in over SHARED state; records promise resolves."""

    def __init__(self, state, resolved):
        self._state = state
        self.resolved = resolved          # shared ledger: every resolve, any submitter

    async def get(self, name, **kw):
        return self._state.get(name)

    def promise(self, name, type_hint=None):
        return _SharedPromise(self.resolved, name)


def _state():
    """Live workflow state for a one-part batch with a clean proposal."""
    return {
        "batch_items": [{
            "mpn": _MPN,
            "subject": f"http://internal/components/{_MPN}",
            "proposed_disposition": "dispatchQualification",
            "needs_review": False,
            "relevance": 1.0,
            "proposed_by_ruleset": "rules@abc123def456",
        }],
        "approver": "svc:review-starter",
        "notice_fingerprint": _FINGERPRINT,
        "notice_id": _FINGERPRINT,
        "doc_type": "PCN",
    }


@pytest.mark.asyncio
async def test_two_concurrent_submits_resolve_the_promise_exactly_once():
    """THE SEAL. Reviewer A and reviewer B both hold the pending task and both submit.
    A wins; the workflow consumes the decision (ctx.set('decision_consumed')); B's
    submit then sees a SETTLED batch and is refused `already_resolved` — WITHOUT
    resolving the promise a second time. One resolve == one wake == ONE fan-out, so
    the qualification tasks cannot be dispatched twice."""
    state = _state()
    resolves: list = []                        # every resolve by ANY submitter
    ctx_a = FakeSharedContext(state, resolves)
    ctx_b = FakeSharedContext(state, resolves)

    out_a = await _SUBMIT(ctx_a, {"decision": {"overrides": {}}})
    assert out_a["accepted"] is True, out_a
    assert len(resolves) == 1, f"A's submit must resolve the decision promise once: {resolves}"

    # The workflow wakes and CONSUMES the decision (what run() does right after
    # `await ctx.promise('decision').value()`), landing in the SAME shared state.
    state["decision_consumed"] = True

    out_b = await _SUBMIT(ctx_b, {"decision": {"overrides": {}}})
    assert out_b["accepted"] is False, f"B's submit must NOT be accepted: {out_b}"
    assert out_b["status"] == "already_resolved", out_b
    # THE load-bearing assertion: no SECOND resolve. A second resolve is the only way
    # a second wake (and therefore a second fan-out) could ever happen.
    assert len(resolves) == 1, (
        f"the promise was resolved {len(resolves)}x — a second wake means the batch can "
        f"fan out TWICE (double-dispatched qualification tasks): {resolves}"
    )


@pytest.mark.asyncio
async def test_second_submit_is_not_a_hollow_acceptance():
    """Outcome #2 — the worst one — is dead. A submit against a settled batch must not
    report success in any shape: not accepted, and it must NAME the condition so the
    BFF can map it to 409 (rather than the generic `still_pending` refusal, which would
    tell the reviewer to try again on a review that is over)."""
    state = _state()
    state["decision_consumed"] = True
    out = await _SUBMIT(FakeSharedContext(state, []), {"decision": {"overrides": {}}})
    assert out.get("accepted") is False
    assert out.get("status") == "already_resolved", out
    assert out.get("status") != "still_pending", "settled != pending — the reviewer must not be told to retry"
    assert "already resolved" in (out.get("reason") or "").lower()


@pytest.mark.asyncio
async def test_positive_control_unsettled_batch_still_accepts():
    """Discrimination (verification-must-be-able-to-fail): the SAME submission on a
    batch that is NOT settled is accepted and DOES resolve the promise. So the two
    tests above are detecting the `decision_consumed` guard, not a batch that was
    unsubmittable for some unrelated reason."""
    state = _state()                       # no decision_consumed
    resolves: list = []
    out = await _SUBMIT(FakeSharedContext(state, resolves), {"decision": {"overrides": {}}})
    assert out["accepted"] is True, out
    assert len(resolves) == 1


@pytest.mark.asyncio
async def test_guard_precedes_validation_so_a_settled_batch_never_re_evaluates():
    """The guard sits BEFORE evaluate_submission. A settled batch must short-circuit
    rather than re-validate — re-validation is exactly how the hollow acceptance was
    produced (valid decision -> 'accepted' -> resolve a write-once promise -> nothing
    happens -> success reported)."""
    state = _state()
    state["decision_consumed"] = True
    with mock.patch.object(grouped_review_workflow, "evaluate_submission") as ev:
        out = await _SUBMIT(FakeSharedContext(state, []), {"decision": {"overrides": {}}})
    assert out["status"] == "already_resolved"
    ev.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
