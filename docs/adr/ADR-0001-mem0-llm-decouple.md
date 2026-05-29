# ADR-0001 — Decouple mem0's internal LLM from the agent reasoning LLM

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:** [ADR-0003](ADR-0003-llm-rightsizing.md) (generalization)

## Context

The fleet's smolagents-based engines (Engine A restate_analyst, Engine E
neo4j_expert, Engine DA data_analyst, Engine W weaviate_expert, etc.)
all use a single env var, `SMOLAGENTS_MODEL`, to select the LLM they
drive through smolagents `CodeAgent`. Until this decision, `mem0`'s
internal LLM — used for **structured fact extraction** during `m.add()`
and for query rewriting during `m.search()` — also used the same
`SMOLAGENTS_MODEL`, by reading it inside
`agent_fleet/utils/mem0_utils._build_mem0_memory()`.

Three things forced a re-evaluation when we tried the full /analyze
flow end-to-end against the d4-dev Ollama (ai1, gpt-oss-128k:120b):

1. **Latency on the hot path.** `m.add()` is called after every agent
   response (to persist the turn into memory); `m.search()` is called
   before every agent invocation (to inject relevant memories into the
   system prompt). With `SMOLAGENTS_MODEL=gpt-oss-128k:120b` and a
   reasoning model on an APU, `m.add()` alone clocked 42–112 seconds in
   our tests. Multiplied across a user session, this is a UX cliff
   before any agent reasoning starts.

2. **Stability.** Engine A's first /analyze attempt crashed Ollama's
   model runner subprocess (Go panic in `runner.go:956`, exit status 2)
   mid-call when mem0 issued its structured-output prompt for fact
   extraction. gpt-oss is a *thinking* model and Ollama's new
   `ollama-engine` runner for reasoning + JSON output is bleeding-edge;
   mid-sized non-reasoning models (gemma, qwen, llama3) have been doing
   structured output reliably for over a year. The crash poisoned
   Ollama's GPU discovery state for 27 minutes; pods restarted in a
   loop.

3. **Right-sizing.** mem0 fact extraction is structured NER +
   paraphrasing of a short conversation turn. A 120B reasoning model
   adds no quality vs a 30B-class model for this task; on the H100
   cluster (soon H200) it also wastes inference budget on a workload
   that fits comfortably in a smaller lane.

## Decision

`agent_fleet/utils/mem0_utils._build_mem0_memory()` now reads its LLM
from a new env var, `MEM0_LLM_MODEL`, with a resolution chain:

```
MEM0_LLM_MODEL  →  SMOLAGENTS_MODEL  →  provider-appropriate default
```

The embedder selection is unchanged (`nomic-embed-text` for the Ollama
provider). Only the LLM used for mem0's structured calls is decoupled.

For the dev cluster we set `agentFleet.env.MEM0_LLM_MODEL = "gemma4:31b"`
(or whichever JSON-stable mid-sized model is available); production
deployments override the same env var. `SMOLAGENTS_MODEL` continues
to point at the agent reasoning model.

Backward-compatible: deploys that don't set `MEM0_LLM_MODEL` behave
identically to before.

## Consequences

**Wins:**
- mem0 calls drop from ~30–120s to ~3–10s against a 30B-class model.
- No more Ollama runner panics under mem0's structured prompt.
- Production inference budget for the 120B reasoning model is reserved
  for actual agent reasoning, not background extraction.
- Engine A's `/analyze` round-trip becomes practical under default
  Restate timeouts (validated: 242s end-to-end with the decouple in
  place vs 300s timeout without).

**Costs:**
- Two models must be available to each engine pod (or to the Ollama
  service it talks to). On the d4-dev unified-memory box (94 GB) both
  models can stay resident simultaneously. On larger production hosts
  this is trivial; on smaller dev rigs operators need to either accept
  swap latency or pre-pull both.
- Env var sprawl: this is the first per-workload `_LLM_MODEL` override.
  [ADR-0003](ADR-0003-llm-rightsizing.md) generalizes the pattern.

## Alternatives considered

- **Keep mem0 coupled to `SMOLAGENTS_MODEL`.** Rejected. The latency
  argument alone is fatal for user-facing chat; the stability argument
  makes it operationally fragile.

- **Switch `SMOLAGENTS_MODEL` globally to a 30B-class model.** Rejected.
  mem0's task is small and structured; the agent's reasoning task is
  not. Sizing for mem0 means under-sizing for the agent.

- **Disable mem0's LLM entirely (mem0 in "no-inference" mode).**
  Investigated; mem0 0.1.x does not cleanly support this — its
  add/search pipelines call the LLM unconditionally for fact extraction
  and entity linking. Patching mem0 out of the loop would be a larger
  surgery than this env-var change.

- **Use a per-engine env var (`ENGINE_A_LLM_MODEL`, …).** Rejected.
  The workload class — *structured-output fact extraction* — is what
  matters, not the engine identity. mem0 lives in two engines (A and E)
  and both use the same model. See [ADR-0003](ADR-0003-llm-rightsizing.md).

## Indicators for revisiting

- mem0 ships a stable interface for disabling its internal LLM (e.g.,
  a `Memory(llm=None)` mode), in which case we may stop configuring it
  entirely for one or both engines.
- The Ollama `ollama-engine` runner becomes stable for reasoning +
  structured output, *and* benchmarks show the 120B reasoning model has
  acceptable latency on the target hardware for mem0's task.
- A future mem0 release inverts the prompt design (e.g., embeds the
  fact-extraction prompt in a way that benefits from reasoning models),
  changing the right-sizing math.
