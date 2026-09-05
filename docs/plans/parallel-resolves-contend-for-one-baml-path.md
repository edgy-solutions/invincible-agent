---
id:         parallel-resolves-contend-for-one-baml-path
status:     open
owner:      unassigned — MEASUREMENT FIRST, no fix until the chain is timed
blocked-on: a measured distribution of `/resolve` latency under N concurrent subtasks
repo:       invincible-agent
ruled-by:   ADR-0019 Contract B (an ungrounded subject goes to the generalist — which is what makes a timeout cost the whole answer)
code-site:  src/iagent/defs/dynamic_supervisor.py:329 (`/resolve`, read timeout=30), agent_fleet/ontology_service/main.py (the BAML calls on the resolve path), the fan-out in `create_task_plan` / `execute_subtask`
summary:    Two parallel subtasks post `/resolve` to engine-o simultaneously. Engine O's BAML calls run 8–30s against Ollama; the supervisor's read timeout is 30s. Measured 2026-09-04: one subtask timed out at 30s while its sibling completed the same chain in ~44s. The timeout is not a tail event — it is BELOW the observed successful latency, so it fires on the normal case whenever contention is present. This recurs on EVERY decomposed question, and Contract B makes it cost the entire answer rather than degrading it.
---

# Parallel resolves contend for one BAML path

## The measurement

```
02:44:47  task_0   resolve_subject failed ... Read timed out (read timeout=30)
02:44:48  task_1   routing_decision subject_uri=fin#Program conf=0.97
                   verb_iri=mesh:finVarianceAnalysis verb_conf=0.94
02:52:28  task_1   resolve_subject failed ... Read timed out (read timeout=30)
02:52:42  task_0   routing_decision subject_uri=fin#Program conf=0.97
```

Both runs: two subtasks, simultaneous `/resolve`, **one dies at exactly 30s** while the sibling
finishes the same work. Which index dies is not stable — it was `task_0` in one run and
`task_1` in the other.

**Serially, the same input is deterministic.** Seven draws of the failing phrasing against the
deployed engine-o returned `fin#Program` at 0.92–0.95 with an IDENTICAL candidate set on every
draw. Zero set disjointness. **The resolver is not flaky. The path is contended.**

## Why the budget is the suspect and not the concurrency

A single ExtractIntent call was logged at **8334ms**. The full resolve chain — hybrid recall,
BAML classify, instance fan-out to six providers — completed at roughly **44s** on the
succeeding sibling.

**The timeout is 30s. The observed successful latency is ~44s.** So the budget is not protecting
against a pathological tail; it is set BELOW the normal completion time under contention, which
means it fires on the ordinary case. A retry would not help — the second attempt contends with
the same queue.

**This is the seam-9 budget lesson one hop upstream:** a timeout guessed rather than measured,
guarding a call whose real distribution nobody had plotted.

## And Contract B makes a timeout cost everything

ADR-0019 Contract B is correct — no LLM verb call without subject grounding — but it means a
`/resolve` timeout does not degrade the answer, it **replaces** it: `subject_uri=UNKNOWN` sends
the subtask to the generalist, which then answers from the catalog wearing the caller's persona.
At 21:47 that produced a fabricated entitlement story. **The timeout's blast radius is a wrong
answer, not a slow one.**

## Three candidate fixes, none to be taken before the measurement

1. **Serialize the subtasks' resolves.** Smallest change; costs wall-clock on every decomposed
   question and removes the parallelism deliberately.
2. **A worker pool on engine-o's resolve path.** Addresses the actual contention. Needs the
   concurrency ceiling measured, not guessed — the same error one layer down.
3. **A budget derived from the measured chain.** Necessary regardless of 1 or 2, because the
   current number is demonstrably below the normal case.

**The measurement comes first, and it is small:** time `/resolve` at N = 1, 2, 4 concurrent
posts, record the distribution rather than a mean, and set the budget from the tail actually
observed. Anything else replaces one guessed number with another.

## What NOT to conclude

**Not "the resolver is non-deterministic."** It is deterministic on this input; seven of seven
draws agreed exactly. The variance lives entirely in contention, and a run scored on winners
alone would have recorded this as sampler instability — which is how three separate hypotheses
(gate-drop, classifier sampling, phrasing recall) all came to measure a neighbour of a timeout.

---

# MEASURED 2026-09-05 — the budget has no headroom even at N=1

Serial and concurrent posts of the same failing phrasing to the deployed engine-o, with a
**180-second** client timeout so the real chain is visible rather than clipped at 30s.

| N concurrent | n | min | **median** | max | would exceed the 30s budget |
|---|---|---|---|---|---|
| 1 | 3 | 17.5s | **18.4s** | 22.0s | 0/3 |
| 2 | 6 | 18.1s | **26.1s** | 27.8s | 0/6 |
| 4 | 12 | 26.0s | **35.7s** | 46.6s | **9/12** |

**Every single request returned HTTP 200.** Nothing is broken and nothing is retried away —
the work completes, and the budget is simply smaller than the work.

## What the numbers settle

**The budget was never sized for the chain, not even for one caller.** At N=1, with no
contention at all, the median resolve takes **61% of the 30-second budget**. That is the
baseline, not the tail.

**At N=2 the margin is 2.2 seconds.** Median 26.1s, max 27.8s, zero timeouts in six draws —
which is exactly why this was invisible until it wasn't. Two subtasks is the ordinary shape of
a decomposed question, and it sits just inside the cliff. Any additional load on the same BAML
path — another engine's `classify_predicate`, a `fill_slots`, an `ExtractIntent` — pushes it
over, which is why production saw at N=2 what a clean N=2 does not reproduce.

**At N=4 it is not a tail event: 9 of 12 exceed the budget.** The failure rate is 75%.

## The recommendation the data supports

**Serialize the subtasks' resolves, and size the budget from N=1.**

Serializing moves the operating point from N=2 (median 26.1s, margin 2.2s) to N=1 (median
18.4s, max 22.0s) — where a 30s budget finally has real room. The cost is small and
calculable: two subtasks resolving serially is ~36s of wall clock against ~27s parallel,
**about nine seconds**, and it removes an entire failure class whose blast radius is a wrong
answer rather than a slow one.

A worker pool on engine-o is the better long-run answer and is not needed to close this. It
needs its own measurement — the concurrency ceiling, measured rather than guessed, which is the
same error one layer down.

**Raising the budget alone is refused.** It would make the timeout rarer without making it
rare: at N=4 the max is 46.6s, so any number that covers today's load is a number chosen
against a load nobody is holding fixed. Serializing changes the load; the budget then covers it.
