"""Multi-approval join lifecycle sealed deterministically (ADR-0029 Slice 5).

The join arithmetic, and — the point of the slice — the suspend-vs-fail discipline for joins:
a join that can STILL complete is PENDING (suspend); the instant it can NEVER complete it is
UNSATISFIABLE (terminate), never a stuck-suspended (parked) execution.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_workflow_join.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.workflow_join import (  # noqa: E402
    Approval, evaluate_join, COMPLETE, JOIN_PENDING, UNSATISFIABLE,
)


def _apps(g=0, d=0, p=0):
    return ([Approval(f"g{i}", "granted") for i in range(g)]
            + [Approval(f"d{i}", "denied") for i in range(d)]
            + [Approval(f"p{i}", "pending") for i in range(p)])


# ---------------------------------------------------------------------------
# all_of (threshold = number of required approvers)
# ---------------------------------------------------------------------------

def test_all_of_all_granted_complete():
    js = evaluate_join(_apps(g=3), threshold=3)
    assert js.state == COMPLETE and js.action == "proceed"


def test_all_of_one_denied_is_unsatisfiable_not_pending():
    """A required approver denied -> the join can never reach all-of -> UNSATISFIABLE (terminate),
    NOT a workflow parked forever awaiting an approval that will never come."""
    js = evaluate_join(_apps(g=2, d=1), threshold=3)
    assert js.state == UNSATISFIABLE and js.action == "terminate"


def test_all_of_partial_still_pending():
    js = evaluate_join(_apps(g=1, p=2), threshold=3)
    assert js.state == JOIN_PENDING and js.action == "suspend"


# ---------------------------------------------------------------------------
# n_of (threshold = n, over a larger pool)
# ---------------------------------------------------------------------------

def test_n_of_met_even_with_a_denial():
    """2-of-3: two grants meet the threshold even though the third denied -> COMPLETE."""
    js = evaluate_join(_apps(g=2, d=1), threshold=2)
    assert js.state == COMPLETE


def test_n_of_pending_when_still_satisfiable():
    js = evaluate_join(_apps(g=1, p=2), threshold=2)
    assert js.state == JOIN_PENDING


def test_n_of_unsatisfiable_when_too_many_denied():
    js = evaluate_join(_apps(g=1, d=2), threshold=2)  # granted+pending=1 < 2
    assert js.state == UNSATISFIABLE


# ---------------------------------------------------------------------------
# Misconfiguration + vacuous
# ---------------------------------------------------------------------------

def test_threshold_above_approvers_is_unsatisfiable_from_start():
    js = evaluate_join(_apps(g=1, p=1), threshold=5)
    assert js.state == UNSATISFIABLE  # fails loud, never parks awaiting the impossible


def test_zero_threshold_is_vacuously_complete():
    assert evaluate_join(_apps(), threshold=0).state == COMPLETE


# ---------------------------------------------------------------------------
# THE DoS boundary — the exact PENDING -> UNSATISFIABLE tipping point
# ---------------------------------------------------------------------------

def test_dos_boundary_flip_suspend_to_terminate():
    """2-of-3. State 1: 1 granted, 1 pending, 1 denied -> granted+pending=2 >= 2 -> PENDING (suspend;
    still reachable). State 2: that last approver DENIES -> 1 granted, 2 denied -> granted+pending=1
    < 2 -> UNSATISFIABLE (terminate). The moment it becomes impossible it flips off suspend — it does
    NOT remain parked. This is the whole slice."""
    still_reachable = evaluate_join(_apps(g=1, d=1, p=1), threshold=2)
    assert still_reachable.state == JOIN_PENDING and still_reachable.action == "suspend"

    now_impossible = evaluate_join(_apps(g=1, d=2, p=0), threshold=2)
    assert now_impossible.state == UNSATISFIABLE and now_impossible.action == "terminate"


def test_counts_reported_for_observability():
    js = evaluate_join(_apps(g=1, d=1, p=1), threshold=2)
    assert (js.granted, js.denied, js.pending, js.threshold) == (1, 1, 1, 2)


# ---------------------------------------------------------------------------
# THE TIME DIMENSION — the oracle is only as good as its MOMENT (item-F / the flip)
#
# evaluate_join is stateless: it judges the approval facts AS THEY ARE NOW. Entitlements change
# UNDERNEATH parked joins (a grant lands late; an approver loses can_view post-flip), so the
# SAME join re-evaluates to a DIFFERENT verdict as its inputs move. The driver MUST therefore
# re-run the check on every join wake/heartbeat — NOT cache the creation-time verdict — or a
# join that became unsatisfiable sits PENDING forever (the parked-resource surface this slice
# exists to kill), and a join judged unsatisfiable a moment too early terminates a workflow a
# late-landing grant would have completed. Both directions are proven below.
# ---------------------------------------------------------------------------

def test_reevaluation_flips_pending_to_unsatisfiable_when_approver_lost():
    """A join PENDING on an outstanding approver -> that approver loses entitlement (their pending
    approval is revoked/denied) -> re-evaluation flips PENDING->UNSATISFIABLE (suspend->terminate).
    If the driver cached the creation-time PENDING it would park forever on the impossible."""
    at_creation = evaluate_join(_apps(g=1, p=1), threshold=2)       # 1 granted, 1 pending
    assert at_creation.state == JOIN_PENDING and at_creation.action == "suspend"

    after_revocation = evaluate_join(_apps(g=1, d=1), threshold=2)  # that pending approver now denied
    assert after_revocation.state == UNSATISFIABLE and after_revocation.action == "terminate"


def test_reevaluation_flips_unsatisfiable_to_complete_when_grant_lands_late():
    """The reverse: judged UNSATISFIABLE because a grant had not landed yet -> the grant lands ->
    re-evaluation flips UNSATISFIABLE->COMPLETE. Proof the verdict is moment-bound: terminating on
    the FIRST (premature) evaluation would have been wrong. The driver must evaluate at the right
    moment (on wake, after approvals settle), not eagerly at creation."""
    too_early = evaluate_join(_apps(g=1, d=1), threshold=2)         # grant for the 3rd not yet issued
    assert too_early.state == UNSATISFIABLE

    grant_landed = evaluate_join(_apps(g=2, d=1), threshold=2)      # the awaited grant arrives
    assert grant_landed.state == COMPLETE
