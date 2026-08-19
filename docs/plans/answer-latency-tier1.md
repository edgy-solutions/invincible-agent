---
id:         answer-latency-tier1
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    DECOMPOSED 2026-08-19 (n=5 + isolated hop probes). Tier-1 answer is 262.0s +/- 10.6 (the filed 324.9s was a ~6-sigma outlier, likely a cold 64.7GB model load). >99% is sequential LLM generation; ALL data/graph work totals 2.3s. Root cause: a 116.8B REASONING model at ~33 tok/s where 95-97% of generated tokens are hidden reasoning, called ~sequentially. Largest phase is composing (102.5s), which the original filing never named.
---

# Tier-1 answer latency — 324.9s for one metadata field

**Measured 2026-08-18**, as a by-product of the `ui-renders-honest-failure-as-answer`
success-arm witness. This is not an estimate and not a cold-start anecdote: it is the
instrumented phase timeline of a real question asked by a real user through cortex-bff on
sandbox.

## The measurement

Question: *"who owns the publog p_cage table?"* — asked as `alice`, answered correctly. The
answer is **a single metadata field** (and in this case, the honest absence of one).

| t (s) | Δ | phase |
|------:|----:|---|
| 3.4 | — | `understanding` started |
| 12.2 | **8.8** | `understanding` completed |
| 89.2 | **77.0** | `locating` completed (`create_task_plan`) |
| 89.2 | 0.0 | `choosing_action` completed |
| 121.9 | 32.7 | `route_decision` emitted (`idp#Table` @ 0.98) |
| 237.2 | **148.0** | `retrieving` completed (`execute_subtask[task_0]`) |
| 291.2 | 54.0 | `composing` — `synthesize_stateful` |
| 302.4 | 11.2 | `composing` — `generate_ui_payload` |
| 324.9 | 22.5 | `composing` completed → final payload |

**Total 324.9s.** Two phases own 69% of it: `locating` (77.0s) and `retrieving` (148.0s).

## Why this is a packet and not a footnote

It was found in another packet's margins, which is exactly where a latency fact goes to die.
Two independent reasons it needs its own line on the board:

1. **Demo-room liability.** Five and a half minutes of a progress spinner for a question a
   human would expect to be near-instant. No amount of correct answering survives that in a
   live demonstration.
2. **A standing user-experience fact**, not a one-off. Nothing in the trace suggests a cold
   start or a retry: the phases ran once, in order, and completed.

## What is NOT yet known (do not skip this)

The breakdown says WHERE the time goes, not WHY. Specifically un-investigated:

* **`locating` 77.0s** — this is plan construction (`create_task_plan`). Whether that is LLM
  latency, ontology/Weaviate recall, or the compat-walk is unmeasured.
* **`retrieving` 148.0s** — `execute_subtask` against the catalog. Whether the cost is the
  engine call, the LLM inside it, or the instance-resolution fan-out (which has per-provider
  timeout budgets) is unmeasured.
* **Sandbox LLM hosts are modest.** Some of this is substrate, not architecture, and a naive
  read that blames the router would be premature. **Measure the phase internals before
  attributing.**

Per [[decide-the-meaning-before-the-measurement]]: decide what "acceptable Tier-1 latency"
IS before optimising toward a number nobody agreed on.

## Adjacent, deliberately not conflated

* `instance_resolved: false` on this same run — a CORRECTNESS question that belongs to the
  instance-resolution layer, not a latency one. Different packet, different owner.
* The 89.6 MB `.collect()` payload item — a DIFFERENT path. This question was a metadata read
  and never touched the parquet, so this 324.9s says **nothing** about that item either way.


---

# DECOMPOSITION — measured 2026-08-19 (n=5 full runs + isolated hop probes)

The filing above warned: *"the breakdown says WHERE the time goes, not WHY … measure the
phase internals before attributing."* Done. Nothing below is inferred from a single run.

## Correction 1 — the headline number was an outlier

**262.0s mean, stdev 10.6 (4% CV), n=5:** 256.4 / 249.4 / 261.8 / 277.8 / 264.8.

The filed **324.9s is ~6 sigma above this mean** and should not be quoted again. It was the
first run against an idle host and the model is **64.7 GB resident**; a cold load is the
leading candidate. *The n=1 lesson recurred exactly as predicted — and it was MY number.*

## Correction 2 — the largest phase was never named

| phase | mean | min | max | stdev | % of total |
|---|---:|---:|---:|---:|---:|
| understanding | 8.6 | 8.5 | 8.7 | 0.1 | 3.3% |
| locating | 59.7 | 54.2 | 72.9 | 7.8 | 22.8% |
| retrieving | 91.3 | 79.0 | 117.4 | **15.1** | 34.8% |
| **composing** | **102.5** | 97.6 | 113.6 | 6.6 | **39.1%** |
| TOTAL | 262.0 | 249.4 | 277.8 | 10.6 | |

The original filing named *77s locating, 148s retrieving* and **never mentioned composing**,
which is in fact the single largest consumer. Turning an already-known one-field fact into a
card costs more than finding it.

## The answer to the question the item asked

> *how much is per-call LLM latency times call count, versus infrastructure waits, versus
> actual data movement?*

**Essentially all of it is per-call LLM latency times call count. Data movement is under 1%.**

| work | measured | share of 262.0s |
|---|---:|---:|
| Neo4j compat-walk (`/find_compatible_verbs`) | **0.08s** | 0.03% |
| DataHub catalog read (`/query_metadata`) | **2.19s** | 0.84% |
| **all non-LLM work** | **~2.3s** | **~0.9%** |
| everything else | ~259.7s | ~99.1% |

Isolated hop probes (n=4 each, ranges tight enough to trust):

| hop | mean | range |
|---|---:|---|
| `/route_intent` | 6.81 | 6.73–6.89 |
| `/resolve` | 12.23 | 11.65–12.67 |
| `/classify_predicate` | 8.24 | 7.50–8.52 |
| `/plan` | 8.15 | 7.62–9.56 |
| `/find_compatible_verbs` | **0.08** | 0.06–0.09 |
| D `/query_metadata` | 2.19 | 1.90–2.74 |
| D `/resolve_instance` | 2.83 | 2.56–3.05 |

**The graph traversal — the part that intuitively looks expensive — is 80 milliseconds.**

## WHY each call is slow — the root cause, measured

`OLLAMA_MODEL = gpt-oss-128k:120b` (**116.8B params, 64.7 GB resident**) on ai1, one host,
sustaining **~33 tok/s** (5 tok -> 0.80s; 100 -> 3.21s; 300 -> 8.95s).

**And it is a REASONING model, which is the real finding.** Measured across three probe
shapes, generated tokens are overwhelmingly hidden chain-of-thought, not answer:

| probe | wall | answer tok | reasoning tok | reasoning % |
|---|---:|---:|---:|---:|
| trivial JSON echo | 2.20s | 2 | 59 | **96.7%** |
| classify into 3 classes | 2.70s | 4 | 73 | **94.8%** |
| pick 1 of 3 verbs | 4.14s | 6 | 121 | **95.3%** |

A `{"ok":true}` echo costs **158 completion tokens for 2 tokens of answer**. Every small,
deterministic, structured routing decision pays a full chain-of-thought tax. The response
carries a separate `reasoning` field, so this is the model's own thinking output — not
prompt design.

## Named candidate cause per phase >= 30s

* **locating, 59.7s** — four sequential BAML calls measured at **35.5s combined**
  (`route_intent` + `resolve` + `classify_predicate` + `plan`), plus a 0.08s graph walk.
  **~24s remains UNATTRIBUTED** (supervisor-side orchestration and/or calls not probed).
  *Stated as a gap, not smoothed over: an earlier draft of this claimed a 95% match, and
  that was an artifact of contaminated probes — see the method note.*
* **retrieving, 91.3s** — the catalog read is **2.19s, i.e. 2.4% of the phase.** The other
  ~89s is Engine A's smolagents ReAct loop, `SMOLAGENTS_MODEL = gpt-oss-128k:120b`, each
  turn paying the reasoning tax. **Highest variance of any phase (stdev 15.1)**, which is
  what a variable turn count looks like.
* **composing, 102.5s** — three sub-steps (`synthesize_stateful` ~45s, `generate_ui_payload`
  ~25s, final render ~33s). All LLM, all operating on a fact already in hand.

## Method note — a contamination I caused and corrected

The FIRST hop probes ran **while the n=5 runs were in flight**, against the same single
Ollama host. `/route_intent` then measured 6.9s and 25.8s — a 3.7x spread I nearly filed as
natural variance. Re-measured in isolation it is **6.73–6.89s**. The spread was entirely
self-inflicted queueing. Every hop number above is from the isolated pass. Recorded because
the contaminated numbers were plausible and would have supported a wrong conclusion about
where locating's time goes.

## What is still NOT known

* The **~24s unattributed inside locating**. Needs engine-side instrumentation, not probing.
* **LLM call COUNT per run** — no Langfuse and no OTEL on sandbox, so calls could not be
  counted directly; the totals here are wall-clock, not call-counted.
* Whether concurrency would help at all: **one Ollama host, one loaded model**, so parallel
  calls likely serialize. NOT measured — measuring it requires load that would perturb
  everything else. This matters, because "parallelise the routing calls" is the obvious fix
  and it may buy nothing.

**No fixes attempted, per the assignment.** The fix list is a morning decision.
