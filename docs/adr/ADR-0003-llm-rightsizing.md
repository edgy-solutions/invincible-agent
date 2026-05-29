# ADR-0003 — Right-size LLMs per workload class on the agent mesh

**Status:** Accepted
**Date:** 2026-05-29
**Deciders:** Platform team
**Related:** [ADR-0001](ADR-0001-mem0-llm-decouple.md) (specific
instance), [ADR-0002](ADR-0002-mem0-monkeypatches.md) (mem0 patches
that unblocked this work)

## Context

[ADR-0001](ADR-0001-mem0-llm-decouple.md) decoupled mem0's internal LLM
from the agent reasoning LLM. The case it makes — structured fact
extraction is a fundamentally different workload from open-ended agent
reasoning, and they deserve different model classes — is not unique
to mem0. The same shape recurs across the fleet:

| Engine / call | Workload class | What we currently use |
|---|---|---|
| Engine A `run_smolagent` CodeAgent loop | open-ended reasoning + tool use | `SMOLAGENTS_MODEL` (gpt-oss-128k:120b in prod) |
| Engine E `run_smolagent` Cypher loop | open-ended reasoning + tool use | `SMOLAGENTS_MODEL` |
| Engine O `b.ClassifyDomainIntent` (BAML) | structured classification | `SMOLAGENTS_MODEL` |
| Engine O `b.DecomposeQuery` (BAML) | structured planning | `SMOLAGENTS_MODEL` |
| Engine O `b.ClassifyLegacyTable` (BAML) | structured classification | `SMOLAGENTS_MODEL` |
| Engine F `b.DesignUI` (BAML) | structured archetype mapping | `SMOLAGENTS_MODEL` |
| mem0 fact extraction (Engine A, E) | structured NER + paraphrasing | `MEM0_LLM_MODEL` (per ADR-0001) |
| Embedding (Engine A, E, O, W) | vector encoding | hardcoded `nomic-embed-text` |

Six of those eight rows are BAML calls or smolagents prompts that ask
for **structured output from a short prompt**. Only the two
`run_smolagent` rows are open-ended reasoning. Yet everything is
pointed at the same `SMOLAGENTS_MODEL` env var, which production sets
to the largest reasoning model available.

This is wrong in three ways, all for the same reasons we hit in mem0:

1. **Latency.** Structured-output calls block the agent loop or the
   request handler; a 120B reasoning model's 30–60s per call dominates
   total response time even when the actual task is "extract three
   fields from this short message."

2. **Stability.** Reasoning models on Ollama's `ollama-engine` runner
   have known issues with structured-output prompts (see ADR-0001 and
   the runner-crash trace it documents). BAML calls and mem0's
   extraction prompts are exactly the workload class that triggers it.

3. **Cost / right-sizing.** With 10×H100 (soon H200), the deployment
   has plenty of room to host multiple model classes simultaneously.
   The Strix Halo unified-memory dev box already demonstrates the
   pattern: `gpt-oss-128k:120b` (70 GB) + `nomic-embed-text` (604 MB)
   + room for a `gemma4:31b` (18.5 GB) all live in the 94 GB pool
   simultaneously, no swapping.

## Decision

The fleet adopts a **workload-class routing pattern** for LLMs:

- Each *workload class* gets its own env var.
- Engine code reads the workload-class env var, with a fallback chain
  to `SMOLAGENTS_MODEL` and then to a provider-appropriate default.
- Deployment surfaces (Helm `agentFleet.env`) set the model per class,
  not per engine.

Initial classes and env vars:

| Class | Env var | Role |
|---|---|---|
| Agent reasoning loop | `SMOLAGENTS_MODEL` | Open-ended tool-use loops; smolagents `CodeAgent` |
| Structured output | `BAML_LLM_MODEL` *(to be added)* | BAML calls in Engine O, Engine F, etc. |
| mem0 fact extraction | `MEM0_LLM_MODEL` | Established by ADR-0001 |
| Embedding | `EMBEDDER_MODEL` *(to be added)* | Vector encoding; currently hardcoded `nomic-embed-text` |

For dev (single Ollama on ai1) the assignment looks like:

```
SMOLAGENTS_MODEL = gpt-oss-128k:120b      # agent reasoning
BAML_LLM_MODEL   = gemma4:31b             # structured output
MEM0_LLM_MODEL   = gemma4:31b             # fact extraction
EMBEDDER_MODEL   = nomic-embed-text       # embeddings
```

For production (10×H100/H200) the same env vars route to potentially
different models per workload class, with all models warm in parallel
across the cluster.

This ADR sets the **pattern**; the rollout is incremental:

- **Phase 1 (done):** `MEM0_LLM_MODEL` (ADR-0001).
- **Phase 2 (next):** `BAML_LLM_MODEL`. Plumb through
  `agent_fleet/llm_utils.py::init_baml_client`. Highest-value lift after
  mem0 because every BAML call in Engine O / Engine F is structured.
- **Phase 3 (later):** `EMBEDDER_MODEL`. Lower priority because
  `nomic-embed-text` is universally adequate and the hardcoded value
  works.

## Consequences

**Wins:**
- Each workload runs on the model class that fits it. Latency wins on
  the structured-output path are large (the Step 3 e2e validation
  measured 42–112s for a single mem0 call against the 120B reasoning
  model vs ~5–10s with the 30B-class model in the same hot path).
- Stability wins: structured-output workloads stop hitting the
  reasoning-model + JSON output failure mode that crashed Ollama under
  load (ADR-0001 documents the trace).
- Cost wins on the production cluster: reasoning inference budget is
  reserved for actual reasoning, freeing the 120B lane for the work
  that needs it.
- Future model upgrades can be staged per workload class — switch one
  env var to test a new structured-output model without disturbing the
  agent reasoning loop.

**Costs:**
- More env vars to set. Mitigated by sensible fallback chains —
  unset workload-class vars fall back to `SMOLAGENTS_MODEL`, so deploys
  that don't care behave as today.
- More models warm at runtime. On the dev unified-memory box (94 GB)
  this is fine; on production hosts it requires capacity planning.
  The natural place to surface that planning is in Helm
  `agentFleet.env` comments noting the memory footprint per class.
- Ops complexity: when a workload misbehaves, the diagnostic question
  "which model is this even using?" gets a touch harder. Mitigated by
  logging the resolved model name at handler entry (already done in
  `llm_utils.get_smolagent_model` via the `LiteLLMModel` constructor
  echo; should be added for BAML init too in Phase 2).

## Alternatives considered

- **One `SMOLAGENTS_MODEL` for everything.** Status quo before ADR-0001.
  Rejected for the reasons that ADR documents — applies the same to
  BAML and other structured calls.

- **Per-engine env vars** (`ENGINE_O_LLM_MODEL`, `ENGINE_F_LLM_MODEL`).
  Rejected. The right axis is workload class, not engine identity. The
  same BAML call type fired from two different engines wants the same
  model; the same engine making both reasoning *and* structured calls
  wants both models.

- **Hardcode model choices in code.** Rejected. Removes deploy-time
  flexibility; couples the code repo's release cycle to model
  selection. Env vars decouple the two.

- **Let BAML's `ClientRegistry` handle this internally.** BAML can
  route to multiple clients per call. Useful eventually, but adds
  BAML-specific configuration that doesn't generalize to mem0 or the
  smolagents path. The env-var pattern works uniformly across all
  LLM-driving libraries we use.

## Indicators for revisiting

- A single model becomes good enough at both reasoning *and*
  structured output that the latency, stability, and cost arguments
  flip. GPT-5 / Claude-Opus-equivalent local models with stable
  Ollama harnesses would qualify. At that point collapse the workload
  classes back into `SMOLAGENTS_MODEL` and delete the per-class env
  vars.
- We move off Ollama entirely (e.g., vLLM with proper structured-output
  guards, or a managed API where the structured-output failure mode
  doesn't exist). The stability argument weakens; only latency and
  cost remain.
- BAML adds first-class workload-class routing in `ClientRegistry`
  that subsumes our env-var convention. At that point migrate to it
  for BAML calls specifically; mem0 stays on its own env var unless
  mem0 grows a similar mechanism.
