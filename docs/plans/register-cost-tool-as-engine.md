---
id:         register-cost-tool-as-engine
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
ruled-by:   ADR-0045 (the stamped engine template) · ADR-0049 §3 option A + Ruling 4 (what an inner call owes) · ADR-0047 §3 (the exportable-modules requirement, now designed in rather than hoped for)
code-site:  setup/ontologies/cost_extension.ttl (new), agent_fleet/cost_agent/ (new engine), helm/invincible-agent/values.yaml + templates/{engines,configmap,secrets}.yaml + NOTES.txt + Chart.yaml, setup/prime_databases.py (manifest entry), tests/test_endpoint_gating_manifest.py + docs/architecture/endpoint_gating_manifest.yaml
summary:    BUILD engine-cost — an ORIGINAL implementation of the per-lot cost-accounting concept on the ADR-0045 pattern, notional data. PREMISE CORRECTED 2026-09-02 — filed as "register an existing external tool", but no such tool exists in this workspace to wrap, so this is a BUILD FROM SPECIFICATION and the module-isolability FORK IS RETIRED (nothing foreign to refactor; exportability is designed in, so ADR-0047 §3's premise inverts from hope to design). Five cost categories (labor split touch/support/SEPM, material, other-direct, warranty, contracts) over numbered production lots, a deterministic pricing composition base->fringe->overhead->G&A->cost-of-money->profit->price, and a fiscal-year rate table carrying a VINTAGE. Six verbs declared before building. GATES TWO ADR CHAINS — affordability's third source under ADR-0049 option A, and the computation ADR-0047's package carries. ONE GENUINELY NEW ARCHETYPE — the price composition is a waterfall/stack nothing existing renders. Mandatory slots lot and rate_vintage, the latter because a price without its rate vintage is the EAC-without-method ambiguity and refuses the same way.
---

# Build `engine-cost` — per-lot cost accounting, original implementation

> ## PREMISE CORRECTED 2026-09-02 — this is a BUILD, not a registration
>
> **This packet was filed as "register the existing cost-estimation tool as a mesh engine",
> assuming an external codebase to wrap.** A survey of the workspace found no such tool, and the
> lane stopped before §0 rather than guessing which repository to import from — guessing would have
> produced a real importability result against the wrong code, answering ADR-0047 §3's premise
> falsely.
>
> **The correction, from the architect: replicate the CONCEPT from its description; port nothing.**
> The specification below is derived from that description plus public cost-estimating practice,
> carrying no internal names. Nothing is copied.
>
> **THE FORK SECTION IS RETIRED, and the retraction is the reason.** The prior version carried a
> risk — *the pricing modules may not import standalone; if not, either the tool's owner pays for a
> refactor or ADR-0047 §3's byte-identical claim is revised* — with both outcomes named so the lane
> could not silently choose between them. **That risk cannot fire: there is no foreign codebase to
> isolate and nothing to refactor.** Exportability becomes a **construction constraint on code this
> lane writes** (§Construction constraint) rather than a property hoped for in code it does not own.
> **ADR-0047 §3's premise inverts from hope to design**, which is the better version.
>
> *Retired rather than deleted: a reader arriving from ADR-0047 §3 will look for the isolability
> answer, and must find that the question dissolved rather than that it was skipped.*
>
> **The packet id is unchanged deliberately.** Identity is the declared `id`, not the title —
> renaming would orphan the references in ADR-0048 §6 and this file's own gating table for a
> cosmetic gain.

**A lane's task, not an ADR.** [`docs/runbooks/adding-an-engine.md`](../runbooks/adding-an-engine.md)
is the plan — **§0 through §9, in order.** Follow it; do not re-derive it.

## Why this is board-tracked

| chain | what it needs from this |
|---|---|
| [ADR-0049](../adr/ADR-0049-cross-engine-composition-a-verb-that-needs-another-engines-data.md) | Affordability's **third source**. Under option A a composing verb calls sibling **verbs**; without this engine there is nothing to call |
| [ADR-0047](../adr/ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) / [ADR-0048](../adr/ADR-0048-customer-validation-package-first-consumer-of-computation-export.md) | The **computation the package carries** at a pinned SHA — specifically the pricing composition below |
| [ADR-0048](../adr/ADR-0048-customer-validation-package-first-consumer-of-computation-export.md) §6 | The **customer-facing format prototype**. Slice 1 builds both formats as notional-data mocks produced by the **real** packaging verb, so the format decision and the §3 measurements wait on this engine existing |

## §0 — RULED: `engine-cost`

Checked with the runbook's own grep across `helm/ agent_fleet/ src/ scripts/ tests/` — **zero hits**
for every candidate namespace. The four names, deliberately different strings:

| namespace | value |
|---|---|
| helm values key | `engineCost` |
| component / service / deployment | `engine-cost` |
| image name | `cost-agent` |
| Keycloak client id | `iagent-cost-agent` |

**`engine-c` is taken** (swarms scraper), so the single-letter form was never available — the same
collision that cost Engine F its first hour, found here before it cost anything.

## Spec — what the engine computes

**Domain: production lots.** Numbered and sequential; a mature program has many. Most per-lot verbs
take `lot` as a spoken-mandatory slot.

### Five cost categories

| category | what it carries |
|---|---|
| **Labor** | price and hours, split three ways — **touch** (direct production), **support** (indirect), **SEPM** (systems engineering / program management). Lot totals, unit rates per lot, rate comparison across lots. Touch carries regression-based hours prediction and historical-vs-forecast; SEPM carries average-hours-per-month and concurrency across overlapping lots |
| **Material** | price totals, unit price per lot, estimating-vs-actual unit price, and supplier concentration (suppliers above a threshold) |
| **Other direct costs** | price, unit price per lot, unit-price trend across lots |
| **Warranty** | price, hours, unit price per lot |
| **Contracts** | aggregate contract-related pricing |

### The pricing composition — the deterministic core

**base rate → fringe → overhead → G&A → cost of money → profit → final price**, applied per lot,
producing the full breakdown as a row set. **This is the module ADR-0047's package ships**, so it is
written importable-standalone from the first line.

### Rate and escalation management

A **rate table by fiscal year** — direct rates, indirect rates, escalation indices — feeding the
composition. **Rates carry a VINTAGE**, the same as-of discipline the fiscal calendar already gives.

### Summary views

A cross-category aggregate per lot, and lot-over-lot trending.

## The six verbs — declared before building

| verb | subject | output shape | archetype |
|---|---|---|---|
| `cost_lot_breakdown` | Lot | per-category price/hours for one lot | grid (exists) |
| `cost_unit_price_trend` | Program | unit price per lot across lots, by category | `MULTI_SERIES` (exists) |
| `cost_rate_comparison` | Lot | actual vs. estimating rates | ranked / delta shape |
| `cost_labor_composition` | Lot | touch / support / SEPM split with rates | grid |
| `cost_price_composition` | Lot | base → … → price, the full stack | **NEW — waterfall/stack** |
| `cost_rate_assumptions` | Program | the rate table at a vintage | grid |

**`cost_price_composition` is the one genuinely new archetype**, and it gets ADR-0045's
amendment treatment: **read the projection arm before assuming a fit.** If nothing takes a stacked
composition, that is a cortex build — **filed, not forced onto a lookalike whose name sounds right.**

## Mandatory slots

- **`lot`** — on every per-lot verb.
- **`rate_vintage`** — on anything forward-looking. **A price without its rate vintage is the
  EAC-without-method ambiguity**: the number is meaningless without the assumption set behind it, so
  the verb **refuses the same way** rather than defaulting to the newest table.

Kinds **hand-annotated, never inferred** (runbook §4). **The refusal contract distinguishes empty /
unavailable / unentitled** per [ADR-0049](../adr/ADR-0049-cross-engine-composition-a-verb-that-needs-another-engines-data.md)
Ruling 4 — these will be inner calls to affordability.

## Notional data, and two seals it must satisfy

One fake program, **8–10 lots**, round-number rates, obviously invented supplier names. **No real
program, lot, or supplier data enters this engine.**

1. **UNIT PRICES MUST TREND ACROSS LOTS.** A flat curve makes every trend verb vacuous while every
   test passes — Engine F's identical-CPI trap, where constant seed factors could not produce the
   trend the verb existed to show, and a demo over that data would have been indistinguishable from
   a bug.
2. **THE COMPOSITION MUST REPRODUCE THE SUM.** base → … → price must add up to the price the
   breakdown reports. A pricing engine whose stack does not sum is wrong in the one way a customer
   checks first.

## Construction constraint — exportable by design

**No config read at import. No module-level I/O. The pricing composition is a pure function of its
inputs.** ADR-0047 §3 ships these modules byte-identical to a recipient, so isolability is a
property the code is **written to have**. This replaces the retired fork: the risk is gone because
the constraint sits upstream of the code existing.

## Fences

- One engine, this repo. **No affordability vocabulary** — ADR D is unwritten.
- **No packaging work** — ADR-0047 §§1–5 are cleared to build but are a separate dispatch.
- Runbook §10's error table and the appendix's change list are the checklist on the way out. **The
  four edits outside the engine's own directory are the ones that get forgotten**, and `Chart.yaml`
  must be version-bumped or the chart publishes nothing while reporting green.

## Completion bar — falsifiable

1. **A routed question reaches the engine and returns its declared output type**, verified end to end
   (runbook §9 step 5), never by a component's self-report.
2. **Verbs and classes present in the graph BY NAME**, non-null, at the right FQDN endpoint — not by
   count, and the by-name check asserts the names match an expected set.
3. **The pricing composition imports standalone** in a clean environment with no application
   context, and **reproduces the sum** — ADR-0047 §3's precondition, demonstrated rather than hoped.
4. **Each verb's refusal contract distinguishes the three states** ADR-0049 Ruling 4 requires.
5. **The trend seal bites** — unit prices differ materially across lots, asserted rather than assumed.
