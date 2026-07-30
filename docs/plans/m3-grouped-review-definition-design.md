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
    audience: "disposition_review:SUSTAINMENT"   # GENERIC audience (see blocker 3); today's live
                                                 # value is task_audience pcn_disposition:<compartment>
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
2. **The executor + runner cutover is a separate SEALED increment** (Slice-1 doc): `workflow_definition.py`
   is schema+loader ONLY. Running a definition needs the stage-2 verifier + dispatch + cutting the
   `BPMNWorkflowRunner` from the inline `GroupedReview` class to `_run_definition` — it touches the sealed
   runner and gets its own proven-to-bite seal. Not a thing to do unsupervised.
3. **Generic audience naming**: the live audience is `pcn_disposition:<compartment>` (task_audience). The
   definition should carry a generic `disposition_review:<compartment>` (or `review:<compartment>`) — but
   that's a git-rails grant rename (`task_grants.yaml`) coordinated with a live Topaz reseed, which is a
   deploy-time change, not a branch edit.

## Sequencing (per ADR-0029 slices)
- **Now (M2, done on this branch):** de-pcn the mechanism (engine-a/o + BFF + UI renamed generic). The
  `GroupedReview` Restate Workflow + `grouped_review` kind are already generic-named.
- **Next (M3.1):** author Part/Notice/BOM ontology classes + register their verbs (unblocks spo_operation
  steps + the SPO interview, ADR-0029 Slice-2).
- **M3.2:** build the definition executor (stage-2 verifier + dispatch) + cut the runner over to
  `_run_definition`, behind its own seal; land `policy/workflows/grouped_review.yaml`.
- **M3.3 (on the presentation trigger):** `rendersAs` triples; retire `taskKindRegistry` + the hand-fed
  dashboard feeder. NOT before the second instances-by-property view.

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

## Acceptance when M3.2 lands
The hand-coded `grouped_review_workflow.py` is deleted; the grouped review runs from
`policy/workflows/grouped_review.yaml` via `_run_definition`; the sealed HITL mechanics (register-before-
suspend, `can_act`, promise resolve, bulk-resolve) still pass their seals; and a NON-grouped definition
(a plain approval) runs on the same executor — proving the runner is definition-driven, not class-driven.

**And the sentence that makes "configurable workflow" FALSIFIABLE — the milestone's north star, not a
feature request trailing behind it:**

> A team step's **quorum and claiming behavior changes by editing the definition YAML — zero code.**

Concretely: flipping `completion: {kind: any-of}` → `{kind: n-of-m, n: 2}` in
`policy/workflows/grouped_review.yaml` makes the review require two sign-offs, with no deploy of engine-a,
cortex-bff, or cortex-ui; flipping `claiming: none` → `advisory` makes concurrent work visible, same way.
If either needs a code change, M3.2 has not landed — it has only moved the hand-coding.
