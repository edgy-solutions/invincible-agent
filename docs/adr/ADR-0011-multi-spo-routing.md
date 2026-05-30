# ADR-0011 — Multi-SPO routing in NL (design exploration)

**Status:** Proposed
**Date:** 2026-05-30
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) — the predicate
    graph already supports multi-hop traversal via `/find_path`; this
    ADR considers how an NL query maps to one.
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — single-SPO
    routing (Step F'.6) is the foundation this builds on.
  - [ADR-0008](ADR-0008-routing-fallback-policy.md) — the fallback
    policy will need a `"path_break"` reason if multi-SPO lands.

## Context

ADR-0009 Step F'.6 handles **single-SPO** routing well: NL → Weaviate
hybrid → one predicate → one engine call. The supervisor's
`DecomposeQuery` adds **parallel decomposition** — break a query into
N independent subtasks, fan them out, fan in the results.

What neither of those handle is **chained SPOs** — a single NL query
that implies a sequence where step N's output becomes step N+1's
input. Three shapes of multi-SPO query are worth distinguishing:

1. **Parallel independent SPOs** — *"Diagnose the vibration on turbine
   3 **and** list the safety procedures for the maintenance bay."*
   Two SPOs, no data dependency. `DecomposeQuery` already covers
   this.

2. **Sequential, data-dependent** — *"Diagnose the vibration on
   turbine 3 **and then** look up safety procedures for the failed
   component."* Step 2's input mentions something step 1 produces
   (`FaultReport.failed_component`). The supervisor must execute
   step 1 first, extract the field, then route step 2. Today: not
   handled at the supervisor layer.

3. **Discovery-driven** — *"Help me fix the vibration on turbine 3."*
   The user names an end state and an observation; the system has to
   figure out the chain (diagnose → identify part → look up procedure
   → maybe order part). Requires graph traversal from observation
   to artifact. Today: not handled at all.

The capability to traverse multi-hop predicate paths already exists in
Engine O — [`/find_path`](../../agent_fleet/ontology_service/main.py)
takes `(start_uri, end_uri, max_hops, cost_class_filter,
exclude_human_approval)` and returns a chain. Nothing currently calls
it; we built the substrate but the consumer side is empty.

This ADR is a **decision-deferred design exploration**, not an
implementation commitment. The user direction is to focus on testing
what we have (single-SPO + parallel decomposition) before scaling
complexity. The job here is to capture the design space legibly so
the future decision is informed instead of relitigated.

## Decision

**Decision deferred.** The current single-SPO + parallel-fan-out path
covers a substantial fraction of real queries; we want operational
data on it before deciding whether multi-SPO routing earns its
complexity. This ADR documents the design space and pre-commits to
the *shape* of the eventual decision, not the answer.

When we revisit, the question on the table will be:

> **Where does multi-SPO chain awareness live, and which subset of
> the three flavors above is worth building for?**

Pre-committed framing:

- **Intra-domain chains stay in engines.** Engine E's smolagents loop
  already chains `get_graph_schema → execute_cypher →
  search_manual_text`. That's multi-step within one engine on one
  domain's knowledge. The registry sees the *outer* verb
  (`mesh:queryKnowledgeGraph`); internal tool composition is the
  engine's business. No supervisor change is contemplated for this.
- **Cross-engine chains, if we build them, route through `/find_path`.**
  The supervisor — not an LLM, not a hand-coded plan — uses the
  predicate graph to find the chain. Same deterministic-routing
  posture as ADR-0009 Step F'.6.
- **NL → (start_uri, end_uri) resolution is the new piece.** Either
  in Engine O (new endpoint) or in the supervisor (post-process
  `ExtractIntent.entity_refs` through `/resolve`). Open question
  below.

## Design space — where multi-SPO awareness can live

| Layer | What it does | Strengths | Weaknesses |
|---|---|---|---|
| **Inside engines** (smolagents tool loop) | Engine composes tool calls internally; the registry sees only the outer verb | Already works; LLM has full context; no supervisor changes; engine team owns its own composition | Cross-engine chains impossible (Engine A can't call Engine E via a tool); engine-internal composition is opaque to the predicate graph |
| **Supervisor via extended `DecomposeQuery`** | LLM splits into chained subtasks with data-dependency annotations | Familiar; fan-out already exists | LLM has to invent verb assignments without seeing the graph; re-introduces the constraint-loss risk we fixed in ADR-0009 Step F'.6 |
| **Supervisor via `/find_path`** | Graph traversal from start_uri to end_uri | Deterministic; uses the registry as source of truth; substrate already exists | Requires NL → (start, end) resolver; per-step `sub_query` synthesis is its own design question |
| **Engine O extended with `/route_path`** | LLM identifies start/end entity hints, supervisor calls `/find_path` | Bridges NL and graph; constrained by what's registered | One more LLM endpoint to maintain; depends on `/resolve` quality |

The honest verdict the deferral is built on: **engines already
handle intra-domain chains; cross-engine chains are real but
unmeasured.** Building cross-engine chain routing before we know how
often it matters is the kind of speculative complexity ADR-0009 just
finished cleaning up. Wait for the signal.

## Sketch of an implementation (for when we decide)

This is the shape the ADR pre-commits to *if* we build cross-engine
multi-SPO. Captured here so the future code change has a clear
starting point instead of a blank page.

1. **`ExtractIntent` keeps its current `{mode, entity_refs}` output.**
   No new fields. Multi-SPO awareness is added downstream, not in
   the intent extractor.

2. **New supervisor helper `_resolve_predicate_path`**:
   - Call `/resolve` for each `entity_ref` in parallel.
   - If ≥ 2 entities resolve to ontology URIs, attempt
     `/find_path(start_uri=…, end_uri=…)`.
   - If `/find_path` returns a chain, execute it step-by-step.
   - If `/find_path` returns no path OR only 1 entity resolved, fall
     back to single-hop `/search_predicates` (existing F'.6 behavior).

3. **NL → (start, end) disambiguation**:
   - Heuristic first: the entity_ref that anchors the *observation*
     (Symptom, Dataset, Document) is the start; the one that names
     the *desired artifact* (SafetyDocument, FaultReport, Procedure)
     is the end. Built from URI-type metadata on the resolved
     OntologyClass nodes.
   - If the heuristic is ambiguous, ask the LLM to pick — constrained
     by the resolved URIs. New BAML function: `PickPathEndpoints`.

4. **Per-step `sub_query` synthesis**:
   - Template-first: `"{verb} applied to {previous_step.output} for
     {original_user_query}"`. Cheap, deterministic, lossy.
   - LLM-second only if the template doesn't produce good results
     in practice. New BAML function: `SynthesizeStepQuery`.
   - Don't build both at once; ship the template, measure quality,
     escalate to LLM only if needed.

5. **Chain-break fallback (ADR-0008 extension)**:
   - If step K of an N-step chain returns FAILED, the supervisor
     escalates to Engine A with `fallback_reason="path_break"`,
     `fallback_step=K`, `partial_results=[results_0..K-1]`,
     `intended_path=[step descriptions]`.
   - Engine A's prompt preamble grows a third branch: "you are
     completing a partially-failed multi-step chain; here's what's
     been gathered so far."

6. **New Dagster op `execute_chain`** alongside the existing
   `execute_subtask`. The supervisor picks one based on
   `_resolve_predicate_path`'s return: single-hop → `execute_subtask`
   (existing); multi-hop → `execute_chain` (new).

7. **Telemetry**:
   - `predicate_chain_executed_total{hops="N"}` counter.
   - `predicate_chain_break_total{step="K", reason=…}` counter.
   - Same structured-log pattern ADR-0008 uses.

## Consequences (of deferring)

**Wins of waiting:**

- Operational data on single-SPO + parallel decomposition tells us
  which multi-SPO flavor (sequential vs discovery) actually shows up.
  Maybe one of them dominates and the other can be skipped.
- The ADR-0008 fallback already catches multi-SPO queries that
  single-SPO can't handle — they route to Engine A as generalist
  and get a useful (if uncertain) answer. So the failure mode of
  "we don't have multi-SPO" is "the user gets a generalist response"
  rather than a hard error.
- Avoids the trap of building chain routing on speculation and
  having to retrofit it once real queries inform the design.

**Costs of waiting:**

- Sequential multi-SPO queries today get either decomposed into
  parallel (DecomposeQuery may try to fan-out a query that needs
  threading, producing worse results) or fall through to Engine A
  as generalist (which the smolagents loop can sometimes handle
  internally if the tools are right). Neither is great; both are
  acceptable v1 behavior.
- The empty consumer side of `/find_path` is technical debt — code
  that exists but is dead. Tolerable as long as the ADR documents
  the intent.

## Alternatives considered

- **Build chain routing now, pre-empt the demand.** Rejected per the
  deferred-decision posture. Build for what we've measured, not what
  we predict.
- **Push everything to engine-internal smolagents loops.** Rejected
  as a *complete* answer because cross-engine chains genuinely can't
  happen at the engine level — Engine A can't call Engine E via a
  tool. But this is the right answer for intra-domain chains, and
  it's the v1 fallback (Engine A as generalist absorbs what it can).
- **Use `DecomposeQuery` for chained subtasks too — add data-dependency
  annotations to its output.** Rejected as an architectural choice
  because it pushes graph-traversal semantics into an LLM call.
  ADR-0009 Step F'.6 just argued that an embedding model does the
  matching job; the same logic says graph traversal should use the
  graph (`/find_path`), not an LLM.
- **Always try `/find_path` first** (and fall back to single-hop on
  no path) **vs only when ExtractIntent flags a multi-step query**.
  No decision needed for the deferral, but flagged as the load-bearing
  choice when we revisit.

## Open questions to settle when we revisit

1. **Where does the (start_uri, end_uri) picker live?** Engine O with
   a new endpoint vs. supervisor post-processing of `entity_refs`.
2. **Should the supervisor *always* try `/find_path` first** or only
   when an LLM hint says multi-step? The first wastes a Cypher call
   per query; the second adds an LLM-judgment failure mode.
3. **Per-step `sub_query` — template or LLM?** Template is simpler;
   LLM is more natural. Likely a measurement-driven choice.
4. **Chain partial-success policy** — fallback after K successful
   steps vs. hard-fail vs. per-step retries.
5. **Are entity-driven chains common enough in practice** to justify
   the design? The whole reason for deferring is to gather this data.

## Indicators for revisiting

- **Real user queries** that consistently fail single-SPO routing and
  trip ADR-0008's `low_confidence` fallback because they're shaped
  as chains. If `predicate_fallback_total{reason="low_confidence"}`
  has a strong chain-shape signal in the captured query text, that's
  the call to build this.
- **Engine A as generalist starts dominating** specifically on
  multi-noun queries. Same signal, different angle.
- **`/find_path` gets called by something** (a workflow author, a
  manual operator tool, a future ADR's component) — once it has a
  consumer, the question of "should it also serve NL routing"
  becomes natural to revisit.
- **A user-facing requirement explicitly asks for chained reasoning
  visibility** (e.g., "show me the diagnostic chain"). At that point
  the chain becomes a feature, not just a routing optimization.
- **Engine inter-domain coupling becomes operationally common** (one
  engine wants to feed another) — that's the cross-engine chain case
  asking to be promoted to a first-class supervisor capability.

## Non-goals for this ADR

- **Specifying the BAML signature** for any of the speculative
  endpoints (`PickPathEndpoints`, `SynthesizeStepQuery`,
  `/route_path`). Premature; locks in choices before measurement.
- **Picking the chain-execution Dagster topology**. The "new op
  `execute_chain`" framing above is a sketch, not a commitment —
  could be a different shape (e.g. a single op that iterates
  internally).
- **Capturing intra-engine tool composition rules.** Engines own
  that; the registry sees only the outer verb. Not this ADR's
  business.
