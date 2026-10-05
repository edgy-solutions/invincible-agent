"""SPO-native WorkflowDefinition — the git-asserted process model (ADR-0029 Slice 1).

A workflow definition is a **git-asserted** YAML (``policy/workflows/*.yaml``),
reviewed like ``asset_grants.yaml`` / ``task_grants.yaml`` so classification +
grants compose, and executed on the Restate ``BPMNWorkflowRunner``.

Design (see ``docs/reference/slice-1-spo-workflow-promotion.md`` + ADR-0029):

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
import re
from pathlib import Path
from typing import Annotated, Any, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

__all__ = [
    "CompletionPolicy",
    "HumanAwaitStep",
    "SpoOperationStep",
    "DirectCallStep",
    "DispatchFanoutStep",
    "RenderStep",
    "SignalAwaitStep",
    "WaitStep",
    "EmitStep",
    "StubVerb",
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


class _Declared(BaseModel):
    """Every model a definition author writes. AN UNKNOWN FIELD IS REFUSED, NOT DROPPED.

    pydantic's default is ``extra="ignore"``: a misspelled ``deadline_secs`` or a field this
    runner does not implement validated cleanly and then did nothing. For an approval process that
    is the worst failure available -- the YAML reads as declaring an escalation, a task kind or a
    quorum, and the executor never sees it. Refusing at load turns a silent no-op into a typo.
    Sealed by tests/test_a_definition_field_the_runner_cannot_see_is_refused.py.
    """

    model_config = ConfigDict(extra="forbid")


class CompletionPolicy(_Declared):
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


class HumanAwaitStep(_Declared):
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

    # ── THE DEADLINE, AND WHY IT TERMINATES RATHER THAN ESCALATES ──────────────────────────────
    #
    # Seconds to wait for the human before the step ends in `timed_out`. Optional: a step with no
    # deadline waits forever, which is today's behaviour and stays the default — adding a default
    # timeout would silently change every existing definition's meaning, and "the approval expired"
    # is not a thing any current process has agreed to.
    #
    # IT TERMINATES; IT DOES NOT DECIDE. A timeout is not a disposition — nobody accepted, nobody
    # rejected, and writing one of those verbs on expiry would put a decision in the archive that
    # no human made. ADR-0034 archives decision records, so a manufactured verb there is worse
    # than an absent one. The step ends at the declared terminal `timed_out` and a chaining table
    # decides what happens next: escalate, re-open to a wider audience, or abandon. THAT choice is
    # policy and belongs in a row, not in the executor.
    #
    # `timed_out` MUST BE IN THE TABLE'S `terminals:` OR THE CHAIN CANNOT NAME IT. That is the
    # rail: a terminal resolves against the table header, so a typo fails like a typo'd
    # definition. A deadline with nowhere to land is a field that cannot be acted on.
    deadline_seconds: Optional[int] = Field(default=None, gt=0)

    # ── THE TASK KIND IS PROCESS CONTENT, DECLARED PER STEP ────────────────────────────────────
    #
    # The kind keys `/act`'s decision vocabulary (`accepts`) and its reason requirement, so it
    # decides which gate a human's verb must pass. Until this field it was an argument the SERVICE
    # passed for every step of a run, and that was wrong the first time a definition's steps
    # differed: `safety_concurrence` registered the user representative's concurrence under the
    # ACCEPTANCE kind, whose vocabulary has no `concurred`.
    #
    # BINDABLE AND STRICT, like `audience`: ``risk_acceptance_{level_slug}`` is one declaration
    # serving four levels, and an unbound placeholder would register a kind no species declares.
    #
    # HONOURED ONLY FROM THE REGISTRY. BPMNWorkflowRunner still runs a caller-supplied
    # `definition`; a kind read from one would let the caller choose its own gate, which is why
    # `_register_human_task` takes kind as an argument and never from the task. The executor
    # refuses a declared kind unless its caller loaded the definition from the registry.
    task_kind: Optional[str] = None

    # ── WHO MAY NOT DECIDE, DECLARED ───────────────────────────────────────────────────────────
    #
    # Actors refused at the authority gate WHATEVER their grants: a steward confirming the origin
    # of an artifact they dropped themselves holds `can_act` on the audience like any other
    # steward, so a grant cannot express "everyone in this audience except the one person whose
    # claim this is". Each entry binds STRICTLY from the context (an exclusion that bound to
    # nothing would be a guard that cannot fire) and names an `authz_id` -- the namespace
    # `approve` verifies `acted_by` in. A JWT `sub` here would never equal an `acted_by`, and the
    # exclusion would pass everyone.
    excludes: list[str] = Field(default_factory=list)

    # ── WHAT AN ANSWER MEANS FOR THE CASE, DECLARED BESIDE THE AWAIT ────────────────────────────
    #
    # `approves` names the verbs that count as an APPROVAL of the current proposal. Answered with
    # one, the executor appends an approval-chain entry (ADR-0046 §4: step, role, approver,
    # decision, decided_at, decision_record_ref) -- written by the EXECUTOR from the verified
    # `acted_by`, never authored by a template. Answered with any OTHER verb, the chain the step
    # was extending ENDS: a rejection or a deferral returns the case to a new proposal, and an
    # approval of the old one must not ride along into the next release. A timeout is not an
    # answer and touches nothing.
    #
    # `role` is what the chain entry calls the approver. Required with `approves`, because an
    # entry with no role is a signature with no capacity.
    #
    # `chooses_from` is a dotted path to a list of options, each carrying a `verb`. The answer's
    # verb selects the option, which is recorded as the step's `chosen` output -- so "which option
    # did the approver pick" is the verb itself, and `/act` needs no field it does not have.
    role: Optional[str] = None
    approves: list[str] = Field(default_factory=list)
    chooses_from: Optional[str] = None

    @model_validator(mode="after")
    def _an_approval_has_a_role(self) -> "HumanAwaitStep":
        if self.approves and not self.role:
            raise ValueError(f"step {self.id}: `approves` requires a `role` for the chain entry")
        if (self.approves or self.chooses_from) and self.completion.mode == "grouped":
            raise ValueError(
                f"step {self.id}: `approves`/`chooses_from` on a grouped await is declarable but "
                "NOT implemented -- a grouped review resolves N rows, not one proposal")
        if self.excludes and self.completion.mode == "grouped":
            # The grouped path never binds `excludes`, so it would refuse NOBODY -- neither at
            # routing nor at the gate. Refused at load rather than honoured in name only.
            raise ValueError(
                f"step {self.id}: `excludes` on a grouped await is NOT implemented -- the grouped "
                "path neither routes around nor refuses an excluded actor")
        return self

    def resolved_promise_name(self) -> str:
        """The durable promise name this step actually suspends on. ONE
        derivation, so the executor and every seal ask the same function rather
        than re-deriving the string in parallel and hoping to agree."""
        return self.promise_name or f"approval_{self.id}"


class SpoOperationStep(_Declared):
    """A pre-resolved SPO operation. ``subject``/``verb`` are RESOLVED
    identifiers (instance/class URI + verb IRI), NOT natural language — the
    executor verifies the declared verb against the caller's eligibility set
    (stage-2), it does not NL-classify it."""

    kind: Literal["spo_operation"]
    id: str
    subject: str  # resolved subject instance/class URI
    verb: str  # resolved verb IRI — verified ∈ caller's eligible set
    expected_output: Optional[str] = None  # declared output_uri (contract)


class DirectCallStep(_Declared):
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
    extra_payload: Optional[dict] = Field(
        default=None,
        description=(
            "Declared inputs for this call, templated against the run's context the same way "
            "emit/render steps' `template` is ({case.*}/{trigger.*}/{outputs.*} placeholders; the "
            "strict renderer, not the flat `{placeholder}` endpoint binder). Rendered by the "
            "dispatch loop and passed through to the executor's own `extra_payload` parameter "
            "verbatim -- the executor stays generic; only this step's declared surface widens "
            "(item B, 2026-10-03)."
        ),
    )


class DispatchFanoutStep(_Declared):
    """Dispatch the review's batch WITHOUT a human — the autonomous counterpart of ``human_await``.

    A STEP KIND WHOSE SEMANTICS ARE EXECUTOR-OWNED, and that is the whole design. The YAML declares
    WHAT (a capability-gated dispatch of this review's batch); the executor owns HOW: assert
    ``can_invoke``, synthesize the empty ``BulkDecision`` (accept-all-with-exceptions, which is what
    an autonomous run's "decision" IS), run the shared pure core, and either fan out on the sealed
    exactly-once path or ESCALATE the whole notice to a human.

    WHY NOT DEFINITION CONTENT: the same reason ``human_await``'s mechanics are not. The load-bearing
    behaviours — server-authored batch, the refusal checks, per-item idempotency, escalation — are
    INTRINSIC to what the step means, so no definition author can omit them. **Escalation cannot be
    forgotten because it is not authored.** A definition that dispatches without an escalation path
    is unexpressible.

    WHY IT IS NOT ``direct_call``. It was one, and that was a costume. ``direct_call`` is a generic
    HTTP escape hatch, and this step never made a generic HTTP call — it POSTed a fixed envelope to
    prove the capability gate existed, which it did faithfully for months while the gate denied it.
    The false generality is exactly what let ``{dispatch_endpoint}`` sit unbound: a generic caller is
    ALLOWED to have an arbitrary endpoint, so nothing could tell that this one was nonsense. Naming
    the step for what it does makes its inputs checkable. Generic ``direct_call`` survives unchanged
    for its own purpose and its ADR-0029 promotion path.

    ``capability`` stays REQUIRED and Topaz-decided — the gate the recorded ``[403]`` proved, kept in
    the declaration plane where "this process dispatches under this capability" belongs.
    """

    kind: Literal["dispatch_fanout"]
    id: str
    capability: str = Field(
        ...,
        min_length=1,
        description=(
            "Topaz-decidable capability for the dispatch (can_invoke). REQUIRED — an autonomous "
            "dispatch that could be declared ungated is the one thing this kind must not permit."
        ),
    )


class RenderStep(_Declared):
    """Render a YAML template against the run's context and record it as this step's output.

    THE OPTION TEMPLATES LIVE HERE, not in Python: a domain's proposals are data a reviewer reads
    in git. The renderer is STRICT -- a path that resolves to nothing raises, never renders blank
    -- because a proposal missing its spares record is a different proposal, not a shorter one.
    A string that is EXACTLY one ``{path}`` yields the raw value (a list stays a list); anything
    else interpolates scalars only. Registry-only: see the executor."""

    kind: Literal["render"]
    id: str
    template: Any


class SignalAwaitStep(_Declared):
    """Await a SYSTEM's answer -- an acknowledgement, not a human decision.

    Distinct from ``human_await`` because it registers NO human task: a machine's ack in a human
    queue is a row nobody should act on. The gate is the same one: the resolving handler checks
    ``can_act`` against the JOURNALLED ``audience``, and additionally refuses a status outside the
    journalled ``accepts`` -- the vocabulary a human task's kind would otherwise supply.
    The deadline race and its ``timed_out`` terminal are human_await's, unchanged."""

    kind: Literal["signal_await"]
    id: str
    signal: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    audience: str
    accepts: list[str] = Field(..., min_length=1)
    #: statuses the resolver must explain; a blank `comments` on one is refused (400)
    reason_required: list[str] = Field(default_factory=list)
    deadline_seconds: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _reasons_are_accepted(self) -> "SignalAwaitStep":
        stray = sorted(set(self.reason_required) - set(self.accepts))
        if stray:
            raise ValueError(f"signal_await {self.id}: reason_required {stray} is not in "
                             f"accepts {self.accepts} -- a reason for a status nobody can send")
        return self


class WaitStep(_Declared):
    """A durable timer. Its disposition is ``elapsed``, so a chaining row can say what a parked
    case does when it comes back -- a deferral that never revisits is a deletion."""

    kind: Literal["wait"]
    id: str
    seconds: int = Field(..., gt=0)


class EmitStep(_Declared):
    """Render a template and append it to this instance's ``outbox:{channel}``.

    THE TRANSPORT IS NOT DECIDED HERE, and that is deliberate: the record is durable in the
    instance's state and readable through the owning service's ``outbox`` handler; WHO carries it
    across the boundary is a binding the receiving side has not ruled on. Emitting is recorded;
    delivery is not claimed."""

    kind: Literal["emit"]
    id: str
    channel: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    template: Any


# Discriminated union on `kind` — an unknown/absent kind fails validation loudly.
Step = Annotated[
    Union[HumanAwaitStep, SpoOperationStep, DirectCallStep, DispatchFanoutStep,
          RenderStep, SignalAwaitStep, WaitStep, EmitStep],
    Field(discriminator="kind"),
]


class WorkflowDefinition(_Declared):
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

    @model_validator(mode="after")
    def _step_ids_are_unique(self) -> "WorkflowDefinition":
        # A step's output is recorded under `outputs.<definition id>.<step id>`, and its promise and
        # register names derive from the id -- two steps sharing one would overwrite each other.
        ids = [s.id for s in self.steps]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"definition {self.id}: duplicate step ids {dup}")
        # One promise name, one awaiting step: the audience is journalled UNDER the name, so a
        # second await on it would overwrite the first's gate input.
        names = [s.resolved_promise_name() if s.kind == "human_await" else s.signal
                 for s in self.steps if s.kind in ("human_await", "signal_await")]
        shared = sorted({n for n in names if names.count(n) > 1})
        if shared:
            raise ValueError(f"definition {self.id}: promise names awaited twice {shared}")
        return self


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


def candidate_definition_dirs(module_path: Path) -> list[Path]:
    """The ordered places a definitions directory can live, given this module's path.

    TWO LAYOUTS, and the second one is why this is a function rather than a line:
      * REPO — ``agent_fleet/restate_analyst/workflow_definition.py``, so the
        definitions are three levels up at ``<repo>/policy/workflows``.
      * CONTAINER — the image FLATTENS the service directory into ``/app``, so this
        module is ``/app/workflow_definition.py`` and the definitions are baked
        beside it at ``/app/policy/workflows``.

    The repo candidate is GUARDED on depth. ``Path('/app/workflow_definition.py')``
    has exactly two parents, so an unguarded ``parents[2]`` raises IndexError in the
    container — which would crash BEFORE the loud, specific WorkflowDefinitionError
    below could ever be raised. An honest error path that is unreachable in the only
    environment that needs it is not an error path.
    """
    here = module_path.resolve()
    out: list[Path] = []
    if len(here.parents) >= 3:  # repo layout only; guarded, see docstring
        out.append(here.parents[2] / "policy" / "workflows")
    out.append(here.parent / "policy" / "workflows")  # flattened container layout
    return out


def definition_dirs() -> "list[Path]":
    """The SEED-THEN-OVERLAY search path, lowest precedence first (ADR-0036).

    ``WORKFLOW_DEFINITIONS_DIR`` is an ``os.pathsep``-separated LIST, not a single directory —
    the same shape as ``TASK_KIND_OVERLAY_DIRS``. A deployment's own definitions compose over
    the platform's by id, **full replacement by key**, exactly as a task-kind overlay row
    replaces a seed row rather than merging into it.

    WHY A LIST RATHER THAN ONE DIRECTORY. A single path forces a deployment that needs one
    domain definition to either fork the whole directory or bake its own copy of every platform
    definition — and a forked copy stops tracking the original silently, which is the drift the
    overlay layer exists to prevent. It is also what ADR-0039 needs: a programme tailors ITS
    definitions without carrying ours.

    A SINGLE PATH STILL WORKS AND MEANS WHAT IT MEANT. One entry is a list of one, so every
    existing deployment keeps its behaviour without an edit — the compatibility that makes this
    safe to land ahead of the decision tables that will use it.

    LATER WINS, and the order is the declaration. Unset falls back to the repo/container
    candidates as before; if none exist the first is returned anyway, so the error names a
    concrete path rather than a guess.
    """
    env = os.environ.get("WORKFLOW_DEFINITIONS_DIR")
    if env:
        # A trailing or doubled separator is a typo, not a request to search the CWD — an empty
        # entry would resolve to Path(""), i.e. ".", and silently admit whatever is beside the
        # process.
        parts = [p.strip() for p in env.split(os.pathsep)]
        dirs = [Path(p) for p in parts if p]
        if dirs:
            return dirs
    candidates = candidate_definition_dirs(Path(__file__))
    existing = [c for c in candidates if c.is_dir()]
    if not existing:
        return candidates[:1]
    # THE SEED, THEN EVERY OVERLAY'S workflows/ IN NAME ORDER -- the same default
    # `decision_table.decision_dirs` composes, so a definition and the table that selects it
    # resolve from the same overlays. Before this an overlay could ship a selection table naming a
    # definition the registry could not find. Name order is not a precedence anyone chose, so no
    # two overlays may declare one definition id (sealed).
    seed = existing[0]
    return [seed, *sorted(p for p in (seed.parent / "overlays").glob("*/workflows") if p.is_dir())]


def definitions_dir() -> Path:
    """The HIGHEST-PRECEDENCE directory — kept for callers that want one path to name.

    Returns the LAST entry of :func:`definition_dirs`, because later overrides earlier. Use
    :func:`definition_dirs` for anything that resolves a definition: this cannot see a platform
    definition that an overlay does not replace.
    """
    return definition_dirs()[-1]


def describe_registry() -> dict:
    """What the runtime ACTUALLY loaded — the startup/roll witness in one call.

    Returns the resolved search path and the COMPOSED definition ids. Deliberately reports the
    INVENTORY, not a count: "loaded 2 definitions" passes over the wrong two as happily as the
    right two, and the roll's claim is that the image carries the definitions the gate tested.

    IT REPORTS EVERY DIRECTORY, INCLUDING THE ONES THAT DO NOT EXIST. A missing overlay is the
    most likely deploy defect once the path is a list, and it fails SILENTLY — composition over
    an absent directory contributes nothing and the platform definitions still resolve, so the
    service looks healthy while a programme's tailoring is simply not there. The witness has to
    name what it could not find, or nobody can tell that case from a correct one-entry path.
    """
    dirs = definition_dirs()
    composed: dict = {}
    for d in dirs:
        if d.is_dir():
            for p in sorted(d.glob("*.yaml")):
                composed[p.stem] = str(d)      # later wins: full replacement by id
    return {
        "directories": [{"path": str(d), "exists": d.is_dir()} for d in dirs],
        # The single `directory` key is kept so an existing reader does not break; it is the
        # highest-precedence entry, which is what it always effectively named.
        "directory": str(dirs[-1]),
        "exists": any(d.is_dir() for d in dirs),
        "ids": sorted(composed),
        "resolved_from": composed,
    }


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
    dirs = definition_dirs()
    if not any(d.is_dir() for d in dirs):
        raise WorkflowDefinitionError(
            f"no workflow definitions directory exists in this runtime — looked in "
            f"{[str(d) for d in dirs]}. The git-asserted definitions are not shipped here. Set "
            "WORKFLOW_DEFINITIONS_DIR (an os.pathsep-separated list) or mount/bake "
            "policy/workflows/."
        )
    # NO TWO OVERLAYS MAY DECLARE ONE DEFINITION. The seal on the committed tree cannot see a
    # deployment's own overlays, and between overlays "later" is name order, which nobody chose.
    owners = [d for d in dirs[1:] if (d / f"{workflow_id}.yaml").is_file()]
    if len(owners) > 1:
        raise WorkflowDefinitionError(
            f"definition {workflow_id!r} is declared by two overlays ({[str(d) for d in owners]}); "
            "name order is not a precedence anyone chose"
        )
    # LATER WINS, so search in REVERSE precedence order and take the first hit: an overlay's
    # definition replaces the platform's by id, wholesale, never field-merged.
    for d in reversed(dirs):
        path = d / f"{workflow_id}.yaml"
        if path.is_file():
            return load_workflow_definition(path)
    # THE ERROR NAMES EVERY DIRECTORY AND THE COMPOSED INVENTORY, not just the last one. With a
    # search path, "not in <dir>" is a true statement that answers the wrong question — the
    # reader needs to know where it looked and what it did find, or a missing overlay and a
    # misspelled id produce the same message.
    available = sorted({p.stem for d in dirs if d.is_dir() for p in d.glob("*.yaml")})
    raise WorkflowDefinitionError(
        f"no git-asserted definition {workflow_id!r} in any of "
        f"{[str(d) for d in dirs if d.is_dir()]} (have: {available})"
    )


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


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# PLACEHOLDER BINDING — strictly at ADMISSION, or fail loud THERE
# ═══════════════════════════════════════════════════════════════════════════════════════════════
#
# THE DEFECT THIS CLOSES (2026-08-09, found on the FIRST EVER execution of the autonomous dispatch
# path). `autonomous_review.yaml` declares `endpoint: "{dispatch_endpoint}"` and NOTHING bound it.
# The literal string reached an HTTP client:
#
#     [500 Internal] Invalid URL '{dispatch_endpoint}': No scheme supplied.   retry_count 16
#
# Three things made that possible, and the fix has to answer all three:
#
#   1. NOTHING BOUND IT. `direct_call` passed `step.endpoint` through raw.
#   2. NOTHING NOTICED. Both existing tests INJECT `dispatch_endpoint` into their bindings and then
#      assert the workflow used it — transport proven, sourcing never. The tests agreed with
#      themselves and never once asked the runtime.
#   3. NOTHING RAN IT. The step sat behind `can_invoke(mesh:dispatchDispositions)`, granted to
#      nobody, so it had executed ZERO times. The gate that made the system safe also made the bug
#      invisible — every expected-deny is a lid over virgin code.
#
# THIRD MEMBER OF THE UNBOUND-PLACEHOLDER CLASS (`{compartment}` audience binding, `{artifact_label}`
# cosmetics, now `{dispatch_endpoint}`), so it gets the general rule rather than a third patch:
# **every placeholder in a definition binds at ADMISSION or fails loud there** — never at
# HTTP-client time, sixteen retries deep, where the cause surfaces as a URL-parsing complaint three
# layers away from the thing that was actually missing.
#
# ONE VALUE, ONE HOME. Config placeholders resolve from the SAME source of truth the working
# supervised path already uses (`dispatch_driver.ENGINE_O_URL` <- ONTOLOGY_SERVICE_URL), never a
# second declaration that can drift from it.

_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class UnboundPlaceholder(WorkflowDefinitionError):
    """A definition names a placeholder the runtime cannot bind. Raised at ADMISSION."""


def collect_placeholders(node: object) -> set:
    """Every placeholder reachable in a PARSED definition.

    Parsed, never raw text: YAML comments are already gone, so prose that happens to contain
    `{...}` cannot manufacture a phantom requirement. Only values the executor can actually
    substitute are considered.
    """
    found: set = set()
    if isinstance(node, str):
        found.update(_PLACEHOLDER_RE.findall(node))
    elif isinstance(node, dict):
        for v in node.values():
            found |= collect_placeholders(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            found |= collect_placeholders(v)
    return found


def config_bindings() -> dict:
    """Runtime CONFIG placeholders — the deployment's own wiring, not per-request data.

    Sourced from the same env the working dispatch path reads, so the autonomous path cannot
    disagree with the supervised one about where engine-o lives.
    """
    engine_o = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084").rstrip("/")
    bff = os.getenv("CORTEX_BFF_URL", "http://iagent-cortex-bff:8090").rstrip("/")
    return {
        # The disposition write engine-a already performs on the SUPERVISED path
        # (`dispatch_driver`: f"{ENGINE_O_URL}/write_item_state"). Same endpoint, same source.
        "dispatch_endpoint": f"{engine_o}/write_item_state",
        "publish_endpoint": f"{bff}/internal/human_tasks/register",
        # origin_record's `written` step (item B, 2026-10-03) — same BFF, same env var.
        "origin_write_endpoint": f"{bff}/internal/origin/write",
    }


def bind_placeholders(definition: dict, trigger: dict) -> dict:
    """Substitute every placeholder in `definition`, or RAISE naming the unbound ones.

    Returns a bound COPY; the definition itself is git-asserted and never mutated.

    Failing here is the whole point. An unbound placeholder is a DEPLOYMENT defect — it is true of
    every run of this definition, not of this notice — so it must surface once, loudly, at
    admission, rather than as a retryable-looking transport error per invocation.
    """
    bindings = {**config_bindings(),
                **{k: v for k, v in (trigger or {}).items() if isinstance(v, (str, int, float))}}
    required = collect_placeholders(definition)
    missing = sorted(p for p in required if p not in bindings)
    if missing:
        raise UnboundPlaceholder(
            f"workflow definition {definition.get('id')!r} names placeholder(s) {missing} that the "
            f"RUNTIME does not bind. Available: config={sorted(config_bindings())} "
            f"trigger={sorted(k for k in (trigger or {}) if isinstance((trigger or {})[k], (str, int, float)))}. "
            f"This is a DEPLOYMENT defect, not a per-notice one — every run of this definition "
            f"fails identically. Bind it in `config_bindings()` (config) or supply it on the "
            f"trigger (data); do NOT let the literal reach a client, where it surfaces as a URL "
            f"parse error three layers from its cause."
        )

    def _sub(node):
        if isinstance(node, str):
            return _PLACEHOLDER_RE.sub(lambda m: str(bindings[m.group(1)]), node)
        if isinstance(node, dict):
            return {k: _sub(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_sub(v) for v in node]
        return node

    return _sub(definition)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# STUB VERBS — a verb a definition names before the engine that serves it exists
# ═══════════════════════════════════════════════════════════════════════════════════════════════


class StubVerb(_Declared):
    """A declared stand-in for a mesh verb that is not served yet.

    THE STUB IS DECLARED, NAMED AND DATED, never a Python branch: ``stub: true`` and a non-empty
    ``retired_by`` say on the row itself that this is not the verb, and what replaces it. Its
    ``returns`` renders from the run's context with the strict renderer, so a stub reads no store
    and performs no effect -- which is the only reason it may skip the stage-2 verifier. Honoured
    only from the registry, like every field that changes what a run does."""

    verb: str = Field(..., min_length=1)
    stub: Literal[True]
    retired_by: str = Field(..., min_length=1)
    returns: Any


def verb_dirs() -> "list[Path]":
    """``policy/verbs`` (if any) then every ``policy/overlays/*/verbs``, beside the definitions."""
    seed = definition_dirs()[0].parent / "verbs"
    return [seed, *sorted(p for p in (seed.parent / "overlays").glob("*/verbs") if p.is_dir())]


def load_stub_verbs() -> "dict[str, StubVerb]":
    """Every declared stub, keyed by verb. TWO DECLARATIONS OF ONE VERB ARE REFUSED -- name order
    would otherwise pick which canned answer a run sees."""
    out: dict[str, StubVerb] = {}
    for d in verb_dirs():
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            try:
                v = StubVerb.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
            except (OSError, yaml.YAMLError, ValidationError) as exc:
                raise WorkflowDefinitionError(f"{p}: invalid stub verb:\n{exc}") from exc
            if v.verb in out:
                raise WorkflowDefinitionError(f"{p}: stub verb {v.verb!r} is declared twice")
            out[v.verb] = v
    return out
