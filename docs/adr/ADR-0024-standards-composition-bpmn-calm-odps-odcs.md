---
status: Partially Proposed (Publish/promotion — 2026-06-27); Reserved (Standards composition)
date: 2026-06-26
amended: 2026-06-27
deciders: Platform team
---

# ADR-0024 — Standards composition + publish / promotion

## Status

This ADR covers **two related decisions** governed by the same
underlying discipline (single-authoritative-standard-per-concept).
The two parts have different statuses because their triggers fired
at different times.

- **Part A — Standards composition (BPMN / CALM / ODPS / ODCS).**
  **Reserved** (2026-06-26). The scope is named so ADR-0023's
  reserved edge vocabulary (`PRODUCED_BY_PROCESS`, `CONFORMS_TO`,
  `IS`, `WITHIN`) can reference it durably, but substantive
  reasoning lands when the first standard pulls in for integration.
  Standards are a directional decision and the reasoning gets
  sharper with one real integration in hand.

- **Part B — Publish / promotion.** **Proposed** (2026-06-27).
  Promotion of grounded answer-artifacts to target tools (dbt-in-
  git, Superset, Grist, Dagster) is an active operational concern
  that doesn't wait on any of the four standards landing first. It
  is filled in now because it is an *instance* of one of the
  disciplines this ADR already reserves — single-authoritative-
  standard-per-concept — applied at action time: after publish,
  the target tool is canonical for the published asset.
  **AMENDED 2026-09-02** — the sequencing STOP is scoped to TOOL
  targets; `target_system` gains `recipient`; the graph-node
  discipline is unchanged. See the amendment above the STOP-point
  section, and ADR-0047.

## Related

- [ADR-0023 — iagent AnswerArtifact as a graph-native CQRS object](ADR-0023-iagent-answer-artifact-graph-cqrs.md):
  the answer-artifact node shape, validity (`valid_as_of`), typed
  edges (`PRODUCED_BY`, `DERIVED_FROM`, `CITES`). Part B extends
  this with a new `PublishedArtifact` node and the `PROMOTED_TO`
  / `SUPERSEDES` edges; it does not restate ADR-0023's discipline,
  it builds on it. ADR-0023 also names the **Neo4j → Postgres
  → Electric projector** seam that Part B's publish substrate
  depends on (see "Sequencing" below).
- [ADR-0017 — Presentation-as-Predicate](ADR-0017-presentation-as-predicate.md):
  the artifact-references-never-reimplements discipline both Parts
  inherit. The presentation predicate is registered, not re-derived
  per consumer; the same shape applies to standards facts (Part A)
  and to published references (Part B — the published-artifact
  node references the target locator, never re-implements the
  target's content).
- [ADR-0022 — DataHub integration: owned wrapper, mining the MCP
  server as reference](ADR-0022-datahub-integration-owned-wrapper-mining-mcp-reference.md):
  the integration-discipline template both Parts reuse. For Part A:
  mine the upstream standard as deterministic reference, never
  adopt third-party clients wholesale. For Part B: the DataHub
  scrub job that detects dangling published-artifact references
  reuses the owned-wrapper pattern.

---

## Part A — Standards composition (Reserved)

This part remains **Reserved** as of 2026-06-27. The substance below
is the scope of what will be ruled when a standard's integration
trigger fires; the rules themselves are not yet decided.

### Scope (what this part will rule on, when it lands)

The four standards in scope:

- **BPMN** (Business Process Model and Notation) — the executable
  process model the artifact's `PRODUCED_BY_PROCESS` edge points
  at. Answers "which workflow produced this answer."
- **CALM** (Common Architecture Language Model) — the architecture
  / component model the artifact's `WITHIN` edge places it in.
  Answers "which system component owns this answer."
- **ODPS** (Open Data Product Standard) — the data-product
  specification the artifact's `IS` edge identifies it as. Answers
  "what data product does this artifact materialize."
- **ODCS** (Open Data Contract Standard) — the data-contract the
  artifact's `CONFORMS_TO` edge attests to. Answers "what contract
  does this artifact's payload claim to honor."

For each, the ADR will rule:

1. **Which standard is authoritative for which concept** — the
   non-overlap discipline. If ODPS and ODCS both have something
   to say about "what shape this output is," exactly one of them
   is authoritative for that fact and the artifact references
   that one.
2. **How the seams compose** — the cross-standard relationships.
   ODPS data products are produced by BPMN processes within CALM
   components conforming to ODCS contracts. The composition has to
   be coherent across all four; the ADR will rule on the seam
   shape (e.g., which standard's identifier is canonical at each
   seam, who references whom).
3. **The artifact-references-never-reimplements discipline** —
   the artifact's edges point at standards-shaped nodes; the
   artifact does NOT re-implement what the standards already say.
   If BPMN says "this process has these activities," the artifact
   doesn't copy that into its own properties; it points at the
   BpmnProcess node and lets the standard's substrate carry the
   detail.
4. **Per-standard integration order and triggers** — which
   standard lands first, what real consumer need pulls it in,
   what gets integrated minimally vs fully. Standards arrive
   per-demand, not on a schedule.

### Why Part A is reserved rather than written now

- **The reasoning gets sharper with one real integration in hand.**
  Composition rules in the abstract tend to over-fit a hypothesis
  about how the standards will be used; one real PR landing the
  first standard exposes which seams are load-bearing and which
  are decorative.
- **ADR-0023 doesn't block on this.** The artifact-as-graph-CQRS-
  node decision is rule-able and buildable now. Reserving the
  edge vocabulary in ADR-0023 keeps the schema honest when each
  standard lands without forcing the standards composition today.
- **Per-standard ADRs may follow from this.** It's plausible that
  Part A ends up split into one ADR per standard-seam (ADR-0024a
  BPMN-seam, ADR-0024b CALM-seam, etc.) once the integration
  shape is real. The number is claimed to keep the discussion
  durable; the granularity gets settled when the work starts.

### Triggers (when Part A converts from Reserved to Proposed)

Part A moves to Proposed when any of the following happen, because
at that point the abstract reasoning has to become concrete:

- A consumer (UI, downstream agent, governance report) asks "which
  BPMN process produced this answer" and the substrate needs to
  resolve it.
- An ODPS data product is registered and an artifact materializes
  it — the `IS` edge needs a real target.
- An ODCS contract is registered and an artifact claims conformance
  — the `CONFORMS_TO` edge needs a real target.
- A CALM component model is loaded and the artifact needs to
  identify which component owns it — the `WITHIN` edge needs a
  real target.

The first of these to land triggers the conversion. The PR that
triggers it owns drafting the substantive content of Part A for
the standard it pulls in; the remaining standards' content lands
when their own triggers fire.

---

## Part B — Publish / promotion (Proposed 2026-06-27)

This part of ADR-0024 is **Proposed** as of 2026-06-27.

**Why now, ahead of Part A**: publish/promotion has a triggering
need that doesn't require any of the four standards to land first.
Artifacts get promoted to target tools as part of ongoing system
operation; the discipline for how that promotion relates to
iagent's graph needs to be written before the first publish
backend lands so the substrate isn't built ad-hoc.

Publish/promotion is also a clean instance of the single-
authoritative-standard-per-concept rule Part A reserves: after
publish, the target tool (dbt-in-git, Superset, Grist, Dagster,
…) is the canonical source for the published asset. iagent holds
a thin reference and the frozen lineage; it does not hold a
copy. Writing this case now sharpens the discipline that Part A
will later apply to the standards.

### The decision

**Publish is a one-way emit, not a sync.** After publish:

- The target tool is the single source of truth for the
  published asset's content and post-publish freshness.
- iagent holds only:
  - The **frozen `AnswerArtifact`** — the historical record of
    the grounded answer that was promoted, with its `valid_as_of`
    captured at promotion time.
  - A **`PublishedArtifact` node** — a thin reference to the
    target's locator, never the asset's content.
- iagent does not pull the asset back. It reads the target
  through the existing wrapper layer (ADR-0022 pattern) when it
  needs current state for display.

### Node shapes

**`AnswerArtifact`** — unchanged from ADR-0023. At publish time it
becomes the **frozen historical record** of the grounded answer
that was promoted, preserving its `valid_as_of` at that moment.
It does not chase the live published asset.

**`PublishedArtifact`** — new. A deliberately thin reference node.
The absence of content is **load-bearing**, not an omission — see
Rule 1 below.

```text
PublishedArtifact {
  id              -- stable identifier
  target_system   -- enum: dbt | superset | grist | dagster | …
  locator         -- system-specific pointer (NOT content):
                  --   dbt:      { repo, path, commit_sha }
                  --   superset: { chart_id }
                  --   grist:    { doc_id, table_id? }
                  --   dagster:  { asset_key }
  published_at    -- when the promotion happened
  status          -- live | orphaned (default: live)
  orphaned_as_of  -- nullable; set when a DataHub scrub finds
                  -- the target gone

  -- NO authoritative content. The absence is load-bearing.
  -- Same shape as Phase 1 marking `status:pending` on
  -- AnswerArtifact as UI-not-persisted: a schema-level comment
  -- on this node MUST call out that it never holds the
  -- asset's content. Restoring content would violate Rule 1.
}
```

### Typed edges

**`PROMOTED_TO`** : `PublishedArtifact → AnswerArtifact`

Lineage back to the grounded answer the publish came from. The
published-artifact knows which frozen historical answer it
derives from; this edge is **capture-or-lose-forever** at
promotion time. Without it, the answer-to-publish derivation
can't be reconstructed.

**`SUPERSEDES`** : `PublishedArtifact → PublishedArtifact`

**Decided 2026-06-27: yes, build the chain.**

Each re-publish creates a new `PublishedArtifact` node AND a
`SUPERSEDES` edge to the prior one for that target locator. git
holds the real version history of the asset; the graph holds the
queryable promotion chain.

Without this edge captured at publish time, supersession can't
be reconstructed later — the graph would show N independent
publications with no temporal ordering, and "which answer-
artifact was the latest source for this dbt model" becomes
unanswerable. Building the chain at promotion time is cheap;
reconstructing it post-hoc isn't.

### The four rules — binding constraints

These are written as constraints, not aspirations. Any PR that
appears to violate one must update this ADR first.

**Rule 1 — Reference only, no copies.**

The `PublishedArtifact` node never stores the asset's content.
iagent reads the target (dbt repo, Superset API, Grist sheet,
Dagster asset) through the wrapper layer to show current state;
it does not hold the content. The whole reason the node is thin
is so iagent CAN'T present stale content as live — the absence
of a copy is what makes Rule 4 honest.

**Rule 2 — Publish is backend, on an artifact id.**

The UI triggers publish on an `AnswerArtifact.id`. The UI never
composes the published payload from its local card state. The
thing emitted to the target system is built **backend-side** from
the captured `AnswerArtifact`, so there is no UI synthesis
surface with external blast radius.

This is the read-side `genArtifact` anti-pattern moved to write-
side, where it would be worse: a UI that composed the publish
payload would let local UI state escape into a downstream
pipeline. Forbid explicitly: **publish is backend, on an id,
period.**

**Rule 3 — Validity gates publish, not post-publish life.**

Publish is gated on the `AnswerArtifact`'s `valid_as_of` per
ADR-0023. A stale answer cannot be promoted into a pipeline.
The exact freshness window is a per-target-system policy not
ruled here; the discipline is that **the gate exists at the
boundary**.

After publish, freshness of the *asset* is the target tool's
concern — git commits for dbt, Superset versions, Grist
revisions, Dagster materialization timestamps. iagent owns only
the truth of the derivation (the frozen `AnswerArtifact` at
publish time) and does not track post-publish freshness of the
target.

**Rule 4 — Dangling renders honestly; scrubs mark status, never restore content.**

A DataHub scrub job (reusing ADR-0022's owned-wrapper pattern)
detects a missing target and sets `status = orphaned` +
`orphaned_as_of` on the `PublishedArtifact` node. The UI renders
this as:

> Published to `<target_system>` at `<locator>`,
> target not found as of `<orphaned_as_of>`.

It **MUST NOT** backfill content from the frozen `AnswerArtifact`.
The honest dangling render is "the live thing is gone." Falling
back to the frozen answer would:

1. **Recreate the copy Rule 1 forbids** — the moment iagent
   displays the frozen answer as "the published asset," it has
   stored the asset's content through the back door.
2. **Present a deleted asset as live** — a `git rm`'d dbt
   model would silently reappear in iagent looking
   authoritative, which is the exact reanimation problem
   "publish is a one-way emit" is meant to prevent.

This is the same honest-empty rule the read side enforces (the
"no components produced" / "this attempt failed" empty states
from ADR-0023 Phase 2 lifecycle hardening) applied at the
lineage layer: **status backfill yes; content backfill never.**

### Non-goals — state explicitly so they don't get built by accident

These are NOT part of this decision. A PR attempting any of
them is blocked by ADR change, not by code-review accident:

- **No two-way sync.** iagent does not pull the published
  asset's content back into the graph or the answer-artifact.
  The arrow is one-way; making it two-way collapses the
  canonical-after-publish discipline.

- **No content backfill on orphan.** See Rule 4. Status
  backfill yes; content backfill never. Repeated explicitly
  here because it is the single most likely thing to get built
  by accident: a "let's just show the frozen answer when the
  target is gone" PR is exactly the violation. If that
  pressure surfaces, the answer is to render the honest-
  empty + locator + orphaned_as_of, NOT to repopulate.

- **Guided-creation / iframe-walkthrough flow is out of scope
  for this ADR.** The human-in-the-loop authoring layer (the
  flow where a user iteratively shapes a chart in Superset's
  embedded UI with iagent providing context) sits on top of
  this substrate and gets its own ADR. This ADR is the node /
  edge / publish-action substrate that flow will stand on,
  not the flow itself.

### Sequencing — publish backend depends on the projector

**Lead-with-dependency note.** The `PublishedArtifact` node is a
graph node projected to the read-side store the same way
`AnswerArtifact` is per ADR-0023. **There is no real publish
substrate until the Neo4j → Postgres → Electric projector
exists.**

Therefore:

- **This ADR ships now.** Documenting the rules, the schema, the
  non-goals does not require the projector. The documentation
  is buildable-against — a future PR opening the publish backend
  can read this section and know exactly what nodes/edges to
  create and what rules to enforce.

- **The publish backend does NOT start until the projector
  lands.** The projector is the bottleneck. A publish backend
  built before it would either:
  1. Build a parallel non-graph storage path for
     `PublishedArtifact` (which violates ADR-0023's graph-native
     discipline), or
  2. Land code that can't actually project published-artifacts
     to the canvas (which violates the read-side contract).
  Both are worse than waiting.

- **The Phase 1 "Monday handoff" and `[[dag-tools-grpc-import-
  timeout]]` arc reference the same projector seam.** The
  publish work and the Phase 1 backend wiring are gated on the
  same build. This is the dependency that orders all three
  threads (projector → publish backend → publish targets fan-out).

### Click-to-recall is independent

The artifact-receipt click-to-recall affordance (each receipt
already knows its `Message.artifactId` per ADR-0023 Phase 1;
wiring a click handler to `setCurrentArtifact(id)` is one line)
is **independent of both** the projector and the publish
substrate. It's a small UI affordance on the existing transcript
/ canvas pair and a fine place to put energy in parallel if a
small thread is wanted while the projector work runs.

### AMENDMENT 2026-09-02 — the STOP binds TOOL targets only; recipient targets are added to the enum

**Ruled by this ADR's owner, in answer to the collision recorded at
[ADR-0047](ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) §7.** Recorded
here rather than only downstream, because a STOP whose resolution lives in another document is a
STOP the next reader will re-litigate.

**The question.** ADR-0047 emits a package to a **recipient** — a person outside the organisation —
and models it as a `PublishedArtifact`. Does the sequencing ruling below (*the publish backend does
not start until the projector lands*) bind that target too?

**The ruling: no. The STOP binds TOOL targets only.** The reasoning is this section's own stated
harms, applied to a target it did not anticipate:

| Part B's stated harm | does it apply to a recipient target? |
|---|---|
| **(a)** a parallel non-graph storage path for `PublishedArtifact`, violating ADR-0023's graph-native discipline | **YES — still binds.** Nothing about the target changes where the node lives |
| **(b)** publish code that cannot project published artifacts to the canvas | **NO.** A recipient package has no canvas projection requirement and **no wrapper-layer read-back at all** — the artifact leaves the building and, by ADR-0047 §4's one-way rule, nothing reads it back by design |

**So the consequences are split, and the split is the useful part:**

- **The packaging path may proceed now** — the verb, the entitlement filter at packaging time, the
  verification manifest, and the seals. None of it touches the projector.
- **The graph-node half still waits**, and waits on harm (a) specifically: **`PublishedArtifact` for
  a recipient target must not be built as a side-store.** It lands graph-native, or it lands after
  the projector ruling. **The graph-node discipline is unchanged by this amendment** — this is a
  scoping of the STOP, not a relaxation of Rule 1 or of ADR-0023.

**`target_system` gains `recipient`** alongside `dbt | superset | grist | dagster`. The enum is
extended, not bypassed, and the locator for that value is a **content hash** per ADR-0034's
`ruleset_ref` discipline rather than a system-specific pointer — because for this target there is no
system to point into. See ADR-0047 §6.

**One asymmetry worth naming for whoever builds it:** for a tool target, Rule 1's thin reference
works because *the target holds the content*. For a recipient target the recipient holds it, so the
same rule is satisfied by the same mechanism with the parties reversed. **Rule 1's purpose — iagent
must never be able to present stale content as live — is preserved exactly**, and the absence of a
copy remains load-bearing.

---

### STOP point for this ADR work

**This ADR commit is the STOP for the current thread.** **Scoped by the 2026-09-02 amendment
above:** this STOP governs the tool-target publish backend. A recipient-target packaging path is not
gated by it; its graph-node half still is.

**Original text follows, unchanged:**

The scaffold sub-bullets that would follow this ADR (publish
backend action, DataHub scrub job for orphan detection,
integration probe per target contract, single-target adapter
starting with Superset since its publish button is already wired
in the UI) are the **next thread's plan, not this thread's
work**. They are gated on the projector landing per the
sequencing note above.

If you finish reading this ADR (or finish writing this section)
and feel the pull to "just sketch the publish action while I'm
in here," **stop.** That work is a separate thread. A bounded
recipe with a named STOP point is what prevents the dependency-
skipping move that would land a publish action before its
projector — which would either build the wrong substrate or
build code that can't run honestly.

The order, recorded here so it survives session boundaries:

1. **ADR (Part B) committed.** ← this thread ends here.
2. **Neo4j → Postgres → Electric projector** lands (per ADR-0023
   open questions). This unblocks both publish AND completes the
   Phase 1 Monday handoff.
3. **Single-target publish backend** (Superset) — backend action
   + scrub job + integration probe. End-to-end round-trip per
   `[[feedback-endpoint-probe-per-engine]]` discipline before
   any target fan-out.
4. **`SUPERSEDES` chain wired** once the single-target path is
   proven.
5. **Additional targets** (dbt, Grist, Dagster) — only after
   step 3 round-trips honestly.

---

## What this ADR does NOT cover

- The artifact-as-graph-CQRS-node schema itself — that's
  [ADR-0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md).
  Part B extends ADR-0023; it does not restate it.
- The openddil overlap — shared UI components and service reuse
  with openddil — that's an openddil-side integration concern.
- The Neo4j → Postgres projector seam — that's a component
  scoped in ADR-0023's "Open questions for the implementing PR."
  Part B depends on it but does not specify it.
- The guided-creation / iframe-walkthrough authoring flow — see
  Part B non-goals; that gets its own ADR on top of this
  substrate.

## When you arrive here from a real integration PR

Two paths, depending on which work you're opening:

**Path 1 — You're integrating one of the four standards (Part A).**

1. Confirm the trigger above matches what you're doing.
2. Update Part A's status from **Reserved** to **Proposed** and
   write the substantive content for the standard you're
   pulling in (and at least sketch how it composes with the
   other three, even if the others are still deferred).
3. Land the corresponding standards-node type in Neo4j (e.g.,
   `:BpmnProcess` with its properties).
4. Wire the reserved edge type from ADR-0023 to the new node
   type.
5. Decide whether the remaining standards still wait or whether
   this PR triggers writing their content too.

**Path 2 — You're scaffolding the publish backend (Part B).**

1. **Verify the Neo4j → Postgres → Electric projector exists.**
   If it doesn't, STOP and land that first. The publish backend
   is gated on it per the sequencing section above.
2. Land the `PublishedArtifact` node type in Neo4j, with the
   schema-level comment calling out that the node never holds
   the asset's content (Rule 1 is load-bearing at the schema
   layer, not just at runtime).
3. Wire `PROMOTED_TO` and `SUPERSEDES` edge types.
4. Build the backend publish action: takes `AnswerArtifact.id`
   + `target_system`, validity-gates per Rule 3, builds the
   target spec backend-side per Rule 2, emits one-way, creates
   the `PublishedArtifact` node + `PROMOTED_TO` edge (+
   `SUPERSEDES` if a prior publish of this lineage exists for
   the same locator).
5. Wire the DataHub scrub job for orphan detection per Rule 4,
   reusing ADR-0022's owned-wrapper.
6. **Integration probe per target contract** — one real round-
   trip per target system you're enabling first (start with
   Superset). Confirm the emitted spec is accepted and the
   locator round-trips back. Per
   `[[feedback-endpoint-probe-per-engine]]`: don't fan out to
   four targets before one round-trips honestly.
