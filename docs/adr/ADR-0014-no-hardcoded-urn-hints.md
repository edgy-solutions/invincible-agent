# ADR-0014 — No hardcoded URN hints in agent prompts; broker/catalog separation

**Status:** Accepted
**Date:** 2026-06-02
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) — predicate-graph
    routing is what surfaced this issue; the same query gets routed to
    different engines depending on its phrasing, so any per-engine
    prompt hint can leak across question shapes.
  - [ADR-0012](ADR-0012-ui-archetype-rigidity.md) — sibling concern at
    the UI boundary. Both ADRs are about the same family of failure
    mode: scaffolding that was correct in a narrow context leaks into
    contexts it was never meant for, and the LLM treats it as ground
    truth.
  - [ADR-0013](ADR-0013-engine-d-capability-surface.md) — argues for
    typed capability tools so the agent never has to *guess* what a
    catalog contains. This ADR is the complementary "what NOT to put in
    a prompt to begin with" rule.

## Context

During the 2026-06-02 DataHub query suite, several queries that should
have routed to Engine A (`mesh:analyzeWithCodeAgent`) instead routed
to Engine DA (`mesh:analyzeDataset`) because the supervisor's hybrid
search on Weaviate matched the word "dataset" in the user's question
more strongly to Engine DA's verb synonyms. Engine DA then answered
the catalog question — "list datasets owned by alice@company.com",
"which downstream datasets break if we change customers_silver" —
with the **hardcoded set of six URNs** baked into its system prompt:

```
urn:li:dataset:(urn:li:dataPlatform:postgres,sales_customers,PROD)
urn:li:dataset:(urn:li:dataPlatform:postgres,instance_state,PROD)
urn:li:dataset:(urn:li:dataPlatform:clickhouse,sales_customers,PROD)
urn:li:dataset:(urn:li:dataPlatform:s3,sales_customers_parquet,PROD)
urn:li:dataset:(urn:li:dataPlatform:s3,sales_customers_delta,PROD)
urn:li:dataset:(urn:li:dataPlatform:s3,sales_customers_iceberg,PROD)
```

Those URNs were added during the previous day's overnight backend-
coverage testing as a deliberate hint — the smolagent needed something
to point `query_datahub_asset` at without hallucinating during a
DataHub-mock-mode test run. The hint block did its job there.

Once Engine DA became reachable through the predicate router and
started receiving catalog-Q&A queries, the hint block became context
poison. The agent treated those URNs as authoritative ground truth.
Several wrong answers came back claiming alice@company.com owned
`sales_customers_parquet` (she doesn't — she owns
`gold.sales.customers_gold`, which IS in DataHub but which the agent
never reached because the hint block was where the agent's "known
URNs" lived).

A second, more subtle facet of the same problem: the **domain broker**
(`iagent-domain-broker`) had the same six URNs in its `LOCAL_ASSETS`
map. It registered them with the central gateway every 120 seconds.
The central gateway wrote them to Redis as `mesh_route:*` keys. Other
engines that ask the gateway "what URNs exist?" would have gotten the
same stale set. Even though Engine DA's prompt was the load-bearing
leak today, the broker was steadily re-poisoning the registry behind
the scenes.

## The constraint we want to keep

- **The LLM is grounded in tool results, not prompt scaffolding.** A
  prompt may describe *how* to discover ground truth, but it must not
  enumerate ground truth itself unless that truth is genuinely
  immutable (e.g. "today is 2026-06-02" qualifies; "here are the six
  URNs in the catalog" does not).
- **No two layers own the same fact independently.** The domain broker
  owns "URN → physical credentials." The DataHub catalog owns "what
  datasets exist + their metadata." When both layers assert their own
  list of URNs, the lists drift and the LLM has no principled way to
  pick between them.
- **Routing scaffolding doesn't masquerade as catalog data.** The
  `mesh_route:*` Redis keys exist so that, given a URN, an engine can
  look up which broker owns it. They are not a list of "datasets
  worth knowing about." Treating them as the latter is the same
  category mistake as treating a DNS table as a phonebook.

The constraint we are relaxing — by enforcement, not by giving up — is
the temptation to **paper over a test fixture by inlining it into the
prompt**. The test scaffold has to live somewhere the prompt can't
read, or the scaffold becomes part of production by accident.

## Decision

**Accepted, three rules effective immediately:**

### Rule 1 — No hardcoded URN hints in agent prompts

An agent's system prompt MUST NOT enumerate specific catalog URNs,
table names, schemas, or other entity identifiers as "known assets the
user might want to query." If the agent needs to know what assets
exist, it discovers them through a tool — `search_datahub`,
`/find_tool`, or a future capability tool per ADR-0013 — and treats
the tool result as the authoritative source.

This rule applies to:
- Per-engine system prompts (Engine A, DA, E, W, ...).
- BAML prompt templates (`DesignUI`, `FormatGraphResponse`,
  `FormatKnowledgeResponse`, ...).
- The `dynamic_schema_map` injection — schema-shape information is
  fine; specific URNs are not.
- Tool docstrings, with one allowed exception: a tool docstring MAY
  give a short example URN purely for illustrating argument format,
  provided it is clearly marked as an example (e.g.
  `# Example: search_datahub("orders_raw")`) and not as a known asset.

If a test workflow needs the agent to know about specific URNs (the
backend-coverage situation), the test seeds those URNs into the actual
catalog (DataHub) before running. The catalog is the source of truth;
the prompt asks the catalog.

**Enforcement landed:** `agent_fleet/data_analyst/main.py`'s
`sandbox_urn_hints` block was removed; the new prompt directs the
agent to call `search_datahub` first if it doesn't have an upstream
URN.

### Rule 2 — Broker / catalog separation

The domain broker owns *physical access*: given a URN, return the
credentials and connection details a `CortexDataClient` needs to read
the data. It does NOT own *catalog metadata*: descriptions, ownership,
tags, lineage. Those live in DataHub.

The `LOCAL_ASSETS` map in the broker MUST contain only URNs the broker
can actually serve credentials for. URNs that exist in DataHub but
have no physical backend (e.g. the seeded catalog assets we add for
query-suite testing) MUST NOT appear in `LOCAL_ASSETS`. Conversely,
URNs the broker serves MUST exist in DataHub as well — otherwise the
agent will discover them via the broker, ask DataHub for metadata, and
get nothing.

**Practical implication:** the broker is one of N "physical backend
registries." DataHub is the federated catalog over all of them. The
broker's job is to answer "I know X exists; how do I read it?" not
"what do I know exists?"

**Enforcement landed:** `c:/tmp/sandbox-domain-broker.yaml` (which
generates the in-cluster ConfigMap) was trimmed to only the two URNs
the broker actually has physical credentials for
(`postgres,sales_customers` and `postgres,instance_state`). Redis was
flushed of the four stale `mesh_route:*` entries.

### Rule 3 — Routing scaffolding is not catalog data

The central gateway's `mesh_route:*` Redis registry is for routing
lookups: "given this URN, which broker owns it?" It is NOT a list of
datasets a user might be interested in. Engines MUST NOT consult the
mesh-route registry to populate "known assets" context for an LLM.

If an engine needs to know what assets exist (the discovery use
case), it asks DataHub. The mesh-route registry is consulted only at
*access time*, when the engine has a specific URN in hand and needs
to find the broker that can read it.

**Enforcement:** no code change today — Engine A's existing JIT tool
discovery via Engine D's `/find_tools` already follows this pattern
correctly. The risk is future engines making the same mistake Engine
DA made. This rule is the lint check for code review.

## Consequences

- **Tests that relied on prompt hints break.** The backend-coverage
  tests for Engine DA worked because the prompt told the agent which
  six URNs to try. With Rule 1 in effect, those tests need a different
  approach: either seed the URNs into DataHub before the test, or
  pass the URN explicitly in the supervisor's `dataset_id` field.
  Both are cleaner; both are more work. The trade is acceptable.
- **Predicate routing becomes more sensitive to verb-description
  quality.** Engine DA's `mesh:analyzeDataset` verb description and
  synonyms now matter more, because the agent has nothing to fall back
  on if it's miss-routed. The next time we see a catalog-Q&A question
  go to Engine DA, it's a routing problem, not a context problem, and
  the fix is to tighten the verb description (Engine DA is for
  data-plane SQL on a specific known URN; catalog Q&A goes to Engine
  A's `mesh:analyzeWithCodeAgent`).
- **Test fixtures live in the catalog, not in code.** This is more
  ceremony — a new test needs a `scripts/seed_datahub_<scenario>.py`
  rather than a hardcoded prompt block. The discipline is worth it.

## Open items

- **Verb description audit.** Walk the current Predicate collection
  entries and assess whether each engine's verb description + synonyms
  are specific enough to discriminate from neighbors. If Engine DA's
  description mentions "dataset" without qualification, it will
  continue to match catalog-Q&A questions. Touch this once the suite
  re-run validates the fix.
- **Lint for hardcoded URNs.** Add a CI check (ruff custom rule, or a
  grep-based step) that fails the build if any file under
  `agent_fleet/*/main.py` contains a literal `urn:li:dataset:(...)`
  string outside of a test or docstring.
- **Broker register schema.** Each entry in `LOCAL_ASSETS` should
  declare which `dataPlatform` it belongs to and the broker should
  refuse to register URNs whose platform doesn't match the entry. This
  catches paste-the-wrong-URN bugs at startup rather than at agent
  query time.

## Out of scope

- The ADR-0012 UI-archetype rigidity discussion. The two ADRs are
  cousins (both about scaffolding that hardens into pseudo-truth) but
  they have separate decisions.
- The ADR-0013 capability-tool generalization. That's the right
  forward direction for Engine D's surface; this ADR is the
  complementary "what we DON'T do" rule for prompt construction.
- The mesh_route TTL policy. Today the gateway writes mesh_route keys
  with a 5-minute TTL and the broker refreshes them every 2 minutes.
  That cadence is fine; this ADR is about *what content* belongs in
  those keys, not *when they expire*.
