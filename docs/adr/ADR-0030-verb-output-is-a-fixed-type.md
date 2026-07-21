---
status: Accepted
date: 2026-07-20
deciders: Platform team
---

# ADR-0030 — A verb's output is a fixed type; parameters project content; presentation is a transform

## Status

**Accepted** (2026-07-20). Extends [ADR-0017](ADR-0017-presentation-as-predicate.md)
(presentation-as-predicate) and defends the static-composition property that
[ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) (SPO-native
workflow steps) depends on. Records a ruling that was proposed and **withdrawn**
during the D4 lineage work, and the contract that replaced it.

## Related

- [ADR-0017 — Presentation-as-predicate](ADR-0017-presentation-as-predicate.md):
  presentation selection is a `/search_predicates` lookup over the produced
  `output_uri`. This ADR makes that the *general* mechanism for changing a
  payload's shape, and reframes `rendersAs` as its degenerate case.
- [ADR-0012 — UI archetype rigidity](ADR-0012-ui-archetype-rigidity.md):
  the archetype is a property of the payload's declared type, not an LLM guess.
- [ADR-0019 — Ontology routing substrate](ADR-0019-ontology-routing-substrate.md)
  / [ADR-0004](ADR-0004-predicate-graph-routing.md): the `(subject, verb,
  object)` typing this ADR keeps statically checkable.
- [ADR-0029 — Process-workflow model](ADR-0029-process-workflow-model-spo-steps-restate.md):
  `spo_operation` steps are pre-resolved and verified at load time; answer→step
  seeding (Slice 4) matches a produced `O` to a compatible next step. **Both
  break if a verb's `O` is result-dependent.** This ADR is what keeps them sound.

## Context

The D4 lineage work surfaced a real case: the question *"which «platform»
tables feed «asset»?"* is answered by a **filtered list**, while *"show me the
lineage of «asset»"* is answered by a **graph**. The specialist's filtered
result is a flat set of nodes with no edges between them.

The first, tempting fix was: let the verb emit `LineageTopology` **or**
`KnowledgeDocument` depending on the answer's shape — "the archetype follows the
result shape." That was **proposed and withdrawn**, because it breaks static
composition:

- **`spo_operation` verification** ([ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md))
  checks a declared step's `(subject, verb)` against eligibility **at load
  time**. If a verb's `O` is only knowable after it runs, the step that
  *consumes* its output can't be verified — the next step doesn't know what
  shape it will receive.
- **Answer→step seeding** (Slice 4) matches a produced answer's `O` to a
  compatible next step. A result-dependent `O` makes "what can consume this?"
  unanswerable statically.

A second false fix — force the flat list through the topology renderer — is what
produced the original bug: the renderer was asked to draw a graph from data with
no edges, so the model **invented** edges (grounding-rule violation), and the
oversized prompt timed out. That was a *semantic* error (a list is not a graph)
that manifested as a timeout.

## Decision

**A verb declares exactly one output type `O`. It never changes its mind.**
Three rules make that hold while still serving both questions:

### 1. Parameters change *content*, not *type*

A projection parameter narrows *what* comes back without changing *what kind* of
thing comes back. `entitled_domains` already works this way — it narrows the
result set, never the result type. **`platforms` is the same category**, and so
is every future projection parameter. `traceLineage` keeps `O = LineageTopology`
whether or not a `platforms` filter is supplied; the filter changes which nodes
survive, not the declared type. Type safety, verification, and seeding are all
preserved because `O` is fixed. **This is the general rule; lineage is one
instance.**

### 2. Filtering is predicate-level; presentation is a transform. Do not collapse the layers.

Retrieval decides *what* is in the answer. Presentation decides *how it is
drawn*. These are different jobs on different layers. Collapsing them — making a
rendering step do retrieval, or making a verb pick a renderer — is exactly what
produced the fabricated edges: a rendering layer was handed retrieval work and
the model was asked to invent relationships not in its input. Two layers, two
jobs.

### 3. Shape changes across `O` happen through *declared presentation verbs*

A payload of one `O` becomes a different `O` via a presentation SPO:
`LineageTopology —presentAsDocument→ KnowledgeDocument`. This is a verb like any
other — declared subject type, declared output type, statically typed,
discovered through the same eligibility machinery ([ADR-0017](ADR-0017-presentation-as-predicate.md)).
`rendersAs` (the single fixed `O`→archetype mapping) is the **degenerate case**:
the presentation verb that applies when nothing more specific does. Presentation
thereby gains the same properties as everything else — discoverable, verifiable,
seedable, composable in workflows.

### The edgeless-topology corner (explicit, because it is the odd one)

A **filtered** `LineageTopology` is *legitimately edgeless*: a platform filter
crosses intermediate hops, so the surviving nodes usually have no surviving
edges. That is a valid degenerate topology, **not** a failure. Therefore the
edgeless→document degradation MUST distinguish three outcomes and never render
them identically (same honesty discipline as the URN-resolution floor):

- **edgeless because filtered** → correct answer → render as a document/list.
- **edgeless because the walk failed** → a failure → say so, do not present an
  empty list as "no dependencies."
- **non-empty topology** → render as a graph.

## Two questions decided directionally

- **Presentation selection is implicit in Q&A, declarable in workflows —
  same mechanism, different invocation.** In a Q&A path nobody types "and
  present it as a document," so selection is the eligibility-intersection over
  the produced `O` (with `rendersAs` as the default when only one candidate
  exists). In a workflow a step may *declare* its presentation ("present this as
  X"). Same lookup, invoked implicitly or explicitly.
- **Presentation verbs need no new gate — but the reason is written at the
  seam, not inherited.** They are pure transforms over data the caller is
  already authorized to hold, so they add no aperture. This is the
  new-consumer-inherits-enforcement question answered *on purpose* rather than by
  accident (cf. the Engine D metadata-plane gate). If a presentation verb ever
  fetches rather than transforms, that reasoning no longer holds and the gate
  must be revisited.

## Near-term (the D4 lineage fix, matching this contract)

- `traceLineage` keeps `output_uri = LineageTopology`, **unchanged**. `platforms`
  is a parameter (rule 1), populated by the `PlatformScope` extractor.
- The deterministic branch retrieves the filtered set, populates `structured_data`
  in code, and **writes the summary FROM that structure** (so narrative cannot
  contradict evidence), emitting a `LineageTopology` whose nodes are the surviving
  set and whose edges are usually empty.
- The presentation layer's edgeless→document degradation (rule 3, degenerate
  case) renders it as a list — which *is* `presentAsDocument` shipped early. The
  full presentation-SPO machinery generalizes this in Stage 2.
- **Boundary:** this is the **last** verb-specific deterministic branch. A
  *second* verb needing the same treatment is the trigger to generalize (Stage
  2), not another `if`.
- **Injection point (banked so it isn't re-litigated):** the deterministic branch
  replaces only the `raw_agent_response, execution_trace, conf` tuple that the
  smolagent path produces; all shared response assembly (memory, `output_uri`,
  `sources`, the full `AgentResponse`) runs unchanged. The complete-response
  shape (TRACE, provenance, sources, left-bar fields) is therefore satisfied *by
  construction*, not by remembering to copy fields.

## Consequences

- Static composition survives: one verb, one `O`, load-time verifiable, seedable.
- No output-type *sets*, no result-dependent archetypes, no "it depends" in the
  contract. Stage 2's "`O` is a contract" statement becomes coherent: `O` is
  fixed per verb; shape changes are *declared transforms* between `O` types.
- Presentation becomes first-class and composable — a workflow can declare a
  presentation step, not just have one happen implicitly at the end.
- The near-term fix is *smaller* than the withdrawn plan (no archetype switch, no
  second verb to register), and it removes a special case instead of adding one.
