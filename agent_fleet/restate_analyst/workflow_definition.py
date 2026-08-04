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
import os
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

__all__ = [
    "CompletionPolicy",
    "HumanAwaitStep",
    "SpoOperationStep",
    "DirectCallStep",
    "WorkflowDefinition",
    "WorkflowDefinitionError",
    "load_workflow_definition",
    "load_all_workflows",
    "definitions_dir",
    "get_workflow_definition",
]


class WorkflowDefinitionError(ValueError):
    """A workflow YAML failed to parse or validate. Raised loudly — a malformed
    definition is a config error (fail at load, never silently skip)."""


class CompletionPolicy(BaseModel):
    """HOW a ``human_await`` settles — declared, so the executor SELECTS its
    resolution semantics rather than inferring them (M3.2 build 1).

    ``mode``:
      * ``single``  — a plain approval. One authorized human resolves the
        promise via the ``approve`` handler. Today's sealed behaviour.
      * ``grouped`` — one approval settles a SERVER-AUTHORED BATCH of N items:
        the batch is persisted before the suspend, ``submit_decision``
        validates a submission against it BEFORE waking (a policy refusal
        leaves the review suspended), a ``decision_consumed`` guard makes a
        second submission an honest 409 instead of a hollow accept, and the
        wake fans out N per-item dispatches.

    ``quorum`` says WHO settles it. ``any_of`` — the first authorized member of
    the audience. ``n_of_m`` — N distinct approvals join one settlement
    (ADR-0027); DECLARABLE but NOT yet implemented, and the executor FAILS
    LOUDLY on it rather than silently settling on the first approval. A quorum
    the runner cannot honour must not read as one it can.

    ``claiming`` — the reviewer claims the batch before deciding (advisory
    lock, surfaced to the UI). Declared here so it is process content, not
    executor convention."""

    mode: Literal["single", "grouped"] = "single"
    quorum: Literal["any_of", "n_of_m"] = "any_of"
    threshold: Optional[int] = None  # required iff quorum == n_of_m
    claiming: bool = False

    @model_validator(mode="after")
    def _threshold_matches_quorum(self) -> "CompletionPolicy":
        if self.quorum == "n_of_m":
            if self.threshold is None or self.threshold < 2:
                raise ValueError("quorum 'n_of_m' requires a threshold >= 2")
        elif self.threshold is not None:
            raise ValueError("threshold is only meaningful with quorum 'n_of_m'")
        return self


class HumanAwaitStep(BaseModel):
    """A designed await on an authorized human (Situation B). Carries the sealed
    HITL fields verbatim; ``audience`` is the Topaz ``task_audience`` gated by
    ``can_act``. Multi-approval = N of these JOINED (ADR-0027), not a parallel
    engine.

    ``promise_name`` is the DURABLE Restate promise this step suspends on, and
    it is declared content on purpose (design doc §1, AMENDED). A promise name
    is durable journal state — an identity surface on live data — so it belongs
    inside the declared process rather than inside executor naming convention.
    Omitted, it defaults to ``approval_{id}``, which is the convention every
    existing definition and the ``approve`` handler already use; declaring it
    lets a definition suspend on a name a SHARED handler resolves (the grouped
    review's ``submit_decision`` resolves ``decision``). The executor and the
    resolving handler must agree on this string or the workflow suspends
    forever with no error — sealed by a string-equality guard."""

    kind: Literal["human_await"]
    id: str
    audience: str  # e.g. "promotion:DATA_ENGINEERING"
    subject_ref: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    requested_by: Optional[str] = None
    promise_name: Optional[str] = None
    completion: CompletionPolicy = Field(default_factory=CompletionPolicy)

    def resolved_promise_name(self) -> str:
        """The durable promise name this step actually suspends on. ONE
        derivation, so the executor and every seal ask the same function rather
        than re-deriving the string in parallel and hoping to agree."""
        return self.promise_name or f"approval_{self.id}"


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


def definitions_dir() -> Path:
    """Where the RUNNING SERVICE reads git-asserted definitions from.

    Env-configurable because the repo path and the deployed path differ: in-repo
    this is ``policy/workflows/``; in the pod it is wherever the definitions are
    mounted or baked. Declaring the seam as an env var keeps the code identical
    across both and makes the deploy step explicit rather than assumed.
    """
    env = os.environ.get("WORKFLOW_DEFINITIONS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "policy" / "workflows"


def get_workflow_definition(workflow_id: str) -> WorkflowDefinition:
    """Fetch ONE git-asserted definition by id, for a runner that must not accept a
    client-supplied process.

    Fails LOUDLY and specifically when the definitions are ABSENT — which is the
    expected failure until they are shipped into the pod. A definition that exists
    in git but not in the running service is not a definition the runner has; the
    error says which, and where it looked, because the alternative (an empty
    registry read as "no such workflow") is the silent-degrade this whole arc
    hunts. Presence in the repo is not presence in the running system.
    """
    d = definitions_dir()
    if not d.is_dir():
        raise WorkflowDefinitionError(
            f"workflow definitions directory {d} does not exist in this runtime — "
            "the git-asserted definitions are not shipped here. Set "
            "WORKFLOW_DEFINITIONS_DIR or mount/bake policy/workflows/."
        )
    path = d / f"{workflow_id}.yaml"
    if not path.is_file():
        available = sorted(p.stem for p in d.glob("*.yaml"))
        raise WorkflowDefinitionError(
            f"no git-asserted definition {workflow_id!r} in {d} (have: {available})"
        )
    return load_workflow_definition(path)


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
