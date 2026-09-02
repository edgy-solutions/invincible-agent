---
id:         period-series-is-a-cost-curve
status:     open
owner:      agent (Engine F lane) — THE BINDING IS MINE; the archetype contract and renderer are cortex-ui's
blocked-on: a ruling — mint a new archetype, or generalise PERIOD_SERIES
repo:       invincible-agent
ruled-by:   ADR-0045 (the amendment's precedent: when no archetype fits, MINT one); ADR-0042 §2 (the selector decides from the payload); ADR-0030 (one verb, one fixed output type)
code-site:  cortex-ui/src/components/planning/PeriodSeries.contract.ts (PeriodSeriesRow, validatePeriodSeries:178), cortex-ui/src/components/planning/PeriodSeries.tsx (hardcoded capex/expense bars), agent_fleet/presentation_agent/capabilities.py (the two bindings), tests/planning/test_producers_speak_their_archetype.py (_FIN_WRONG_ARCHETYPE)
summary:    PERIOD_SERIES IS ENGINE P'S COST CURVE WEARING A GENERIC NAME, and I bound two finance verbs to it because the NAME sounded right. Its row contract requires capex/expense/total/cap/over_cap/overage and its component hardcodes stacked capex+expense bars against a cap column; both fin producers are missing SIX of the seven keys. So `finBurnRate` and `finPerformanceIndices` mount and refuse honestly with "no numeric amount on any row" — the component is correct and the binding was never satisfiable. NO FIELD ADDITION FIXES IT: emitting `total` passes the validator and still draws the wrong chart, and for CPI/SPI it would be a false claim about a dimensionless ratio, which is the same species as the generative-renderer violation. THE REPAIR IS A RULING, NOT A PATCH: mint an archetype for labelled numeric series over periods without a cap (the ADR-0045 precedent that produced the other three), or generalise PERIOD_SERIES so producers DECLARE which fields carry numbers. I refuse the third option — "renderer falls back to any numeric field" — because drawing some number without knowing which is worse than refusing.
---

# `PERIOD_SERIES` is a cost curve, and I bound finance to it because the name sounded right

## What a person sees

```
NOTIONAL PROGRAM MERIDIAN — NOTHING TO DRAW
no numeric amount on any row
```

For `what is the burn rate` and `CPI and SPI over time`. The other four finance cards draw. **The
component is behaving correctly and its message is accurate.**

## The archetype is not generic

```
PeriodSeriesRow:  period, capex, expense, total, cap, over_cap, overage      (all required)
PeriodSeries.tsx: <Bar dataKey="capex" stackId="a"> <Bar dataKey="expense" stackId="a">
                  table columns:  period | total | cap | over by
validatePeriodSeries:  typeof r.total | r.capex | r.expense === "number"  else refuse
```

Every one of those is Engine P's cost-curve vocabulary. **The name says "a series over periods".
The contract says "capex and expense, stacked, against a cap."**

| producer | missing from the required seven |
|---|---|
| `fin_burn_rate` | `cap, capex, expense, over_cap, overage, total` — **6 of 7** |
| `fin_performance_indices` | `cap, capex, expense, over_cap, overage, total` — **6 of 7** |

## Why "just emit `total`" is refused

It would satisfy the validator and still be wrong, in two escalating ways:

1. **Burn rate** would draw empty `capex`/`expense` bars and a `cap` column it has no cap for.
   The chart would render and mean nothing.
2. **CPI/SPI are DIMENSIONLESS RATIOS.** Putting `0.848` in a field called `total`, beside an
   "over by" column, is a **false claim about the number** — the card would assert a currency
   magnitude and a budget breach where neither exists. That is the same species as the
   generative-renderer violation fixed the same day: a plausible-looking card asserting something
   untrue about a finance figure. **A wrong number that looks right is the worst available
   outcome**, and it is worse than the honest refusal happening today.

## The two real repairs

**A — MINT an archetype** for *labelled numeric series over periods, no cap*. This is exactly the
ADR-0045 precedent: when the payload read found no existing archetype fit, three were minted
rather than forced. Burn rate (burn vs planned) and performance indices (CPI, SPI) are both
**multi-series with no ceiling concept**, which no current archetype expresses. Cost: a cortex
component, and a fourth archetype through the five registries.

**B — GENERALISE `PERIOD_SERIES`** so producers declare which fields carry numbers, and the
renderer reads the declared fields instead of three hardcoded names. Fixes the class rather than
this instance, and prevents the third engine hitting it. Cost: a coordinated cortex-ui change to
an archetype Engine P already depends on, and **note the sibling asymmetry that made this
possible** — `SHORTFALL_GRID` and `THRESHOLD_GRID` both declare `value_label`; `PERIOD_SERIES`
declares `value_unit` and names the UNIT the numbers are in while never naming WHICH FIELD IS THE
NUMBER. A producer can satisfy the contract completely and have nothing to draw.

**B is the better fix and A is the smaller one.** B must handle the multi-series case: burn rate
has two series (burn, planned) and indices have two (CPI, SPI), so a single `value_label` is not
enough — it needs a declared *list* of series, which is a larger change than the sibling
archetypes' single label. Not ruled here.

**C — renderer falls back to "any numeric field": REFUSED.** It draws *some* number without
knowing which. On a forecast or a ratio that is the generative-renderer failure mode arriving by a
different door, and the current honest refusal is strictly better.

## How it got past everything

**I compared the payload against the projector's passthrough fields** (`rows`, `scope_label`,
`value_unit`) when the bindings table was authored, **and never against cortex's row contract**,
where `capex`/`total`/`cap` live. One registry checked, and not the one that draws.

**And the seal that encodes this exact requirement did not fire**, because its producer list was
one lambda per archetype — all seven of them Engine P's. A *second* producer binding to an
*existing* archetype was unguarded. That file had already fixed the remembered-population defect
once, for archetypes, after a hand-written list missed `SHORTFALL_GRID`; the producer population
stayed remembered.

**Fixed:** fin bindings are now derived from `PRESENTATION_CAPABILITIES`, and both bad bindings sit
in `_FIN_WRONG_ARCHETYPE` with written reasons — with a second test that **proves each exemption
still fails**, so a stale one cannot sit there suppressing a live check after the repair lands.

## THE GENERAL LESSON: deriving one population does not protect the other

**A seal has as many populations as its parametrisation has axes, and fixing one is what stops
you thinking about the rest.**

`test_the_producer_emits_every_key_its_archetype_requires` is parametrised on two axes:

| axis | how the population was obtained | outcome |
|---|---|---|
| **archetype** | DERIVED from the projector's own table — after a remembered list missed `SHORTFALL_GRID` | caught the three finance archetypes on the day they were added |
| **producer** | REMEMBERED — one lambda per archetype, all seven Engine P's | missed both finance producers entirely |

The file *documents the first fix in its own docstring* — *"the list was REMEMBERED rather than
enumerated… a fix applied to the instances someone could recall, not to the population that
shares the cause"* — and then leaves the second axis remembered, two parameters to the left.

**Why the second axis is the harder one to see:** after deriving the archetype population, the
test *feels* enumerated. It reports coverage, it has a coverage test guarding it, and that test
passes. Nothing about it says "coverage of archetypes, given one arbitrary producer each." The
fixed axis supplies the feeling of completeness for the whole seal.

**The check that generalises:** for any parametrised seal, list the axes and ask of EACH one —
*where did this population come from?* An axis whose answer is "someone wrote them down" is
unguarded regardless of how rigorously its neighbour is derived. Here the un-derived axis was
the one that decides whether a card draws.

*This is the enumeration law with an axis added. It is recorded in this packet rather than
promoted to `docs/principles/`, because that law has instances across several lanes and its
write-up is not this lane's to author alone — offered for promotion if the architect wants it.*

## Owed

* The ruling: A or B.
* If B, the multi-series question above must be answered before anyone writes it.
* **Unverified and worth checking:** Engine P's `plan_cost_curve` emits `capex`/`expense`/`total`
  and should render — but nobody has confirmed the planning `PERIOD_SERIES` card actually draws on
  the work cluster. Consistent with the code, not measured, and stated that way deliberately.

## Related

* `[[a-degradation-must-name-itself]]` — the counter-example that proves the law: this refusal
  **does** name itself, and that is the only reason the diagnosis took minutes instead of a night.
* `[[engine-f-cards-draw-v1]]` — where I published "all six draw" measuring the selected archetype
  instead of the rendered card.
* `[[an-adr-does-not-allocate-a-component-name]]` — the same family: a name that reads generic and
  is not.
