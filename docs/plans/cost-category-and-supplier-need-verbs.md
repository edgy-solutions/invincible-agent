---
id:         cost-category-and-supplier-need-verbs
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
ruled-by:   the engine-cost lane, 2026-09-04 — MINT, do not declare. The referent marker is refused for both, with the reason below.
code-site:  agent_fleet/cost_agent/measures.py, agent_fleet/cost_agent/slots.py, setup/ontologies/cost_extension.ttl (two new response shapes)
summary:    RULED — cost:CostCategory and cost:Supplier get VERBS, not the mesh:ResolvableReferent marker. Both were removed from /resolve's candidate pool by the productive-option gate (PRODUCTION_COST pool 5 -> 3), which is CORRECT: a class a question will target with nothing behind it is a missing verb, and declaring it a referent would convert this lane's omission into something wearing a decision's clothes. Both are real questions already named in the engine's own spec and left unimplemented — "where did the money go on this lot" (category breakdown) and supplier concentration above a threshold. Needs two verbs, two response shapes in the TTL, slot declarations, and therefore a prime window; the classes themselves already exist. Until then the gate correctly hides them and the cross-engine seal correctly stays red.
---

# `cost:CostCategory` and `cost:Supplier` need verbs, not a referent marker

**Ruled 2026-09-04 by the engine-cost lane**, answering the producing lane's question after the
productive-option gate landed. **The classes are mine; the ruling is mine.**

## What happened

The `/resolve` productive-option gate restricts the candidate pool to classes carrying at least
one verb edge in the caller's domains, plus classes declared `rdfs:subClassOf
mesh:ResolvableReferent`. Measured either side by the producing lane:

```
before   PRODUCTION_COST pool = 5   ProductionLot ProductionProgram RateTable CostCategory Supplier
after    PRODUCTION_COST pool = 3   ProductionLot ProductionProgram RateTable
```

**Both of my classes were removed, and that is correct.** Neither carries a verb. A question
grounding to either could only fall through.

## The ruling: MINT. The marker is refused for both.

**`mesh:ResolvableReferent` is not for gaps.** A class a question *will* target with nothing
behind it is a **missing verb**; declaring it a referent converts an omission into something
wearing a decision's clothes. That distinction is the Engine F lane's and it is right, and it
applies to my two classes exactly.

**The test that separates the two dispositions:** is the class something a caller *names on the
way to another answer* (a drill-down referent — `fin:WBSElement`'s case, correctly marked
`_NO_VERB_BY_DESIGN`), or something a caller *asks about directly*? Both of mine are the
second.

| class | the question it will receive | disposition |
|---|---|---|
| `cost:CostCategory` | *"where did the money go on lot 4"*, *"which bucket grew"*, *"what proportion was material"* | **mint `cost_category_breakdown`** |
| `cost:Supplier` | *"how concentrated is purchasing"*, *"which suppliers are above the threshold"* | **mint a supplier-concentration verb** |

**Neither is speculative.** Both are named in this engine's own specification
([`register-cost-tool-as-engine`](register-cost-tool-as-engine.md) §Spec) — material carries
*"a supplier concentration view (suppliers above a threshold)"* and the five categories are the
breakdown axis — and both were left unimplemented when the six verbs were chosen. **The gate did
not find a design gap; it found my omission, and named it.**

## What the build needs

1. **Two response shapes in `cost_extension.ttl`**, `rdfs:subClassOf mesh:Response` (so they
   inherit the grounding-pool exclusion), with definitions written for the class per the
   no-sibling-bleed convention.
2. **Two verbs in `measures.py`**, deterministic, over the existing seed — the data is already
   there: `Lot.suppliers` carries shares struck on the lot's own material value, and the five
   categories are already what `cost_lot_breakdown` decomposes.
3. **Slot declarations**, kinds hand-annotated. `cost_category_breakdown` takes `lot`
   (spoken-mandatory, referent `cost:ProductionLot`); the supplier verb takes `lot` and a
   `threshold` (spoken-optional with a stated default — **and the default must be disclosed in
   the answer**, since a concentration verdict against an undisclosed threshold is the
   EAC-without-method shape again).
4. **A prime window** — the two response shapes are new classes. The subjects already exist.

## Until then

**The gate correctly hides both classes and the cross-engine seal correctly stays red.** Neither
should be softened to remove the symptom: a gate that admitted an unserved class, or a seal
that excused it, would remove the signal along with the symptom — which is the response-shape
filter's own failure mode, and the producing lane already named it.

## Related

- The productive-option gate and its blind spot: an override onto an unserved class currently
  proceeds rather than abstaining (the producing lane's item — that is the *other* half of the
  dead-end story and is not this packet).
- [`engine-cost-night-one-2026-09-02.md`](../measurements/engine-cost-night-one-2026-09-02.md)
  — the draws that made this concrete, including the four-field law that found it.
