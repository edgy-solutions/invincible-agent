---
id:         agent-loop-infra-error-flail
status:     open
owner:      unassigned
blocked-on: nothing
closed-by:
code-site:  agent_fleet/data_analyst/main.py
repo:       invincible-agent
summary:    A hard infrastructure error (ConnectError, 404) is handed to the code agent as an ordinary tool failure, so it burns steps re-attempting and narrating around something no amount of reasoning can fix — then reports `outcome=ok` for having produced an apology.
---

# The agent reasons its way around an unreachable host

Work, 2026-08-14. `query_datahub_asset` raised `ConnectError: Name or service not known` — a
DNS failure, unfixable from inside the loop. The agent then spent six steps and four parse
errors composing explanations, and the run closed as:

```
DA_FUMBLE_METRIC structured=False outcome=ok steps=7 step_errors=4
```

The same shape recurred with an HTTP 404 from the gateway. In both cases the FIRST error was
already terminal, and everything after it was cost without information.

## The distinction the loop does not make

A tool failure is one of two things:

- **retryable / reasonable-around** — a bad column name, a malformed query, a wrong argument.
  Re-attempting is exactly right, and this is what the loop is for.
- **infrastructural** — DNS, connection refused, 401/403, 404 from a routing layer. No
  re-attempt and no rephrasing changes it. The honest move is to stop immediately and say what
  broke.

Today both arrive as a Python exception in a tool call, so the agent treats them identically.
Note it behaved *reasonably* given what it knew — it stopped inventing URNs, which is
ADR-0014 working — but it had no way to know the difference.

## Why the metric cannot see it either

`outcome=ok` for a run whose data path never worked. The agent produced a well-formed final
answer, so by its own accounting it succeeded. That is the same conflation as
[[ui-renders-honest-failure-as-answer]] one layer down: "the loop terminated politely" is being
counted as "the question was answered."

## Work

1. **Classify tool failures at the tool boundary.** `query_datahub_asset` knows whether it got
   a `ConnectError`, a 4xx, or a query error. Raise a distinguishable terminal type for the
   infrastructural ones.
2. **Terminate the loop on a terminal failure**, with the cause named in the final answer
   rather than paraphrased. One step, not six.
3. **Give `DA_FUMBLE_METRIC` an outcome that distinguishes them** — answered, honest-empty,
   infra-failed. Without that the fix is unmeasurable.

## Sibling, not duplicate

[[engine-a-loop-idempotency]] is about a non-idempotent effect INSIDE the loop and is parked
with a reserved design window. This is about the loop's response to a failure it cannot fix.
[[da-schema-affordance]] is the third member of the family: flailing against missing
information rather than a broken dependency.
