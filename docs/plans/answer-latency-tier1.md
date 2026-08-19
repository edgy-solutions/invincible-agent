---
id:         answer-latency-tier1
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    A Tier-1 question whose answer is ONE metadata field took 324.9s end-to-end on sandbox (77s locating, 148s retrieving). Measured, not estimated — phase breakdown from the 2026-08-18 witness run. Demo-room liability and a standing user-experience fact.
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
