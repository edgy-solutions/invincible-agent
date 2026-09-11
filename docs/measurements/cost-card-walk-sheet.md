---
status: WALK SHEET — for a human with the UI open; nothing here is verified until the cards are seen
date: 2026-09-11
engine: engine-cost
---

# Cost card walk — four questions, four expected cards

**This sheet exists because a payload check is not a card walk.** Everything below is what the
engine produces; **none of it is evidence that anything renders.** The only evidence is the
card on screen.

**Runs last in the browser session**, after the finance board and the §9.2 decision.

**Fleet state assumed:** rev 108, all 17 at `74d6f638f4f5`, all eight cost verbs registered
(confirmed from `db.relationshipTypes()`). **So a card that does not draw is a PRESENTATION
problem, not a registration one.** That distinction is the whole point of this walk.

---

## READ THIS BEFORE THE FIRST QUESTION — three ways a CORRECT card looks broken

I chose the lot and year for each question deliberately, because my first picks would have
produced correct cards that look like failures. If you deviate from the parameters below, check
this list before scoring anything red.

1. **A rate comparison in a year with ONE vintage is all-`neutral`, every magnitude `+0.000`.**
   FY2022 and later have a single vintage, so applied *is* estimating and there is genuinely
   nothing to compare. Six grey rows of zero is the **correct** rendering of that. Question 5
   uses **lot 3 / FY2021**, which has two vintages, so real movement appears.
2. **A rate-assumptions series for a one-vintage year is a SINGLE POINT.** A line chart with one
   point looks broken and is right. Question 7 uses **FY2021**, which gives two.
3. **`cost_price_composition` is deliberately UNBOUND and SHOULD refuse.** It is not in this
   walk. If it appears and draws, that is a finding in the other direction.

---

## Q4 — Supplier concentration

> **"how concentrated is purchasing on lot 4"**

**Expect: `CONTRIBUTION_RANKING`, titled `Lot 4`, four rows, largest first.**

| rank | supplier | contribution | share | above bound |
|---|---|---|---|---|
| 1 | Cobalt Components | 604,963.20 | 0.4100 | **yes** |
| 2 | Amber Fabrication | 398,390.40 | 0.2700 | **yes** |
| 3 | Sable Castings | 280,348.80 | 0.1900 | no |
| 4 | Verdigris Electronics | 191,817.60 | 0.1300 | no |

**Checks that matter:**
- **Shares sum to 1.0000.** A ranking whose shares sum to less is truncated and says so, or is wrong.
- **The bound must be visible as `0.25` AND marked as the default** — you did not choose it.
  "Concentrated" with no bound on screen is meaningless.
- Two rows above the bound, and the card should make which two obvious without arithmetic.

---

## Q5 — Rate comparison  ⚠ **use lot 3, vintage 2021-02-01**

> **"did the rates move against the estimate on lot 3"**

**Expect: `DELTA_SET`, titled `Lot 3 - applied vs estimating rates`, six effects.**

| metric | direction | magnitude |
|---|---|---|
| Fringe | improved | −0.010 vs estimate |
| Overhead | improved | −0.010 vs estimate |
| G&A | improved | −0.003 vs estimate |
| Cost of money | **neutral** | +0.000 vs estimate |
| Profit | **neutral** | +0.000 vs estimate |
| Escalation | improved | −0.008 vs estimate |

**Checks that matter:**
- **Two rows are `neutral`, and that is data, not a gap.** Cost of money and profit genuinely did
  not move between vintages. If the card renders neutral identically to improved, the tone is
  not reading `direction`.
- **`Escalation` affects six steps; every other metric affects one.** If the card shows an
  affected list, Escalation's should be visibly longer — it is applied to the base before any
  burden is struck, so it touches everything.
- Direction is the **producer's** judgement. If a renderer inferred it from the sign, the two
  neutral rows would be mislabelled.

---

## Q6 — Labor composition

> **"what is the labor split on lot 4"**

**Expect: `CONTRIBUTION_RANKING`, titled `Lot 4`, value label `Labor cost`, three rows.**

| rank | kind | contribution | share | hours | rate |
|---|---|---|---|---|---|
| 1 | Touch labor | 4,938,800.00 | 0.6236 | 61,735 | 80 |
| 2 | Support labor | 1,889,108.00 | 0.2385 | 27,781 | 68.00 |
| 3 | SEPM | 1,092,000.00 | 0.1379 | 9,750 | 112.00 |

**Checks that matter:**
- **Hours and rate ride along as carried quantities.** If the card shows only money, the archetype
  is drawing but the payload's extra columns are being dropped — which is invisible unless you
  look for them.
- Shares sum to 1.0000; total labor 7,919,908.00.
- **SEPM has the highest rate and the smallest share.** A card that sorts by rate rather than by
  contribution would reverse rows 1 and 3.

---

## Q7 — Rate assumptions  ⚠ **use FY2021**

> **"what rates are we using in FY2021"**

**Expect: `MULTI_SERIES`, six declared series, two periods.**

| period | fringe | overhead | g_and_a | escalation |
|---|---|---|---|---|
| 2021-02-01 | 0.33 | 0.82 | 0.114 | 1.05 |
| 2021-08-01 | 0.34 | 0.83 | 0.117 | 1.058 |

**Checks that matter:**
- **The period is the VINTAGE DATE**, not a fiscal period. A rate table read as data is a series
  over the dates the rates were set.
- **Six series declared: fringe, overhead, g_and_a, cost_of_money, profit, escalation.** If the
  legend shows fewer, a declared series is missing from the rows — it draws a line with a hole
  and no error anywhere.
- **No unit.** These are dimensionless factors. A currency symbol on a rate is a defect.

---

## What each failure shape MEANS — so a red is attributable, not just counted

| what you see | what it means |
|---|---|
| `Knowledge Document · No content available` | the binding was not registered at page load, or the archetype was not admitted |
| card draws, **all rows blank** | the producer is not emitting the archetype's axis keys |
| card draws, **one column blank** | a passthrough field is missing. **`expected_fields` gates nothing** — every archetype but CHART_WIDGET returns `NOT_EVALUATED` — so this draws happily and is the easiest failure to score as a pass |
| no card, no refusal, **generalist prose** | routing did not reach a cost verb. **NOT a registration problem** — all eight are registered; look at scope, preemption, or phrasing |
| routed to `fin:WBSElement` | instance preemption. The post-preemption check is rolled, so this should now **abstain** instead |

> **"The card drew" is not "the payload was right."** Only the per-row checks above distinguish
> the two, and only for the fields they name.

---

## Reporting

Per the standing rules — **pass / fail / void by name.** A card you could not reach because the
session ran out is a **void**, not a fail: it says nothing about the presentation either way.
