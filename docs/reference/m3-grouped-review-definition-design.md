# M3 design — the grouped-review as a WorkflowDefinition (retire the hand-coded class)

**Status: DESIGN (overnight, unsupervised). Not wired. No schema finalized.** Per the standing ruling
(`pcn-extraction-sort.md` §Horizons + [[feedback_graph_derives_whole_stack]]): the declaration/`rendersAs`
layer must NOT be finalized under pressure — a rushed archetype-declaration schema becomes the contract
every future feature writes to. This doc shapes M3 and identifies its real blockers; it deliberately does
NOT commit a `rendersAs` schema or cut the runner over.

## Goal
Re-express the grouped-review process as a **git-asserted `WorkflowDefinition`** (the ADR-0029 Slice-1
model already in `restate_analyst/workflow_definition.py`), consumed by `_run_definition` + the executor,
retiring the hand-coded `grouped_review_workflow.py` (the `Workflow("GroupedReview")` class). The process
becomes DATA the system *runs*, not a feature it *contains*.

## What already exists (built, don't rebuild)
- **The definition model + loader** (`workflow_definition.py`, Slice-1): `HumanAwaitStep`,
  `SpoOperationStep`, `DirectCallStep`, `WorkflowDefinition`, `load_all_workflows("policy/workflows/")`.
  Git-asserted YAML, fail-loud validation, discriminated union on `kind`.
- **The fan-out substrate extension** (`workflow_bulk_resolve.py` + the grouped HumanTask): 1-approval-
  resolves-N is DONE. Per ADR-0029 the fan-out is *dissolved* by per-item invocation + a dispatcher —
  **zero new workflow-model step kinds needed.** The grouped review is a single `human_await`.
- **The per-item driver** (`dispatch_driver.py`, `DispatchItem` VirtualObject) — per-item idempotency.

## The definition shape (DRAFT — embedded here, NOT a loadable *.yaml)
Expressed entirely on the existing three step kinds. This is the *linear per-notice* spine; fan-out to N
items stays in the dispatcher (outside the definition), exactly as ADR-0029 §"worked example" rules.

```yaml
# DRAFT — illustrative only. Do NOT drop into policy/workflows/ until the blockers below clear
# (ontology classes + verbs, executor cutover, generic audience). Kept in this doc, not as *.yaml,
# so load_all_workflows() cannot pick it up.
id: grouped_review
name: Grouped disposition review
classification: null            # set per-compartment when observation (Slice-3) lands
participants: []
domain_stages: [scored, review, dispatched]
steps:
  # 1. The grouped human review — 1 approval resolves N (bulk-resolve substrate, already built).
  - kind: human_await
    id: review
    audience: "disposition_review:SUSTAINMENT"   # GENERIC audience — this IS the live key as of the
                                                 # M3.1 tail (blocker 3 cleared; sync still owed)
    subject_ref: null                            # the notice ref, threaded at start
    title: "Review affected part(s)"
    summary: "Affected parts need a disposition review"
  # 2. Dispatch the approved dispositions. direct_call = TRANSITIONAL, capability-GATED (can_invoke).
  #    A promotion candidate: register mesh:dispatchDispositions as a real verb -> spo_operation.
  - kind: direct_call
    id: dispatch
    endpoint: "DispatchItem/{item_key}/run"      # the per-item driver, invoked by the dispatcher
    capability: "mesh:dispatchDispositions"      # Topaz-decided; REQUIRED (no ungated step kind)
```

Notes: the extraction/matching/scoring stages are `spo_operation` steps in the full model, but they
require registered verbs on real ontology classes (blocker 1) — omitted from this draft spine, which
starts at the review (the human-await the current class implements).

## TEAM STEPS — completion + claiming as DECLARED policy (folded in 2026-07-29)

The live model is **any-one-of-the-audience acts for the team**: `register_task` materializes one row per
entitled actor and the first decision resolves them all (`acted_by` stamped, others' rows flip, the loser
now gets an honest 409-with-provenance — shipped `4b291d1`). That is correct and honest for a shared review
audience, and M3 inherits it **unchanged**. What teams ask for next — *"shouldn't two people sign off on an
LTB?"* and *"is someone already working this?"* — are NOT features to bolt onto the BFF. They change **what
a `human_await` step MEANS**, and M3 is precisely the milestone where step meaning becomes ratifiable data.
Building them as BFF patches now would hand-code workflow semantics one milestone before the point of M3 is
retiring hand-coded workflow semantics.

So they are **two orthogonal policy axes declared on `human_await`** — attributes, NOT new step kinds, so
the doc's "zero new workflow-model step kinds" claim survives intact:

```yaml
  - kind: human_await
    id: review
    audience: "disposition_review:SUSTAINMENT"
    completion: {kind: any-of}        # any-of (DEFAULT, today) | n-of-m {n: 2} | all-of
    claiming:   {kind: none}          # none (DEFAULT, today) | advisory | exclusive
```

**Defaults are today's behavior (`any-of` / `none`), so every existing definition is unchanged BY
CONSTRUCTION** — the fold cannot regress a deployed workflow. This also forces the answer to the doc's open
seal-inheritance question: **completion and claiming are EXECUTOR-owned semantics driven by declared
policy**, not per-definition machinery. A definition author writes `completion: {kind: n-of-m, n: 2}`; the
executor provides the join.

**The quorum engine already exists — this is the bulk-resolve pattern repeating, not new invention.**
Slice-5's multi-approval join (`slice-5-multi-approval-join.md`) is core-complete and sealed 12/12: the join
evaluator, suspend-vs-fail routing, the `PENDING → UNSATISFIABLE` oracle, and satisfiability re-evaluation
when entitlements change (the flip rider). It has been sitting **sealed at the core and unwired at the
driver** — the exact status bulk-resolve had before M1 wired it. M3.2's executor wiring a declared
`completion` policy to that evaluator is a **driver window over a sealed core**. When the N-of-M request
arrives (and a five-name audience says it will, within weeks of the first any-one-of deployment), the answer
is "the core is sealed, here is the wiring cost" — not a design effort.

`claiming: exclusive` (a hard lock) is **deliberately out of v1**: a lease needs expiry/steal/
release-on-navigate-away, and a claimed-then-abandoned task strands work. But the AXIS existing means
exclusive is an EXTENSION, not a redesign.

### Claim visibility is a property of the AUDIENCE, not of the step
`claiming: advisory` broadcasts that work is underway — which is where the collision-avoidance value
actually lives (*don't start what someone started*). But **naming the claimer discloses actor identity
across an audience**, and the observation model was built on not doing that casually (Slice-3's
existence-oracle closure, the `observer_view`/`audit_record` split, and Decision D's parked anonymous-count
question). A shared review audience is the weakest-privacy case — all five already see the same task and
will see `acted_by` at resolution — so naming is *probably* fine **here**; hardcoding "probably fine here"
into the projection is how it becomes the precedent for task kinds where it is NOT (the access-request
queue, cross-compartment cases).

The shape that survives scrutiny, and the DECISION this doc takes:
- **Claim STATE is always broadcast** in the anonymous form — *"in review since 14:02"*. That delivers the
  whole collision-avoidance benefit with zero disclosure.
- **Claimer IDENTITY is a per-audience disclosure declaration**, defaulting to anonymous, opted into where
  the audience's social contract warrants (a mutually-visible team) — i.e. it belongs with the audience
  declaration (`task_grants.yaml` / Topaz-adjacent), NOT as per-step boilerplate. Visibility is a fact
  about the audience, not about one step, so it is declared once and every step over that audience inherits
  it. Consequence: the access-request queue and the disposition team get DIFFERENT disclosure by their
  declarations, with no code branching per kind.
- This is **Decision D's sibling question, and it now has a forcing function** (parked questions with no
  forcing function rot). Cross-reference: `slice-3-observation.md` Decision D.
- Advisory-claim **expiry semantics need designing, not riding along**: *"bob is reviewing"* from a tab bob
  closed an hour ago is a new small lie. A claim is a lease with a visible age, and a stale claim must read
  as stale.

### Decision merging under quorum — the genuinely NEW design surface
The join math is sealed; the claim state is mechanical; **this** is the real work the fold introduces.
Today's path bakes in *one decision, one payload*: `submit_decision` validates ONE `BulkDecision` against
the server-authored batch and resolves a write-once promise. Under `n-of-m` there are **N partial approvals
arriving over time, with possibly CONFLICTING per-item overrides** — approver A overrides part 3 to LTB with
reason X while approver B accepts the proposal on part 3. What merged truth does the fan-out dispatch?

- **last-writer-wins** — REJECTED: silently discards a human's recorded judgment.
- **first-committed-per-item** — a middle path; still discards the later judgment, just less visibly.
- **per-item agreement required among the quorum's approvers → conflicts surface as a NAMED outcome that
  forces explicit reconciliation** — **the DECISION.** It is the only option that never launders an
  override, and "never launder an override" is already the system's most defended property. It is also the
  disposition-conflict rule one level up: honest ambiguity → forced human resolution (the proposer already
  ABSTAINS rather than picking when rules disagree; a quorum should too).

Corollary for the mechanics: **the write-once `decision` promise becomes a JOIN-COMPLETION promise resolved
by the EVALUATOR**, not by any single submitter. Each approval is recorded; the evaluator decides when the
completion policy is satisfied AND the per-item merge is conflict-free, and only then resolves. The
concurrency seal already written (`tests/test_grouped_review_concurrency.py`) is the `any-of` case of that
same invariant — exactly one resolve, therefore exactly one fan-out — and its quorum sibling must assert:
N-1 approvals do NOT fan out, the Nth does, and a conflicting Nth fans out NOTHING and names the conflict.

## rendersAs — SKETCH ONLY (do not finalize)
The presentation-per-step/verb layer (E-list `rendersAs` triples) is the M3 "PRESENTATION" third. The
DECIDED projection already exists as `pcn-dashboard-payload-schema.md` (the hand-assembled version of the
future declaration). The `rendersAs` shape it points at:
- `<verb> rendersAs:archetype <ARCHETYPE>` — a verb's output type declares its canvas archetype
  (GROUPED_REVIEW / INSTANCES_BY_PROPERTY / …), replacing cortex-ui's `taskKindRegistry` code table.
- `<class> rendersAs:tableColumns (…)` — a class declares its instances-by-property columns
  (the `pcn-dashboard-payload-schema.md` `columns[]`, per-property).
- `<class> rendersAs:filterableBy <property>`, `rendersAs:rowIdentity <property>`.
**Do NOT commit these triples or an `/instances` declarative schema now.** Trigger = the SECOND view that
wants an instances-by-property table (the presentation-generalization wake). Build archetype-SHAPED with a
hand-fed feeder until then (already the state: the renderer is generic; the feeder is the one specific
surface).

## Blockers (why M3 is not wired tonight — each is a real prerequisite, not caution)
1. **Ontology classes + verbs don't exist** (ADR-0029 Slice-2 dependency): Part / Notice / BOM classes
   with registered verbs. Without them the `spo_operation` steps can't declare real `(subject, verb)`
   URIs, and the stage-2 eligibility verifier has nothing to verify against.

   **AMENDED 2026-08-03 — this blocks LESS than it was read to block, and the correction matters
   because a work packet was written against the stronger reading.** The classes half landed in M3.1
   (`product_structure_extension.ttl` + `qualification_status_vocabulary.ttl`, both in the prime
   manifest). The verbs half blocks **the FULLER `spo_operation` stage model** — the extraction /
   matching / scoring stages this doc's own draft spine already omits. It does **NOT** block M3.2's
   acceptance: that spine is `human_await` + `direct_call`, and §Acceptance's second definition
   (ADR-0034's autonomous path) is that spine minus one step. Neither declares an `spo_operation`.

   The stage-2 verifier's fixture is likewise **already live**: `mesh:proposeDisposition` on
   `pcn:SustainmentNotice` is a real registered `(subject, verb)` pair reachable through
   `/find_compatible_verbs`, with parent-registration inheritance to PCN/PDN
   (`pcn-menu-growth-exhibit.md`). M3.2 verifies against that; it needs no new registration.

   **Three candidate verbs were assessed for registration and ALL THREE were declined** — the
   assessment is the deliverable, so it is recorded rather than left as an absence:
   - `mesh:composeReviewBatch` — **no compose-only ingress exists.** Composition is the
     `build_review_batch` step *inside* `ReviewStarter/start_review`, a handler already bound to
     `mesh:proposeDisposition`. Registering it is literally the dead-end menu entry
     `pcn_extension.ttl:10`'s standing rule forbids (verbs wake per-endpoint, never before): a menu
     item whose endpoint is step 2 of another verb's handler routes nowhere on its own.
   - `mesh:dispatchDisposition` — **declined as dangerous, not merely premature.** It is declared in
     this doc as a `direct_call` gated on capability `mesh:dispatchDispositions`. As a *verb edge* it
     would make dispatch reachable from the menu without the review, converting the approval gate from
     mandatory to optional-by-menu. Promotion-to-verb stays the already-named future candidate; the
     admission-gate architecture of workflow 2 argues it should never become menu-visible.
   - `mesh:resolveReview` — has a real endpoint (`GroupedReview/{key}/submit_decision`) and still
     fails, on a category argument: the interview offers verbs to **authors composing a workflow**,
     and resolution is a **participant act on an existing suspended instance**, not a step an author
     declares. Offering it would teach the menu a confusion it should not carry.
   **NAMED WAKE for M3.2 — there is no INTERNAL-VERB class, and the one verb that behaves like one
   escapes the menu by accident.** Declining all three above leaves a real hole documented rather than
   patched: `/operable_subjects` and `/find_compatible_verbs` treat **every** edge with `r.iri IS NOT
   NULL` as menu-eligible, so the capability graph has exactly one kind of registered verb — user-facing.
   `mesh:resolveInstance` is already the counter-example (ADR-0006 §"router-support predicates sit
   outside the invariant"), and it stays out of the SPO menu **only** because its pseudo-class input node
   carries no `domain`, so `/operable_subjects`' `s.domain = $domain` filter drops it. That is an
   accident of a missing property, not a rule, and it would stop protecting us the moment a
   process-internal verb is registered on a real domain-carrying class.

   The distinction is deliberately NOT designed here. A scope property on the registration shape
   (user-facing vs definition-only) is **declaration-layer schema**, and this doc's own §Status forbids
   finalizing that under pressure — it becomes the contract every future registration writes to. It also
   has a constraint that only its consumer can state: the split must be at the **menu** layer, never at
   the eligibility layer, because M3.2's stage-2 verifier must still be able to verify an internal verb
   it must never offer. **So it is defined FROM THE VERIFIER'S SIDE in M3.2, where it is first
   consumed** — one real consumer beats a speculative field. Until then the accident is documented as an
   accident, which is the minimum honest state. (ADR-0006 §Indicators already anticipates this exact
   move: *"the registration shape's vocabulary needs to grow, not the source-substrate invariant to
   weaken."*)

2. **The executor + runner cutover is a separate SEALED increment** (Slice-1 doc): `workflow_definition.py`
   is schema+loader ONLY. Running a definition needs the stage-2 verifier + dispatch + cutting the
   `BPMNWorkflowRunner` from the inline `GroupedReview` class to `_run_definition` — it touches the sealed
   runner and gets its own proven-to-bite seal. Not a thing to do unsupervised.
3. ~~**Generic audience naming**~~ — **CLEARED (git side) 2026-08-03, M3.1 tail.** The audience is now
   `disposition_review:<compartment>`: renamed in `task_grants.yaml`, in the two constructions in
   `src/iagent/gateway.py`, in `review_starter.py`'s contract docstrings, and in `AGENTS.md` — whose
   doctrine passage had been citing the domain-named key as its own example of doing this right (a
   generic TYPE carrying a domain-named INSTANCE key is still the domain in the entitlement model, one
   level down). Guarded by `test_cross_repo_contracts.py`, where **the colon is the discriminator**:
   `pcn_disposition:` is forbidden, bare `pcn_disposition` is not, because the TASK KIND of that name is
   a cortex-ui render contract that deliberately survives until M3.3 retires `taskKindRegistry`. Seal
   shown RED in both halves (grants + code) and restored byte-identical before it was trusted.

   **REMAINING, and it is a deploy step not a branch edit:** `task_grant_sync` must run to seed
   `task_audience:disposition_review:SUSTAINMENT` and prune the old relation. Between the git edit and
   that sync **the review routes to NOBODY** — `register_task` materializes zero rows →
   `NoEntitledRecipients` → 422 → the notice never reaches a human. Run the sync in the same window and
   re-drive one notice to witness it. This is the same proven sync the discrimination seal ran; the
   original "deploy-time" framing meant *lands with a sync step*, not *needs a deploy window*.

## Sequencing (per ADR-0029 slices)
- **Now (M2, done on this branch):** de-pcn the mechanism (engine-a/o + BFF + UI renamed generic). The
  `GroupedReview` Restate Workflow + `grouped_review` kind are already generic-named.
- **Next (M3.1):** author Part/Notice/BOM ontology classes + register their verbs (unblocks spo_operation
  steps + the SPO interview, ADR-0029 Slice-2).
- **M3.2:** build the definition executor (stage-2 verifier + dispatch) + cut the runner over to
  `_run_definition`, behind its own seal; land `policy/workflows/grouped_review.yaml`.
- **M3.3 (on the presentation trigger):** `rendersAs` triples; retire `taskKindRegistry` **and
  `_VERBS_BY_KIND`** (see below) + the hand-fed dashboard feeder. NOT before the second
  instances-by-property view.

## TWO interim per-kind tables now, and they retire TOGETHER
(Added 2026-07-31, from the triage-card work — recorded here because a coupling that exists only
in someone's head between a branch and a milestone is a coupling that gets orphaned.)

`cortex-ui`'s `taskKindRegistry` is no longer the only hardcoded per-kind lookup awaiting a served
declaration. The triage-card fix added **`_VERBS_BY_KIND` in `src/iagent/human_tasks.py`** — which
verbs each task species accepts (`extraction_refusal` → acknowledge/re-drive; everything else →
approve/reject). Same shape, same interim status, different repo.

**Naming only `taskKindRegistry` in M3.3 would orphan the other one** — the
retire-coupled-mechanisms-together rule, and the failure mode is the worse half surviving: a
served `rendersAs` declaration that says how a task RENDERS while a code table still decides what
it can DO.

### Verbs belong in the step schema — an M3.2 absorption item, not a new invention
`HumanAwaitStep` today carries `audience / subject_ref / title / summary / requested_by` and **no
verbs, no completion, no claiming.** But a step's verbs are the same *kind* of fact as its quorum
and its claiming behaviour — part of what the step MEANS — and this milestone's own north star is:

> A team step's quorum and claiming behavior changes by editing the definition YAML — zero code.

So **verbs are inside that sentence's scope and are currently outside YAML's reach.** Be honest
about how they got there: the triage task was recording `decision: approved` on *"this notice could
not be prepared for review"* — a decision the data cannot represent, which ADR-0034's decision
records would then archive immutably as promotion evidence. That could not wait for M3, so the
vocabulary went into code **deliberately**, making M3.2's absorption list one item longer rather
than letting the evidence corpus start polluted. The right trade, and a cost — not a freebie.

When M3.2 lands, `HumanAwaitStep` should grow the declaration (verbs, and the `completion` /
`claiming` the north-star sentence already names), and `_VERBS_BY_KIND` is deleted into it. Until
then the table is the interim, and the deletion note lives on it.

## Standards posture (the gap this doc originally missed)
This design covered BPMN→the SPO model but said nothing about ADR-0029's OTHER standards
(`ODCS/ODPS/CALM → directional and greenfield`). Those are **interchange/architecture-description**
standards with NO runtime to import — the BPMN "decline the interpreter" logic does NOT apply to them; the
failure mode is *premature* adoption, and the right shape is adopt-as-export/import-schema at the boundary,
on trigger, with the graph as sole authority. The full three-rule posture (domain=data · process=semantics-
mined · interchange=dialect-on-trigger), the instances, the two standing liabilities (compliance
conversation; first un-dissolvable branch), and the three armed wakes (ODCS↔the ADR-0032 DQ/coverage verb ·
ODPS↔first workflow-promotion · CALM↔first external-architecture ask / work compliance review) are in
**`standards-posture.md`** — the standalone note the ADRs cite. M3's `rendersAs` presentation layer is Rule-2
(graph-derived, not an imported presentation standard).

## Admission lives OUTSIDE the definition — and M3.2's second definition now has a real customer
(See [ADR-0034](../adr/ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md).)
Two boundary facts M3 **inherits as constraints** rather than re-deciding:

**The admission-vs-structure line.** *Whether* a notice enters the human path is an **admission** question
(how far the pipeline is trusted for this input class), decided by a ratifiable **trust table** consulted by
the starter. *What the process is* is a **structure** question, decided here. **No definition consults the
trust table, and no trust rung names a step** — the gate selects BETWEEN declared definitions, which is
legitimate (one gate, data-driven), rather than selecting behavior INSIDE one, which is the coupling
ADR-0029 killed. If an M3 step ever appears to need a trust posture, that is the layer leak ADR-0034's
acceptance sentences forbid: surface it, do not thread it.

**Workflow 2 IS the acceptance criterion, arriving funded.** The "NON-grouped definition on the same
executor" below was written as a discriminating test; ADR-0034's **autonomous disposition path** is that
second definition, and it is a real requirement rather than a synthetic case. Its shape is the strongest
available evidence the step model carved reality at the right joint: it is **the grouped review minus
exactly one step** (`human_await`) — same rules-fetch, same proposer, same `plan_dispatch`, same per-item
`DispatchItem` convergence. Build M3.2 expecting that diff, and treat *"the two definitions differ by one
step and nothing else"* as the design's own check on itself. Also inherited: **escalation out of the
autonomous path back into this one is mandatory** (ADR-0034 §7), and choosing its mechanism — a conditional
human step (the expressiveness wake's first customer) vs. terminate-and-start-workflow-1 — is deliberately
left as an **M3-time decision**.

## M3.2 SHAPE — CLOSED 2026-08-04 after reading the built code (both forks decided)

**The investigation's headline: the executor half is ALREADY BUILT, and the gap is EXPRESSIBILITY.**
Read before planning, and it contradicts this doc's own "M3.2 = build the executor" framing:

- `spo_step_executor.py` is **complete and Restate-pure** — `verify_spo_step` (the stage-2 structural
  verifier against `/find_compatible_verbs`), `dispatch_spo_step`, `check_can_invoke`,
  `execute_direct_call`, raising `StepFailAndRelease` for the runner to map.
- `_run_definition` **exists and is wired**: `BPMNWorkflowRunner.run` dispatches to it whenever
  `request["definition"]` is present — additive, dark-launched, the sealed inline loop untouched.
- `promote_answer_artifact.yaml` is a working definition proving the language drives the sealed path.
- `load_all_workflows` is called **only from a test**, so a new `policy/workflows/*.yaml` is inert at
  runtime until something loads it — adding the YAML is safe, but it is committed-but-unwired until
  the executor honours it, and must be labelled so ([[presence-in-repo-is-not-presence-in-running-system]]).

**What is actually missing is the grouped-resolution semantics.** `_run_definition`'s `human_await` is
a PLAIN approval: register task → `ctx.promise(f"approval_{id}").value()` → done. The hand-coded
`GroupedReview` additionally (a) persists a **server-authored batch** the submission validates
against, (b) **validates BEFORE resolving** — a refused submission leaves the workflow SUSPENDED with
no promise resolved, (c) guards the multiplayer race via `decision_consumed` → the honest 409 with
provenance, and (d) **fans out N** `DispatchItem` invocations. None of that has a home in the model.

### DECISION 1 — batch + fan-out stay OUTSIDE the definition
Not the cautious option, the doctrinally settled one. This doc already ruled it ("the fan-out is
*dissolved* by per-item invocation + a dispatcher — zero new workflow-model step kinds"), and
**ADR-0035's authorship criterion independently confirms it**: a step belongs in the definition if its
author belongs to that plane's discipline. Batch composition, server-authored validation, race
guarding and fan-out mechanics are **executor-discipline**, not process-owner declarations. A domain
expert authoring `grouped_review.yaml` declares THAT there is a grouped review, with this audience and
this completion policy — never HOW the server authors the batch or guards the 409.

The rejected option ("grow `human_await` to carry a payload/validator") was argued as making the
definition *truer*; it has it backwards. It would make the definition **leak executor internals**, and
it would finalize declaration-layer schema under exactly the pressure §Status fences. The
seal-inheritance ruling in the team-steps fold already answered this in principle: the sealed HITL
behaviours are **step-kind semantics the executor OWNS**, inherited by every `human_await` whose
resolution is a grouped decision. Declared policy SELECTS them; YAML never spells them. What the
grouped review does need expressible — `completion` (`any-of` / `n-of-m`) and `claiming` — is already
specced as declared ATTRIBUTES, which is the right altitude. **Policy in the definition, mechanism in
the executor.**

### DECISION 2 — `GroupedReview` KEEPS its service name; only its internals swap
**Cross-repo fact this doc did not know when it wrote "delete the file":** cortex-bff calls
`GroupedReview/{key}/submit_decision` and `/get_batch` **by URL** (`gateway.py:1094` / `:608`), and
`GroupedReview` is a frozen row in `tests/test_cross_repo_contracts.py`. Deleting the class is a
two-repo expand/contract migration with the same dangerous-interval shape as the M3.1 audience rename
— **for zero behavioural gain**, because the acceptance criterion's SUBSTANCE ("runs from the YAML via
`_run_definition`") is fully met by delegation.

So: the service name is the **interface**, the YAML is the **behaviour**, and swapping behaviour behind
a stable interface is what made every other migration in this arc safe. `GroupedReview.main()`
delegates to `_run_definition`; `submit_decision` / `get_batch` stay exactly where cortex-bff expects
them. **The acceptance criterion below is AMENDED accordingly** — acceptance criteria are records too,
and a record written before a fact is known gets corrected, not obeyed. The name's retirement rides
the same future window as the task-kind rename (M3.3's `taskKindRegistry` retirement), where
cross-repo presentation contracts migrate together.

### The resulting build list (bounded, and smaller than this doc's original framing)
1. **Teach `_run_definition`'s `human_await` the grouped-resolution semantics** — server-authored batch
   persisted, validate-before-resolve with refusal-stays-suspended, `decision_consumed` race guard,
   post-resolution dispatcher fan-out — lifted from the hand-coded class into the executor as the step
   kind's owned behaviour, selected by declared `completion` policy.
   **Known seam, and it is NOT an internal detail — RULED 2026-08-04.** `submit_decision` is a SHARED
   handler and cannot move into `_run_definition`'s main context, so the promise names must align:
   today the class awaits `ctx.promise("decision")` while `_run_definition` awaits
   `approval_{step.id}`.

   **A Restate promise name is durable journal state, which makes it an IDENTITY SURFACE ON LIVE
   DATA** — the same class as VirtualObject dedup keys at the M2 cutover, the `pcn_disposition:`
   audience key, and the employee-id rebind ahead. Fourth instance. The failure mode is specific and
   silent: a `GroupedReview` instance **suspended on `decision` at the moment of cutover**, whose new
   delegated code resolves `approval_{step.id}`, can never be resolved by ANY submission — suspended
   forever, no error, a task sitting in a queue that nothing can clear. That is the kill-seal's
   failure mode wearing a promise's clothes, and it is not hypothetical: the M3.1 contract phase had
   already stranded six pending task rows the same way, one layer down (see AGENTS.md, the FOURTH
   STEP of expand/contract).

   **RULING — make the durable name DECLARED CONTENT, so no dual-name interval ever exists:**
   `_run_definition` awaits `step.promise_name or f"approval_{step.id}"`, and the `approve` handler
   (main.py:1678, same construction at main.py:1631) honours the IDENTICAL rule — it must resolve
   what the executor awaits. `grouped_review.yaml` declares `promise_name: decision`, matching the
   name the shared handler already resolves; the prefixed default is retained so the dark-launched
   `promote_answer_artifact` path is byte-identical.
   Chosen over resolving both names during a transition (managing an interval instead of removing
   it) and over draining in-flight reviews (kept as the BELT — drain before cutover anyway, since it
   costs nothing on a sandbox and removes the last in-flight unknown). Rejected: dropping the
   `approval_` prefix globally, the obvious-looking alternative — that is a rename on a durable
   surface whose in-flight instances sit OUTSIDE the grouped-review drain's coverage, i.e. this same
   hazard applied to a path nobody was looking at, because a dark-launched path does not announce
   itself as live state.
   It is also the right shape independent of the hazard, and more honestly so than the original:
   the promise name is **definition content the author controls** OUTRIGHT, rather than a
   coincidence engineered through id-naming, and the durable identity lives inside the declared
   process rather than inside executor naming convention.

   **AMENDED 2026-08-03** (supersedes the mechanism ruled 2026-08-04; reasoning above is unchanged).
   As originally written this asserted `approval_{step.id}` == `decision` for `step.id = "decision"`,
   which is FALSE — evaluated, that is `approval_decision`, and the `approval_` prefix is an executor
   literal no definition content can delete. So the original mechanism produced precisely the silent
   permanent suspension this section was authored to prevent. The wrong ruling is left on the record
   deliberately: it is the evidence the equality guard below cites for its own existence, and the
   first instance of the conventions rule *a ruling that asserts a string identity gets EVALUATED,
   not read* (AGENTS.md).
   **Seal it:** assert the promise name the executor awaits equals the one `submit_decision`
   resolves — a string-equality guard that goes red the moment either side is renamed, which is the
   only thing standing between a future rename and a permanently suspended workflow.
2. **`policy/workflows/grouped_review.yaml`** — the first real definition exercising it.
3. **`GroupedReview.main()` delegates**; the two shared handlers stay.
4. **Workflow 2** (ADR-0034's autonomous path) — a second YAML, one step absent, same executor. The
   funded acceptance that the runner is definition-driven, not class-driven.
5. **Regression gate = the EXISTING seals re-run against the delegated path** — the concurrency/race
   test, refusal routing, kill-seal convergence. Same behaviours, new driver, witnessed equal. Plus a
   proven-to-bite seal on the cutover itself.

## Acceptance when M3.2 lands
~~The hand-coded `grouped_review_workflow.py` is deleted~~ — **AMENDED 2026-08-04, see Decision 2:**
`GroupedReview` KEEPS its Restate service name and its `submit_decision` / `get_batch` handlers,
because cortex-bff calls them by URL and the name is a frozen contract-seal row; its **`main()`
delegates to `_run_definition`**, so the hand-coded ORCHESTRATION is what dies, not the file. The
original phrasing was written before that cross-repo fact was known.

The grouped review runs from `policy/workflows/grouped_review.yaml` via `_run_definition`; the sealed
HITL mechanics (register-before-suspend, `can_act`, promise resolve, bulk-resolve) still pass their
seals — **re-run against the delegated path as the cutover's regression gate**, same behaviours, new
driver, witnessed equal; and a NON-grouped definition (a plain approval — or, per ADR-0034, the
autonomous disposition path) runs on the same executor — proving the runner is definition-driven, not
class-driven.

**And the sentence that makes "configurable workflow" FALSIFIABLE — the milestone's north star, not a
feature request trailing behind it:**

> A team step's **quorum and claiming behavior changes by editing the definition YAML — zero code.**

Concretely: flipping `completion: {kind: any-of}` → `{kind: n-of-m, n: 2}` in
`policy/workflows/grouped_review.yaml` makes the review require two sign-offs, with no deploy of engine-a,
cortex-bff, or cortex-ui; flipping `claiming: none` → `advisory` makes concurrent work visible, same way.
If either needs a code change, M3.2 has not landed — it has only moved the hand-coding.
