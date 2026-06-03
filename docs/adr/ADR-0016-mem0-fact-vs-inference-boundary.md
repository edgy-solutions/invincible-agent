# ADR-0016 — Mem0 boundary: tool-grounded facts vs agent inferences

**Status:** Proposed
**Date:** 2026-06-03
**Deciders:** Platform team
**Related:**
  - [ADR-0001](ADR-0001-mem0-llm-decouple.md) — decouple the Mem0
    fact-extraction LLM from the agent's reasoning LLM. This ADR
    extends ADR-0001 by saying that decoupling the LLMs isn't
    sufficient if the *content* the extractor ingests still mixes
    tool-grounded facts with agent inferences.
  - [ADR-0014](ADR-0014-no-hardcoded-urn-hints.md) — same family of
    failure: scaffolding/context that hardens into pseudo-truth when
    divorced from the registry that should own it. ADR-0014 was the
    case at the prompt-layer; this ADR is the case at the memory
    layer.
  - [ADR-0015](ADR-0015-router-regression-L1.md) — the routing-
    decision audit table provides a *positive* model of "every
    decision is a row, sourced and queryable." This ADR proposes the
    same shape for memory.

## Context

Mem0 v2.0.1 sits between the agent's smolagent loop and a Weaviate
collection. After each agent turn the fact-extraction LLM (post
ADR-0001, deliberately a smaller non-reasoning model — currently
`phi4-16k:14b` on the openwebui host) is given the conversation and
asked to emit "facts" to persist. On the next session those facts
are retrieved as "Relevant Past Experience" and injected into the
agent's prompt.

### The trigger

During the 2026-06-03 DataHub query suite session:

1. Q9 (`catalog_pii`) — "Find every dataset tagged 'pii' exposed to a
   Superset dashboard" — ran in the suite, and Engine A answered
   incorrectly: "No PII datasets are exposed to a Superset
   dashboard." (The correct answer was at least
   `customers_gold → Customer 360`.)
2. After the suite run, Mem0's fact-extractor processed the agent's
   conversation and emitted what it considered a fact:
   *"Assistant found no datasets tagged 'pii' that are exposed to
   any Superset dashboard in the DataHub catalog."*
3. That string was persisted to the `Mem0migrationsOllama` Weaviate
   collection.
4. When Q9 was re-fired (with a freshly-deployed prompt update that
   should have made the agent compose cross-feature predicates),
   Mem0's retrieval surfaced the same string as "Relevant Past
   Experience," and the agent again answered "no PII datasets
   exposed."

The new prompt rule was correct. The agent *started* a
`search_datahub(query="pii", entity_type="dataset")` call (visible
in the agent's reasoning trace). But the confident prior from past
experience overrode the new reasoning pattern, and the agent gave
up before applying the second-condition check.

### Why this happens

The Mem0 fact-extractor sees a transcript like:

```
user:      Find every dataset tagged 'pii' exposed to a Superset dashboard.
agent:     [tool call to search_datahub]
tool:      [response]
agent:     "No PII datasets are exposed to a Superset dashboard."
```

And the extractor LLM is asked to emit facts about this conversation.
It has no way to distinguish between:

- **Tool-grounded fact**: a statement directly verifiable in the
  `tool:` response — e.g. "search_datahub returned customers_gold
  with owner alice@company.com"
- **Agent inference**: an interpretation in the `agent:` final
  reply — e.g. "no PII datasets are exposed"

Both look like declarative statements about the catalog. The
extractor picks the second because it's a tidy summary; the first
is verbose and harder to compress. So the agent's *interpretation*
gets stored as a fact about the world.

On the next session the agent reads "no PII datasets exposed" in its
Past Experience block. The agent's grounding rule says "use only
what the tools return" — but past experience *looks* like it came
from a tool because it's presented as a bullet-point fact, not as
"agent claimed X." The grounding rule fails to discriminate.

The result: **every confident wrong answer becomes a memory that
biases the next attempt.** Mistakes self-reinforce across sessions
silently. The agent gets worse at certain question shapes the more
it sees them, the opposite of what episodic memory is supposed to
provide.

This is the same shape as ADR-0014 (scaffolding hardens into pseudo-
truth) but at a deeper layer: ADR-0014 was prompts; this is memory.

## The constraint we want to keep

- **Tool outputs are authoritative.** Anything written to Mem0 that
  claims to be a fact about the world MUST be derivable from a tool
  response, not from an agent's interpretation.
- **The provenance of every memory must be traceable.** When a fact
  is recalled, we should be able to say "this came from
  search_datahub on date D, query Q, returning result R." Not "the
  agent once said X."
- **The agent treats memory as informative, not authoritative.**
  Past experience is a starting hypothesis, never a substitute for
  the current tool call. The grounding rule needs to be explicit
  enough that the agent doesn't blur the two.
- **Past mistakes are detectable and recoverable.** If a wrong fact
  ends up in memory, there must be a path to identify and remove it
  without a full collection flush.

The constraint we are willing to relax (and what we relax it for)
is **the assumption that "Mem0 fact" means the same thing as
"verified fact."** It currently doesn't. Either we tighten what
Mem0 stores, or we tighten how the agent reads it. This ADR
proposes doing both.

## Decision

### 1. Separate the storage of tool-grounded facts from agent inferences

Today: one Weaviate collection `Mem0migrationsOllama` holds
everything mem0 extracts.

Proposed: two collections (or one collection with a `source` field):

- `ToolFacts` — only entries that are directly traceable to a tool
  output. Each entry carries the tool name, the call arguments, the
  raw tool response excerpt, and a timestamp. Written exclusively
  from tool-output transcripts, never from agent statements.
- `AgentInferences` — entries derived from the agent's reasoning or
  final answers. Stored but explicitly labeled as inferences,
  retrieved into a different prompt block ("Prior reasoning") that
  the agent treats with skepticism.

The extractor LLM gets two different prompts depending on what slice
of the transcript it's processing:

```
For the tool: block:
    "Extract verifiable facts directly stated in the tool response.
     Do NOT add interpretation. Quote field values exactly."

For the agent: block:
    "Summarize the agent's conclusions. Mark each as an inference,
     not a fact. Note whether the conclusion was positive or
     negative (e.g. 'agent concluded NO X exists')."
```

These two streams get retrieved into different prompt blocks at
retrieval time. The agent's instructions for each block are
different:

```
Tool-grounded Facts (authoritative starting context):
  - ...

Prior Reasoning (HINTS only — these are the agent's earlier
guesses; verify against current tool output before reporting):
  - ...
```

The cost is two retrieval calls per agent invocation instead of one,
and one extra extractor call per agent turn. Both are cheap on the
openwebui host (small model, fast inference).

### 2. Provenance on every Mem0 record

Every record written to Mem0 (in either collection) carries:

- `extracted_from` — which agent turn the fact was lifted from
- `source_tool` — for ToolFacts, the tool that produced the
  response; for AgentInferences, the agent's reasoning step ID
- `source_call_args` — for ToolFacts, the arguments the agent
  passed to the tool. Allows the team to query "did this fact come
  from a tool call that was actually grounded against current data,
  or was it from a stale prior session?"
- `extracted_at` — wall-clock at extraction
- `extractor_model` — phi4-16k:14b today; tomorrow possibly different

These fields are not used by the agent at runtime, but they make
the team's debugging-of-bad-memories workflow tractable. When a
wrong fact shows up in past experience, you can query
`SELECT * FROM tool_facts WHERE text LIKE '%no PII%'` and see
exactly where it came from, then delete just that record (or that
class of records).

### 3. The agent's prompt explicitly distinguishes the two blocks

Engine A's system prompt already has a "PAST EXPERIENCE IS A HINT,
NEVER A FACT" rule (added in commit c5168c1 as the immediate
mitigation). With two-stream Mem0, that rule splits:

```
Tool-grounded Facts: These ARE authoritative — they were lifted
verbatim from a prior tool call. You can rely on them without
re-verification IF they are recent and IF the tool's underlying
data hasn't changed since. Recency is shown in the timestamp.

Prior Reasoning: These are HINTS only. They reflect the agent's
earlier interpretations and may be wrong, including wrong because
the agent was wrong. NEVER substitute prior reasoning for a fresh
tool call. If prior reasoning says "no X exists," IGNORE it and run
the tool anyway.
```

The split makes the asymmetry between "this came from a tool" and
"this came from me" explicit at the agent's reading layer.

### 4. Periodic re-verification of stored ToolFacts

Even tool-grounded facts go stale. A weekly background job re-fires
the original tool call for a sample of ToolFacts entries and
compares the response. If the fact's underlying value has changed
(e.g. the owner of a dataset changed), the old fact is marked stale
and demoted from "authoritative" to "historical reference."

This is the dual of ADR-0015's canary pulse: that one validates
routing decisions; this one validates stored memories. Same shape,
different content.

## Alternatives considered

### Disable Mem0 entirely (rejected)

Drop the `MEM0_ENABLED` flag to false on all engines. No past
experience, no pollution, no extractor LLM.

Why rejected: Mem0 *does* provide value when its facts are correct.
Q3 (lineage_src) in the clean-cluster run benefited from Mem0 facts
about the lineage chain extracted from earlier queries; those facts
were correct because the agent's earlier statements about the
lineage were correct. The problem is selectivity, not the existence
of the layer.

### Keep one collection but filter on extraction time (rejected)

Have the extractor LLM emit only facts it can directly attribute to
a tool response, in a single collection.

Why rejected: the extractor LLM is the same one that today emits
inferences. Asking it to filter at extraction time means trusting
the same model to know what's a fact vs an inference, with no
structural enforcement. We already see it fails this distinction in
practice. The two-collection separation forces the distinction at
the data-model level, which is enforceable.

### Switch to a different memory framework (deferred)

Mem0 v2.0.1 has its own opinions about extraction. We could replace
it with something with explicit fact-vs-inference structure
(LangChain memory, custom).

Why deferred: a swap is a multi-week migration with downstream
impact on Engine E too. The two-stream pattern works *within* Mem0
by treating the existing extractor as a labeller that emits two
streams. If we ever migrate off Mem0 the pattern carries forward.

## Open items

- **Provenance schema on `ToolFacts`**: the exact JSONB shape for
  `source_call_args` needs to fit Mem0's existing storage model
  (which is text-blob-shaped). Probably we add a separate sidecar
  table keyed by mem0's record id.
- **Re-verification sampling strategy**: weekly is a reasonable
  starting cadence; high-volume catalog facts may warrant daily;
  rare maintenance manual facts can probably go quarterly. Should
  be configurable per-collection.
- **AgentInferences retention policy**: do we ever DELETE these, or
  let them accumulate? They're useful for "the agent has tried this
  question before and got X, Y, Z, all wrong" patterns the routing
  team might want to mine (per ADR-0015's adversarial-mining
  pattern). Probably TTL them at 90 days or so.
- **Cross-engine sharing**: Engine A and Engine E both use Mem0
  today. They should share the `ToolFacts` collection (the catalog
  is the catalog regardless of which engine asked); they should
  NOT share `AgentInferences` (each engine's reasoning is its own
  concern). The shared/private split needs to be wired explicitly
  at retrieval time.

## Out of scope

- The router-regression observability layer of ADR-0015. The two
  ADRs share design patterns (audit / provenance / continuous
  validation) but their data stores and consumers are separate.
- Replacing Mem0 with another memory framework. Considered and
  deferred above.
- The fact-vs-inference distinction at the BAML output layer. BAML
  outputs are already strongly typed; the inferences-as-facts
  problem is specific to mem0's plaintext storage.
- The Mem0 storage of *user* statements (e.g. "the user prefers
  concise answers"). Those are facts about the user's preferences,
  not about the world, and they belong in a third collection
  (`UserPreferences`) that's out of scope for this ADR's catalog-
  fact discussion.
