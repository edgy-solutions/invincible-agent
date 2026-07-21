---
status: Accepted
date: 2026-07-20
deciders: Platform team
---

# ADR-0030 — Fixed output type per verb re-confirmed under ADR-0029 (the rejection of result-dependent output)

## Status

**Accepted** (2026-07-20). Re-examines [ADR-0017](ADR-0017-presentation-as-predicate.md)
§1 under a constraint that did not exist when it was written
([ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md)), and records
a decision that was **proposed and rejected** during the D4 lineage work.

## Honest scope (read this first)

**~70% of this ADR is re-derivation.** [ADR-0017](ADR-0017-presentation-as-predicate.md)
§1 already decided that a verb has **one fixed `output_uri`** — its Decision
table literally reads `mesh:traceLineage → mesh:LineageTopology`, and it already
established presentation-as-predicate (`rendersAs: output_uri → archetype`,
selected via `/search_predicates`). The D4 work re-derived "one verb, one output
type" from a different direction and found it held. That the design survived
re-examination is worth something, but this ADR does **not** introduce fixed-O.

What is genuinely new, and the reason this is a standalone ADR rather than an
amendment folded into 0017:

1. **The rejection, dated and caused.** During D4 we proposed letting a verb emit
   `LineageTopology` *or* `KnowledgeDocument` depending on the answer's shape
   ("archetype follows result shape") and **rejected it** — because
   [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) made fixed-O
   *load-bearing* rather than merely tidy. 0017 argued fixed-O on cleanliness
   grounds (stop the LLM re-guessing archetypes). 0029 postdates 0017 and raises
   the stakes: its `spo_operation` verifier checks `(subject, verb)` at **load
   time**, and Slice-4 answer→step seeding matches a produced `O` to a compatible
   next step. **A result-dependent `O` breaks both** — the consumer can't be
   verified, and "what can consume this?" has no static answer. The next person
   who proposes result-dependent output types will make the same rendering-layer
   argument we did; the counterargument lives in 0029's composition requirements,
   which is why this record is kept separate rather than read as a clarification
   of an old decision.
2. **The edgeless-topology honesty rule** (below) — specific to the filtered case.

## Context

D4 surfaced two questions served by the same underlying walk: *"show the lineage
of X"* (a graph) and *"which «platform» tables feed X"* (a filtered list). The
filtered result is a flat set of nodes with no edges. The tempting fix — emit a
different `O` by result shape — is the one we rejected above. Forcing the flat
list through the topology renderer is the *other* false fix, and it is what
produced the original bug: the renderer was asked to draw a graph from data with
no edges, so the model **invented** edges and the oversized prompt timed out — a
semantic error (a list is not a graph) that manifested as a timeout.

## Decision

**A verb declares exactly one output type `O` and never changes it** (this
re-affirms [ADR-0017](ADR-0017-presentation-as-predicate.md) §1). Two rules make
that hold while serving both questions:

### 1. A projection parameter changes *content*, not *type*

`entitled_domains` already works this way — it narrows the result set, never the
result type. **`platforms` is the same category**, as is every future projection
parameter. `traceLineage` keeps `O = LineageTopology` whether or not a `platforms`
filter is supplied; the filter changes which nodes survive, not the declared
type. This is implied by 0017's fixed-O; it is stated crisply here because the
withdrawn ruling confused a *parameter* for a *new output type*.

### 2. A filtered `LineageTopology` is legitimately edgeless — and that must be honest

A platform filter crosses intermediate hops, so the surviving nodes usually have
no surviving edges. That is a **valid degenerate topology, not a failure**.
Therefore an explicit `outcome` discriminant travels in `structured_data`, and
the three edgeless situations must never render identically:

- **edgeless because filtered** → correct answer → render as a document/list.
- **edgeless because the walk failed** → a failure → say so; do not present an
  empty list as "no dependencies."
- **non-empty topology** → render as a graph.

(Same three-outcome discipline as the URN-resolution floor: a confident hit
proceeds; no hit or an ambiguous set says so rather than silently picking.)

## What this ADR deliberately does NOT decide

**Presentation transforms (`O → O'`) are directional, not required.** During D4
we floated modelling shape changes as a chain of presentation verbs
(`LineageTopology → presentAsDocument → KnowledgeDocument`), with `rendersAs` as
the degenerate case. That is **not adopted here**, for a sharp reason: 0017's
`rendersAs` already allows *multiple* archetype candidates per `O`, ranked by
`persona_fit`/`domain_fit`. If presenting a `LineageTopology` as a document is
just a *second `rendersAs` edge on the same `O`*, then a new transform primitive
is over-engineering — 0017's existing mechanism covers it.

**Open question (stated, not resolved):** 0017's `rendersAs` selects by
persona/domain fit, **not by content**. The edgeless-vs-graph choice is
*content-based* (does the topology have edges?), which has **no home in 0017's
model**. D4 handles it in the presentation layer as **degradation** — the same
content-based pattern as the empty-chart→document fix (an edgeless/empty payload
with real text degrades to a document rather than rendering an empty graph).
Whether content-based presentation selection *generalizes* — into a first-class
mechanism, an extension of `rendersAs`, or a presentation-SPO layer — is
**undecided**. This ADR leaves that door open without claiming it is built.

## Near-term (the D4 lineage fix)

- `traceLineage` keeps `output_uri = LineageTopology`, **unchanged**. `platforms`
  is a parameter (rule 1), populated by the `ExtractPlatformScope` extractor.
- The deterministic branch retrieves the filtered set, populates `structured_data`
  in code, and **writes the summary FROM that structure** (so narrative cannot
  contradict evidence), emitting a `LineageTopology` — nodes = surviving set,
  edges usually empty.
- **The render is the empty-chart degradation pattern, NOT a transform chain.**
  An edgeless topology carrying a real summary degrades to a document in the
  presentation layer, keyed on the `outcome` discriminant (rule 2), never guessed
  from empty edges. No new presentation primitive is introduced.
- **Boundary:** this is the **last** verb-specific deterministic branch. A
  *second* verb needing the same treatment is the trigger to generalize, not
  another `if`.
- **Injection point (banked):** the deterministic branch replaces only the
  `raw_agent_response, execution_trace, conf` tuple the smolagent path produces;
  all shared response assembly (memory, `output_uri`, `sources`, the full
  `AgentResponse`) runs unchanged, so the complete-response shape (TRACE,
  provenance, sources, left-bar fields) is satisfied *by construction*.

## Owed items — enumerated so "partially applied" stays visible

A decision that establishes a pattern but does not list its consumers cannot
know it is only *partly* applied; the gap becomes discoverable only by a
question that happens to have a knowable answer — which is exactly how the
edgeless-topology bug hid in plain sight (the topology path "worked" for a long
time in the sense that it returned *something*; the fabricated edges and the
whole-list-through-the-LLM reshaping were structurally wrong the entire time).
This section is the checkable record: the consumers of this pattern, and the
follow-ups still owed.

### Consumer adoption (fixed-`O` + deterministic-shape)

| Consumer | Adopted? |
|---|---|
| Engine A `traceLineage` — deterministic branch, fixed `LineageTopology` | ✅ 62bb71e |
| Engine F — edgeless `LineageTopology` → document on the `outcome` discriminant | ✅ 62bb71e |
| Engine F — non-empty topology → graph (`RenderAsTopology`) | ✅ unchanged (the straggler that had been left un-adopted) |
| A *second* verb needing a deterministic branch | ❌ — trigger to **generalize**, not add another `if` |

### Owed: URN resolution belongs on Engine D, not Engine A

D4's subject-name → URN resolution currently runs **inside Engine A** (the
deliberately wrong-on-sight `_TEMPORARY_urn_resolution_belongs_on_engine_d`): a
DataHub search, an `entity_type` derived from the ontology class, top hit under
the ambiguity floor. That is DataHub entity-model knowledge on the wrong engine.

- **Correct home:** Engine D already has `resolve_instance` — this operation *is*
  that. Engine A should call an Engine D endpoint, not reach into the entity
  model. (The *walk* is already layered correctly: Engine A calls Engine D's
  `/lineage_by_platform` over HTTP; only this resolution sub-step leaked.)
- **Why it's here:** `resolve_instance`'s registration is rejected at load
  because `mesh#InstanceIdentifier` / `mesh#InstanceResolution` don't resolve in
  Neo4j — the partial mesh-ontology load gap (a bootstrap-state-debt thread). D4
  routes around the broken endpoint.
- **Marker, not a TODO:** the logic is isolated in one function whose *name*
  reads as wrong every time the file is opened, because a TODO comment is
  precisely how a straggler stays invisible.
- **Trigger to move:** Engine D's `resolve_instance` registers cleanly (the
  `mesh#Instance*` classes load). Then delete the Engine-A function and call the
  endpoint — the call site is written to stay identical across the move.

## Consequences

- Static composition survives (the reason it now matters): one verb, one `O`,
  load-time verifiable, seedable. The rejection of result-dependent `O` is on the
  record with its cause (0029), for the next person who re-proposes it.
- No new presentation primitive is committed. Content-based render selection is a
  named open question, handled near-term by degradation.
- D4's code is consistent with plain 0017 — which is a good sign the contract was
  right, and the reason the ADR trim changed no code.

## Related

- [ADR-0017 — Presentation-as-predicate](ADR-0017-presentation-as-predicate.md):
  decided fixed `output_uri` per verb (§1) and `rendersAs`. This ADR re-confirms
  §1 under a stronger constraint and records the rejection that protects it.
- [ADR-0029 — Process-workflow model](ADR-0029-process-workflow-model-spo-steps-restate.md):
  the `spo_operation` load-time verifier and Slice-4 seeding that make fixed-O
  load-bearing rather than tidy.
- [ADR-0012 — UI archetype rigidity](ADR-0012-ui-archetype-rigidity.md): the
  archetype is a property of the declared type, not an LLM guess.
