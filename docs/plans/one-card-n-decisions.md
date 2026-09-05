---
id:         one-card-n-decisions
status:     open
owner:      unassigned — ADR-shaped, needs a ruling before code
blocked-on: what a multi-subtask answer IS (an ADR question, not an implementation one)
repo:       invincible-agent (+ cortex-ui surface change)
ruled-by:   pending; ADR-0017 (multi-archetype composition) is the nearest existing item
code-site:  src/iagent/gateway.py:4001 (the flag, written before this was measured), src/iagent/gateway.py `_primary_routing_mat`, src/iagent/defs/dynamic_supervisor.py `generate_ui_payload` (the card's own selection loop)
summary:    A question decomposes into PARALLEL subtasks and each makes its own routing decision, but the artifact keeps ONE routing record, ONE graph trace and ONE card — each chosen by a different rule. The immediate contradiction (a correct answer under a "not grounded" header) is closed by selecting the record with the card's rule. What is NOT closed is the question underneath: when two subtasks route differently and both answer, what should a reader see? Filed with the gateway's own pre-existing flag as its citation, because that flag was written before anyone had measured the shape it was flagging.
---

# One card, N decisions

## The flag was already there, and it predates the evidence

```python
# gateway.py:4001
# graph_trace — first subtask wins. Multi-subtask UI
# semantics will revisit this.
```

And forty lines earlier, the intent stated correctly:

> *"the Routing Decision card focuses on the primary route the user's answer flows through"*

**The comment names the right rule and the code implemented a different one** — first
materialization rather than the route the answer came from. That gap was invisible for as long
as runs were single-subtask or all-succeeding.

## What was measured (2026-09-04, runs e82b3031 and 2a627ea7)

Three selections, three different keys:

| artifact field | selected by | eligible subtasks |
|---|---|---|
| `routing_inline` | first to **materialize** | all — failures included |
| `graph_trace_json` | first to **materialize** | only those that **grounded** (`dynamic_supervisor.py:1519`) |
| the rendered card | first result carrying an **`output_uri`** | only those that produced a typed output |

**Three rules with three different eligibility sets agree only by luck.** They disagreed on
2026-09-04: an Engine F variance tree with real EVM rows rendered under a header reading
`NOT GROUNDED · General search · conf 0.00`.

The `routing_inline` half is now fixed — `_primary_routing_mat` selects the first MATCHED
decision, which is this side's expression of the card's rule. **That closes the contradiction
without answering the question.**

## The question this leaves

Two subtasks route to different verbs and both answer. Today the reader sees one card and one
decision path, and the other subtask's work is present in the artifact but unreachable from any
surface. Three dispositions:

1. **Primary route only** (today, now selected correctly). Cheapest, honest about the card
   shown, and silently discards a real second answer. The reader cannot know a second route
   ran, which is the shape this repo keeps removing elsewhere.
2. **N decision paths, one per subtask.** Truthful and complete. Costs a cortex surface — the
   Routing Decision card becomes a list — and needs a rule for what "the" route is in the HUD.
3. **Primary route plus a count.** "1 of 2 routes shown." Cheap, honest about the omission,
   and does not require the full surface. **My lean**, on the standing principle that an
   omission which leaves no trace is the failure worth avoiding first.

**Not taken here, deliberately.** Picking between these decides what a multi-subtask answer IS,
and that is an ADR, not a gateway edit. The immediate defect must not wait behind it — the
contradiction it caused is on the flagship demo question.

## Why this must not be closed by suppressing the decomposition

The obvious shortcut is to stop fanning out. **That would hide the finding and lose a real
capability**: at 21:47 and 21:55 the decomposition was correct — *"why are we over budget"*
legitimately splits into a variance analysis and a line-item drill-down. One subtask timing out
is a concurrency defect (see `parallel-resolves-contend-for-one-baml-path.md`), not an argument
against decomposing.
