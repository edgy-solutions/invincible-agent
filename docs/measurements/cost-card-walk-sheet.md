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
(confirmed from `db.relationshipTypes()`).

> ## ⚠ WALKED 2026-09-11, AND ALL FOUR ABSTAINED BEFORE ANY CARD WAS REACHED
>
> **This sheet said: "a card that does not draw is a PRESENTATION problem, not a registration
> one." It was NEITHER, and the walk is what proved it.** A two-way split left no name for what
> actually happened — the questions never reached this engine at all.
>
> `"lot 4"` was captured by engine-fin's instance provider at **exactly 0.500**, matching the
> **bare digit** against a WBS element's `instance_id`; `banana 4` reproduces the hit, and
> `lot four` produces nothing. That override discarded a correct `cost:Supplier` classification
> **at 0.92**, and Engine O's post-preemption check then abstained — correctly, and for the
> first time in production.
>
> **So the third state is ROUTING, and it is the one this sheet could not name.** Full chain and
> the controls: [`lot-4-resolves-to-program-support-2026-09-11.md`](lot-4-resolves-to-program-support-2026-09-11.md).
>
> **PREREQUISITE BEFORE WALKING AGAIN**, or all four abstain identically: engine-cost's own
> instance provider (`cost_agent/instances.py`, shipped `d446a15`) must be **registered in the
> graph** — a roll and a prime, not a commit — and Lane 1's scope rule must be in force.
>
> The questions below are **unchanged**, and are now parsed directly out of this file by
> `tests/cost/test_the_walk_sheet_resolves_to_cost_lots.py`: **reword one and the seal moves
> with it. Q5 became TWO prompts on master while this banner was being written, and the seal's
> own count is what caught it — five prompts, four questions, both Q5 steps sealed.**
>
> *Nine verbs are registered now, not eight — `package_export` landed after the line above was
> written, and the instance provider adds two registrations that are not verbs.*

---

## WALKED 2026-09-12 — THREE CARDS DREW, ONE DID NOT, AND THE WALK FOUND FIVE DEFECTS NO SEAL HAD

**The engine's own suite was green through every one of these.** That is the entry worth reading:
each defect below was reachable only by a person typing a question into a browser.

| | question | result |
|---|---|---|
| **Q5** | rate comparison, vintage named | ✅ **`DELTA_SET` drew.** Both checks a payload could not reach passed — the two neutral rows render in their own `NO MATERIAL CHANGE` section rather than identically to improved, so the card reads the producer's `direction` instead of inferring it from the sign; and Escalation's affected list is visibly longer at six steps. |
| **Q6** | labor split on lot 4 | ✅ **`CONTRIBUTION_RANKING` drew**, contributions matching this sheet to the decimal — 62.4 / 23.8 / 13.8 against 0.6236 / 0.2385 / 0.1379. |
| **Q7** | rates in FY2021 | ✅ **`MULTI_SERIES` drew with BOTH vintages plotted**, not the single point trap §1 of the list below warns about. |
| **Q4** | supplier concentration | ❌ **Routed to `cost_lot_breakdown`.** Not a card defect — the instance override replaces the subject, and `cost_supplier_concentration` becomes unreachable. Lane 1 owns it; see [`the-instance-override-survived-its-own-fix`](the-instance-override-survived-its-own-fix-2026-09-12.md). |

**Five defects, and the engine owns four of them** — all fixed in `dedbede`, `4a8c209`,
**none deployed** (the fleet runs `2803900`, which predates them, so Q4's re-walk and the
refusal's re-walk both wait on a roll):

1. **A vintage valid for another lot was a 500** and reached the screen as an **empty card**.
   Lot 4 is FY2022; `2021-02-01` was typed because the previous question used it.
2. **An undeclared param was a 500 on every verb** — and the loop's own fix, merging bound slots
   across hops, would have triggered it on the first multi-verb interview.
3. **The options fix was a sample**: two other verbs declare the same mandatory `rate_vintage`
   and offered nothing, so the ask had no values for cortex to draw *even if cortex consumed
   them*.
4. **`"G And A"` was in the engine's payload**, not cortex's rendering — two verbs over the same
   six factors spoke two vocabularies.
5. **`"9 exist"` with no menu** — the engine's own count with an empty member list.

**Cortex-side, and the split this sheet defines held every time:** the refusal renders as free
text rather than a menu; `CONTRIBUTION_RANKING` drops the `hours` and `rate` columns the payload
carries; and `+$4.9M` puts a delta's sign on a share of a total.

---

## READ THIS BEFORE THE FIRST QUESTION — four ways a CORRECT result looks broken

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
4. **Q5's FIRST response is a REFUSAL, and the refusal is the correct answer.** `rate_vintage`
   is a **required** slot (`cost_rate_comparison(state, *, lot: int, rate_vintage: str)`) and
   `_require_vintage` raises **unconditionally** when it is absent — not only when the year has
   two vintages. The question as written names no vintage, so **`VintageRequired` fires every
   time.** Scoring that red would fail the engine for doing the one thing it was built to do:
   it is the analogue of Engine F's mandatory EAC method. See Q5's two steps below.

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

## Q5 — Rate comparison  ⚠ **TWO STEPS — a refusal, then the card**

**The `⚠` here used to read `use lot 3, vintage 2021-02-01`, which is not something the walker
can do in one question — the phrasing below carries no vintage and there is nowhere to put one.
It was a PREDICTION about which vintage the answer would use, written as an INSTRUCTION.**

### Step 1 — ask it as written, and expect a REFUSAL

> **SECOND-WALK EXPECTATION, set 2026-09-12 by cortex-ui-60 and worth reading before you score.**
> The refusal must show **two option chips and NO text box — and NO UI change between the two
> walks.** The menu branch was always a ternary on `options.length > 0`; the card was correct and
> the PAYLOAD was empty, because `OPTION_SOURCES` was keyed `(verb, slot)` with a single entry so
> two verbs declaring the same mandatory `rate_vintage` carried nothing. The re-key by slot
> (engine-cost's) is the whole fix; no cortex code changed.
>
> **So "it looks the same as last time" is the PASS, and a text box is a DATA finding, not a
> render one.** That is a better check than "did it change", because it can only pass one way —
> and cortex deliberately did not build a second code path, which would have made this walk
> verify a rendering the producer never emits.



> **"did the rates move against the estimate on lot 3"**

**Expect: `outcome: "slot_required"` — *not* a card, and this is a PASS.**

> **⚠ THIS SAID `VintageRequired` UNTIL 2026-09-11, AND THAT REFUSAL COULD NOT HAPPEN.**
> `rate_vintage` is spoken-mandatory, so `/measure/{fn}` short-circuits **before the verb
> runs**. `_require_vintage` — the only code that knows the vintages — **was unreachable
> through the path the UI uses.** The wire carried `missing` and `declarations` and **no
> values at all**, so the second check below could not pass and a walker would have scored a
> red against a rendering that works. Found by reading the payload rather than the code.
> **Fixed**: the route now computes `options` from the slots the caller did supply, and a
> seal asserts it agrees with what the verb would have said.

The phrasing routes correctly (`"did the rates move"` is a declared synonym of
`mesh:costRateComparison`), and the **route** then refuses because `rate_vintage` is required
and absent. **This is the payload to compare against — captured from the engine, not written
from memory:**

```json
{ "refused": true, "outcome": "slot_required",
  "reason": "cost_rate_comparison needs rate_vintage",
  "missing": ["rate_vintage"],
  "options": { "rate_vintage": ["2021-02-01", "2021-08-01"] } }
```

**Checks that matter, and nothing has ever confirmed these render:**

- **The refusal DRAWS AT ALL.** A designed refusal that renders as generalist prose, or as
  `No content available`, is the same defect as a card that will not draw — and it is the one
  failure this walk was most likely to mislabel. **This is the whole reason Q5 is here.**
- **It names BOTH vintages — `2021-02-01` and `2021-08-01`** — from `options.rate_vintage`.
  A refusal that withholds them is a dead end wearing a refusal's clothes. **If the screen
  shows the refusal but not the two values, the payload is right and the RENDERER is
  dropping them; that is a cortex finding, not an engine one.**
- **It says WHY — and today it says "needs rate_vintage", which is a missing-parameter
  reason, not a basis reason.** ⚠ **KNOWN RESIDUAL, do not score it red.** The route's
  message is generic across every verb; the basis-level explanation lives in
  `VintageRequired`, which this path still does not reach. The *values* were the load-bearing
  half and they are now carried; the *wording* is an open improvement.

### Step 2 — name the vintage, and expect the card

> **"did the rates move against the estimate on lot 3, using the 2021-02-01 vintage"**

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
| a **refusal** where the sheet expects a card | check whether the verb has a REQUIRED slot the question does not fill. Q5 is the known case; a refusal there is a **pass**, not a fail. A refusal is only a fail when the slot WAS supplied |

> **"The card drew" is not "the payload was right."** Only the per-row checks above distinguish
> the two, and only for the fields they name.

---

## Reporting

Per the standing rules — **pass / fail / void by name.** A card you could not reach because the
session ran out is a **void**, not a fail: it says nothing about the presentation either way.
