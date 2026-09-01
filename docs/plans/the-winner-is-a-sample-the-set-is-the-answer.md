---
id:         the-winner-is-a-sample-the-set-is-the-answer
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0031 (instance resolution ladder); ADR-0025 (the can_view-filtered candidate pool)
code-site:  agent_fleet/ontology_service/main.py (/resolve — candidate recall, then selection), docs/measurements/engine-f-end-to-end-routing-v1.md and engine-f-grounding-corpus-v1.json (the totals this retires)
summary:    MEASURED 2026-09-01, arm A n=3 on one fixed substrate, recording the candidate SET and the WINNER on every draw. The candidate sets are DETERMINISTIC — 0 of 20 flipped. The winner selected from them is NOT — 2 of 20 flipped, and that is a FLOOR rather than a rate: a third row flipped between two earlier runs and held across these three, so n=3 understates it. CONSEQUENCE: a right-class grounding TOTAL is not a usable instrument at this precision, because it sums twenty draws from a partly non-deterministic selection layer sitting on top of a stable one. This retires BOTH published totals for the finance corpus — 11/20 and 12/20 — and, more importantly, retires the DIFFERENCE between them, which was read as substrate evidence and discriminates nothing: one of the two known-unstable rows IS the row the difference consisted of. THE FORBIDDEN ARITHMETIC is treating 2/20 as a noise budget and subtracting it from a delta; the claim the data supports is qualitative and stronger than any budget. What to measure instead: SET DISJOINTNESS, which is measured on the deterministic layer.
---

# The winner is a sample; the set is the answer

**Framing owed to Lane 1**, who put it better than I had: *the SET is the system's answer and
the WINNER is a sample from it, so any measurement that scores the winner is measuring the
sampler as much as the system.*

## The measurement

`/resolve`, arm A (`domains=["PROGRAM_FINANCE"]`, `user_email=alice@example.com`), 20 finance
phrasings, **n=3 on one fixed substrate**, recording the candidate set and the winner on every
draw:

| | result |
|---|---|
| rows whose candidate **SET** flipped across 3 draws | **0 / 20** |
| rows whose **WINNER** flipped across 3 draws | **2 / 20** |
| rows where both flipped | 0 / 20 |
| shape occurrences in the sets | 24 across 14 phrases — reproduced exactly |

The two flippers:

```
"show me SPI over time"     EarnedValueTechnique  <-> PerformanceMeasurementBaseline
"how fast are we spending"  FundingLine           <-> PerformanceMeasurementBaseline
```

**The recall layer is deterministic and the selection layer is not.** Same substrate, same
query, minutes apart: identical candidate set, different pick.

## 2/20 IS A FLOOR, NOT A RATE — and the difference matters

`"what is the funding status"` flipped between two earlier runs (`FundingStatusGrid` /
`FundingLine`, identical set both times) and was **stable across these three**. So at least
three rows are unstable and **n=3 understates it**.

> ### ⛔ THE FORBIDDEN ARITHMETIC
>
> Do not treat `2/20` as a noise budget, subtract it from a delta, and believe the remainder.
> That is precisely the reasoning this finding forbids: the floor is an **existence proof**,
> not a magnitude, and a reader who budgets with it will license exactly the comparisons that
> are unavailable.
>
> **The supportable claim is qualitative and stronger than any budget: a right-class grounding
> total is not a usable instrument at this precision.**

## What this retires

**Both published finance totals, and the difference between them.**

Two lanes measured the same corpus and got `11/20` and `12/20`. The gap was attributed to
substrate — one set of draws was taken mid-ingest — and one number was retired on those
grounds. **The row the gap consisted of is `"show me SPI over time"`, which is one of the two
rows that flips on a fully-ingested substrate.**

So "biased by an incomplete substrate" and "unstable regardless of substrate" are competing
explanations for one row, and **the 11-vs-12 gap discriminates between them not at all.**
Neither total is reinstated. Reclaiming one would repeat the original error backwards —
treating a total as a fact about the system when it is a draw from a sampler.

*(Five consecutive identical draws is unlikely under an unbiased flip, so substrate bias
remains live as a hypothesis. It is simply not evidenced by this comparison.)*

## What to measure instead

**Set disjointness**, asserted per row, because it reads the layer that holds still:

* did the candidate set change, and how;
* did a named class leave or enter a set;
* aggregate over sets, not over winners.

Concretely for the response-shape exclusion this corpus was built to measure: the assertion is
**24 shape-occurrences across 14 sets → 0**, per-row, with totals reported for continuity and
explicitly **not interpreted**. And record the winner *alongside* the set on every draw, so a
flip reads as a flip rather than being laundered into a total.

## Why the control is not affected

`arm C` (no `domains`, so scoped to `MAINTENANCE`) has reproduced **7/20 across three separate
primes**. That is not a counter-example: most of its rows ground outside `fin:` entirely and
land in the same bucket whichever way an unstable row falls. A stable total over a corpus whose
instability sits inside one bucket is consistent with an unstable sampler — which is itself a
caution, because **a total can look reproducible for reasons unrelated to the thing it
measures**.

## Scope, and what is NOT claimed

* **Not** that `/resolve` is broken. A stable set with a sampled winner may be entirely by
  design — the selection step is BAML-backed and nothing promises determinism.
* **Not** a rate, a budget, or a confidence interval. n=3 over 20 rows supports existence, not
  magnitude.
* **Not** specific to finance. The mechanism is the recall/selection split, which every
  grounded question crosses. A planning or catalog corpus scored by right-class totals inherits
  the same defect; none has been measured for it.

## Owed

* A determinism run at higher n, on a corpus that is not finance, to establish whether the
  floor is ~10% or much higher. Until then no rate is quotable.
* An annotation on `engine-f-end-to-end-routing-v1.md` pointing here, so its published totals
  are not read as facts. **Done in the same change as this packet.**
