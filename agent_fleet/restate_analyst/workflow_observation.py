"""Workflow observation — the PURE enforcement core (ADR-0029 Slice 3, Decision 4).

Given a ``WorkflowDefinition``, a workflow instance's runtime state, and an observer,
compute the GATED observation projection the observer may see, per the 3-audience tiers
(design: docs/reference/slice-3-observation.md). Pure — no Restate, no Topaz. The authz
decisions are INJECTED (the Topaz calls live in the thin driver), so the *gating logic*
is unit-testable without a cluster — the analogue of ``spo_step_executor.py`` /
``spo_interview.py``.

Two filters, applied IN ORDER (design §1):
  1. **The author's declared surface** — a field not on ``observable_state.visible`` (or
     listed ``internal``) is NEVER surfaced, to anyone. The author's choice, not authz.
  2. **The 3-audience gate** (Decision 4) — applied per element by the observer's
     relationship to the workflow.

Deny-by-default is structural: ``can_observe_others`` defaults ``False`` and
``can_view_subject`` defaults to a deny, so a driver that forgets to inject a grant fails
CLOSED (an other-party action stays redacted; an agent step over an unknown subject stays
hidden), never open. Same discipline as the Slice-2 enforcement funnel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

try:  # same lazy-import dance as spo_step_executor / spo_interview
    from workflow_definition import WorkflowDefinition  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_definition import WorkflowDefinition

# AGENT-action step kinds — visibility is clearance-bounded by can_view on the subject.
_AGENT_KINDS = {"spo_operation", "direct_call", "service_task", "service"}
# HUMAN-action step kinds — self-tier if the observer is the actor/assignee, else
# other-humans deny-by-default.
_HUMAN_KINDS = {"human_await", "user_task"}


@dataclass
class StepRuntime:
    """One step's runtime facts, normalized from the runner's per-step results by the driver."""
    id: str
    kind: str
    status: str = "pending"          # pending | running | suspended | done | failed
    subject: Optional[str] = None    # agent-action clearance key (can_view)
    actor: Optional[str] = None      # human identity that ACTED, or None/engine for an agent step
    assignee_role: Optional[str] = None  # for a pending human step: whose role it awaits


@dataclass
class WorkflowRuntimeState:
    workflow_id: str
    current_stage: Optional[str] = None
    steps: list[StepRuntime] = field(default_factory=list)
    participant_bindings: dict = field(default_factory=dict)  # role -> identity


@dataclass
class ObservationProjection:
    """What the observer MAY see. ``redactions`` records WHAT was hidden and WHY (for audit)
    — never the hidden content itself."""
    workflow_id: str
    visible: bool
    classification: Optional[str] = None
    domain_stages: list[str] = field(default_factory=list)
    current_stage: Optional[str] = None
    steps: list[dict] = field(default_factory=list)
    participants: list[dict] = field(default_factory=list)
    redactions: list[str] = field(default_factory=list)


def _observable_fields(definition: WorkflowDefinition) -> tuple[set, set]:
    """observable_state -> (visible_keys, internal_keys). Keys: ``domain_stages`` or
    ``<step_id>.<attr>`` (e.g. ``approve_promotion.status``, ``publish_artifact.result``).
    Absent observable_state -> nothing declared visible: an undeclared field is treated as
    internal (fail-closed on the author surface)."""
    obs = getattr(definition, "observable_state", None) or {}
    return set(obs.get("visible") or []), set(obs.get("internal") or [])


def _declared_visible(key: str, visible: set, internal: set) -> bool:
    """On the author's declared surface iff in ``visible`` and not ``internal`` (internal wins)."""
    return key in visible and key not in internal


def project_observation(
    definition: WorkflowDefinition,
    runtime: WorkflowRuntimeState,
    observer: str,
    *,
    observer_role: Optional[str] = None,
    can_observe_workflow: bool = False,
    can_view_subject: Optional[Callable[[str], bool]] = None,
    can_observe_others: bool = False,
) -> ObservationProjection:
    """The observer's gated view of a workflow instance (Decision 4).

    ``observer_role``       — the observer's participant role, or None (self-tier signal).
    ``can_observe_workflow``— classification clearance to observe the workflow AT ALL.
    ``can_view_subject``    — (subject_uri)->bool, the agent-action clearance (Topaz can_view);
                              defaults to DENY so an un-injected driver hides agent steps.
    ``can_observe_others``  — the explicit other-humans grant; defaults False (deny-by-default).
    """
    is_participant = observer_role is not None
    can_view = can_view_subject or (lambda _s: False)  # fail-closed

    # Tier 0 — may the observer see the workflow AT ALL? (participant OR classification-cleared)
    # Deny reveals nothing beyond the deny itself (existence-oracle).
    if not (is_participant or can_observe_workflow):
        return ObservationProjection(
            workflow_id=runtime.workflow_id, visible=False,
            redactions=["workflow: not a participant and not classification-cleared"],
        )

    visible_keys, internal_keys = _observable_fields(definition)
    proj = ObservationProjection(
        workflow_id=runtime.workflow_id, visible=True,
        classification=getattr(definition, "classification", None),
    )

    # Domain-stage view — gated by the declared 'domain_stages' surface.
    if _declared_visible("domain_stages", visible_keys, internal_keys):
        proj.domain_stages = list(getattr(definition, "domain_stages", []) or [])
        proj.current_stage = runtime.current_stage
    elif runtime.current_stage is not None or getattr(definition, "domain_stages", None):
        proj.redactions.append("domain_stages/current_stage: not on the declared observable surface")

    # Per-step gating: filter 1 (declared surface) then filter 2 (3-audience tier).
    for s in runtime.steps:
        if not _declared_visible(f"{s.id}.status", visible_keys, internal_keys):
            proj.redactions.append(f"{s.id}: not on the declared observable surface (internal)")
            continue
        if s.kind in _AGENT_KINDS:
            # clearance-bounded: an agent action over a subject you cannot view is redacted.
            if s.subject and not can_view(s.subject):
                proj.redactions.append(f"{s.id}: agent action over a subject you cannot view")
                continue
            proj.steps.append({"id": s.id, "kind": s.kind, "status": s.status, "subject": s.subject})
        elif s.kind in _HUMAN_KINDS:
            is_self = (s.actor is not None and s.actor == observer) or (
                s.assignee_role is not None and s.assignee_role == observer_role
            )
            if is_self:
                proj.steps.append({"id": s.id, "kind": s.kind, "status": s.status, "actor": "you"})
            elif can_observe_others:
                proj.steps.append({"id": s.id, "kind": s.kind, "status": s.status, "actor": s.actor})
            else:
                # deny-by-default: redact ENTIRELY — do not reveal the step (or its actor) EXISTS.
                proj.redactions.append(f"{s.id}: another party's action (restricted)")
                continue
        else:
            proj.redactions.append(f"{s.id}: unknown step kind {s.kind!r} (fail-closed)")
            continue

    # Participants: self sees its own binding; others deny-by-default.
    for role, identity in (runtime.participant_bindings or {}).items():
        if identity == observer or role == observer_role:
            proj.participants.append({"role": role, "identity": "you"})
        elif can_observe_others:
            proj.participants.append({"role": role, "identity": identity})
        else:
            proj.redactions.append(f"participant {role}: another party (restricted)")

    return proj
