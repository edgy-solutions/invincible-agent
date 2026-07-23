"""Multi-approval join — the PURE lifecycle core (ADR-0029 Slice 5, [[ADR-0027]]-coupled).

N ``human_await`` steps jointly gate one step. This computes the JOIN LIFECYCLE STATE from the
per-approval decisions (from Topaz) + the join threshold (from the git-asserted policy):

    COMPLETE       -> the gated step PROCEEDS
    PENDING        -> SUSPEND (a designed await on the outstanding approvers; still satisfiable)
    UNSATISFIABLE  -> TERMINATE (fail-and-release; the join can NEVER complete — never park)

Pure — no Topaz. The AUTHZ decision (who counts, is the join satisfied) is decided ON Topaz rego
against the ADR-0027 policy; this owns only the suspend-vs-fail LIFECYCLE (the runner's job), and
it takes the per-approval decisions as INPUT. Design: docs/plans/slice-5-multi-approval-join.md.

Central discipline ([[feedback_hitl_suspend_vs_fail_ruling]], applied to joins): a join that can
STILL complete suspends; a join that can NEVER complete terminates. Parking on an unsatisfiable
join is the DoS surface wearing a join's clothes — an unbounded held execution keyed on an
impossible condition.
"""
from __future__ import annotations

from dataclasses import dataclass

GRANTED = "granted"
DENIED = "denied"
PENDING = "pending"

# Lifecycle states (str constants — kept plain so the driver can compare without importing enums).
COMPLETE = "COMPLETE"
JOIN_PENDING = "PENDING"
UNSATISFIABLE = "UNSATISFIABLE"

# The runner action each state maps to — the DoS discipline made explicit.
_ACTION = {COMPLETE: "proceed", JOIN_PENDING: "suspend", UNSATISFIABLE: "terminate"}


@dataclass
class Approval:
    approver: str
    decision: str  # granted | denied | pending


@dataclass
class JoinStatus:
    state: str          # COMPLETE | PENDING | UNSATISFIABLE
    granted: int
    denied: int
    pending: int
    threshold: int

    @property
    def action(self) -> str:
        """The runner action: proceed / suspend / terminate. UNSATISFIABLE -> terminate is the
        whole point — a join that can never complete must fail-and-release, not park."""
        return _ACTION[self.state]


def evaluate_join(approvals: list[Approval], *, threshold: int) -> JoinStatus:
    """Compute the join lifecycle state (design §1).

    * COMPLETE      when ``granted >= threshold``                          -> the gated step proceeds.
    * PENDING       when not complete but ``granted + pending >= threshold`` -> SUSPEND: satisfiable,
                    a designed await on the outstanding approvers (Situation B).
    * UNSATISFIABLE when ``granted + pending < threshold``                  -> TERMINATE: the join
                    can never reach the threshold (too many denials) — fail-and-release, never park.

    A required-approver denial (``all_of`` = ``threshold == len(required)``) collapses to
    UNSATISFIABLE by construction — no special case. A ``threshold`` above the number of approvers
    is UNSATISFIABLE from the start (a misconfigured join fails loud, it does not park forever)."""
    granted = sum(1 for a in approvals if a.decision == GRANTED)
    denied = sum(1 for a in approvals if a.decision == DENIED)
    pending = sum(1 for a in approvals if a.decision == PENDING)
    if granted >= threshold:
        state = COMPLETE
    elif granted + pending >= threshold:
        state = JOIN_PENDING
    else:
        state = UNSATISFIABLE
    return JoinStatus(state=state, granted=granted, denied=denied, pending=pending, threshold=threshold)
