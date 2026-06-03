# ADR-0012 — UI archetype rigidity vs. data-shape diversity

**Status:** Proposed
**Date:** 2026-06-02
**Deciders:** Platform team
**Related:**
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — persona split
    (UI archetype is the caller-side concern, distinct from the
    answerer persona on each subtask response). This ADR is about
    extending that vocabulary, not changing the split.
  - `baml_shared/baml_src/contracts.baml` — the `SemanticArchetype`
    enum, the six concrete UI component classes
    (`TopologyUI` / `HazardUI` / `MetricUI` / `DocumentUI` / `ChartUI`
    / `DigitalTwinUI`), and the `DesignUI` BAML function that routes
    raw agent text into one of them.
  - `agent_fleet/presentation_agent/main.py` — Engine F, a 60-line
    handler whose entire job is to call `b.DesignUI(raw_data,
    persona)` and return the resulting `DashboardUI`.

## Context

This is a **decision-deferred design exploration**, not an
implementation commitment. The intent is to capture the design space
honestly so the future decision is informed rather than relitigated
in a hurry under a failing test.

### What the current architecture is for

The mesh uses a fixed set of six UI archetypes:

```
PROCESS_TOPOLOGY     // workflows, BPMN steps         → graph/diagram widget
HAZARD_DECLARATION   // safety, risk, warnings        → red-banner widget
ASSET_STATE_METRIC   // inventory, telemetry, tables  → tabular widget
KNOWLEDGE_DOCUMENT   // manuals, prose, code          → markdown panel
CHART_WIDGET         // BAR / LINE / PIE              → Recharts
DIGITAL_TWIN_3D      // element-level diagnostics     → three.js scene
```

Each archetype has a strictly-typed BAML class (e.g.
[`MetricUI`](../../baml_shared/baml_src/contracts.baml) carries
`metrics: UIEntity[]`, where `UIEntity = { id, name?, type?,
description? }`). The frontend has one React component per archetype
and a single switch on `archetype` to dispatch.

**This is not an accidental design.** It is doing real work:

- **Type safety end-to-end.** The frontend never receives shapes it
  doesn't know how to render. BAML rejects outputs that don't match
  the class. The contract is enforceable at every layer between the
  LLM and the screen.
- **Grounding.** BAML's structured-output constraint is the *only*
  reason `KnowledgeResponse.referenced_documents`,
  `GraphExpertResponse.confidence_score`, and the persona-specific
  response types (`MechanicResponse`, `AuditResponse`, ...) reliably
  carry truthful metadata. Without BAML enforcing the schema, the LLM
  emits prose that *resembles* structured output but isn't.
- **Predictable rendering.** Frontend code paths are statically
  analyzable. There is no "agent emits arbitrary JSX" rabbit hole.
- **Bounded blast radius for LLM failure.** When the model hallucinates,
  the damage is bounded to the fields the BAML class names. The
  frontend can't be tricked into rendering executable content or
  re-arranging its layout based on agent output.

This matters because the operating environment is **decision support
inside a regulated business**, not a consumer chatbot. A pilot reading
a `MetricUI` table of "fuel pump TBOs" needs to know that every row is
a real part with a real owner and a real interval, not a hallucinated
table that looks confident. The strict archetype contract is what
makes "looks confident" map to "actually grounded."

### Where it falls down

The constraint that protects grounding also constrains
**expressiveness**. Real catalog and maintenance answers carry more
fields than the archetypes can hold.

Concrete trigger (2026-06-02 session):

The DataHub query suite asked Engine A questions like:

- *"Who owns the customers_gold dataset?"*
- *"What is the source of truth for the Revenue by Region dashboard?
  Follow lineage back to the raw Postgres source."*
- *"If we change customers_silver's schema, what dashboards break?"*

Engine A correctly called `search_datahub` on Engine D, which returned
(verified via direct curl):

```
[DATASET] gold.sales.customers_gold | owner=alice@company.com
                                    | last_updated=2026-04-18
                                    | tags=pii
    description: Customer table with computed segments...
    upstream: DATASET:silver.sales.customers_silver
    downstream: DASHBOARD:Customer 360, CHART:Top Customers
    columns: customer_id:STRING, name_masked:STRING, region:STRING,
             segment:STRING, lifetime_value:NUMBER
```

Engine A's smolagent then produced a correct natural-language answer
naming alice@company.com and the lineage chain. Engine F's `DesignUI`
then routed that answer to **`ASSET_STATE_METRIC`** (MetricUI) because
the rule "data describes a list of assets → use MetricUI" fired.

MetricUI's slots are `{id, name?, type?, description?}` — four
columns. The owner (alice) didn't fit. The lineage chain
(silver→bronze→postgres) didn't fit. The freshness (2026-04-18)
didn't fit. The columns array didn't fit. The PII tag didn't fit.

What the model did next is instructive. Asked for an `id` field where
none of the agent's text had an URN-shaped identifier handy, it
**invented URNs from training/prompt context** — specifically the
`urn:li:dataset:(...,sales_customers_parquet,...)` / `delta` /
`iceberg` URNs that had been mentioned in the previous overnight
backend-coverage test seed. Those URNs are not in the current DataHub
catalog at all. They came from somewhere in the LLM's context window
or its prior session memory; either way they are wrong.

The pattern across the eight wrong responses we collected before
killing the suite was uniform: **the strict UIEntity schema demanded
identifiers, the agent didn't have grounded ones for the four-slot
layout, so the model substituted plausible-looking URNs that read as
correct.**

A workaround patch ([commit 9d289e6](../../baml_shared/baml_src/contracts.baml))
extends `DesignUI`'s prompt with explicit grounding rules:

1. NEVER INVENT IDENTIFIERS — every `id` must appear verbatim in
   `raw_data`.
2. NEVER INVENT ASSETS — `metrics` array entries must correspond 1:1
   to assets named in raw_data.
3. PREFER PROSE WHEN IN DOUBT — catalog Q&A goes to KNOWLEDGE_DOCUMENT.
4. NO PARSING-WITHOUT-EVIDENCE — don't manufacture downstream names
   for "impact" questions.

That patch **prevents the hallucination** but **does not solve the
underlying constraint mismatch**: when the data has twelve relevant
attributes per row and the archetype has four slots, eight attributes
are still being dropped. Rule (3) pushes catalog Q&A to
KNOWLEDGE_DOCUMENT, which preserves all the prose but **loses
interactivity** — the user can't sort by `last_updated`, filter by
`owner`, or drill into a column on click. The four-column table was
the only interactive thing in the answer; the workaround removed it.

This is the architectural sore point: **rigid archetypes protect
grounding by constraining shape, but the chosen shapes don't span the
shapes real business answers take.** The LLM's response to insufficient
shape is to hallucinate to fill the slots, which silently breaks
grounding via a different path.

## The constraint we want to keep

Whatever option we pick, the original design's contract must hold:

- **The LLM cannot emit arbitrary React.** No "agent emits JSX" path.
- **Every shape the frontend receives is type-validated.** BAML or
  equivalent enforces structure before render. The frontend never
  guesses.
- **Grounded metadata is machine-readable, not just prose.**
  Confidence scores, source URIs, owner names, last-updated
  timestamps must be addressable fields — not "look for it in the
  markdown." This is what makes audits and downstream automation
  possible.
- **A failing LLM produces a bounded failure**, not a layout break or
  a credential leak.

The constraint we are willing to relax is **enumerated-shape
rigidity**: the assumption that six fixed schemas can carry every
real-world answer.

## Options

Four ways to ease the constraint without abandoning the grounding
contract. Each is presented in terms of what it preserves and what
it gives up, framed against the constraints above.

### Option 1 — Generalize `MetricUI` to dynamic columns

Replace the fixed `UIEntity { id, name, type, description }` with an
explicit column schema:

```baml
class TableColumn {
  key string            @description("Field key in each row. Must be unique within the columns array.")
  label string          @description("Display label.")
  data_type string?     @description("Optional render hint: string, number, date, url, etc.")
  source_field string?  @description("Verbatim field name from raw_data this column was extracted from. Required for grounding audit.")
}

class TableRow {
  values map<string, string>
}

class MetricUI {
  archetype SemanticArchetype @description("MUST be ASSET_STATE_METRIC")
  source_persona string?
  subject_concept string?
  columns TableColumn[]
  rows TableRow[]
}
```

The LLM picks which columns the data deserves. The frontend renders a
generic table (AG-Grid, TanStack-Table, or whatever already exists)
with the LLM's column list. No new archetype is introduced.

**Preserves:**
- Type safety — the contract is still strict, just at a different
  level (every cell is `string`, every row has a `values` map).
- Bounded blast radius — the frontend is still a single component
  with no JSX-execution path.
- Audit — `TableColumn.source_field` is a new addressable field that
  enforces "this column came from this raw_data field name." Pairs
  with the existing grounding patch.

**Relaxes:**
- The frontend now has to handle arbitrary column lists. This is
  cheap with modern table libraries but is a real frontend change.
- The LLM now has more freedom to pick columns badly. The grounding
  rules from the workaround patch carry forward, and `source_field`
  gives the auditor a way to verify each column post-hoc.

**Estimated delta:** ~1 day. BAML class change, `DesignUI` prompt
update, one React component swap, regenerate clients.

**Reliability story:** Strong. Every column the LLM emits must name
its `source_field`, which is a verbatim field from raw_data. If
that field doesn't exist, the table fails validation. The LLM's
freedom is at the column-selection layer, not the data-fabrication
layer.

### Option 2 — Add a `RICH_KNOWLEDGE_DOCUMENT` archetype with embedded structured blocks

Keep KNOWLEDGE_DOCUMENT for plain prose. Add a richer variant that
allows the LLM to emit markdown with embedded structured blocks:

- Markdown tables → frontend renders them as interactive tables.
- Mermaid blocks → diagram widget.
- Fenced JSON blocks tagged with a `schema:` annotation → typed
  cards.

The LLM has full markdown freedom; the frontend has a renderer that
recognizes the embedded structured forms.

**Preserves:**
- Type safety at the archetype level (it's still `RichDocumentUI`
  with `markdown_content: string`).
- The "grounding lives in prose" model for unconstrained answers.

**Relaxes:**
- The frontend now has to parse markdown for embedded structure,
  which means a markdown extension surface (and its bugs) is now part
  of the trust boundary. A markdown table cell could contain HTML
  that the renderer mishandles. This is solvable (CommonMark + strict
  sanitizer) but it is a new attack surface that the strict archetype
  model didn't have.
- Auditing structured embedded blocks is harder than auditing typed
  BAML fields. "Was this number in the source data?" requires
  markdown parsing rather than field lookup.

**Estimated delta:** ~2-3 days. Mostly frontend (markdown extensions
+ sanitizer). Backend just relaxes `markdown_content`'s constraint.

**Reliability story:** Mixed. Stronger expressiveness, weaker
machine-auditability. Reasonable for human-consumed answers; risky
for downstream automation that wants to read fields back out of the
response.

### Option 3 — Generative UI / schema-on-emit

The LLM emits a JSON Schema describing the shape of its data,
alongside the data. The frontend has one "auto-render" component that
switches on the schema:

- `array of objects` → table with inferred columns
- `graph: { nodes, edges }` → topology view
- `timeseries: { series, x, y }` → chart
- `tree: { root, children }` → tree view

The schema is itself constrained by a BAML class (
`class GenerativeUI { schema string; data string }`), but the *content*
of the schema is free. Vercel's AI SDK and LangChain both have
patterns like this.

**Preserves:**
- The "LLM cannot emit React" rule, because the frontend is still
  the renderer.

**Relaxes:**
- The "every shape is type-validated" rule, fundamentally. The
  schema-on-emit pattern moves type validation from compile time to
  runtime, and the runtime check is "does the data conform to the
  schema the LLM emitted." That's tautological — the LLM that
  hallucinated the data also gets to declare what shape the data
  should be in.
- Bounded blast radius gets worse, because new shapes can introduce
  rendering paths that weren't tested.

**Estimated delta:** 1-2 weeks if done seriously. Schema vocabulary,
auto-render component, frontend regression tests for shapes that
appear in production.

**Reliability story:** Weakest for our operating environment. The
schema-on-emit pattern is a great fit for consumer-facing assistants
where the worst case is a confused user. It is a poor fit for
business decision support where the worst case is a hallucinated table
of fuel pump TBOs that the user trusts.

**Recommendation: NOT this one,** for the reasons above. Documenting
it for completeness — and because parts of the community will
correctly point out that this is where generative-UI is going. The
answer for this codebase is that the operating environment makes
those trade-offs differently than a consumer assistant does.

### Option 4 — Keep six archetypes; make each one richer

Don't add new archetypes. Make the existing ones less restrictive.

- `MetricUI` gets the dynamic-columns treatment from Option 1.
- `TopologyUI` gets edge labels, node sub-types, and a `metadata`
  map on each node.
- `DocumentUI` gets sidebar/figure support via additional fields,
  not via embedded markdown.
- `HazardUI` gets a severity scale and a structured `mitigations`
  list per hazard.

This is "Option 1 generalized to every archetype." It treats the
six-archetype taxonomy as essentially correct — the shapes of answers
business users want **are** topology, hazard, table, document,
chart, twin — and admits that each one needs more flexibility within
its shape.

**Preserves:**
- Everything Option 1 preserves.
- The conceptual map "answer shape → archetype" remains stable.
  Engineers reasoning about new use cases still have six buckets to
  pick from, not an open universe.

**Relaxes:**
- Same as Option 1, applied to every archetype. Each one becomes a
  more flexible contract.

**Estimated delta:** ~3-5 days. Linear in the number of archetypes;
the per-archetype change is the same as Option 1's.

**Reliability story:** Same as Option 1, applied breadth-first.
Slightly larger surface area for the grounding rules to be
maintained in `DesignUI`'s prompt.

## Decision

**Decision deferred. Recommended direction: Option 1 first, then
re-evaluate.**

Option 1 is the smallest change that addresses the worst observed
pain point (`MetricUI` rigidity), preserves every grounding
constraint that justified the original design, and gives us
operational data on whether dynamic columns + the workaround prompt
patch are enough.

If after a few weeks of real use we are still routinely losing
shape (e.g. topology answers want edge labels, hazard answers want
structured mitigations), Option 4 generalizes the same approach to
the rest of the archetypes incrementally — one per sprint, smallest
PR each.

Option 2 (rich markdown) is a strong second choice if the frontend
team prefers to absorb expressiveness through embedded markdown
rather than per-archetype schema changes. The architectural trade-off
is real and reasonable people will pick differently.

Option 3 (generative UI / schema-on-emit) is explicitly rejected for
this codebase, with the recognition that the rejection is
environment-specific. The bet against generative UI is that the
operating environment values audit-grade grounding over
maximum-flexibility rendering, and the BAML-typed archetype
contract is what enforces audit-grade grounding today.

## Open items for the future decision

- Empirical study: tag every Engine F response over a representative
  week with "which archetype, what fields were lost." That's the
  data that should drive the per-archetype generalization order if
  Option 1 succeeds and Option 4 follows.
- Frontend table library choice: AG-Grid is the obvious heavyweight;
  TanStack-Table is the obvious lightweight. The dynamic-column
  table is one component swap regardless. Capture in implementation
  PR, not here.
- Grounding-rule maintenance: the workaround patch added four
  CRITICAL GROUNDING RULES to the `DesignUI` prompt. As we
  generalize archetypes, those rules need to be carried forward and
  ideally lifted into shared text that every UI-mapping BAML
  function inherits. Possibly via a BAML `prompt`-fragment include
  if the BAML version supports it.

## Out of scope

- Whether to add new archetypes for use cases not yet exercised
  (e.g. timeline / Gantt for project plans, geospatial for fleet
  positioning). Adding archetypes is always an option; this ADR is
  about generalizing the existing six, not enumerating new ones.
- Changing the persona split from ADR-0009. UI archetype remains a
  caller-side concern; answerer persona remains a per-subtask
  concern. This ADR does not touch that boundary.
- The Engine D enrichment ([commit 15c4fa1](../../agent_fleet/datahub_wrapper/main.py))
  that surfaced the issue. That patch is correct independent of how
  we resolve the archetype question — Engine D should be returning
  rich metadata regardless of which UI archetype consumes it.
