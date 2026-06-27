---
status: Reserved
date: 2026-06-26
deciders: Platform team
---

# ADR-0024 — Standards composition (BPMN / CALM / ODPS / ODCS)

## Status

**Reserved** (2026-06-26). This ADR's number is claimed and its
scope named so the schema decisions in ADR-0023 can reference it
durably, but its substantive reasoning will land when the first
standard pulls in for integration.

This is a **directional** decision — the standards arrive
per-demand, not on a single rollout. Writing the full ADR before
any of them is integrated would be reasoning in the abstract; the
reasoning will be sharper once a real integration is shaping
real edges in the substrate.

## Related

- [ADR-0023 — iagent AnswerArtifact as a graph-native CQRS object](ADR-0023-iagent-answer-artifact-graph-cqrs.md):
  the ADR this one is split out from. ADR-0023 **reserves the
  edge vocabulary** (`PRODUCED_BY_PROCESS`, `CONFORMS_TO`, `IS`,
  `WITHIN`); ADR-0024 will **rule on the composition reasoning**
  when the first standard pulls in.
- [ADR-0017 — Presentation-as-Predicate](ADR-0017-presentation-as-predicate.md):
  the artifact-references-never-reimplements discipline this ADR
  inherits. The presentation predicate is registered, not
  re-derived per consumer; the same shape applies to standards
  facts.
- [ADR-0022 — DataHub integration: owned wrapper, mining the MCP
  server as reference](ADR-0022-datahub-integration-owned-wrapper-mining-mcp-reference.md):
  the integration-discipline template this ADR reuses — the system
  owns the integration layer (wrapper / projector / adapter), mines
  the upstream standard as the deterministic reference, but does
  not adopt third-party clients wholesale that would re-introduce
  the assumed-contract class.

## Scope (what this ADR will rule on, when it lands)

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

## Why this ADR is reserved rather than written now

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
  ADR-0024 ends up being one ADR per standard-seam (ADR-0024a
  BPMN-seam, ADR-0024b CALM-seam, etc.) once the integration
  shape is real. The number is claimed to keep the discussion
  durable; the granularity gets settled when the work starts.

## Triggers (when this ADR converts from Reserved to Proposed)

This ADR moves to **Proposed** when any of the following happen,
because at that point the abstract reasoning has to become
concrete:

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
triggers it owns drafting the substantive content of this ADR for
the standard it pulls in; the remaining standards' content lands
when their own triggers fire.

## What this ADR does NOT cover

- The artifact-as-graph-CQRS-node schema itself — that's
  [ADR-0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md).
- The openddil overlap — shared UI components and service reuse
  with openddil — that's an openddil-side integration concern.
- The Neo4j→Postgres projector seam — that's a component scoped
  in ADR-0023's "Open questions for the implementing PR."

## When you arrive here from a real integration PR

If you're reading this because you're about to integrate one of
the four standards, the order of operations is:

1. Confirm the trigger above matches what you're doing.
2. Update this ADR's status from **Reserved** to **Proposed** and
   write the substantive content for the standard you're pulling
   in (and at least sketch how it composes with the other three,
   even if the others are still deferred).
3. Land the corresponding standards-node type in Neo4j (e.g.,
   `:BpmnProcess` with its properties).
4. Wire the reserved edge type from ADR-0023 to the new node type.
5. Decide whether the remaining standards still wait or whether
   this PR triggers writing their content too.
