---
iri: docs:runbook-writing-a-walk-sheet
# EXPLAINS: NONE, and the sentinel is the decision (R-015). A walk sheet is an act performed by a
# human with a browser open. Derived from setup/ontologies/mesh_system.ttl rather than recalled:
# the mesh declares four lowercase verbs -- enumerateInstances, proposeDisposition, rendersAs,
# resolveInstance -- and 72 classes, and NOT ONE concerns walking, verifying, screens or
# rendering. `mesh:Archetype` is the nearest thing and it fails: an archetype is what a card
# IS, not the act of confirming one drew. Minting `mesh:WalkSheet` to make the edge look tidy is
# exactly what ADR-0037 section 1 refuses.
explains: none
doc_kind: how-to
# From policy/personas.yaml, in its own casing (R-017: the corpus normalises TO the policy file).
audience_hint: ARCHITECT
---

# Writing a walk sheet

> **Written 2026-09-11, from one sheet that was walked and found wrong before the browser
> opened.** `cost-card-walk-sheet.md` specified a refusal that could not happen, and a walker
> following it would have scored a red against a rendering that works.

**A walk sheet is the instrument for the only claim a payload test cannot make: that a human
looking at the screen sees the right thing.** Everything else in this repo checks the engine. A
sheet checks the last hop, and it is the hop with no seal.

## The rule that this page exists for

> **SHEETS CARRY CAPTURED PAYLOADS.** Paste the bytes the consumer receives. Not a description of
> them, not the exception class the code raises, not a table retyped from the producer.

**A sheet written from the code asserts what the code says, not what the wire carries** — see
[`reachability-is-a-property-of-a-path`](../principles/reachability-is-a-property-of-a-path.md).
The failure is not carelessness; it is that the code agrees with itself. Q5 was specified as
returning `VintageRequired` and checked for *"it names BOTH vintages"*, because
`_require_vintage` does exactly that. It is unreachable over HTTP: a generic `slot_required`
answers first, and the wire carried **no values at all**.

**Cost of getting this wrong is not a missed defect. It is an INVENTED one**, aimed at the wrong
component — the sheet would have sent a reader to the renderer for an engine gap.

**How to capture**, cheaply and without a cluster: stand the app up in-process and post the real
request.

```python
from fastapi.testclient import TestClient
from agent_fleet.<engine>.main import app
with TestClient(app) as c:
    print(c.post("/measure/<verb>", json={"params": {...}}).json())
```

Paste the result into the sheet, trimmed to the fields a walker compares. **If it will not fit,
that is information** — a payload too large to show is one a human cannot verify either.

## What a row must carry

| field | why |
|---|---|
| **the question, verbatim** | Not a paraphrase. The phrasing is the routing signal; a reworded question tests a different path. Prefer the engine's own declared synonyms and **say that is where it came from**. |
| **the expected archetype, by name** | "A chart appears" is not a check. `CONTRIBUTION_RANKING` is. |
| **the captured payload** | See above. |
| **checks that distinguish** | A check both a right and a wrong render would pass is decoration. |
| **what a CORRECT result looks like BROKEN** | The highest-value section, and the one only the author can write. |

## Correct results that look like failures

**Write these before the walk, not after someone scores a red.** The cost sheet has four, and
each was found by the author choosing parameters and noticing the answer would mislead:

- a comparison in a year with **one** vintage is all-neutral, every magnitude `+0.000` — six grey
  rows of zero is the **correct** rendering;
- a series for a one-vintage year is a **single point** — a line chart with one point looks
  broken and is right;
- a verb that is deliberately **unbound** *should* refuse, and drawing would be the finding;
- **a designed refusal is a PASS.**

> **The refusal screen is the one nobody looks at.** Cards get walked because they are the
> interesting part. A designed refusal that renders as generalist prose, or as `No content
> available`, is the same defect as a card that will not draw — and it is the one a walk is most
> likely to mislabel, because "nothing drew" is what both look like.

## Say which component owns each possible failure

A check that can fail two ways needs the split written down, or the walker guesses:

> *If the refusal draws but the two values do not appear, the payload is right and the RENDERER
> is dropping them — that is a cortex finding, not an engine one.*

## Name the residuals, and mark them do-not-score-red

A sheet with a known gap must say so **at the check**, not in a footer. The cost sheet's:

> *It says WHY — and today it says "needs rate_vintage", a missing-parameter reason rather than a
> basis reason. ⚠ KNOWN RESIDUAL, do not score it red.*

**An unnamed residual gets scored as a defect by the first honest walker**, and the second one
learns to ignore the sheet. Both outcomes cost more than the sentence.

## Before the walk, and it is not optional

1. **Re-capture every payload.** The sheet ages against the engine; a figure correct last week is
   a stale claim that reads as checked.
2. **State the fleet revision and sha the sheet assumes**, and check it still holds. A sheet
   assuming a rev that has rolled is measuring something else.
3. **Confirm the prerequisites are DEPLOYED, not committed.** Declared and resolves are different
   claims — a provider in a commit is not a provider in the graph, and a prime alone does not
   restore routing (engines re-register at startup, so it is a roll **and** a prime).

## If a sheet is derived by a test, say so in the sheet

`tests/cost/test_the_walk_sheet_resolves_to_cost_lots.py` parses its questions **out of**
`cost-card-walk-sheet.md`. That is worth doing — reword a question and the seal moves with it,
rather than passing against text nobody asks any more — but it makes the sheet **load-bearing
source**, and a reader editing it deserves to know.

**Give that parser its own positive control.** If the heading style changes, the regex matches
nothing, every parameterized case collapses to zero, and pytest reports green for a suite that
asserted nothing. An exact expected count is what catches it: when lane/01 split Q5 into two
prompts on master, the count went red and **named the parsed five** instead of silently
re-parameterizing. A `>=` there would have absorbed the change — which is the whole failure it
was written against.
