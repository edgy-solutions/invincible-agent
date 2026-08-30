---
id:         night-sweep-tier3-premise-retired
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  docs/demo-stable-phrasings.md (TIER 3), agent_fleet/planning_agent/main.py (/resolve_instance)
summary:    MEASURED post-prime. TIER 3's stated blocker is RETIRED — "plan entities live only in Engine P's in-memory PlanState and are invisible to /resolve" was true when written and is not true now: engine-p is a mesh:resolveInstance provider and those entities resolve. 5 of 5 named entities behaved exactly as pre-registered. But retiring the blocker surfaced something the blocked tier was hiding: THE INTENT COLUMN HAS TYPE ERRORS. "Financial Close Automation" is a CAPABILITY (C1) and "Supply Chain Visibility" an INITIATIVE (I3), yet six phrasings map them to `process_evolution`, which takes a `process_id` — the only BusinessProcesses in the model are BP1 "Order to Cash" and BP2 "Plan to Produce". Those six route to the wrong verb, and would have 422'd on a correct resolver. A seventh entity, "Straight-through invoicing", is in no seed collection at all.
---

# TIER 3's premise is retired, and it was hiding a type error

## What the corpus says

> The measure requires an id that nothing can resolve: plan entities ("Wave 1 Cutover",
> "Straight-through invoicing") live only in Engine P's in-memory `PlanState` and are
> invisible to `/resolve`. **Architecture item, post-demo. Do not script these.**

That was true when written. **It is not true now.** Engine P registers as a
`mesh:resolveInstance` provider (`[[the-filler-has-no-entity-resolution]]`), so those
entities are exactly as visible as any other referent.

## Measured — 5 of 5 as pre-registered

Pre-registration written before the probe: Wave 1 Cutover and Core ERP Platform resolve;
Financial Close Automation and Supply Chain Visibility come back wrong-class; Straight-through
invoicing is absent from the seed.

| entity named in TIER 3 | resolves to | the slot wants | verdict |
|---|---|---|---|
| Wave 1 Cutover | **P5** `Project` | `Project` | ✅ resolves |
| Core ERP Platform | **T1** `Technology` | `Technology` | ✅ resolves |
| Financial Close Automation | **C1** `Capability` | `BusinessProcess` | ✗ **wrong class** |
| Supply Chain Visibility | **I3** `Initiative` | `BusinessProcess` | ✗ **wrong class** |
| Straight-through invoicing | *no candidates* | `Capability` | ✗ **not in the seed** |

## The tier splits three ways, not one

Fourteen phrasings, and "needs an entity slot" is no longer the honest label for any of them:

| n | phrasings | now |
|---|---|---|
| **5** | the three `what blocks / what slips / waiting on Wave 1 Cutover` + the two `Core ERP Platform` | **UNBLOCKED** — the id resolves and the slot is fillable |
| **6** | three on *Financial Close Automation*, three on *Supply Chain Visibility* | **MIS-TYPED IN THE CORPUS** — see below |
| **3** | the *Straight-through invoicing* set | still blocked, and for a different reason: the entity does not exist |

## The six are a corpus error the blockage was hiding

`process_evolution` takes a `process_id`. The **only** BusinessProcesses in the model are
`BP1` *Order to Cash* and `BP2` *Plan to Produce*.

*Financial Close Automation* is `C1`, a **Capability**. *Supply Chain Visibility* is `I3`, an
**Initiative**. Neither is a process, so six phrasings are mapped to a verb that cannot take
them — and the correct destinations look like `capability_path` for the first and something
initiative-scoped for the second.

**This was invisible while the whole tier was blocked**, because a slot that could never be
filled fails the same way whatever it was pointed at. Retiring the blocker is what separated
"cannot resolve the id" from "resolves to the wrong kind of thing" — the distinction the
`wrong_class` outcome exists to make.

> A blocked tier hides the quality of its own intent. Unblocking it is the first time anyone
> finds out whether the mapping was right.

## What is NOT claimed

**Gate 1 only, and not end-to-end.** This measures that the referent resolves to the right
class. It does not show a card rendering — the corpus's own standard — and gates 3 and 4 are
untested for these phrasings. The five "unblocked" rows are unblocked *at the slot*, which is
one gate of four.

**No corpus edit made.** The six mis-typed rows and the three absent-entity rows are recorded
here, not rewritten: the phrasing corpus is the architect's, and the intent column is a
judgment about what a question means, not a fact about the substrate.
