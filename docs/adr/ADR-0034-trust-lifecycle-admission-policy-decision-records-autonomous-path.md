# ADR-0034 — The trust lifecycle: admission policy, decision records, and the autonomous path

**Status:** Proposed. Phase 1 (decision records + trust table + starter consultation) is M3-independent and
buildable now; the autonomous workflow definition is M3-coupled and explicitly deferred.
**Date:** 2026-07-30
**Deciders:** Platform team
**Related:**
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) — the process-workflow model. This ADR
    **consumes** it: the trust gate selects *between declared definitions*; it does not add a step kind, a
    mode flag, or a branch inside one.
  - [ADR-0030](ADR-0030-verb-output-is-a-fixed-type.md) — fixed output type per verb. Decision records are
    **emitted artifacts of a fixed shape**, schema-validated at emission — not authored config.
  - [ADR-0027](ADR-0027-composable-approval-policy.md) — grant-issuance governance over the single decider.
    Promotion up the trust ladder is **an approval**, and (see §6) it is the *same authority event* as the
    autonomous identity's dispatch capability grant.
  - [ADR-0026](ADR-0026-persona-entitlement-topaz-authorization.md) — the single decider. `can_invoke` on the
    capability namespace is the enforcement point for "this pipeline may act unsupervised."
  - [M3 design](../reference/m3-grouped-review-definition-design.md) — this ADR **sharpens M3's boundary**
    (admission lives outside the definition) and **supplies M3.2's acceptance customer** (the autonomous
    workflow is the "second definition on the same executor," no longer a synthetic test case).

## Context

Today a PCN/PDN notice reaches a human's work queue **only when the logic decides a review is needed.**
Everything else is disposed without a human ever seeing it. The requirement from the field inverts that
default: **every notice should enter a work queue until the pipeline can be trusted** — and the trust is
expected to be earned per *vendor format*, measured by manual review, then relaxed.

Two things are true at once, and the design has to hold both:

1. **The "always review" instinct is answering a real deficiency.** Not the absence of review — the absence
   of an **auditable record of the decision not to review**. Today a skipped notice leaves no artifact
   explaining *why* it was skipped, so the only way to inspect the decision is to re-run it. "Review
   everything" is a blunt instrument aimed at a legitimate target.
2. **"Review everything, forever" is not a resting state.** A queue that always contains every notice trains
   reviewers to rubber-stamp, and rubber-stamped approvals are worse evidence than no approvals: they look
   like ratification and carry no signal. The volume that makes the policy safe is the same volume that
   makes its output untrustworthy.

The resolution is that these are **two different questions that today are one**:

> **Does this notice enter the human review path, or does it auto-proceed?** — an **admission** question,
> about how much the pipeline is trusted for this kind of input.
>
> **What is the process once it does?** — a **structure** question, about steps and their order.

Conflating them is what produces both bad answers. Separated, leadership's entire ask — *supervise, measure,
automate, revoke* — becomes a sequence in which **every noun is data**.

### How far is this from what exists?

Closer than it looks, because the expensive parts are built:

- **The human path exists and is sealed** — grouped review, `register_task` before suspend, `can_act`,
  bulk-resolve, per-item `DispatchItem` convergence.
- **The decision inputs already exist and are already computed** — `needs_review` per part, doc-level flag,
  extraction warnings (`crops_failed`), `ruleset_ref` content hash, category classification, proposed
  disposition per part. Today they are **used and discarded**; the decision record threads values the
  pipeline already has. This is a [[resolution-discard-pattern]] instance, and the cure is the usual one.
- **Policy-as-ratifiable-data exists** — the disposition ruleset is git-asserted, content-hashed, validated
  at load, and fails loud. The trust table is the same machinery with a different payload.
- **Durable, journaled, convergence-sealed execution exists** — and the autonomous path needs *all* of it.

What genuinely does not exist: **the decision record**, **the trust table**, and **the second workflow
definition**. Two of those three are M3-independent.

### Is the leadership model reasonable?

Mostly yes, with one correction that must be recorded because it changes the key:

**"Once a vendor's format is set" is a weak invariant.** The three notices that broke this pipeline in one
week — Qorvo, Diodes, onsemi — broke on *format variation within a vendor*, and the extraction improved
underneath them (vision → text-layer) mid-arc. A vendor is not a stable unit of format. Worse, trust keyed
on vendor alone would survive a **pipeline upgrade**, which is exactly when accumulated evidence stops
applying: the thing that earned trust is no longer the thing running.

So the model is right in shape and wrong in key. Trust is keyed on **vendor-format × pipeline-version**
(§2), and a pipeline upgrade re-evaluates rather than inherits.

## Decision

### 1. Three layers, three owners, no layer encodes another's decision

| layer | artifact | decides |
|---|---|---|
| **Trust table** | ratifiable data (rules machinery) | *May the pipeline act without a human for this input class?* |
| **Starter routing** | code in the start path | *Does a review start?* — posture **∧** content |
| **Workflow definition** | `policy/workflows/*.yaml` | *What is the process?* |

The starter is the only place the two signals meet, and it meets them as a **conjunction**: a `supervised`
posture forces the review path *regardless of content*; a `trusted` posture **defers to the content chain**
— it does not override a content refusal into silence. Trust buys the absence of a human, never the absence
of a check.

**No definition consults the trust table, and no trust rung names a step.** That is the layer-leak the
acceptance sentences in §8 make falsifiable.

### 2. Trust keys on `vendor-format × pipeline-version`, never vendor alone

Evidence accrues to *the pair*. A pipeline upgrade resets or re-evaluates the rung, because the accumulated
evidence was produced by a different extractor. The transition is exactly the re-extraction diff shape
already in the system: new content at the same location is **supersede, not duplicate**.

Record the Qorvo / Diodes / onsemi incidents in the ADR body as the standing evidence that *format-is-set*
is not a durable claim. **Format fingerprinting is an open question (§9)** — the naive fingerprint (vendor
+ layout hash) is a starting point, not the answer, and a fingerprint that is too coarse silently grants
trust across a format boundary.

### 3. Three rungs, and one forbidden transition

- **`supervised`** — every notice enters the human queue. Full decision records. The born-default.
- **`monitored`** — auto-proceeds, **sampled** into the human queue, full decision records on every notice.
- **`trusted`** — auto-proceeds; records still emitted; sampling optional.

**`supervised → trusted` is not a permitted transition.** `monitored` is not a formality on the way to
automation — it is where most formats should live *longest*, because it is the only rung that produces
**counterfactual evidence**: what the pipeline would have done, checked against what a human did, on
traffic the pipeline is already handling. Skipping it means promoting on evidence gathered under a
different regime.

**Unknown vendor-format ⇒ `supervised`, by construction.** Deny-by-default for autonomy, and the default is
computed from absence rather than written down per vendor — a table that must *list* a vendor to supervise
it fails open on the vendor nobody added.

### 4. Decision records are emitted artifacts, not authored config

One per **processed notice** — including refusals, `NO_RESIDUE`, and auto-proceeds. Schema-validated **at
emission**, immutable, self-versioned. Contents:

- extraction **content hash** + `source_key` (the artifact identity already threaded through run_key,
  triage task_id and the ingress key — this is its fourth consumer);
- **pipeline version** and **vendor-format fingerprint**;
- **every check's verdict with its inputs and thresholds** — never a bare pass/fail;
- **governing policy state**: `ruleset_ref` content hash and the trust table's content hash;
- **admission outcome**: `admitted_by: policy | content | escalation`;
- **eventual human corrections**, joined later (the record is the join key).

> **The inputs-and-thresholds clause is the whole point.** A record of `check_x: pass` is re-derivable only
> by re-running the pipeline that produced it — which is the audit gap this ADR exists to close. A record
> that says *what was compared against what* answers "why was this not reviewed?" **from the artifact**,
> which is the coherence-seal principle: the served artifact must contain the claim. A promotion decision
> made on bare verdicts is a promotion made on the pipeline's self-report.
>
> **THE INCIDENT THAT MAKES THIS NON-NEGOTIABLE (2026-07-31, live).** Two work notices carried a
> cross-check reason, and both numbers were invented: *"summary implies ~89 parts but 2 were extracted"*
> was the count parser reading a **package type** (`SOT‑89`); *"summary implies ~2024 parts but 1 were
> extracted"* was a **year**. Stored as `{"verdict": "mismatch"}`, both would have entered the corpus as
> evidence that **the extraction was unreliable** — and a vendor could have been held back from promotion
> on the strength of a regex bug, permanently, since records are immutable. Stored with their inputs, a
> reader sees immediately that the 89 came from `"SOT‑89 package parts"` and dismisses it.
>
> This is the clause a future simplifier will try to lose ("we only need the verdict"). The answer is that
> **a check's verdict without its inputs is not evidence, it is an assertion** — and the corpus governs
> whether a pipeline may act unsupervised.

This directly answers the user-facing requirement: **the audit of a decision NOT to review is a stored
artifact, not a re-run.**

### 5. Two definitions, one step apart

- **Workflow 1** — the review path (today's grouped review).
- **Workflow 2** — the **autonomous disposition** path: *the same steps minus `human_await`.*

Workflow 2 is **autonomous but still a workflow** — durable, journaled, convergence-sealed, threading
`ruleset_ref` and decision-record provenance. An auto-proceed implemented as "the starter calls dispatch
directly" would be the un-journaled-composition mistake rebuilt **on the highest-stakes path in the
system** — the one acting without supervision, where the audit trail must be *strongest*, not absent.

That the two definitions differ by exactly one step is the strongest available evidence that **the step
model carved reality at the right joint.** The autonomous path is not a stripped sibling; it is the same
process with the human step absent.

### 6. The trust rung and the dispatch capability are ONE authority with TWO enforcement points

Promotion to `trusted` and the service identity's `can_invoke(mesh:dispatchDispositions)` grant are
**governed together** — same ratification event, or the grant conditioned on the table. Demotion revokes
both.

Split, they drift into two failure modes, both bad and both quiet: a vendor marked `trusted` whose
autonomous workflow **403s at dispatch** (visible, annoying), or a **demoted vendor whose grant still
stands** (invisible, and the pipeline keeps acting unsupervised on a format that lost trust). The
entitlement plane's statement of "this pipeline may act unsupervised" and the admission plane's statement
of the same fact must be **ratified once**.

### 7. Escalation is mandatory design, not an error path

A check that trips **during** workflow 2 — a late `needs_review`, a coherence failure, a degraded
extraction — **routes the notice into the human path** with `admitted_by: escalation`. It must never limp
forward autonomously, and never bare-fail.

**Autonomy is always one bad check away from supervision, and the road back must be paved, not improvised.**

The *mechanism* is deliberately **not decided here** — it is an M3-time decision between:

- **(a) a conditional human step inside workflow 2** — the first real customer for a condition in the step
  model (the expressiveness wake, arriving with its named trigger); or
- **(b) terminate-and-start-workflow-1** — simpler, no model change, and it reuses the supersede grammar.

Both options and the expressiveness implication are recorded; choosing between them under this ADR would be
deciding the workflow model's expressiveness as a side effect of a trust decision.

### 8. Acceptance sentences (falsifiable, both required)

> **Promoting a vendor changes zero workflow definitions, and changing a workflow definition changes zero
> trust state.** *(the layer-leak test — each direction independently)*

> **No vendor name, trust state, or threshold appears in mechanism. Every trust change is a data edit.**
> *(deletion-test grammar: delete the trust table and the pipeline runs fully supervised, not broken)*

## Consequences

- **A new governed surface** (admission policy) joins the ratifiable-data family — inheriting validation,
  content-hashing, fail-loud load, and git-blame audit from the disposition-rules pattern.
- **A new persisted artifact class** (decision records) becomes the system's **evidence corpus** — for
  promotion, for audit, and for "why was this not reviewed?" Its value compounds from the first emission,
  which is why Phase 1 is worth starting before M3.
- **The audit answer stops being a re-run.** That is the actual deliverable behind the "review everything"
  request, obtained without the queue volume that would poison the evidence.
- **M3.2's acceptance criterion acquires a funded customer** — the second definition is no longer synthetic.
- **A second execution path exists that no human observes**, which raises the bar on records, escalation,
  and the capability coupling. Every one of §4/§6/§7 exists to pay for §5.

## Non-goals

- **Deciding the escalation mechanism** (§7) — M3-time, both options recorded.
- **Deciding promotion thresholds numerically** — semantics in §9; numbers come from the evidence corpus,
  which does not exist yet. Setting them now would be authoring the answer before the measurement.
- **Building workflow 2** — M3-coupled; Phase 1 ships with `trusted` + clean behaving exactly as today.
- **Auto-dispatch of any kind in Phase 1.**
- **A vendor-onboarding UI** — the trust table is ratifiable data through existing rails.

## Open questions

1. **Promotion threshold semantics — corrections-weighted, not approval-count.** N approvals is the
   rubber-stamp metric: it measures that humans clicked, not that the pipeline was right. The signal is
   **how often a human CHANGED the proposed disposition**, and a promotion gate should read a low and
   *stable* correction rate over a *diverse* sample. Exact function deferred to the corpus.
2. **Sampling-rate governance for `monitored`** — who sets it, is it per-format, and does it decay with
   accumulated evidence? Sampling is the evidence engine of the middle rung, so its rate is policy, not a
   constant.

2b. **Does a reason have to be a GOOD reason? — arrived in live practice on day one.** The triage card
   requires a non-empty reason on Acknowledge, and the very first real acknowledgement (2026-07-31,
   sandbox, witnessed) recorded **`comment: 'sasa'`**. The non-empty *floor* is enforced and held; reason
   **quality** is now demonstrably the open governance question, with `'sasa'` as its founding exhibit.
   This matters here and not only in the UI: the corpus reads human corrections as promotion evidence, and
   *"parts entered in the legacy system"* versus *"notice withdrawn by the vendor"* versus `'sasa'` are
   three very different facts about a pipeline — the third being no fact at all. No gate can enforce
   meaningfulness, so the candidates are a structured reason (select-from-authorized-set, this codebase's
   standing preference over free text), a minimum-signal heuristic (which would have to fail to NONE), or
   accepting that low-signal reasons are themselves a measurable quality signal about the review process.
   **Do not silently treat all non-empty reasons as equal evidence when computing a correction rate.**
3. **Format-fingerprint sharpening** (§2) — a fingerprint too coarse silently grants trust across a format
   boundary; too fine and no format ever accumulates enough evidence to promote. Needs real corpus data.
4. **Do decision records live in the graph or a table?** Graph is the lean — promotion queries are
   *instances-by-property* shaped and the corpus wants joining to notices and corrections — but this must
   be justified at build time, not assumed.
5. **Retention.** Records are the audit trail for automated decisions; their retention is a compliance
   question this ADR raises and does not answer.
