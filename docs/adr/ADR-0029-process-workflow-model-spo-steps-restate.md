---
status: Accepted (model shape + process→Restate seam) — other standard seams DIRECTIONAL / greenfield; build deferred to slices
date: 2026-07-12
deciders: Platform team
---

# ADR-0029 — The process-workflow model (SPO-native steps on Restate; the standard→substrate mapping)

## Status

**Accepted** for: (1) the **process-workflow model shape** — SPO-native steps +
human-await steps, git-asserted definitions, executed on the Restate durable-
execution primitive, **superseding the BPMN→Dagster machinery**; and (2) the
**standard→substrate mapping**, with honest per-seam status (BPMN→Restate
**decided/built-on**; ODCS/ODPS→Dagster+DataHub and CALM→graph **directional and
greenfield**). The **build is deferred to slices** (see Rollout); the first slice
re-expresses the already-sealed HITL promotion workflow against this model before
anything new is added.

This answers, for the *process* seam, the question ADR-0024 Part A reserved
("which standard is authoritative for which concept, on which substrate") — not by
settling all four standards, but by *stating the mapping* and *deciding the one
seam that has a real consumer today*.

## Context

Everything the downstream vision waits on — the HITL's real workflow source, the
canvas's Use-3 answer-seeding ([[ADR-0028]]), type-2 workflow observation,
[[ADR-0027]]'s multi-approval — needs **a workflow-definition model**: what a
workflow *is* (its steps, human-await points, participants, observable state,
classification), such that it's declarable, executable, observable, and seedable
from answers. A 2026-07-12 survey (three code-reality agents + the ADR/requirements
synthesis) established the following, which this ADR builds on:

**1. Everything that exists is BPMN, mis-routed to Dagster — one wrong turn.**
- The `ProcessInterviewer` (Socratic interrogator) → BPMN payload → Dagster job
  compile is a **process standard forced onto an asset substrate.** Dagster models
  asset materialization; it has no natural "suspend for days awaiting a human
  approval." BPMN models process; its natural substrate is durable execution.
- The **`BpmnCatalog`** (Postgres, LLM-generated BPMN blobs) is written on the live
  path (auto-compile) but read only by Dagster at cold-start; the `/bpmn/catalog`
  GET has no caller. Most tellingly, the **one workflow with a real human-await —
  the sealed HITL Case-2 promotion workflow — bypasses it entirely**, running on the
  Restate `BPMNWorkflowRunner` with an *inline* task list and `ctx.promise()`
  suspend/resume. Your own build already routed around the catalog when it needed a
  real process workflow. Verdict: **supersede, don't build on.**
- The interrogator is **deeply BPMN-fused** (the BAML `IterateBPMNGraph` prompt,
  `BPMNInterviewState` of nodes/edges/gateways, and the graph validation are
  BPMN-shaped throughout — "the emit-BPMN step *is* the interview logic"). It is
  **not re-pointable as code** — re-aiming it is a rebuild, not an adapter.

**2. The one keeper is a pattern, not a component.** The interrogator's *interview
pattern* is **mesh-informed select-from-authorized-set**: it injects live ontology
classes (Engine O) + data sources (Engine D) and constrains the user to exact
matches from those lists ("no match → suggest closest"). That is the
[[feedback_select_from_authorized_set]] discipline *applied to authoring*, and it
transfers even though the BPMN code does not. It also has a gap this model fixes:
**it never asks which VERB** — it captures subject + data-source but no predicate.

**3. A step is SPO-shaped, and that is the design spine.** The survey tested the
hypothesis that a workflow step is an SPO operation `(subject, verb, output)` such
that an *answer* — an SPO operation that already ran — can seed one. Finding:
today's tasks are NOT SPO (opaque `{id, endpoint, service_payload}`), but **answers
ARE SPO** (`routing.about` = subject, `routing.action` = verb, `rendered_output` =
object), and **the system already routes `(verb + subject) → engine`** (the
supervisor, recorded in `routing.handled_by`). So *defining* a step as an SPO tuple
makes it **executable by the same router that answers queries**, and answer→step
seeding becomes native. The impedance mismatch the survey found is with the *old
endpoint-task shape* — the thing being superseded.

**4. The requirements are all process-workflow requirements, already accumulated.**
human-await points (HITL, [[feedback_hitl_suspend_vs_fail_ruling]]: designed-awaits
suspend, denials fail); domain-vocabulary stages, participants, observable state,
and 3-audience access tiers (type-2 observation — *not yet ADR'd*); answer-as-step
([[ADR-0028]] Use-3); N-HumanTask multi-approval joins decided on the single decider
([[ADR-0027]]); classification/compartment gating observers (enforcement). None is a
data-pipeline requirement — the consumers all want *process* workflows.

**5. The substrates all exist; the other three standards are greenfield.** Restate
(durable exec, proven), Dagster (asset orchestration, doc-tools ingest), DataHub
(catalog), the graph/ontology (Neo4j + `ontology_service`). But **ODCS, ODPS, CALM
have ZERO application-code presence** (only the DataHub SDK carries the classes in
venv). So the standard→substrate mapping is a real *direction* but entirely
unbuilt beyond BPMN — there is nothing partial to reconcile.

## Decision

### 1. The process-workflow model

A **workflow definition** is a **git-asserted declaration** — authored/reviewed in
git like `asset_grants.yaml` / `task_grants.yaml`, so it is blame-auditable and
**composes with classification + grants** — executed on the **Restate durable-
execution primitive** (the existing `BPMNWorkflowRunner`, reused as the *executor*;
the *definition language* changes from BPMN to SPO-native). It **supersedes
`BpmnCatalog`** as the definition source. Shape:

```
WorkflowDefinition {
  id
  name
  domain_stages[]        # user-vocabulary stage labels (for observation)
  classification         # compartment/marker — gates who may OBSERVE (enforcement overlay)
  participants[]         # declared parties (for observation + self-participation access)
  steps[]                # ordered / DAG of:

    SPO-operation step:
      { subject, verb, expected_output? }
      # executed by the router (verb+subject → engine); seedable from an answer.
      # inherits the FULL eligibility intersection at execution — see Decision 5.

    human-await step:
      { audience, title, summary, subject_ref }
      # suspends on ctx.promise().value(); registers a durable HumanTask
      # (kind=workflow_ack) gated by Topaz can_act on `audience`.
      # multi-approval = N such steps JOINED, join decided by Topaz rego (ADR-0027) —
      # NOT a parallel approval engine.

    direct_call step (TRANSITIONAL — escapes the verb ontology, NOT the gate):
      { endpoint, capability }
      # for infrastructural actions not (yet) a mesh verb (e.g. a publish emit).
      # STILL GATED on the single decider: Topaz can_invoke(caller, capability).
      # A direct_call is a promotion candidate — it is CLOSED by either registering
      # its action as a real verb (-> spo_operation) or by capability-gating. The
      # model MUST NOT contain a permanently-ungated step kind (that is the bypass
      # class — in-code fallbacks / second deciders / ungated paths — the model exists
      # to eliminate). See Decision 6.

    (timer / event steps as needed)

  observable_state       # which steps/fields are OBSERVABLE vs internal (Decision 4)
}
```

Non-negotiable: the model must express the **sealed HITL Case-2 promotion workflow
without breaking it** (inline definition, service + human-await + subsequent
service step, `ctx.promise` suspend/resume, `audience`→Topaz `can_act`, durable
pre-suspend registration, identity threaded). That is the first-slice proof.

### 2. The standard→substrate mapping (ADR-0024 Part-A, answered as a mapping)

Each standard's content lives/executes on the substrate its shape fits. Status is
honest per seam:

| Standard | Models | Substrate | Status |
|---|---|---|---|
| **BPMN** | process (activities, human-tasks, approvals, long-running) | **Restate** (durable exec + `ctx.promise`) | **DECIDED / built-on** — this ADR; proven by the sealed HITL workflow |
| **ODCS** | data contracts (schema, quality, guarantees) | **Dagster** (asset checks) + **DataHub** | DIRECTIONAL / greenfield (zero code) |
| **ODPS** | data products (asset bundles, outputs, consumers) | **Dagster** (asset groups) + **DataHub** | DIRECTIONAL / greenfield (zero code) |
| **CALM** | architecture (components, relationships, controls, topology) | **the graph / ontology** (Neo4j + `ontology_service`) | DIRECTIONAL / greenfield — descriptive, likely not an *executor* target at all |

The mis-route was **BPMN→Dagster specifically** (process onto asset). This does not
delete Dagster — Dagster keeps its data-plane role — it corrects *which standard*
lands there. The directional rows are **stated so a future builder knows where each
lands**, but are unbuilt; converting them from directional to decided is a separate
trigger (per ADR-0024's per-standard-integration discipline).

### 3. The interrogator: supersede the machinery, keep the pattern, add the verb

- **Supersede** the BPMN-fused interview machinery (`IterateBPMNGraph`,
  `BPMNInterviewState`, gateway/dead-end validation) with the `BpmnCatalog`.
- **Keep** the mesh-informed **select-from-authorized-set interview pattern** —
  re-implemented for the SPO model: ask **subject** (from the ontology/asset catalog
  it already injects), **verb** (from the eligibility intersection — the predicate
  the current interview *never asks*), and **output**. This produces the SPO step
  shape directly and is *more* mesh-informed than today.
- The same pattern later authors ODCS/ODPS (the greenfield future the pattern
  enables) — not built here.

### 4. The 3-audience observation ruling (pinned deliberately)

Declaring `participants` + `observable_state` decides the observation access model
*by implication* unless ruled. Pin the three tiers explicitly:

1. **Self-participation** — a party to a workflow may observe *their own*
   participation and the workflow's declared domain-stage state.
2. **Agent-actions, clearance-bounded** — agent-performed steps are observable
   bounded by the observer's clearance (the enforcement overlay: an observer sees an
   agent action only over subjects/compartments they may view).
3. **Other-humans, restricted (existence-oracle)** — other humans' participation
   and actions are restricted; revealing them can be an existence-oracle leak
   (that a party *exists* on a compartmented workflow is itself intelligence). Deny
   by default; reveal only under an explicit grant.

Observability is thus **classification-gated by construction** (the workflow's
`classification` + the observer's grants decide what each tier sees), reusing the
single-decider (Topaz), not a bespoke observation ACL.

### 5. SPO-step execution — the router call shape, and enforcement by construction

**The design question inside the elegant idea:** the supervisor's router is
*query-shaped* (a human asked; synthesis is for a human; output expectations are
answer-shaped). A **step is not a query** (no human asking, output may feed the next
step, not a person). So invoking the router from a workflow step needs a **step
call-shape** that is not "pretend it's a user query." Getting that shape right is
the load-bearing engineering task of the first slice; everything builds on it.

**Refinement (a step is PRE-RESOLVED — the precise seam):** a query starts from NL and
must *resolve* to `(subject, verb)` (stages 1 + 3); a step *declares* them, so it is
already resolved. A step therefore does NOT invoke the NL-resolution half — it invokes
**stage 2 (the structural eligibility gate) as a VERIFIER**, then dispatches. This is
strictly better than "invoke the router as a query": no stochastic re-interpretation of
a declared step (fatal for a repeatable workflow), and enforcement is literal at the
dispatch seam — the declared verb must be in the caller's eligible set or the step
**fails-and-releases** (`TerminalError`, Situation C; a denial is a failure, never a
suspend).

**The upside, stated as a decided property:** a step executed by the same router
that answers queries **inherits the full eligibility intersection — domain ∩ arity ∩
argument-fit ∩ permission** ([[feedback_verb_eligibility_intersection]]). Therefore
**workflow steps are access-governed by construction**, exactly like the canvas's
SPO composition ([[ADR-0028]]) — the enforcement model reaches the workflow layer
*for free*, with no separate workflow-authz surface. **The load-bearing consequence:
a workflow CANNOT be used to launder access.** You cannot declare a step with a verb
you are not eligible for and have it execute — the stage-2 verifier catches it against
the *caller's* identity. A workflow is **bounded by its initiator's grants, by
construction, at every step** (identity = the initiator, the sealed precedent: the
runner already threads `user_jwt` into every task; starting a workflow cannot grant
authority the initiator lacks). That is the property that makes workflows safe at
classification. **Delegated authority** (an approver's authority carrying into a later
step) is a DEFERRED, separate decision — and when opened, its shape is **"the approval
ISSUES A GRANT that authorizes the step" (the [[ADR-0027]] grant-issuance model), NOT
"the step impersonates the approver"**; it is a privilege-escalation-by-design surface
needing its own ruling AND its own seal.

**Pre-flight permission check — advisory fail-fast, sibling to the dispatch gate (RULED).**
Dispatch-time enforcement (the stage-2 verifier at each step) is the SOLE AUTHORITATIVE
gate. But a workflow whose steps are **statically declared** can be checked at *start*:
if a declared step is already outside the initiator's eligible set, the workflow is
predestined to fail, and it must **fail at start — before executing any step or routing
any human-await task.** The harm this prevents is concrete: routing a HumanTask for an
approval on a workflow that was always going to fail a later step consumes an authorized
approver's attention on a doomed request — and at classification, *creating* that task is
itself an existence-oracle emission (it reveals the workflow/subject exists) for a request
that auto-fails anyway. This is [[ADR-0027]]'s **auto-checks-before-human-routing
precedence** (auto-checked necessary-conditions are denied BEFORE any human-approval task
is created) applied to workflow *execution*.

Three properties keep this safe in a single-decider architecture, and must not drift:

- **It never grants and never substitutes.** The pre-check asks the SAME decider (Topaz,
  via the same stage-2 verifier) the SAME question, merely earlier. It is structurally
  incapable of becoming a second decider or a bypass; its only power is to fail early. A
  pre-check result is **never cached or carried as authorization** — dispatch re-asks,
  authoritatively, at execution.
- **When wrong, it is wrong in the SAFE direction.** A pre-check can only fail a workflow
  at start that would have failed at step 4 anyway (over-caution — an availability cost,
  never an over-grant); it can never let through what dispatch would deny. That asymmetry
  is *why* an advisory check is admissible at all under a single decider.
- **It covers statically-declared steps only.** A step whose subject/verb is fixed in the
  definition is pre-checkable; a step whose subject comes from a prior step's output (if the
  model ever grows dynamic subjects) is NOT, and falls through to the dispatch gate alone —
  correct, because dispatch is authoritative. **Pre-flight-passed does NOT mean the whole
  workflow is cleared** — only that no statically-declared step is already ineligible.

Implementation (where the pre-check runs, how it batches the verifier calls) is a
Slice-2-or-later design detail; this ruling fixes the *decision* — advisory, same-decider,
safe-direction, static-scope — so it cannot later be quietly turned into a caching
authorization layer.

### 6. The conversation→Dagster-job compile feature — retired

The `ProcessInterviewer` → BPMN → auto-compile → `BpmnCatalog` → Dagster-cold-start
path is **retired** as part of superseding the BPMN machinery. If any independent
value is later found in "compile a conversationally-authored *data pipeline* to
Dagster," it is a *separate, ODCS/ODPS-shaped* feature authored by the re-aimed
interview pattern — not a BPMN process compiled to Dagster. It does not linger as an
orphan writing blobs to a superseded catalog.

## Rollout / slices

- **Slice 1 (the proof):** re-express the **already-sealed HITL Case-2 promotion
  workflow** as an SPO-native git-asserted `WorkflowDefinition` executed on Restate.
  Success = it still runs, still suspends on the human-await, still routes the
  approval via Topaz `can_act`, and still seals (allow/deny discrimination). This
  proves the model against the one workflow known to work *before* anything new is
  added. Design the **step call-shape** (Decision 5) here. If the SPO definition
  cannot express the promotion workflow, that is learned early and cheaply.
- **Slice 2:** the re-aimed SPO interview (Decision 3), producing SPO definitions.
- **Slice 3:** type-2 observation (Decision 4) — domain-stage view, gated per the
  3-audience tiers.
- **Slice 4:** canvas answer→step seeding ([[ADR-0028]] Use-3) — native, since a step
  is an SPO tuple and an answer is an SPO op that ran.
- **Slice 5:** multi-approval joins ([[ADR-0027]]) — N human-await steps, join on
  Topaz rego.
- **Later / triggered:** the ODCS/ODPS/CALM seams (Decision 2) — greenfield, per
  ADR-0024's per-standard-integration triggers.

## Consequences

- **The keystone unblocks its four consumers** (HITL real source, canvas Use-3,
  type-2 observation, ADR-0027 approvals) — but only after Slice 1 proves the model
  on a real case, not on paper.
- **Enforcement reaches the workflow layer for free** (Decision 5) — no separate
  workflow-authz to build or seal.
- **One wrong turn retired cleanly** (interrogator machinery, `BpmnCatalog`,
  Dagster-compile) — and because the other standards are greenfield, there is no
  partial implementation to reconcile.
- **Risk:** the step call-shape (Decision 5) is unproven; if the router can't be
  cleanly invoked from a step, the SPO-native execution needs rethinking — which is
  why it is the explicit load-bearing task of Slice 1, not an assumption.
- **Honest scope:** standards composition beyond the process seam stays directional;
  this ADR states the mapping, it does not build ODCS/ODPS/CALM.

## Non-goals

- Building ODCS/ODPS/CALM authoring or execution (Decision 2 states the mapping;
  the build is triggered later per ADR-0024).
- The observation UI, the seeding interaction, or the new interview — later slices.
- Any BPMN/CALM authority reconciliation inside a standard (ADR-0024 Part A's
  cross-standard seams stay reserved).

## Related

- [[ADR-0024]] — standards composition (Part A reserved; this ADR answers the
  *process* seam as a substrate mapping and supersedes the BPMN→Dagster attempt).
- [[ADR-0028]] — the canvas; Use-3 (answer→step seeding) is a consumer; SPO
  composition is the sibling shape.
- [[ADR-0027]] — composable approval; multi-approval joins are workflow-shaped,
  decided on the single decider.
- [[ADR-0025]] / [[feedback_verb_eligibility_intersection]] — the eligibility
  intersection steps inherit by construction.
- [[feedback_hitl_suspend_vs_fail_ruling]] — designed-awaits suspend; denials fail.
- [[feedback_select_from_authorized_set]] — the interview pattern kept from the
  interrogator.
