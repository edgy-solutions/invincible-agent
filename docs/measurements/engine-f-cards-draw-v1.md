---
id:         engine-f-cards-draw-v1
status:     open
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0045 (Engine F; the amendment's deterministic-renderer ruling); ADR-0017 (rendersAs); ADR-0042 §2 (the selector decides from the payload)
code-site:  agent_fleet/presentation_agent/main.py (_PROJECTED_ARCHETYPES — the projected set), agent_fleet/utils/mesh_registration.py:492, src/iagent/defs/dynamic_supervisor.py (the conditional fill_slots budget, lane 1)
summary:    THE HEADLINE CLAIM IN THIS DOCUMENT WAS WRONG AND IS CORRECTED BELOW. It said all six cards draw. FOUR draw. The two bound to PERIOD_SERIES - finBurnRate and finPerformanceIndices - mount and REFUSE with `NOTHING TO DRAW / no numeric amount on any row`. I measured which archetype the renderer SELECTED and reported it as the card appearing, which is the exact substitution the bar forbade: routing standing in for the card. ROOT CAUSE, a binding error of mine rather than a payload gap: PERIOD_SERIES is Engine P's COST CURVE wearing a generic name - its row contract requires capex/expense/total plus cap/over_cap/overage and its component hardcodes stacked capex+expense bars against a cap column. Both fin producers are missing SIX of the seven required keys, so no field addition could have made the binding work; CPI/SPI are dimensionless ratios with no cap, no overage and no total. THE SEAL THAT SHOULD HAVE CAUGHT IT checked one producer per archetype, all seven of them Engine P's, so a SECOND producer on an EXISTING archetype was unguarded - the same remembered-population defect this file had already fixed once for archetypes. Now derived from the capability table, with both bad bindings recorded as exemptions a second test PROVES still fail. Everything else stands: routing, entitlement, the fill_slots fix, the projection fix, and four cards drawing with zero generative renders.
---

# Six of six satisfy every declared refusal condition — pending a human look

> ## RE-MEASURED 2026-09-02, after MULTI_SERIES and the stale-row delete
>
> **This time "draw" is measured as the payload satisfying cortex's DECLARED REFUSAL
> CONDITIONS, evaluated field by field — not the archetype label.** That substitution is what
> made the earlier headline wrong, and the correction below is left standing.
>
> | question | archetype | verdict against the contract |
> |---|---|---|
> | estimate at completion | FORECAST_MEASURE | eac=14,152,380.95 method=CPI formula=`EAC = BAC / CPI` |
> | why are we over budget | VARIANCE_TREE | root=Notional Program Meridian variance=−1,130,000 children=3 |
> | what is the burn rate | **MULTI_SERIES** | 6 periods × 2 series (Spent/USD, Planned/USD) |
> | what is the funding status | SHORTFALL_GRID | 18 cells |
> | CPI and SPI over time | **MULTI_SERIES** | 6 periods × 2 series (CPI, SPI — **no unit**) |
> | what is driving the cost variance | CONTRIBUTION_RANKING | 3 contributors, top = Integration and Test −1,100,000 |
>
> Every declared refusal condition was evaluated against the real payload: rows present,
> series declared, every declared series numeric in at least one row, units consistent,
> method and value present on the forecast, single root carrying a variance and a name,
> contributors carrying names and contributions, cells carrying subject and required amount.
>
> **The CPI/SPI card declares NO unit and the burn card declares USD** — the per-series unit
> working as designed, and the reason accommodation A2 could be retired rather than sealed.
>
> ⚠️ **THIS IS STILL NOT "A PERSON SAW A CARD."** It is the strongest server-side proxy
> available — the component's own refusal conditions, applied to the bytes it will receive —
> and it is exactly one step short of the claim. The last time this document said six, the
> gap between "the payload is right" and "the card rendered" is where the error lived.
> **Chris opens the UI; until then this says six of six SATISFY, not six of six DREW.**

# ~~All six finance cards draw~~ — FOUR draw. Correcting my own headline.

> ## CORRECTION 2026-09-02
>
> **This document claimed all six cards draw. Four do.** `finBurnRate` and
> `finPerformanceIndices` mount and refuse:
>
> ```
> NOTIONAL PROGRAM MERIDIAN — NOTHING TO DRAW
> no numeric amount on any row
> ```
>
> **The instrument error is the one the bar was written about.** I read `archetype=PERIOD_SERIES`
> out of the response stream and recorded it as the card drawing. Selecting an archetype and
> rendering a card are different events, and the dispatch said in as many words: *no "routing
> works" standing in for "the card appeared."* I substituted exactly that, on the claim it was
> written to prevent — and published it as `status: closed`.
>
> A card that mounts and refuses is INDISTINGUISHABLE from one that draws, if what you measure is
> the archetype label. The refusal text was in the artifact the whole time and my harness
> extracted the one field that could not see it.
>
> Found by the lane that owns the renderer, from the user's report. Not by me, and not by any
> seal here.

## The root cause: the binding was never satisfiable

**`PERIOD_SERIES` is Engine P's cost curve wearing a generic name.** Its row contract:

```
PeriodSeriesRow: period, capex, expense, total, cap, over_cap, overage   (all required)
PeriodSeries.tsx: <Bar dataKey="capex" stackId="a">  <Bar dataKey="expense" stackId="a">
                  table columns: period | total | cap | over by
```

Measured against both producers:

| producer | missing |
|---|---|
| `fin_burn_rate` | `cap, capex, expense, over_cap, overage, total` — **6 of 7** |
| `fin_performance_indices` | `cap, capex, expense, over_cap, overage, total` — **6 of 7** |

**So this is not a payload gap and no field addition fixes it.** Emitting `total` would satisfy
the validator and still draw the wrong chart — empty capex/expense bars and a cap column. For
CPI/SPI it would be worse than wrong: they are DIMENSIONLESS RATIOS, and a ratio in a field called
`total` beside an "over by" column is a false claim about the number. That is the same species as
the generative-renderer violation — a plausible-looking card asserting something untrue about a
finance figure — which is why the "just emit total" interim is refused here.

**I chose this archetype because its NAME sounded right**, and my own bindings packet compared the
payload against the projector's passthrough fields (`rows`, `scope_label`, `value_unit`) rather
than against cortex's row contract, where `capex`/`total`/`cap` live. One registry checked, and
not the one that draws — the same error as seam 11, four days earlier.

## The seal that should have caught it, and why it did not

`test_the_producer_emits_every_key_its_archetype_requires` already encodes the exact requirement.
Its producer list is **one lambda per archetype, all seven of them Engine P's**:

```python
("PERIOD_SERIES", lambda s: measures.plan_cost_curve(s)),
```

**So a SECOND producer binding to an EXISTING archetype is unguarded.** This file had already
fixed the remembered-population defect once — for archetypes, after a hand-written list missed
SHORTFALL_GRID — and left the producer population remembered. Fixed now: fin bindings are derived
from `PRESENTATION_CAPABILITIES`, so a seventh verb inherits the guard, and both bad bindings are
recorded as exemptions that a second test PROVES still fail.

## What stands, unchanged

Routing, entitlement, verb execution, the ontology classes, the archetype declarations, lane 1's
fill_slots fix, the projection fix, and **four cards drawing with zero generative renders** —
including the FORECAST_MEASURE carrying the $14.2M EAC, which was the ruling-violation repair.

---

## Original document follows, with its 6/6 table left standing as written

# All six finance cards draw

**The bar, set 2026-09-01:** *"by morning, either all six cards demonstrably draw in sandbox
through the real path, or a named list of exactly which seam stops each one — no 'routing works'
standing in for 'the card appeared.'"*

**Measured 2026-09-02, six questions as alice, persona `PROGRAM_FINANCE_ANALYST`, domain
`PROGRAM_FINANCE`, through `/interview/stream`:**

| question | verb routed | conf | card drawn |
|---|---|---|---|
| estimate at completion, using CPI | `finEacCalculation` | 0.92 | **FORECAST_MEASURE** |
| why are we over budget | `finVarianceAnalysis` | 0.96 | **VARIANCE_TREE** |
| what is the burn rate | `finBurnRate` | 0.96 | ~~PERIOD_SERIES~~ **REFUSES** |
| what is the funding status | `finFundingStatus` | 0.96 | **SHORTFALL_GRID** |
| CPI and SPI over time | `finPerformanceIndices` | 0.96 | ~~PERIOD_SERIES~~ **REFUSES** |
| what is driving the cost variance | `finVarianceDrivers` | 0.86 | **CONTRIBUTION_RANKING** |

```
presentation_path, all six runs after the roll : archetype-hardened  (6/6)
generative renders (BAML DesignUI)             : 0
fill_slots timeouts                            : 0
```

The lone `fallback-designui` in the log window predates the pod start at 17:18:14Z; every run
from 17:22 to 17:44 is hardened.

## The eleven seams, and who owned each

| # | seam | owner |
|---|---|---|
| 1–7 | routing, entitlement, verb execution, payload conformance, ontology classes, archetype declaration, HUD naming | verified green |
| 8 | `fin:` missing from two CURIE prefix maps → Contract D refused six registrations | **mine** |
| 9 | `fill_slots` 20s budget applied to spoken-**mandatory** slots → every question became an ask | lane 1 |
| 10 | four verbs hung off subjects no question names → `compatible_count=2` | **mine** |
| 11 | three minted archetypes never projected → generative fallback | **mine** |

**Four of the eleven were mine, and seam 11 is the one I would least like to have shipped.**

## Seam 11, stated plainly, because it is the instructive one

`fin:ForecastMeasure`'s own `rdfs:comment`, which I wrote:

> *"DETERMINISTIC BY REQUIREMENT — a forecast must not be routed through a generative renderer."*

ADR-0045's amendment rejected `ASSET_STATE_METRIC` for precisely that reason. And the measured
behaviour before this fix:

```
render_ui: no hardened renderer for archetype=FORECAST_MEASURE; falling back to legacy DesignUI.
→ EAC $14,152,380.95, VAC -$2,152,380.95, CPI 0.848 ... rendered as CHART_WIDGET label/value pairs
```

**The number survived the trip.** That is the whole problem: the figures were correct, the card
was populated, and nothing anywhere reported that a finance forecast had been through a language
model. A wrong number would have been safer, because someone would have seen it.

I declared these three in the ontology, added them to `capability_admission`, bound them in
`PRESENTATION_CAPABILITIES`, minted their classes under `mesh:Archetype` and registered them into
cortex's menu — **five registries** — and never added the sixth, which is the one that draws.

## What made the diagnosis expensive, and the one thing worth carrying forward

**All eleven seams produced the same card.** A missing prefix entry, a timeout, a coverage gap, a
grounding failure and an absent renderer are five different problems in four different services
with four different owners, and every one of them read as `Knowledge Document · No content
available`.

The consequence is not merely slow diagnosis. **Fixing seam 8 changed nothing observable**, and
"I fixed it and nothing changed" is evidence *against* a correct fix. Without the row counts
(23→29), a direct probe of the selector (6/6, `source=registered`), and a pre-registration written
before the run, the honest reading would have been to re-open a repair that was already right.

That is filed as `[[a-fallback-that-absorbs-every-failure-reports-none]]`, and its point stands
independent of finance: **the discriminating information already exists at all three layers and is
thrown away before the card.** `X-Presentation-Path` told seams 8 and 11 apart the whole time.

## Method notes, kept because they were nearly failures

* **The prereg earned itself three times.** P3 predicted the cards would *not* draw after the
  subject widening, because seam 9 was untouched — so an unchanged symptom could not be read as
  that change failing.
* **A seal caught seam 11's fix.** `test_every_projected_archetype_has_a_producer_case` failed the
  moment the three entries landed, because it enumerates from the projector's own table rather
  than a remembered list. Three producer conformance cases were owed and are now written.
* **Two instrument failures caught before publication**, both by the uniform-extreme tell:
  `SUBCLASS_OF` vs `subClassOf` (two invariants at exactly 0), and a flat envelope where
  `MeasureRequest` nests under `params` (6/6 identical refusals).
* **An invariant moved next to someone else's delete.** Verb edges went 8→10 the same day Lane 1
  removed 58 rows; it was my subject widening, and it was flagged as mine *before* scoring
  anything.

## Still open

* **The recall gap:** `what is our burn rate` cannot ground correctly, because
  `fin:PerformanceMeasurementBaseline` is not in its candidate set. `fin:FundingLine` owns the
  money-depletion language (*"run out of money"*) while PMB claims only *"the planned spread of
  budget over time"* — nothing about the rate at which money leaves. A definition change, and it
  needs a prime.
* **The `/resolve` scoping escape** (`are we getting more efficient` → 122 candidates, zero
  `fin:`, under an explicit single-domain scope) — accepted by lane 1.
* **`_PLANNING_ARCHETYPES` is mis-named** now that it holds finance archetypes; the rename is
  filed rather than ridden in on a correctness fix.
* **The empty-`{}` residue** on the fill_slots fix, named by lane 1 in its own docstring: a longer
  budget makes the timeout rare, it does not make `{}` honest.
