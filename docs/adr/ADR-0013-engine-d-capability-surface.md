# ADR-0013 — Engine D capability surface vs DataHub GraphQL richness

**Status:** Proposed
**Date:** 2026-06-02
**Deciders:** Platform team
**Related:**
  - [ADR-0012](ADR-0012-ui-archetype-rigidity.md) — parallel structural
    concern at the *rendering* boundary. ADR-0012 is "the UI shapes
    we let the LLM emit are too narrow." This ADR is "the catalog
    capabilities we let the LLM ask about are too narrow." Same
    family of design tension (rigid shapes protecting grounding vs.
    expressive shapes serving real questions), different boundary.
  - `agent_fleet/datahub_wrapper/main.py` — Engine D today. One
    `/query_metadata` endpoint, one GraphQL query, one formatted-prose
    response.
  - `agent_fleet/restate_analyst/main.py` — Engine A's `search_datahub`
    tool, the only consumer of Engine D. Its tool docstring now
    documents Engine D's response format (commit `9b333ce`), which
    surfaced the question this ADR addresses.

## Context

This is a **decision-deferred design exploration**. The intent is to
capture the shape of the problem and the trade-offs of each direction
so the future implementation decision is informed rather than
relitigated under pressure.

### What Engine D is today

Engine D is a thin FastAPI wrapper that fronts DataHub's GraphQL
endpoint with a single search-shaped capability. Its surface:

- **One tool exposed upward**: `search_datahub(query, entity_type)` —
  fuzzy keyword search over DataHub's `search` GraphQL field.
- **One GraphQL query template** (`_GENERIC_SEARCH_QUERY`) — a fixed
  fragment that selects a hand-picked subset of fields for each entity
  type (Dataset / Dashboard / Chart).
- **One response shape** — a multi-line prose block, one matched
  asset per stanza, owned + lineage + freshness + tags + columns
  serialized as `key=value` and indented sub-lines. The agent reads
  this format per the tool docstring contract.
- **Live introspection limited to the `EntityType` enum** at startup,
  so the agent can be told "you may pass DATASET, DASHBOARD, CHART,
  DATA_FLOW, DATA_JOB" as the `entity_type` argument. Nothing else
  about DataHub's schema is discovered or surfaced.

Post-enrichment (commit `15c4fa1`), the fields exposed per entity are:

| Field | Source aspect |
|---|---|
| urn, type, name, description | `properties` |
| owner usernames | `ownership.owners.owner` (CorpUser only) |
| tag names | `tags.tags.tag` |
| schema columns (up to 12) | `schemaMetadata.fields[*]` |
| upstream / downstream URNs | `relationships(DownstreamOf, Consumes)` |
| last update timestamp + type | `operations[0]` |
| Platform filter detection | hardcoded `PLATFORM_MAP` of 5 platforms |

### What DataHub's GraphQL actually offers

DataHub's GraphQL surface is large. A representative (non-exhaustive)
list of capabilities we do *not* expose:

- **`CorpGroup` ownership** — we only walk CorpUser. Groups own things
  in real catalogs ("the Sales DataEng team owns this dataset").
- **Glossary terms** (`glossaryTerms`) — the formal taxonomy /
  business glossary surface, distinct from informal tags. "What's the
  business definition of `customer_segment`?" is a glossary question.
- **Structured properties** (`structuredProperties`) — DataHub's
  user-defined-fields feature. Anything custom an org has added to
  its catalog is invisible to us.
- **Health & assertions** (`health`, `assertions`) — data quality
  state. The "is this dataset currently healthy / are the freshness
  SLOs being met / did the last quality check pass?" question
  DataHub is explicitly designed to answer is unreachable.
- **Usage stats** (`usageStats`) — view counts, top users, query
  frequency. "Is this dashboard load-bearing?" today collapses to
  "how many downstream assets does it have?" — which is a much
  weaker signal than "how many distinct users hit it last week?"
- **Field-level lineage** — DataHub tracks column-to-column lineage.
  "If we drop the `email` column from `customers_silver`, what
  downstream columns break?" needs this.
- **Domain / data product** (`domain`, `dataProduct`) — first-class
  organizational scopes. Today invisible.
- **Containers** (`container`, `parentContainers`) — the
  database / schema / folder hierarchy.
- **Browse paths**, documentation aspects, forms, subscriptions,
  role assignments, deprecation status, soft-delete state, embedded
  links, change events, deprecation notes, related entities by
  relationship type other than DownstreamOf / Consumes, etc.

A reasonable estimate: **we expose ~5-10% of DataHub's catalog
surface.** Most of the question shapes a senior data engineer
would naturally ask DataHub are unreachable through Engine A today.

### Why the current design exists (the steel-man)

The current shape is what you'd write the first time you wrap a
complex external API for an LLM. The constraints it was respecting
are real:

1. **Token economy.** A single dataset's full DataHub response can be
   tens of KB. Multiplied by N matched assets it blows the context
   window even of a 128k model in a single search call. A hand-picked
   query is a budget enforcer.
2. **Deterministic response shape.** Fixed query + fixed formatter =
   predictable token cost, predictable parse logic, BAML can ground
   what comes back because the formatter knows what fields it
   selected.
3. **Schema stability.** DataHub's GraphQL evolves across versions.
   Pinning to a narrow surface insulates us from upstream breakage.
4. **The agent doesn't know what to ask for.** Exposing every possible
   field as a tool would overwhelm the smolagent's tool-selection.
   Someone picked the "common-case 80%" — and that 80% turned out to
   be much smaller than DataHub's actual surface.
5. **Bounded LLM blast radius.** A narrow surface bounds what a
   hallucinating model can claim. Today's failure modes are limited
   to "the agent says a field is missing that's actually there" or
   "the agent quotes a field correctly but interprets it wrong." A
   wider surface introduces new failure modes (the agent claims an
   assertion passed when it didn't, the agent invents a glossary
   term that doesn't exist, etc.).

Those reasons all hold. They justify shipping today's Engine D. They
do not justify staying here forever.

### The trigger

2026-06-02 DataHub query suite testing. Several questions in the
suite map cleanly to fields Engine D exposes (ownership, lineage,
PII compliance, schema). Several others — phrased plausibly enough
that an engineer would expect them to work against any DataHub
deployment — touch fields Engine D does not expose:

- *"Which dashboards have the most weekly viewers?"* → `usageStats`
- *"Did the last quality check on `customers_gold` pass?"* →
  `assertions` / `health`
- *"If we deprecate `customers_raw.email`, which downstream columns
  break?"* → field-level lineage
- *"What's the business definition of `lifetime_value`?"* →
  `glossaryTerms`
- *"Which datasets belong to the Sales data product?"* → `dataProduct`

None of those is exotic; all are first-class DataHub features. None
is reachable from Engine A today because Engine D doesn't expose them.

The agent observably "knows" these questions exist (it sometimes
mentions a deprecation status or an assertion in its summary, drawn
from prior-session memory or training data) and that's worse than
not knowing — it's grounded in nothing.

## The constraint we want to keep

Same vocabulary as ADR-0012:

- **The LLM cannot emit arbitrary GraphQL.** No "agent writes raw
  query, Engine D runs it" path — that path makes Engine D a
  passthrough and the LLM a database admin.
- **Every tool call returns a typed, validated shape.** Tool inputs
  are typed by the `@tool` decorator. Tool outputs are strings
  whose format the docstring documents, which Engine A's prompt
  refers to. BAML eventually grounds the final answer.
- **Grounded metadata is machine-readable.** Ownership, lineage,
  freshness, assertions, etc. are addressable fields in tool
  responses, not "find it in the prose." This is what makes audit
  and downstream automation possible.
- **A failing LLM produces a bounded failure**, not a credential
  leak, not a DoS of DataHub through an unbounded query, not an
  assertion that an assertion passed when it didn't.
- **Predictable token cost per tool call.** Capability tools must
  cap their own response size; Engine D enforces depth and breadth
  bounds, not the agent.

The constraint we are willing to relax is **single-tool single-query
rigidity**: the assumption that one fuzzy-search tool with one
hand-picked field set is sufficient for the catalog questions real
users ask.

## Options

Four ways to ease the constraint without abandoning the original
contract. Each is presented in terms of what it preserves and what
it gives up, framed against the constraints above.

### Option 1 — Capability tools

Multiple `@tool` wrappers in Engine A's tool list, each translating to
a focused GraphQL fragment in Engine D. Each tool has a typed input,
a typed string output, and a docstring documenting the response
format. Examples:

```
search_datahub(query, entity_type)            # keep — fuzzy discovery entry
get_owner(urn)
get_lineage(urn, direction, depth)
get_field_lineage(urn, field, direction)
get_assertions(urn)
get_usage_stats(urn, window_days)
list_assets_by_tag(tag, limit)
list_assets_by_owner(owner, limit)
list_stale_assets(days_threshold, limit)
list_assets_in_domain(domain, limit)
list_pii_assets_without_owner(limit)
get_glossary_term(name)
```

Engine D grows correspondingly: one endpoint per capability, each
translating to the right GraphQL fragment with the right depth /
limit caps.

**Preserves:**
- BAML can still ground each call — outputs are typed strings with
  docstring-documented shape, same as today.
- Token cost is bounded per tool (Engine D caps each fragment).
- LLM cannot emit raw GraphQL — only typed tool calls.
- Bounded blast radius — each tool's response shape is small and
  audit-friendly.

**Relaxes:**
- The catalog surface grows from one tool to ~10-15. Smolagents
  handles 10-20 tools fine empirically; at 50+ the tool-selection
  step itself becomes lossy.
- Each tool is a small chunk of work to build and maintain. Some
  will overlap (e.g. `get_owner` + `list_assets_by_owner` both touch
  `ownership` — keep the GraphQL helpers DRY in Engine D, not the
  tools themselves).

**Estimated delta:** ~1-2 days per batch of 4-5 tools. Incremental;
ship one capability at a time as questions demand.

**Reliability story:** Strong. Each capability is narrow, typed, and
groundable. The agent's tool-selection picks the right capability
based on the question shape. New capabilities don't disturb existing
ones.

**This is the recommended direction.** It preserves every original
constraint, adds the catalog richness the questions need, and
grows incrementally — the platform team can land one capability per
PR without coordinating a big refactor.

### Option 2 — GraphQL passthrough with schema introspection

One tool: `query_datahub(graphql: str)`. Engine D introspects
DataHub's GraphQL schema at startup, formats it as a context block
the agent receives, and lets the agent write its own queries.

**Preserves:**
- "LLM cannot emit React" stays true at the rendering boundary
  (this is about the data boundary).

**Relaxes:**
- "Every tool call returns a typed, validated shape" — fundamentally
  broken. The query the LLM writes determines what comes back; the
  response shape is whatever GraphQL returns. No way to validate that
  the response means what the LLM thinks it means.
- "Predictable token cost per call" — the agent picks the query
  depth and selection set. A query like
  `dataset { upstream { upstream { upstream { ... }}}}` can return
  arbitrarily large results.
- Bounded blast radius — new failure modes: syntactically invalid
  queries, queries that return correct data but the agent
  misinterprets it, queries that hit fields the agent reads in
  training but which a particular DataHub deployment doesn't expose.
- "LLM cannot emit arbitrary X" generalizes to data, not just
  rendering. We *would* be letting the LLM emit arbitrary queries,
  which is the same shape of risk.

**Estimated delta:** ~1-2 weeks. Schema introspection format,
context-block construction, depth / cost limits enforced at the
Engine D layer, regression tests for the LLM-written queries that
appear in production.

**Reliability story:** Weakest for our operating environment. The
"agent writes its own GraphQL" pattern is well-loved in research
demos and consumer assistants. It is a poor fit for audit-graded
business decision support, for the same reason ADR-0012 rejected
generative UI: the failure modes are broader and harder to bound,
and the operating environment values bound-ability over flexibility.

**Recommendation: NOT this one.** Documenting for completeness and
because parts of the community will correctly point out that this is
where API-wrapping is going. The answer for this codebase is the
same as ADR-0012's: the operating environment makes the trade-offs
differently than a consumer assistant does.

### Option 3 — Capability tools auto-generated from schema

Engine D introspects DataHub's GraphQL schema at startup and, for
each entity type and addressable relationship, emits a typed `@tool`
wrapper. Tool count grows automatically as DataHub adds features.

**Preserves:**
- Everything Option 1 preserves.
- The conceptual model "agent calls typed tool that returns typed
  shape" stays intact.
- New DataHub upstream features propagate to the mesh without a
  hand-written PR.

**Relaxes:**
- Tool-list explosion. DataHub has dozens of entity types and
  hundreds of fields. A naive "one tool per relationship" expansion
  might generate 50+ tools, which strains smolagent's tool-selection.
- Auto-generated docstrings are mechanical and less useful for the
  LLM than hand-written ones that name the business use case
  ("list_pii_assets_without_owner" tells the LLM more than
  "find_entities_by_relationship_type_RemovedTag_with_filter").
- Implementation complexity is higher than Option 1. Schema-driven
  tool generation needs a tool-naming convention, a docstring
  template, a way to handle filter combinations, and a way to opt
  capabilities out (we probably don't want to expose every internal
  DataHub aspect).

**Estimated delta:** ~1-2 weeks for the generation framework, then
~free per new tool.

**Reliability story:** Same as Option 1 in steady state. The risk
moves to the generation step: a mistake in the template propagates
across every generated tool at once, rather than being caught at the
per-PR level of Option 1.

**Decision:** defer to after Option 1 has produced 10-15
hand-written capability tools. That's the data set that tells us
whether the long tail justifies the generation framework. If
hand-written tools cover 90% of the questions users actually ask,
Option 3 may not pay back its implementation cost.

### Option 4 — Status quo (keep enriching the single search tool)

Continue adding fields to `_GENERIC_SEARCH_QUERY` and the response
formatter, one at a time. The single `search_datahub` tool keeps
growing.

**Preserves:**
- The simplest possible architecture.
- The smallest possible change per new requirement.

**Relaxes:**
- Nothing — but it doesn't fix anything either.

**Hidden costs:**
- Every new field touches the single hot path. Risk of regression
  per field is borne by every caller.
- The response prose block keeps growing. The agent has to scan
  more lines to find the one field it cares about — slower, more
  expensive, easier to miss.
- The fuzzy-search return shape eventually hits a ceiling where
  the agent's context can't hold the response for N matched assets.
  We're not at that ceiling yet but we're approaching it.
- Questions that don't fit search-as-discovery (e.g. "list every
  stale asset" — there's no search keyword for that) still aren't
  reachable. Status quo absorbs catalog richness only along the
  axis of "search returns more fields per asset," not along the
  axis of "different question shapes get different tools."

**Estimated delta:** ~30 minutes per new field exposed. Tiny per
change.

**Reliability story:** Degrades slowly. The single endpoint becomes
the bottleneck; the response format becomes a load-bearing prose
contract that's hard to evolve without breaking the docstring on
`search_datahub` and the prompt on Engine A. Today's Option 4 is
fine; perpetual Option 4 becomes a slow-motion architectural debt.

## Decision

**Decision deferred. Recommended direction: Option 1, incremental.**

Option 1 preserves every constraint that justified the original
Engine D design, addresses the worst gap (the questions that touch
fields outside the hand-picked subset), and grows one PR at a time.
No big-bang refactor; the existing `search_datahub` tool stays as the
discovery entry point and new capability tools land alongside it.

Stepwise plan if Option 1 is chosen:

1. Keep `search_datahub` as-is. It's a fuzzy-discovery entry point;
   keeping it preserves backward-compatibility with everything that
   already calls it.
2. Land 4-5 capability tools that the DataHub query suite explicitly
   needs and the data already supports:
   - `get_owner(urn)`
   - `get_lineage(urn, direction, depth)`
   - `list_assets_by_owner(owner, limit)`
   - `list_stale_assets(days_threshold, limit)`
   - `list_pii_assets_without_owner(limit)`
3. Add capability tools that reach new DataHub aspects, one per PR,
   prioritized by user-question frequency:
   - `get_assertions(urn)` — health / quality state
   - `get_usage_stats(urn, window_days)` — load-bearing assessment
   - `get_field_lineage(urn, field, direction)` — column-to-column
   - `get_glossary_term(name)` — business definitions
   - `list_assets_in_domain(domain, limit)` — domain scoping
4. When the tool count crosses ~15, re-evaluate Option 3
   (auto-generation) for the remaining long tail. The empirical
   question by then will be: "are hand-written tools still better
   than generated ones for our agent's tool-selection?"

Option 2 (GraphQL passthrough) explicitly rejected for this codebase,
same reasoning as ADR-0012's Option 3 rejection: maximum flexibility
at the cost of validation strength, in an audit-graded operating
environment that values validation over flexibility.

## Open items for the future decision

- **Smolagents tool-selection scaling.** How many tools can the agent
  reliably pick between before tool-selection itself becomes lossy?
  Empirical question. The answer informs when (if ever) Option 3
  auto-generation is needed.
- **Multi-call capability tools.** Some natural capabilities require
  multiple GraphQL calls inside Engine D (e.g. "list stale assets"
  is search + filter on `operations.timestampMillis`; "list PII
  assets without owner" is search + filter on tags + filter on
  ownership). These belong as orchestrations *inside* Engine D, not
  as multi-tool loops in the agent.
- **Capability tools that return aggregates.** Counts, top-N rankings,
  group-by results. These may need their own response shape distinct
  from per-asset details. Touches ADR-0012 territory — the result
  shape may need its own UI archetype.
- **Caching.** Capability tools that return slow-changing data
  (ownership, schema) can be cached in Engine D. Engine D already
  caches the EntityType enum at startup. Caching policy belongs in
  Engine D, not in the agent.
- **Cross-capability consistency.** If `get_owner(urn)` and
  `list_assets_by_owner(owner)` give different answers (because of
  caching, replication lag, or implementation drift), the agent has
  no good way to detect this. Define a "DataHub view consistency"
  contract that every capability tool follows.

## Out of scope

- Building the capability tools. This ADR proposes the *shape*, not
  the implementation. Each capability lands in its own PR.
- Engine W and Engine E parallel structures. They have a similar
  shape (single-tool, hand-picked fields) but different upstream
  APIs (Weaviate semantic search, Neo4j Cypher). The architectural
  pattern proposed here may or may not apply; that's a separate
  decision per engine.
- ADR-0012's choices. UI archetypes and Engine D capability surface
  are independent architectural decisions, even though they share a
  constraint vocabulary. Decisions on one do not bind decisions on
  the other.
- Engine D versioning / backward-compatibility policy for the
  capability tool surface. Will likely need an ADR of its own once
  the first capability tools are in production and the second batch
  needs to evolve without breaking the first.
