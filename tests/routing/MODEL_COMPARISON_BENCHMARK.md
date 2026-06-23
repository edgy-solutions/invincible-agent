# Routing model comparison — benchmark record (2026-06-10/11)

Goal: compare per-call routing latency and matrix pass rate across
candidate Ollama models for engine-o's `/resolve` and
`/classify_predicate` endpoints. Frozen baseline:
[routing-baseline-v1](https://github.com/edgy-solutions/invincible-agent/releases/tag/routing-baseline-v1).

## Setup

- **ai1 (`192.168.1.126`)** = Strix Halo APU, shared unified DRAM.
  Hosts the agent-reasoning model (`gpt-oss-128k:120b`) pinned forever.
- **.188** = dedicated GPU server. Hosts the routing-comparison models
  + Mem0's `phi4-16k:14b`.
- All routing models pinned `keep_alive: -1`. Matrix harness:
  [scripts/phase1_stable_harness.sh](../../scripts/phase1_stable_harness.sh).
- `temperature: 0` enforced via clients.baml (commit `7ffd294` +
  baml_client regen `c93341f`).
- 11 queries × 5 runs = 55 cases per model.

## Result (sorted by accuracy)

| Model | Params | Host | Pass rate | Avg /resolve | Avg /classify | Avg total/query | Wall-clock/run |
|---|---:|---|---:|---:|---:|---:|---:|
| **gpt-oss-128k:120b** | 116.8B | ai1 | **55/55 = 100.0%** | 6.63s | 7.78s | **14.48s** | 155-165s |
| **gemma4-routing** (gemma4:e4b base) | 8B | ai1 | 54/55 = 98.2% | 10.38s | 15.02s | 25.47s | 270-289s |
| **gemma4-routing** (gemma4:e4b base) | 8B | .188 | 51/55 = 92.7% | 5.53s | 7.41s | **13.03s** | 139-150s |
| **nemotron-3-nano-routing** | 4.0B | .188 | 41/55 = 74.5% | 1.79s | 2.23s | 4.10s | 40-47s |
| **lfm2_5-routing** (MoE) | 8.5B | .188 | 27/55 = 49.1% | 3.39s | 4.14s | 7.60s | 65-88s |
| **ministral-3-routing** | 3.8B | .188 | 17/55 = 30.9% | 1.17s | 1.16s | 2.41s | 18-27s |

## Read

**The accuracy/speed trade is sharply non-linear.** Below
~92% accuracy, the matrix breaks deterministically on multiple cases
per run. Above ~92% — only gpt-oss on ai1 and gemma on .188 — the
matrix is usable for production routing.

**gemma on ai1 is the worst real option** (98.2% but 2× slower than
baseline). Memory contention with the 97GB gpt-oss pin starves the 8B
model on Strix Halo's shared DRAM. Same model on dedicated GPU
(.188) is fastest but loses 7.3% accuracy on a deterministic miss
(`What columns does orders_raw have?` → subject resolves UNKNOWN every
time).

**The smaller models trade too much accuracy.** Ministral-3 (3.8B)
runs 6× faster than gpt-oss but loses 69% accuracy. lfm2_5 MoE and
nemotron-3-nano lose 51% and 26% respectively. Failures spread across
many different queries, not concentrated on a deterministic miss —
characteristic of inadequate reasoning capacity, not a single
prompt-engineering gap.

## Decision: revert to gpt-oss-128k:120b on ai1

The 1.5s/query latency win from gemma on .188 isn't worth the 7.3%
accuracy hit for a single deterministic miss on a query pattern users
will hit (column queries). Routing accuracy is more product-critical
than routing latency at the matrix's prompt sizes (~3-8k tokens,
single-pass JSON output).

**Real latency leverage is structural, not model size**:
- The combined `ClassifyRoute` BAML function (single LLM call producing
  both subject and verb, instead of two separate `ClassifyDomainIntent`
  + `ClassifyPredicate` calls) would cut total per-query latency
  ~50% — much bigger win than any model swap.
- Tighter verb descriptions reduce LLM ambiguity → higher confidence
  on first pick → no abstention loops.

## Footgun discovered along the way

`agent_fleet/llm_utils.py:init_baml_client` overrides the BAML Ollama
client at engine-o startup, using `SMOLAGENTS_MODEL` (not
`OLLAMA_MODEL`) as the model name. Engine-o doesn't run smolagents but
still uses this shared init code. Until this is renamed/fixed, any
attempt to swap engine-o's routing model via `OLLAMA_MODEL` (the
obvious env var name) silently fails — BAML keeps using whatever
`SMOLAGENTS_MODEL` is. Several of this session's "gemma swapped"
verifications were false positives until this was caught.

**Follow-up**: rename to read `OLLAMA_MODEL` first with
`SMOLAGENTS_MODEL` as fallback, so the obvious env-var name works for
engines that aren't smolagents.
