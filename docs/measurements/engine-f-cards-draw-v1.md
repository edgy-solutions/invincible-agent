---
id:         engine-f-cards-draw-v1
status:     closed
owner:      agent
blocked-on:
repo:       invincible-agent
ruled-by:   ADR-0045 (Engine F; the amendment's deterministic-renderer ruling); ADR-0017 (rendersAs); ADR-0042 §2 (the selector decides from the payload)
code-site:  agent_fleet/presentation_agent/main.py (_PLANNING_ARCHETYPES — the projected set), agent_fleet/utils/mesh_registration.py:492, src/iagent/defs/dynamic_supervisor.py (the conditional fill_slots budget, lane 1)
summary:    THE BAR IS MET. All six finance cards draw in sandbox through the real path — phrase -> BFF -> supervisor as alice -> engine-fin -> artifact -> projection -> card. 6/6 land on their intended archetype (FORECAST_MEASURE, VARIANCE_TREE, PERIOD_SERIES x2, SHORTFALL_GRID, CONTRIBUTION_RANKING), all six post-roll runs report presentation_path=archetype-hardened, and there are ZERO generative renders and ZERO fill_slots timeouts. It took ELEVEN seams, four of which were mine, and every one of them produced the identical observable — a card reading `Knowledge Document / No content available` — which is why the diagnosis cost what it did and why the discriminating-fallback packet is the most valuable thing filed alongside it. The last seam is the sharpest: three archetypes I minted were declared, admitted, bound and registered, and NEVER PROJECTED, so a $14.15M forecast was being rendered by an LLM in direct violation of the ruling written into that archetype's own definition.
---

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
| what is the burn rate | `finBurnRate` | 0.96 | **PERIOD_SERIES** |
| what is the funding status | `finFundingStatus` | 0.96 | **SHORTFALL_GRID** |
| CPI and SPI over time | `finPerformanceIndices` | 0.96 | **PERIOD_SERIES** |
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
