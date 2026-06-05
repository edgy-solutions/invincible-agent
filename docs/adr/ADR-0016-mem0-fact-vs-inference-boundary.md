# ADR-0016 (r2) — Fact-storage authority: read from the system-of-record, don't manufacture memory

**Status:** Accepted (r2, 2026-06-04). Tier 0(b) shipped (`infer=False`
on both engines). r1 ("two-collection Weaviate split") withdrawn.
**Date:** 2026-06-04
**Deciders:** Platform team
**Supersedes:** ADR-0016 r1 draft (2026-06-03) — "Mem0 boundary:
tool-grounded facts vs agent inferences"
**Related:**
  - [ADR-0001](ADR-0001-mem0-llm-decouple.md) — decoupled the Mem0
    extractor LLM from the agent's reasoning LLM. This revision goes
    further: decoupling the LLMs doesn't help if the agent is being
    asked to *memorize world-state that an authoritative store
    already holds*.
  - [ADR-0006](ADR-0006-verb-registry-location.md) — Neo4j ← DataHub
    via doc-tools' `aitool_registration_sensor`, uni-directional,
    doc-tools is the sole writer. §4 below renegotiates this *only*
    if/when the gated `:DERIVED_FACT` subgraph is ever populated.
  - [ADR-0014](ADR-0014-no-hardcoded-urn-hints.md) — same family of
    failure (scaffolding hardening into pseudo-truth). The r1 framing
    pointed at the memory *layer*; the corrected diagnosis is narrower
    and centers on the extractor LLM's input shape.
  - [ADR-0015](ADR-0015-router-regression-L1.md) — the
    `routing_decisions` audit table is the natural observability
    substrate for the revisit trigger in §5 below. **Currently
    proposed, not implemented** (zero matches in `src/` or
    `agent_fleet/` as of 2026-06-04).
  - [ADR-0017](ADR-0017-presentation-as-predicate.md) — added Engine
    A's catalog verbs (`mesh:lookupOwnership`, `mesh:traceLineage`,
    `mesh:describeAsset`, `mesh:filterByTag`). The Q9-class queries
    that originally surfaced this issue route through these verbs.

## Context

### The original diagnosis was wrong about the code

The 2026-06-03 r1 draft assumed Mem0's extractor receives a transcript
containing `tool:` blocks and mis-selects the agent's tidy summary
over the verbose tool-grounded fact — i.e. a *mixing* problem to be
solved by separating two streams. Discovery on 2026-06-04 falsifies
this:

1. **The extractor never sees tool output.** The only thing passed to
   `m.add()` is `[{"role":"user", content: <task description>},
   {"role":"assistant", content: <summary text>}]`
   ([restate_analyst/main.py:699-720](../../agent_fleet/restate_analyst/main.py#L699);
   structurally identical at
   [neo4j_expert/service.py:408-422](../../agent_fleet/neo4j_expert/service.py#L408)
   with variables `user_query`/`raw_agent_response` instead of
   `task.task_description`/`summary_text`). No `tool:` blocks, no
   intermediate reasoning, no `search_datahub` responses. Everything
   Mem0 ingests is, by construction, the agent's own voice. There is
   no second stream to separate from; there is one stream, and it is
   100% inference.

2. **The stock prompt is built to canonize that inference.** Mem0
   v2.0.1 with the default `version="v1.1"` runs the V3 phased
   pipeline whose system prompt is `ADDITIVE_EXTRACTION_PROMPT`,
   **not** the v1-era `FACT_RETRIEVAL_PROMPT` referenced in the r1
   draft. The v1 prompt said to ignore system messages and was
   lenient on assistant summaries. The v2 prompt explicitly
   instructs the model to extract from assistant messages and
   reframe them as facts about the user ("User was recommended X").
   The live poisoned record's `attributed_to: 'user'` is this rule
   firing on an assistant-summarized tool result —
   `attributed_to` is therefore an *output style* of the extractor,
   not a provenance signal on the input. No
   `custom_fact_extraction_prompt` is set anywhere
   (`grep custom_fact_extraction_prompt|custom_instructions` returns
   zero matches in `agent_fleet/` and `src/`); this is fully stock
   behaviour.

3. **The memorized fact had an authoritative home all along.** "No
   PII datasets are exposed" is catalog state. Catalog state is owned
   by DataHub and projected into Neo4j by doc-tools (per ADR-0006).
   It is *readable on demand* from the system-of-record. Storing the
   agent's conclusion about it in Mem0 was never necessary — it was a
   cache of something the agent could re-read, and the cache went
   stale-and-wrong the instant the agent was wrong once.

So the Q9 catalog-PII regression is not "the extractor mixed up two
kinds of fact." It is **"we asked a non-authoritative, inference-only
memory layer to hold world-state that an authoritative store already
owns, and the agent's first wrong answer poisoned the cache."**

### The architectural correction

Neo4j is the production SPO system-of-record for our data. The
sandbox Neo4j looks near-empty (10 nodes, routing predicates only)
**because the doc-tools content pipeline isn't seeded in sandbox**,
not because the architecture lacks a fact store. Reasoning from
sandbox population to production architecture was the error in the
discovery report's "category (iii)" call; it is corrected here. The
authoritative read path the agent needs already exists in
production.

## The constraint we want to keep

- **World-facts have exactly one authoritative home and one trusted
  write path.** DataHub is the catalog source; doc-tools projects it
  into Neo4j; the agent *reads* from those. No agent ever writes a
  world-fact into the authoritative relationship types.
- **The strength of the read-source is the reason not to cache.** A
  fact that can be cheaply and authoritatively re-read should be
  re-read, never memorized — in Mem0 or anywhere else. Caching
  authoritative state only buys staleness risk, and we have no
  staleness/GC layer (no cron, no canary; the only "GC" to date was
  hand-dropping the collection during the 2026-06-04 debug session).
- **Anything persisted as derived knowledge must be structurally
  distinguishable from ground truth, provenanced, and
  invalidatable.** A wrong inference must never become
  indistinguishable from a doc-tools fact.

The constraint we are willing to relax — and what we relax it for —
is **ADR-0006's "doc-tools is the sole writer to Neo4j."** We relax
it *only* to admit a second writer confined to a disjoint,
clearly-typed relationship namespace (`:DERIVED_FACT`), never the
authoritative types, and only once a concrete case demonstrates a
derivation too expensive to re-compute (see §4 gating). This
relaxation does not happen as part of this ADR's accepted scope; it
sits as the gated future path of §4.

## Decision

### 1. Authority map — what class of fact lives where

| Fact class | Example | Home | Agent operation |
|---|---|---|---|
| World-state (catalog) | owner of `customers_gold`; PII tag; lineage; dashboard exposure | **DataHub / Neo4j (SPO)** | **Read** on demand. Never memorized, never written back. |
| Ontology / taxonomy / definitions | what `owl:Class` a domain has; NL definitions | **Jena/Fuseki** | Read (via Engine O) for intent classification. Not written by agents. |
| Routing predicates (verbs) | `mesh:lookupOwnership`, engine endpoints | **Neo4j + Weaviate (predicate registry)** | Read for routing. Written only by doc-tools' sensor. |
| Caller/user facts | "user prefers concise answers" | **Mem0 with `infer=False`** | Stored as raw user/assistant transcript; no LLM extraction. |
| Agent intermediate reasoning (within session) | smolagents' `agent.logs` for the current call | **`agent.memory.steps` ephemeral state** | Read back within the session for trace formatting; intentionally discarded at `agent.run` exit. Never persisted. |
| Agent intermediate reasoning (across sessions) | a chain-of-thought step from yesterday | **nowhere** | Not persisted. |
| Genuinely-derived durable knowledge | a computed relationship no upstream pipeline produces | **Neo4j `:DERIVED_FACT` subgraph (gated, see §4)** | Currently empty by design. |

The governing principle: **read from the system-of-record; do not
manufacture memory you don't need.** For catalog state this fully
dissolves the Q9 failure — a conclusion about the catalog has no
valid destination except the authoritative store it was read from,
which is re-read, so it cannot harden.

### 2. Tier 0 — accepted decision

**This is what ships under this ADR.** `infer=False` is added to the
two `m.add(...)` call sites:

- [`restate_analyst/main.py:704`](../../agent_fleet/restate_analyst/main.py#L704) — Engine A
- [`neo4j_expert/service.py:413`](../../agent_fleet/neo4j_expert/service.py#L413) — Engine E

This disables Mem0's extractor LLM. Without it, `m.add` stores the
raw transcript only and never invokes the stock
`ADDITIVE_EXTRACTION_PROMPT` that reframes assistant messages as
user-attributed facts. The catalog-poisoning failure mode that
produced the Q9 cascade is structurally eliminated at the write
site.

What is preserved by choosing this over full disable:

- The hard-won monkey-patches in
  [`agent_fleet/utils/mem0_utils.py`](../../agent_fleet/utils/mem0_utils.py) —
  `_install_mem0_none_guards()` (lines 64-99) fixing the
  NoneType-comparison crash, `_install_mem0_score_propagation_patch()`
  (lines 119-147) fixing the langchain `score=None` hardcode, the
  `Mem0CompatibleWeaviate` adapter (lines 165-317) translating v4
  filters and sanitizing datetime/UUID payloads, the
  `_MEM0_ALLOWED_PROPS` allow-list (lines 181-184), the singleton
  init lock, the LLM-decoupled config supporting `MEM0_LLM_MODEL`
  distinct from the agent model (ADR-0001).
- The read path. `m.search` still surfaces past raw transcripts
  under the existing `PAST EXPERIENCE IS A HINT, NEVER A FACT`
  guard in
  [`main.py:577-580`](../../agent_fleet/restate_analyst/main.py#L577).
  Because the stored records are now raw user queries (not extracted
  "facts"), the similarity match is over what was *asked*, not over
  what the agent *concluded*.
- The observability surface. `@safe_observe(as_type='retrieval',
  name='mem0_context_retrieval')` at
  [`main.py:387`](../../agent_fleet/restate_analyst/main.py#L387)
  continues to ship retrieval queries to Langfuse, which keeps the
  per-session record from which the §5 revisit trigger could
  eventually be derived.

`infer=True` (the previous default) is the **rejected option**;
ADR-0017's verb decomposition + this ADR's `infer=False` together
return the system to the post-flush behavior observed in Runs 9-10
(12/12 user-visible correct) and prevent that state from drifting
back to Run 8's regressions without further manual intervention.

### 3. Surviving Mem0 use scoped to caller facts (not yet activated)

If the team later turns Mem0 retrieval into a substrate for caller
preferences and durable procedural lessons (under §5's revisit
process), the constraint at the write site is **fixed-shape records
written by code, not by an extractor LLM**. A legitimate procedural
memory is "for cross-feature-predicate questions, compose the
second condition after the first `search_datahub` call" — a strategy,
verifiable against nothing in the world, useful next time. An
illegitimate one is "no PII datasets are exposed" — a world-claim.
The distinction is enforced by construction at write time (a
preference/strategy struct), not by asking the extractor to judge
it. Until §5 activates this path, `infer=False` continues to store
raw transcripts and that's the entire scope.

### 4. The `:DERIVED_FACT` subgraph — schema and write contract (deferred)

This section describes the gated future path; **no code lands under
the current accepted scope**. It exists in this ADR so that when a
qualifying derivation appears the contract is already specified.

**Gating:** do not write the first derived fact until a concrete
case shows a derivation that is durable AND too expensive to
re-compute from the authoritative store. Catalog state does **not**
qualify — re-reading `search_datahub` is ~15s, bounded, and
deterministic for fixed state
([restate_analyst/main.py:431](../../agent_fleet/restate_analyst/main.py#L431);
Engine D is stateless), so catalog facts are always re-read, never
written here. **Production-scale caveat:** the 15s bound is the
per-call timeout, not the observed P50/P99 against a populated
DataHub. Multi-hop recursive lineage (per the
`REASONING PATTERN — RECURSIVE LINEAGE TRAVERSAL` block at
[main.py:154-167](../../agent_fleet/restate_analyst/main.py#L154))
fans out to N sequential calls per session. If P99 on
`mesh:traceLineage` / `mesh:assessImpact` against populated
production DataHub exceeds a user-facing SLO, the gating condition
may already be satisfied. This must be measured before §4 is
activated; see §5 prerequisite (c).

Four invariants, made concrete:

**(i) Structurally distinct from ground truth.** Derived facts use a
dedicated relationship type, never `MERGE`'d into an authoritative
type (`HAS_OWNER`, `UPSTREAM_OF`, etc.) that doc-tools owns. A
single edge type carries the asserted predicate as a property:

```cypher
// Derived edge — NEVER the authoritative relationship type.
(:DataAsset {urn})-[:DERIVED_FACT {
    predicate_iri:        'mesh:hasOwner',      // what is asserted
    object_value:         'alice@company.com',  // literal, or use object node ref
    confidence:           0.0,                  // agent-reported

    // --- provenance (mandatory; an edge without these is rejected) ---
    derived_by:           'engine_a_restate_analyst',
    source_tool:          'search_datahub',
    source_call_args:     '{"query":"customers_gold","entity_type":"dataset"}',
    source_response_hash: '<sha256 of raw Engine D short_answer>',
    agent_model:          'phi4-16k:14b',
    run_id:               '<restate invocation id>',

    // --- bitemporal (Graphiti pattern, built in Cypher; we own the graph) ---
    created_at:           datetime(),  // when we derived/learned it
    valid_at:             datetime(),  // when the fact is asserted true
    invalid_at:           null,        // set, not deleted, on supersession
    superseded_by:        null,        // -> id of the edge that invalidated this
    status:               'active'     // active | stale | invalidated
}]->(:Owner {email})
```

**(ii) Invalidate, never update-in-place or delete.** On a *new*
derivation about the same `(subject, predicate)`:

- If it **agrees** with an existing `active` edge → NOOP, optionally
  bump a `last_confirmed_at`. (This is the common case and is why
  naive "contradiction detection" doesn't fix Q9: agreement, not
  contradiction, is what re-confirmed the wrong answer. Agreement
  must be a NOOP, not a new row.)
- If it **contradicts** → set the old edge `invalid_at =
  datetime()`, `status = 'invalidated'`, `superseded_by = <new id>`;
  `CREATE` the new edge. History is preserved.
- **Concurrent contradictions across engines (open):** the contract
  does not yet specify arbitration for two engines deriving opposite
  predicates within the same `valid_at` window. Last-writer-wins-by-
  timestamp is the failure shape Mem0 had. Naming the arbiter is a
  §4-activation prerequisite.

**(iii) Fenced at read time.** `:DERIVED_FACT` edges are surfaced to
the agent in a context block separate from authoritative reads,
under the same guard as the existing grounding rule
([main.py:577-580](../../agent_fleet/restate_analyst/main.py#L577),
"PAST EXPERIENCE IS A HINT, NEVER A FACT"). **Telemetry gap (open):**
the fence is a prompt convention, not a runtime invariant. There is
no audit signal that records whether the agent's final answer came
from an authoritative tool result vs. a `:DERIVED_FACT` hint.
ADR-0015's `routing_decisions` audit table would close this; it is
unimplemented. The fence rule can silently degrade if a future verb
prompt drops the PAST EXPERIENCE warning, or if a `:DERIVED_FACT`
read path is added that doesn't reuse the same labeled-block
treatment.

**(iv) ADR-0006 renegotiated, on purpose.** ADR-0006's
uni-directional "Neo4j ← DataHub, doc-tools sole writer" rule is
**preserved for all authoritative relationship types.** This ADR
proposes a second writer (the engine) confined to the
`:DERIVED_FACT` type only. doc-tools remains the sole writer of
ground-truth edges; the new writer cannot touch them. Whether
agent-derived facts are architecturally first-class alongside
doc-tools-extracted facts is a decision ADR-0006's owners must
ratify — it is named here, not bent silently. **Cross-engine
isolation prerequisite:** Engine A and Engine E currently share the
Mem0 collection under `user_id`-only scoping (no `agent_id`/engine
partition). Per-engine isolation must land before either engine is
permitted to write `:DERIVED_FACT` edges.

### 5. Revisit trigger (for later resurrection)

The user's stated condition for revisiting this ADR is "when by
mean of observability tools discern valuable insight derived by
the agents that should be fed back into the graph (multihop
links)." That condition is **currently unfalsifiable** — no
recursion-depth counter, no duplicate-question detector, no
per-session tool-call ledger, and ADR-0015's `routing_decisions`
table is unimplemented (zero matches in `src/` or `agent_fleet/`).
Langfuse spans ship retrieval payloads as opaque blobs without
semantic tagging.

**Concrete prerequisites** before this ADR is revisited (any of (a)
or (b) suffices to activate §3; (c) is mandatory before §4
activation):

(a) **Recursion-depth + duplicate-question metric.** A Langfuse
metric (or equivalent) recording per-session
`search_datahub_call_count`, `recursion_depth`, and a normalized
`question_hash`. A revisit candidate emerges when, e.g.,
`recursion_depth >= 3` and `question_hash` repeats within 7 days
across distinct sessions — that's "expensive derivation, asked
again." Threshold and window are placeholders; finalize against
real data.

(b) **ADR-0015 `routing_decisions` audit table landed.** That table
provides per-request `engine`, `verb`, `output_uri`, `declared_uri`,
`echoed_uri`, and (per ADR-0017's §8 extension) `presentation_path`.
Add a `mem0_path` column and the substrate exists for "agent's
final answer derived from `:DERIVED_FACT` hint vs. fresh tool
output."

(c) **Production-scale `search_datahub` latency profile.** A load
test of `mesh:traceLineage` and `mesh:assessImpact` against
populated production DataHub. If P99 over a 5-hop trace exceeds the
user-facing SLO, §4's "too expensive to recompute" gate has already
fired and the current "default to disabled writes" stance becomes
operationally wrong for prod.

Until one of (a) or (b) lands, §3 remains inactive and Mem0
continues to run with `infer=False` storing raw transcripts only.
Until (c) lands, §4's gate cannot be invoked.

## Alternatives considered

### Two-collection Weaviate split (the 2026-06-03 r1 draft) — **withdrawn**

The draft proposed `ToolFacts` + `AgentInferences` collections in
Weaviate. Withdrawn for three independent reasons surfaced by the
2026-06-04 discovery agent and code-accuracy review:

- **No source for `ToolFacts`.** Tool blocks never reach `.add()`
  (only `[user_query, summary_text]`), so the grounded collection
  has nothing to ingest without first re-architecting the write
  path to read `agent.memory.steps`. The split presupposes a feed
  that doesn't exist.
- **Provenance is impossible on the current schema.** The
  `Mem0migrationsOllama` allow-list at
  [`mem0_utils.py:181-184`](../../agent_fleet/utils/mem0_utils.py#L181)
  has no slot for `source_tool`, `extracted_from`, etc., and the
  adapter strips unknown properties. The draft's provenance fields
  can't be written.
- **It rebuilds a fact store we already have.** With Neo4j as the
  SPO system-of-record (in production), growing Mem0 into a typed/
  provenanced/invalidatable fact store is reimplementing — worse,
  in text blobs — what the graph gives us natively. Two text
  collections are strictly dominated by typed edges in the existing
  graph.

### Write agent conclusions into Neo4j as plain SPOs — **rejected**

The tempting misreading of "Neo4j is the fact store" is "so write
derived facts into it." Rejected: an untyped, unprovenanced agent
conclusion `MERGE`'d into an authoritative relationship type is
Q9 **promoted into the system-of-record.** Mem0 poisoning was
survivable precisely because Mem0 is non-authoritative; corrupting
the SPO graph is not. Any derived write must satisfy all four §4
invariants or it does not happen.

### Tier 0(a) full disable of Mem0 on Engine A — **rejected as standing default**

Considered as the user's initial inclination on 2026-06-04. Rejected
in favour of Tier 0(b) `infer=False` because:

- **The helm-flag path doesn't exist in code.** Repo-wide grep for
  `MEM0_ENABLED` returns one match (this ADR's text) and zero
  matches in any `.py` file. [`main.py:383`](../../agent_fleet/restate_analyst/main.py#L383),
  [387](../../agent_fleet/restate_analyst/main.py#L387),
  [599-614](../../agent_fleet/restate_analyst/main.py#L599),
  [699-720](../../agent_fleet/restate_analyst/main.py#L699), and
  [`mem0_utils.py:340`](../../agent_fleet/utils/mem0_utils.py#L340)
  unconditionally build the singleton and call `m.search` / `m.add`.
  Flipping a helm value alone is a no-op — the Weaviate collection
  keeps growing. Full disable would have required code work the
  user's mental model didn't include.
- **It would put the `mem0_utils.py` monkey-patch stack on the
  dead-code path.** The None-score guard, the langchain
  score-propagation patch, the v4 schema adapter — accumulated
  across multiple Mem0 releases — would bit-rot through future
  Weaviate/Mem0 upgrades. Re-enablement in 3-6 months would be
  several days of work to recover capability `infer=False`
  preserves for ~10 lines of code now.
- **It would remove the only persistent stream of agent-derived
  statements before §5's observability is in place.** ADR-0015's
  audit table is unimplemented; Langfuse spans are content-blind.
  Mem0 writes are paradoxically the only persistent record from
  which the §5 revisit trigger could be derived. Full disable
  removes the substrate while deferring decision until evidence
  appears on that substrate — unfalsifiable by construction.

The trade-off articulated here is durable: if the team later wants
to fully disable Mem0 (both read and write paths), the right move
is to plumb explicit `MEM0_READ_ENABLED` / `MEM0_WRITE_ENABLED`
env-var guards around `get_mem0_memory()` and the three call sites
*as a separate PR*, defaulting to off, so flipping helm becomes a
real switch instead of a wish.

### Switch to a purpose-built temporal-KG engine (Graphiti/Zep) — **rejected for this stack**

Earlier in the design discussion a temporal-KG engine was floated
for provenanced, self-invalidating memory. Rejected now that the
substrate is known: we own a production Neo4j SPO store. The
bi-temporal + invalidation-on-contradiction pattern (§4 ii) would
be implemented directly in Cypher rather than bought, avoiding a
multi-week migration and a fourth graph to keep in sync. Re-evaluate
if §4 activates and the in-Cypher implementation hits a complexity
wall.

## Open items

- **Engine E re-enable (Phase 3) prerequisites.** Engine E shares
  the Mem0 collection with Engine A under `user_id`-only scoping
  ([`neo4j_expert/service.py:413`](../../agent_fleet/neo4j_expert/service.py#L413))
  and **has no grounding-rule guard** in its prompt
  ([`agent_fleet/neo4j_expert/prompts.py`](../../agent_fleet/neo4j_expert/prompts.py)
  contains only PERSONA_PROMPTS with six terse one-liners; no
  equivalent of Engine A's
  [`main.py:577-580`](../../agent_fleet/restate_analyst/main.py#L577)
  "PAST EXPERIENCE IS A HINT, NEVER A FACT" guard). Re-enabling it
  as-is would reintroduce the same poisoning path from a second
  entry point — `infer=False` mitigates the write side but the read
  side still surfaces inference-shaped transcripts under no
  grounding fence. Required before `engineE.enabled: true`: port the
  grounding rule into the Engine E system prompt AND add an
  `agent_id` / engine attribution dimension to Mem0 records so
  Engine E's history is isolated from Engine A's.
- **`mem0ai` version skew in monorepo lockfiles.** Engine sublocks
  ([`agent_fleet/restate_analyst/uv.lock:970`](../../agent_fleet/restate_analyst/uv.lock)
  and [`agent_fleet/neo4j_expert/uv.lock:946`](../../agent_fleet/neo4j_expert/uv.lock))
  pin `mem0ai==2.0.1`; top-level
  [`uv.lock:1503`](../../uv.lock) pins `mem0ai==1.0.7`. Engines run
  2.0.1 (image builds from per-service locks), but anyone deduping
  the workspace could silently reintroduce 1.0.7 and resurrect the
  pre-v2 prompt regression. Resolve in a follow-up cleanup pass.
- **Document the v1.x → v2.x Mem0 prompt regression.** Mem0 2.0.1's
  default pipeline uses `ADDITIVE_EXTRACTION_PROMPT` (mines
  assistant turns and reframes them as user-attributed facts),
  superseding the v1-era `FACT_RETRIEVAL_PROMPT` assumption. Until
  Mem0 publishes a clean changelog noting this, paste the relevant
  excerpt into this repo (e.g. as a `docs/research/` note) so the
  next person doesn't re-inherit "stock Mem0 ignores assistant
  messages."
- **Revisit observability — see §5 prerequisites (a), (b), (c).**
- **`:DERIVED_FACT` gating authority — same owner as ADR-0006.**
- **Re-verification/staleness for `:DERIVED_FACT`.** If/when the
  subgraph is populated, a sampled re-read job becomes relevant.
  Defer until subgraph is non-empty.

## Out of scope

- The `routing_decisions` audit table (ADR-0015) — still
  unimplemented; separate concern, named as a §5 prerequisite but
  not built here.
- The predicate-registry drift between Neo4j and Weaviate
  (ADR-0006) — unchanged here.
- BAML-layer fact typing — BAML outputs are already strongly typed;
  the inference-as-fact problem was specific to Mem0's plaintext
  write path.
- A full migration off Mem0's storage model — unnecessary once
  world-state stops being routed to it. Mem0 with `infer=False`
  remains the per-caller raw-transcript substrate of the future §3
  preference store.

## Research artifacts (for later resurrection)

The 2026-06-04 decision rests on a discovery report and a
multi-perspective workflow review. Both are preserved outside the
repo for the next resurrector:

- **Discovery report:** `c:/tmp/adr0016_discovery.md` — answers to
  the 21-question questionnaire that informed r2's diagnosis,
  including live schema dumps, code citations with file paths and
  line numbers, the `ADDITIVE_EXTRACTION_PROMPT` finding, the
  Engine A / Engine E symmetry confirmation, and the Mem0
  `Mem0migrationsOllama` schema.
- **Multi-perspective workflow:** `wf_bd8a2124-ccd` transcript at
  `C:\Users\cnogr\.claude\projects\c--Users-cnogr-git-iagent-mesh-sdk\0bd43fcc-349d-444a-af78-c130e26bf9b6\subagents\workflows\wf_bd8a2124-ccd\` —
  four-reviewer panel (code-accuracy, architectural soundness,
  devil's-advocate steelman, operational) and synthesis. The
  workflow surfaced the strongest concrete arguments for and
  against each of Tier 0(a), 0(b), and §4 activation. Key findings
  folded into this ADR:
    - All five primary code citations in r2 verified accurate
      against the live repo.
    - `MEM0_ENABLED` does not exist in any `.py` file — only in
      this ADR's text. Disablement requires code work, not just
      helm.
    - §4(iii) read-time fence is a prompt convention with no
      runtime audit. The fence rule can silently decay.
    - §4(ii) NOOP-on-agreement defeats the Q9 re-confirmation
      cascade but is silent on concurrent multi-engine
      contradictions.
    - Engine E lacks Engine A's grounding rule and shares the
      collection — re-enable prerequisites named in Open Items.
    - Sandbox-clean ≠ production-safe; §4 may already be operationally
      required at prod scale.

These artifacts should be consulted by anyone activating §3, §4, or
revisiting the standing default under §5.
