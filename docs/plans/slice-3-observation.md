# Slice 3 design — type-2 workflow observation (the domain-vocabulary "watch my workflow" view)

Implements ADR-0029 **Decision 4** (the 3-audience observation ruling) and consumes what
Slices 1–2 already declare: a `WorkflowDefinition` carries `classification`, `participants`,
`domain_stages`, and `observable_state`, and the runner produces per-step runtime results.
Slice 3 turns those declarations into a **gated observation projection**: given a workflow's
runtime state and an observer, compute exactly what that observer may see — no bespoke
observation ACL, the single decider (Topaz) reused.

## 0. What already exists (the ground this stands on)

- **Declared observable surface** — `WorkflowDefinition.observable_state = {visible: [...],
  internal: [...]}` (e.g. `promote_answer_artifact.yaml`: visible `[domain_stages,
  approve_promotion.status]`, internal `[publish_artifact.result]`). The *author* decides
  which fields are observable at all; Slice 3 never surfaces an `internal` field to anyone.
- **Declared parties** — `participants[] = [{role: initiator}, {role: approver}]`; at runtime
  each role binds to an identity.
- **Declared stages** — `domain_stages[]` = ordered user-vocabulary labels
  (`[awaiting_approval, publishing, published]`).
- **Runtime state** — the runner (`restate_analyst/main.py run` / `_run_definition`) executes
  steps and produces per-step `{id, status, result}`. Slice 3 consumes a normalized projection
  of that (per-step `{id, kind, status, subject?, actor?}` + `current_stage` + role→identity),
  produced by the driver from the runner's state + the definition.

## 1. The two filters (in order) — declared surface, then audience gate

A field is observable to an observer **iff** it passes BOTH:

1. **The author's declared surface** (`observable_state`): `internal` fields are never
   surfaced to anyone. This is the definition author's choice, not an authz decision.
2. **The 3-audience gate** (Decision 4), applied per element by the observer's relationship to
   the workflow. This is the Topaz-decided authz overlay.

Filter 1 before filter 2: an `internal` field is invisible even to a fully-cleared observer;
a `visible` field is still gated by the audience tier.

## 2. The 3-audience tiers (Decision 4), as enforcement rules

| Element | Tier | Rule |
|---|---|---|
| The workflow's `domain_stages` + `current_stage` | self / cleared | visible if the observer is a **participant** OR is **classification-cleared** to observe the workflow at all; else the whole projection is a deny (see existence-oracle). |
| An **agent-action** step (`spo_operation` / `direct_call` / service) | agent-actions, clearance-bounded | visible **iff** the observer may `can_view` the step's **subject/compartment** (the same sealed ontology-visibility gate). An agent action over a subject you can't see is redacted. |
| A **human-action** step (`human_await`) performed by **self** | self-participation | always visible to that participant. |
| A **human-action** step performed by **another human** | other-humans, restricted | **deny by default** — redacted ENTIRELY (not just the actor blanked), because the *existence* of another party's action on a compartmented workflow is itself intelligence (existence-oracle). Revealed only under an **explicit** other-observers grant. |
| Another party's **participation** (that role X is bound to human Y) | other-humans, restricted | same deny-by-default; self sees its own binding, others need the grant. |

**Classification-gated by construction:** the workflow's `classification` + the observer's
grants decide what each tier sees. Nothing here is a new ACL — `can_view` is the existing
ontology-visibility gate, and the other-humans grant is a Topaz relation like the others.

## 3. The pure core (this slice) — `workflow_observation.py`

Mirrors `spo_interview.py` / `spo_step_executor.py`: a **pure, enforceable, unit-testable**
module with **authz injected** (the Topaz calls live in the thin driver, so the *gating logic*
is testable without a cluster). Shapes:

- `StepRuntime{id, kind, status, subject?, actor?}` — one runtime step.
- `WorkflowRuntimeState{workflow_id, current_stage, steps[], participant_bindings{role→id}}`.
- `ObservationProjection{workflow_id, visible, classification?, domain_stages[], current_stage?,
  steps[], participants[], redactions[]}` — the redacted view (plus an audit list of *what* was
  hidden and *why* — never the hidden content).

Entry point:

```
project_observation(
    definition, runtime, observer, *,
    observer_role,            # the observer's participant role, or None (self-tier)
    can_observe_workflow,     # classification clearance to see the workflow at all
    can_view_subject,         # (subject_uri) -> bool  (agent-action clearance; Topaz can_view)
    can_observe_others=False, # explicit other-humans grant (deny-by-default)
) -> ObservationProjection
```

- **Deny-by-default is the constructor default** (`can_observe_others=False`) so a driver that
  forgets to pass the grant fails CLOSED, not open. Same discipline as the enforcement funnel.
- A step's kind decides which tier applies; `actor == observer` promotes a human step to the
  self tier; `subject` drives the agent-action `can_view`.
- An `internal` field never appears in the projection regardless of authz.

## 4. The driver (spec — deploy-gated, not this slice)

A thin observation handler (`ProcessInterviewerV2`-style, or a new observation service) that:
maps the runner's runtime state → `WorkflowRuntimeState`; asks Topaz the four questions
(participant? classification-clear? can_view each subject? other-observers grant?); calls
`project_observation`; returns the projection to cortex-ui. The **Restate UI stays the operator
view**; cortex-ui is the **domain** view (this projection). The other-observers grant needs a
git-asserted namespace (like the other grants) — filed as a follow-up.

## 5. Composed-path seal (spec)

Two observers on ONE compartmented workflow instance see **different** projections — a
participant sees their own human-await + the domain stages; a non-participant, non-cleared
observer sees a deny; a cleared-but-not-granted observer sees the agent steps over subjects they
can view but NOT the other party's human action. The discriminating seal (like the ontology
`can_view` and HITL-queue seals): prove the redaction is real, both sides, on the same instance.
