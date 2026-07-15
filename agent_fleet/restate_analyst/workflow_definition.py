"""SPO-native WorkflowDefinition — the git-asserted process model (ADR-0029 Slice 1).

A workflow definition is a **git-asserted** YAML (``policy/workflows/*.yaml``),
reviewed like ``asset_grants.yaml`` / ``task_grants.yaml`` so classification +
grants compose, and executed on the Restate ``BPMNWorkflowRunner``.

Design (see ``docs/plans/slice-1-spo-workflow-promotion.md`` + ADR-0029):

* **A step is PRE-RESOLVED.** An ``spo_operation`` step *declares* its
  ``(subject, verb)`` — it does NOT go through the router's NL-resolution
  (stages 1+3). At execution it hits the router's **structural eligibility
  verifier (stage 2)**; a declared verb not in the caller's eligible set
  (``domain ∩ arity ∩ argument-fit ∩ permission``) → fail-and-release. This is
  what makes "a workflow cannot launder access" true by construction.
* **``human_await``** maps 1:1 onto the sealed HITL mechanics (register durable
  HumanTask → suspend on the promise → Topaz ``can_act`` → resolve).
* **``direct_call`` is TRANSITIONAL and MUST be gated** (RULING Q3): it may
  escape the verb *ontology* (an action not yet a mesh verb) but NEVER the
  *gate* — it declares a ``capability`` that Topaz decides
  (``can_invoke(caller, capability)``). The schema makes ``capability``
  **required**, so a permanently-ungated step kind cannot be expressed. A
  ``direct_call`` is a promotion candidate: close it by registering the action
  as a real verb (→ ``spo_operation``) or keep it capability-gated.

This module is the **schema + loader only** (Slice-1 foundation). The executor
(stage-2 verifier + dispatch) and the runner cutover are separate, reviewable
increments — they touch the sealed runner and get their own seal.
"""
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError

__all__ = [
    "HumanAwaitStep",
    "SpoOperationStep",
    "DirectCallStep",
    "WorkflowDefinition",
    "WorkflowDefinitionError",
    "load_workflow_definition",
    "load_all_workflows",
]


class WorkflowDefinitionError(ValueError):
    """A workflow YAML failed to parse or validate. Raised loudly — a malformed
    definition is a config error (fail at load, never silently skip)."""


class HumanAwaitStep(BaseModel):
    """A designed await on an authorized human (Situation B). Carries the sealed
    HITL fields verbatim; ``audience`` is the Topaz ``task_audience`` gated by
    ``can_act``. Multi-approval = N of these JOINED (ADR-0027), not a parallel
    engine."""

    kind: Literal["human_await"]
    id: str
    audience: str  # e.g. "promotion:DATA_ENGINEERING"
    subject_ref: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    requested_by: Optional[str] = None


class SpoOperationStep(BaseModel):
    """A pre-resolved SPO operation. ``subject``/``verb`` are RESOLVED
    identifiers (instance/class URI + verb IRI), NOT natural language — the
    executor verifies the declared verb against the caller's eligibility set
    (stage-2), it does not NL-classify it."""

    kind: Literal["spo_operation"]
    id: str
    subject: str  # resolved subject instance/class URI
    verb: str  # resolved verb IRI — verified ∈ caller's eligible set
    expected_output: Optional[str] = None  # declared output_uri (contract)


class DirectCallStep(BaseModel):
    """TRANSITIONAL escape hatch for an infrastructural action not (yet) a mesh
    verb. MUST stay inside the single decider: ``capability`` is REQUIRED and
    Topaz gates it (``can_invoke(caller, capability)``). Promotion candidate —
    register the action as a real verb (→ spo_operation) or keep it gated."""

    kind: Literal["direct_call"]
    id: str
    endpoint: str
    capability: str = Field(
        ...,
        min_length=1,
        description=(
            "Topaz-decidable capability for this action (can_invoke). REQUIRED "
            "so a permanently-ungated step kind cannot be expressed (RULING Q3)."
        ),
    )


# Discriminated union on `kind` — an unknown/absent kind fails validation loudly.
Step = Annotated[
    Union[HumanAwaitStep, SpoOperationStep, DirectCallStep],
    Field(discriminator="kind"),
]


class WorkflowDefinition(BaseModel):
    """A git-asserted process workflow. ``classification`` gates who may OBSERVE
    (the 3-audience tiers); ``participants``/``domain_stages`` feed observation.
    Steps execute as the workflow **initiator** (the sealed precedent — no
    escalation; delegated authority is a separate, deferred decision)."""

    id: str
    name: str
    classification: Optional[str] = None
    participants: list[dict] = Field(default_factory=list)
    domain_stages: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(..., min_length=1)
    observable_state: Optional[dict] = None


def load_workflow_definition(path: str | Path) -> WorkflowDefinition:
    """Load + validate one workflow YAML. Raises ``WorkflowDefinitionError`` on
    any parse/validation failure (config errors fail loud, never silent)."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowDefinitionError(f"cannot read/parse {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowDefinitionError(f"{p}: top level must be a mapping")
    try:
        return WorkflowDefinition.model_validate(raw)
    except ValidationError as exc:
        raise WorkflowDefinitionError(f"{p}: invalid workflow definition:\n{exc}") from exc


def load_all_workflows(directory: str | Path) -> dict[str, WorkflowDefinition]:
    """Load every ``*.yaml`` under ``directory`` (default home:
    ``policy/workflows/``), keyed by definition ``id``. Duplicate ids fail
    loudly (two files claiming one workflow is a config error)."""
    d = Path(directory)
    out: dict[str, WorkflowDefinition] = {}
    for f in sorted(d.glob("*.yaml")):
        wf = load_workflow_definition(f)
        if wf.id in out:
            raise WorkflowDefinitionError(
                f"duplicate workflow id {wf.id!r} ({f} vs a prior file)"
            )
        out[wf.id] = wf
    return out
