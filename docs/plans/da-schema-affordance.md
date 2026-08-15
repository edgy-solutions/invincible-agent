---
id:         da-schema-affordance
status:     open
owner:      unassigned
blocked-on: nothing — both halves are small and independently shippable.
closed-by:
code-site:  agent_fleet/data_analyst/main.py:386
repo:       invincible-agent
summary:    Engine DA is handed a URN and no schema, so it guesses column names and learns them from BinderException text; and `query_datahub_asset` returns a JSON STRING, so the agent then discovers it cannot index it. 3 of 6 steps on a successful two-row read were spent on both.
---

# The agent is given an asset and no way to know what is in it

The successful work run on 2026-08-15 — the one that returned real data — took 6 steps and
logged `step_errors=3`. Every error was a missing affordance, not a mistake:

```
Step 1  SELECT cage FROM dataset LIMIT 2
        BinderException: Referenced column "cage" not found in FROM clause!
        Candidate bindings: "cage_code", "cage_status", "cao", "state_province", "city"
Step 2  SELECT cage_code FROM dataset LIMIT 2  ->  [{"cage_code":"00000"},{"cage_code":"00001"}]
Step 4  [row["cage_code"] for row in result]
        InterpreterError: string indices must be integers
Step 5  json.loads(result) first  ->  ['00000', '00001']
```

## Two independent defects

**1. No schema in the prompt.** DA receives the resolved URN and the DataHub *entity-type*
list, but nothing about the asset's columns. The user asked for "cage values"; the column is
`cage_code`. The agent's only route to that is to guess and read the database's error message.
It worked here because DuckDB's `BinderException` helpfully lists candidate bindings — the
recovery depends on an error-message format, which is a thin thing to rely on.

The schema is available: `mesh:findSchema` is a registered verb over the same subject, and the
broker's asset info carries column metadata. Putting the column list in the prompt beside the
resolved URN removes the guess entirely.

**2. `query_datahub_asset` returns a JSON string.** So a natural `[row["col"] for row in
result]` fails, and the agent has to discover it needs `json.loads`. Returning parsed rows —
or documenting the shape in the tool's docstring, which is what the agent reads — costs
nothing and removes two more steps.

## Why this is worth fixing rather than tolerating

It succeeded, so it is easy to dismiss. But each wasted step is an LLM call against a live
data path, the recovery leans on a specific error-message format, and `DA_FUMBLE_METRIC` is
already measuring it (`structured=False outcome=ok steps=6 step_errors=3`) — the metric exists
because someone expected this to matter.

It also compounds with [[ui-renders-honest-failure-as-answer]]: a run with more steps has more
chances to end in an articulate apology that reports itself as success.

## Distinct from the other loop item

[[agent-loop-infra-error-flail]] is the agent flailing against a hard infrastructure error it
can never fix. This is flailing against information it should have been given. Same metric,
different repair, and this one is the tractable half.
