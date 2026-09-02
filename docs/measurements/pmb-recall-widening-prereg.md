---
id:         pmb-recall-widening-prereg
status:     open
owner:      agent
blocked-on: a prime — the change is committed and UNMEASURED until the ontology is re-seeded
repo:       invincible-agent
ruled-by:   ADR-0019 (Contract D); ADR-0031 (instance resolution ladder); adding-an-engine.md §1 (the rdfs:comment IS the recall signal, written for the class and never for a query)
code-site:  setup/ontologies/finance_extension.ttl (fin:PerformanceMeasurementBaseline), docs/measurements/response-shape-exclusion-results.md (the gap this answers)
summary:    WRITTEN BEFORE THE PRIME, because this change cannot be measured until the ontology is re-seeded and I will not start a prime while lane 1 has the /resolve scoping escape open. The gap: `what is our burn rate` grounds to fin:FundingLine and CANNOT be right, because fin:PerformanceMeasurementBaseline IS NOT IN ITS CANDIDATE SET — a recall failure, not a selection one. The cause is legible in the two definitions: FundingLine's comment owns the money-depletion language ("run out of money before it runs out of work") while PMB's claimed only "the planned spread of budget over time" and said NOTHING about actual cost incurred, despite the class carrying exactly that. PMB's comment now states the property it always had. PREDICTS: PMB enters the candidate set for spend-rate phrasings. REGISTERS THE RISK IN ADVANCE: the three rows that currently ground CORRECTLY to FundingLine are the ones this could break, and if any of them moves to PMB the widening has overreached and must be narrowed rather than defended.
---

# Pre-registration: widening `fin:PerformanceMeasurementBaseline`'s recall signal

**Written before the prime.** The change is committed and inert until the ontology is re-seeded,
so there is a clean window to say what should happen before anything can be read backwards.

## The gap this answers

From the exclusion results, and it is a **set**-level fact, which is why it was invisible while
the corpus was scored on winners:

```
"what is our burn rate"
  set    = [WBSElement, FundingLine, Program, EarnedValueTechnique]
  winner = FundingLine
  expected = fin:PerformanceMeasurementBaseline      ← NOT IN THE SET
```

**No re-draw fixes this.** The recall layer never offered a correct outcome, so the selection layer
could not have produced one. The repair is the class definition, not the sampler.

## The cause, visible in the two definitions

| class | what its `rdfs:comment` claimed |
|---|---|
| `fin:FundingLine` | *"…how much money is left to obligate… where the effort will **run out of money** before it runs out of work"* |
| `fin:PerformanceMeasurementBaseline` | *"the **planned spread of budget over time**… how much was planned versus claimed versus paid in a period"* |

**FundingLine owned every phrase about money leaving. PMB owned none of them** — despite the PMB
being the thing that *carries the actual cost incurred in each period*. A question about the rate
of spend went to the class that talked about money running out, which is the only one that did.

## What changed, and why it is not query-bait

The runbook's rule is that the comment is written **for the class, never for a query**. So the
addition is a statement of a property the class already has and had omitted:

> *"IT CARRIES THE ACTUAL COST INCURRED IN EACH PERIOD, so the rate at which cost is being
> incurred — how fast money is going out, and whether that is faster or slower than the plan
> phased for it — is a property of this class."*

plus a distinction stated **without naming the sibling**, matching the convention the existing
comments already use:

> *"What is measured here is COST INCURRED AGAINST A PHASED PLAN, which is a different thing from
> the headroom remaining in an appropriation: this compares spending to a schedule, not a drawn
> amount to an authorized ceiling."*

Every clause is true of the PMB independently of any question anyone asks. **If the phrasing
`"burn rate"` had been inserted verbatim, that would be query-bait and this packet would be an
argument for reverting it.**

## Predictions

**P1 — PMB enters the candidate SET for spend-rate phrasings.** The claim under test, asserted on
the set. `what is our burn rate` and `how fast are we spending` should both contain
`fin:PerformanceMeasurementBaseline` among their candidates.

**P2 — `what is our burn rate` grounds to PMB.** Weaker than P1 by construction: it runs through
the selection layer, which is measured non-deterministic at ≥2/20. A single counter-example is a
draw, not a refutation.

**P3 — the verb routes regardless of which of the two wins.** `finBurnRate` is now registered on
`fin:Program` as well as PMB, so the subject widening already covers program-named phrasings. This
change is about the phrasings that name *nothing*.

## ⚠️ THE RISK, REGISTERED IN ADVANCE — this can make three correct rows wrong

**PMB and FundingLine now compete for money language, and three rows currently ground correctly to
FundingLine:**

| row | current | must stay |
|---|---|---|
| `when do we run out of money` | `FundingLine` | `FundingLine` |
| `how much is unobligated` | `FundingLine` | `FundingLine` |
| `is the money committed` | `FundingLine` | `FundingLine` |

These are about an appropriation's **headroom** — authorized, obligated, expended — which is
genuinely the funding instrument's territory and not the baseline's. **If any of the three moves
to PMB, this widening has overreached**, and the correct response is to narrow the addition, not
to argue that the new answer is defensible. Recorded here so that call is already made.

`how fast are we spending` currently grounds to PMB **correctly** and must stay there; it is the
row that shows the two classes were always meant to split this way.

## What will be measured, after the next prime

1. Candidate **sets** for `what is our burn rate` and `how fast are we spending` — does PMB appear
   (P1).
2. The three FundingLine rows above — **the control, and more important than P1**.
3. Winners recorded alongside sets, per the standing rule, with any `subject_unknown` flagged
   separately rather than folded in.

## What will NOT be claimed

* No right-class total, and specifically no comparison against the `15/20` on record — that number
  is explicitly not a baseline.
* No claim from a single draw that P2 succeeded or failed.
