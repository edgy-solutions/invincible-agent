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
