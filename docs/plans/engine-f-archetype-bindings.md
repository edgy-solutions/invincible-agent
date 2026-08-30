---
id:         engine-f-archetype-bindings
status:     open
owner:      agent
blocked-on:
repo:       cortex-ui
ruled-by:   ADR-0045 Amendment 2026-08-29 (the three rulings on this table); ADR-0042 (§2 the selector decides from the payload; the projection arm); ADR-0030 (one verb, one fixed output type)
code-site:  agent_fleet/presentation_agent/main.py (_PLANNING_ARCHETYPES, the projection arm), agent_fleet/finance_agent/measures.py (the six payloads), cortex-ui src/registry/assembleCapabilities.ts (DERIVED_BINDINGS)
summary:    THE BINDING TABLE FOR ENGINE F, produced BEFORE cortex is dispatched, with payload field names read off the running verbs and contract fields read off _PLANNING_ARCHETYPES — so the fit is demonstrated rather than asserted. RESULT IS NOT SIX BINDING ROWS. Two map cleanly (fin_burn_rate, fin_funding_status). One maps at a stated cost (fin_performance_indices — PERIOD_SERIES declares `value_unit` in its passthrough and this verb DELIBERATELY does not emit one, because CPI is a dimensionless ratio; the row field is named `amount_unit` specifically to defeat the projector's rows[0] lift, which is an accommodation nobody would find without this note). THREE ARE REAL CORTEX BUILDS, NOT BINDING ROWS: fin_variance_analysis emits a TREE (nested `contributors`) and no archetype in the projection arm takes nesting — ADR-0045 already deferred its archetype and this confirms why; fin_eac_calculation emits ONE forecast whose METHOD is half the answer and no existing archetype carries a method, while the nearest candidate (ASSET_STATE_METRIC) is an LLM renderer that would send finance figures to a fallback chain beginning at OpenRouter; fin_variance_drivers was assigned INSTANCES_BY_PROPERTY by ADR-0045, but that archetype is A FILTERED INSTANCE TABLE fed by a hand-set BFF feeder, is ABSENT from _PLANNING_ARCHETYPES entirely, and requires target/columns/row_identity/state_vocabulary that a RANKING has none of. Also records the page-load registration law as a runbook verification step: bindings reach the graph on an authenticated browser page load, never from a deploy. RULED 2026-08-29 (architect), recorded as ADR-0045's Amendment: (1) EAC gets a small DETERMINISTIC value+method+formula archetype, NOT ASSET_STATE_METRIC — build this first; (2) INSTANCES_BY_PROPERTY REFUSED for drivers, and DELTA_SET was checked before minting and does NOT generalize (the axis is inverted — N metrics x one comparison vs one metric x N entities — and ordering is meaningful in one and not the other), so a ranked-set archetype is the build, reusing DELTA_SET's CELL grammar but not the archetype and NOT its producer-formatted magnitude string; (3) variance-tree deferral confirmed with the flatten-vs-build question stated and left open, architect leaning FLATTEN (top level plus a drill-down affordance) because it composes with the elicitation surface — but that changes what the verb RETURNS and must be argued against Decision 3's one-verb-not-a-chain ruling rather than slipped in as a rendering convenience. Accommodation A2 is now SEALED (tests/finance, negative control verified).
---

# Engine F → archetype bindings, demonstrated before cortex is dispatched

**Produced 2026-08-29, before any cortex work is scoped.** Payload field names are read from the
six running verbs (`POST /measure/<fn>`, notional seed); contract fields are read from
`_PLANNING_ARCHETYPES` in `agent_fleet/presentation_agent/main.py`. Nothing here is asserted
from memory.

**The headline: this is not six binding rows.** Two are, one is with a cost that must be
written down, and **three are real cortex builds.**

---

## How a binding actually lands, because it decides what a "row" is

`_PLANNING_ARCHETYPES` maps **archetype → (payload key, passthrough fields)**. The projector:

* takes rows from `payload_key`, then `structured_data`, then `rows`;
* for each passthrough field, reads `resp.get(field)` and **falls back to `rows[0].get(field)`**;
* **carries nothing it was not given** — "nothing is defaulted, inferred or invented".

That fallback matters: **a per-row `scope_label` is lifted from row 0**, so Engine F emitting
`scope_label` per row rather than at the envelope is fine. Verified against the code, not assumed.

Only **seven** archetypes have a projection arm: `INTERVAL_TIMELINE`, `PERIOD_SERIES`,
`THRESHOLD_GRID`, `MATRIX_GRID`, `DELTA_SET`, `CANVAS_SEED`, `SHORTFALL_GRID`. **Anything else
is not a binding row**, whatever the archetype vocabulary says — which is the single fact that
turns three of ADR-0045's six assignments into builds.

---

## The table

| verb | output class | target archetype | exists? | fit |
|---|---|---|---|---|
| `fin_burn_rate` | `fin:BurnRateSeries` | `PERIOD_SERIES` | ✅ in arm | **clean** |
| `fin_funding_status` | `fin:FundingStatusGrid` | `SHORTFALL_GRID` | ✅ in arm | **clean, via accommodation A1** |
| `fin_performance_indices` | `fin:PerformanceIndexSeries` | `PERIOD_SERIES` | ✅ in arm | **fits at a cost — accommodation A2** |
| `fin_variance_drivers` | `fin:VarianceDriverRanking` | ~~`INSTANCES_BY_PROPERTY`~~ | ❌ **not in arm** | **MISFIT — build** |
| `fin_eac_calculation` | `fin:EstimateAtCompletion` | *(none)* | ❌ | **MISFIT — build** |
| `fin_variance_analysis` | `fin:VarianceDecomposition` | *(none)* | ❌ | **MISFIT — build** |

---

## The three that map

### ✅ `fin_burn_rate` → `PERIOD_SERIES` — clean, no accommodation

`PERIOD_SERIES` = `("rows", ("scope_label", "value_unit"))`.

| contract field | where Engine F puts it | value |
|---|---|---|
| `rows` | envelope `rows` | 6 rows, one per reported period |
| `scope_label` | **per row** → lifted from `rows[0]` | `"Notional Program Meridian"` |
| `value_unit` | envelope (from `measures.VALUE_UNIT`) | `"USD"` |

Row fields: `period`, `burn`, `planned`, `variance_to_plan`, `cum_burn`, `cum_planned`,
`budget_remaining`, `trailing_rate`, `trailing_periods`, `runway_periods`, `scope_label`,
`value_unit`.

`period` is the series axis and every value is an amount in one declared unit. **Nothing was
shaped to fit.** This is what a clean reuse looks like and it is the only one of the six.

### ✅ `fin_funding_status` → `SHORTFALL_GRID` — clean, but bought with accommodation A1

`SHORTFALL_GRID` = `("rows", ("value_label", "value_unit", "scope_label"))`. All three are
emitted at the envelope *and* per row.

| grid's contract field | Engine F's value | IPMDAR field carried beside it |
|---|---|---|
| `subject_id` / `subject_name` | `FL-RDTE` / *Research, Development…* | `line_id` |
| `required` | authorization ceiling | `authorized` |
| `committed` | placed under obligation | `obligated` |
| `secured` | actually paid out | `expended` |
| `shortfall` | `max(0, authorized − obligated)` | `unobligated_balance` |
| `at_risk` | `max(0, authorized − expended)` | `unexpended_balance` |
| `state` | `short` / `pledged-not-firm` / `met` | `funding_state`: `unobligated-balance` / `obligated-not-expended` / `expended` |
| `period` | `FY26-01`…`FY26-06` | — |

All three states occur in the seed, so every cell colour is exercised. **18 rows, 3 lines × 6
periods.**

### ⚠️ `fin_performance_indices` → `PERIOD_SERIES` — fits, and the cost is a contract field

| contract field | status |
|---|---|
| `rows` | ✅ 6 rows |
| `scope_label` | ✅ per row, lifted |
| `value_unit` | ❌ **deliberately absent** |

**CPI and SPI are dimensionless ratios.** `fin_performance_indices` is the one verb excluded
from `measures.VALUE_UNIT`, because stamping `"USD"` on `0.85` is a lie the producer told. The
amounts that sit beside the ratios in each row *do* have a unit, and it is carried — as
**`amount_unit`**.

> **That field is named `amount_unit` and not `value_unit` ON PURPOSE, and this note is the
> only place that fact exists.** The projector's passthrough falls back to `rows[0]`, so a row
> field called `value_unit` would have been **lifted to the card envelope and drawn as the
> series' unit** — putting a dollar sign on the ratio chart by way of a field that was only ever
> describing its secondary columns. Renaming it defeats the lift deliberately.

**The open question for cortex, and it is a question rather than a finding:** the projection arm
treats passthrough as *carry-if-present*, so omitting `value_unit` is legal at the projector.
Whether the `PERIOD_SERIES` **component** tolerates its absence is a cortex-side fact this repo
cannot see. **If it does not, the answer is not to emit a fake unit** — it is a component that
renders a unitless series, or a second archetype for ratios.

---

## The three that do not map

### ❌ `fin_variance_analysis` → nothing. **A tree, and no arm takes nesting.**

This is the one the dispatch flagged and the flag was right.

The payload is **one row that contains a tree**:

```
row = { level: "program", entity_id, entity_name, variance, share_of_root,
        bcws, bcwp, acwp, value_unit, stop_reason: "decomposed",
        contributors: [ { level: "control_account", …, contributors: [ {level: "work_package", …} ] } ],
        residual?, residual_note? }
```

Every archetype in the arm is **flat**: `rows` is an array of row objects and the projector
passes them through verbatim. **Nothing consumes `contributors`.** A `PERIOD_SERIES` or grid
component handed this draws one row with an unreadable nested cell — the shape of failure that
looks like it worked.

**This is a real cortex build**, not a binding row. ADR-0045 already deferred the archetype
("needs a payload read first"); this *is* that payload read, and it confirms the deferral. What
the component must render, which no existing one does:

* **nesting is the answer**, not a display preference — a variance without what produced it is a
  number nobody can act on;
* **`stop_reason`** per node (`decomposed` / `explained` / `leaf` / `depth`) — a tree truncated
  by the depth limit and a tree that genuinely ended look identical otherwise;
* **`residual` + `residual_note`** — the contributors below the materiality floor, so the
  children visibly sum to the parent.

### ❌ `fin_eac_calculation` → nothing. **One number whose METHOD is half the answer.**

ADR-0045 suggested "period series or single measure". Measured against the arm:

* **`PERIOD_SERIES` is wrong.** One row, and it has **no `period` field at all** (`as_of_period`
  is a stamp, not an axis). A series component drawing a single point with no axis is a chart of
  nothing.
* **`ASSET_STATE_METRIC` is worse, and this is the important part.** It is in
  `KNOWN_ARCHETYPES` but **not in the projection arm** — it dispatches to `b.RenderAsMetric`, a
  **BAML/LLM renderer**. The deterministic projection arm exists precisely to bypass that path,
  whose measured costs were *31–59s per card* and *portfolio funding figures sent to a fallback
  chain whose first entry is OpenRouter*. **Routing an EAC through it would send program cost
  forecasts to an external model.** Tolerable for notional data; exactly the wrong default for
  the real finance data ADR-0045 Decision 5 contemplates this engine eventually reading.

The row is `eac`, `vac`, `etc`, `bac`, `bcws`, `bcwp`, `acwp`, `cpi`, `spi`,
`percent_complete`, `as_of_period`, `reported_periods`, **`method`**, **`formula`**,
`program_id`, `program_name`, `scope_label`, `value_unit`.

**`method` and `formula` are load-bearing and no existing archetype has anywhere to put them.**
A card that draws `14,152,381` without *"CPI-based, EAC = BAC / CPI"* beside it reproduces
exactly the ambiguity the mandatory method slot exists to refuse — the refusal would be enforced
at the router and then undone at the card. **A deterministic single-measure-with-provenance
archetype is the build**, and its non-negotiable field is the method.

### ❌ `fin_variance_drivers` → `INSTANCES_BY_PROPERTY` is the wrong archetype. Twice over.

ADR-0045 assigned this and the assignment does not survive contact.

**1 — It is not in the projection arm.** `INSTANCES_BY_PROPERTY` is assembled by a hand-set
feeder at the BFF (`src/iagent/gateway.py:1059`, `instances_by_property_dashboard`) which
**hard-sets its own archetype**. The neighbouring comment in that same file names copying it as
re-opening `archetype-chosen-before-data` *at the BFF, one hop from where it was closed*. So
there is no mechanical row to add.

**2 — The semantics are a different question.** Its schema
(`docs/reference/pcn-dashboard-payload-schema.md`) defines it as *"a table of INSTANCES of class
C in domain D, **FILTERED by property P**"*, and requires:

| its required field | what a driver ranking has |
|---|---|
| `target.{domain, class, filter_property, filter_value}` | **no filter property** — nothing is being filtered |
| `state_vocabulary` | **no value set** — contribution is continuous, not enumerable |
| `columns[].from` (an ontology property per column) | `contribution` is **computed**, not a property of the instance |
| `row_identity.{iri, display_from_local_name}` | ids are `WP-3101`, not IRIs |
| `rows[]` — order is not meaningful | **order IS the answer** |

A ranking's content — `rank`, `share_of_total`, `favourable`, a signed `contribution` — has no
home in a filtered-instance table, and the table's framing fields have no source in a ranking.

> **I emitted `instance_id`, `instance_label`, `property_label` and `value` on every row as
> "the archetype's generic keys". That was written against my assumption of the archetype, not
> against its schema, and it is wrong.** They are harmless (they duplicate `entity_id`,
> `entity_name` and `contribution`) and they are left in place *only* until this is ruled,
> because removing them now would presume the answer. **They are not evidence of a fit.**

The honest target is a **ranked-contribution archetype**: signed magnitudes ordered by absolute
size, each with its share, the favourable tail visible, and `withheld_contributors` /
`withheld_contribution` when `top_n` truncates.

---

## Accommodations, recorded as design decisions

**Reuse sometimes costs a field. The next engine's author needs to know that, and neither of
these is visible from the code alone.**

**A1 — `fin_funding_status` carries TWO vocabularies per cell.** Six duplicated fields
(`required`/`authorized`, `committed`/`obligated`, `secured`/`expended`, plus
`shortfall`/`unobligated_balance`, `at_risk`/`unexpended_balance`, `state`/`funding_state`).

*Why:* the renderer colours on `state`, whose three values are the planning grid's own. Emitting
finance-native state strings would leave the card **with no colour at all**, and fixing that
means editing a registry in another repository. *The cost:* every cell says
**`pledged-not-firm`** about money that is not pledged — planning's word for a finance condition
properly called *obligated-not-expended*, which is why the IPMDAR name rides beside it. **The
duplication is the price of not minting a fourth grid** (ADR-0045 Decision 3), and it is the
right trade — but it is a price, not a free reuse.

**A2 — `fin_performance_indices` renames a field to DEFEAT a contract's lift.** **SEALED
2026-08-29** by `test_indices_rows_never_name_a_field_value_unit`, with a negative control run:
renaming the field back to `value_unit` turns the seal red. A comment was not enough — this is
the shape a well-meaning cleanup destroys silently, so the reason is encoded where the tidy-up
meets it. `amount_unit`
instead of `value_unit`, so the projector's `rows[0]` fallback cannot promote a currency onto a
ratio card. **This is the least discoverable decision in the engine**: it looks like a naming
inconsistency, and reverting it to `value_unit` for tidiness would silently put a dollar sign on
CPI. It is commented at the emit site and recorded here.

**Not an accommodation, stated so it is not mistaken for one:** `scope_label` per row rather than
at the envelope. The projector lifts it from `rows[0]` by design.

---

## RULED 2026-08-29 — recorded as ADR-0045's Amendment

The three misfits were ruled by the architect; the amendment carries the reasoning and this
packet is the payload read it rests on. In build order:

1. **`fin_eac_calculation` → a small DETERMINISTIC archetype carrying value + method + formula.**
   `ASSET_STATE_METRIC` is refused on both grounds argued below — it is outside the projection
   arm and dispatches to an LLM renderer, and a card that drops the method **undoes at the card
   the refusal the router just enforced.** Smallest build, clearest need, do it first.
2. **`fin_variance_drivers` → a ranked-set archetype.** `INSTANCES_BY_PROPERTY` refused.
   **`DELTA_SET` was checked before minting, per the ruling, and does not generalize** — see
   the comparison added below. Reuse its **cell grammar**, not the archetype.
3. **`fin_variance_analysis` → deferral CONFIRMED, design question OPEN.** Either a
   hierarchical archetype, or flatten at the engine to a top level plus a drill-down
   affordance. **The architect leans flatten**, because it composes with the elicitation
   surface rather than requiring a new one — but flattening changes what the verb RETURNS,
   which is a change to Decision 3's *one verb, not a chain* and must be argued as such.
   **Nothing is built for either until that is settled.**

### `DELTA_SET` checked before minting — it does NOT generalize

| | `DELTA_SET` (`plan_diff`) | a driver ranking |
|---|---|---|
| axis | **N metrics**, one comparison | **one metric**, N entities |
| ordering | unordered — a set | **ordering is the answer** |
| share of a whole | none | `share_of_total`, tail must be visible |
| magnitude | a **producer-formatted display STRING** (`"-$1.2M in FY26-Q1"`) | raw signed number + `value_unit` |

**The axis is inverted, and that is not a field that can be added.** But the *cell* grammar is
close — `delta`/`direction`/`affected` map onto `contribution`/`favourable`/`entity_name`, so
the ranked-set archetype should reuse that vocabulary and the two will read as one system.

> **Carried into that build as a caution:** `DELTA_SET`'s `magnitude` is display text the
> PRODUCER formats. Engine F emits raw numbers plus `value_unit` and leaves formatting to the
> renderer. **Do not copy the string habit** — a producer formatting display text is a
> presentation decision at the producer, which is the boundary ADR-0042 §2 draws.

## What is being asked of cortex

**Two binding rows, now:** `fin:BurnRateSeries → PERIOD_SERIES`,
`fin:FundingStatusGrid → SHORTFALL_GRID`.

**One binding row plus one question:** `fin:PerformanceIndexSeries → PERIOD_SERIES` — does the
component tolerate an absent `value_unit`? If not, that is a component change, **never** a fake
unit from the producer.

**Three builds, in the order their evidence supports:**

1. **ranked-contribution** (`fin_variance_drivers`) — smallest, most reusable, and the one
   another engine is likeliest to want next;
2. **single-measure-with-method** (`fin_eac_calculation`) — carries ADR-0045's demo beat, and
   must be deterministic rather than `ASSET_STATE_METRIC`'s LLM path;
3. **nested-decomposition** (`fin_variance_analysis`) — largest, and the one ADR-0045 already
   deferred pending exactly this read.

**Nothing should be built from this packet alone**; it is the payload read those builds start
from, so they begin with evidence rather than a blank page.
