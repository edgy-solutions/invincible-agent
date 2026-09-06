---
status: ROWS WRITTEN AND SEALED — awaiting a page-load registration and six routed questions
date: 2026-09-05
engine: engine-cost
---

# Cost card bindings — seven rows, one refusal in writing

**Routing worked; cards did not exist.** Two different claims, and only the first was proven.
Every cost answer routed correctly, produced its output, and would have rendered as
*"Knowledge Document — No content available"* — exactly where finance was before its rows landed.

## The part a row count understates

**A binding row alone renders nothing.** CONTRIBUTION_RANKING draws `entity_id` /
`entity_name` / `contribution`; a payload carrying only `category` and `price` has, to the
component, **no axes at all**. That is the defect that produced three blank cards in one morning
on the planning side — correct on both sides, wrong only in the seam, visible only in a browser.

So the work was seven rows **and** seven producers taught to speak their archetype. The pattern
is Engine F's and so is its reason: emit the generic keys **beside** the domain names, because
*"renaming the domain fields to fit a renderer is the translation layer ADR-0045 refused at the
ontology layer."* Money stays an exact Decimal string in the domain field and appears as a float
in the generic one — sealed to agree to the cent.

## The bindings

| verb | archetype | why |
|---|---|---|
| `cost_lot_breakdown` | CONTRIBUTION_RANKING | buckets contributing to one lot's cost; hours ride along as a carried quantity |
| `cost_unit_price_trend` | MULTI_SERIES | **the period is the lot**, because a lot is when the money was spent |
| `cost_labor_composition` | CONTRIBUTION_RANKING | touch/support/SEPM as shares of worked effort |
| `cost_rate_assumptions` | MULTI_SERIES | six factors over the vintages they were set at — a rate table read as data rather than as a spreadsheet |
| `cost_rate_comparison` | **DELTA_SET** | see the axis test |
| `cost_category_breakdown` | CONTRIBUTION_RANKING | share and movement, not amount |
| `cost_supplier_concentration` | CONTRIBUTION_RANKING | order *is* the answer here |
| `cost_price_composition` | **none** | refused in writing — see below |

## The axis test: `cost_rate_comparison` → DELTA_SET, not CONTRIBUTION_RANKING

DELTA_SET's contract opens: ***"It renders a COMPARISON, never a state."*** That is this verb
exactly — applied against estimating, factor by factor.

CONTRIBUTION_RANKING fails in four concrete places, the same form of test its own contract used
against DELTA_SET in the other direction:

1. **`entity_id` would carry a METRIC NAME.** Fringe is a factor, not an entity — the
   borrowed-name defect that contract explicitly refuses.
2. **`contribution` would contribute to nothing.** Rates do not sum to a total.
3. **`share_of_total` has no meaning at all.** There is no total to take a share of.
4. **Order is the sequence in which factors are STRUCK**, not a ranking. Rendering it as one
   would assert that Fringe outranks Profit.

Two things DELTA_SET requires that the measure now owns rather than the renderer:

- **`direction` is a judgement.** The contract is explicit that inferring it from the sign of
  `delta` would call a rising capability level a degradation. A rate above estimate raises the
  price, so it is `degraded` — and zero is `neutral`, which a sign test cannot produce.
- **`affected` names the composition steps the factor feeds.** A required field with nothing in
  it is the declared-but-unwired shape; this avoids it with fact.

**And `affected` came out empty for Escalation** — caught by the seal that refuses an empty
list, not by reading. Escalation has no `rate_key` because it is **not a step**: it is applied
to the base amounts before any burden is struck. So it affects the base and, through it, every
step struck on the base. Naming only *"Base cost"* would understate it.

## The refusal: `cost_price_composition`

Its payload is an **ordered walk** — each step names the `basis` it was struck on and carries a
`running_total`, and the order is a sequence in which each step's basis is the previous step's
result.

CONTRIBUTION_RANKING is the closest fit and fails on **the two fields that carry the whole
claim**: `basis` and `running_total` have no slot, and they are what proves overhead was struck
on labor-plus-fringe rather than on labor. Rendering it as a ranking would also assert that
Profit outranks Base cost, which is not a statement anyone made.

**A `STEP_LADDER` archetype is the right answer** — it is the price-composition table the HTML
package already renders — and it is a cortex change, outside this lane's fence. Until it exists
the honest state is **unbound rather than mis-bound**, and a seal asserts that the refusal stays
written down beside the rows.

## The silent failure that would have swallowed all seven

`cost:` was missing from `_IRI_PREFIXES_FOR_LOOKUP`. Without it every row registers, reports
**accepted**, and never matches a payload — indistinguishable from having no binding at all.
The comment beside `fin:` warns of exactly this; it is the same defect that once refused six
finance rows. Added, and sealed.

## Two stale claims corrected

- The shared exemption *"DELTA_SET is produced only by a committed scenario diff, not by a
  measure over seed state"* is now false — `cost_rate_comparison` is a measure over seed state.
  Amended, with its conformance placed in `tests/cost/` so adding a cost verb never requires
  editing a planning test.
- `cost_unit_price_trend` called its data list `series`, which is the name MULTI_SERIES needs
  for the **declaration**. One word meaning two things in one payload is how a renderer draws
  the wrong half. Renamed to `points`; `rows` and `series` now mean what the archetype says.

## Bite-checks

| mutation | red |
|---|---|
| the `cost:` prefix removed (the silent failure) | 1 |
| a producer stops emitting `entity_id` | 1 |
| a MULTI_SERIES row loses a declared series key | 1 |
| `direction` becomes a sign test that ignores zero | 1 |
| the generic keys REPLACE the domain names | 1 |
| a binding advertises a field nobody emits | 1 |
| `PriceComposition` silently bound instead of refused in writing | 1 |

**142 cost seals green; 666 across cost + planning.**

## Owed

A **page-load registration** (genuine reload) and then the six routed questions with the
four-per-draw record. No prime is needed — `STEP_LADDER` was not minted, and every class these
rows name already exists.
