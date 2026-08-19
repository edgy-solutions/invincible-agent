# STOP-AND-REPORT — the M3 gap read is already done, in the artifact

**2026-08-19.** Commissioned as "read `PcnGroupedReview` against the three step kinds, produce
the PCN process as a draft definition YAML, enumerate what doesn't fit." **Do not commission
this.** All three deliverables already exist in the repo, and the premise they rested on is stale.

## The premise, checked

> *"PCN … landed as hand-coded Python (`PcnGroupedReview`), bypassing the definition layer
> entirely, with the M3 milestone … filed and never started."*

**`PcnGroupedReview` is in a FORBIDDEN list.** `tests/test_cross_repo_contracts.py` asserts that
it, `PcnReviewStarter`, `PcnDispatchItem`, `pcn_grouped_review`, `write_pcn_disposition_state`,
`pcn_parts_by_state` and `resolve_pcn_instance` **must not survive anywhere in the mechanism**
— "deletion test, code layer". **9 tests, green.** The hand-coded class is gone and its return
is sealed against. The deletion-test roadmap the assignment describes as the thing M3 can't
start without is not only started, it is **enforced**.

## The draft YAML exists — it is `policy/workflows/grouped_review.yaml`

Authored `2d268b7`, header: *"SPO-native re-expression of the grouped disposition-review
workflow (ADR-0029 M3)."* It carries its own status line: **"definition ARTIFACT only (M3.1).
NOT yet wired to `_run_definition`."**

## The question the assignment posed is ANSWERED IN THE FILE

> *can the three-kind model express PCN at all?*

**Yes, with ZERO new step kinds** — stated in the artifact:

> *"Per ADR-0029 the FAN-OUT to N parts is dissolved by per-item invocation + the dispatcher
> (outside the definition) — this spine is the single per-notice review + dispatch, ZERO new
> step kinds."*

The fan-out ruling was not merely cited, it was **applied and then acted on again**: M3.2
REMOVED a `direct_call dispatch_dispositions` step, with the reasoning recorded at the site —
the step was M3.1-era authorship that predated the ruling that batch and fan-out are
executor-owned semantics, i.e. *"the declaration is the STALE RECORD."*

## The gap enumeration, already classified

| gap | the artifact's classification |
|---|---|
| fan-out to N parts | **dissolves into substrate** — per-item invocation + dispatcher, outside the definition |
| extraction / matching / relevance-scoring | **NOT a missing step kind.** They are `spo_operation` steps blocked on Part/Notice/BOM ontology classes + registered verbs that don't exist (ADR-0029 Slice-2 prereq), so the stage-2 verifier has no real (subject, verb) URIs to check |
| per-invocation compartment | **needs model growth, not a step kind** — static `WorkflowDefinition.classification` cannot express a per-trigger compartment; `classification: null` with the audience carrying it, named as an M3 open item |

**No row lands in "needs a new step kind."** The definition-may-not-branch line is not under
pressure from PCN, so the ADR-0039 litigation the assignment reserved for you is not triggered.

## What IS genuinely open (the real M3 remainder)

1. **Executor cutover** — the definition is not wired to `_run_definition`; the stage-2
   verifier + runner cutover is a separate sealed increment.
2. **Slice-2 ontology prereq** — Part/Notice/BOM classes + registered verbs, which gate the
   `spo_operation` steps.
3. **M3.3** — retire `taskKindRegistry`; bare `pcn_disposition` deliberately survives as a
   cortex-ui render contract until then. The seal distinguishes it from the renamed
   `pcn_disposition:` audience key **by the colon**, which is load-bearing.

## Why this was worth a stop rather than a redo

Producing the commissioned gap read would have re-derived a classification that already exists,
and filed it as new — the two-homes defect, with the newer copy being the less authoritative
one. The assignment's premise was a **stale mental model, not a stale repo**: M3.1 and M3.2 have
landed since it was formed.

**Recommendation:** re-scope the night's second job to the three open items above, of which only
(1) is a definition-layer question at all.
