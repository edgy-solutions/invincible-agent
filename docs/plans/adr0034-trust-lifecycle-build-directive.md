# Build directive — ADR-0034 (trust lifecycle) + pre-M3

**Read this fully before starting. The sequencing and the refusals are part of the spec.**
Governing decisions live in
[ADR-0034](../adr/ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md); this file
is the *work order*, not the decision record. Where they disagree, the ADR wins — and the disagreement is
itself a finding worth surfacing.

## Phase 0 — the ADR (DONE)

ADR-0034 is written and committed. **It is capture, not design** — the decisions were made in review, and
this directive exists so M3 work inherits them as constraints rather than re-litigating them. If a Phase 1
task seems to require *changing* an ADR-0034 decision, that is a finding: surface it, do not quietly
redesign.

The one paragraph added to the M3 design doc (admission-vs-structure boundary + workflow-2-as-acceptance-
customer) is also landed.

## Phase 1 — build now (M3-INDEPENDENT)

**Hard boundary: do NOT touch the workflow model, the executor, or any sealed mechanism.** Everything below
is additive around the existing start path.

### 1.1 Decision record emission
Schema + persistence, emitted from the sensor/starter path, threading values the pipeline **already
computes** (check verdicts, content hashes, `needs_review`, `crops_failed`, `ruleset_ref`, proposed
dispositions). This is a [[resolution-discard-pattern]] cure: nothing new is derived, values already
computed stop being discarded.

- **Persistence:** graph triples preferred — promotion queries are *instances-by-property* shaped and the
  corpus wants joining to notices and corrections. **If you choose otherwise, justify it in the commit**;
  do not let convenience pick the substrate silently.
- **Identity:** the record keys on the SAME artifact identity already threaded through the sensor's
  `run_key`, the triage `task_id`, and the ingress idempotency key (`ETag` + `source_key`). This is its
  fourth consumer — if you find yourself deriving a new identity here, stop: that drift is how the same
  artifact becomes "the same work" to one mechanism and "new work" to another.

**Seals (each proven-to-bite, harness-proves-it-can-fail FIRST):**
- Emission is **schema-gated**: validate at emit, fail LOUD on violation. A record that fails validation
  must not be silently dropped — it is evidence, and evidence that vanishes on malformation is worse than
  none.
- A record exists for **every processed notice** — including refusals, `NO_RESIDUE`, and auto-proceeds.
  The gap in that set is exactly the audit gap this closes.
- Records are **immutable** (corrections join, they do not overwrite).
- **Inputs-and-thresholds, not bare verdicts** — assert a record contains what was compared against what.
  See the refusal below; this is the one most likely to be quietly weakened.

### 1.2 Trust table
A ratifiable artifact through the **existing rules/validation machinery** — same family as the disposition
ruleset: git-asserted, content-hashed (`ruleset_ref`-style), validated at load, fails loud.

- Keyed on **vendor-format × pipeline-version** (never vendor alone — ADR-0034 §2).
- **Unknown vendor-format ⇒ `supervised` BY CONSTRUCTION.** Computed from absence, not written per vendor:
  a table that must *list* a vendor in order to supervise it fails open on the vendor nobody added.

### 1.3 Starter consultation
The start path consults the table **before honoring "no review needed"**:

- `supervised` → forces the existing review workflow **regardless of content**.
- `monitored` / `trusted` → **defers to the content chain** (today's behavior). Trust buys the absence of a
  human, never the absence of a check.
- Thread `admitted_by` into the batch/task context.

**Workflow 2 does not exist yet. In this phase `trusted` + clean behaves EXACTLY as today. Do not build
auto-dispatch.**

### 1.4 Seals for the layer split
- `supervised` admits a clean notice → review starts, `admitted_by: policy`.
- `trusted` defers to the content chain (a content refusal still refuses).
- Unknown format → `supervised`.
- A decision record is present on **all** paths.
- The two ADR-0034 §8 acceptance sentences as tests where expressible; the mechanism half is a **grep-able
  deletion test** (no vendor name / trust state / threshold in code).

## Phase 2 — M3-COUPLED (do NOT build now; these are M3 work items)

- **Workflow 2 as a definition** — this IS M3.2's "second definition on the same executor" acceptance.
- **The escalation mechanism decision** — conditional step vs. terminate-and-start-workflow-1 (ADR-0034 §7).
- **`purpose: audit` step attribute.**
- **Promotion-proposal-as-grouped-review** (the recursion: promotion is itself an approval).
- **Capability-grant coupling mechanics** (ADR-0034 §6).
- **The ingress goes ASYNC, and refusal routing relocates into the Restate handler.** Filed here because
  several places already point at "ADR-0034 Phase 2" as this work's trigger
  (`docs/plans/refusal-routing-design.md` §NAMED WAKE and `_ingress_idempotency_key`'s docstring), and a
  wake that names a destination the destination does not acknowledge is how a deferral becomes a
  disappearance. Today the BFF calls `start_review` **synchronously** and the sensor classifies the
  response — which is what makes today's refusal routing possible at all. The autonomous path cannot work
  that way: there is no human latency to wait on, the sensor fire-and-forgets into a definition, and there
  is **no synchronous response left to classify**. So workflow 2 forces three coupled changes that must
  land together: (1) the BFF `send`s and returns 202; (2) refusal routing moves INTO the handler — the
  decider that knows the refusal routes it, which is also where the trust gate lives; (3)
  `tests/test_refusal_routing.py` is rewritten against the two-definition shape. The ingress idempotency
  key (landed `e513242`) is what makes deferring this safe: the synchronous hold is a bounded wait on a
  **deduplicated** invocation — ugly, but honest.

## Refusals — slip-is-signal applies

**Stop and surface** rather than proceeding if:

- a Phase 1 item appears to require touching a **workflow definition**, the **executor**, or **sealed HITL
  mechanics** — that is the layer leak the acceptance sentences forbid;
- you find yourself **encoding a vendor, a trust state, or a threshold in code** — same leak, other
  direction;
- the decision-record schema tempts you toward **re-derivable conclusions without their inputs** (storing
  `check_x: pass` instead of what was compared against what) — that is the smooth-green: it validates, it
  looks complete, and it silently makes every future promotion decision rest on the pipeline's self-report.

## Deliverables

1. ADR-0034 committed. ✅
2. One paragraph in the M3 design doc. ✅
3. Phase 1 on a branch, sealed, **with the evidence corpus accumulating from the first merged notice.**

## Why this order

Phase 0 gives the agent the decided boundaries so M3 inherits them as constraints. Phase 1 **starts the
evidence clock immediately** — the corpus is worthless the day it is created and valuable in proportion to
how long it has been running, so it is the one part with a real cost to deferring. Phase 2's explicit
do-not-build list is what keeps an eager unsupervised session from hand-coding the exact semantics M3 exists
to declare.

M3's hardest question was always *where its edges are*. This draws the two that matter: **admission lives
outside**, and **the second definition is the proof**.
