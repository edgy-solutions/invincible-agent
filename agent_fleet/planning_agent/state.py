"""Plan state and ops — SERVER-OWNED, per the plan's Seam-1 ruling.

WHY THIS FILE IS HERE AND NOT IN THE BROWSER. Rev 2 of the plan moved computation
server-side and left the store in the client, which left a client `effectiveState()`
selector and server-side verbs with no ruled relationship between them. A server verb
cannot read a browser selector. The ruling: baseline, scenarios and ops live here and are
addressable; verbs evaluate over `(state_ref, ops[])`; the client store is an OPTIMISTIC
MIRROR whose only job is interaction feedback and which is never the source of a number
that reaches a card.

WHY EVALUATION IS STATELESS OVER POSTED DELTAS. `apply_ops(base, ops)` returns a NEW state
and never mutates its input. That is what makes a diff cheap and honest: run a measure over
`base` and over `apply_ops(base, ops)` and subtract. It is also what makes ADR-0042's OQ2
resolvable as "one verb over two state refs" — a verb that mutates could not be asked about
two worlds at once.

VERSIONING. Every scenario carries a monotonically increasing `version` bumped on each op.
ADR-0042 OQ1 resolved to PULL on a server-issued version: the client re-requests when the
version it holds is stale. Push was rejected because it does not survive a second client or
a reconnect, and a live view that silently stops recomputing is the compounding failure
Ruling 9 is about.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from typing import Literal, Optional, Union

try:  # flat in the image (/app), packaged in the repo — see tests/test_agent_modules_survive_flat_layout.py
    from entities import FiscalPeriod, FundingCommitment, FundingKind, FundingRequirement, Interval, PlanState
except ImportError:
    from agent_fleet.planning_agent.entities import FiscalPeriod, FundingCommitment, FundingKind, FundingRequirement, Interval, PlanState


# ─────────────────────────────────────────────────────────────────────────────
# Ops — the closed set of things a room may do to a plan
# ─────────────────────────────────────────────────────────────────────────────
# A CLOSED SET, deliberately. Every op is replayable, diffable, and auditable, and a
# decision artifact is meaningless if it records "and some other edits". Growing this set
# is a deliberate act with a measure and a diff-effect to match.

@dataclass(frozen=True)
class MoveProject:
    project_id: str
    new_planned: Interval
    op: Literal["move_project"] = "move_project"


@dataclass(frozen=True)
class SetCost:
    project_id: str
    kind: FundingKind
    period: FiscalPeriod
    amount: float
    op: Literal["set_cost"] = "set_cost"


@dataclass(frozen=True)
class SetCommitment:
    project_id: str
    org_id: str
    period: FiscalPeriod
    kind: FundingKind
    amount: float
    op: Literal["set_commitment"] = "set_commitment"


@dataclass(frozen=True)
class MoveSiteImpact:
    project_id: str
    site_id: str
    new_window: Interval
    op: Literal["move_site_impact"] = "move_site_impact"


PlanOp = Union[MoveProject, SetCost, SetCommitment, MoveSiteImpact]


class UnknownTarget(ValueError):
    """An op naming something the model does not contain.

    Raised rather than ignored. A silently-dropped op is the worst outcome available here:
    the room believes it made a change, the diff shows nothing, and the decision artifact
    records an op that never applied.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────

def apply_ops(base: PlanState, ops: list[PlanOp]) -> PlanState:
    """Return a NEW state with `ops` applied in order. `base` is never mutated.

    Order matters and is preserved: two moves of the same project mean the later one wins,
    which is what a room dragging the same bar twice expects.
    """
    s = copy.deepcopy(base)
    for op in ops:
        if isinstance(op, MoveProject):
            proj = s.project(op.project_id)
            if proj is None:
                raise UnknownTarget(f"move_project names unknown project {op.project_id!r}")
            if not op.new_planned.is_well_formed():
                raise UnknownTarget(
                    f"move_project {op.project_id}: interval {op.new_planned} is inverted"
                )
            proj.planned = op.new_planned

        elif isinstance(op, SetCost):
            if s.project(op.project_id) is None:
                raise UnknownTarget(f"set_cost names unknown project {op.project_id!r}")
            existing = next(
                (r for r in s.requirements
                 if r.project_id == op.project_id and r.period == op.period and r.kind == op.kind),
                None,
            )
            if existing is not None:
                existing.amount = op.amount
            else:
                # A NEW requirement row, not an edit of a neighbouring period. Costs are
                # entered per period; folding a new period into an existing row would
                # silently move money through time.
                s.requirements.append(FundingRequirement(
                    req_id=f"R-op-{len(s.requirements) + 1}",
                    project_id=op.project_id, period=op.period,
                    kind=op.kind, amount=op.amount,
                ))

        elif isinstance(op, SetCommitment):
            if s.project(op.project_id) is None:
                raise UnknownTarget(f"set_commitment names unknown project {op.project_id!r}")
            if not any(o.org_id == op.org_id for o in s.organizations):
                raise UnknownTarget(f"set_commitment names unknown org {op.org_id!r}")
            existing = next(
                (k for k in s.commitments
                 if k.project_id == op.project_id and k.org_id == op.org_id
                 and k.period == op.period and k.kind == op.kind),
                None,
            )
            if existing is not None:
                existing.amount = op.amount
            else:
                s.commitments.append(FundingCommitment(
                    commit_id=f"K-op-{len(s.commitments) + 1}",
                    project_id=op.project_id, org_id=op.org_id,
                    period=op.period, kind=op.kind, amount=op.amount,
                ))

        elif isinstance(op, MoveSiteImpact):
            impact = next(
                (i for i in s.site_impacts
                 if i.project_id == op.project_id and i.site_id == op.site_id),
                None,
            )
            if impact is None:
                raise UnknownTarget(
                    f"move_site_impact names no impact for {op.project_id}/{op.site_id}"
                )
            impact.window = op.new_window

        else:  # pragma: no cover — the union is closed
            raise UnknownTarget(f"unknown op {op!r}")

    return s


# ─────────────────────────────────────────────────────────────────────────────
# Scenarios — server-addressable, which is what makes state_ref possible
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Scenario:
    """A named fork. `base` is 'baseline' or another scenario id — the demo only needs
    baseline forks, but scenario-of-scenario costs nothing to allow and forbidding it later
    is harder than allowing it now."""
    scenario_id: str
    name: str
    base: str = "baseline"
    created_at: str = ""
    ops: list[PlanOp] = field(default_factory=list)
    # Bumped on every op. The client polls this; a stale version is the pull trigger.
    version: int = 0
    archived: bool = False


class PlanStore:
    """The server-side owner of plan state. In-memory for this cycle.

    ADR-0042 §3: this is the PLACEHOLDER — it becomes Postgres in Phase 4 and a graph
    projection in Phase 8. What does not move is that verbs read through it rather than
    through anything in a browser. The class boundary is the seam that stays fixed.
    """

    def __init__(self, baseline: PlanState):
        self._baseline = baseline
        self._scenarios: dict[str, Scenario] = {}
        self._baseline_version = 0

    # ── reads ──
    @property
    def baseline(self) -> PlanState:
        return self._baseline

    def scenario(self, scenario_id: str) -> Scenario:
        sc = self._scenarios.get(scenario_id)
        if sc is None:
            raise UnknownTarget(f"unknown scenario {scenario_id!r}")
        return sc

    def scenarios(self, *, include_archived: bool = False) -> list[Scenario]:
        return [s for s in self._scenarios.values() if include_archived or not s.archived]

    def resolve(self, state_ref: str) -> PlanState:
        """`state_ref` -> a concrete PlanState. THE function verbs evaluate over.

        'baseline' resolves to the baseline; a scenario id resolves to its base with its
        ops applied, recursively, so a scenario-of-scenario is not a special case.
        """
        if state_ref == "baseline":
            return self._baseline
        sc = self.scenario(state_ref)
        return apply_ops(self.resolve(sc.base), sc.ops)

    def version_of(self, state_ref: str) -> int:
        """The pull trigger's discriminant (ADR-0042 OQ1). A client holding an older
        version knows to re-request; it never has to be told."""
        if state_ref == "baseline":
            return self._baseline_version
        return self.scenario(state_ref).version

    # ── writes ──
    def fork(self, scenario_id: str, name: str, *, base: str = "baseline",
             created_at: str = "") -> Scenario:
        if scenario_id in self._scenarios:
            raise UnknownTarget(f"scenario {scenario_id!r} already exists")
        if base != "baseline":
            self.scenario(base)  # raises if the base does not resolve
        sc = Scenario(scenario_id=scenario_id, name=name, base=base, created_at=created_at)
        self._scenarios[scenario_id] = sc
        return sc

    def append_op(self, scenario_id: str, op: PlanOp) -> Scenario:
        """Append and BUMP. Validation happens by applying eagerly, so an op that cannot
        apply is rejected at post time rather than at read time — the room finds out while
        it still has the context to understand why."""
        sc = self.scenario(scenario_id)
        apply_ops(self.resolve(sc.base), sc.ops + [op])  # raises on a bad op
        sc.ops.append(op)
        sc.version += 1
        return sc

    def write_baseline_op(self, op: PlanOp) -> int:
        """The plan's ONE exception: cost/funding entry with no active scenario writes
        baseline directly — the 'costs persist' requirement — and still produces a change
        record, which is the caller's job to capture. Restricted to funding ops on purpose:
        a schedule change to baseline without a scenario is exactly the thing anti-goal
        'no editing baseline directly from a drag' forbids.
        """
        if not isinstance(op, (SetCost, SetCommitment)):
            raise UnknownTarget(
                "only funding ops may write baseline directly; schedule changes require a scenario"
            )
        self._baseline = apply_ops(self._baseline, [op])
        self._baseline_version += 1
        return self._baseline_version

    def commit(self, scenario_id: str) -> int:
        """Apply a scenario's ops to baseline and archive it. The DECISION ARTIFACT is the
        caller's responsibility and the commit ceremony blocks without a rationale — that
        gate lives at the route, not here, because this class must stay a store."""
        sc = self.scenario(scenario_id)
        self._baseline = apply_ops(self.resolve(sc.base), sc.ops)
        self._baseline_version += 1
        sc.archived = True
        return self._baseline_version
